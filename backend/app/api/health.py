from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.db.database import get_db

router = APIRouter(prefix="/health", tags=["health"])

@router.get("")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Health check endpoint."""
    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Health check DB ping failed: {e}")
        db_status = "disconnected"
        
    return {
        "status": "ok",
        "db": db_status,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

