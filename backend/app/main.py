from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.database import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(timeout=5.0)
    yield
    await app.state.http_client.aclose()
    await engine.dispose()


app = FastAPI(
    title="Repo Guard AI",
    lifespan=lifespan,
)

app.include_router(health_router)


@app.get("/")
async def read_root():
    return {"message": "Repo Guard AI backend is running"}