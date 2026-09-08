import logging

import httpx  # pyright: ignore[reportMissingImports]
from fastapi import APIRouter, Request  # pyright: ignore[reportMissingImports]
from fastapi.responses import JSONResponse  # pyright: ignore[reportMissingImports]
from sqlalchemy import text  # pyright: ignore[reportMissingImports]

from app.core.config import get_settings
from app.core.database import engine

router = APIRouter(tags=["health"])
settings = get_settings()
logger = logging.getLogger(__name__)


async def check_postgres() -> dict:
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        is_ok = result.scalar() == 1

    return {"status": "ok" if is_ok else "error"}


async def check_redis(http_client: httpx.AsyncClient) -> dict:
    response = await http_client.post(
        settings.upstash_redis_rest_url,
        headers={
            "Authorization": f"Bearer {settings.upstash_redis_rest_token}",
        },
        json=["PING"],
    )
    response.raise_for_status()

    payload = response.json()
    is_ok = payload.get("result") == "PONG"

    return {"status": "ok" if is_ok else "error"}


@router.get("/health/live")
async def liveness_check():
    """Confirm that the API process is running without calling dependencies."""
    return {"status": "ok"}


async def _readiness_response(request: Request) -> JSONResponse:
    """
    Report whether the API can serve database-backed requests.

    PostgreSQL is required and controls the HTTP status. Redis protects selected
    write paths, which fail closed independently; its outage is reported as
    degraded without restarting an otherwise healthy API process.
    """
    services: dict[str, dict[str, str]] = {}
    postgres_ready = True
    redis_ready = True

    try:
        services["postgres"] = await check_postgres()
    except Exception:
        postgres_ready = False
        services["postgres"] = {"status": "error"}
        logger.exception("PostgreSQL readiness check failed")

    try:
        http_client: httpx.AsyncClient = request.app.state.http_client
        services["redis"] = await check_redis(http_client)
    except Exception:
        redis_ready = False
        services["redis"] = {"status": "error"}
        logger.exception("Redis readiness check failed")

    if not postgres_ready:
        overall_status = "error"
        status_code = 503
    elif not redis_ready:
        overall_status = "degraded"
        status_code = 200
    else:
        overall_status = "ok"
        status_code = 200

    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall_status,
            "services": services,
        },
    )


@router.get("/health/ready")
async def readiness_check(request: Request):
    """Expose dependency readiness for deployment probes."""
    return await _readiness_response(request)
