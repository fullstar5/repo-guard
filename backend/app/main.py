from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.repositories import router as repositories_router
from app.api.pull_requests import router as pull_requests_router
from app.api.pr_files import router as pull_request_files_router
from app.api.review_jobs import router as review_jobs_router
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
app.include_router(auth_router)
app.include_router(repositories_router)
app.include_router(pull_requests_router)
app.include_router(pull_request_files_router)
app.include_router(review_jobs_router)


@app.get("/")
async def read_root():
    return {"message": "Repo Guard AI backend is running"}