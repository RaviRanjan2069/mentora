# --- 1. build the React frontend ------------------------------------------------------
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2. Python API + worker (serves the built frontend at /app) ----------------------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY mentora ./mentora
COPY scripts ./scripts
# CPU-only PyTorch keeps the image small; the ml extra adds the embedding/rerank/NLI models.
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu ".[ml]"

COPY alembic.ini ./
COPY alembic ./alembic
COPY data ./data
COPY --from=web /web/dist ./frontend/dist

EXPOSE 8000
# PORT is set by hosts such as Render; proxy headers keep https URLs correct behind them.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn mentora.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
