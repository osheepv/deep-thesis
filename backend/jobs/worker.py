"""可独立轮询、也可由应用生命周期托管的轻量 Worker。"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from typing import Any

from .models import JobRun
from .registry import (
    JobBudgetExceededError,
    JobCancelledError,
    JobRegistry,
    JobRegistryError,
    PermanentJobError,
)
from .runtime import JobRuntime, Pricing, job_runtime_context

logger = logging.getLogger("thesis.jobs")
JobHandler = Callable[[JobRun], dict[str, Any]]


class JobWorker:
    def __init__(
        self,
        registry: JobRegistry,
        handlers: dict[str, JobHandler],
        *,
        worker_id: str = "",
        poll_interval: float = 0.5,
        lease_seconds: int = 120,
        pricing: Pricing | None = None,
    ) -> None:
        self.registry = registry
        self.handlers = dict(handlers)
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:12]}"
        self.poll_interval = max(0.05, poll_interval)
        self.lease_seconds = max(10, lease_seconds)
        self.pricing = pricing or Pricing.from_env()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name=f"thesis-{self.worker_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, timeout))

    def run_forever(self) -> None:
        self._loop()

    def run_once(self) -> JobRun | None:
        job = self.registry.claim_next(
            self.worker_id, lease_seconds=self.lease_seconds
        )
        if job is None:
            return None
        runtime = JobRuntime(
            registry=self.registry,
            job_id=job.job_id,
            worker_id=self.worker_id,
            pricing=self.pricing,
            lease_token=job.lease_token,
        )
        handler = self.handlers.get(job.operation)
        if handler is None:
            return self.registry.fail(
                job.job_id,
                self.worker_id,
                f"未注册作业处理器: {job.operation}",
                retryable=False,
                lease_token=job.lease_token,
            )
        heartbeat_stop = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(job.job_id, heartbeat_stop, job.lease_token),
            name=f"heartbeat-{job.job_id}",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            with job_runtime_context(runtime):
                runtime.check_cancelled()
                result = handler(job)
                runtime.check_cancelled()
            return self.registry.complete(
                job.job_id, self.worker_id, result, lease_token=job.lease_token
            )
        except JobCancelledError as exc:
            return self.registry.fail(
                job.job_id, self.worker_id, str(exc), retryable=False, lease_token=job.lease_token
            )
        except JobBudgetExceededError as exc:
            return self.registry.fail(
                job.job_id, self.worker_id, str(exc), retryable=False, lease_token=job.lease_token
            )
        except PermanentJobError as exc:
            return self.registry.fail(
                job.job_id, self.worker_id, str(exc), retryable=False, lease_token=job.lease_token
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("后台作业执行失败 %s", job.job_id)
            return self.registry.fail(
                job.job_id, self.worker_id, str(exc), retryable=True, lease_token=job.lease_token
            )
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self.run_once()
            except JobRegistryError:
                logger.exception("Worker 租约或作业状态已变化，继续轮询")
                self._stop.wait(self.poll_interval)
                continue
            if job is None:
                self._stop.wait(self.poll_interval)

    def _heartbeat_loop(self, job_id: str, stop: threading.Event, lease_token: str) -> None:
        interval = max(2.0, self.lease_seconds / 3)
        while not stop.wait(interval):
            try:
                self.registry.heartbeat(
                    job_id, self.worker_id, lease_seconds=self.lease_seconds,
                    lease_token=lease_token,
                )
            except Exception:  # noqa: BLE001 - 作业已结束或租约已转移
                return
