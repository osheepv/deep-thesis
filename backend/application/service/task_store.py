# -*- coding: utf-8 -*-
"""任务记录与持久化存储（从 uc_main_orchestration.py 拆出）。

TaskRecord 负责应用层任务数据结构（含各环产物、模板映射），
_TaskStore 负责 SQLite / 内存持久化（含工作区位置 CAS 写入）。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from common.resume import (
    WorkspaceRevisionConflict,
    read_revision,
    workspace_content,
)
from jobs.runtime import job_write_fence


class TaskRecord:
    """应用层任务记录（含各环产物，可落库）。"""

    RING_FIELDS = tuple(f"ring{i}" for i in range(1, 11))

    def __init__(self, task_id: str, title: str, degree: str, subject_field: str,
                 session_id: str = "", tenant_id: str = "default",
                 template_id: Optional[str] = None, scope: str = "all",
                 template_path: str = "",
                 template_name: str = "",
                 template_placeholders: Optional[List[str]] = None,
                 template_mapping: Optional[Dict[str, str]] = None,
                 owner_user_id: str = "") -> None:
        self.task_id = task_id
        self.title = title
        self.degree = degree
        self.subject_field = subject_field
        self.template_id = template_id
        self.template_path = template_path
        self.template_name = template_name
        self.template_placeholders = list(template_placeholders or [])
        self.template_mapping = dict(template_mapping or {})
        self.owner_user_id = owner_user_id
        self.session_id = session_id
        self.tenant_id = tenant_id
        self.scope = scope
        self.ring1: Optional[Dict[str, Any]] = None
        self.ring2: Optional[Dict[str, Any]] = None
        self.ring3: Optional[Dict[str, Any]] = None
        self.ring4: Optional[Dict[str, Any]] = None
        self.ring5: Optional[Dict[str, Any]] = None
        self.ring6: Optional[Dict[str, Any]] = None
        self.ring7: Optional[Dict[str, Any]] = None
        self.ring8: Optional[Dict[str, Any]] = None
        self.ring9: Optional[Dict[str, Any]] = None
        self.ring10: Optional[Dict[str, Any]] = None
        self.docx: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """序列化（环产物为 JSON 文本；None 存 "null" 保持语义）。"""
        def _dump(v: Optional[Dict[str, Any]]) -> str:
            if v is None:
                return "null"
            try:
                return json.dumps(v, ensure_ascii=False)
            except (TypeError, ValueError):
                return "null"
        row: Dict[str, Any] = {
            "task_id": self.task_id,
            "title": self.title,
            "degree": self.degree,
            "subject_field": self.subject_field,
            "template_id": self.template_id or "",
            "template_path": self.template_path,
            "template_name": self.template_name,
            "template_placeholders": list(self.template_placeholders),
            "template_mapping": dict(self.template_mapping),
            "owner_user_id": self.owner_user_id,
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "scope": getattr(self, "scope", "all"),
        }
        for f in TaskRecord.RING_FIELDS:
            row[f] = _dump(getattr(self, f))
        row["docx"] = _dump(self.docx)
        return row

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskRecord":
        """反序列化（遗漏的环产物置 None，不补空壳）。"""

        def _load(v: Any) -> Optional[Dict[str, Any]]:
            if isinstance(v, dict):
                return v
            if isinstance(v, str) and v.strip() not in ("", "null"):
                try:
                    return json.loads(v)
                except (TypeError, ValueError):
                    return None
            return None

        rec = cls(
            task_id=data.get("task_id", ""),
            title=data.get("title", ""),
            degree=data.get("degree", "MASTER"),
            subject_field=data.get("subject_field", ""),
            session_id=data.get("session_id", ""),
            tenant_id=data.get("tenant_id", "default"),
            template_id=data.get("template_id") or None,
            scope=data.get("scope", "all"),
            template_path=str(data.get("template_path", "")),
            template_name=str(data.get("template_name", "")),
            template_placeholders=list(data.get("template_placeholders", []) or []),
            template_mapping=dict(data.get("template_mapping", {}) or {}),
            owner_user_id=str(data.get("owner_user_id", "")),
        )
        for f in cls.RING_FIELDS:
            setattr(rec, f, _load(data.get(f)))
        rec.docx = _load(data.get("docx"))
        return rec


class TaskStore:
    """任务暂存：默认 SQLite 文件持久化（重启不丢），测试可切内存。

    存储结构（内置 sqlite3，零新依赖）：
        t_task_store(
            task_id TEXT PRIMARY KEY,
            payload TEXT,        -- 整条 TaskRecord 的 JSON
            created_at TEXT,
            updated_at TEXT
        )
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._lock = threading.Lock()
        # 显式传 db_path = 必须 SQLite（测试/自管场景）；不传时按环境变量切内存
        if db_path is None and os.getenv("THESIS_TASK_STORE_MEMORY", "").lower() == "true":
            self._path = None
            self._tasks = {}
            self._workspace = {}
            self._db = None
            return
        self._path = db_path or self._default_path()
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._db = sqlite3.connect(self._path, check_same_thread=False, timeout=15)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS t_task_store ("
            "task_id TEXT PRIMARY KEY, payload TEXT NOT NULL, "
            "created_at TEXT, updated_at TEXT)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS t_workspace_state ("
            "workspace_key TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        self._db.commit()

    @staticmethod
    def _default_path() -> str:
        base = os.getenv("THESIS_TASK_STORE_DIR", "")
        if not base:
            # 默认与 thesis.db 同目录（backend/），gitignored
            here = os.path.dirname(os.path.abspath(__file__))
            base = os.path.join(os.path.dirname(os.path.dirname(here)), ".")
        return os.path.join(base, "task_store.db")

    def put(self, rec: TaskRecord) -> TaskRecord:
        with job_write_fence(rec.task_id), self._lock:
            if self._db is None:
                self._tasks[rec.task_id] = deepcopy(rec)
            else:
                payload = json.dumps(rec.to_dict(), ensure_ascii=False)
                now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                self._db.execute(
                    "INSERT INTO t_task_store(task_id, payload, created_at, updated_at) "
                    "VALUES(?, ?, ?, ?) "
                    "ON CONFLICT(task_id) DO UPDATE SET payload=excluded.payload, "
                    "updated_at=excluded.updated_at",
                    (rec.task_id, payload, now, now),
                )
                self._db.commit()
        return rec

    def get(self, task_id: str) -> Optional[TaskRecord]:
        with self._lock:
            if self._db is None:
                return deepcopy(self._tasks.get(task_id))
            row = self._db.execute(
                "SELECT payload FROM t_task_store WHERE task_id=?", (task_id,)
            ).fetchone()
        if row is None:
            return None
        try:
            return TaskRecord.from_dict(json.loads(row[0]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def all(self) -> List[TaskRecord]:
        """全部任务（会话列表）。"""
        with self._lock:
            if self._db is None:
                return deepcopy(list(self._tasks.values()))
            rows = self._db.execute(
                "SELECT payload FROM t_task_store ORDER BY created_at"
            ).fetchall()
        recs: List[TaskRecord] = []
        for (payload,) in rows:
            try:
                recs.append(TaskRecord.from_dict(json.loads(payload)))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return recs

    def delete(self, task_id: str) -> bool:
        """删除任务。"""
        with job_write_fence(task_id), self._lock:
            if self._db is None:
                return self._tasks.pop(task_id, None) is not None
            cur = self._db.execute(
                "DELETE FROM t_task_store WHERE task_id=?", (task_id,)
            )
            self._db.commit()
            return cur.rowcount > 0

    def _write_workspace(
        self, workspace_key: str, value: Dict[str, Any], now: str
    ) -> Dict[str, Any]:
        """无条件写入（调用方必须已经在锁内并完成 revision 判定）。"""
        payload = {
            **dict(value),
            "revision": read_revision(value),
            "updated_at": now,
        }
        if self._db is None:
            self._workspace[workspace_key] = payload
        else:
            self._db.execute(
                "INSERT INTO t_workspace_state(workspace_key, payload, updated_at) "
                "VALUES(?, ?, ?) ON CONFLICT(workspace_key) DO UPDATE SET "
                "payload=excluded.payload, updated_at=excluded.updated_at",
                (workspace_key, json.dumps(payload, ensure_ascii=False), now),
            )
        return dict(payload)

    def _read_workspace_locked(self, workspace_key: str) -> Dict[str, Any]:
        """在锁内读取当前行（不额外加锁，供 CAS 判定复用）。"""
        if self._db is None:
            return dict(self._workspace.get(workspace_key, {}))
        row = self._db.execute(
            "SELECT payload FROM t_workspace_state WHERE workspace_key=?",
            (workspace_key,),
        ).fetchone()
        if row is None:
            return {}
        try:
            value = json.loads(str(row[0]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(value) if isinstance(value, dict) else {}

    def put_workspace(self, workspace_key: str, value: Dict[str, Any]) -> Dict[str, Any]:
        """按 revision 单调写入工作区位置。

        - incoming > current：接受；
        - incoming < current：拒绝（旧请求不能倒退覆盖）；
        - incoming == current 且内容相同：幂等重放，返回现有状态；
        - incoming == current 且内容不同：明确冲突，不覆盖；
        - 无历史行：作为首次写入接受。
        比较与写入都在同一把锁内完成，乱序到达的请求不会互相倒退。
        """
        workspace_key = workspace_key.strip()
        if not workspace_key or len(workspace_key) > 200:
            raise ValueError("workspace_key非法")
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        incoming_revision = read_revision(value)
        with self._lock:
            current = self._read_workspace_locked(workspace_key)
            if current:
                current_revision = read_revision(current)
                if incoming_revision < current_revision:
                    raise WorkspaceRevisionConflict(
                        current_revision, incoming_revision, "旧快照"
                    )
                if incoming_revision == current_revision:
                    if workspace_content(current) == workspace_content(value):
                        return dict(current)
                    raise WorkspaceRevisionConflict(
                        current_revision, incoming_revision, "同版本内容不同"
                    )
            stored = self._write_workspace(workspace_key, value, now)
            if self._db is not None:
                self._db.commit()
            return stored

    def bump_workspace_revision(self, workspace_key: str) -> int:
        """把指定工作区的 revision 提升到当前值 + 1，返回新 revision。"""
        workspace_key = workspace_key.strip()
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._lock:
            current = self._read_workspace_locked(workspace_key)
            if not current:
                return 0
            next_revision = read_revision(current) + 1
            self._write_workspace(workspace_key, {**current, "revision": next_revision}, now)
            if self._db is not None:
                self._db.commit()
            return next_revision

    def get_workspace(self, workspace_key: str) -> Dict[str, Any]:
        workspace_key = workspace_key.strip()
        with self._lock:
            return self._read_workspace_locked(workspace_key)

    def clear_workspace_task(self, task_id: str) -> None:
        """删除任务后清理所有指向它的工作区位置，包括展开项和编辑锚点。

        服务端状态修改必须产生比当前更高的 revision，
        这样客户端仍在途的旧 POST 不会把位置倒退回被删任务。
        """
        cleared_position = {
            "last_task_id": "",
            "active_tab": "refs",
            "expanded_items": [],
            "editor_anchor": "",
        }
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._lock:
            if self._db is None:
                for key, value in list(self._workspace.items()):
                    if str(value.get("last_task_id", "")) == task_id:
                        self._workspace[key] = {
                            **value, **cleared_position,
                            "revision": read_revision(value) + 1, "updated_at": now,
                        }
                return
            rows = self._db.execute(
                "SELECT workspace_key, payload FROM t_workspace_state"
            ).fetchall()
            dirty = False
            for workspace_key, raw in rows:
                try:
                    value = json.loads(str(raw))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if not isinstance(value, dict):
                    continue
                if str(value.get("last_task_id", "")) != task_id:
                    continue
                value.update({
                    **cleared_position,
                    "revision": read_revision(value) + 1,
                    "updated_at": now,
                })
                self._db.execute(
                    "UPDATE t_workspace_state SET payload=?, updated_at=? WHERE workspace_key=?",
                    (json.dumps(value, ensure_ascii=False), now, str(workspace_key)),
                )
                dirty = True
            if dirty:
                self._db.commit()
            self._db.commit()
