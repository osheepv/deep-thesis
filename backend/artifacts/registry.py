"""SQLite 版本化产物仓库。

核心约束：
1. 产物正文不可原地覆盖，新内容只能创建新版本；
2. 只有自动验收通过的版本才能等待作者审批；
3. 新版本被批准后，旧批准版本才失效，并递归标记下游产物过期；
4. Agent 只能依赖同一任务中已批准的产物。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from jobs.runtime import job_write_fence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import (
    ApprovalDecision,
    Artifact,
    ArtifactKind,
    ArtifactStatus,
    ContextManifest,
)


class ArtifactRegistryError(ValueError):
    """违反产物版本、依赖或审批约束。"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ArtifactRegistry:
    """线程安全的 SQLite 产物注册表。"""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._lock = threading.RLock()
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            timeout=15,
        )
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _init_schema(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS t_artifact (
                artifact_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                stage_no INTEGER NOT NULL,
                kind TEXT NOT NULL,
                version INTEGER NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                context_manifest TEXT NOT NULL,
                gate_report TEXT NOT NULL DEFAULT '{}',
                stale_reason TEXT NOT NULL DEFAULT '',
                source_event_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(task_id, stage_no, kind, version)
            );

            CREATE TABLE IF NOT EXISTS t_artifact_dependency (
                artifact_id TEXT NOT NULL,
                depends_on_artifact_id TEXT NOT NULL,
                PRIMARY KEY(artifact_id, depends_on_artifact_id),
                FOREIGN KEY(artifact_id) REFERENCES t_artifact(artifact_id) ON DELETE CASCADE,
                FOREIGN KEY(depends_on_artifact_id) REFERENCES t_artifact(artifact_id)
            );

            CREATE INDEX IF NOT EXISTS idx_artifact_dependency_parent
            ON t_artifact_dependency(depends_on_artifact_id);

            CREATE TABLE IF NOT EXISTS t_artifact_approval (
                approval_id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                actor TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(artifact_id) REFERENCES t_artifact(artifact_id) ON DELETE CASCADE
            );
            """
        )
        columns = {
            str(row[1]) for row in self._db.execute("PRAGMA table_info(t_artifact)").fetchall()
        }
        if "source_event_id" not in columns:
            self._db.execute(
                "ALTER TABLE t_artifact ADD COLUMN source_event_id TEXT NOT NULL DEFAULT ''"
            )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_artifact_stream "
            "ON t_artifact(task_id, stage_no, kind, version DESC)"
        )
        self._db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_artifact_source_event "
            "ON t_artifact(source_event_id) WHERE source_event_id <> ''"
        )
        self._db.commit()

    def create_version(
        self,
        *,
        task_id: str,
        stage_no: int,
        kind: ArtifactKind,
        payload: dict[str, Any],
        dependency_ids: Iterable[str] = (),
        context_manifest: ContextManifest | None = None,
        source_event_id: str = "",
    ) -> Artifact:
        """创建不可变新版本；依赖必须是同任务的已批准产物。"""
        task_id = task_id.strip()
        if not task_id:
            raise ArtifactRegistryError("task_id 不能为空")
        if stage_no < 1 or stage_no > 10:
            raise ArtifactRegistryError("stage_no 必须在 1..10")
        if not isinstance(kind, ArtifactKind):
            raise ArtifactRegistryError("kind 必须是 ArtifactKind")
        if not isinstance(payload, dict):
            raise ArtifactRegistryError("payload 必须是字典")

        dependencies = tuple(dict.fromkeys(dependency_ids))
        manifest = context_manifest or ContextManifest()
        payload_json = _json_dump(payload)
        content_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        now = _utc_now()

        with job_write_fence(task_id), self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                if source_event_id:
                    existing = self._db.execute(
                        "SELECT artifact_id FROM t_artifact WHERE source_event_id=?",
                        (source_event_id,),
                    ).fetchone()
                    if existing is not None:
                        self._db.commit()
                        return self.get(str(existing[0]))
                self._validate_dependencies(task_id, dependencies)
                row = self._db.execute(
                    "SELECT COALESCE(MAX(version), 0) AS max_version "
                    "FROM t_artifact WHERE task_id=? AND stage_no=? AND kind=?",
                    (task_id, stage_no, kind.value),
                ).fetchone()
                version = int(row["max_version"]) + 1
                artifact_id = f"ART-{uuid.uuid4().hex[:20].upper()}"
                self._db.execute(
                    "INSERT INTO t_artifact("
                    "artifact_id, task_id, stage_no, kind, version, status, payload, "
                    "content_hash, context_manifest, gate_report, stale_reason, source_event_id, "
                    "created_at, updated_at"
                    ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', '', ?, ?, ?)",
                    (
                        artifact_id,
                        task_id,
                        stage_no,
                        kind.value,
                        version,
                        ArtifactStatus.GENERATED.value,
                        payload_json,
                        content_hash,
                        _json_dump(manifest.to_dict()),
                        source_event_id,
                        now,
                        now,
                    ),
                )
                self._db.executemany(
                    "INSERT INTO t_artifact_dependency(artifact_id, depends_on_artifact_id) "
                    "VALUES(?, ?)",
                    [(artifact_id, dep_id) for dep_id in dependencies],
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return self.get(artifact_id)

    def submit_auto_gate(
        self,
        artifact_id: str,
        *,
        passed: bool,
        report: dict[str, Any] | None = None,
    ) -> Artifact:
        """提交自动验收结果；通过后才能进入用户审批。"""
        target = (
            ArtifactStatus.WAITING_APPROVAL
            if passed
            else ArtifactStatus.AUTO_REJECTED
        )
        with job_write_fence(self.get(artifact_id).task_id), self._lock:
            artifact = self.get(artifact_id)
            if artifact.status != ArtifactStatus.GENERATED:
                raise ArtifactRegistryError("只有 GENERATED 产物可以提交自动验收")
            self._db.execute(
                "UPDATE t_artifact SET status=?, gate_report=?, updated_at=? WHERE artifact_id=?",
                (target.value, _json_dump(report or {}), _utc_now(), artifact_id),
            )
            self._db.commit()
        return self.get(artifact_id)

    def decide(
        self,
        artifact_id: str,
        *,
        approved: bool,
        actor: str = "author",
        reason: str = "",
    ) -> Artifact:
        """记录用户审批；新版本批准时递归使旧版本的下游过期。"""
        with job_write_fence(self.get(artifact_id).task_id), self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                artifact = self.get(artifact_id)
                if artifact.status != ArtifactStatus.WAITING_APPROVAL:
                    raise ArtifactRegistryError("只有 WAITING_APPROVAL 产物可以审批")

                if approved:
                    previous = self._db.execute(
                        "SELECT artifact_id FROM t_artifact "
                        "WHERE task_id=? AND stage_no=? AND kind=? AND status=? AND version<? "
                        "ORDER BY version DESC LIMIT 1",
                        (
                            artifact.task_id,
                            artifact.stage_no,
                            artifact.kind.value,
                            ArtifactStatus.APPROVED.value,
                            artifact.version,
                        ),
                    ).fetchone()
                    if previous is not None:
                        previous_id = str(previous["artifact_id"])
                        self._db.execute(
                            "UPDATE t_artifact SET status=?, updated_at=? WHERE artifact_id=?",
                            (ArtifactStatus.SUPERSEDED.value, _utc_now(), previous_id),
                        )
                        self._invalidate_dependents_locked(
                            previous_id,
                            reason=f"上游产物 {previous_id} 已被批准的新版本替代",
                        )
                    new_status = ArtifactStatus.APPROVED
                    decision = ApprovalDecision.APPROVE
                else:
                    new_status = ArtifactStatus.REJECTED
                    decision = ApprovalDecision.REJECT

                now = _utc_now()
                self._db.execute(
                    "UPDATE t_artifact SET status=?, updated_at=? WHERE artifact_id=?",
                    (new_status.value, now, artifact_id),
                )
                self._db.execute(
                    "INSERT INTO t_artifact_approval("
                    "approval_id, artifact_id, decision, actor, reason, created_at"
                    ") VALUES(?, ?, ?, ?, ?, ?)",
                    (
                        f"APR-{uuid.uuid4().hex[:20].upper()}",
                        artifact_id,
                        decision.value,
                        actor.strip() or "author",
                        reason,
                        now,
                    ),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return self.get(artifact_id)

    def get(self, artifact_id: str) -> Artifact:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM t_artifact WHERE artifact_id=?",
                (artifact_id,),
            ).fetchone()
            if row is None:
                raise ArtifactRegistryError(f"产物不存在: {artifact_id}")
            dependencies = self._db.execute(
                "SELECT depends_on_artifact_id FROM t_artifact_dependency "
                "WHERE artifact_id=? ORDER BY depends_on_artifact_id",
                (artifact_id,),
            ).fetchall()
        return self._row_to_artifact(row, tuple(str(r[0]) for r in dependencies))

    def get_active(
        self,
        *,
        task_id: str,
        stage_no: int,
        kind: ArtifactKind,
    ) -> Artifact | None:
        """返回当前仍有效的最新批准版本。"""
        with self._lock:
            row = self._db.execute(
                "SELECT artifact_id FROM t_artifact "
                "WHERE task_id=? AND stage_no=? AND kind=? AND status=? "
                "ORDER BY version DESC LIMIT 1",
                (task_id, stage_no, kind.value, ArtifactStatus.APPROVED.value),
            ).fetchone()
        return self.get(str(row[0])) if row is not None else None

    def list_task(self, task_id: str) -> list[Artifact]:
        with self._lock:
            rows = self._db.execute(
                "SELECT artifact_id FROM t_artifact WHERE task_id=? "
                "ORDER BY stage_no, kind, version",
                (task_id,),
            ).fetchall()
        return [self.get(str(row[0])) for row in rows]

    def list_task_ids(self) -> list[str]:
        with self._lock:
            rows = self._db.execute(
                "SELECT DISTINCT task_id FROM t_artifact ORDER BY task_id"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def get_by_source_event(self, source_event_id: str) -> Artifact | None:
        if not source_event_id:
            return None
        with self._lock:
            row = self._db.execute(
                "SELECT artifact_id FROM t_artifact WHERE source_event_id=?",
                (source_event_id,),
            ).fetchone()
        return self.get(str(row[0])) if row is not None else None

    def delete_task(self, task_id: str) -> int:
        """删除指定任务的投影产物；FSM Outbox 仍保留审计源。"""
        with job_write_fence(task_id), self._lock:
            cur = self._db.execute("DELETE FROM t_artifact WHERE task_id=?", (task_id,))
            self._db.commit()
            return int(cur.rowcount)

    def list_approvals(self, artifact_id: str) -> list[dict[str, str]]:
        self.get(artifact_id)
        with self._lock:
            rows = self._db.execute(
                "SELECT approval_id, decision, actor, reason, created_at "
                "FROM t_artifact_approval WHERE artifact_id=? ORDER BY created_at",
                (artifact_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _validate_dependencies(self, task_id: str, dependency_ids: tuple[str, ...]) -> None:
        for dependency_id in dependency_ids:
            row = self._db.execute(
                "SELECT task_id, status FROM t_artifact WHERE artifact_id=?",
                (dependency_id,),
            ).fetchone()
            if row is None:
                raise ArtifactRegistryError(f"依赖产物不存在: {dependency_id}")
            if str(row["task_id"]) != task_id:
                raise ArtifactRegistryError("禁止跨论文任务引用产物")
            if str(row["status"]) != ArtifactStatus.APPROVED.value:
                raise ArtifactRegistryError("只能依赖已批准且仍有效的产物")

    def _invalidate_dependents_locked(self, artifact_id: str, *, reason: str) -> None:
        pending = [artifact_id]
        visited: set[str] = set()
        now = _utc_now()
        while pending:
            parent_id = pending.pop()
            rows = self._db.execute(
                "SELECT artifact_id FROM t_artifact_dependency "
                "WHERE depends_on_artifact_id=?",
                (parent_id,),
            ).fetchall()
            for row in rows:
                child_id = str(row[0])
                if child_id in visited:
                    continue
                visited.add(child_id)
                self._db.execute(
                    "UPDATE t_artifact SET status=?, stale_reason=?, updated_at=? "
                    "WHERE artifact_id=? AND status NOT IN (?, ?)",
                    (
                        ArtifactStatus.STALE.value,
                        reason,
                        now,
                        child_id,
                        ArtifactStatus.REJECTED.value,
                        ArtifactStatus.SUPERSEDED.value,
                    ),
                )
                pending.append(child_id)

    @staticmethod
    def _row_to_artifact(row: sqlite3.Row, dependencies: tuple[str, ...]) -> Artifact:
        return Artifact(
            artifact_id=str(row["artifact_id"]),
            task_id=str(row["task_id"]),
            stage_no=int(row["stage_no"]),
            kind=ArtifactKind(str(row["kind"])),
            version=int(row["version"]),
            status=ArtifactStatus(str(row["status"])),
            payload=json.loads(str(row["payload"])),
            content_hash=str(row["content_hash"]),
            dependency_ids=dependencies,
            context_manifest=ContextManifest.from_dict(
                json.loads(str(row["context_manifest"]))
            ),
            gate_report=json.loads(str(row["gate_report"])),
            stale_reason=str(row["stale_reason"]),
            source_event_id=str(row["source_event_id"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
