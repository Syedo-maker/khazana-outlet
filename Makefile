# Khazana Outlet. One entry point for every common task.
# Run `make help` to see the targets.

.DEFAULT_GOAL := help
API := apps/api
WEB := apps/web
PY := $(API)/.venv/Scripts/python

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

.PHONY: setup
setup: ## Create the API virtual environment and install everything
	python -m venv $(API)/.venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e "$(API)[dev]"
	cd $(WEB) && npm install

.PHONY: up
up: ## Start Postgres and Redis for local development
	docker compose up -d

.PHONY: down
down: ## Stop the local services
	docker compose down

.PHONY: migrate
migrate: ## Apply all database migrations
	cd $(API) && .venv/Scripts/alembic upgrade head

.PHONY: migration
migration: ## Create a migration from model changes. Usage: make migration m="add x"
	cd $(API) && .venv/Scripts/alembic revision --autogenerate -m "$(m)"

.PHONY: seed
seed: ## Load the synthetic marketplace: brands, lots, manifests, resellers, orders
	$(PY) -m khazana.seed

.PHONY: api
api: ## Run the API with reload
	cd $(API) && .venv/Scripts/uvicorn khazana.main:app --reload --port 8000

.PHONY: web
web: ## Run the web app
	cd $(WEB) && npm run dev

.PHONY: test
test: ## Run the test suite
	cd $(API) && .venv/Scripts/pytest

.PHONY: cov
cov: ## Run tests with a coverage report
	cd $(API) && .venv/Scripts/pytest --cov=khazana --cov-report=term-missing

.PHONY: lint
lint: ## Lint and type check
	cd $(API) && .venv/Scripts/ruff check . && .venv/Scripts/ruff format --check . && .venv/Scripts/mypy src

.PHONY: fix
fix: ## Auto fix what can be auto fixed
	cd $(API) && .venv/Scripts/ruff check --fix . && .venv/Scripts/ruff format .

.PHONY: evals
evals: ## Run the AI eval suites against recorded fixtures
	$(PY) -m khazana.ai.evals.run --offline

.PHONY: check
check: lint test ## What CI runs

.PHONY: prepush
prepush: ## The repository rules gate: no em dashes, no AI attribution
	@bash scripts/prepush-check.sh
