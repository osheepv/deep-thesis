"""真实用户全流程暴露问题的回归保护。"""

from __future__ import annotations

import json

import pytest

from application.service.uc_main_orchestration import MainOrchestration
from artifacts import ArtifactKind
from common.aicoding.enums import Degree
from common.aicoding.exception.biz_exception import BizException
from executor.base import ExecResult


class _FlowExecutor:
    def __init__(self) -> None:
        self.degraded_ring6 = False
        self.last_ring6_context = None

    def for_ring(self, ring_no: int):
        owner = self

        class _Executor:
            def execute(self, ctx) -> ExecResult:
                source = "test-double"
                if ring_no == 1:
                    payload = {
                        "candidates": [
                            {"title": "候选题目一"},
                            {"title": "作者选择的候选题目二"},
                        ],
                        "recommendation": "请作者选择",
                    }
                elif ring_no == 2:
                    payload = {"novelty_level": "HIGH", "similar_count": 0}
                elif ring_no == 3:
                    payload = {
                        "items": [
                            {"title": "纳入文献", "doi": "10.1000/included"},
                            {"title": "排除文献", "doi": "10.1000/excluded"},
                        ],
                        "summary": "候选池",
                    }
                elif ring_no == 4:
                    payload = {"verdict": "通过", "overlap_count": 0}
                elif ring_no == 5:
                    payload = {
                        "theme": "作者选择的候选题目二",
                        "chapters": [
                            {"level": 1, "number": "第1章", "title": "绪论"},
                            {"level": 1, "number": "第2章", "title": "实验结果"},
                        ],
                    }
                elif ring_no == 6:
                    owner.last_ring6_context = ctx
                    if owner.degraded_ring6:
                        payload = {
                            "chapters": [{
                                "chapter_no": 1,
                                "chapter_title": "绪论",
                                "content": "本节梳理第 2 个关键环节。",
                                "word_count": 15,
                            }],
                            "total_words": 15,
                            "used_refs": [],
                            "used_result_ids": [],
                        }
                        source = "mock"
                    else:
                        marker = (
                            "[[BOOKMARK:TABLE-4-1|表4-1 mIoU结果]] "
                            "经用户核验，mIoU为0.812 [RES-TEST] [L1]。"
                        )
                        first = marker + ("可信正文内容" * 2500)
                        second = marker + ("实验分析内容" * 2500)
                        payload = {
                            "chapters": [
                                {"chapter_no": 1, "chapter_title": "绪论", "content": first, "word_count": len(first)},
                                {"chapter_no": 2, "chapter_title": "实验结果", "content": second, "word_count": len(second)},
                            ],
                            "total_words": len(first) + len(second),
                            "used_refs": ["[L1]"],
                            "used_result_ids": ["RES-TEST"],
                        }
                        source = "test-double"
                elif ring_no == 7:
                    payload = {
                        "chapters": json.loads(ctx.draft)["chapters"],
                        "total_words": 30_000,
                        "issues_found": [],
                    }
                    source = "test-double"
                elif ring_no == 8:
                    references = list(getattr(ctx, "references", []) or [])
                    payload = {
                        "total": len(references),
                        "passed": len(references),
                        "failed": 0 if references else 1,
                        "items": [
                            {
                                "ref_title": reference.get("title", ""),
                                "ref_doi": reference.get("doi", ""),
                                "gbt7714": f"{reference.get('title', '')}[J]. 2026.",
                            }
                            for reference in references
                        ],
                        "summary": "通过" if references else "未提供参考文献",
                    }
                    return ExecResult(
                        output=json.dumps(payload, ensure_ascii=False),
                        accept=bool(references),
                        fallbackTo=None if references else 6,
                        issues=[] if references else ["未提供参考文献"],
                        evidence={"source": "test-double"},
                    )
                else:
                    payload = {"total": 1, "passed": 1, "failed": 0}
                    source = "test-double"
                return ExecResult(
                    output=json.dumps(payload, ensure_ascii=False),
                    accept=True,
                    evidence={"source": source},
                )

        return _Executor()


