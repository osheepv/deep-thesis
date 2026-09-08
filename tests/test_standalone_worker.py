"""Standalone entrypoint, shared storage, and graceful foreground draining."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from db.session import build_fsm_repository
from jobs import JobRegistry, JobStatus, JobWorker


BACKEND = Path(__file__).resolve().parents[1] / "backend"


def _environment(tmp_path):
    environment = {name: value for name, value in os.environ.items()
                   if not name.startswith(("THESIS_", "DOCX_"))}
    environment.update({
        "PYTHONPATH": str(BACKEND),
        "THESIS_DATA_DIR": str(tmp_path / "data"),
        "THESIS_TASK_STORE_MEMORY": "false",
        "THESIS_JOB_WORKER_ENABLED": "false",
        "THESIS_DEEPSEEK_ENABLED": "false",
        "THESIS_DEEPSEEK_FALLBACK_TO_MOCK": "true",
        "PYTHONIOENCODING": "utf-8",
    })
    return environment


def test_api_enqueues_and_standalone_process_executes_from_different_directory(tmp_path):
    api_directory = tmp_path / "api"
    worker_directory = tmp_path / "worker"
    api_directory.mkdir()
    worker_directory.mkdir()
    script = '''
import json, os, subprocess, sys
from fastapi.testclient import TestClient
from application.main import app

with TestClient(app) as client:
    created = client.post('/api/v1/console/tasks', json={
        'title': 'Offline worker test', 'degree': 'MASTER',
        'subject_field': 'Computer Science', 'session_id': 'standalone',
    }).json()
    assert created['code'] == 0, created
    task_id = created['data']['task_id']
    url = f'/api/v1/console/tasks/{task_id}/jobs?session_id=standalone'
    queued = client.post(url, json={
        'operation': 'ring.execute', 'payload': {'ring_no': 1},
        'idempotency_key': 'ring1',
    }).json()['data']
    assert queued['status'] == 'PENDING'
    assert app.state.job_worker._thread is None
    checked = subprocess.run([sys.executable, '-m', 'application.worker', '--check'],
        cwd=sys.argv[1], capture_output=True, text=True, timeout=45)
    assert checked.returncode == 0, checked.stderr
    assert client.get(url).json()['data'][0]['status'] == 'PENDING'
    completed = subprocess.run([sys.executable, '-m', 'application.worker', '--once'],
        cwd=sys.argv[1], capture_output=True, text=True, timeout=45)
    assert completed.returncode == 0, completed.stderr + completed.stdout
    result = client.get(url).json()['data'][0]
    assert result['status'] == 'SUCCEEDED', result
    assert result['attempt'] == 1
    assert app.state.orchestration._store.get(task_id).ring1
    assert app.state.orchestration.progress(task_id).data['phase_state'] == 'WAITING_APPROVAL'
    duplicate = client.post(url, json={
        'operation': 'ring.execute', 'payload': {'ring_no': 1}, 'idempotency_key': 'ring1',
    }).json()['data']
    assert duplicate['job_id'] == queued['job_id']
    render_script = """
