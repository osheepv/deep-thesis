"""Offline relocation of explicitly mapped, current-schema local storage."""

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

from .backup import _absolute, _check_databases, _inventory


DATABASES = {
    "thesis.db": "t_fsm_state", "task_store.db": "t_task_store",
    "artifacts.db": "t_artifact", "evidence.db": "t_evidence_source",
    "research.db": "t_experiment_run", "sections.db": "t_section_draft",
    "autosave.db": "t_autosave_draft", "jobs.db": "t_job_run",
    "security.db": "t_security_user", "docx.db": "t_docx_record",
}
DIRECTORIES = ("kb", "templates", "outputs")


def _load_plan(plan_path):
    plan = json.loads(_absolute(plan_path).read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or plan.get("format") != 1:
        raise ValueError("Unsupported migration plan")
    sources = plan.get("sources")
    if not isinstance(sources, dict) or set(sources) != set(DATABASES) | set(DIRECTORIES):
        raise ValueError("Provide every database and directory explicitly; no inferred defaults")
    target = _absolute(plan["target"])
    if target.exists():
        raise ValueError("Migration target must not exist")
    sources = {name: _absolute(value) for name, value in sources.items()}
    if len(set(sources.values())) != len(sources):
        raise ValueError("Source locations must be distinct")
    for name, source in sources.items():
        if not (source.is_file() if name in DATABASES else source.is_dir()):
            raise ValueError(f"Missing source: {name}; missing in-memory records cannot be reconstructed")
        if target == source or target in source.parents or source in target.parents:
            raise ValueError("Target must be separate from all sources")
        for other_name in DIRECTORIES:
            other = sources[other_name]
            if source != other and other in source.parents:
                raise ValueError("Source directories must not overlap other sources")
    return target, sources


def _snapshot(sources):
    fingerprints = {}
    for name, source in sources.items():
        if name in DIRECTORIES:
            fingerprints[name] = _inventory(source)
        else:
            selected = {}
            for suffix in ("", "-wal", "-shm", "-journal"):
                item = source.with_name(source.name + suffix)
                if item.exists():
                    _absolute(item)
                    digest = hashlib.sha256()
                    with item.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                    selected[name + suffix] = {"sha256": digest.hexdigest(), "size": item.stat().st_size}
            fingerprints[name] = selected
    return fingerprints


def _copy_sources(sources, stage, fingerprints):
    for name, source in sources.items():
        if name in DIRECTORIES:
            shutil.copytree(source, stage / name)
        else:
            for filename in fingerprints[name]:
                suffix = filename[len(name):]
                shutil.copy2(source.with_name(source.name + suffix), stage / filename)
    copied_sources = {name: stage / name for name in sources}
    if _snapshot(copied_sources) != fingerprints or _snapshot(sources) != fingerprints:
        raise ValueError("Source changed during copy")


def _rewrite(stage, target, sources):
    changes = 0
    with closing(sqlite3.connect(stage / "docx.db")) as db:
        registered = {(kind, record_id): json.loads(payload) for kind, record_id, payload in
                      db.execute("SELECT kind, record_id, payload FROM t_docx_record WHERE deleted=0")}

    def relocate(value, category):
        nonlocal changes
        if not value:
            return value
        path = _absolute(value)
        try:
            relative = path.relative_to(sources[category])
        except ValueError:
            raise ValueError(f"Unmapped file reference in {category}") from None
        if not (stage / category / relative).is_file():
            raise ValueError(f"Missing referenced file in {category}")
        changes += 1
        return str(target / category / relative)

    # Only operational pointers are changed. Immutable artifact bodies, hashes,
    # approval history and manuscript text are copied unchanged.
    with closing(sqlite3.connect(stage / "task_store.db")) as db, db:
        for task_id, payload in db.execute("SELECT task_id, payload FROM t_task_store").fetchall():
            record = json.loads(payload)
            if not isinstance(record, dict):
                raise ValueError("Invalid task record")
            if record.get("template_path"):
                if ("template", record.get("template_id")) not in registered:
                    raise ValueError("Task template registration missing; re-register in the old environment")
                record["template_path"] = relocate(record["template_path"], "templates")
            docx = record.get("docx")
            serialized = isinstance(docx, str)
            docx = json.loads(docx) if serialized and docx.strip() else docx
            if docx:
                if not isinstance(docx, dict):
                    raise ValueError("Invalid task document record")
                if ("output", docx.get("filename")) not in registered:
                    raise ValueError("Task output registration missing; re-register in the old environment")
                if docx.get("file_path"):
                    docx["file_path"] = relocate(docx["file_path"], "outputs")
                record["docx"] = json.dumps(docx, ensure_ascii=False) if serialized else docx
            db.execute("UPDATE t_task_store SET payload=? WHERE task_id=?",
                       (json.dumps(record, ensure_ascii=False), task_id))
    with closing(sqlite3.connect(stage / "docx.db")) as db, db:
        for kind, record_id, payload in db.execute(
            "SELECT kind, record_id, payload FROM t_docx_record WHERE deleted=0"
        ).fetchall():
            if kind not in ("template", "output"):
                raise ValueError("Unsupported document registration kind")
            record = json.loads(payload)
            if not record.get("file_path"):
                raise ValueError("Document registration has no file path")
            record["file_path"] = relocate(record["file_path"], "templates" if kind == "template" else "outputs")
            db.execute("UPDATE t_docx_record SET payload=? WHERE kind=? AND record_id=?",
                       (json.dumps(record, ensure_ascii=False), kind, record_id))
    for meta in (stage / "kb").glob("*/meta.json"):
        index = json.loads(meta.read_text(encoding="utf-8"))
        if not isinstance(index, dict) or not isinstance(index.get("documents"), list):
            raise ValueError("Invalid knowledge index")
        for record in index["documents"]:
            if not isinstance(record, dict) or not record.get("file_path"):
                raise ValueError("Knowledge record has no file path")
            record["file_path"] = relocate(record["file_path"], "kb")
        meta.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return changes


def migrate(plan_path, *, apply=False, stopped=False):
    if not stopped:
        raise ValueError("Stop API and all Workers, then pass --stopped")
    target, sources = _load_plan(plan_path)
    # Preflight performs the same copy/check/rewrite as apply, but publishes nothing.
    # Temporary files stay outside sources. Apply stages beside the destination.
    if apply:
        target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".deep-thesis-migrate-",
                                     dir=target.parent if apply else None) as folder:
        stage = Path(folder) / "data"
        stage.mkdir()
        fingerprints = _snapshot(sources)
        _copy_sources(sources, stage, fingerprints)
        _check_databases(stage)
        for name, table in DATABASES.items():
            with closing(sqlite3.connect(stage / name)) as db:
                if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    raise ValueError(f"Unsupported database schema: {name}")
        with closing(sqlite3.connect(stage / "jobs.db")) as db:
            if db.execute("SELECT 1 FROM t_job_run WHERE status IN ('RUNNING', 'CANCEL_REQUESTED') LIMIT 1").fetchone():
                raise ValueError("Settle running jobs in the old environment before migration")
        changes = _rewrite(stage, target, sources)
        _check_databases(stage)
        if _snapshot(sources) != fingerprints:
            raise ValueError("Source changed during migration")
        report = {"format": 1, "status": "COPIED_REQUIRES_RECONCILIATION" if apply else "PREFLIGHT_OK",
                  "path_changes": changes, "target": str(target),
                  "sources": {name: str(path) for name, path in sources.items()}}
        if apply:
            (stage / "migration-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            stage.rename(target)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Deep Thesis offline storage migration")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--stopped", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = migrate(args.plan, apply=args.apply, stopped=args.stopped)
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as exc:
        print(f"Deep Thesis migration: FAILED ({type(exc).__name__}): {exc}")
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
