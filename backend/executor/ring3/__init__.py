# -*- coding: utf-8 -*-
"""环3 文献调研执行体（M2 二期：真实检索，决策 D2）。

职责：根据选题（``ctx.theme`` / ``ctx.subject_field``）系统搜集文献，
构建证据池（题录 + 摘要 + 分类 + 可靠度 + GB/T 7714 导出）。

设计要点：
    1. 检索走真实 API（Crossref + OpenAlex，common.lit.LiteratureService），
       严禁 LLM 编造文献（学术诚信红线）。
    2. 学位分级目标数量：本科 ~30 / 硕士 50~80 / 博士 100+；
       免费 API 示例取 top N（26 条以内），完整规模标注"需订阅源补全"。
    3. 中文条目自动标记 reliability=uncertain，提示"待人工/订阅源复核"。
    4. LLM 仅用于"检索词扩展 + 摘要压缩"，不作为文献来源。
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from typing import List

from pydantic import BaseModel, ConfigDict, Field

from common.aicoding.enums import Degree, RingType
from common.citation import format_gbt7714
from common.lit import LiteratureService, LitItem, get_lit_service
from common.llm import LLMError, StructuredOutputError, get_llm_client, get_llm_settings
from common import prompt_repo
from common.agent_loop import (
    AgentLoopSettings,
    BoundedToolLoop,
    ReadOnlyTool,
    ToolLoopError,
)
from executor.base import (
    ExecContext,
    ExecResult,
    RingExecutor,
    register_executor,
)

logger = logging.getLogger("thesis.ring3")

#: 环境开关：false 时环3/环8 跳过真实检索（离线/测试），默认 true
_LIT_ENABLED = os.environ.get("THESIS_LIT_ENABLED", "true").lower() not in ("0", "false", "no")

#: 学位分级目标文献数（免费 API 单次演示检索的上限）
_DEGREE_TARGETS: dict[Degree, int] = {
    Degree.BACHELOR: 30,
    Degree.MASTER: 80,
    Degree.PHD: 100,
}
#: 每次真实检索最多取数（API 限流友好）
_API_FETCH_LIMIT = 24

#: 文献分类关键词（按标题匹配，用于证据池归档）
_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("综述", ["survey", "review", "综述", "进展", "回顾", "overview"]),
    ("理论", ["theory", "framework", "model", "理论", "框架", "模型", "形式化"]),
    ("方法", ["method", "algorithm", "approach", "方法", "算法", "网络", "架构"]),
    ("实证", ["experiment", "empirical", "dataset", "实验", "实证", "数据集", "评估"]),
]


class LiteratureItem(BaseModel):
    """证据池单条文献。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    title: str = Field(default="", description="题名")
    authors: list[str] = Field(default_factory=list, description="作者")
    year: int | None = Field(default=None, description="年份")
    venue: str = Field(default="", description="期刊/会议")
    doi: str = Field(default="", description="DOI")
    abstract: str = Field(default="", description="摘要")
    citation_count: int | None = Field(default=None, description="被引次数")
    category: str = Field(default="", description="分类：综述/理论/方法/实证")
    reliability: str = Field(default="uncertain", description="可靠度 verified/matched/uncertain")
    gbt7714: str = Field(default="", description="GB/T 7714 引用")
    urls: list[str] = Field(default_factory=list, description="链接")
    item_type: str = Field(default="article", description="article/conference/guide等")
    relevance_score: float = Field(default=0.0, description="与当前选题的词法相关度 0..1")
    relevance_terms: list[str] = Field(default_factory=list, description="命中的选题关键词")


