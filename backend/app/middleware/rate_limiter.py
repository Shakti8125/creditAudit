from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Union

import anyio
from fastapi import Depends, HTTPException, Request
from upstash_redis.asyncio import Redis

from app.config import settings
from app.api.deps import get_current_user
from app.schemas.auth import TokenPayload

logger = logging.getLogger(__name__)

LUA_DIR = Path(__file__).resolve().parent.parent.parent / "lua"


class RateLimiter:
    """FastAPI Rate Limiter middleware backed by Upstash Redis and atomic Lua scripts."""

    def __init__(self) -> None:
        self.redis = Redis(url=settings.redis.url, token=settings.redis.token)
        self.token_bucket_sha: str | None = None
        self.gcra_sha: str | None = None
        self._scripts_loaded: bool = False

    async def load_scripts(self) -> None:
        """Dynamically load Lua scripts into Redis and store their SHAs."""
        if self._scripts_loaded:
            return

        try:
            token_bucket_path = LUA_DIR / "token_bucket.lua"
            token_bucket_script = await anyio.Path(token_bucket_path).read_text(encoding="utf-8")
            self.token_bucket_sha = await self.redis.script_load(token_bucket_script)

            gcra_path = LUA_DIR / "gcra_leaky_bucket.lua"
            gcra_script = await anyio.Path(gcra_path).read_text(encoding="utf-8")
            self.gcra_sha = await self.redis.script_load(gcra_script)

            self._scripts_loaded = True
            logger.info("Rate limiting Lua scripts successfully loaded into Redis.")
        except Exception as e:
            logger.error(f"Failed to load rate limiting scripts: {e}", exc_info=True)

    async def check_rate_limit(
        self,
        request: Request,
        current_user: Union[TokenPayload, dict[str, Any]],
    ) -> bool:
        """Check rate limit for current request and tenant."""
        if not self._scripts_loaded:
            await self.load_scripts()

        if isinstance(current_user, TokenPayload):
            tenant_id = str(current_user.tenant_id) if current_user.tenant_id else "default"
            tier = getattr(current_user, "tier", "FREE") or "FREE"
        else:
            tenant_id = str(current_user.get("tenant_id", "default"))
            tier = current_user.get("tier", "FREE") or "FREE"

        if hasattr(tier, "value"):
            tier = tier.value
        tier = str(tier).upper()

        # Determine cost based on endpoint
        path = request.url.path
        cost = 1
        if "/compare" in path:
            cost = 5
        elif "/gap-analysis" in path:
            cost = 3
        elif "/health" in path:
            cost = 0

        if cost == 0:
            return True

        # Tier capacities and rates
        tier_configs = {
            "FREE": {"capacity": 10, "refill_rate": 1},
            "PROFESSIONAL": {"capacity": 100, "refill_rate": 5},
            "ENTERPRISE": {"capacity": 1000, "refill_rate": 50},
        }

        config = tier_configs.get(tier, tier_configs["FREE"])
        capacity = config["capacity"]
        refill_rate = config["refill_rate"]

        if cost > capacity:
            raise HTTPException(
                status_code=403,
                detail="Cost exceeds maximum burst capacity for your tier.",
            )

        now = int(time.time())
        key = f"rate_limit:tenant:{tenant_id}"

        try:
            if not self.token_bucket_sha:
                await self.load_scripts()

            # Execute token bucket Lua script
            result = await self.redis.evalsha(
                self.token_bucket_sha,
                [key],
                [capacity, refill_rate, cost, now],
            )

            allowed = result[0]
            val = result[1]

            if allowed == 0:
                retry_after = val
                raise HTTPException(
                    status_code=429,
                    detail="Too Many Requests",
                    headers={"Retry-After": str(retry_after)},
                )
            return True
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Rate limiting error: {e}", exc_info=True)
            return True  # Fail open


rate_limiter_instance = RateLimiter()


async def get_rate_limiter(
    request: Request,
    current_user: TokenPayload = Depends(get_current_user),
) -> None:
    """FastAPI dependency to enforce rate limits per request."""
    await rate_limiter_instance.check_rate_limit(request, current_user)