def _advance_to_ring6(monkeypatch) -> tuple[MainOrchestration, _FlowExecutor, str]:
    fake = _FlowExecutor()
    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor",
        fake.for_ring,
    )
    orchestration = MainOrchestration()
    task_id = orchestration.create_task(
        "论文方向", Degree.MASTER, "计算机科学", session_id="hardening"
    ).data["task_id"]
    orchestration.run_ring1(task_id)
    orchestration.select_ring1_candidate(task_id, {"candidate_index": 1})
    orchestration.confirm_ring(task_id, 1)
    orchestration.run_ring2(task_id)
    orchestration.confirm_ring(task_id, 2)
    orchestration.run_ring3(task_id)
    orchestration.curate_literature(task_id, {"included_indexes": [0]})
    orchestration.confirm_ring(task_id, 3)
    orchestration.run_ring4(task_id)
    orchestration.confirm_ring(task_id, 4)
    orchestration.run_ring5(task_id)
    orchestration.confirm_ring(task_id, 5)
    return orchestration, fake, task_id


def test_author_candidate_selection_is_required_and_projected(monkeypatch):
    fake = _FlowExecutor()
    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor", fake.for_ring
    )
    orchestration = MainOrchestration()
    task_id = orchestration.create_task(
        "论文方向", Degree.MASTER, "计算机科学", session_id="candidate"
    ).data["task_id"]
    orchestration.run_ring1(task_id)

    with pytest.raises(BizException, match="选择候选题目"):
        orchestration.confirm_ring(task_id, 1)

    selected = orchestration.select_ring1_candidate(
        task_id, {"candidate_index": 1}
    )
    assert selected.data["chosen"] == "作者选择的候选题目二"
    orchestration.confirm_ring(task_id, 1)
    artifact = orchestration.list_artifacts(task_id).data[0]
    assert artifact["payload"]["chosen"] == "作者选择的候选题目二"
    assert artifact["payload"]["selection_confirmed"] is True


def test_literature_must_be_curated_and_is_registered_in_kb(monkeypatch, tmp_path):
    monkeypatch.setenv("THESIS_KB_ROOT", str(tmp_path / "kb"))
    fake = _FlowExecutor()
    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor", fake.for_ring
    )
    from knowledge.store import KnowledgeStore

    knowledge = KnowledgeStore(tmp_path / "kb")
    orchestration = MainOrchestration(knowledge_store=knowledge)
    task_id = orchestration.create_task(
        "论文方向", Degree.MASTER, "计算机科学", session_id="literature"
    ).data["task_id"]
    orchestration.run_ring1(task_id)
    orchestration.select_ring1_candidate(task_id, {"candidate_index": 1})
    orchestration.confirm_ring(task_id, 1)
    orchestration.run_ring2(task_id)
    orchestration.confirm_ring(task_id, 2)
    orchestration.run_ring3(task_id)

    with pytest.raises(BizException, match="筛选"):
        orchestration.confirm_ring(task_id, 3)

    curated = orchestration.curate_literature(
        task_id, {"included_indexes": [0]}
    )
    assert curated.data["included_count"] == 1
    assert curated.data["excluded_count"] == 1
    docs = knowledge.list_documents("literature")
    assert len(docs) == 1
    assert docs[0]["metadata"]["title"] == "纳入文献"
    assert docs[0]["metadata"]["kind"] == "literature"


