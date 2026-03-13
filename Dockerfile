# AI GC START
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    UVICORN_WORKERS=1 \
    APP_DATA_DIR=/app/data \
    APP_DB_PATH=/app/data/app.db \
    APP_LLM_TIMEOUT_SECONDS=60

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY app /app/app

RUN python -m pip install --upgrade pip && \
    python -m pip install .

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host ${APP_HOST} --port ${APP_PORT} --workers ${UVICORN_WORKERS}"]
# AI GC END