import json
from application.bootstrap import build_orchestration
orchestration = build_orchestration(require_persistent=True)
generated = orchestration._docx.generate('builtin', {
    'title': 'Shared output', 'main_body': 'Body from the independent process',
}, session_id='standalone')
print(json.dumps(generated))
"""
    rendered = subprocess.run([sys.executable, '-c', render_script], cwd=sys.argv[1],
        capture_output=True, text=True, timeout=45)
    assert rendered.returncode == 0, rendered.stderr
    generated = json.loads(rendered.stdout.strip().splitlines()[-1])
    downloaded = client.get(generated['download_url'], params={'session_id': 'standalone'})
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b'PK'), downloaded.content
    print(json.dumps({'task_id': task_id, 'job_id': result['job_id'], 'file_id': generated['filename']}))
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(worker_directory)], cwd=api_directory,
        env=_environment(tmp_path), capture_output=True, text=True, encoding="utf-8", timeout=100,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    identifiers = json.loads(result.stdout.strip().splitlines()[-1])
    # All application processes have exited. Back up, preserve the original,
    # then restore before verifying actual application records and reconciliation.
    backup_path = tmp_path / "snapshot"
    for action in ("create", "restore"):
        if action == "restore":
            (tmp_path / "data").rename(tmp_path / "preserved-data")
        backed_up = subprocess.run(
            [sys.executable, "-m", "application.backup", action,
             "--data-dir", str(tmp_path / "data"), "--backup-dir", str(backup_path), "--stopped"],
            cwd=worker_directory, env=_environment(tmp_path), capture_output=True,
            text=True, encoding="utf-8", timeout=45,
        )
        assert backed_up.returncode == 0, backed_up.stderr + backed_up.stdout
    restart = '''
import sys
from application.bootstrap import build_orchestration
orchestration = build_orchestration(require_persistent=True)
assert 'application.main' not in sys.modules
assert orchestration._jobs.get_by_id(sys.argv[2]).status.value == 'SUCCEEDED'
assert orchestration._store.get(sys.argv[1]).ring1
assert orchestration._docx_service._repo.get_output_owned(sys.argv[3], 'standalone')
assert orchestration.reconcile_startup().data['status'] == 'CONSISTENT'
from fastapi.testclient import TestClient
from application.main import app
with TestClient(app) as client:
    downloaded = client.get('/api/v1/docx/files/' + sys.argv[3], params={'session_id': 'standalone'})
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content.startswith(b'PK')
'''
    result = subprocess.run(
        [sys.executable, "-c", restart, identifiers["task_id"], identifiers["job_id"], identifiers["file_id"]],
        cwd=worker_directory, env=_environment(tmp_path), capture_output=True, text=True,
        encoding="utf-8", timeout=45,
    )
    assert result.returncode == 0, result.stderr
    assert not (api_directory / "thesis.db").exists()
    assert not (worker_directory / "thesis.db").exists()


@pytest.mark.parametrize("setting,value", [
    ("THESIS_TASK_STORE_MEMORY", "true"), ("THESIS_JOB_DB", ":memory:"),
    ("THESIS_DATA_DIR", "relative"), ("THESIS_DB_URL", "sqlite:///:memory:"),
])
def test_standalone_rejects_nonpersistent_storage(tmp_path, setting, value):
    environment = _environment(tmp_path)
    environment[setting] = value
    result = subprocess.run(
        [sys.executable, "-m", "application.worker", "--check"], cwd=tmp_path,
        env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 2
    assert "startup refused" in result.stderr


def test_persistent_fsm_does_not_fallback_when_database_is_unavailable(tmp_path):
    with pytest.raises(RuntimeError, match="startup refused"):
        build_fsm_repository(f"sqlite:///{tmp_path / 'missing' / 'fsm.db'}", require_persistent=True)


def test_standalone_refuses_orphan_job_without_claiming_it(tmp_path):
    registry = JobRegistry(tmp_path / "data" / "jobs.db")
    job = registry.create(task_id="missing", session_id="test", operation="ring.execute")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "application.worker", "--once"], cwd=tmp_path,
            env=_environment(tmp_path), capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        assert result.returncode == 2
        assert "NEEDS_REPAIR" in result.stdout
        assert registry.get_by_id(job.job_id).attempt == 0
    finally:
        registry.close()


def test_cli_sigterm_drains_current_job_and_restores_signal_handlers(tmp_path, monkeypatch):
    import signal
    from types import SimpleNamespace
    from application.worker import main

    registry = JobRegistry()
    first = registry.create(task_id="one", session_id="test", operation="work")
    second = registry.create(task_id="two", session_id="test", operation="work")

    def handler(job):
        signal.raise_signal(signal.SIGTERM)
        return {"finished": True}

    orchestration = SimpleNamespace(
        _jobs=registry, job_handlers=lambda: {"work": handler},
        reconcile_startup=lambda: SimpleNamespace(data={"status": "CONSISTENT"}),
    )
    monkeypatch.setattr("application.worker.build_orchestration", lambda **kwargs: orchestration)
    monkeypatch.setenv("THESIS_DATA_DIR", str(tmp_path))
    previous = signal.getsignal(signal.SIGTERM)
    try:
        assert main([]) == 0
        assert registry.get_by_id(first.job_id).status == JobStatus.SUCCEEDED
        assert registry.get_by_id(second.job_id).status == JobStatus.PENDING
        assert signal.getsignal(signal.SIGTERM) == previous
    finally:
        registry.close()


def test_foreground_worker_finishes_current_job_before_stopping():
    registry = JobRegistry()
    first = registry.create(task_id="one", session_id="test", operation="work")
    second = registry.create(task_id="two", session_id="test", operation="work")

    def handler(job):
        worker.stop(timeout=0)
        return {"finished": True}

    worker = JobWorker(registry, {"work": handler})
    try:
        worker.run_forever()
        assert registry.get_by_id(first.job_id).status == JobStatus.SUCCEEDED
        assert registry.get_by_id(second.job_id).status == JobStatus.PENDING
    finally:
        registry.close()
