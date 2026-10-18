# Python API + worker; also serves the web app (plain HTML/CSS/JS, no build) at /app
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY mentora ./mentora
COPY scripts ./scripts
# CPU-only PyTorch keeps the image small; the ml extra adds the embedding/rerank/NLI models.
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu ".[ml]"

COPY data ./data
COPY frontend ./frontend

EXPOSE 8000
# The API creates MongoDB indexes on start (idempotent). PORT is set by hosts such as
# Render; proxy headers keep https URLs correct behind them.
CMD ["sh", "-c", "exec uvicorn mentora.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
