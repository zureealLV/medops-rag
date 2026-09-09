"""FastAPI application factory."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.answers import router as answers_router
from app.api.artifacts import router as artifacts_router
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.api.knowledge_bases import router as knowledge_bases_router
from app.api.metrics import router as metrics_router
from app.api.search import router as search_router
from app.api.summaries import router as summaries_router
from app.api.tools import router as tools_router
from app.api.users import router as users_router
from app.config import Settings
from app.db import initialize
from app.exceptions import install_exception_handlers
from app.logging import configure_logging
from app.observability import install_observability

WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        initialize(resolved.database_path)
        yield

    application = FastAPI(
        title="MedOps RAG",
        version="3.0.0",
        description=(
            "Auditable multimodal RAG for public medical knowledge and medical-device evidence. "
            "Educational use only; not medical advice."
        ),
        lifespan=lifespan,
    )
    application.state.settings = resolved
    for router in (
        health_router,
        auth_router,
        users_router,
        knowledge_bases_router,
        metrics_router,
        jobs_router,
        summaries_router,
        documents_router,
        artifacts_router,
        search_router,
        answers_router,
        tools_router,
        audit_router,
    ):
        application.include_router(router)
    application.mount("/ui", StaticFiles(directory=WEB_ROOT, html=True), name="ui")

    @application.get("/", include_in_schema=False)
    def web_console() -> RedirectResponse:
        return RedirectResponse(url="/ui/")

    install_exception_handlers(application)
    install_observability(application)
    configure_logging(resolved.log_level)
    return application


app = create_app()
