"""Offline, verifiable backups for the unified local data directory."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile


MANIFEST = "manifest.json"


def _absolute(value):
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("Use an absolute path")
    # Reject links/junctions in ancestors too: storage must not escape the tree.
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise ValueError("Links and junctions are unsupported")
    return path.resolve()


def _inventory(root):
    result = {}
    for path in sorted(root.rglob("*")):
        _absolute(path)
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("Unsupported storage entry")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        result[path.relative_to(root).as_posix()] = {
            "size": path.stat().st_size, "sha256": digest.hexdigest(),
        }
    return result


def _check_databases(root):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        with path.open("rb") as stream:
            sqlite = stream.read(16) == b"SQLite format 3\x00"
        if not sqlite:
            if path.suffix == ".db":
                raise ValueError("Invalid SQLite database")
            continue
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("SQLite integrity check failed")
        finally:
            connection.close()


def verify(backup_dir):
    root = _absolute(backup_dir)
    _absolute(root / MANIFEST)
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    if manifest.get("format") != 1 or not isinstance(manifest.get("files"), dict):
        raise ValueError("Unsupported backup manifest")
    _absolute(manifest["source"])
    payload = root / "data"
    _absolute(payload)
    if not payload.is_dir() or not manifest["files"]:
        raise ValueError("Backup payload is missing or empty")
    if _inventory(payload) != manifest["files"]:
        raise ValueError("Backup file inventory or checksum mismatch")
    # Check a disposable copy: opening a WAL database can change its sidecars.
    with tempfile.TemporaryDirectory(prefix="deep-thesis-verify-") as folder:
        copied = Path(folder) / "data"
        shutil.copytree(payload, copied)
        _check_databases(copied)
    return manifest


def create(data_dir, backup_dir, *, stopped=False):
    if not stopped:
        raise ValueError("Stop API and every Worker; pass --stopped to acknowledge")
    source, target = _absolute(data_dir), _absolute(backup_dir)
    if not source.is_dir():
        raise ValueError("Data directory does not exist")
    if target == source or source in target.parents or target in source.parents:
        raise ValueError("Backup and data directories must be separate")
    if target.exists():
        raise ValueError("Backup destination must not exist")
    # An overridden location could silently omit part of the project.
    for name in ("THESIS_TASK_STORE_DIR", "THESIS_KB_ROOT", "DOCX_UPLOAD_DIR",
                 "DOCX_OUTPUT_DIR", "THESIS_ARTIFACT_DB", "THESIS_EVIDENCE_DB",
                 "THESIS_RESEARCH_DB", "THESIS_SECTION_DB", "THESIS_AUTOSAVE_DB",
                 "THESIS_JOB_DB", "THESIS_SECURITY_DB", "THESIS_DOCX_DB"):
        if os.getenv(name):
            configured = _absolute(os.environ[name])
            if configured != source and source not in configured.parents:
                raise ValueError(f"{name} is outside the data directory")
    if os.getenv("THESIS_DB_URL") not in (None, f"sqlite:///{(source / 'thesis.db').as_posix()}"):
        raise ValueError("Backup supports the default unified SQLite database only")
    before = _inventory(source)
    if not before:
        raise ValueError("Cannot back up an empty data directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".deep-thesis-backup-", dir=target.parent) as folder:
        staged = Path(folder) / "backup"
        staged.mkdir()
        shutil.copytree(source, staged / "data")
        if _inventory(source) != before or _inventory(staged / "data") != before:
            raise ValueError("Storage changed during backup; stop all writers")
        (staged / MANIFEST).write_text(json.dumps({
            "format": 1, "source": str(source), "files": before,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        verify(staged)
        staged.rename(target)
    return target


def restore(backup_dir, data_dir, *, stopped=False):
    if not stopped:
        raise ValueError("Stop API and every Worker; pass --stopped to acknowledge")
    manifest = verify(backup_dir)
    target = _absolute(data_dir)
    if target != _absolute(manifest["source"]):
        raise ValueError("Restore requires the original path because records contain absolute paths")
    if target.exists():
        raise ValueError("Restore destination must not exist; preserve the old directory first")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".deep-thesis-restore-", dir=target.parent) as folder:
        staged = Path(folder) / "data"
        shutil.copytree(_absolute(backup_dir) / "data", staged)
        if _inventory(staged) != manifest["files"]:
            raise ValueError("Backup changed during restore")
        staged.rename(target)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description="Deep Thesis offline backup and restore")
    parser.add_argument("action", choices=("create", "verify", "restore"))
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--data-dir")
    parser.add_argument("--stopped", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "verify":
            verify(args.backup_dir)
        else:
            if not args.data_dir:
                parser.error("--data-dir is required for create/restore")
            if args.action == "create":
                create(args.data_dir, args.backup_dir, stopped=args.stopped)
            else:
                restore(args.backup_dir, args.data_dir, stopped=args.stopped)
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as exc:
        print(f"Deep Thesis backup: FAILED ({type(exc).__name__})")
        return 2
    print(f"Deep Thesis backup: {args.action.upper()} OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
