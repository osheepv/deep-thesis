import json
import sqlite3

import pytest

from application.backup import create, main, restore, verify


@pytest.fixture
def storage(tmp_path, monkeypatch):
    # These tests exercise isolated unified storage, not development settings.
    import os
    for key in list(os.environ):
        if key.startswith("THESIS_") or key in ("DOCX_UPLOAD_DIR", "DOCX_OUTPUT_DIR"):
            monkeypatch.delenv(key)
    source = tmp_path / "论文数据"
    source.mkdir()
    connection = sqlite3.connect(source / "thesis.db")
    connection.execute("create table progress (stage integer)")
    connection.execute("insert into progress values (6)")
    connection.commit()
    connection.close()
    (source / "outputs").mkdir()
    (source / "outputs" / "paper.docx").write_bytes(b"test attachment")
    return source, tmp_path / "backup"


def test_cli_roundtrip_preserves_progress_and_attachments(storage):
    source, backup = storage
    assert main(["create", "--data-dir", str(source), "--backup-dir", str(backup), "--stopped"]) == 0
    assert main(["verify", "--backup-dir", str(backup)]) == 0
    source.rename(source.with_name("preserved-original"))
    assert main(["restore", "--data-dir", str(source), "--backup-dir", str(backup), "--stopped"]) == 0
    with sqlite3.connect(source / "thesis.db") as db:
        assert db.execute("select stage from progress").fetchone() == (6,)
    assert (source / "outputs" / "paper.docx").read_bytes() == b"test attachment"


@pytest.mark.parametrize("change", ["modify", "remove", "extra"])
def test_corruption_blocks_restore_without_creating_destination(storage, change):
    source, backup = storage
    create(source, backup, stopped=True)
    attachment = backup / "data" / "outputs" / "paper.docx"
    if change == "modify":
        attachment.write_bytes(b"corrupt")
    elif change == "remove":
        attachment.unlink()
    else:
        (backup / "data" / "extra").write_text("extra")
    source.rename(source.with_name("preserved-original"))
    with pytest.raises(ValueError, match="checksum"):
        restore(backup, source, stopped=True)
    assert not source.exists()


def test_refuses_overwrite_or_relocation(storage):
    source, backup = storage
    create(source, backup, stopped=True)
    with pytest.raises(ValueError, match="must not exist"):
        restore(backup, source, stopped=True)
    with pytest.raises(ValueError, match="original path"):
        restore(backup, source.with_name("relocated"), stopped=True)
    with pytest.raises(ValueError, match="must not exist"):
        create(source, backup, stopped=True)


def test_requires_stopped_and_rejects_nested_destination(storage):
    source, backup = storage
    with pytest.raises(ValueError, match="Stop API"):
        create(source, backup)
    with pytest.raises(ValueError, match="Stop API"):
        restore(backup, source)
    with pytest.raises(ValueError, match="separate"):
        create(source, source / "backup", stopped=True)


def test_external_storage_refused(storage, monkeypatch):
    source, backup = storage
    monkeypatch.setenv("THESIS_KB_ROOT", str(source.parent / "external-kb"))
    with pytest.raises(ValueError, match="outside"):
        create(source, backup, stopped=True)
    assert not backup.exists()


def test_invalid_database_refused_even_with_matching_hashes(storage):
    source, backup = storage
    (source / "thesis.db").write_bytes(b"not sqlite")
    with pytest.raises(ValueError, match="Invalid SQLite"):
        create(source, backup, stopped=True)
    assert not backup.exists()


def test_manifest_path_traversal_does_not_extract_files(storage):
    source, backup = storage
    create(source, backup, stopped=True)
    path = backup / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["files"]["../../escaped"] = {"size": 0, "sha256": "x"}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        verify(backup)
    assert not (source.parent / "escaped").exists()


def test_wal_commits_survive_backup(storage):
    source, backup = storage
    db = sqlite3.connect(source / "thesis.db")
    try:
        db.execute("pragma journal_mode=WAL")
        db.execute("update progress set stage=7")
        db.commit()
        # Connection is idle; preserve WAL sidecars as after a stopped process.
        create(source, backup, stopped=True)
        assert verify(backup)["files"]["thesis.db-wal"]
        with sqlite3.connect(backup / "data" / "thesis.db") as restored:
            assert restored.execute("select stage from progress").fetchone() == (7,)
    finally:
        db.close()


def test_changing_source_never_publishes_backup(storage, monkeypatch):
    from application import backup as module
    source, backup = storage
    original = module.shutil.copytree

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        (source / "outputs" / "paper.docx").write_bytes(b"new revision")
        return result

    monkeypatch.setattr(module.shutil, "copytree", changed)
    with pytest.raises(ValueError, match="changed"):
        create(source, backup, stopped=True)
    assert not backup.exists()
