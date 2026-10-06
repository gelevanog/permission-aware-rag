.DEFAULT_GOAL := help
.PHONY: help install db db-stop migrate seed serve web test lint format web-install web-lint web-build eval eval-offline eval-real free-models docker-up docker-up-ollama docker-build clean

DB_URL ?= postgresql+psycopg://clearance:clearance@127.0.0.1:55432/clearance
export CLEARANCE_DATABASE_URL ?= $(DB_URL)
export TEST_DATABASE_URL ?= postgresql+psycopg://clearance:clearance@127.0.0.1:55432/clearance_test

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-17s\033[0m %s\n", $$1, $$2}'

install:  ## Python dependencies (uv) and the web app's (npm)
	uv sync
	cd web && npm ci --no-audit --no-fund

db:  ## Local PostgreSQL + pgvector on port 55432 (with a test database)
	docker run -d --name clearance-db -e POSTGRES_USER=clearance -e POSTGRES_PASSWORD=clearance -e POSTGRES_DB=clearance \
		-p 127.0.0.1:55432:5432 pgvector/pgvector:pg17
	@until docker exec clearance-db pg_isready -U clearance >/dev/null 2>&1; do sleep 1; done
	docker exec clearance-db psql -U clearance -c "CREATE DATABASE clearance_test" || true

db-stop:  ## Remove the local database container
	docker rm -f clearance-db

migrate:  ## Schema, indexes, reader role and row-level security policies
	uv run clearance migrate

seed:  ## Index the demo company corpus (data/company) with local embeddings
	uv run clearance ingest data/company

serve:  ## API + dev IdP on http://localhost:8000 (seeds the demo corpus on first start)
	uv run clearance serve --port 8000

web:  ## Next.js dev server on http://localhost:3000
	cd web && npm run dev

test:  ## Python tests (no API keys, no model downloads; DB tests need TEST_DATABASE_URL)
	uv run pytest

lint:  ## Ruff lint + format check + mypy (strict)
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy

format:  ## Auto-format and fix lint issues
	uv run ruff format src tests
	uv run ruff check --fix src tests

web-lint:  ## ESLint + TypeScript type check
	cd web && npm run lint && npm run typecheck

web-build:  ## Production build of the web app
	cd web && npm run build

eval-offline:  ## Leak test (retrieval only), recall study, ACL-change and latency runs: no LLM calls
	uv run clearance eval leak
	uv run clearance eval acl-change
	uv run clearance eval latency

eval:  ## Leak test with answers from the local model (Ollama) for Clearance and the baselines
	uv run clearance eval leak --generate clearance,unfiltered --provider ollama

eval-real:  ## Quality: local vs free cloud model, judged by a free cloud model (needs OPENROUTER_API_KEY)
	uv run clearance eval quality
	uv run clearance eval latency
	uv run clearance eval ledger

free-models:  ## List free OpenRouter models and smoke-test three of them (3 calls)
	uv run clearance eval models --smoke 3

docker-build:  ## Build the API and web images
	docker compose build

docker-up:  ## Everything in Docker (web :3000, API :8000); uses an Ollama on the host if CLEARANCE_LLM_BASE_URL points to it
	docker compose up --build

docker-up-ollama:  ## Everything in Docker including Ollama and the local model (pulled on first start)
	docker compose --profile ollama up --build

clean:  ## Remove caches (keeps results/ and the downloaded models)
	rm -rf .pytest_cache .mypy_cache .ruff_cache .hypothesis web/.next
