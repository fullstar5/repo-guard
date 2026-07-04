import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import engine

router = APIRouter(tags=["health"])
settings = get_settings()


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


@router.get("/health")
async def health_check(request: Request):
    services: dict[str, dict[str, str]] = {}
    overall_status = "ok"

    try:
        services["postgres"] = await check_postgres()
    except Exception as exc:
        overall_status = "error"
        services["postgres"] = {
            "status": "error",
            "detail": str(exc),
        }

    try:
        http_client: httpx.AsyncClient = request.app.state.http_client
        services["redis"] = await check_redis(http_client)
    except Exception as exc:
        overall_status = "error"
        services["redis"] = {
            "status": "error",
            "detail": str(exc),
        }

    status_code = 200 if overall_status == "ok" else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall_status,
            "services": services,
        },
    )