class LiteraturePoolResult(BaseModel):
    """环3 文献调研结构化产物。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    theme: str = Field(default="", description="题目")
    subject_field: str = Field(default="", description="学科方向")
    degree: Degree = Field(default=Degree.BACHELOR, description="学位层次")
    items: list[LiteratureItem] = Field(default_factory=list, description="证据池文献清单")
    total: int = Field(default=0, description="总条目数")
    target_count: int = Field(default=0, description="学位目标数量")
    summary: str = Field(default="", description="调研说明（数据来源/可靠度/补全建议）")
    search_queries: list[str] = Field(default_factory=list, description="实际执行的检索式")


def _categorize(title: str) -> str:
    """按标题关键词规则分类。"""
    low = (title or "").lower()
    for cat, kws in _CATEGORY_RULES:
        if any(k in low for k in kws):
            return cat
    return "方法"


_GENERIC_TERMS = {
    "研究", "方法", "系统", "模型", "算法", "优化", "分析", "设计", "实现",
    "基于", "面向", "场景", "检测", "本科", "毕业", "论文", "应用", "机制",
    "study", "research", "method", "system", "model", "algorithm", "optimization",
    "detection", "based", "approach", "analysis", "design",
}
_GENERIC_PHRASES = {
    "检测算法优化研究", "算法优化研究", "技术优化研究", "系统设计与实现",
    "场景适配研究", "应用研究", "方法研究", "模型研究",
}


def _lexical_terms(text: str) -> set[str]:
    """提取中英文检索词；中文使用2~4字n-gram以避免依赖分词服务。"""
    normalized = (text or "").lower()
    terms = {
        token
        for token in re.findall(r"[a-z][a-z0-9_-]{2,}", normalized)
        if token not in _GENERIC_TERMS
    }
    for sequence in re.findall(r"[一-鿿]{2,}", normalized):
        for width in (2, 3, 4):
            terms.update(
                sequence[index:index + width]
                for index in range(max(0, len(sequence) - width + 1))
            )
    return {
        term
        for term in terms
        if term not in _GENERIC_TERMS
        and not any(term in phrase for phrase in _GENERIC_PHRASES)
    }


def _rank_by_relevance(
    items: List[LiteratureItem], theme: str, subject_field: str
) -> List[LiteratureItem]:
    """按选题相关度排序；可靠度只做小幅加分，不能替代主题相关性。"""
    query_terms = _lexical_terms(f"{theme} {subject_field}")
    if not query_terms or not items:
        return items
    title_terms = [_lexical_terms(item.title) for item in items]
    abstract_terms = [_lexical_terms(item.abstract) for item in items]
    document_terms = [title | abstract for title, abstract in zip(title_terms, abstract_terms)]
    idf = {
        term: math.log((len(items) + 1) / (1 + sum(term in doc for doc in document_terms))) + 1
        for term in query_terms
    }
    denominator = sum(idf.values()) or 1.0
    for index, item in enumerate(items):
        title_overlap = query_terms & title_terms[index]
        abstract_overlap = query_terms & abstract_terms[index]
        title_score = sum(idf[term] for term in title_overlap) / denominator
        abstract_score = sum(idf[term] for term in abstract_overlap) / denominator
        phrase_bonus = 0.08 if any(
            len(term) >= 4 and term in item.title.lower() for term in query_terms
        ) else 0.0
        reliability_bonus = (
            0.04 if item.reliability in {"verified", "matched"} else 0.0
        )
        item.relevance_score = round(min(
            1.0,
            title_score * 0.78 + abstract_score * 0.18
            + phrase_bonus + reliability_bonus,
        ), 4)
        overlaps = title_overlap | abstract_overlap
        item.relevance_terms = sorted(overlaps, key=lambda value: (-len(value), value))[:8]
    return sorted(
        items,
        key=lambda item: (
            item.item_type == "guide",
            -item.relevance_score,
            -(item.citation_count or 0),
            item.title,
        ),
    )


def _llm_expand_queries(subject_field: str, theme: str) -> list[str]:
    """LLM 扩展检索词（可选；失败回退基础检索词）。"""
    settings = get_llm_settings()
    if not (settings.enabled and settings.api_key):
        return []

    from pydantic import BaseModel as BM

    class QueryOut(BM):
        queries: list[str]

    try:
        tpl = prompt_repo.render("ring3_queries", {
            "subject_field": subject_field,
            "theme": theme,
        })
        out = get_llm_client().generate_json(
            system=tpl["system"],
            prompt=tpl["prompt"],
            model_cls=QueryOut,
            temperature=0.3,
        )
        return [q.strip() for q in out.queries if isinstance(q, str) and q.strip()][:3]
    except (LLMError, StructuredOutputError) as exc:
        logger.info("环3 LLM 检索词扩展不可用（%s），用基础检索词", exc)
        return []


def _literature_tools(
    ctx: ExecContext,
    theme: str,
    *,
    context_reads: set[str] | None = None,
    validated_queries: set[str] | None = None,
) -> list[ReadOnlyTool]:
    """环3 Agent Loop 只读工具集。"""
    obj = {"type": "object", "additionalProperties": False}
    project_memory = dict(getattr(ctx, "project_memory", {}) or {})
    context_reads = context_reads if context_reads is not None else set()
    validated_queries = validated_queries if validated_queries is not None else set()

    def read_approved_topic(args: dict) -> dict:
        context_reads.add("approved_topic")
        return {
            "theme": theme,
            "subject_field": ctx.subject_field,
            "degree": ctx.degree.value if hasattr(ctx.degree, "value") else str(ctx.degree),
        }

    def read_project_memory(args: dict) -> dict:
        context_reads.add("project_memory")
        if not project_memory:
            return {"status": "empty", "message": "当前无已批准项目记忆。"}
        terminology = list(project_memory.get("terminology", []) or [])
        decisions = [
            item for item in (project_memory.get("decisions", []) or [])
            if isinstance(item, dict) and item.get("active", True)
        ]
        return {
            "status": "found",
            "research_questions": project_memory.get("research_questions", []),
            "key_terms": [
                str(item.get("preferred_form") or item.get("term") or "").strip()
                for item in terminology if isinstance(item, dict)
                and str(item.get("preferred_form") or item.get("term") or "").strip()
            ],
            "scope_notes": [str(item.get("text", "")).strip() for item in decisions
                            if str(item.get("text", "")).strip()],
        }

    def check_relevance(args: dict) -> dict:
        title = str(args.get("title", ""))
        if not title:
            return {"error": "title不能为空"}
        from executor.ring3 import _lexical_terms, _rank_by_relevance
        from executor.ring3 import LiteratureItem as _LI
        probe = _LI(title=title)
        scored = _rank_by_relevance([probe], theme, ctx.subject_field)
        return {
            "title": title,
            "relevance_score": scored[0].relevance_score,
            "matched_terms": scored[0].relevance_terms[:5],
        }

    def validate_query(args: dict) -> dict:
        q = str(args.get("query", "")).strip()
        if not q:
            return {"valid": False, "reason": "检索词不能为空"}
        if len(q) > 200:
            return {"valid": False, "reason": "检索词过长（>200字符）"}
        terms = _lexical_terms(q)
        if not terms:
            return {"valid": False, "reason": "检索词全是通用词，无有效关键词"}
        validated_queries.add(q)
        return {
            "valid": True,
            "keyword_count": len(terms),
            "keywords": sorted(terms)[:8],
        }

    return [
        ReadOnlyTool(
            name="read_approved_topic",
            description="读取当前论文选题、学科和学位，只读。",
            parameters={
                **obj,
                "properties": {},
            },
            handler=read_approved_topic,
        ),
        ReadOnlyTool(
            name="read_project_memory",
            description="读取已批准的项目记忆（研究问题、关键词、范围），只读。",
            parameters={
                **obj,
                "properties": {},
            },
            handler=read_project_memory,
        ),
        ReadOnlyTool(
            name="check_relevance",
            description="按选题词法检查一条候选文献标题与当前选题的相关度。",
            parameters={
                **obj,
                "properties": {"title": {"type": "string"}},
                "required": ["title"],
            },
            handler=check_relevance,
        ),
        ReadOnlyTool(
            name="validate_query",
            description="校验一个检索词是否有效（非空、长度合理、含有效关键词）。",
            parameters={
                **obj,
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            handler=validate_query,
        ),
    ]


def _parse_search_strategy(content: str) -> list[str]:
    """解析Agent输出中的精化检索词列表。"""
    import json as _json
    try:
        data = _json.loads(content)
    except (ValueError, TypeError):
        # 尝试从文本中提取JSON块
        match = re.search(r"\{[^{}]*\"queries\"\s*:\s*\[[^\]]*\][^{}]*\}", content, re.DOTALL)
        if not match:
            raise StructuredOutputError("环3 Agent输出无有效JSON")
        data = _json.loads(match.group())
    if not isinstance(data, dict):
        raise StructuredOutputError("环3 Agent输出必须是JSON对象")
    queries_raw = data.get("queries", [])
    if not isinstance(queries_raw, list):
        raise StructuredOutputError("环3 Agent输出queries必须是列表")
    if any(not isinstance(query, str) for query in queries_raw):
        raise StructuredOutputError("环3 Agent输出queries只能包含字符串")
    queries = [query.strip() for query in queries_raw if query.strip()]
    if len(queries) < 3:
        raise StructuredOutputError("环3 Agent至少需要返回3条检索词")
    if len(queries) > 5:
        raise StructuredOutputError("环3 Agent最多只能返回5条检索词")
    if len(set(queries)) != len(queries):
        raise StructuredOutputError("环3 Agent输出包含重复检索词")
    return queries


def _build_search_strategy(
    ctx: ExecContext,
    theme: str,
    settings: AgentLoopSettings,
) -> dict:
    """运行有界Agent Loop生成精化检索策略。"""
    project_memory = dict(getattr(ctx, "project_memory", {}) or {})
    memory_note = (
        "存在已批准项目记忆，必须先调用read_project_memory获取研究问题。"
        if project_memory
        else "当前无已批准项目记忆。"
    )
    tpl = prompt_repo.render("ring3_agent", {
        "theme": theme,
        "subject_field": ctx.subject_field,
        "degree_label": ctx.degree.label if hasattr(ctx.degree, "label") else str(ctx.degree),
        "memory_status": memory_note,
    })
    context_reads: set[str] = set()
    validated_queries: set[str] = set()
    loop = BoundedToolLoop(
        get_llm_client().complete_with_tools,
        settings,
    )
    try:
        outcome = loop.run(
            system=tpl["system"],
            prompt=tpl["prompt"],
            tools=_literature_tools(
                ctx,
                theme,
                context_reads=context_reads,
                validated_queries=validated_queries,
            ),
            require_tool_call=True,
        )
    except ToolLoopError as exc:
        raise StructuredOutputError(f"环3检索策略Agent失败: {exc}") from exc
    queries = _parse_search_strategy(outcome.content)
    if "approved_topic" not in context_reads:
        raise StructuredOutputError("环3检索策略Agent未读取已批准选题")
    if project_memory and "project_memory" not in context_reads:
        raise StructuredOutputError("环3检索策略Agent未读取已批准项目记忆")
    unvalidated = [query for query in queries if query not in validated_queries]
    if unvalidated:
        raise StructuredOutputError(
            f"环3检索策略Agent存在未校验检索词: {unvalidated}"
        )
    return {
        "queries": queries,
        "agent_trace": outcome.trace,
        "agent_turns": outcome.turns,
        "agent_tool_calls": outcome.tool_call_count,
        "agent_context_reads": sorted(context_reads),
        "agent_validated_queries": list(queries),
    }


def _to_lit_item(it: LitItem) -> LiteratureItem:
    """LitItem → LiteratureItem（分类 + GB/T 7714）。"""
    d = it.to_dict()
    return LiteratureItem(
        title=d["title"],
        authors=d["authors"],
        year=d["year"],
        venue=d["venue"],
        doi=d["doi"],
        abstract=d["abstract"][:300],
        citation_count=d["citation_count"],
        category=_categorize(d["title"]),
        reliability=d["reliability"],
        gbt7714=format_gbt7714(d),
        urls=d["urls"],
        item_type=d["item_type"],
    )


def _kb_docs_to_items(ctx: ExecContext) -> List[LiteratureItem]:
    """会话知识库中明确标记为literature的题录进入候选池。"""
    result: List[LiteratureItem] = []
    for doc in (getattr(ctx, "kb_files", None) or []):
        if not isinstance(doc, dict):
            continue
        meta = doc.get("metadata") or {}
        if str(meta.get("kind", "")).strip().lower() != "literature":
            continue
        title = meta.get("title") or doc.get("file_name", "")
        if not title:
            continue
        reliability = str(meta.get("reliability", "uncertain")).strip().lower()
        if reliability not in {"verified", "matched", "uncertain", "discovery"}:
            reliability = "uncertain"
        result.append(LiteratureItem(
            title=title,
            authors=meta.get("authors") or [],
            year=meta.get("year"),
            venue=meta.get("venue", ""),
            doi=meta.get("doi", ""),
            abstract=meta.get("abstract", ""),
            category=_categorize(title),
            # 上传只证明文件存在，不自动证明题录或内容真实。
            reliability=reliability,
            gbt7714=format_gbt7714({"title": title, "authors": meta.get("authors") or [],
                                   "year": meta.get("year"), "venue": meta.get("venue", ""),
                                   "doi": meta.get("doi", ""), "item_type": "article"}),
            urls=[],
            item_type="article",
        ))
    return result


@register_executor
class Ring3LiteratureReviewExecutor(RingExecutor):
    """环3 文献调研执行体。

    输入：theme（当前题目）+ subject_field + degree。
    输出：证据池（文献清单 + 分类 + GB/T 7714 + 可靠度标记）。
    """

    ring_type: RingType = RingType.RING_3
    hitl_required: bool = False

    def execute(self, ctx: ExecContext) -> ExecResult:
        theme = (getattr(ctx, "theme", "") or "").strip() or f"基于{ctx.subject_field}的研究"
        if not ctx.subject_field.strip():
            raise ValueError("subject_field 不能为空")

        agent_loop_enabled = bool(getattr(ctx, "agent_loop_enabled", False))
        agent_result: dict | None = None

        # 离线/测试开关必须在任何LLM或文献源调用之前生效。
        if not _LIT_ENABLED:
            local_items = _kb_docs_to_items(ctx)
            result = LiteraturePoolResult(
                theme=theme, subject_field=ctx.subject_field, degree=ctx.degree,
                items=local_items, total=len(local_items), target_count=_DEGREE_TARGETS[ctx.degree],
                summary=(f"在线文献检索已禁用，使用已登记的 {len(local_items)} 条本地文献；上传不代表已核验。"
                         if local_items else "文献检索已禁用（THESIS_LIT_ENABLED=false），池为空；环5/6 须禁止引用。"),
            )
            return ExecResult(
                output=result.model_dump_json(indent=2),
                accept=True, fallbackTo=None, issues=["文献检索禁用，池空"],
                evidence={
                    "sources": ["knowledge_base"] if local_items else [],
                    "fetched": 0,
                    "note": "THESIS_LIT_ENABLED=false",
                    "agent_loop": {
                        "enabled": agent_loop_enabled,
                        "status": "skipped_literature_disabled",
                        "turns": 0,
                        "tool_calls": 0,
                    },
                },
            )

        if agent_loop_enabled:
            settings = get_llm_settings()
            if not (settings.enabled and settings.api_key):
                raise LLMError("环3 Agent Loop已启用，但DeepSeek不可用")
            agent_result = _build_search_strategy(
                ctx, theme, AgentLoopSettings(),
            )
            queries = agent_result["queries"]
        else:
            queries = _llm_expand_queries(ctx.subject_field, theme)
        if not queries:
            queries = [theme, ctx.subject_field, f"{ctx.subject_field} {theme}"]

        # 逐检索词真实检索（按 scope 路由标准通道；去重合并）
        svc: LiteratureService = get_lit_service()
        scope = (getattr(ctx, "scope", "") or "all")
        seen_doi: set[str] = set()
        items: List[LiteratureItem] = []
        kb_items = _kb_docs_to_items(ctx) if hasattr(ctx, "kb_files") else []
        items.extend(kb_items)  # 知识库已存文献先入池（用户下载的）
        for kb_it in kb_items:
            if kb_it.doi:
                seen_doi.add(kb_it.doi.strip().lower())
        for q in queries[:3]:
            try:
                hits = svc.search(q, max_results=_API_FETCH_LIMIT, scope=scope)
            except Exception as exc:  # noqa: BLE001
                logger.warning("检索词 %s 失败: %s", q, exc)
                continue
            for h in hits:
                key = h.doi.strip().lower() if h.doi else h.title.strip().lower()
                if key in seen_doi:
                    continue
                seen_doi.add(key)
                items.append(_to_lit_item(h))
                if len(items) >= _API_FETCH_LIMIT:
                    break

        items = _rank_by_relevance(
            items,
            theme,
            f"{ctx.subject_field} {' '.join(queries)}",
        )
        target = _DEGREE_TARGETS[ctx.degree]
        # 可靠度统计
        verified = sum(1 for it in items if it.reliability in ("verified", "matched"))
        uncertain_cn = sum(1 for it in items if it.reliability == "uncertain")
        relevant = sum(
            1 for it in items
            if it.item_type != "guide" and it.relevance_score >= 0.12
        )
        summary = (
            f"共检索 {len(items)} 条（真实 API：Crossref + OpenAlex）；"
            f"可靠命中 {verified} 条；相关度达标 {relevant} 条；"
            f"中文/低置信 {uncertain_cn} 条需人工复核。"
            f"学位目标 {target} 条——免费 API 单次演示取 top {_API_FETCH_LIMIT} 条，"
            f"完整规模需订阅源（NCPSSD/知网/万方）或人工补全。"
        )

        result = LiteraturePoolResult(
            theme=theme,
            subject_field=ctx.subject_field,
            degree=ctx.degree,
            items=items,
            total=len(items),
            target_count=target,
            summary=summary,
            search_queries=queries,
        )

        evidence = {
            "sources": ["crossref", "openalex"],
            "fetched": len(items),
            "target": target,
            "reliability": {"verified": verified, "uncertain": uncertain_cn},
            "note": "文献来源真实 API，严禁编造；中文条目待人工复核",
            "agent_loop": {
                "enabled": agent_loop_enabled,
                "status": "completed" if agent_loop_enabled else "disabled",
                "turns": int((agent_result or {}).get("agent_turns", 0)),
                "tool_calls": int((agent_result or {}).get("agent_tool_calls", 0)),
                "context_reads": list(
                    (agent_result or {}).get("agent_context_reads", [])
                ),
                "validated_queries": list(
                    (agent_result or {}).get("agent_validated_queries", [])
                ),
            },
        }

        return ExecResult(
            output=result.model_dump_json(indent=2),
            accept=True,
            fallbackTo=None,
            issues=(
                []
                if verified > 0 and relevant >= 3
                else ["可靠且相关的文献不足3条，请调整检索词或人工建池"]
            ),
            evidence=evidence,
        )
