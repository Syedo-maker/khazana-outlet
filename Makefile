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

# Smart App Control blocks unsigned executables on this machine, so ruff and
# mypy cannot run directly. These targets run the same tools inside Linux
# containers, where Windows app control does not apply. Same ruff version as
# CI, so the results match exactly.
RUFF_IMAGE := ghcr.io/astral-sh/ruff:0.16.10

.PHONY: lint-docker
lint-docker: ## Lint and format check inside Docker, when ruff is blocked locally
	docker run --rm -v "$(CURDIR)/apps/api":/io -w /io $(RUFF_IMAGE) check .
	docker run --rm -v "$(CURDIR)/apps/api":/io -w /io $(RUFF_IMAGE) format --check .

.PHONY: fix-docker
fix-docker: ## Auto fix lint and formatting inside Docker
	docker run --rm -v "$(CURDIR)/apps/api":/io -w /io $(RUFF_IMAGE) check --fix .
	docker run --rm -v "$(CURDIR)/apps/api":/io -w /io $(RUFF_IMAGE) format .

.PHONY: types-docker
types-docker: ## Type check inside Docker. Slower, it installs dependencies first
	docker run --rm -v "$(CURDIR)/apps/api":/io -w /io python:3.11-slim bash -c "pip install -q -e '.[dev]' && mypy src"

.PHONY: check
check: lint test ## What CI runs

.PHONY: prepush
prepush: ## The repository rules gate: no em dashes, no AI attribution
	@bash scripts/prepush-check.sh
