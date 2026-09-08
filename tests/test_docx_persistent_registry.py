"""API and worker connections share file registration and ownership checks."""

import pytest

from common.aicoding.exception import BizException
from thesis_docx.repository.sqlite_repository import SqliteDocxRepository


def test_template_and_output_registration_survive_restart(tmp_path):
    path = tmp_path / "docx.db"
    api = SqliteDocxRepository(path)
    worker = SqliteDocxRepository(path)
    try:
        api.save_template({"template_id": "template", "session_id": "owner",
                           "placeholders": ["title"], "file_path": "template.docx"})
        assert worker.get_template_owned("template", "owner").placeholders == ["title"]
        worker.save_output({"file_id": "output", "session_id": "owner", "file_path": "output.docx"})
        assert api.get_output_owned("output", "owner").file_path == "output.docx"
        for read, identifier in ((worker.get_template_owned, "template"), (api.get_output_owned, "output")):
            with pytest.raises(BizException):
                read(identifier, "other-user")
        assert api.list_templates("other-user") == []
    finally:
        api.close()
        worker.close()
    reopened = SqliteDocxRepository(path)
    try:
        assert reopened.get_template("template").created_at
        assert reopened.get_output("output").file_path == "output.docx"
        reopened.soft_delete_template("template")
        assert reopened.get_template("template") is None
        assert reopened.list_templates("owner") == []
    finally:
        reopened.close()
