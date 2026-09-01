from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, health
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
    yield
    # Shutdown
    logger.info("Shutting down")
    await engine.dispose()

app = FastAPI(
    title="ModelAudit AI API",
    description="API for ModelAudit AI",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
origins = settings.allowed_origins_list or ["http://localhost:5173", "http://localhost:3000"]

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
from app.api import documents, query, compare, gap_analysis, regulatory, models, system, privacy
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
