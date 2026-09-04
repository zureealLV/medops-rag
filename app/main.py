from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.users import router as users_router
from app.api.knowledge_bases import router as knowledge_bases_router
from app.api.documents import router as documents_router


app = FastAPI()


app.include_router(health_router)
app.include_router(users_router)
app.include_router(knowledge_bases_router)
app.include_router(documents_router)