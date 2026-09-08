"""Persistent template and output records shared by the API and worker."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from .docx_repository import DocxRepository, TemplateRecordDict


class SqliteDocxRepository(DocxRepository):
    def __init__(self, db_path):
        super().__init__()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False, timeout=15)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS t_docx_record ("
            "kind TEXT NOT NULL, record_id TEXT NOT NULL, session_id TEXT NOT NULL, "
            "deleted INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL, "
            "PRIMARY KEY(kind, record_id))"
        )
        self._db.commit()

    def close(self):
        with self._lock:
            self._db.close()

    def _save(self, kind, record_id, record):
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO t_docx_record(kind, record_id, session_id, deleted, payload) "
                "VALUES(?, ?, ?, ?, ?) ON CONFLICT(kind, record_id) DO UPDATE SET "
                "session_id=excluded.session_id, deleted=excluded.deleted, payload=excluded.payload",
                (kind, record_id, record.get("session_id", ""), bool(record.get("deleted")),
                 json.dumps(record, ensure_ascii=False)),
            )
        return record

    def _get(self, kind, record_id):
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM t_docx_record WHERE kind=? AND record_id=? AND deleted=0",
                (kind, record_id),
            ).fetchone()
        return TemplateRecordDict(json.loads(row[0])) if row else None

    def save_template(self, record):
        record = TemplateRecordDict(record)
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        record.setdefault("created_at", now)
        record.setdefault("updated_at", now)
        record.setdefault("deleted", False)
        return self._save("template", record["template_id"], record)

    def get_template(self, template_id):
        return self._get("template", template_id)

    def list_templates(self, session_id):
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM t_docx_record WHERE kind='template' AND deleted=0 "
                "AND (?='' OR session_id=?) ORDER BY record_id", (session_id, session_id),
            ).fetchall()
        return [TemplateRecordDict(json.loads(row[0])) for row in rows]

    def soft_delete_template(self, template_id):
        with self._lock, self._db:
            self._db.execute(
                "UPDATE t_docx_record SET deleted=1 WHERE kind='template' AND record_id=?",
                (template_id,),
            )

    def save_output(self, output):
        record = TemplateRecordDict(output)
        record.setdefault("created_at", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
        record.setdefault("deleted", False)
        return self._save("output", record["file_id"], record)

    def get_output(self, file_id):
        return self._get("output", file_id)
