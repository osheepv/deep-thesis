import json
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest

from application.migrate_storage import DATABASES, DIRECTORIES, _snapshot, migrate


@pytest.fixture
def plan(tmp_path):
    sources = {}
    for name, table in DATABASES.items():
        source = tmp_path / (name + "-old") / "store.sqlite"
        source.parent.mkdir()
        with closing(sqlite3.connect(source)) as db, db:
            columns = {
                "task_store.db": "task_id TEXT, payload TEXT",
                "docx.db": "kind TEXT, record_id TEXT, payload TEXT, deleted INTEGER",
                "jobs.db": "status TEXT",
            }.get(name, "id TEXT")
            db.execute(f"CREATE TABLE {table} ({columns})")
        sources[name] = str(source)
    for name in DIRECTORIES:
        source = tmp_path / (name + "-old")
        source.mkdir()
        sources[name] = str(source)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"format": 1, "target": str(tmp_path / "new"), "sources": sources}), encoding="utf-8")
    return path, sources, tmp_path / "new"


def test_preflight_preserves_sources_and_creates_no_target(plan):
    path, sources, target = plan
    mapped = {key: Path(value) for key, value in sources.items()}
    before = _snapshot(mapped)
    assert migrate(path, stopped=True)["status"] == "PREFLIGHT_OK"
    assert not target.exists()
    assert _snapshot(mapped) == before
    assert migrate(path, apply=True, stopped=True)["status"] == "COPIED_REQUIRES_RECONCILIATION"
    assert _snapshot(mapped) == before
    assert (target / "migration-report.json").is_file()
    with pytest.raises(ValueError, match="must not exist"):
        migrate(path, apply=True, stopped=True)


@pytest.mark.parametrize("issue", ["missing", "running", "cancel", "schema", "relative", "overlap"])
def test_invalid_sources_never_publish(plan, issue):
    path, sources, target = plan
    if issue == "missing":
        Path(sources["docx.db"]).unlink()
    elif issue in ("running", "cancel"):
        with closing(sqlite3.connect(sources["jobs.db"])) as db, db:
            db.execute("INSERT INTO t_job_run VALUES (?)", ("RUNNING" if issue == "running" else "CANCEL_REQUESTED",))
    elif issue == "schema":
        with closing(sqlite3.connect(sources["artifacts.db"])) as db, db:
            db.execute("DROP TABLE t_artifact")
    else:
        data = json.loads(path.read_text())
        if issue == "relative":
            data["sources"]["kb"] = "relative"
        else:
            data["target"] = str(Path(sources["kb"]) / "nested")
        path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        migrate(path, apply=True, stopped=True)
    assert not target.exists()


def test_lost_template_registration_blocks_migration(plan):
    path, sources, target = plan
    template = Path(sources["templates"]) / "custom.docx"
    template.write_bytes(b"template")
    record = {"template_path": str(template), "template_id": "lost", "docx": "null"}
    with closing(sqlite3.connect(sources["task_store.db"])) as db, db:
        db.execute("INSERT INTO t_task_store VALUES (?, ?)", ("t1", json.dumps(record)))
    with pytest.raises(ValueError, match="registration missing"):
        migrate(path, apply=True, stopped=True)
    assert not target.exists()


@pytest.mark.parametrize("outside", [False, True])
def test_missing_or_unmapped_knowledge_file_blocks_migration(plan, outside):
    path, sources, target = plan
    session = Path(sources["kb"]) / "session"
    session.mkdir()
    referenced = target.parent / "outside.txt" if outside else session / "missing.txt"
    if outside:
        referenced.write_text("external")
    (session / "meta.json").write_text(json.dumps({"documents": [{"file_path": str(referenced)}]}))
    with pytest.raises(ValueError, match="Unmapped|Missing referenced"):
        migrate(path, apply=True, stopped=True)
    assert not target.exists()


def test_requires_offline_acknowledgment(plan):
    with pytest.raises(ValueError, match="Stop API"):
        migrate(plan[0], apply=True)


