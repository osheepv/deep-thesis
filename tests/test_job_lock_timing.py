"""Lease deadlines must use the clock after SQLite write-lock acquisition."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading

import pytest

from jobs import JobRegistry, JobRegistryError, JobStatus


class _LockArrival:
    def __init__(self, connection, arrived):
        self.connection = connection
        self.arrived = arrived

    def execute(self, statement, *args):
        if statement.startswith(("BEGIN IMMEDIATE", "UPDATE t_job_run")):
            self.arrived.set()
        return self.connection.execute(statement, *args)

    def __getattr__(self, name):
        return getattr(self.connection, name)


@pytest.mark.parametrize("operation", ["claim", "heartbeat", "recover"])
def test_lease_clock_is_sampled_after_lock_wait(tmp_path, monkeypatch, operation):
    current_time = [datetime(2026, 9, 6, tzinfo=timezone.utc)]
    monkeypatch.setattr("jobs.registry._utc_now_dt", lambda: current_time[0])
    registry = JobRegistry(tmp_path / "jobs.db")
    blocker = JobRegistry(tmp_path / "jobs.db")
    job = registry.create(task_id="task", session_id="test", operation="work")
    claimed = registry.claim_next("worker", lease_seconds=10) if operation != "claim" else None
    arrived = threading.Event()
    registry._db = _LockArrival(registry._db, arrived)

    def mutate():
        if operation == "claim":
            return registry.claim_next("worker", lease_seconds=60)
        if operation == "recover":
            return registry.recover_expired()
        return registry.heartbeat(job.job_id, "worker", lease_token=claimed.lease_token)

    try:
        blocker._db.execute("BEGIN IMMEDIATE")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(mutate)
            try:
                assert arrived.wait(5)
                current_time[0] += timedelta(seconds=11)
            finally:
                blocker._db.commit()
            if operation == "heartbeat":
                with pytest.raises(JobRegistryError):
                    future.result(timeout=5)
                assert registry.get_by_id(job.job_id).lease_expires_at == claimed.lease_expires_at
            elif operation == "recover":
                assert future.result(timeout=5) == 1
                assert registry.get_by_id(job.job_id).status == JobStatus.PENDING
            else:
                result = future.result(timeout=5)
                expected = current_time[0] + timedelta(seconds=60)
                assert datetime.fromisoformat(result.lease_expires_at) == expected
    finally:
        blocker.close()
        registry.close()
