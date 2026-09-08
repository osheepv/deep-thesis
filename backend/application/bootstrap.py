"""Shared API and standalone worker assembly without creating an HTTP app."""

import os
from pathlib import Path


def configure_storage() -> Path | None:
    value = os.getenv("THESIS_DATA_DIR", "").strip()
    if not value:
        return None
    root = Path(value).expanduser()
    if not root.is_absolute():
        raise ValueError("THESIS_DATA_DIR must be an absolute path")
    if os.getenv("THESIS_TASK_STORE_MEMORY", "").lower() == "true":
        raise ValueError("THESIS_DATA_DIR requires THESIS_TASK_STORE_MEMORY=false")
    root = root.resolve()
    paths = {
        "THESIS_TASK_STORE_DIR": root,
        "THESIS_KB_ROOT": root / "kb",
        "DOCX_UPLOAD_DIR": root / "templates",
        "DOCX_OUTPUT_DIR": root / "outputs",
        **{f"THESIS_{name}_DB": root / filename for name, filename in {
            "ARTIFACT": "artifacts.db", "EVIDENCE": "evidence.db",
            "RESEARCH": "research.db", "SECTION": "sections.db",
            "AUTOSAVE": "autosave.db", "JOB": "jobs.db",
            "SECURITY": "security.db", "DOCX": "docx.db",
        }.items()},
    }
    for name, default in paths.items():
        if not Path(os.getenv(name, str(default))).is_absolute():
            raise ValueError(f"{name} must be an absolute persistent path")
    root.mkdir(parents=True, exist_ok=True)
    for name, default in paths.items():
        os.environ.setdefault(name, str(default))
    os.environ.setdefault("THESIS_DB_URL", f"sqlite:///{(root / 'thesis.db').as_posix()}")
    return root


def build_orchestration(*, require_persistent: bool = False):
    root = configure_storage()
    from db.session import build_fsm_repository
    from fsm.orchestrator import FsmOrchestrator
    from knowledge.store import get_kb_store
    from thesis_docx.repository import DocxRepository
    from thesis_docx.service import DocxService
    from .service.uc_main_orchestration import MainOrchestration, RealDocxRenderer

    fsm = FsmOrchestrator(build_fsm_repository(require_persistent=require_persistent or root is not None))
    if root is not None:
        from thesis_docx.repository.sqlite_repository import SqliteDocxRepository

        repository = SqliteDocxRepository(os.environ["THESIS_DOCX_DB"])
    else:
        repository = DocxRepository()
    docx_service = DocxService(repository=repository)
    orchestration = MainOrchestration(
        fsm=fsm, docx_renderer=RealDocxRenderer(repository=repository),
        knowledge_store=get_kb_store(),
    )
    orchestration._docx_service = docx_service
    return orchestration
