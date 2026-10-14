# Developer shortcuts. Backend venv: backend/.venv (python3.11 -m venv backend/.venv).
PY := backend/.venv/bin/python
.PHONY: setup dev-db api worker web test test-backend test-frontend e2e lint typecheck demo eval eval-llm perf up down backup models

setup:          ## install backend + frontend dependencies
	python3.11 -m venv backend/.venv && backend/.venv/bin/pip install -e "backend[dev,embeddings]"
	cd frontend && npm install

dev-db:         ## PostgreSQL (pgvector) on 5436 and Redis on 6382 for local development
	docker run -d --name threadline-devdb -e POSTGRES_USER=threadline -e POSTGRES_PASSWORD=threadline -e POSTGRES_DB=threadline -p 5436:5432 pgvector/pgvector:pg16
	docker run -d --name threadline-devredis -p 6382:6379 redis:7-alpine
	sleep 5 && docker exec threadline-devdb psql -U threadline -c "CREATE DATABASE threadline_test"

api:            ## API with reload (events processed in-process)
	cd backend && .venv/bin/alembic upgrade head && .venv/bin/uvicorn app.main:app --reload --port 8000

worker:         ## Celery worker (only needed with EVENTS_EAGER=false)
	cd backend && .venv/bin/celery -A app.workers.celery_app worker -Q events,default --loglevel=INFO --pool=threads --concurrency=4

web:            ## Next.js dev server on :3000 (proxies /api to :8000)
	cd frontend && npm run dev

demo:           ## (re)create the synthetic demo account
	cd backend && .venv/bin/python -m scripts.seed_demo

test: test-backend test-frontend

test-backend:   ## unit + integration tests (needs dev-db)
	cd backend && .venv/bin/pytest -q

test-frontend:
	cd frontend && npm test

e2e:            ## Playwright against a running stack (E2E_BASE_URL, default http://localhost:3000)
	cd frontend && npx playwright test

lint:
	cd backend && .venv/bin/ruff check app evals tests scripts
	cd frontend && npm run lint

typecheck:
	cd backend && .venv/bin/mypy app
	cd frontend && npm run typecheck

eval:           ## evaluation suite (extractive answers; no LLM needed)
	cd backend && .venv/bin/python -m evals.run_all

eval-llm:       ## evaluation incl. local LLM answers and LLM extraction (needs Ollama)
	cd backend && .venv/bin/python -m evals.run_all --llm

perf:           ## performance benchmark at 1k / 10k / 100k memory objects
	cd backend && .venv/bin/python -m evals.perf

models:         ## pull the default local model
	ollama pull qwen3:4b-instruct-2507-q4_K_M

up:             ## full stack in Docker
	docker compose up --build -d

down:
	docker compose down

backup:
	./scripts/backup.sh
