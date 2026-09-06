"""后台作业上下文：协作取消与 LLM Token/费用预算。"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from .registry import JobRegistry


@dataclass(frozen=True)
class Pricing:
    input_per_million: float = 0.0
    output_per_million: float = 0.0

    @classmethod
    def from_env(cls) -> "Pricing":
        return cls(
            input_per_million=float(os.getenv("THESIS_LLM_INPUT_COST_PER_MILLION", "0") or 0),
            output_per_million=float(os.getenv("THESIS_LLM_OUTPUT_COST_PER_MILLION", "0") or 0),
        )

    def calculate(self, input_tokens: int, output_tokens: int) -> float:
        return (
            max(0, input_tokens) * self.input_per_million
            + max(0, output_tokens) * self.output_per_million
        ) / 1_000_000


@dataclass
class JobRuntime:
    registry: JobRegistry
    job_id: str
    worker_id: str
    pricing: Pricing

    def check_cancelled(self) -> None:
        self.registry.raise_if_cancelled(self.job_id)
        self.registry.assert_active_lease(self.job_id, self.worker_id)

    def before_llm(self, estimated_input_tokens: int, max_output_tokens: int) -> None:
        self.check_cancelled()
        estimated_cost = self.pricing.calculate(
            estimated_input_tokens, max_output_tokens
        )
        self.registry.assert_budget(
            self.job_id,
            estimated_input_tokens=estimated_input_tokens,
            max_output_tokens=max_output_tokens,
            estimated_cost=estimated_cost,
        )

    def record_llm_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.registry.record_usage(
            self.job_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=self.pricing.calculate(input_tokens, output_tokens),
        )
        self.check_cancelled()


_CURRENT_RUNTIME: ContextVar[JobRuntime | None] = ContextVar(
    "thesis_job_runtime", default=None
)


def get_current_job_runtime() -> JobRuntime | None:
    return _CURRENT_RUNTIME.get()


def get_current_job_id() -> str:
    runtime = get_current_job_runtime()
    return runtime.job_id if runtime is not None else ""


@contextmanager
def job_runtime_context(runtime: JobRuntime) -> Iterator[None]:
    token = _CURRENT_RUNTIME.set(runtime)
    try:
        yield
    finally:
        _CURRENT_RUNTIME.reset(token)