def test_empty_literature_retry_reads_newly_uploaded_material(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from knowledge.store import KnowledgeStore

    knowledge = KnowledgeStore(tmp_path / "kb")
    fake = _FlowExecutor()

    def search(context):
        items = [{"title": doc["file_name"], "reliability": "uncertain"}
                 for doc in context.kb_files if doc.get("metadata", {}).get("kind") == "literature"]
        return ExecResult(output=json.dumps({"items": items}), accept=True)

    monkeypatch.setattr("knowledge.store.get_kb_store", lambda: knowledge)
    monkeypatch.setattr("application.service.uc_main_orchestration.get_executor",
                        lambda ring: SimpleNamespace(execute=search) if ring == 3 else fake.for_ring(ring))
    orchestration = MainOrchestration(knowledge_store=knowledge)
    task_id = orchestration.create_task("Retry literature", Degree.BACHELOR, "CS", session_id="retry-kb").data["task_id"]
    orchestration.run_ring1(task_id)
    orchestration.select_ring1_candidate(task_id, {"candidate_index": 0})
    orchestration.confirm_ring(task_id, 1)
    orchestration.run_ring2(task_id)
    orchestration.confirm_ring(task_id, 2)
    with pytest.raises(BizException, match="未检索到"):
        orchestration.run_ring3(task_id)
    knowledge.save_document("retry-kb", "fixture.txt", b"test fixture", metadata={"kind": "literature"})
    result = orchestration.run_ring3(task_id)
    assert result.data["total"] == 1
    assert result.data["items"][0]["reliability"] == "uncertain"
    assert orchestration.progress(task_id).data["phase_state"] == "WAITING_APPROVAL"


def test_degraded_draft_is_rejected_and_verified_results_reach_writer(monkeypatch):
    orchestration, fake, task_id = _advance_to_ring6(monkeypatch)
    outline = orchestration._artifacts.get_active(  # noqa: SLF001
        task_id=task_id, stage_no=5, kind=ArtifactKind.OUTLINE
    )
    ledger = orchestration._artifacts.create_version(  # noqa: SLF001
        task_id=task_id,
        stage_no=6,
        kind=ArtifactKind.RESULT_LEDGER,
        payload={
            "results": [{
                "result_id": "RES-TEST",
                "metric": "mIoU",
                "value": "0.812",
                "unit": "ratio",
                "table_or_figure_id": "TABLE-4-1",
                "source_file_id": "FILE-RESULT",
                "verified_by_user": True,
            }]
        },
        dependency_ids=(outline.artifact_id,),
    )
    orchestration._artifacts.submit_auto_gate(  # noqa: SLF001
        ledger.artifact_id, passed=True, report={"verified_results": 1}
    )
    orchestration._artifacts.decide(  # noqa: SLF001
        ledger.artifact_id, approved=True, actor="author"
    )

    fake.degraded_ring6 = True
    with pytest.raises(BizException, match="降级|字数|质量"):
        orchestration.run_ring6(task_id)
    assert orchestration.progress(task_id).data["phase_state"] == "FALLBACK"

    fake.degraded_ring6 = False
    result = orchestration.run_ring6(task_id)
    assert result.is_ok
    assert fake.last_ring6_context.results[0]["result_id"] == "RES-TEST"
    assert result.data["total_words"] >= Degree.MASTER.min_word_requirement


def test_ring6_checkpoint_is_persisted_when_provider_fails(monkeypatch):
    orchestration, _fake, task_id = _advance_to_ring6(monkeypatch)

    class _FailingRing6:
        def execute(self, ctx):
            ctx.agent_plan_callback({
                "chapter_plans": [{
                    "chapter_no": 1,
                    "objectives": ["绪论目标"],
                    "suggested_refs": ["[L1]"],
                    "evidence_gaps": [],
                }],
                "agent_tool_calls": 1,
            })
            ctx.chapter_checkpoint_callback([{
                "chapter_no": 1,
                "chapter_title": "第1章 绪论",
                "content": "已完成章节 [L1]",
                "word_count": 10,
            }])
            raise RuntimeError("模拟后续章节供应商失败")

    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor",
        lambda ring_no: _FailingRing6(),
    )

    with pytest.raises(RuntimeError, match="供应商失败"):
        orchestration.run_ring6(task_id)

    checkpoint = orchestration._store.get(task_id).ring6  # noqa: SLF001
    assert checkpoint["checkpoint"] is True
    assert checkpoint["completed_chapter_count"] == 1
    assert checkpoint["chapters"][0]["chapter_title"] == "第1章 绪论"
    assert checkpoint["agent_plan"]["agent_tool_calls"] == 1


def test_ring6_agent_loop_requires_deepseek_tools_capability(monkeypatch):
    from common import llm
    from common.llm import LLMSettings

    orchestration, _fake, task_id = _advance_to_ring6(monkeypatch)
    monkeypatch.setenv("THESIS_AGENT_LOOP_ENABLED", "true")
    monkeypatch.setattr(
        llm,
        "_llm_settings",
        LLMSettings(
            api_key="test-key",
            model="deepseek-v4-flash-vision-exp",
            supports_tools=False,
            supports_vision=True,
        ),
    )

    with pytest.raises(BizException, match="未启用Tools"):
        orchestration.run_ring6(task_id)


