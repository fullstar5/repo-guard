FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --requirement requirements.txt

COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini .
COPY --chown=app:app app ./app

USER app

EXPOSE 8000

# Northflank overrides this command for worker, migration, and cron workloads.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]