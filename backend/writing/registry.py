"""按 section_id 独立版本化的 SQLite 分节草稿仓库。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import SectionDraft, SectionDraftStatus
from jobs.runtime import job_write_fence


class SectionDraftRegistryError(ValueError):
    """违反分节版本、验收或审批约束。"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class SectionDraftRegistry:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._lock = threading.RLock()
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self._db_path, check_same_thread=False, timeout=15)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _init_schema(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS t_section_draft (
                section_draft_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                section_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                status TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                claim_ids TEXT NOT NULL DEFAULT '[]',
                evidence_ids TEXT NOT NULL DEFAULT '[]',
                result_ids TEXT NOT NULL DEFAULT '[]',
                upstream_artifact_ids TEXT NOT NULL DEFAULT '[]',
                context_manifest TEXT NOT NULL DEFAULT '{}',
                gate_report TEXT NOT NULL DEFAULT '{}',
                stale_reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(task_id, section_id, version)
            );

            CREATE INDEX IF NOT EXISTS idx_section_draft_task
            ON t_section_draft(task_id, section_id, version DESC);

            CREATE TABLE IF NOT EXISTS t_section_draft_approval (
                approval_id TEXT PRIMARY KEY,
                section_draft_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                actor TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(section_draft_id) REFERENCES t_section_draft(section_draft_id)
                    ON DELETE CASCADE
            );
            """
        )
        self._db.commit()

    def create_version(
        self,
        *,
        task_id: str,
        section_id: str,
        title: str,
        content: str,
        claim_ids: Iterable[str] = (),
        evidence_ids: Iterable[str] = (),
        result_ids: Iterable[str] = (),
        upstream_artifact_ids: Iterable[str] = (),
        context_manifest: dict[str, Any] | None = None,
    ) -> SectionDraft:
        if not task_id.strip():
            raise SectionDraftRegistryError("task_id 不能为空")
        if not section_id.strip():
            raise SectionDraftRegistryError("section_id 不能为空")
        if not title.strip():
            raise SectionDraftRegistryError("分节标题不能为空")
        if not content.strip():
            raise SectionDraftRegistryError("分节正文不能为空")
        now = _utc_now()
        with job_write_fence(task_id), self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM t_section_draft "
                    "WHERE task_id=? AND section_id=?",
                    (task_id, section_id),
                ).fetchone()
                version = int(row[0]) + 1
                draft_id = f"SEC-{uuid.uuid4().hex[:20].upper()}"
                self._db.execute(
                    "INSERT INTO t_section_draft(section_draft_id, task_id, section_id, version, "
                    "status, title, content, content_hash, claim_ids, evidence_ids, result_ids, "
                    "upstream_artifact_ids, context_manifest, gate_report, stale_reason, "
                    "created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', "
                    "'', ?, ?)",
                    (
                        draft_id, task_id, section_id.strip(), version,
                        SectionDraftStatus.GENERATED.value, title.strip(), content.strip(),
                        hashlib.sha256(content.strip().encode("utf-8")).hexdigest(),
                        _json_dump(tuple(dict.fromkeys(claim_ids))),
                        _json_dump(tuple(dict.fromkeys(evidence_ids))),
                        _json_dump(tuple(dict.fromkeys(result_ids))),
                        _json_dump(tuple(dict.fromkeys(upstream_artifact_ids))),
                        _json_dump(context_manifest or {}), now, now,
                    ),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return self.get(task_id, draft_id)

    def submit_auto_gate(
        self, task_id: str, section_draft_id: str, *, passed: bool,
        report: dict[str, Any] | None = None,
    ) -> SectionDraft:
        draft = self.get(task_id, section_draft_id)
        if draft.status != SectionDraftStatus.GENERATED:
            raise SectionDraftRegistryError("只有 GENERATED 分节草稿可以提交自动验收")
        status = (
            SectionDraftStatus.WAITING_APPROVAL
            if passed
            else SectionDraftStatus.AUTO_REJECTED
        )
        with job_write_fence(task_id), self._lock:
            self._db.execute(
                "UPDATE t_section_draft SET status=?, gate_report=?, updated_at=? "
                "WHERE task_id=? AND section_draft_id=?",
                (
                    status.value, _json_dump(report or {}), _utc_now(),
                    task_id, section_draft_id,
                ),
            )
            self._db.commit()
        return self.get(task_id, section_draft_id)

    def decide(
        self, task_id: str, section_draft_id: str, *, approved: bool,
        actor: str = "author", reason: str = "",
    ) -> SectionDraft:
        with job_write_fence(task_id), self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                draft = self.get(task_id, section_draft_id)
                if draft.status != SectionDraftStatus.WAITING_APPROVAL:
                    raise SectionDraftRegistryError("只有 WAITING_APPROVAL 分节草稿可以审批")
                now = _utc_now()
                if approved:
                    self._db.execute(
                        "UPDATE t_section_draft SET status=?, updated_at=? WHERE task_id=? "
                        "AND section_id=? AND status=? AND section_draft_id<>?",
                        (
                            SectionDraftStatus.SUPERSEDED.value, now, task_id, draft.section_id,
                            SectionDraftStatus.APPROVED.value, section_draft_id,
                        ),
                    )
                    status = SectionDraftStatus.APPROVED
                else:
                    status = SectionDraftStatus.REJECTED
                report = dict(draft.gate_report)
                report["author_reason"] = reason.strip()
                self._db.execute(
                    "UPDATE t_section_draft SET status=?, gate_report=?, updated_at=? "
                    "WHERE task_id=? AND section_draft_id=?",
                    (status.value, _json_dump(report), now, task_id, section_draft_id),
                )
                self._db.execute(
                    "INSERT INTO t_section_draft_approval(approval_id, section_draft_id, "
                    "decision, actor, reason, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                    (
                        f"SAP-{uuid.uuid4().hex[:20].upper()}", section_draft_id,
                        "APPROVE" if approved else "REJECT", actor.strip() or "author",
                        reason.strip(), now,
                    ),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return self.get(task_id, section_draft_id)

    def mark_stale(self, task_id: str, section_draft_id: str, *, reason: str) -> SectionDraft:
        draft = self.get(task_id, section_draft_id)
        if draft.status in {
            SectionDraftStatus.REJECTED,
            SectionDraftStatus.SUPERSEDED,
            SectionDraftStatus.AUTO_REJECTED,
        }:
            return draft
        with job_write_fence(task_id), self._lock:
            self._db.execute(
                "UPDATE t_section_draft SET status=?, stale_reason=?, updated_at=? "
                "WHERE task_id=? AND section_draft_id=?",
                (
                    SectionDraftStatus.STALE.value, reason.strip(), _utc_now(),
                    task_id, section_draft_id,
                ),
            )
            self._db.commit()
        return self.get(task_id, section_draft_id)

    def get(self, task_id: str, section_draft_id: str) -> SectionDraft:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM t_section_draft WHERE task_id=? AND section_draft_id=?",
                (task_id, section_draft_id),
            ).fetchone()
        if row is None:
            raise SectionDraftRegistryError(f"当前任务中不存在分节草稿: {section_draft_id}")
        return self._row_to_draft(row)

    def get_active(self, task_id: str, section_id: str) -> SectionDraft | None:
        with self._lock:
            row = self._db.execute(
                "SELECT section_draft_id FROM t_section_draft WHERE task_id=? AND section_id=? "
                "AND status=? ORDER BY version DESC LIMIT 1",
                (task_id, section_id, SectionDraftStatus.APPROVED.value),
            ).fetchone()
        return self.get(task_id, str(row[0])) if row is not None else None

    def list_task(self, task_id: str) -> list[SectionDraft]:
        with self._lock:
            rows = self._db.execute(
                "SELECT section_draft_id FROM t_section_draft WHERE task_id=? "
                "ORDER BY section_id, version",
                (task_id,),
            ).fetchall()
        return [self.get(task_id, str(row[0])) for row in rows]

    def list_task_ids(self) -> list[str]:
        with self._lock:
            rows = self._db.execute(
                "SELECT DISTINCT task_id FROM t_section_draft ORDER BY task_id"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def list_approvals(self, task_id: str, section_draft_id: str) -> list[dict[str, str]]:
        self.get(task_id, section_draft_id)
        with self._lock:
            rows = self._db.execute(
                "SELECT approval_id, decision, actor, reason, created_at "
                "FROM t_section_draft_approval WHERE section_draft_id=? ORDER BY created_at",
                (section_draft_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_task(self, task_id: str) -> int:
        with job_write_fence(task_id), self._lock:
            cur = self._db.execute("DELETE FROM t_section_draft WHERE task_id=?", (task_id,))
            self._db.commit()
            return int(cur.rowcount)

    @staticmethod
    def _row_to_draft(row: sqlite3.Row) -> SectionDraft:
        return SectionDraft(
            section_draft_id=str(row["section_draft_id"]), task_id=str(row["task_id"]),
            section_id=str(row["section_id"]), version=int(row["version"]),
            status=SectionDraftStatus(str(row["status"])), title=str(row["title"]),
            content=str(row["content"]), content_hash=str(row["content_hash"]),
            claim_ids=tuple(json.loads(str(row["claim_ids"]))),
            evidence_ids=tuple(json.loads(str(row["evidence_ids"]))),
            result_ids=tuple(json.loads(str(row["result_ids"]))),
            upstream_artifact_ids=tuple(json.loads(str(row["upstream_artifact_ids"]))),
            context_manifest=json.loads(str(row["context_manifest"])),
            gate_report=json.loads(str(row["gate_report"])),
            stale_reason=str(row["stale_reason"]), created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