def test_ring8_failure_can_reopen_ring6(monkeypatch):
    orchestration, fake, task_id = _advance_to_ring6(monkeypatch)
    orchestration.run_ring6(task_id)
    orchestration.confirm_ring(task_id, 6)
    orchestration.run_ring7(task_id)
    orchestration.confirm_ring(task_id, 7)
    record = orchestration._store.get(task_id)  # noqa: SLF001
    record.ring6["used_refs"] = []
    record.ring7["content"] = record.ring7.get("content", "").replace("[L1]", "")
    orchestration._store.put(record)  # noqa: SLF001
    failed = orchestration.run_ring8(task_id)
    assert not failed.is_ok

    reopened = orchestration.reopen_stage(task_id, 6, reason="补充引用")
    assert reopened.data["current_ring_no"] == 6
    assert orchestration.progress(task_id).data["current_ring_no"] == 6
    record = orchestration._store.get(task_id)  # noqa: SLF001
    assert record.ring6 is None
    assert record.ring7 is None
    assert record.ring8 is None


def test_legacy_citations_render_reference_list(monkeypatch):
    orchestration, _fake, task_id = _advance_to_ring6(monkeypatch)
    orchestration.run_ring6(task_id)
    orchestration.confirm_ring(task_id, 6)
    orchestration.run_ring7(task_id)
    orchestration.confirm_ring(task_id, 7)

    result = orchestration.run_ring8(task_id)
    assert result.is_ok
    record = orchestration._store.get(task_id)  # noqa: SLF001
    assert record.ring8["reference_entries"][0]["number"] == 1
    assert "# 参考文献" in record.ring8["rendered_content"]
    assert "纳入文献[J]. 2026." in record.ring8["rendered_content"]


def test_ring9_never_guesses_another_tasks_docx(monkeypatch):
    orchestration, _fake, task_id = _advance_to_ring6(monkeypatch)
    orchestration.run_ring6(task_id)
    orchestration.confirm_ring(task_id, 6)
    orchestration.run_ring7(task_id)
    orchestration.confirm_ring(task_id, 7)
    orchestration.run_ring8(task_id)
    orchestration.confirm_ring(task_id, 8)
    record = orchestration._store.get(task_id)  # noqa: SLF001
    record.docx = {"filename": "missing-current-task.docx"}
    orchestration._store.put(record)  # noqa: SLF001
    captured = {}

    class _Ring9:
        def execute(self, ctx):
            captured["docx_path"] = getattr(ctx, "docx_path", "")
            return ExecResult(
                output=json.dumps({"compliant": False, "issues": []}),
                accept=False,
            )

    monkeypatch.setattr(
        "application.service.uc_main_orchestration.get_executor",
        lambda ring_no: _Ring9(),
    )

    result = orchestration.run_ring9(task_id)

    assert not result.is_ok
    assert captured["docx_path"] == ""


def test_failed_job_can_reopen_before_fsm_enters_fallback(monkeypatch):
    orchestration, _fake, task_id = _advance_to_ring6(monkeypatch)
    orchestration.run_ring6(task_id)
    orchestration.confirm_ring(task_id, 6)
    assert orchestration.progress(task_id).data["phase_state"] == "NOT_STARTED"

    job = orchestration._jobs.create(  # noqa: SLF001
        task_id=task_id,
        session_id="hardening",
        operation="ring.execute",
        payload={"ring_no": 7},
        max_attempts=1,
    )
    claimed = orchestration._jobs.claim_next("worker-reopen")  # noqa: SLF001
    assert claimed is not None and claimed.job_id == job.job_id
    orchestration._jobs.fail(  # noqa: SLF001
        job.job_id,
        "worker-reopen",
        "Token 预算不足",
        retryable=False,
    )

    reopened = orchestration.reopen_stage(task_id, 6, reason="环7作业失败")
    assert reopened.data["current_ring_no"] == 6
    assert orchestration.progress(task_id).data["current_ring_no"] == 6