def test_real_task_migrates_and_downloads_without_old_paths(tmp_path):
    backend = Path(__file__).resolve().parents[1] / "backend"
    old = tmp_path / "old"
    environment = {key: value for key, value in os.environ.items() if not key.startswith(("THESIS_", "DOCX_"))}
    environment.update({"PYTHONPATH": str(backend), "THESIS_DATA_DIR": str(old),
                        "THESIS_TASK_STORE_MEMORY": "false", "THESIS_JOB_WORKER_ENABLED": "false",
                        "THESIS_DEEPSEEK_ENABLED": "false", "THESIS_DEEPSEEK_FALLBACK_TO_MOCK": "true",
                        "PYTHONIOENCODING": "utf-8"})
    setup = '''
import json
from fastapi.testclient import TestClient
from application.main import app
from security.store import SecurityStore
from pathlib import Path
import os
SecurityStore(Path(os.environ['THESIS_DATA_DIR']) / 'security.db')._db.close()
with TestClient(app) as client:
    result = client.post('/api/v1/console/tasks', json={
        'title': 'Migration test', 'degree': 'MASTER', 'subject_field': 'CS', 'session_id': 'migration',
    }).json()
    assert result['code'] == 0, result
    task_id = result['data']['task_id']
    orchestration = app.state.orchestration
    assert orchestration.run_ring1(task_id).code == 0
    orchestration._drafts.save(task_id=task_id, tenant_id='default', author_id='author',
        object_type='PROJECT_MEMORY_FORM', draft_key='project-memory:main',
        content={'notes': 'Unsubmitted work'}, revision=3)
    generated = orchestration._docx.generate('builtin', {'title': 'Migration', 'main_body': 'Preserved body'}, session_id='migration')
    task = orchestration._store.get(task_id)
    task.docx = generated
    orchestration._store.put(task)
    document = orchestration._knowledge_store.save_document('migration', 'source.txt', b'Preserved evidence')
    print(json.dumps({'task_id': task_id, 'file_id': generated['filename'], 'kb_id': document['file_id']}))
'''
    result = subprocess.run([sys.executable, "-c", setup], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, encoding="utf-8", timeout=45)
    assert result.returncode == 0, result.stderr + result.stdout
    identifiers = json.loads(result.stdout.strip().splitlines()[-1])
    sources = {}
    for name in DATABASES:
        # Move complete closed DBs to different directories and filenames.
        source = tmp_path / (name + "-split") / "legacy.sqlite"
        source.parent.mkdir()
        shutil.copy2(old / name, source)
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = old / (name + suffix)
            if sidecar.exists():
                shutil.copy2(sidecar, source.with_name(source.name + suffix))
        sources[name] = str(source)
    for name in DIRECTORIES:
        (old / name).mkdir(exist_ok=True)
        sources[name] = str(old / name)
    target = tmp_path / "new"
    path = tmp_path / "migration.json"
    path.write_text(json.dumps({"format": 1, "target": str(target), "sources": sources}))
    before = _snapshot({key: Path(value) for key, value in sources.items()})
    assert migrate(path, stopped=True)["path_changes"] >= 3
    applied = subprocess.run([sys.executable, "-m", "application.migrate_storage", "--plan", str(path),
                              "--stopped", "--apply"], cwd=tmp_path, env=environment,
                             capture_output=True, text=True, encoding="utf-8", timeout=45)
    assert applied.returncode == 0, applied.stderr + applied.stdout
    assert json.loads(applied.stdout)["status"] == "COPIED_REQUIRES_RECONCILIATION"
    assert _snapshot({key: Path(value) for key, value in sources.items()}) == before
    # Hide original attachment locations: accidental reads from old paths must fail.
    old.rename(tmp_path / "preserved-old")
    environment["THESIS_DATA_DIR"] = str(target)
    check = '''
import json, sys
from pathlib import Path
from fastapi.testclient import TestClient
from application.main import app
ids = json.loads(sys.argv[1])
with TestClient(app) as client:
    orchestration = app.state.orchestration
    assert orchestration.reconcile_startup().data['status'] == 'CONSISTENT'
    task = orchestration._store.get(ids['task_id'])
    assert task.ring1
    assert orchestration.progress(ids['task_id']).data['phase_state'] == 'WAITING_APPROVAL'
    draft = orchestration._drafts.get(ids['task_id'], 'author', 'project-memory:main')
    assert draft.revision == 3 and draft.content_json == {'notes': 'Unsubmitted work'}
    assert Path(task.docx['file_path']).is_file()
    doc = orchestration._knowledge_store.get_document('migration', ids['kb_id'])
    assert Path(doc['file_path']).read_bytes() == b'Preserved evidence'
    response = client.get('/api/v1/docx/files/' + ids['file_id'], params={'session_id': 'migration'})
    assert response.status_code == 200
    assert response.content.startswith(b'PK')
'''
    result = subprocess.run([sys.executable, "-c", check, json.dumps(identifiers)], cwd=tmp_path,
                            env=environment, capture_output=True, text=True, encoding="utf-8", timeout=45)
    assert result.returncode == 0, result.stderr + result.stdout


def test_changed_source_blocks_publication(plan, monkeypatch):
    from application import migrate_storage as module
    path, sources, target = plan
    original = module._rewrite

    def change(*args):
        count = original(*args)
        (Path(sources['kb']) / 'late.txt').write_text('concurrent write')
        return count

    monkeypatch.setattr(module, '_rewrite', change)
    with pytest.raises(ValueError, match='changed'):
        migrate(path, stopped=True, apply=True)
    assert not target.exists()
