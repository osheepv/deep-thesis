# -*- coding: utf-8 -*-
"""FastAPI 应用入口（application 层主编排装配）。

职责：
    1) 实例化主编排用例 MainOrchestration（内部含 M1 FSM / M2 执行体 / M5+M6 docx），
       挂到 app.state 供控制器依赖注入。
    2) 挂载主编排聚合路由（WriterConsole，/api/v1/console）。
    3) 注册 BizException / 校验 / 兜底异常处理器，统一转 `Result.fail`。

关于业务模块原生 HTTP 路由（M1 / M5+M6）：
    由于共通层 `common.aicoding.dto.Result` 的泛型定义（``Generic[T], BaseModel``）
    不符合 pydantic 2 要求，任何以 ``Result[X]`` 作为返回注解 / response_model 的
    路由（fsm.api / health / tasks）在**模块导入时**即触发
    ``Invalid args for response field``。此为本期共通层契约缺陷，需由 M0/skeleton
    成员修复后，再在本处挂载成员原生路由。当前仅挂载应用层编排路由，
    业务模块通过编排内部函数调用接入（不改动成员产物）。

启动（在 backend 目录）：
    uvicorn application.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from .bootstrap import build_orchestration, configure_storage

configure_storage()

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from common.aicoding.dto.result import Result
from common.aicoding.exception.biz_exception import BizException
from common.aicoding.exception.error_code import ErrorCode

from .controller.writer_console import router as writer_console_router
from .health import router as health_router
from .service.uc_main_orchestration import MainOrchestration
from .tasks import router as tasks_router
from thesis_docx.service import DocxService
from jobs import JobWorker
from security import SecuritySettings, SecurityStore
from security.middleware import SecurityMiddleware
from security.router import router as security_router

logger = logging.getLogger("thesis.application")


def _default_orchestration() -> MainOrchestration:
    """API and worker share business assembly and persistent paths."""
    import fsm.di as _fsm_di

    orchestration = build_orchestration()
    _fsm_di._orchestrator = orchestration._fsm
    return orchestration


def build_app(
    orchestration: Optional[MainOrchestration] = None,
    security_store: Optional[SecurityStore] = None,
) -> FastAPI:
    """构建 FastAPI 应用（主编排闭环）。

    Args:
        orchestration: 预注入的主编排用例（测试可传自定义实例）。
    Returns:
        FastAPI app。
    """
    orchestration = orchestration or _default_orchestration()
    security_settings = (
        security_store.settings if security_store is not None else SecuritySettings.from_env()
    )
    if security_settings.enabled and len(security_settings.bootstrap_token) < 32:
        raise RuntimeError(
            "THESIS_AUTH_ENABLED=true 时必须配置至少32字符的 THESIS_AUTH_BOOTSTRAP_TOKEN"
        )
    security_store = security_store or SecurityStore(
        security_settings.db_path if security_settings.enabled else ":memory:",
        settings=security_settings,
    )
    startup_reconciliation = orchestration.reconcile_startup().data
    job_worker = JobWorker(
        orchestration._jobs,  # noqa: SLF001 - 应用生命周期托管同一持久化注册表
        orchestration.job_handlers(),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if os.getenv("THESIS_JOB_WORKER_ENABLED", "true").lower() not in (
            "0", "false", "no"
        ):
            job_worker.start()
        try:
            yield
        finally:
            job_worker.stop()

    app = FastAPI(
        title="Deep Thesis",
        description="学位论文全流程智能体工作台",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS（本地 UI 预览：http://localhost:8787 等前端端口）
    # 默认仅允许项目文档中的本地 UI；生产用 THESIS_CORS_ORIGINS 显式配置真实来源。
    from fastapi.middleware.cors import CORSMiddleware

    origins_env = os.getenv(
        "THESIS_CORS_ORIGINS",
        "http://127.0.0.1:8787,http://localhost:8787",
    ).strip()
    configured_origins = [
        origin.strip() for origin in origins_env.split(",") if origin.strip()
    ]
    allows_wildcard = "*" in configured_origins
    if security_settings.enabled and allows_wildcard:
        raise RuntimeError("认证模式禁止 THESIS_CORS_ORIGINS=*")
    allow_origins = ["*"] if allows_wildcard else configured_origins
    app.add_middleware(
        SecurityMiddleware,
        store=security_store,
        orchestration=orchestration,
    )
    # Starlette 后添加的中间件位于外层；CORS 必须包住 401/403 安全响应。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=not allows_wildcard,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 主编排聚合路由（/api/v1/console）
    app.include_router(writer_console_router)
    app.include_router(security_router)

    # 业务模块原生路由（M1 FSM / M5+M6 docx / M9 知识库）：
    # 一期曾因 Result[T] 泛型与 pydantic 2 的兼容问题未挂载；pydantic 2.11.4 下
    # 已可正常挂载（实测通过），本次补挂全部业务端点。
    from knowledge.router import router as kb_router
    from thesis_docx.router import router as docx_router

    # fsm 动作路由（闸门/回退）：advance/hitl/rollback，不挂 tasks CRUD（application/tasks 已有）
    from fsm.api import build_fsm_router

    action = build_fsm_router(prefix="/api/v1")
    # 只保留 advance/hitl/rollback/progress 动作路由；tasks CRUD 交给 application/tasks 与 console
    for route in list(action.routes):
        if route.path in ("/api/v1/tasks", "/api/v1/tasks/{task_id}", "/api/v1/tasks/{task_id}/route"):
            action.routes.remove(route)
    app.include_router(action)
    app.include_router(docx_router)
    app.include_router(kb_router)

    # 骨架原生路由（/healthz、/api/v1/tasks）
    app.include_router(health_router)
    app.include_router(tasks_router)

    # 应用级编排单例
    app.state.orchestration = orchestration
    app.state.startup_reconciliation = startup_reconciliation
    app.state.security_store = security_store
    # docx 业务路由（/api/v1/docx/files 等）与 console 链路共享同一服务/仓储
    app.state.docx_service = getattr(orchestration, "_docx_service", None) or DocxService()
    orchestration._docx_service = app.state.docx_service  # noqa: SLF001 - console 模板链路共享持久化服务
    app.state.job_worker = job_worker

    # 异常处理器
    _register_exception_handlers(app)

    return app


def _register_exception_handlers(app: FastAPI) -> None:
    """注册 BizException / 校验 / 兜底异常处理器。"""

    @app.exception_handler(BizException)
    async def biz_exception_handler(request: Request, exc: BizException) -> JSONResponse:
        code = int(exc.code) if exc.code.isdigit() else 0
        payload = Result.fail(code=code, msg=exc.msg, data={"detail": exc.detail})
        return JSONResponse(status_code=exc.http_status, content=payload.model_dump())

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        payload = Result.fail(
            code=int(ErrorCode.INVALID_PARAM.value),
            msg=ErrorCode.INVALID_PARAM.default_msg,
            data={"errors": exc.errors()},
        )
        return JSONResponse(status_code=200, content=payload.model_dump())

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        payload = Result.fail(
            code=int(ErrorCode.SYSTEM_ERROR.value),
            msg=ErrorCode.SYSTEM_ERROR.default_msg,
            data={"err": str(exc)},
        )
        return JSONResponse(status_code=200, content=payload.model_dump())


#: 模块级应用实例（uvicorn application.main:app 直接可启动）。
app = build_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("application.main:app", host="0.0.0.0", port=8000, reload=True)
