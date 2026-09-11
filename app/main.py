"""FastAPI application factory."""

from contextlib import AsyncExitStack, asynccontextmanager
from functools import partial
from pathlib import Path

import httpx
from anyio import to_thread
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings

from app.agents.model import ModelProvider
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
from app.mcp import create_mcp_server
from app.observability import install_observability

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VUE_WEB_ROOT = REPOSITORY_ROOT / "frontend" / "dist"
LEGACY_WEB_ROOT = REPOSITORY_ROOT / "web"


def _resolve_web_root() -> Path:
    """Prefer the production Vue bundle while keeping source checkouts runnable."""
    return VUE_WEB_ROOT if (VUE_WEB_ROOT / "index.html").is_file() else LEGACY_WEB_ROOT


def create_app(
    settings: Settings | None = None,
    *,
    model_transport: httpx.BaseTransport | None = None,
    model_async_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    resolved = settings or Settings.from_env()
    if model_async_transport is None and isinstance(model_transport, httpx.MockTransport):
        model_async_transport = model_transport
    model_provider = ModelProvider(
        resolved,
        transport=model_transport,
        async_transport=model_async_transport,
    )
    mcp_server = create_mcp_server(resolved, model_provider)
    mcp_app = mcp_server.streamable_http_app(
        streamable_http_path="/",
        json_response=True,
        stateless_http=True,
        max_request_body_size=1_048_576,
        transport_security=TransportSecuritySettings(
            allowed_hosts=list(resolved.mcp_allowed_hosts),
            allowed_origins=list(resolved.mcp_allowed_origins),
        ),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with AsyncExitStack() as stack:
            await model_provider.start()
            stack.push_async_callback(model_provider.aclose)
            await stack.enter_async_context(mcp_server.session_manager.run())
            await to_thread.run_sync(partial(initialize, resolved.database_path))
            yield

    application = FastAPI(
        title="MedOps RAG",
        version="3.4.0",
        description=(
            "Auditable multimodal RAG for public medical knowledge and medical-device evidence. "
            "Educational use only; not medical advice."
        ),
        lifespan=lifespan,
    )
    application.state.settings = resolved
    application.state.model_provider = model_provider
    application.state.mcp_server = mcp_server
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
    application.mount("/mcp", mcp_app, name="mcp")
    application.mount("/ui", StaticFiles(directory=_resolve_web_root(), html=True), name="ui")

    @application.get("/", include_in_schema=False)
    def web_console() -> RedirectResponse:
        return RedirectResponse(url="/ui/")

    install_exception_handlers(application)
    install_observability(application)
    configure_logging(resolved.log_level)
    return application


app = create_app()
