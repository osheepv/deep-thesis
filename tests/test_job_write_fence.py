"""Execution receipts fence late business commits, including reused worker names."""

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from application.service.task_store import TaskRecord, TaskStore
from artifacts import ArtifactKind, ArtifactRegistry
from common.aicoding.enums import Degree
from fsm.repository import InMemoryFsmRepository, SqlAlchemyFsmRepository
from fsm.state.models import FsmState
from fsm.state.orm import FSMBase
from jobs import JobRegistry, JobRegistryError, JobRuntime, Pricing
from jobs.runtime import job_runtime_context, job_write_fence
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from writing import SectionDraftRegistry


def _runtime(registry, claimed):
    return JobRuntime(registry, claimed.job_id, claimed.lease_owner, Pricing(), claimed.lease_token)


def _replace(registry, claimed):
    registry.fail(claimed.job_id, claimed.lease_owner, "handover", retry_delay_seconds=0,
                  lease_token=claimed.lease_token)
    return registry.claim_next(claimed.lease_owner)


@pytest.fixture
def leased(tmp_path):
    registry = JobRegistry(tmp_path / "jobs.db")
    registry.create(task_id="task", session_id="session", operation="write")
    old = registry.claim_next("same-worker")
    yield registry, old
    registry.close()


@pytest.mark.parametrize("memory", [False, True])
def test_late_checkpoint_cannot_overwrite_new_attempt(leased, tmp_path, memory):
    registry, old = leased
    store = TaskStore(None if memory else str(tmp_path / "tasks.db"))
    rec = TaskRecord("task", "original", "MASTER", "AI")
    store.put(rec)
    stale = store.get("task")
    fresh = _replace(registry, old)
    with job_runtime_context(_runtime(registry, fresh)):
        rec.ring6 = {"checkpoint": True, "content": "new"}
        store.put(rec)
    stale.ring6 = {"checkpoint": True, "content": "stale"}
    try:
        with job_runtime_context(_runtime(registry, old)), pytest.raises(JobRegistryError):
            store.put(stale)
        assert store.get("task").ring6["content"] == "new"
    finally:
        if store._db is not None:
            store._db.close()


@pytest.mark.parametrize("memory", [False, True])
def test_late_fsm_transition_is_rejected(leased, tmp_path, memory):
    registry, old = leased
    engine = create_engine(f"sqlite:///{tmp_path / 'fsm.db'}")
    FSMBase.metadata.create_all(engine)
    repo = InMemoryFsmRepository() if memory else SqlAlchemyFsmRepository(sessionmaker(engine))
    state = FsmState("task", 6, Degree.MASTER)
    repo.persist_transition(state)
    stale = repo.get_by_task_id("task")
    _replace(registry, old)
    stale.current_ring_no = 7
    try:
        with job_runtime_context(_runtime(registry, old)), pytest.raises(JobRegistryError):
            repo.persist_transition(stale)
        assert repo.get_by_task_id("task").current_ring_no == 6
    finally:
        engine.dispose()


@pytest.mark.parametrize("domain", ["artifact", "section"])
def test_stale_version_and_gate_writes_are_rejected(leased, tmp_path, domain):
    registry, old = leased
    if domain == "artifact":
        store = ArtifactRegistry(tmp_path / "artifacts.db")
        create = lambda: store.create_version(task_id="task", stage_no=6,
                    kind=ArtifactKind.SECTION_DRAFT, payload={"body": "new"})
        item = create()
        gate = lambda: store.submit_auto_gate(item.artifact_id, passed=True)
    else:
        store = SectionDraftRegistry(tmp_path / "sections.db")
        create = lambda: store.create_version(task_id="task", section_id="1.1",
                                               title="section", content="new")
        item = create()
        gate = lambda: store.submit_auto_gate("task", item.section_draft_id, passed=True)
    _replace(registry, old)
    try:
        with job_runtime_context(_runtime(registry, old)):
            with pytest.raises(JobRegistryError):
                create()
            with pytest.raises(JobRegistryError):
                gate()
        assert len(store.list_task("task")) == 1
        assert store.list_task("task")[0].status.value == "GENERATED"
    finally:
        store.close()


