from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, health
from app.api.errors import TypedHTTPException, typed_http_exception_handler
from app.config import settings
from app.db.database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up ModelAudit AI backend")
    from app.middleware.rate_limiter import rate_limiter_instance
    await rate_limiter_instance.load_scripts()
    # LLM_STARTUP_PROBE (off by default): a detached background task that only logs. It is
    # started before the slow warm-up and never awaited, so it cannot delay or fail start-up.
    probe_task = None
    if settings.llm_startup_probe:
        from app.services.llm.startup_probe import start_startup_probe
        probe_task = start_startup_probe()
    if settings.warm_models_on_startup:
        from app.services.warmup import warm_models
        await warm_models()
    yield
    # Shutdown
    logger.info("Shutting down")
    if probe_task is not None:
        from app.services.llm.startup_probe import stop_startup_probe
        await stop_startup_probe(probe_task)
    await engine.dispose()

app = FastAPI(
    title="ModelAudit AI API",
    description="API for ModelAudit AI",
    version="0.1.0",
    lifespan=lifespan,
)

# Typed errors (PR-02): `{"detail", "code", "retryable"}` for /compare and /gap-analysis failures.
app.add_exception_handler(TypedHTTPException, typed_http_exception_handler)

# CORS
origins =settings.allowed_origins_list or ["http://localhost:5173", "http://localhost:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Routers
app.include_router(health.router)
app.include_router(auth.router)
from app.api import documents, query, compare, gap_analysis, regulatory, models, system, privacy, rag_eval
from fastapi import Depends
from app.middleware.rate_limiter import get_rate_limiter

# Note: Documents, query, compare, gap_analysis, and regulatory should have the rate limiter
# But for simplicity, we add it to the routers that cost tokens.
app.include_router(documents.router, dependencies=[Depends(get_rate_limiter)])
app.include_router(query.router, dependencies=[Depends(get_rate_limiter)])
app.include_router(compare.router, dependencies=[Depends(get_rate_limiter)])
app.include_router(gap_analysis.router, dependencies=[Depends(get_rate_limiter)])
app.include_router(regulatory.router, dependencies=[Depends(get_rate_limiter)])
app.include_router(models.router, dependencies=[Depends(get_rate_limiter)])
app.include_router(system.router, dependencies=[Depends(get_rate_limiter)])
app.include_router(privacy.router, dependencies=[Depends(get_rate_limiter)])
app.include_router(rag_eval.router, dependencies=[Depends(get_rate_limiter)])
