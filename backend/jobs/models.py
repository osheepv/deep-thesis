"""持久化后台作业与预算状态。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_JOB_STATUSES = {
    JobStatus.SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}


@dataclass(frozen=True)
class JobRun:
    job_id: str
    task_id: str
    session_id: str
    operation: str
    payload: dict[str, Any]
    status: JobStatus
    idempotency_key: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    attempt: int = 0
    max_attempts: int = 3
    priority: int = 0
    token_budget: int = 0
    cost_budget: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_used: float = 0.0
    lease_owner: str = ""
    lease_token: str = ""
    lease_expires_at: str = ""
    not_before: str = ""
    cancel_requested: bool = False
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        value["tokens_used"] = self.input_tokens + self.output_tokens
        value["tokens_remaining"] = (
            max(0, self.token_budget - value["tokens_used"])
            if self.token_budget > 0
            else None
        )
        value["cost_remaining"] = (
            max(0.0, self.cost_budget - self.cost_used)
            if self.cost_budget > 0
            else None
        )
        return value