def test_fence_excludes_takeover_until_business_write_finishes(leased, tmp_path):
    registry, old = leased
    other = JobRegistry(tmp_path / "jobs.db")
    attempted = threading.Event()
    claimed = threading.Event()

    def takeover():
        attempted.set()
        replacement = _replace(other, old)
        claimed.set()
        return replacement

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with job_runtime_context(_runtime(registry, old)), job_write_fence("task"):
                future = pool.submit(takeover)
                assert attempted.wait(3)
                assert not claimed.wait(0.2)
            replacement = future.result(timeout=5)
            assert replacement.lease_token != old.lease_token
    finally:
        other.close()


def test_fence_releases_after_failed_write_and_blocks_cancelled_or_other_task(leased):
    registry, old = leased
    with job_runtime_context(_runtime(registry, old)):
        with pytest.raises(RuntimeError, match="disk"):
            with job_write_fence("task"):
                raise RuntimeError("disk error")
        with pytest.raises(JobRegistryError):
            with job_write_fence("another-task"):
                pytest.fail("cross-task write")
        registry.request_cancel("task", old.job_id)
        from jobs import JobCancelledError
        with pytest.raises(JobCancelledError):
            with job_write_fence("task"):
                pytest.fail("cancelled write")


def test_same_worker_old_token_cannot_heartbeat_complete_or_fail(leased):
    registry, old = leased
    fresh = _replace(registry, old)
    assert fresh.lease_token != old.lease_token
    for mutation in (
        lambda: registry.heartbeat(old.job_id, old.lease_owner, lease_token=old.lease_token),
        lambda: registry.complete(old.job_id, old.lease_owner, {}, lease_token=old.lease_token),
        lambda: registry.fail(old.job_id, old.lease_owner, "stale", lease_token=old.lease_token),
    ):
        with pytest.raises(JobRegistryError):
            mutation()
    assert registry.get_by_id(old.job_id).lease_token == fresh.lease_token


def test_legacy_job_database_migrates_without_losing_records(tmp_path):
    path = tmp_path / "legacy.db"
    registry = JobRegistry(path)
    job = registry.create(task_id="task", session_id="session", operation="write")
    registry.close()
    with sqlite3.connect(path) as database:
        database.execute("ALTER TABLE t_job_run DROP COLUMN lease_token")
    registry = JobRegistry(path)
    try:
        assert registry.get_by_id(job.job_id).lease_token == ""
        assert registry.claim_next("worker").lease_token
    finally:
        registry.close()


def test_ring6_late_checkpoint_cannot_replace_reclaimed_work(monkeypatch):
    from tests.test_full_flow_hardening import _advance_to_ring6

    orchestration, _, task_id = _advance_to_ring6(monkeypatch)
    registry = orchestration._jobs
    registry.create(task_id=task_id, session_id="test", operation="ring.execute")
    old = registry.claim_next("same-worker")

    class LateExecutor:
        def execute(self, ctx):
            fresh = _replace(registry, old)
            with job_runtime_context(_runtime(registry, fresh)):
                ctx.chapter_checkpoint_callback([{
                    "chapter_no": 1, "content": "new checkpoint", "checkpoint_complete": False,
                }])
            ctx.chapter_checkpoint_callback([{
                "chapter_no": 1, "content": "late checkpoint", "checkpoint_complete": False,
            }])
            raise AssertionError("stale executor should stop at checkpoint")

    monkeypatch.setattr("application.service.uc_main_orchestration.get_executor",
                        lambda ring: LateExecutor())
    with job_runtime_context(_runtime(registry, old)), pytest.raises(JobRegistryError):
        orchestration.run_ring6(task_id)
    assert orchestration._store.get(task_id).ring6["chapters"][0]["content"] == "new checkpoint"
    assert orchestration._fsm.get_task(task_id).current_ring_no == 6
