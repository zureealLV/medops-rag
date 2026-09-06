"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.answers import router as answers_router
from app.api.artifacts import router as artifacts_router
from app.api.audit import router as audit_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.api.knowledge_bases import router as knowledge_bases_router
from app.api.search import router as search_router
from app.api.tools import router as tools_router
from app.api.users import router as users_router
from app.config import Settings
from app.db import initialize
from app.exceptions import install_exception_handlers
from app.logging import configure_logging
from app.observability import install_observability


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        initialize(resolved.database_path)
        yield

    application = FastAPI(
        title="MedOps RAG",
        version="2.0.0-beta.2-dev",
        description=(
            "Auditable multimodal RAG for synthetic hospital IT operations knowledge. "
            "Not medical advice."
        ),
        lifespan=lifespan,
    )
    application.state.settings = resolved
    for router in (
        health_router,
        users_router,
        knowledge_bases_router,
        jobs_router,
        documents_router,
        artifacts_router,
        search_router,
        answers_router,
        tools_router,
        audit_router,
    ):
        application.include_router(router)
    install_exception_handlers(application)
    install_observability(application)
    configure_logging(resolved.log_level)
    return application


app = create_app()
