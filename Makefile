PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: venv install test lint run smoke up down

venv:
	$(PY) -m venv $(VENV)

install: venv
	$(BIN)/pip install -e ".[dev]"

test:
	$(BIN)/pytest -q

lint:
	$(BIN)/ruff check app tests

run:
	$(BIN)/uvicorn app.main:app --reload --port 8000

smoke:
	$(BIN)/python scripts/smoke.py

eval:
	$(BIN)/python scripts/eval.py

demo:
	$(BIN)/python scripts/demo.py

migrate:
	$(BIN)/alembic upgrade head

migrate-gen:
	$(BIN)/alembic revision --autogenerate -m "auto"

chaos:
	$(BIN)/python scripts/chaos.py

smoke-auth:
	$(BIN)/python scripts/smoke_auth.py

smoke-pgvector:
	$(BIN)/python scripts/smoke_pgvector.py

bench-hnsw:
	$(BIN)/python scripts/bench_hnsw.py

ci: lint test chaos smoke-auth

up:
	docker compose up -d

down:
	docker compose down
