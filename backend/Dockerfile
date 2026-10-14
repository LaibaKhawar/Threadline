# Threadline backend image (API, worker, beat and migrations share it).
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data EVAL_RESULTS_DIR=/data/eval-results EMBEDDING_CACHE_DIR=/models HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
RUN mkdir -p app evals && touch app/__init__.py evals/__init__.py && pip install ".[embeddings]" && pip uninstall -y threadline
COPY . .
RUN pip install --no-deps . \
    # bake the local embedding model into the image so first start works offline
    && python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/models')" \
    && useradd -u 10001 -m threadline && mkdir -p /data && chown -R threadline /data /models
USER threadline
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=10 CMD curl -fsS http://localhost:8000/api/health || exit 1
# The frontend proxy forwards X-Forwarded-For; trusting it gives per-client rate limits. Only expose :8000 to that proxy.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
