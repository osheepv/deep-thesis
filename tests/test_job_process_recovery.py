"""Real process termination, socket loss and competing SQLite workers."""

import multiprocessing
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from jobs import JobRegistry, JobRegistryError, JobStatus, JobWorker
from jobs import JobRuntime, Pricing


def _crash_worker(database, ready):
    registry = JobRegistry(database)

    def wait_for_termination(job):
        registry.record_usage(job.job_id, input_tokens=12, output_tokens=8, cost=0.01)
        ready.set()
        threading.Event().wait(45)
        return {"unexpected": True}

    JobWorker(registry, {"crash": wait_for_termination}, lease_seconds=10).run_once()


def _drain_worker(database, ready, start):
    registry = JobRegistry(database)
    ready.set()
    if not start.wait(15):
        raise RuntimeError("worker start timed out")
    worker = JobWorker(registry, {"fast": lambda job: {"job_id": job.job_id}})
    while worker.run_once() is not None:
        pass
    registry.close()


def test_killed_worker_recovers_after_real_lease_expiry(tmp_path):
    database = str(tmp_path / "jobs.db")
    registry = JobRegistry(database)
    job = registry.create(task_id="crash", session_id="test", operation="crash")
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    process = context.Process(target=_crash_worker, args=(database, ready))
    process.start()
    try:
        assert ready.wait(15), "child did not enter handler"
        process.kill()
        process.join(5)
        assert not process.is_alive()
        assert registry.claim_next("early") is None
        deadline = time.monotonic() + 18
        recovered = None
        while time.monotonic() < deadline:
            recovered = registry.claim_next("replacement", lease_seconds=10)
            if recovered is not None:
                break
            time.sleep(0.1)
        assert recovered is not None
        assert recovered.job_id == job.job_id
        assert recovered.attempt == 2
        assert recovered.input_tokens + recovered.output_tokens == 20
        assert recovered.cost_used == pytest.approx(0.01)
        registry.complete(job.job_id, "replacement", {"recovered": True})
        registry.close()
        registry = JobRegistry(database)
        assert registry.get_by_id(job.job_id).result == {"recovered": True}
    finally:
        if process.is_alive():
            process.kill()
        process.join(5)
        registry.close()


def test_competing_processes_execute_each_job_once(tmp_path):
    database = str(tmp_path / "jobs.db")
    registry = JobRegistry(database)
    jobs = [registry.create(task_id="parallel", session_id="test", operation="fast")
            for _ in range(24)]
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    ready = [context.Event() for _ in range(3)]
    processes = [context.Process(target=_drain_worker, args=(database, event, start))
                 for event in ready]
    try:
        for process in processes:
            process.start()
        assert all(event.wait(15) for event in ready)
        start.set()
        for process in processes:
            process.join(20)
            assert process.exitcode == 0
        for job in jobs:
            saved = registry.get_by_id(job.job_id)
            assert saved.status == JobStatus.SUCCEEDED
            assert saved.attempt == 1
            assert saved.result == {"job_id": job.job_id}
    finally:
        for process in processes:
            if process.is_alive():
                process.kill()
            process.join(5)
        registry.close()


def test_socket_disconnect_then_manual_retry_retains_usage(tmp_path):
    registry = JobRegistry(tmp_path / "jobs.db")
    job = registry.create(task_id="network", session_id="test", operation="socket",
                          max_attempts=1, token_budget=100)

    def disconnected_handler(current):
        registry.record_usage(current.job_id, input_tokens=3, output_tokens=2, cost=0)
        local, remote = socket.socketpair()
        try:
            local.settimeout(2)
            remote.close()
            if local.recv(1) == b"":
                raise ConnectionError("peer closed before response")
        finally:
            local.close()
            remote.close()

    try:
        worker = JobWorker(registry, {"socket": disconnected_handler})
        assert worker.run_once().status == JobStatus.FAILED
        assert registry.retry("network", job.job_id).input_tokens == 3
        worker.handlers["socket"] = lambda current: {"restored": True}
        assert worker.run_once().status == JobStatus.SUCCEEDED
        assert registry.get_by_id(job.job_id).output_tokens == 2
    finally:
        registry.close()


