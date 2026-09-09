# -*- coding: utf-8 -*-
"""主编排用例（UC-01~UC-04 聚合）。

将「创建论文任务 → 环1选题 → 环5大纲 → 环6撰写 → 生成 docx」串成一个可运行
最小闭环。每个步骤以 `Result[T]` 包裹；错误以 `BizException` 抛出，由上层
（controller / FastAPI handler）统一转换为 `Result.fail`。

模块边界（与 M1 / M2 / M5+M6 成员产物直接对接）：
    - M1 FSM 编排器：直接复用 `fsm.orchestrator.FsmOrchestrator`（状态推进/进度）。
    - M2 执行体：直接复用 `executor.get_executor(ring).execute(ctx)`（四字段结果，
      output 为 JSON 字符串）。
    - M5/M6 docx：经由 :class:`DocxRenderPort` 抽象端口接入，生产实现由
      :class:`RealDocxRenderer` 提供；测试可注入 mock 避免对真实 docxtpl 的依赖。
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("thesis.uc")
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from common.aicoding.dto.result import Result
from common.aicoding.enums.degree import Degree
from common.aicoding.enums.phase_state import PhaseState
from common.aicoding.exception.biz_exception import BizException
from common.aicoding.exception.error_code import ErrorCode
from common.workflow_contracts import get_stage_contract
from common.citation import format_gbt7714
from common.project_memory import validate_project_memory
from common.resume import (
    WorkspaceRevisionConflict,
    WorkspaceState,
    validate_workspace_state,
    read_revision,
)
from common.trust import (
    TrustCheckStatus,
    build_citation_trust_assessment,
    with_author_review,
)
from thesis_docx.cross_reference import normalize_target_id

from artifacts import (
    ArtifactKind,
    ArtifactOutboxProjector,
    ArtifactRegistry,
    ArtifactStatus,
    ContextManifest,
)
from evidence import (
    ClaimType,
    EvidenceLedger,
    EvidenceLedgerError,
    EvidenceRelation,
    SourceVerificationStatus,
)
from research import (
    ArgumentClaimSpec,
    ArgumentMap,
    ArgumentRole,
    ExperimentStatus,
    ResearchExecutionRegistry,
    ResearchMethod,
    ResearchProtocol,
    ResearchRegistryError,
)
from writing import (
    AutosaveDraftError,
    AutosaveDraftRevisionConflict,
    AutosaveDraftStore,
    SectionDraftGenerator,
    SectionDraftRegistry,
    SectionDraftRegistryError,
    SectionDraftStatus,
)
from jobs import (
    JobRegistry,
    JobRegistryError,
    PermanentJobError,
    Pricing,
    get_current_job_id,
)

from executor import ExecContext, get_executor
from application.service.task_store import TaskRecord, TaskStore as _TaskStore
from application.service.docx_bridge import DocxRenderPort, RealDocxRenderer
from application.service.evidence_service import EvidenceServiceMixin
from application.service.artifact_helpers import ArtifactHelpersMixin
from application.service.research_service import ResearchServiceMixin
from application.service.section_service import SectionServiceMixin
from application.service.workspace_service import WorkspaceServiceMixin
from application.service.memory_service import MemoryServiceMixin
from application.service.job_service import JobServiceMixin
from application.service.reconciliation_service import ReconciliationServiceMixin
from fsm.orchestrator import FsmOrchestrator
from fsm.repository import InMemoryFsmRepository




# =====================================================================
# 主编排用例
# =====================================================================
class MainOrchestration(EvidenceServiceMixin, ArtifactHelpersMixin, ResearchServiceMixin, SectionServiceMixin, WorkspaceServiceMixin, MemoryServiceMixin, JobServiceMixin, ReconciliationServiceMixin):
    """主编排用例。

    Args:
        fsm: M1 FSM 编排器（默认注入内存仓储的 FsmOrchestrator）。
        docx_renderer: M5/M6 docx 渲染端口（默认 RealDocxRenderer）。
        store: 任务暂存（默认进程内实例）。
    """

    # 自动草稿能力声明：只有后端、API与至少四个真实编辑面全部可用时才置为 True。
    DRAFT_AUTOSAVE_CAPABLE = True

    _JOB_OPERATIONS = {
        "ring.execute", "section.generate", "sections.generate_all", "docx.generate"
    }

    def __init__(
        self,
        fsm: Optional[FsmOrchestrator] = None,
        docx_renderer: Optional[DocxRenderPort] = None,
        store: Optional[_TaskStore] = None,
        artifact_registry: Optional[ArtifactRegistry] = None,
        evidence_ledger: Optional[EvidenceLedger] = None,
        research_registry: Optional[ResearchExecutionRegistry] = None,
        section_registry: Optional[SectionDraftRegistry] = None,
        section_generator: Optional[SectionDraftGenerator] = None,
        job_registry: Optional[JobRegistry] = None,
        draft_store: Optional[AutosaveDraftStore] = None,
        knowledge_store: Any = None,
    ) -> None:
        self._fsm = fsm or FsmOrchestrator(InMemoryFsmRepository())
        self._docx = docx_renderer or RealDocxRenderer()
        self._store = store or _TaskStore()
        if artifact_registry is None:
            if os.getenv("THESIS_TASK_STORE_MEMORY", "").lower() == "true":
                artifact_registry = ArtifactRegistry()
            else:
                artifact_path = os.getenv(
                    "THESIS_ARTIFACT_DB",
                    os.path.join(os.path.dirname(_TaskStore._default_path()), "artifacts.db"),
                )
                artifact_registry = ArtifactRegistry(artifact_path)
        self._artifacts = artifact_registry
        self._artifact_projector = ArtifactOutboxProjector(self._artifacts)
        if evidence_ledger is None:
            if os.getenv("THESIS_TASK_STORE_MEMORY", "").lower() == "true":
                evidence_ledger = EvidenceLedger()
            else:
                evidence_path = os.getenv(
                    "THESIS_EVIDENCE_DB",
                    os.path.join(os.path.dirname(_TaskStore._default_path()), "evidence.db"),
                )
                evidence_ledger = EvidenceLedger(evidence_path)
        self._evidence = evidence_ledger
        if research_registry is None:
            if os.getenv("THESIS_TASK_STORE_MEMORY", "").lower() == "true":
                research_registry = ResearchExecutionRegistry()
            else:
                research_path = os.getenv(
                    "THESIS_RESEARCH_DB",
                    os.path.join(os.path.dirname(_TaskStore._default_path()), "research.db"),
                )
                research_registry = ResearchExecutionRegistry(research_path)
        self._research = research_registry
        if section_registry is None:
            if os.getenv("THESIS_TASK_STORE_MEMORY", "").lower() == "true":
                section_registry = SectionDraftRegistry()
            else:
                section_path = os.getenv(
                    "THESIS_SECTION_DB",
                    os.path.join(os.path.dirname(_TaskStore._default_path()), "sections.db"),
                )
                section_registry = SectionDraftRegistry(section_path)
        self._sections = section_registry
        self._section_generator = section_generator or SectionDraftGenerator()
        if draft_store is None:
            if os.getenv("THESIS_TASK_STORE_MEMORY", "").lower() == "true":
                draft_store = AutosaveDraftStore()
            else:
                draft_path = os.getenv(
                    "THESIS_AUTOSAVE_DB",
                    os.path.join(os.path.dirname(_TaskStore._default_path()), "autosave.db"),
                )
                draft_store = AutosaveDraftStore(draft_path)
        self._drafts = draft_store
        if job_registry is None:
            if os.getenv("THESIS_TASK_STORE_MEMORY", "").lower() == "true":
                job_registry = JobRegistry()
            else:
                job_path = os.getenv(
                    "THESIS_JOB_DB",
                    os.path.join(os.path.dirname(_TaskStore._default_path()), "jobs.db"),
                )
                job_registry = JobRegistry(job_path)
        self._jobs = job_registry
        self._knowledge_store = knowledge_store
        self._reconciliation_issues: dict[str, list[dict[str, str]]] = {}
        self._global_reconciliation_issues: list[dict[str, str]] = []

    def delete_task(self, task_id: str) -> Result[Dict[str, Any]]:
        """删除会话（连带知识库）。"""
        rec = self._store.get(task_id)
        if rec is None:
            raise BizException(ErrorCode.TASK_NOT_FOUND, msg=f"任务不存在: {task_id}")
        self._store.delete(task_id)
        self._store.clear_workspace_task(task_id)
        self._artifacts.delete_task(task_id)
        self._evidence.delete_task(task_id)
        self._research.delete_task(task_id)
        self._sections.delete_task(task_id)
        self._drafts.delete_task(task_id)
        self._jobs.delete_task(task_id)
        template_deleted = False
        if rec.template_id:
            try:
                service = getattr(self, "_docx_service", None)
                if service is not None:
                    service._repo.soft_delete_template(rec.template_id)  # noqa: SLF001
                if rec.template_path:
                    from pathlib import Path as _Path
                    from thesis_docx.config import DocxConfig

                    target = _Path(rec.template_path).resolve()
                    config = getattr(service, "_config", None) if service is not None else None
                    upload_root = _Path(
                        config.UPLOAD_DIR if config is not None else DocxConfig.UPLOAD_DIR
                    ).resolve()
                    if target.is_relative_to(upload_root) and target.is_file():
                        target.unlink()
                        template_deleted = True
            except Exception:  # noqa: BLE001 - 模板清理失败不破坏任务删除
                logger.warning("任务 %s 的模板文件清理失败", task_id, exc_info=True)
        try:
            self._fsm.delete_task(task_id)
        except Exception:  # noqa: BLE001 - FSM 无该任务不阻塞
            pass
        # 连带删除知识库目录。兼容旧数据：若还有任务错误地共享同一 session，
        # 保留知识库，避免删除一个任务时破坏另一个任务的数据。
        knowledge_is_shared = any(
            other.session_id == rec.session_id for other in self._store.all()
        )
        if rec.session_id and not knowledge_is_shared:
            try:
                import shutil as _sh
                from knowledge.store import get_kb_store
                import os as _os
                kb_path = get_kb_store().session_path(rec.session_id)
                for sub in ("files", "notes", "meta.json"):
                    target = _os.path.join(kb_path, sub)
                    if _os.path.isdir(target):
                        _sh.rmtree(target, ignore_errors=True)
                    elif _os.path.isfile(target):
                        _os.remove(target)
            except Exception:  # noqa: BLE001
                pass
        return Result.ok(
            data={
                "task_id": task_id,
                "knowledge_deleted": bool(rec.session_id and not knowledge_is_shared),
                "template_deleted": template_deleted,
            },
            msg=(
                "会话已删除（含知识库）"
                if rec.session_id and not knowledge_is_shared
                else "会话已删除；检测到旧任务共享知识库，资料已保留"
            ),
        )

    # ------------------------------------------------------------------
    # 步骤 1：创建论文任务（UC-01）
    # ------------------------------------------------------------------
    def list_tasks(
        self, session_id: str = "", tenant_id: str = ""
    ) -> Result[List[Dict[str, Any]]]:
        """会话列表（含当前进度/学位/当前环），供前端左侧栏渲染。"""
        recs = self._store.all()
        if session_id:
            recs = [r for r in recs if r.session_id == session_id]
        if tenant_id:
            recs = [r for r in recs if r.tenant_id == tenant_id]
        items = []
        for rec in recs:
            try:
                prog = self._fsm.get_progress(rec.task_id)
                current_ring = prog.get("current_ring_no", 1)
                percent = prog.get("complete_percent", 0)
            except Exception:  # noqa: BLE001 - 状态异常仍返回
                current_ring, percent = 1, 0
            items.append({
                "task_id": rec.task_id,
                "title": rec.title,
                "degree": rec.degree,
                "current_ring_no": current_ring,
                "complete_percent": percent,
                "session_id": rec.session_id,
                "created_at": "",
            })
        return Result.ok(data=items, msg="会话列表")

    def get_task_view(self, task_id: str) -> Result[Dict[str, Any]]:
        """返回所有任务API共用的持久化任务视图。"""
        rec = self._require(task_id)
        progress = self._fsm.get_progress(task_id)
        return Result.ok(
            data={
                "task_id": rec.task_id,
                "task_no": rec.task_id,
                "title": rec.title,
                "degree": rec.degree,
                "subject_field": rec.subject_field,
                "session_id": rec.session_id,
                "tenant_id": rec.tenant_id,
                "status": progress.get("phase_state", "NOT_STARTED"),
                "current_ring_no": progress.get("current_ring_no", 1),
                "current_ring": progress.get("current_ring", "RING_1"),
                "complete_percent": progress.get("complete_percent", 0),
            },
            msg="任务查询成功",
        )

    # ------------------------------------------------------------------
    # 跨天断点续作：恢复摘要 + 工作区位置
    # ------------------------------------------------------------------
    def get_resume_summary(
        self, task_id: str, *, author_id: str = ""
    ) -> Result[Dict[str, Any]]:
        rec = self._require(task_id)
        progress = self.progress(task_id).data or {}
        artifacts = self._artifacts.list_task(task_id)
        approved_artifacts = [
            item for item in artifacts if item.status == ArtifactStatus.APPROVED
        ]
        approved_artifacts.sort(key=lambda item: (item.stage_no, item.version))
        last_approved = approved_artifacts[-1] if approved_artifacts else None
        pending_approvals = [
            {
                "type": "ARTIFACT",
                "id": item.artifact_id,
                "kind": item.kind.value,
                "stage_no": item.stage_no,
                "version": item.version,
            }
            for item in artifacts
            if item.status == ArtifactStatus.WAITING_APPROVAL
        ]
        if progress.get("phase_state") == PhaseState.WAITING_APPROVAL.value:
            pending_approvals.insert(0, {
                "type": "RING_GATE",
                "id": f"RING-{progress.get('current_ring_no', 0)}",
                "kind": "RING_CONFIRMATION",
                "stage_no": int(progress.get("current_ring_no", 0) or 0),
                "version": 0,
            })
        for draft in self._sections.list_task(task_id):
            if draft.status == SectionDraftStatus.WAITING_APPROVAL:
                pending_approvals.append({
                    "type": "SECTION_DRAFT",
                    "id": draft.section_draft_id,
                    "kind": "SECTION_DRAFT",
                    "stage_no": 6,
                    "version": draft.version,
                })

        jobs = self._jobs.list_task(task_id, limit=100)

        def _job_summary(job) -> Dict[str, Any]:
            return {
                "job_id": job.job_id,
                "operation": job.operation,
                "status": job.status.value,
                "attempt": job.attempt,
                "max_attempts": job.max_attempts,
                "tokens_used": job.input_tokens + job.output_tokens,
                "token_budget": job.token_budget,
                "updated_at": job.updated_at,
            }

        active_jobs = [
            _job_summary(job) for job in jobs
            if job.status.value in {"PENDING", "RUNNING", "CANCEL_REQUESTED"}
        ]
        recoverable_jobs = [
            _job_summary(job) for job in jobs
            if job.status.value in {"FAILED", "CANCELLED"}
        ]
        consistency_status = (
            "NEEDS_REPAIR"
            if progress.get("artifact_projection_pending")
            or progress.get("reconciliation_status") == "NEEDS_REPAIR"
            else "CONSISTENT"
        )

        ring_no = int(progress.get("current_ring_no", 1) or 1)
        draft_author = author_id or "default"
        self._refresh_autosave_staleness(task_id, draft_author)
        autosave_records = self._drafts.list_task(task_id, draft_author)
        autosaved_drafts = [draft.metadata() for draft in autosave_records]
        resumable_draft = next(
            (
                draft for draft in autosave_records
                if draft.status == "ACTIVE"
                and draft.stage_no == ring_no
                and draft.object_type in {
                    "SECTION_REVISION",
                    "RESEARCH_PROTOCOL_FORM",
                    "ARGUMENT_MAP_FORM",
                }
            ),
            None,
        )
        consistency_issues = list(progress.get("artifact_projection_issues", []) or [])
        consistency_issues.extend(
            str(issue.get("code", ""))
            for issue in (progress.get("reconciliation_issues", []) or [])
            if isinstance(issue, dict)
            and str(issue.get("code", ""))
            and str(issue.get("code", "")) != "ARTIFACT_PROJECTION_PENDING"
        )
        consistency_issues = list(dict.fromkeys(consistency_issues))
        if consistency_status != "CONSISTENT":
            reason_code = (
                "ARTIFACT_PROJECTION_PENDING"
                if progress.get("artifact_projection_pending")
                else "STARTUP_RECONCILIATION_REQUIRED"
            )
            blocking_count = max(1, len(consistency_issues))
            action = {
                "type": "REPAIR_REQUIRED",
                "label": "修复产物投影不一致后再继续",
                "ring_no": ring_no,
            }
        elif active_jobs:
            reason_code = "ACTIVE_JOB_IN_PROGRESS"
            blocking_count = len(active_jobs)
            action = {
                "type": "MONITOR_JOB",
                "label": "继续查看正在运行的后台作业",
                "ring_no": ring_no,
                "job_id": active_jobs[0]["job_id"],
            }
        elif progress.get("phase_state") == PhaseState.WAITING_APPROVAL.value:
            if progress.get("author_decision_ready") is False:
                reason_code = "AUTHOR_DECISION_REQUIRED"
                blocking_count = 1
                action = {
                    "type": "COMPLETE_AUTHOR_DECISION",
                    "label": str(progress.get("author_decision_blocker", "")) or "完成作者决定",
                    "ring_no": ring_no,
                }
            else:
                reason_code = "AUTHOR_APPROVAL_REQUIRED"
                blocking_count = max(1, len(pending_approvals))
                action = {
                    "type": "CONFIRM_RING",
                    "label": f"审阅并确认环{ring_no}产物",
                    "ring_no": ring_no,
                }
        elif resumable_draft is not None:
            reason_code = "DRAFT_RESUME_AVAILABLE"
            blocking_count = 0
            action = {
                "type": "RESUME_DRAFT",
                "label": "继续编辑未提交草稿",
                "ring_no": ring_no,
                "draft_key": resumable_draft.draft_key,
                "object_type": resumable_draft.object_type,
                "object_id": resumable_draft.object_id,
            }
        elif progress.get("phase_state") == PhaseState.FALLBACK.value:
            reason_code = "STAGE_RECOVERY_REQUIRED"
            blocking_count = max(1, len(recoverable_jobs))
            action = {
                "type": "RECOVER_STAGE",
                "label": f"修复环{ring_no}阻断项后重试",
                "ring_no": ring_no,
            }
        elif int(progress.get("complete_percent", 0) or 0) >= 100:
            reason_code = "DELIVERY_REVIEW_REQUIRED"
            blocking_count = 0
            action = {
                "type": "REVIEW_DELIVERY",
                "label": "查看最终交付文件与清单",
                "ring_no": 10,
            }
        else:
            reason_code = "READY_TO_EXECUTE"
            blocking_count = 0
            action = {
                "type": "EXECUTE_RING",
                "label": f"继续执行环{ring_no}",
                "ring_no": ring_no,
            }
        return Result.ok(data={
            "task_id": rec.task_id,
            "title": rec.title,
            "current_ring_no": ring_no,
            "current_ring": progress.get("current_ring", f"RING_{ring_no}"),
            "phase_state": progress.get("phase_state", "NOT_STARTED"),
            "complete_percent": int(progress.get("complete_percent", 0) or 0),
            "last_approved_artifact": (
                {
                    "artifact_id": last_approved.artifact_id,
                    "kind": last_approved.kind.value,
                    "stage_no": last_approved.stage_no,
                    "version": last_approved.version,
                    "updated_at": last_approved.updated_at,
                }
                if last_approved is not None
                else None
            ),
            "pending_approvals": pending_approvals,
            "active_jobs": active_jobs,
            "recoverable_jobs": recoverable_jobs,
            # 只返回草稿元数据，绝不返回 content_json、正文片段或表单全文。
            "autosaved_drafts": autosaved_drafts,
            "consistency_status": consistency_status,
            "consistency_issues": consistency_issues,
            "stop_reason_code": reason_code,
            "blocking_count": blocking_count,
            "next_safe_action": action,
            "capabilities": {
                "workspace_restore": True,
                "formal_artifact_restore": True,
                # 后端、API与四个真实编辑面均已接入。
                "draft_autosave": self.DRAFT_AUTOSAVE_CAPABLE,
            },
        }, msg="任务恢复摘要")

    def create_task(self, title: str, degree: Degree, subject_field: str,
                    template_id: Optional[str] = None, session_id: str = "",
                    tenant_id: str = "default", scope: str = "",
                    owner_user_id: str = "") -> Result[Dict[str, Any]]:
        """创建论文任务并初始化 FSM（默认停在环1）。

        Args:
            scope: 文献检索范围（english/chinese/all），空则用全局默认。
        Returns:
            含 task_id / title / degree / subject_field / current_ring 的任务视图。
        """
        scope = scope or os.getenv("THESIS_LIT_SCOPE", "all")
        if scope not in ("english", "chinese", "all"):
            scope = "all"
        try:
            state = self._fsm.create_task(
                title=title, degree=degree, subject_field=subject_field,
                template_id=template_id or "",
            )
            canonical_session_id = session_id.strip()
            if not canonical_session_id or canonical_session_id == "default":
                canonical_session_id = state.task_id
            if any(r.session_id == canonical_session_id for r in self._store.all()):
                self._fsm.delete_task(state.task_id)
                raise BizException(
                    ErrorCode.INVALID_PARAM,
                    msg="一个会话只能绑定一个论文任务，请使用新的 session_id",
                    detail={"session_id": canonical_session_id},
                )
            rec = TaskRecord(
                task_id=state.task_id, title=title, degree=degree.value,
                subject_field=subject_field, session_id=canonical_session_id,
                tenant_id=tenant_id, template_id=template_id, scope=scope,
                owner_user_id=owner_user_id,
            )
            self._store.put(rec)
            data = {
                "task_id": state.task_id,
                "title": title,
                "degree": degree.value,
                "subject_field": subject_field,
                "template_id": template_id,
                "session_id": canonical_session_id,
                "current_ring": state.ring.value,
                "status": "NOT_STARTED",
            }
            return Result.ok(
                data=data,
                msg="论文任务创建成功",
                trace_id=canonical_session_id,
                tenant_id=tenant_id,
            )
        except BizException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BizException(
                ErrorCode.TASK_STATE_INVALID, msg=f"创建论文任务失败: {exc}", detail=str(exc)
            ) from exc

    # ------------------------------------------------------------------
    # 步骤 2：解析模板占位符（UC-01b，可选）
    # ------------------------------------------------------------------
    def upload_template(self, task_id: str, file_bytes: bytes, filename: str,
                        session_id: str = "") -> Result[Dict[str, Any]]:
        """解析已上传模板的占位符，返回模板信息（可选步骤）。"""
        rec = self._require(task_id)
        try:
            docx_service = getattr(self, "_docx_service", None)
            if docx_service is not None:
                uploaded = docx_service.upload_template(
                    file_bytes,
                    filename,
                    session_id=rec.session_id,
                    task_id=task_id,
                )
                info = uploaded.model_dump()
                stored = docx_service._repo.get_template(  # noqa: SLF001 - 同一应用内持久化路径
                    uploaded.template_id
                )
                rec.template_path = str((stored or {}).get("file_path", ""))
            else:
                info = self._docx.upload_template(
                    file_bytes, filename, template_id=f"TPL-{uuid.uuid4().hex[:12].upper()}",
                    task_id=task_id, session_id=session_id,
                )
            rec.template_id = info.get("template_id")
            rec.template_name = str(info.get("template_name") or info.get("filename") or filename)
            rec.template_placeholders = list(info.get("placeholders", []) or [])
            rec.template_mapping = self._suggest_template_mapping(
                rec.template_placeholders
            )
            self._store.put(rec)
            info["mapping"] = dict(rec.template_mapping)
            return Result.ok(data=info, msg="模板解析成功")
        except BizException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BizException(
                ErrorCode.DOCX_PARSE_FAILED, msg=f"模板解析失败: {exc}", detail=str(exc)
            ) from exc

    # ------------------------------------------------------------------
    # 步骤 3：环1 选题（UC-02）
    # ------------------------------------------------------------------
    def run_ring1(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环1选题：M2 产出候选题目，等待用户确认。"""
        rec = self._require_current_ring(task_id, 1)
        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=rec.title,
            session_id=rec.session_id,
            tenant_id=rec.tenant_id,
        )
        res = get_executor(1).execute(ctx)
        if not res.accept:
            raise BizException(
                ErrorCode.FSM_ACCEPTANCE_REJECTED, msg="环1选题未通过验收",
                detail={"fallbackTo": res.fallbackTo, "issues": res.issues},
            )
        data = json.loads(res.output)
        candidates = data.get("candidates", [])
        if not candidates:
            raise BizException(
                ErrorCode.FSM_ACCEPTANCE_REJECTED,
                msg="环1没有生成可供作者选择的候选题目",
            )
        single_candidate = len(candidates) == 1
        rec.ring1 = {
            "candidates": candidates,
            "chosen": str(candidates[0].get("title", "")) if single_candidate else "",
            "selected_candidate_index": 0 if single_candidate else None,
            "selection_confirmed": single_candidate,
            "compliant": True,
        }
        self._store.put(rec)
        self._fsm.submit_execution(task_id, res.output, accepted=True)
        return Result.ok(data={"candidates": candidates, "chosen": rec.ring1["chosen"],
                               "recommendation": data.get("recommendation", "")},
                         msg="环1选题完成")

    def select_ring1_candidate(
        self, task_id: str, value: Dict[str, Any]
    ) -> Result[Dict[str, Any]]:
        """把作者选择写入任务事实，不能只停留在浏览器本地状态。"""
        rec = self._require(task_id)
        state = self._fsm.get_task(task_id)
        if state.current_ring_no != 1 or state.phase_state != PhaseState.WAITING_APPROVAL:
            raise BizException(
                ErrorCode.FSM_INVALID_TRANSITION,
                msg="只能在环1产物待确认时选择候选题目",
            )
        candidates = list((rec.ring1 or {}).get("candidates", []) or [])
        try:
            index = int(value.get("candidate_index"))
        except (TypeError, ValueError) as exc:
            raise BizException(ErrorCode.INVALID_PARAM, msg="candidate_index 必须是整数") from exc
        if index < 0 or index >= len(candidates):
            raise BizException(ErrorCode.INVALID_PARAM, msg="候选题目序号超出范围")
        chosen = str(candidates[index].get("title", "")).strip()
        if not chosen:
            raise BizException(ErrorCode.INVALID_PARAM, msg="候选题目标题为空")
        expected_title = str(value.get("title", "")).strip()
        if expected_title and expected_title != chosen:
            raise BizException(ErrorCode.INVALID_PARAM, msg="候选序号与标题不一致")
        rec.ring1["chosen"] = chosen
        rec.ring1["selected_candidate_index"] = index
        rec.ring1["selection_confirmed"] = True
        self._store.put(rec)
        return Result.ok(
            data={"chosen": chosen, "candidate_index": index},
            msg="作者选择已登记",
        )

    # ------------------------------------------------------------------
    # 步骤 3.5：环2 开题评审（UC-02 延续）
    # ------------------------------------------------------------------
    def run_ring2(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环2开题评审：真实检索相似研究 → 新颖度判定（LOW 回退环1）。"""
        rec = self._require_current_ring(task_id, 2)
        chosen = (rec.ring1 or {}).get("chosen", rec.title)
        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=chosen,
            session_id=rec.session_id,
            tenant_id=rec.tenant_id,
        )
        res = get_executor(2).execute(ctx)
        data = json.loads(res.output)
        data["compliant"] = bool(res.accept)
        rec.ring2 = data
        self._store.put(rec)
        self._fsm.submit_execution(task_id, res.output, accepted=res.accept)
        if not res.accept:
            # 评审未通过：返回错误语义（fallbackTo=1 由执行体产出）
            return Result.fail(
                code=101200,
                msg=f"环2评审未通过：{data.get('recommendation', '')}",
                data={
                    "novelty_level": data.get("novelty_level", ""),
                    "similar_count": data.get("similar_count", 0),
                    "recommendation": data.get("recommendation", ""),
                    "fallbackTo": 1,
                },
            )
        return Result.ok(data={
            "novelty_level": data.get("novelty_level", ""),
            "similar_count": data.get("similar_count", 0),
            "differ_from_prior": data.get("differ_from_prior", ""),
            "recommendation": data.get("recommendation", ""),
            "fallbackTo": None if res.accept else 1,
        }, msg=f"环2开题评审完成：{data.get('novelty_level', '')}" if res.accept else f"环2评审未通过：{data.get('recommendation', '')}")

    # ------------------------------------------------------------------
    # 步骤 3.75：环4 综述评审（UC-03 前哨）
    # ------------------------------------------------------------------
    def run_ring4(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环4综述评审：池内竞争度 + 创新点包住检查（需重评估回退环2）。"""
        rec = self._require_current_ring(task_id, 4)
        chosen = (rec.ring1 or {}).get("chosen", rec.title)
        pool = self._ensure_literature(rec, chosen)
        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=chosen,
            literature=pool,
            session_id=rec.session_id,
            tenant_id=rec.tenant_id,
        )
        res = get_executor(4).execute(ctx)
        data = json.loads(res.output)
        data["compliant"] = bool(res.accept)
        rec.ring4 = data
        self._store.put(rec)
        self._fsm.submit_execution(task_id, res.output, accepted=res.accept)
        if not res.accept:
            return Result.fail(
                code=101200,
                msg=f"环4评审未通过：{data.get('recommendation', '')}",
                data={
                    "verdict": data.get("verdict", ""),
                    "overlap_count": data.get("overlap_count", 0),
                    "recommendation": data.get("recommendation", ""),
                    "fallbackTo": res.fallbackTo,
                },
            )
        return Result.ok(data={
            "verdict": data.get("verdict", ""),
            "overlap_count": data.get("overlap_count", 0),
            "recommendation": data.get("recommendation", ""),
            "fallbackTo": None,
        }, msg="环4综述评审完成，等待确认")

    # ------------------------------------------------------------------
    # 步骤 3.7：环3 文献调研（显式入口）
    # ------------------------------------------------------------------
    def run_ring3(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环3文献调研：真实检索建池，等待用户确认。"""
        rec = self._require_current_ring(task_id, 3)
        chosen = (rec.ring1 or {}).get("chosen", rec.title)
        pool = self._ensure_literature(rec, chosen)
        if rec.ring3 is None or not pool:
            raise BizException(
                ErrorCode.FSM_ACCEPTANCE_REJECTED,
                msg="环3未检索到可用文献，禁止继续写作",
                detail={"fallbackTo": 3, "issues": ["文献池为空"]},
            )
        rec.ring3["candidate_items"] = list(rec.ring3.get("items", []) or [])
        single_candidate = len(rec.ring3["candidate_items"]) == 1
        rec.ring3["curated"] = single_candidate
        rec.ring3["included_indexes"] = [0] if single_candidate else []
        rec.ring3["excluded_items"] = []
        rec.ring3["compliant"] = True
        self._store.put(rec)
        if single_candidate:
            self._register_curated_literature(rec, rec.ring3["candidate_items"])
        self._fsm.submit_execution(
            task_id, json.dumps(rec.ring3, ensure_ascii=False), accepted=True
        )
        return Result.ok(data={
            "total": len(pool),
            "items": rec.ring3.get("items", []) if rec.ring3 else [],
            "summary": rec.ring3.get("summary", "") if rec.ring3 else "文献池为空",
            "curated": single_candidate,
        }, msg="环3文献调研完成" if rec.ring3 else "环3文献检索失败/禁用，池为空")

    def curate_literature(
        self, task_id: str, value: Dict[str, Any]
    ) -> Result[Dict[str, Any]]:
        """保存作者的纳入/排除决定，并把纳入题录登记到项目知识库。"""
        rec = self._require(task_id)
        state = self._fsm.get_task(task_id)
        if state.current_ring_no != 3 or state.phase_state != PhaseState.WAITING_APPROVAL:
            raise BizException(
                ErrorCode.FSM_INVALID_TRANSITION,
                msg="只能在环3文献产物待确认时执行筛选",
            )
        ring3 = rec.ring3 or {}
        candidates = list(ring3.get("candidate_items") or ring3.get("items") or [])
        raw_indexes = value.get("included_indexes", []) or []
        try:
            included_indexes = list(dict.fromkeys(int(item) for item in raw_indexes))
        except (TypeError, ValueError) as exc:
            raise BizException(ErrorCode.INVALID_PARAM, msg="文献筛选序号必须是整数") from exc
        if not included_indexes:
            raise BizException(ErrorCode.INVALID_PARAM, msg="至少纳入一条文献")
        if min(included_indexes) < 0 or max(included_indexes) >= len(candidates):
            raise BizException(ErrorCode.INVALID_PARAM, msg="文献筛选序号超出范围")
        included = [candidates[index] for index in included_indexes]
        included_set = set(included_indexes)
        excluded = [
            {"index": index, "item": item, "reason": "作者排除"}
            for index, item in enumerate(candidates)
            if index not in included_set
        ]
        ring3["items"] = included
        ring3["included_indexes"] = included_indexes
        ring3["excluded_items"] = excluded
        ring3["curated"] = True
        ring3["summary"] = f"候选 {len(candidates)} 条，纳入 {len(included)} 条，排除 {len(excluded)} 条"
        rec.ring3 = ring3
        self._store.put(rec)
        self._register_curated_literature(rec, included)
        return Result.ok(
            data={
                "included_count": len(included),
                "excluded_count": len(excluded),
                "items": included,
            },
            msg="文献筛选已保存并登记到项目知识库",
        )

    def _register_curated_literature(
        self, rec: TaskRecord, items: List[Dict[str, Any]]
    ) -> None:
        from knowledge.store import get_kb_store

        store = self._knowledge_store or get_kb_store()
        if not hasattr(store, "save_document"):
            return
        existing_keys = {
            str(document.get("metadata", {}).get("ring3_item_key", ""))
            for document in store.list_documents(rec.session_id)
        }
        for index, item in enumerate(items, start=1):
            key = self._literature_item_key(item)
            if key in existing_keys:
                continue
            title = str(item.get("title", "") or item.get("ref_title", "")).strip()
            doi = str(item.get("doi", "")).strip()
            authors = item.get("authors", []) or []
            if isinstance(authors, str):
                authors = [authors]
            ris_lines = ["TY  - JOUR", f"TI  - {title}"]
            ris_lines.extend(f"AU  - {author}" for author in authors if str(author).strip())
            if item.get("year"):
                ris_lines.append(f"PY  - {item.get('year')}")
            if doi:
                ris_lines.append(f"DO  - {doi}")
            ris_lines.extend(["ER  - ", ""])
            store.save_document(
                rec.session_id,
                f"ring3_{index:03d}.ris",
                "\n".join(ris_lines).encode("utf-8"),
                metadata={
                    "kind": "literature",
                    "source": "ring3",
                    "ring3_item_key": key,
                    "title": title,
                    "authors": list(authors),
                    "year": item.get("year"),
                    "doi": doi,
                    "reliability": item.get("reliability", ""),
                    "gbt7714": item.get("gbt7714", ""),
                },
            )
            existing_keys.add(key)

    @staticmethod
    def _literature_item_key(item: Dict[str, Any]) -> str:
        doi = str(item.get("doi", "")).strip().lower()
        title = str(item.get("title", "") or item.get("ref_title", "")).strip().lower()
        return f"doi:{doi}" if doi else f"title:{title}"

    # ------------------------------------------------------------------
    # 步骤 4：环5 大纲（UC-03）
    # ------------------------------------------------------------------
    def run_ring5(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环5大纲：基于选题生成章节结构，等待用户确认。"""
        rec = self._require_current_ring(task_id, 5)
        argument_maps = [
            artifact
            for artifact in self._artifacts.list_task(task_id)
            if artifact.kind == ArtifactKind.ARGUMENT_MAP
        ]
        argument_map = self._active_argument_map(task_id)
        if argument_maps and argument_map is None:
            raise BizException(
                ErrorCode.FSM_INVALID_TRANSITION,
                msg="论证图尚未获作者批准，不能生成大纲",
            )
        protocols = [
            artifact
            for artifact in self._artifacts.list_task(task_id)
            if artifact.kind == ArtifactKind.RESEARCH_PROTOCOL
        ]
        protocol = self._active_research_protocol(task_id)
        if protocols and protocol is None:
            raise BizException(
                ErrorCode.FSM_INVALID_TRANSITION,
                msg="研究协议尚未获作者批准，不能生成大纲",
            )
        chosen = (rec.ring1 or {}).get("chosen", rec.title)
        pool = self._ensure_literature(rec, chosen)
        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=chosen,
            literature=pool,
            argument_map=argument_map.payload if argument_map is not None else {},
            research_protocol=protocol.payload if protocol is not None else {},
            session_id=rec.session_id,
            tenant_id=rec.tenant_id,
        )
        res = get_executor(5).execute(ctx)
        if not res.accept:
            raise BizException(
                ErrorCode.FSM_ACCEPTANCE_REJECTED, msg="环5大纲未通过验收",
                detail={"fallbackTo": res.fallbackTo, "issues": res.issues},
            )
        outline = json.loads(res.output)
        chapters = outline.get("chapters", [])
        if argument_map is not None:
            required_sections = {
                str(item.get("section_id", ""))
                for item in argument_map.payload.get("claims", []) or []
                if str(item.get("section_id", ""))
            }
            outline_sections = {
                str(item.get("number", ""))
                for item in self._outline_leaf_nodes(chapters)
                if str(item.get("number", ""))
            }
            missing_sections = sorted(required_sections - outline_sections)
            if missing_sections:
                raise BizException(
                    ErrorCode.FSM_ACCEPTANCE_REJECTED,
                    msg="环5大纲未覆盖论证图中的全部章节位置",
                    detail={"missing_section_ids": missing_sections},
                )
        canon_hash, contract_hash = self._embed_section_contracts(task_id, chapters)
        outline["canon_hash"] = canon_hash
        outline["contract_hash"] = contract_hash
        outline_text = self._outline_to_text(chapters)
        rec.ring5 = {"outline": outline_text, "chapters": outline.get("chapters", []),
                     "theme": outline.get("theme", chosen), "compliant": True,
                     "canon_hash": canon_hash, "contract_hash": contract_hash}
        self._store.put(rec)
        self._fsm.submit_execution(
            task_id, json.dumps(outline, ensure_ascii=False), accepted=True
        )
        return Result.ok(data={"outline": outline_text, "chapters": chapters,
                               "summary": outline.get("summary", ""),
                               "canon_hash": canon_hash,
                               "contract_hash": contract_hash}, msg="环5大纲完成")

    # ------------------------------------------------------------------
    # 步骤 5：环6 撰写（UC-03 延续）
    # ------------------------------------------------------------------
    def run_ring6(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环6撰写：基于大纲生成初稿正文，等待用户确认。"""
        if self._sections.list_task(task_id):
            return self.assemble_section_drafts(task_id)
        rec = self._require_current_ring(task_id, 6)
        protocol = self._active_research_protocol(task_id)
        result_ledger = self._artifacts.get_active(
            task_id=task_id, stage_no=6, kind=ArtifactKind.RESULT_LEDGER
        )
        if protocol is not None and self._method_requires_execution(protocol.payload):
            if result_ledger is None:
                raise BizException(
                    ErrorCode.FSM_INVALID_TRANSITION,
                    msg="实证/系统类研究须先完成实验、核验结果并批准结果账本，才能撰写初稿",
                    detail={"required_artifact": ArtifactKind.RESULT_LEDGER.value},
                )
        chosen = (rec.ring1 or {}).get("chosen", rec.title)
        outline_json = json.dumps(
            {"chapters": (rec.ring5 or {}).get("chapters", [])},
            ensure_ascii=False,
        )
        pool = self._ensure_literature(rec, chosen)
        verified_results = [
            item
            for item in (result_ledger.payload.get("results", []) if result_ledger else [])
            if bool(item.get("verified_by_user"))
        ]
        argument_map = self._active_argument_map(task_id)
        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=chosen,
            outline=outline_json,
            literature=pool,
            session_id=rec.session_id,
            tenant_id=rec.tenant_id,
        )
        ctx.results = verified_results
        ctx.argument_map = argument_map.payload if argument_map is not None else {}
        ctx.research_protocol = protocol.payload if protocol is not None else {}
        project_memory = self._active_project_memory(task_id)
        ctx.project_memory = project_memory.payload if project_memory is not None else {}
        ctx.project_memory_artifact_id = (
            project_memory.artifact_id if project_memory is not None else ""
        )
        from common.agent_loop import AgentLoopSettings
        from common.llm import get_llm_settings

        agent_settings = AgentLoopSettings()
        llm_settings = get_llm_settings()
        if agent_settings.enabled and not llm_settings.supports_tools:
            raise BizException(
                ErrorCode.FSM_INVALID_TRANSITION,
                msg=f"当前DeepSeek模型 {llm_settings.model} 未启用Tools，不能运行写作计划Agent",
            )
        ctx.agent_loop_enabled = agent_settings.enabled
        ctx.enforce_chapter_minimum = True
        checkpoint = (
            rec.ring6
            if isinstance(rec.ring6, dict) and rec.ring6.get("checkpoint")
            else {}
        )
        ctx.chapter_checkpoint = list(checkpoint.get("chapters", []) or [])
        ctx.agent_plan_checkpoint = dict(checkpoint.get("agent_plan", {}) or {})

        def _save_agent_plan(agent_plan: Dict[str, Any]) -> None:
            latest = self._require(task_id)
            existing = latest.ring6 if isinstance(latest.ring6, dict) else {}
            latest.ring6 = {
                **existing,
                "checkpoint": True,
                "agent_plan": agent_plan,
            }
            self._store.put(latest)

        def _save_chapter_checkpoint(chapters: List[Dict[str, Any]]) -> None:
            latest = self._require(task_id)
            existing = latest.ring6 if isinstance(latest.ring6, dict) else {}
            latest.ring6 = {
                **existing,
                "checkpoint": True,
                "chapters": chapters,
                "completed_chapter_count": sum(
                    1
                    for chapter in chapters
                    if bool(chapter.get("checkpoint_complete", True))
                ),
            }
            self._store.put(latest)

        ctx.agent_plan_callback = _save_agent_plan
        ctx.chapter_checkpoint_callback = _save_chapter_checkpoint
        res = get_executor(6).execute(ctx)
        if not res.accept:
            self._fsm.submit_execution(task_id, res.output, accepted=False)
            raise BizException(
                ErrorCode.FSM_ACCEPTANCE_REJECTED,
                msg="环6初稿未通过验收：" + "；".join(res.issues or ["质量不达标"]),
                detail={"fallbackTo": res.fallbackTo, "issues": res.issues},
            )
        draft = json.loads(res.output)
        chapters = draft.get("chapters", [])
        full_content = self._draft_to_text(chapters)
        draft["content"] = full_content
        draft["used_refs"] = list(dict.fromkeys(
            list(draft.get("used_refs", []) or [])
            + re.findall(r"\[L\d+\]", full_content)
        ))
        draft["used_result_ids"] = list(dict.fromkeys(
            list(draft.get("used_result_ids", []) or [])
            + re.findall(r"\[(RES-[A-Z0-9]+)\]", full_content)
        ))
        actual_words, quality_issues = self._manuscript_quality_issues(
            rec,
            draft,
            source=str((res.evidence or {}).get("source", "")),
            literature=pool,
            verified_results=verified_results,
        )
        if quality_issues:
            self._fsm.submit_execution(
                task_id,
                json.dumps({"quality_issues": quality_issues}, ensure_ascii=False),
                accepted=False,
            )
            raise BizException(
                ErrorCode.FSM_ACCEPTANCE_REJECTED,
                msg="环6稿件质量验收失败：" + "；".join(quality_issues),
                detail={"fallbackTo": 6, "issues": quality_issues},
            )
        rec.ring6 = {"chapters": chapters, "content": full_content,
                     "total_words": actual_words,
                     "used_refs": draft.get("used_refs", []),
                     "used_result_ids": draft.get("used_result_ids", []),
                     "generation_source": str((res.evidence or {}).get("source", "")),
                     "agent_plan": dict(getattr(ctx, "agent_plan_result", {}) or {}),
                     "compliant": True}
        self._store.put(rec)
        self._fsm.submit_execution(task_id, res.output, accepted=True)
        return Result.ok(data={"chapters": chapters, "total_words": actual_words,
                               "content_preview": full_content[:200]}, msg="环6撰写完成")

    # ------------------------------------------------------------------
    # 步骤 6：环7 润色（UC-03 延续）
    # ------------------------------------------------------------------
    def run_ring7(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环7润色：对环6 初稿做表达润色 + 术语统一，只改表达不改事实。"""
        rec = self._require_current_ring(task_id, 7)
        contract_audit = self.audit_section_contracts(task_id)
        if not contract_audit.get("can_polish", False):
            recovery = {
                "type": "RECOVER_STAGE",
                "label": "修复环6分节证据/合同阻断后重试",
                "ring_no": 6,
            }
            failure = {
                "reason_code": "SECTION_CONTRACT_REAUDIT_FAILED",
                "blocking_count": int(contract_audit.get("blocking_count", 0) or 0),
                "next_safe_action": recovery,
                "audit": {
                    "mode": contract_audit.get("mode", "contract"),
                    "blocking_reasons": list(contract_audit.get("blocking_reasons", []) or []),
                    "canon_hash": str(contract_audit.get("canon_hash", "")),
                    "contract_hash": str(contract_audit.get("contract_hash", "")),
                },
            }
            self._fsm.submit_execution(
                task_id, json.dumps(failure, ensure_ascii=False), accepted=False
            )
            raise BizException(
                ErrorCode.FSM_ACCEPTANCE_REJECTED,
                msg="环7润色前复审未通过，请先修复环6分节阻断项",
                detail={"fallbackTo": 6, **failure},
            )
        chosen = (rec.ring1 or {}).get("chosen", rec.title)
        draft = (rec.ring6 or {}).get("chapters", [])
        # ring6 产物可能是 chapters 列表，序列化为 JSON 供环7 解析
        draft_json = json.dumps({"chapters": draft}, ensure_ascii=False)
        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=chosen,
            draft=draft_json,
            session_id=rec.session_id,
            tenant_id=rec.tenant_id,
        )
        checkpoint = rec.ring7 if isinstance(rec.ring7, dict) and rec.ring7.get("checkpoint") else {}
        ctx.polished_checkpoint = list(checkpoint.get("chapters", []) or [])
        ctx.polish_notes_checkpoint = list(checkpoint.get("notes", []) or [])

        def _save_polish_checkpoint(chapters: List[Dict[str, Any]], notes: List[str]) -> None:
            latest = self._require(task_id)
            latest.ring7 = {
                "checkpoint": True,
                "chapters": chapters,
                "notes": notes,
                "completed_chapter_count": len(chapters),
            }
            self._store.put(latest)

        ctx.checkpoint_callback = _save_polish_checkpoint
        res = get_executor(7).execute(ctx)
        if not res.accept:
            self._fsm.submit_execution(task_id, res.output, accepted=False)
            raise BizException(
                ErrorCode.FSM_ACCEPTANCE_REJECTED,
                msg="环7润色未通过验收：" + "；".join(res.issues or ["质量不达标"]),
                detail={"fallbackTo": res.fallbackTo, "issues": res.issues},
            )
        data = json.loads(res.output)
        polished = data.get("chapters", [])
        full_content = self._draft_to_text(polished)
        quality_payload = {
            **data,
            "chapters": polished,
            "content": full_content,
            "used_refs": list((rec.ring6 or {}).get("used_refs", []) or []),
            "used_result_ids": list((rec.ring6 or {}).get("used_result_ids", []) or []),
        }
        result_ledger = self._artifacts.get_active(
            task_id=task_id, stage_no=6, kind=ArtifactKind.RESULT_LEDGER
        )
        verified_results = [
            item
            for item in (result_ledger.payload.get("results", []) if result_ledger else [])
            if bool(item.get("verified_by_user"))
        ]
        actual_words, quality_issues = self._manuscript_quality_issues(
            rec,
            quality_payload,
            source=str((res.evidence or {}).get("source", "")),
            literature=self._ensure_literature(rec, chosen),
            verified_results=verified_results,
        )
        if quality_issues:
            self._fsm.submit_execution(
                task_id,
                json.dumps({"quality_issues": quality_issues}, ensure_ascii=False),
                accepted=False,
            )
            raise BizException(
                ErrorCode.FSM_ACCEPTANCE_REJECTED,
                msg="环7润色质量验收失败：" + "；".join(quality_issues),
                detail={"fallbackTo": 6, "issues": quality_issues},
            )
        rec.ring7 = {"chapters": polished,
                     "content": full_content,
                     "total_words": actual_words,
                     "used_refs": quality_payload["used_refs"],
                     "used_result_ids": quality_payload["used_result_ids"],
                     "generation_source": str((res.evidence or {}).get("source", "")),
                     "model_calls": int((res.evidence or {}).get("model_calls", 0) or 0),
                     "length_guard_rejections": int(
                         (res.evidence or {}).get("length_guard_rejections", 0) or 0
                     ),
                     "issues_found": list(data.get("issues_found", []) or []),
                     "applied_terms": list(data.get("applied_terms", []) or []),
                     "canon_hash": str(contract_audit.get("canon_hash", "")),
                     "contract_hash": str(contract_audit.get("contract_hash", "")),
                     "contract_audit": {
                         "mode": contract_audit.get("mode", "legacy"),
                         "blocking_count": int(contract_audit.get("blocking_count", 0) or 0),
                         "audited_section_ids": list(contract_audit.get("audited_section_ids", []) or []),
                     },
                     "compliant": True}
        self._store.put(rec)
        self._fsm.submit_execution(task_id, res.output, accepted=True)
        return Result.ok(data={
            "chapters": polished,
            "total_words": actual_words,
            "applied_terms": data.get("applied_terms", []),
            "issues_found": data.get("issues_found", []),
        }, msg="环7润色完成（只改表达不改事实）")

    # ------------------------------------------------------------------
    # 步骤 7：环9 排版检查（UC-04 延续）
    # ------------------------------------------------------------------
    def run_ring9(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环9排版合规检查：对 docx 产物做版式检查（只查不改）。"""
        rec = self._require_current_ring(task_id, 9)
        docx = rec.docx or {}
        docx_path = ""
        # rec.docx 存的是 file_id/下载信息；实际文件路径需从生成链路拿。
        # 兜底：扫描最近生成产物（按 session/文件名）或要求先 generate_docx。
        if not docx:
            raise BizException(ErrorCode.DOCX_GENERATE_FAILED,
                              msg="请先运行 docx 生成（generate_docx），再执行排版检查",
                              detail={"task_id": task_id})
        # 从当前任务 docx 记录中找落盘路径（generate 时已存 file_path；无则按
        # 当前任务 filename 精确拼接）。禁止用全局 glob 猜测，避免并发任务串档。
        import os as _os
        docx_path = docx.get("file_path", "") or ""
        if docx_path and not _os.path.exists(docx_path):
            docx_path = ""
        if not docx_path:
            fn = docx.get("filename", "")
            outputs_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(
                _os.path.abspath(__file__)))), "thesis_docx", "storage", "outputs")
            if fn:
                p = _os.path.join(outputs_dir, fn)
                if _os.path.exists(p):
                    docx_path = p
        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=rec.title,
            session_id=rec.session_id,
            tenant_id=rec.tenant_id,
        )
        ctx.docx_path = docx_path  # extra 字段（ExecContext extra=allow）
        ctx.template_path = str(rec.template_id or "")

        res = get_executor(9).execute(ctx)
        data = json.loads(res.output)
        data["compliant"] = bool(res.accept)
        rec.ring9 = data
        self._store.put(rec)
        self._fsm.submit_execution(task_id, res.output, accepted=res.accept)
        result_data = {
            "compliant": data.get("compliant", False),
            "issue_count": len(data.get("issues", [])),
            "summary": data.get("summary", ""),
            "fallbackTo": res.fallbackTo,
        }
        if not res.accept:
            return Result.fail(
                code=101200,
                msg=f"环9排版检查未通过：{data.get('summary', '')}",
                data=result_data,
            )
        return Result.ok(data=result_data, msg="环9排版检查完成，等待确认")

    # ------------------------------------------------------------------
    # 步骤 6.5：环8 引用校验（UC-03 延续）
    # ------------------------------------------------------------------
    def run_ring8(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环8引用校验：把环6 引用的 [L序号] 映射为池内题录 → 多源核验。"""
        rec = self._require_current_ring(task_id, 8)
        chosen = (rec.ring1 or {}).get("chosen", rec.title)
        pool = self._ensure_literature(rec, chosen)
        pool_by_idx = {i + 1: it for i, it in enumerate(pool)}

        # 从环6 产物收集 used_refs 对应的题录
        ring6 = rec.ring6 or {}
        used_refs = (ring6.get("used_refs") or []) if isinstance(ring6, dict) else []
        if ring6.get("section_draft_ids") or any(
            str(ref).startswith("EVD-") for ref in used_refs
        ):
            return self._run_ledger_citation_audit(task_id, rec)
        refs = []
        for ref in dict.fromkeys(str(item) for item in used_refs):
            m = re.match(r"\[L(\d+)\]", ref)
            if m and int(m.group(1)) in pool_by_idx:
                it = pool_by_idx[int(m.group(1))]
                refs.append({
                    "marker": ref,
                    "title": it.get("title", "") or it.get("ref_title", ""),
                    "authors": it.get("authors", []),
                    "year": it.get("year"),
                    "venue": it.get("venue", ""),
                    "item_type": it.get("item_type", "article"),
                    "doi": it.get("doi", ""),
                })
        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=chosen,
            session_id=rec.session_id,
            tenant_id=rec.tenant_id,
        )
        ctx.references = refs  # extra 字段
        res = get_executor(8).execute(ctx)
        data = json.loads(res.output)
        data["compliant"] = bool(res.accept)
        if res.accept:
            checked_items = list(data.get("items", []) or [])
            reference_entries: list[dict[str, Any]] = []
            citation_map: dict[str, int] = {}
            for number, ref in enumerate(refs, start=1):
                checked = checked_items[number - 1] if number <= len(checked_items) else {}
                gbt = str(checked.get("gbt7714", "")) or format_gbt7714(ref)
                reference_entries.append({
                    "number": number,
                    "marker": ref["marker"],
                    "title": ref["title"],
                    "doi": ref["doi"],
                    "gbt7714": gbt,
                })
                citation_map[ref["marker"]] = number
            rendered_content = str((rec.ring7 or ring6).get("content", ""))
            for marker, number in citation_map.items():
                rendered_content = rendered_content.replace(marker, f"[{number}]")
            if reference_entries:
                references_text = "\n".join(
                    f"[{item['number']}] {item['gbt7714']}"
                    for item in reference_entries
                )
                rendered_content = (
                    f"{rendered_content.rstrip()}\n\n# 参考文献\n\n{references_text}"
                )
            data["reference_entries"] = reference_entries
            data["citation_map"] = citation_map
            data["rendered_content"] = rendered_content
        rec.ring8 = data
        self._store.put(rec)
        self._fsm.submit_execution(task_id, res.output, accepted=res.accept)
        result_data = {
            "total": data.get("total", 0),
            "passed": data.get("passed", 0),
            "uncertain": data.get("uncertain", 0),
            "failed": data.get("failed", 0),
            "reference_entries": data.get("reference_entries", []),
            "citation_map": data.get("citation_map", {}),
            "trust_assessment": data.get("trust_assessment", {}),
            "fallbackTo": res.fallbackTo,
        }
        if not res.accept:
            return Result.fail(
                code=101200,
                msg=f"环8引用校验未通过：{data.get('summary', '')}",
                data=result_data,
            )
        return Result.ok(
            data=result_data,
            msg=f"环8引用校验完成，等待确认：{data.get('summary', '')}",
        )

    def _run_ledger_citation_audit(
        self, task_id: str, rec: TaskRecord
    ) -> Result[Dict[str, Any]]:
        """审计分节正文中的证据/结果标记，并生成稳定参考文献编号。"""
        ring6 = rec.ring6 or {}
        final_draft = rec.ring7 or ring6
        content = str(final_draft.get("content", ""))
        expected_evidence_ids = {
            str(item)
            for item in (ring6.get("used_refs", []) or [])
            if str(item).startswith("EVD-")
        }
        expected_result_ids = {
            str(item)
            for item in (ring6.get("used_result_ids", []) or [])
            if str(item).startswith("RES-")
        }
        marked_evidence_ids = set(re.findall(r"\[(EVD-[A-Z0-9]+)\]", content))
        marked_result_ids = set(re.findall(r"\[(RES-[A-Z0-9]+)\]", content))
        issues: list[str] = []
        structure_issues: list[str] = []
        metadata_issues: list[str] = []
        evidence_issues: list[str] = []

        def _add_issue(bucket: list[str], message: str) -> None:
            bucket.append(message)
            issues.append(message)

        missing_evidence_markers = sorted(expected_evidence_ids - marked_evidence_ids)
        unexpected_evidence_markers = sorted(marked_evidence_ids - expected_evidence_ids)
        missing_result_markers = sorted(expected_result_ids - marked_result_ids)
        unexpected_result_markers = sorted(marked_result_ids - expected_result_ids)
        if missing_evidence_markers:
            _add_issue(structure_issues, f"正文丢失证据标记: {missing_evidence_markers}")
        if unexpected_evidence_markers:
            _add_issue(structure_issues, f"正文出现未登记证据标记: {unexpected_evidence_markers}")
        if missing_result_markers:
            _add_issue(structure_issues, f"正文丢失结果标记: {missing_result_markers}")
        if unexpected_result_markers:
            _add_issue(structure_issues, f"正文出现未登记结果标记: {unexpected_result_markers}")

        evidence_rows: dict[str, tuple[Any, Any]] = {}
        for evidence_id in sorted(expected_evidence_ids | marked_evidence_ids):
            try:
                excerpt = self._evidence.get_excerpt(task_id, evidence_id)
                source = self._evidence.get_source(task_id, excerpt.source_id)
            except Exception as exc:  # noqa: BLE001
                _add_issue(evidence_issues, f"证据 {evidence_id} 不存在或跨任务: {exc}")
                continue
            if excerpt.review_status.value != "APPROVED":
                _add_issue(evidence_issues, f"证据 {evidence_id} 未获作者批准")
            if source.verification_status in {
                SourceVerificationStatus.UNVERIFIED,
                SourceVerificationStatus.RETRACTED_FLAG,
                SourceVerificationStatus.EXCLUDED,
            }:
                _add_issue(
                    metadata_issues,
                    f"来源 {source.source_id} 核验状态不可用于终稿: "
                    f"{source.verification_status.value}"
                )
            evidence_rows[evidence_id] = (excerpt, source)

        result_ledger = self._artifacts.get_active(
            task_id=task_id, stage_no=6, kind=ArtifactKind.RESULT_LEDGER
        )
        verified_results = {
            str(item.get("result_id", "")): item
            for item in (result_ledger.payload.get("results", []) if result_ledger else [])
            if bool(item.get("verified_by_user"))
        }
        for result_id in sorted(expected_result_ids | marked_result_ids):
            if result_id not in verified_results:
                _add_issue(evidence_issues, f"结果 {result_id} 不属于当前已批准结果账本")

        argument_map = self._active_argument_map(task_id)
        claim_audit = (
            self._evidence.audit(task_id, argument_map.artifact_id)
            if argument_map is not None
            else {
                "claim_count": 0,
                "blocking_claim_ids": [],
                "can_publish": True,
                "claims": [],
            }
        )
        if claim_audit.get("blocking_claim_ids"):
            _add_issue(
                evidence_issues,
                f"仍有未支持或有争议论断: {claim_audit['blocking_claim_ids']}"
            )

        ordered_evidence_ids = sorted(
            evidence_rows,
            key=lambda evidence_id: (
                content.find(f"[{evidence_id}]")
                if f"[{evidence_id}]" in content
                else len(content),
                evidence_id,
            ),
        )
        source_numbers: dict[str, int] = {}
        reference_entries: list[dict[str, Any]] = []
        citation_map: dict[str, int] = {}
        for evidence_id in ordered_evidence_ids:
            _excerpt, source = evidence_rows[evidence_id]
            if source.source_id not in source_numbers:
                number = len(source_numbers) + 1
                source_numbers[source.source_id] = number
                item = {
                    "title": source.title,
                    "authors": list(source.authors),
                    "year": source.year,
                    "venue": source.venue,
                    "doi": source.doi,
                    "item_type": str(source.metadata.get("item_type", "article")),
                }
                reference_entries.append(
                    {
                        "number": number,
                        "source_id": source.source_id,
                        "title": source.title,
                        "doi": source.doi,
                        "gbt7714": str(source.metadata.get("gbt7714", ""))
                        or format_gbt7714(item),
                    }
                )
            citation_map[evidence_id] = source_numbers[source.source_id]

        rendered_content = content
        for evidence_id, number in citation_map.items():
            rendered_content = rendered_content.replace(f"[{evidence_id}]", f"[{number}]")
        cross_reference_map: dict[str, dict[str, str]] = {}
        for result_id in sorted(expected_result_ids | marked_result_ids):
            result = verified_results.get(result_id)
            if result is None:
                continue
            raw_target = str(result.get("table_or_figure_id", "")) or result_id
            target = normalize_target_id(raw_target)
            display = self._cross_reference_display(raw_target)
            if f"[[BOOKMARK:{target}|" not in rendered_content:
                _add_issue(
                    structure_issues,
                    f"结果 {result_id} 缺少交叉引用目标 BOOKMARK:{target}",
                )
            cross_reference_map[result_id] = {
                "target": target,
                "display": display,
            }
            rendered_content = rendered_content.replace(
                f"[{result_id}]", f"[[REF:{target}|{display}]]"
            )
        if reference_entries:
            references_text = "\n".join(
                f"[{item['number']}] {item['gbt7714']}" for item in reference_entries
            )
            rendered_content = f"{rendered_content.rstrip()}\n\n# 参考文献\n\n{references_text}"

        structure_status = (
            TrustCheckStatus.FAILED
            if structure_issues
            else TrustCheckStatus.PASSED
        )
        metadata_status = (
            TrustCheckStatus.FAILED
            if metadata_issues
            else TrustCheckStatus.PASSED
            if reference_entries
            else TrustCheckStatus.NOT_ASSESSED
        )
        evidence_was_assessed = bool(
            expected_evidence_ids
            or marked_evidence_ids
            or expected_result_ids
            or marked_result_ids
            or claim_audit.get("claim_count")
        )
        evidence_status = (
            TrustCheckStatus.NOT_ASSESSED
            if not evidence_was_assessed
            else TrustCheckStatus.FAILED
            if evidence_issues
            or structure_status != TrustCheckStatus.PASSED
            or metadata_status != TrustCheckStatus.PASSED
            else TrustCheckStatus.PASSED
        )
        trust = build_citation_trust_assessment(
            structure=structure_status,
            metadata=metadata_status,
            evidence=evidence_status,
            summaries={
                "structure": (
                    f"引用/结果标记与交叉引用结构阻断项 {len(structure_issues)}"
                ),
                "metadata": (
                    f"已登记参考文献 {len(reference_entries)}，"
                    f"来源状态阻断项 {len(metadata_issues)}"
                ),
                "evidence": (
                    f"已复核摘录 {len(evidence_rows)}，"
                    f"论断 {claim_audit.get('claim_count', 0)}，"
                    f"证据阻断项 {len(evidence_issues)}"
                ),
            },
        )
        accepted = not issues
        data = {
            "total": len(reference_entries),
            "passed": len(reference_entries) if accepted else 0,
            "uncertain": 0,
            "failed": len(issues),
            "items": reference_entries,
            "citation_map": citation_map,
            "cross_reference_map": cross_reference_map,
            "claim_audit": claim_audit,
            "marker_audit": {
                "expected_evidence_ids": sorted(expected_evidence_ids),
                "marked_evidence_ids": sorted(marked_evidence_ids),
                "expected_result_ids": sorted(expected_result_ids),
                "marked_result_ids": sorted(marked_result_ids),
            },
            "issues": issues,
            "trust_assessment": trust,
            "rendered_content": rendered_content,
            "summary": (
                f"证据链、结果链与 {len(reference_entries)} 条参考文献均通过审计"
                if accepted
                else f"引用审计发现 {len(issues)} 个阻断项"
            ),
            "compliant": accepted,
        }
        rec.ring8 = data
        self._store.put(rec)
        self._fsm.submit_execution(
            task_id, json.dumps(data, ensure_ascii=False), accepted=accepted
        )
        result_data = {
            key: data[key]
            for key in (
                "total", "passed", "uncertain", "failed", "citation_map",
                "cross_reference_map", "issues", "summary", "trust_assessment",
            )
        }
        if not accepted:
            return Result.fail(
                code=101200,
                msg=f"环8引用校验未通过：{data['summary']}",
                data=result_data,
            )
        return Result.ok(
            data=result_data,
            msg=f"环8引用校验完成，等待确认：{data['summary']}",
        )

    # ------------------------------------------------------------------
    # 步骤 7.5：环10 定稿汇总（UC-05）
    # ------------------------------------------------------------------
    def run_ring10(self, task_id: str) -> Result[Dict[str, Any]]:
        """执行环10定稿：汇总环1~9 验收状态 + 一致性/材料检查 + 交付清单。"""
        rec = self._require_current_ring(task_id, 10)
        artifacts: Dict[str, Any] = {}
        for no in range(1, 10):
            art = getattr(rec, f"ring{no}")
            if art is not None:
                artifacts[f"ring{no}"] = art
        if rec.docx:
            artifacts["docx"] = rec.docx
        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=rec.title,
            session_id=rec.session_id,
            tenant_id=rec.tenant_id,
        )
        ctx.artifacts = artifacts  # extra 字段
        res = get_executor(10).execute(ctx)
        data = json.loads(res.output)
        data["compliant"] = bool(res.accept)
        rec.ring10 = data
        self._store.put(rec)
        self._fsm.submit_execution(task_id, res.output, accepted=res.accept)
        if not res.accept:
            return Result.fail(
                code=101200,
                msg=f"环10未通过：{data.get('summary', '')}",
                data={**data, "fallbackTo": res.fallbackTo},
            )
        return Result.ok(data=data, msg=f"环10定稿待最终确认：{data.get('summary', '')}")

    # ------------------------------------------------------------------
    # 步骤 8：生成 docx（UC-04）
    # ------------------------------------------------------------------
    def generate_docx(self, task_id: str, template_id: Optional[str] = None) -> Result[Dict[str, Any]]:
        """按用户模板 + 初稿内容生成 docx，返回下载链接。

        docx 是环9排版检查的输入，因此只允许在环8确认完成、进入环9后生成。
        若已完成环7润色，优先使用润色稿；未提供模板时使用内置骨架渲染。
        """
        rec = self._require(task_id)
        state = self._fsm.get_task(task_id)
        if state.current_ring_no != 9 or state.phase_state == PhaseState.WAITING_APPROVAL:
            raise BizException(
                ErrorCode.FSM_INVALID_TRANSITION,
                msg="docx 只能在环8确认完成、进入环9后生成",
            )
        if not rec.ring5 or not (rec.ring7 or rec.ring6):
            raise BizException(
                ErrorCode.DOCX_GENERATE_FAILED,
                msg="大纲或正文产物缺失，无法生成 docx",
                detail={"task_id": task_id},
            )
        tid = template_id or rec.template_id
        draft = rec.ring7 or rec.ring6 or {}
        rendered_content = (
            (rec.ring8 or {}).get("rendered_content", "")
            if isinstance(rec.ring8, dict)
            else ""
        )
        chosen_title = (rec.ring1 or {}).get("chosen", rec.title)
        content = {
            "topic": chosen_title,
            "title": chosen_title,
            "outline": (rec.ring5 or {}).get("outline", ""),
            "chapter": rendered_content or draft.get("content", ""),
            "content": rendered_content or draft.get("content", ""),
            "abstract": str(draft.get("abstract", "")) or (
                (rendered_content or draft.get("content", ""))[:800]
            ),
            "degree": rec.degree,
            "subject_field": rec.subject_field,
            "references": "\n".join(
                f"[{item.get('number')}] {item.get('gbt7714')}"
                for item in ((rec.ring8 or {}).get("items", []) if isinstance(rec.ring8, dict) else [])
            ),
        }
        for placeholder, source_key in rec.template_mapping.items():
            if source_key in content:
                content[placeholder] = content[source_key]
        unresolved = sorted(
            placeholder
            for placeholder in rec.template_placeholders
            if placeholder not in content
        )
        if rec.template_path and unresolved:
            raise BizException(
                ErrorCode.DOCX_GENERATE_FAILED,
                msg="学校模板仍有未映射占位符",
                detail={"unresolved_placeholders": unresolved},
            )
        try:
            gen = self._docx.generate(
                tid,
                content=content,
                task_id=task_id,
                session_id=rec.session_id,
                template_path=rec.template_path,
            )
        except BizException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BizException(
                ErrorCode.DOCX_GENERATE_FAILED, msg=f"docx 生成失败: {exc}", detail=str(exc)
            ) from exc
        rec.docx = {"file_id": gen.get("file_id"), "download_url": gen.get("download_url"),
                    "filename": gen.get("filename", ""), "file_path": gen.get("file_path", ""),
                    "template_id": tid, "cross_references": gen.get("cross_references", {})}
        self._store.put(rec)
        return Result.ok(data=gen, msg="docx 生成完成")

    # ------------------------------------------------------------------
    # 进度视图
    # ------------------------------------------------------------------
    def progress(self, task_id: str) -> Result[Dict[str, Any]]:
        """读取任务进度（委托 M1 FSM progress）。"""
        try:
            rec = self._require(task_id)
            reconciliation = self.reconcile_task_state(task_id).data
            projection_issues = list(
                reconciliation.get("artifact_projection_issues", []) or []
            )
            try:
                data = self._fsm.get_progress(task_id)
            except Exception:  # noqa: BLE001 - 对账页必须能呈现 FSM 缺失
                data = {
                    "task_id": task_id,
                    "current_ring_no": 1,
                    "current_ring": "RING_1",
                    "complete_percent": 0,
                    "phase_state": PhaseState.FALLBACK.value,
                    "can_execute": False,
                    "can_confirm": False,
                    "rings": [],
                }
            data.update({
                "title": rec.title,
                "session_id": rec.session_id,
                "scope": rec.scope,
                "artifact_projection_pending": bool(projection_issues),
                "artifact_projection_issues": projection_issues,
                "reconciliation_status": reconciliation.get("status", "CONSISTENT"),
                "reconciliation_issues": list(reconciliation.get("issues", []) or []),
                "repair_required": reconciliation.get("status") != "CONSISTENT",
                "trust_assessments": {
                    "8": (rec.ring8 or {}).get("trust_assessment", {})
                } if isinstance(rec.ring8, dict) and rec.ring8.get("trust_assessment") else {},
            })
            decision_ready = True
            decision_blocker = ""
            if data.get("phase_state") == PhaseState.WAITING_APPROVAL.value:
                if data.get("current_ring_no") == 1:
                    decision_ready = bool((rec.ring1 or {}).get("selection_confirmed"))
                    decision_blocker = "请先选择候选题目" if not decision_ready else ""
                elif data.get("current_ring_no") == 3:
                    decision_ready = bool((rec.ring3 or {}).get("curated"))
                    decision_blocker = "请先完成文献筛选" if not decision_ready else ""
            data["author_decision_ready"] = decision_ready
            data["author_decision_blocker"] = decision_blocker
            if (
                data.get("phase_state") == PhaseState.WAITING_APPROVAL.value
                and data.get("current_ring_no") in {1, 3, 8}
            ):
                data["author_decision_payload"] = getattr(
                    rec, f"ring{data['current_ring_no']}"
                ) or {}
            return Result.ok(data=data, msg="进度查询成功")
        except BizException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BizException(
                ErrorCode.STATE_READ_FAILED, msg=f"进度查询失败: {exc}", detail=str(exc)
            ) from exc

    def get_template_config(self, task_id: str) -> Result[Dict[str, Any]]:
        rec = self._require(task_id)
        return Result.ok(
            data={
                "template_id": rec.template_id,
                "template_name": rec.template_name or (
                    os.path.basename(rec.template_path) if rec.template_path else ""
                ),
                "placeholders": list(rec.template_placeholders),
                "mapping": dict(rec.template_mapping),
                "is_custom": bool(rec.template_id and rec.template_path),
            },
            msg="论文模板配置",
        )

    def set_template_mapping(
        self, task_id: str, mapping: Dict[str, Any]
    ) -> Result[Dict[str, Any]]:
        rec = self._require(task_id)
        if not rec.template_id or not rec.template_path:
            raise BizException(ErrorCode.TEMPLATE_NOT_FOUND, msg="请先上传学校 DOCX 模板")
        allowed_sources = {
            "topic", "title", "outline", "chapter", "content",
            "abstract", "degree", "subject_field", "references",
        }
        cleaned = {str(key): str(value) for key, value in mapping.items()}
        unknown_targets = sorted(set(cleaned) - set(rec.template_placeholders))
        unknown_sources = sorted(set(cleaned.values()) - allowed_sources)
        if unknown_targets:
            raise BizException(
                ErrorCode.INVALID_PARAM,
                msg=f"映射包含模板中不存在的占位符: {unknown_targets}",
            )
        if unknown_sources:
            raise BizException(
                ErrorCode.INVALID_PARAM,
                msg=f"映射包含不支持的内容源: {unknown_sources}",
            )
        rec.template_mapping = cleaned
        self._store.put(rec)
        return Result.ok(
            data={
                "placeholders": list(rec.template_placeholders),
                "mapping": dict(rec.template_mapping),
            },
            msg="模板占位符映射已保存",
        )

    @staticmethod
    def _suggest_template_mapping(placeholders: List[str]) -> Dict[str, str]:
        exact = {
            "topic", "title", "outline", "chapter", "content",
            "abstract", "degree", "subject_field", "references",
        }
        suggestions: Dict[str, str] = {}
        for placeholder in placeholders:
            low = placeholder.strip().lower()
            if low in exact:
                suggestions[placeholder] = low
            elif any(token in placeholder for token in ("题目", "标题")):
                suggestions[placeholder] = "title"
            elif "大纲" in placeholder or "目录" in placeholder:
                suggestions[placeholder] = "outline"
            elif any(token in placeholder for token in ("正文", "内容", "章节")):
                suggestions[placeholder] = "content"
            elif "摘要" in placeholder:
                suggestions[placeholder] = "abstract"
            elif "参考文献" in placeholder:
                suggestions[placeholder] = "references"
            elif "学位" in placeholder:
                suggestions[placeholder] = "degree"
            elif any(token in placeholder for token in ("学科", "专业")):
                suggestions[placeholder] = "subject_field"
        return suggestions

    def confirm_ring(
        self,
        task_id: str,
        ring_no: int,
        confirmed: bool = True,
        reject_reason: str = "",
    ) -> Result[Dict[str, Any]]:
        """确认或拒绝当前环产物；成功确认后才推进到下一环。"""
        reconciliation = self.reconcile_task_state(task_id).data
        if reconciliation.get("status") != "CONSISTENT":
            issue_codes = [
                str(issue.get("code", ""))
                for issue in (reconciliation.get("issues", []) or [])
                if isinstance(issue, dict) and str(issue.get("code", ""))
            ]
            raise BizException(
                ErrorCode.STATE_CONFLICT,
                msg="任务状态对账未通过，禁止确认当前环节",
                detail={
                    "reason_code": "STARTUP_RECONCILIATION_REQUIRED",
                    "blocking_count": len(issue_codes),
                    "issue_codes": issue_codes,
                    "next_safe_action": {"type": "REPAIR_REQUIRED"},
                },
            )
        state = self._fsm.get_task(task_id)
        if state.current_ring_no != ring_no:
            raise BizException(
                ErrorCode.FSM_INVALID_TRANSITION,
                msg=f"当前是环{state.current_ring_no}，不能确认环{ring_no}",
            )
        if state.phase_state != PhaseState.WAITING_APPROVAL:
            raise BizException(
                ErrorCode.FSM_INVALID_TRANSITION,
                msg="当前环没有待确认产物，请先执行该环节",
            )
        rec = self._require(task_id)
        if confirmed and ring_no == 1 and not bool(
            (rec.ring1 or {}).get("selection_confirmed")
        ):
            raise BizException(
                ErrorCode.FSM_INVALID_TRANSITION,
                msg="请先选择候选题目，再确认环1",
            )
        if confirmed and ring_no == 3 and not bool((rec.ring3 or {}).get("curated")):
            raise BizException(
                ErrorCode.FSM_INVALID_TRANSITION,
                msg="请先完成文献筛选并保存纳入/排除决定，再确认环3",
            )
        if confirmed and ring_no == 5:
            protocols = [
                artifact
                for artifact in self._artifacts.list_task(task_id)
                if artifact.kind == ArtifactKind.RESEARCH_PROTOCOL
            ]
            if protocols and self._active_research_protocol(task_id) is None:
                raise BizException(
                    ErrorCode.FSM_INVALID_TRANSITION,
                    msg="研究协议尚未获作者批准，不能确认环5",
                    detail={"required_artifact": ArtifactKind.RESEARCH_PROTOCOL.value},
                )
            argument_maps = [
                artifact
                for artifact in self._artifacts.list_task(task_id)
                if artifact.kind == ArtifactKind.ARGUMENT_MAP
            ]
            if argument_maps and self._active_argument_map(task_id) is None:
                raise BizException(
                    ErrorCode.FSM_INVALID_TRANSITION,
                    msg="论证图尚未获作者批准，不能确认环5",
                    detail={"required_artifact": ArtifactKind.ARGUMENT_MAP.value},
                )
        payload = getattr(rec, f"ring{ring_no}", None) or {}
        if ring_no == 8 and isinstance(payload, dict) and payload.get("trust_assessment"):
            payload = dict(payload)
            payload["trust_assessment"] = with_author_review(
                payload["trust_assessment"],
                approved=confirmed,
                reason=reject_reason,
            )
        contract = get_stage_contract(ring_no)
        event_id = f"EVT-{uuid.uuid4().hex[:20].upper()}"
        dependency_ids: tuple[str, ...] = ()
        if ring_no == 5:
            project_memory = self._active_project_memory(task_id)
            protocol = self._active_research_protocol(task_id)
            argument_map = self._active_argument_map(task_id)
            if project_memory is not None or protocol is not None or argument_map is not None:
                ring4 = self._artifacts.get_active(
                    task_id=task_id,
                    stage_no=4,
                    kind=ArtifactKind(get_stage_contract(4).runtime_artifact_kind),
                )
                if ring4 is None:
                    raise ResearchRegistryError("环5产物缺少有效的环4依赖")
                dependency_ids = tuple(
                    [ring4.artifact_id]
                    + ([project_memory.artifact_id] if project_memory is not None else [])
                    + ([protocol.artifact_id] if protocol is not None else [])
                    + ([argument_map.artifact_id] if argument_map is not None else [])
                )
        elif ring_no == 6:
            result_ledger = self._artifacts.get_active(
                task_id=task_id, stage_no=6, kind=ArtifactKind.RESULT_LEDGER
            )
            if result_ledger is not None:
                outline = self._artifacts.get_active(
                    task_id=task_id, stage_no=5, kind=ArtifactKind.OUTLINE
                )
                if outline is None:
                    raise ResearchRegistryError("环6产物缺少有效大纲依赖")
                dependency_ids = (outline.artifact_id, result_ledger.artifact_id)
        job_id = str(payload.get("_job_id", "")) if isinstance(payload, dict) else ""
        job_usage = None
        if job_id:
            try:
                job_usage = self._jobs.get(task_id, job_id)
            except JobRegistryError:
                job_usage = None
        context_manifest = ContextManifest(
            prompt_id=f"ring{ring_no}",
            prompt_version="legacy-v1",
            model=str(payload.get("source", "")) if isinstance(payload, dict) else "",
            input_artifact_ids=dependency_ids,
            job_id=job_id,
            token_budget=job_usage.token_budget if job_usage else 0,
            input_tokens=job_usage.input_tokens if job_usage else 0,
            output_tokens=job_usage.output_tokens if job_usage else 0,
            cost_budget=job_usage.cost_budget if job_usage else 0.0,
            cost_used=job_usage.cost_used if job_usage else 0.0,
            canon_hash=(
                str(payload.get("canon_hash", "")) if isinstance(payload, dict) else ""
            ),
            contract_hash=(
                str(payload.get("contract_hash", "")) if isinstance(payload, dict) else ""
            ),
        )
        artifact_event = {
            "event_id": event_id,
            "task_id": task_id,
            "stage_no": ring_no,
            "kind": contract.runtime_artifact_kind,
            "payload": payload if isinstance(payload, dict) else {"value": payload},
            "context_manifest": context_manifest.to_dict(),
            "dependency_ids": list(dependency_ids),
            "auto_gate_passed": True,
            "gate_report": {
                "fsm_acceptance": "passed",
                "trust_assessment": (
                    payload.get("trust_assessment", {})
                    if isinstance(payload, dict)
                    else {}
                ),
                "canon_hash": (
                    str(payload.get("canon_hash", ""))
                    if isinstance(payload, dict)
                    else ""
                ),
                "contract_hash": (
                    str(payload.get("contract_hash", ""))
                    if isinstance(payload, dict)
                    else ""
                ),
            },
            "actor": "author",
        }
        self._fsm.advance(
            task_id=task_id,
            biz_req_no=f"CONFIRM-{task_id}-R{ring_no}-{uuid.uuid4().hex[:8]}",
            accept=confirmed,
            reject_reason=reject_reason or None,
            gate_rule="user_confirmation",
            artifact_event=artifact_event,
        )
        if ring_no == 8 and isinstance(payload, dict) and payload.get("trust_assessment"):
            rec.ring8 = payload
            self._store.put(rec)
        projection_issues = self._project_pending_artifacts(task_id)
        progress = self._fsm.get_progress(task_id)
        progress["artifact_projection_pending"] = bool(projection_issues)
        progress["artifact_projection_issues"] = projection_issues
        return Result.ok(
            data=progress,
            msg=(
                "已确认，进入下一环"
                if confirmed and ring_no < 10
                else "论文全流程已确认完成"
                if confirmed
                else "已拒绝当前产物，可重新执行或回退"
            ),
        )

    # ------------------------------------------------------------------
    # 会话隔离校验
    # ------------------------------------------------------------------
    def assert_session(self, task_id: str, session_id: str) -> None:
        """校验任务归属指定会话（M9 会话隔离预留）。

        Args:
            task_id: 任务 ID。
            session_id: 请求携带的会话 ID。空串表示默认会话，允许访问。
        Raises:
            BizException: 任务不存在或不属于该会话。
        """
        rec = self._require(task_id)
        if session_id and rec.session_id and rec.session_id != session_id:
            raise BizException(
                ErrorCode.FORBIDDEN, msg="任务不属于当前会话，禁止访问",
                detail={"task_id": task_id, "session_id": session_id},
            )

    def assert_tenant_access(self, task_id: str, tenant_id: str) -> None:
        rec = self._require(task_id)
        if not tenant_id or rec.tenant_id != tenant_id:
            raise PermissionError("任务不属于当前租户")

    def assert_session_tenant(self, session_id: str, tenant_id: str) -> None:
        rec = next(
            (item for item in self._store.all() if item.session_id == session_id),
            None,
        )
        if rec is None or not tenant_id or rec.tenant_id != tenant_id:
            raise PermissionError("知识库会话不属于当前租户")

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _require(self, task_id: str) -> TaskRecord:
        rec = self._store.get(task_id)
        if rec is None:
            raise BizException(ErrorCode.TASK_NOT_FOUND, msg=f"任务不存在: {task_id}")
        return rec

    def list_artifacts(self, task_id: str) -> Result[List[Dict[str, Any]]]:
        """列出任务全部产物版本及审批/失效状态。"""
        self._require(task_id)
        projection_issues = self._project_pending_artifacts(task_id)
        items = []
        for artifact in self._artifacts.list_task(task_id):
            items.append(
                {
                    "artifact_id": artifact.artifact_id,
                    "stage_no": artifact.stage_no,
                    "kind": artifact.kind.value,
                    "version": artifact.version,
                    "status": artifact.status.value,
                    "payload": artifact.payload,
                    "content_hash": artifact.content_hash,
                    "dependency_ids": list(artifact.dependency_ids),
                    "context_manifest": artifact.context_manifest.to_dict(),
                    "gate_report": artifact.gate_report,
                    "stale_reason": artifact.stale_reason,
                    "source_event_id": artifact.source_event_id,
                    "created_at": artifact.created_at,
                    "updated_at": artifact.updated_at,
                }
            )
        return Result.ok(
            data=items,
            msg=(
                "产物列表（存在待恢复投影）"
                if projection_issues
                else "产物列表"
            ),
        )

    def reopen_stage(
        self, task_id: str, target_ring_no: int, *, reason: str = ""
    ) -> Result[Dict[str, Any]]:
        """从失败 Gate 安全回到契约允许的上游环节，并清除待重建运行产物。"""
        rec = self._require(task_id)
        state = self._fsm.get_task(task_id)
        allowed = get_stage_contract(state.current_ring_no).reentry_targets
        failed_job = any(
            job.status.value == "FAILED"
            and job.operation == "ring.execute"
            and int(job.payload.get("ring_no", 0) or 0) == state.current_ring_no
            for job in self._jobs.list_task(task_id, limit=100)
        )
        if state.phase_state != PhaseState.FALLBACK and not failed_job:
            raise BizException(
                ErrorCode.FSM_INVALID_TRANSITION,
                msg="只有失败回退状态或当前环失败作业可以重新打开上游环节",
            )
        if target_ring_no not in allowed:
            raise BizException(
                ErrorCode.FSM_INVALID_TRANSITION,
                msg=f"环{state.current_ring_no}只允许回到: {list(allowed)}",
            )
        restored = self._fsm.rollback(task_id, target_ring_no)
        for ring_no in range(target_ring_no, 11):
            setattr(rec, f"ring{ring_no}", None)
        if target_ring_no <= 9:
            rec.docx = None
        self._store.put(rec)
        return Result.ok(
            data={
                "current_ring_no": restored.current_ring_no,
                "phase_state": restored.phase_state.value,
                "reason": reason,
            },
            msg=f"已回到环{target_ring_no}，请修订后重新执行",
        )

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 分节写作、逐节审批与环6汇编
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 研究协议、实验运行与结果账本
    # ------------------------------------------------------------------

    def _ensure_literature(self, rec: TaskRecord, theme: str) -> List[Dict[str, Any]]:
        """确保文献池已构建（执行环3 并缓存），返回池条目列表。

        环3 离线/无文献源时返回空池（环5/6 prompt 会提示"禁止引用"）。
        已知库文献（用户从引导层平台下载的）合并入池。
        """
        if rec.ring3 is not None and rec.ring3.get("items"):
            return rec.ring3.get("items", [])
        # 读会话知识库已存文献（用户下载的题录）
        kb_files = []
        if rec.session_id:
            try:
                from knowledge.store import get_kb_store

                kb_files = get_kb_store().list_documents(rec.session_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("知识库读取失败: %s", exc)

        from common.agent_loop import AgentLoopSettings

        agent_settings = AgentLoopSettings()
        if agent_settings.enabled:
            from common.llm import get_llm_settings

            llm_settings = get_llm_settings()
            if not llm_settings.supports_tools:
                raise BizException(
                    ErrorCode.FSM_INVALID_TRANSITION,
                    msg=(
                        f"当前DeepSeek模型 {llm_settings.model} 未启用Tools，"
                        "不能运行环3检索策略Agent"
                    ),
                )
        project_memory = self._active_project_memory(rec.task_id)
        ctx = ExecContext(
            subject_field=rec.subject_field,
            degree=Degree(rec.degree),
            theme=theme,
            scope=getattr(rec, "scope", "all") or "all",
            kb_files=kb_files,
            session_id=rec.session_id,
            tenant_id=rec.tenant_id,
        )
        ctx.agent_loop_enabled = agent_settings.enabled
        ctx.project_memory = project_memory.payload if project_memory is not None else {}
        try:
            res = get_executor(3).execute(ctx)
            data = json.loads(res.output)
            rec.ring3 = data
            self._store.put(rec)
            return data.get("items", [])
        except BizException:
            raise
        except Exception as exc:  # noqa: BLE001 - 基础检索失败可返回空池
            if agent_settings.enabled:
                raise BizException(
                    ErrorCode.RING_EXECUTION_FAILED,
                    msg=f"环3检索策略Agent执行失败: {exc}",
                    detail={"fallbackTo": 3, "agent_loop": True},
                ) from exc
            logger.warning("环3文献检索失败，返回空池: %s", exc)
            return []

    def _manuscript_quality_issues(
        self,
        rec: TaskRecord,
        draft: Dict[str, Any],
        *,
        source: str,
        literature: List[Dict[str, Any]],
        verified_results: List[Dict[str, Any]],
    ) -> tuple[int, List[str]]:
        """学位论文写作硬 Gate：真实字数、章节、引用、结果和降级状态。"""
        chapters = [item for item in (draft.get("chapters", []) or []) if isinstance(item, dict)]
        content = str(draft.get("content", "")) or self._draft_to_text(chapters)
        actual_words = len(re.sub(r"[\s#*`-]+", "", content))
        issues: list[str] = []
        degree = Degree(rec.degree)
        if source in {"mock", "none", "fingerprint_reject", "fallback"}:
            issues.append(f"生成来源为降级模式 {source or 'unknown'}")
        if actual_words < degree.min_word_requirement:
            issues.append(
                f"实际字数 {actual_words} 低于{degree.label}最低要求 "
                f"{degree.min_word_requirement}"
            )
        expected_chapters = [
            item
            for item in ((rec.ring5 or {}).get("chapters", []) or [])
            if isinstance(item, dict) and int(item.get("level", 1) or 1) == 1
        ]
        if expected_chapters and len(chapters) < len(expected_chapters):
            issues.append(
                f"正文仅覆盖 {len(chapters)}/{len(expected_chapters)} 个一级章节"
            )
        placeholder_hits = sum(
            content.count(fragment)
            for fragment in (
                "本节梳理第",
                "明确本章要解决的核心问题",
                "为后续章节奠定基础",
            )
        )
        if placeholder_hits > 2:
            issues.append(f"检测到 {placeholder_hits} 处重复占位模板句")

        used_refs = {
            str(item) for item in (draft.get("used_refs", []) or []) if str(item)
        }
        used_refs.update(re.findall(r"\[L\d+\]", content))
        if literature:
            baseline = {Degree.BACHELOR: 3, Degree.MASTER: 5, Degree.PHD: 10}[degree]
            required = min(len(literature), baseline)
            if len(used_refs) < required:
                issues.append(f"正文仅使用 {len(used_refs)} 条文献，最低需要 {required} 条")
            invalid_pool_refs = sorted(
                ref
                for ref in used_refs
                if (match := re.fullmatch(r"\[L(\d+)\]", ref))
                and int(match.group(1)) > len(literature)
            )
            if invalid_pool_refs:
                issues.append(f"正文引用了文献池外编号: {invalid_pool_refs}")
        missing_ref_markers = sorted(ref for ref in used_refs if ref not in content)
        if missing_ref_markers:
            issues.append(f"正文缺少已登记引用标记: {missing_ref_markers}")

        expected_result_ids = {
            str(item.get("result_id", ""))
            for item in verified_results
            if str(item.get("result_id", ""))
        }
        used_result_ids = {
            str(item) for item in (draft.get("used_result_ids", []) or []) if str(item)
        }
        used_result_ids.update(re.findall(r"\[(RES-[A-Z0-9]+)\]", content))
        missing_results = sorted(expected_result_ids - used_result_ids)
        if missing_results:
            issues.append(f"正文未使用全部已批准结果: {missing_results}")
        for item in verified_results:
            result_id = str(item.get("result_id", ""))
            if result_id not in used_result_ids:
                continue
            target = normalize_target_id(
                str(item.get("table_or_figure_id", "")) or result_id
            )
            if f"[[BOOKMARK:{target}|" not in content:
                issues.append(f"结果 {result_id} 缺少交叉引用目标 BOOKMARK:{target}")
        return actual_words, issues

    @staticmethod
    def _outline_to_text(chapters: List[Dict[str, Any]]) -> str:
        """把大纲节点平铺为可读文本（供环6/渲染端消费）。"""
        lines: List[str] = []
        for node in chapters:
            if not isinstance(node, dict):
                continue
            level = node.get("level", 1)
            number = node.get("number", "")
            title = node.get("title", "")
            prefix = "  " * (level - 1)
            lines.append(f"{prefix}{number} {title}".strip())
        return "\n".join(lines)

    @staticmethod
    def _draft_to_text(chapters: List[Dict[str, Any]]) -> str:
        """把各章节草稿拼接为完整正文文本。"""
        parts: List[str] = []
        for ch in chapters:
            if not isinstance(ch, dict):
                continue
            title = ch.get("chapter_title", "")
            content = ch.get("content", "")
            parts.append(f"# {title}\n\n{content}".strip())
        return "\n\n".join(parts)
