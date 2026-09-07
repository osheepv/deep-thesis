"""Persisted business checkpoints survive process death and late old workers."""

import multiprocessing
from pathlib import Path
import time

import pytest

from application.service.task_store import TaskRecord, TaskStore
from artifacts import ArtifactKind, ArtifactRegistry
from jobs import JobRegistry, JobRegistryError, JobStatus, JobWorker


class _LostHeartbeatWorker(JobWorker):
    def _heartbeat_loop(self, job_id, stop, lease_token):
        stop.wait(45)


def _checkpoint_process(directory, ready, release, rejected):
    directory = Path(directory)
    registry = JobRegistry(directory / "jobs.db")
    store = TaskStore(str(directory / "tasks.db"))
    artifacts = ArtifactRegistry(directory / "artifacts.db")

    def handler(job):
        record = store.get(job.task_id)
        record.ring6 = {"chapters": [{"chapter_no": 1, "content": "saved chapter"}]}
        store.put(record)
        artifacts.create_version(
            task_id=job.task_id, stage_no=6, kind=ArtifactKind.SECTION_DRAFT,
            payload={"content": "saved chapter"},
        )
        ready.set()
        if not release.wait(40):
            raise TimeoutError("replacement did not release old handler")
        record.ring6 = {"chapters": [{"chapter_no": 1, "content": "late old chapter"}]}
        with pytest.raises(JobRegistryError):
            store.put(record)
        with pytest.raises(JobRegistryError):
            artifacts.create_version(
                task_id=job.task_id, stage_no=6, kind=ArtifactKind.SECTION_DRAFT,
                payload={"content": "late old chapter"},
            )
        return {"owner": "old"}

    try:
        worker = _LostHeartbeatWorker(
            registry, {"write": handler}, worker_id="shared-worker", lease_seconds=10,
        )
        try:
            worker.run_once()
        except JobRegistryError:
            rejected.set()
        else:
            raise AssertionError("old worker unexpectedly completed")
    finally:
        artifacts.close()
        store._db.close()
        registry.close()


@pytest.mark.parametrize("failure", ["kill", "lost_heartbeat"])
def test_process_takeover_preserves_and_extends_checkpoint(tmp_path, failure):
    registry = JobRegistry(tmp_path / "jobs.db")
    store = TaskStore(str(tmp_path / "tasks.db"))
    artifacts = ArtifactRegistry(tmp_path / "artifacts.db")
    store.put(TaskRecord("task", "checkpoint recovery", "MASTER", "AI"))
    job = registry.create(task_id="task", session_id="test", operation="write")
    context = multiprocessing.get_context("spawn")
    ready, release, rejected = (context.Event() for _ in range(3))
    process = context.Process(
        target=_checkpoint_process, args=(str(tmp_path), ready, release, rejected),
    )
    process.start()

    def resume(current):
        assert current.attempt == 2
        record = store.get(current.task_id)
        assert record.ring6["chapters"] == [{"chapter_no": 1, "content": "saved chapter"}]
        record.ring6["chapters"].append({"chapter_no": 2, "content": "new chapter"})
        store.put(record)
        artifacts.create_version(
            task_id=current.task_id, stage_no=6, kind=ArtifactKind.SECTION_DRAFT,
            payload={"content": "new chapter"},
        )
        if failure == "lost_heartbeat":
            release.set()
            assert rejected.wait(10), "old worker failed to reject late writes"
            process.join(5)
            assert process.exitcode == 0
        return {"chapters": 2}

    try:
        assert ready.wait(15), "child did not persist its checkpoint"
        old = registry.get_by_id(job.job_id)
        if failure == "kill":
            process.kill()
            process.join(5)
            assert not process.is_alive()
        replacement = JobWorker(registry, {"write": resume}, worker_id="shared-worker")
        assert replacement.run_once() is None
        deadline = time.monotonic() + 20
        result = None
        while time.monotonic() < deadline:
            result = replacement.run_once()
            if result is not None:
                break
            time.sleep(0.1)
        assert result is not None
        assert result.status == JobStatus.SUCCEEDED
        assert result.lease_token != old.lease_token
        assert result.result == {"chapters": 2}
    finally:
        if process.is_alive():
            process.kill()
        process.join(5)
        artifacts.close()
        store._db.close()
        registry.close()

    reopened_jobs = JobRegistry(tmp_path / "jobs.db")
    reopened_store = TaskStore(str(tmp_path / "tasks.db"))
    reopened_artifacts = ArtifactRegistry(tmp_path / "artifacts.db")
    try:
        assert reopened_jobs.get_by_id(job.job_id).status == JobStatus.SUCCEEDED
        assert reopened_store.get("task").ring6["chapters"] == [
            {"chapter_no": 1, "content": "saved chapter"},
            {"chapter_no": 2, "content": "new chapter"},
        ]
        versions = reopened_artifacts.list_task("task")
        assert {version.version for version in versions} == {1, 2}
        assert {version.payload["content"] for version in versions} == {"saved chapter", "new chapter"}
    finally:
        reopened_artifacts.close()
        reopened_store._db.close()
        reopened_jobs.close()