def test_worker_keeps_polling_after_lease_transfer(tmp_path):
    database = tmp_path / "jobs.db"
    registry = JobRegistry(database)
    other = JobRegistry(database)
    first = registry.create(task_id="transfer", session_id="test", operation="transfer")
    second = registry.create(task_id="next", session_id="test", operation="fast")
    continued = threading.Event()

    def transfer(current):
        other.fail(current.job_id, "old", "handover", retry_delay_seconds=0)
        replacement = other.claim_next("new")
        assert replacement.job_id == first.job_id
        other.complete(first.job_id, "new", {"owner": "new"})
        return {"owner": "old"}

    def next_job(current):
        continued.set()
        return {"next": True}

    worker = JobWorker(registry, {"transfer": transfer, "fast": next_job}, worker_id="old")
    try:
        worker.start()
        assert continued.wait(5), "lost lease stopped worker polling"
        worker.stop()
        assert registry.get_by_id(first.job_id).result == {"owner": "new"}
        assert registry.get_by_id(second.job_id).status == JobStatus.SUCCEEDED
    finally:
        worker.stop()
        registry.close()
        other.close()


def test_expired_owner_cannot_renew_complete_or_start_model_call(tmp_path):
    registry = JobRegistry(tmp_path / "jobs.db")
    job = registry.create(task_id="expiry", session_id="test", operation="fast")
    registry.claim_next("old")
    registry._db.execute(
        "UPDATE t_job_run SET lease_expires_at=? WHERE job_id=?",
        ("2000-01-01T00:00:00Z", job.job_id),
    )
    registry._db.commit()
    runtime = JobRuntime(registry, job.job_id, "old", Pricing())
    try:
        with pytest.raises(JobRegistryError):
            registry.heartbeat(job.job_id, "old")
        with pytest.raises(JobRegistryError):
            registry.complete(job.job_id, "old", {"stale": True})
        with pytest.raises(JobRegistryError):
            runtime.before_llm(10, 20)
        assert registry.claim_next("new").attempt == 2
    finally:
        registry.close()


@pytest.mark.parametrize("operation", ["heartbeat", "cancel", "retry"])
def test_state_changes_do_not_overwrite_new_owner(tmp_path, monkeypatch, operation):
    database = tmp_path / "jobs.db"
    registry = JobRegistry(database)
    other = JobRegistry(database)
    job = registry.create(task_id="race", session_id="test", operation="fast")
    registry.claim_next("old")
    if operation == "retry":
        registry.fail(job.job_id, "old", "failure", retryable=False)
    reached = threading.Event()
    changed = threading.Event()
    original = registry.get if operation != "heartbeat" else registry.get_by_id

    def paused_read(*args, **kwargs):
        snapshot = original(*args, **kwargs)
        if not reached.is_set():
            reached.set()
            assert changed.wait(5)
        return snapshot

    monkeypatch.setattr(registry, "get" if operation != "heartbeat" else "get_by_id", paused_read)

    def concurrent_change():
        assert reached.wait(5)
        if operation == "retry":
            other.retry("race", job.job_id)
            other.claim_next("new")
        else:
            other.complete(job.job_id, "old", {"done": True})
        changed.set()

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(concurrent_change)
            if operation == "heartbeat":
                with pytest.raises(JobRegistryError):
                    registry.heartbeat(job.job_id, "old")
            elif operation == "cancel":
                assert registry.request_cancel("race", job.job_id).status == JobStatus.SUCCEEDED
            else:
                with pytest.raises(JobRegistryError):
                    registry.retry("race", job.job_id)
            future.result(timeout=5)
        current = other.get_by_id(job.job_id)
        if operation == "retry":
            assert current.lease_owner == "new"
            assert current.status == JobStatus.RUNNING
        else:
            assert current.status == JobStatus.SUCCEEDED
            assert current.lease_expires_at == ""
    finally:
        changed.set()
        registry.close()
        other.close()
