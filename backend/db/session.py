# -*- coding: utf-8 -*-
"""数据库会话/仓储工厂（M4 持久化装配）。

设计（决策：二期限 SQLite 过渡，后期迁 PostgreSQL）：
    - 依据 ``THESIS_DB_URL``（config.Settings.db_url）创建 SQLAlchemy engine；
    - SQLite：开箱即用（Python 内置驱动），自动建表（仅开发便利，生产走 Alembic）；
    - PostgreSQL：按 DDL/Alembic 建表（二期正式迁移时启用）；
    - 连不上 DB（如未装 PG）时：警告并回退 InMemoryFsmRepository，保证服务可启动
      （开发期友好；生产环境应显式配置）。

注意：SQLAlchemy 通用 ``JSON`` 类型在 SQLite 上映射为 TEXT 存储，
与 PostgreSQL JSONB 语义兼容（本项目 FsmStateModel 已使用通用 JSON）。
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import settings

logger = logging.getLogger("thesis.db")


def build_engine(db_url: Optional[str] = None):
    """创建 SQLAlchemy engine。

    Args:
        db_url: 数据库 URL；None 时读取全局配置。
    Returns:
        engine。
    """
    url = db_url or settings.db_url

    if url.startswith("sqlite"):
        # SQLite 默认单线程限制；FastAPI 多线程需关闭检查
        return create_engine(url, connect_args={"check_same_thread": False})

    return create_engine(url)


def build_session_factory(db_url: Optional[str] = None):
    """创建 sessionmaker。"""
    return sessionmaker(bind=build_engine(db_url))


def build_fsm_repository(db_url: Optional[str] = None, *, require_persistent: bool = False):
    """构建 FSM 仓储（SQLAlchemy 优先，连不上回退内存）。

    Returns:
        FsmRepository（SqlAlchemyFsmRepository / InMemoryFsmRepository）。
    """
    from fsm.repository import InMemoryFsmRepository, SqlAlchemyFsmRepository
    from fsm.state.orm import FSMBase

    url = db_url or settings.db_url
    if require_persistent:
        from sqlalchemy.engine import make_url

        parsed = make_url(url)
        if parsed.get_backend_name() == "sqlite":
            from pathlib import Path

            if not parsed.database or not Path(parsed.database).is_absolute() or parsed.query.get("mode") == "memory":
                raise ValueError("Standalone storage requires an absolute persistent THESIS_DB_URL")
    engine = None
    try:
        engine = build_engine(url)
        # 自动建表：开发/过渡期便利；生产由 Alembic 管理（create_all 不破坏已有表）
        FSMBase.metadata.create_all(engine)
        return SqlAlchemyFsmRepository(session_factory=sessionmaker(bind=engine))
    except Exception as exc:  # noqa: BLE001 - 无 PG/权限等开发环境常见
        if require_persistent:
            if engine is not None:
                engine.dispose()
            raise RuntimeError("Persistent FSM database is unavailable; startup refused") from exc
        logger.warning("数据库不可用（%s），回退 InMemory FSM 仓储：%s", url, exc)
        return InMemoryFsmRepository()
