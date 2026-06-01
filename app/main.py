from fastapi import Depends, FastAPI

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.security import require_internal_api_key
from app.routers import ai, health, rag

configure_logging()
app = FastAPI(title=settings.app_name)

internal_dependencies = [Depends(require_internal_api_key)]
app.include_router(
    health.router,
    prefix="/internal",
    dependencies=internal_dependencies,
)
app.include_router(
    rag.router,
    prefix="/internal",
    dependencies=internal_dependencies,
)
app.include_router(
    ai.router,
    prefix="/internal",
    dependencies=internal_dependencies,
)
