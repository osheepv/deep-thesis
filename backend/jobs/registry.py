"""SQLite JobRun 注册表：租约、恢复、取消、重试和预算原子更新。"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import JobRun, JobStatus, TERMINAL_JOB_STATUSES


class JobRegistryError(ValueError):
    """作业状态、租约、隔离或预算约束错误。"""


class JobCancelledError(RuntimeError):
    """作业已收到取消请求。"""


class JobBudgetExceededError(RuntimeError):
    """Token 或费用预算不足。"""


class PermanentJobError(RuntimeError):
    """业务输入或 Gate 失败；不应自动重试。"""


def _utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _utc_now() -> str:
    return _to_iso(_utc_now_dt())


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class JobRegistry:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._lock = threading.RLock()
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self._db_path, check_same_thread=False, timeout=15)
        self._db.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _init_schema(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS t_job_run (
                job_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                session_id TEXT NOT NULL DEFAULT '',
                operation TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL,
                idempotency_key TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '',
                attempt INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                priority INTEGER NOT NULL DEFAULT 0,
                token_budget INTEGER NOT NULL DEFAULT 0,
                cost_budget REAL NOT NULL DEFAULT 0,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cost_used REAL NOT NULL DEFAULT 0,
                lease_owner TEXT NOT NULL DEFAULT '',
                lease_expires_at TEXT NOT NULL DEFAULT '',
                not_before TEXT NOT NULL DEFAULT '',
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                started_at TEXT NOT NULL DEFAULT '',
                finished_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_job_claim
            ON t_job_run(status, not_before, priority DESC, created_at);

            CREATE INDEX IF NOT EXISTS idx_job_task
            ON t_job_run(task_id, created_at DESC);

            CREATE UNIQUE INDEX IF NOT EXISTS uq_job_idempotency
            ON t_job_run(task_id, idempotency_key) WHERE idempotency_key <> '';
            """
        )
        self._db.commit()

        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                columns = {row[1] for row in self._db.execute("PRAGMA table_info(t_job_run)")}
                if "lease_token" not in columns:
                    self._db.execute("ALTER TABLE t_job_run ADD COLUMN lease_token TEXT NOT NULL DEFAULT ''")
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise

    def create(
        self,
        *,
        task_id: str,
        session_id: str,
        operation: str,
        payload: dict[str, Any] | None = None,
        idempotency_key: str = "",
        max_attempts: int = 3,
        priority: int = 0,
        token_budget: int = 0,
        cost_budget: float = 0.0,
    ) -> JobRun:
        if not task_id.strip():
            raise JobRegistryError("task_id 不能为空")
        if not operation.strip():
            raise JobRegistryError("operation 不能为空")
        if max_attempts < 1 or max_attempts > 10:
            raise JobRegistryError("max_attempts 必须在 1..10")
        if token_budget < 0 or cost_budget < 0:
            raise JobRegistryError("预算不能为负数")
        idempotency_key = idempotency_key.strip()
        with self._lock:
            if idempotency_key:
                row = self._db.execute(
                    "SELECT job_id FROM t_job_run WHERE task_id=? AND idempotency_key=?",
                    (task_id, idempotency_key),
                ).fetchone()
                if row is not None:
                    return self.get(task_id, str(row["job_id"]))
            job_id = f"JOB-{uuid.uuid4().hex[:20].upper()}"
            now = _utc_now()
            self._db.execute(
                "INSERT INTO t_job_run(job_id, task_id, session_id, operation, payload, status, "
                "idempotency_key, max_attempts, priority, token_budget, cost_budget, created_at, "
                "updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id, task_id, session_id.strip(), operation.strip(),
                    _json_dump(payload or {}), JobStatus.PENDING.value, idempotency_key,
                    max_attempts, priority, token_budget, cost_budget, now, now,
                ),
            )
            self._db.commit()
        return self.get(task_id, job_id)

    def get(self, task_id: str, job_id: str) -> JobRun:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM t_job_run WHERE task_id=? AND job_id=?",
                (task_id, job_id),
            ).fetchone()
        if row is None:
            raise JobRegistryError(f"当前任务中不存在作业: {job_id}")
        return self._row_to_job(row)

    def list_task(self, task_id: str, *, limit: int = 100) -> list[JobRun]:
        limit = min(max(int(limit), 1), 500)
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM t_job_run WHERE task_id=? ORDER BY created_at DESC LIMIT ?",
                (task_id, limit),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def list_task_ids(self) -> list[str]:
        with self._lock:
            rows = self._db.execute(
                "SELECT DISTINCT task_id FROM t_job_run ORDER BY task_id"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def recover_expired(self) -> int:
        """启动或巡检时恢复过期 Worker 租约，返回受影响作业数。"""
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                recovered = self._recover_expired_locked(_utc_now())
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return recovered

    def claim_next(self, worker_id: str, *, lease_seconds: int = 60) -> JobRun | None:
        if not worker_id.strip():
            raise JobRegistryError("worker_id 不能为空")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                now_dt = _utc_now_dt()
                now = _to_iso(now_dt)
                lease_expires = _to_iso(now_dt + timedelta(seconds=max(10, lease_seconds)))
                self._recover_expired_locked(now)
                row = self._db.execute(
                    "SELECT job_id FROM t_job_run WHERE status=? "
                    "AND (not_before='' OR not_before<=?) "
                    "ORDER BY priority DESC, created_at LIMIT 1",
                    (JobStatus.PENDING.value, now),
                ).fetchone()
                if row is None:
                    self._db.commit()
                    return None
                job_id = str(row["job_id"])
                self._db.execute(
                    "UPDATE t_job_run SET status=?, attempt=attempt+1, lease_owner=?, lease_token=?, "
                    "lease_expires_at=?, started_at=CASE WHEN started_at='' THEN ? ELSE started_at END, "
                    "updated_at=? WHERE job_id=? AND status=?",
                    (
                        JobStatus.RUNNING.value, worker_id, uuid.uuid4().hex, lease_expires, now, now,
                        job_id, JobStatus.PENDING.value,
                    ),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return self.get_by_id(job_id)

    def get_by_id(self, job_id: str) -> JobRun:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM t_job_run WHERE job_id=?", (job_id,)
            ).fetchone()
        if row is None:
            raise JobRegistryError(f"作业不存在: {job_id}")
        return self._row_to_job(row)

    def heartbeat(self, job_id: str, worker_id: str, *, lease_seconds: int = 60,
                  lease_token: str | None = None) -> JobRun:
        job = self.get_by_id(job_id)
        if job.lease_owner != worker_id or job.status not in {
            JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED
        }:
            raise JobRegistryError("作业租约不属于当前 Worker")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                now_dt = _utc_now_dt()
                now = _to_iso(now_dt)
                lease = _to_iso(now_dt + timedelta(seconds=max(10, lease_seconds)))
                cursor = self._db.execute(
                    "UPDATE t_job_run SET lease_expires_at=?, updated_at=? WHERE job_id=? "
                    "AND lease_owner=? AND status IN (?, ?) AND lease_expires_at>? "
                    "AND (? IS NULL OR lease_token=?)",
                    (lease, now, job_id, worker_id, JobStatus.RUNNING.value,
                     JobStatus.CANCEL_REQUESTED.value, now, lease_token, lease_token),
                )
                if cursor.rowcount != 1:
                    raise JobRegistryError("作业租约已失效，不能续租")
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return self.get_by_id(job_id)

    def complete(self, job_id: str, worker_id: str, result: dict[str, Any], *,
                 lease_token: str | None = None) -> JobRun:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                job = self.get_by_id(job_id)
                self._assert_lease(job, worker_id, lease_token)
                cancelled = job.cancel_requested or job.status == JobStatus.CANCEL_REQUESTED
                status = JobStatus.CANCELLED if cancelled else JobStatus.SUCCEEDED
                self._db.execute(
                    "UPDATE t_job_run SET status=?, result=?, error='', lease_owner='', "
                    "lease_expires_at='', finished_at=?, updated_at=? WHERE job_id=?",
                    (
                        status.value, _json_dump({} if cancelled else result),
                        _utc_now(), _utc_now(), job_id,
                    ),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return self.get_by_id(job_id)

    def fail(
        self, job_id: str, worker_id: str, error: str, *, retryable: bool = True,
        retry_delay_seconds: int = 2,
        lease_token: str | None = None,
    ) -> JobRun:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                job = self.get_by_id(job_id)
                self._assert_lease(job, worker_id, lease_token)
                if job.cancel_requested or job.status == JobStatus.CANCEL_REQUESTED:
                    status = JobStatus.CANCELLED
                    not_before = ""
                elif retryable and job.attempt < job.max_attempts:
                    status = JobStatus.PENDING
                    not_before = _to_iso(
                        _utc_now_dt() + timedelta(seconds=max(0, retry_delay_seconds))
                    )
                else:
                    status = JobStatus.FAILED
                    not_before = ""
                finished_at = _utc_now() if status in TERMINAL_JOB_STATUSES else ""
                self._db.execute(
                    "UPDATE t_job_run SET status=?, error=?, lease_owner='', lease_expires_at='', "
                    "not_before=?, finished_at=?, updated_at=? WHERE job_id=?",
                    (
                        status.value, error[:4000], not_before, finished_at,
                        _utc_now(), job_id,
                    ),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return self.get_by_id(job_id)

    def request_cancel(self, task_id: str, job_id: str) -> JobRun:
        job = self.get(task_id, job_id)
        if job.status in TERMINAL_JOB_STATUSES:
            return job
        with self._lock:
            self._db.execute(
                "UPDATE t_job_run SET status=CASE WHEN status=? THEN ? ELSE ? END, "
                "cancel_requested=1, finished_at=CASE WHEN status=? THEN ? ELSE '' END, "
                "updated_at=? WHERE task_id=? AND job_id=? AND status IN (?, ?, ?)",
                (JobStatus.PENDING.value, JobStatus.CANCELLED.value,
                 JobStatus.CANCEL_REQUESTED.value, JobStatus.PENDING.value,
                 _utc_now(), _utc_now(), task_id, job_id, JobStatus.PENDING.value,
                 JobStatus.RUNNING.value, JobStatus.CANCEL_REQUESTED.value),
            )
            self._db.commit()
        return self.get(task_id, job_id)

    def retry(self, task_id: str, job_id: str) -> JobRun:
        job = self.get(task_id, job_id)
        if job.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
            raise JobRegistryError("只有 FAILED/CANCELLED 作业可以人工重试")
        with self._lock:
            cursor = self._db.execute(
                "UPDATE t_job_run SET status=?, error='', result='{}', attempt=0, "
                "cancel_requested=0, lease_owner='', lease_expires_at='', not_before='', "
                "started_at='', finished_at='', updated_at=? WHERE task_id=? AND job_id=? "
                "AND status IN (?, ?) AND updated_at=?",
                (JobStatus.PENDING.value, _utc_now(), task_id, job_id,
                 JobStatus.FAILED.value, JobStatus.CANCELLED.value, job.updated_at),
            )
            self._db.commit()
            if cursor.rowcount != 1:
                raise JobRegistryError("作业状态已变化，请刷新后重试")
        return self.get(task_id, job_id)

    def raise_if_cancelled(self, job_id: str) -> None:
        job = self.get_by_id(job_id)
        if job.cancel_requested or job.status == JobStatus.CANCEL_REQUESTED:
            raise JobCancelledError(f"作业已取消: {job_id}")

    def assert_active_lease(self, job_id: str, worker_id: str, lease_token: str | None = None) -> None:
        job = self.get_by_id(job_id)
        self._assert_lease(job, worker_id)
        if lease_token is not None and job.lease_token != lease_token:
            raise JobRegistryError("作业执行凭证已失效")

    @contextmanager
    def write_fence(self, job_id: str, worker_id: str, lease_token: str, task_id: str):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                job = self.get_by_id(job_id)
                self.assert_active_lease(job_id, worker_id, lease_token)
                if job.task_id != task_id:
                    raise JobRegistryError("后台作业不能写入其他任务")
                self.raise_if_cancelled(job_id)
                yield
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise

    def assert_budget(
        self,
        job_id: str,
        *,
        estimated_input_tokens: int,
        max_output_tokens: int,
        estimated_cost: float,
    ) -> None:
        job = self.get_by_id(job_id)
        self.raise_if_cancelled(job_id)
        projected_tokens = (
            job.input_tokens + job.output_tokens
            + max(0, estimated_input_tokens) + max(0, max_output_tokens)
        )
        if job.token_budget > 0 and projected_tokens > job.token_budget:
            raise JobBudgetExceededError(
                f"Token 预算不足: projected={projected_tokens}, budget={job.token_budget}"
            )
        if job.cost_budget > 0 and job.cost_used + max(0.0, estimated_cost) > job.cost_budget:
            raise JobBudgetExceededError(
                f"费用预算不足: projected={job.cost_used + estimated_cost:.6f}, "
                f"budget={job.cost_budget:.6f}"
            )

    def record_usage(
        self, job_id: str, *, input_tokens: int, output_tokens: int, cost: float
    ) -> JobRun:
        with self._lock:
            self._db.execute(
                "UPDATE t_job_run SET input_tokens=input_tokens+?, output_tokens=output_tokens+?, "
                "cost_used=cost_used+?, updated_at=? WHERE job_id=?",
                (
                    max(0, input_tokens), max(0, output_tokens), max(0.0, cost),
                    _utc_now(), job_id,
                ),
            )
            self._db.commit()
        return self.get_by_id(job_id)

    def delete_task(self, task_id: str) -> int:
        with self._lock:
            cur = self._db.execute("DELETE FROM t_job_run WHERE task_id=?", (task_id,))
            self._db.commit()
            return int(cur.rowcount)

    def _recover_expired_locked(self, now: str) -> int:
        rows = self._db.execute(
            "SELECT * FROM t_job_run WHERE status IN (?, ?) AND lease_expires_at<>'' "
            "AND lease_expires_at<=?",
            (JobStatus.RUNNING.value, JobStatus.CANCEL_REQUESTED.value, now),
        ).fetchall()
        for row in rows:
            job = self._row_to_job(row)
            if job.cancel_requested or job.status == JobStatus.CANCEL_REQUESTED:
                status = JobStatus.CANCELLED
                finished = now
            elif job.attempt >= job.max_attempts:
                status = JobStatus.FAILED
                finished = now
            else:
                status = JobStatus.PENDING
                finished = ""
            self._db.execute(
                "UPDATE t_job_run SET status=?, error=?, lease_owner='', lease_expires_at='', "
                "finished_at=?, updated_at=? WHERE job_id=?",
                (
                    status.value, "Worker 租约过期，已恢复" if status == JobStatus.PENDING
                    else "Worker 租约过期", finished, now, job.job_id,
                ),
            )
        return len(rows)

    @staticmethod
    def _assert_lease(job: JobRun, worker_id: str, lease_token: str | None = None) -> None:
        if job.lease_owner != worker_id or job.status not in {
            JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED
        } or not job.lease_expires_at or job.lease_expires_at <= _utc_now():
            raise JobRegistryError("作业租约不属于当前 Worker")
        if lease_token is not None and job.lease_token != lease_token:
            raise JobRegistryError("作业执行凭证已失效")

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> JobRun:
        return JobRun(
            job_id=str(row["job_id"]), task_id=str(row["task_id"]),
            session_id=str(row["session_id"]), operation=str(row["operation"]),
            payload=json.loads(str(row["payload"])), status=JobStatus(str(row["status"])),
            idempotency_key=str(row["idempotency_key"]),
            result=json.loads(str(row["result"])), error=str(row["error"]),
            attempt=int(row["attempt"]), max_attempts=int(row["max_attempts"]),
            priority=int(row["priority"]), token_budget=int(row["token_budget"]),
            cost_budget=float(row["cost_budget"]), input_tokens=int(row["input_tokens"]),
            output_tokens=int(row["output_tokens"]), cost_used=float(row["cost_used"]),
            lease_owner=str(row["lease_owner"]), lease_expires_at=str(row["lease_expires_at"]),
            lease_token=str(row["lease_token"]),
            not_before=str(row["not_before"]), cancel_requested=bool(row["cancel_requested"]),
            created_at=str(row["created_at"]), started_at=str(row["started_at"]),
            finished_at=str(row["finished_at"]), updated_at=str(row["updated_at"]),
        )
