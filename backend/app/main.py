from contextlib import asynccontextmanager

import httpx  # pyright: ignore[reportMissingImports]
from fastapi import FastAPI  # pyright: ignore[reportMissingImports]
from fastapi.middleware.cors import CORSMiddleware  # pyright: ignore[reportMissingImports]

from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.repositories import router as repositories_router
from app.api.pull_requests import router as pull_requests_router
from app.api.pr_files import router as pull_request_files_router
from app.api.review_jobs import router as review_jobs_router
from app.api.webhooks import router as webhooks_router
from app.core.database import engine
from app.core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the shared HTTP client on startup and close it on shutdown.

    Args:
        app: The FastAPI application. ``app.state.http_client`` is set here.

    Returns:
        None. Control returns to FastAPI while the process is serving.
    """
    app.state.http_client = httpx.AsyncClient(timeout=5.0)
    yield
    await app.state.http_client.aclose()
    await engine.dispose()

settings = get_settings()

app = FastAPI(
    title="Repo Guard AI",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(repositories_router)
app.include_router(pull_requests_router)
app.include_router(pull_request_files_router)
app.include_router(review_jobs_router)
app.include_router(webhooks_router)


@app.get("/")
async def read_root():
    """Confirm the API process is responding.

    Returns:
        A static message. Does not check the database or Redis.
    """
    return {"message": "Repo Guard AI backend is running"}