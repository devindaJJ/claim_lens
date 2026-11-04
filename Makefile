COMPOSE := docker compose
RUN := $(COMPOSE) run --rm api

.PHONY: help data up down seed eval eval-claude test lint frontend-dev logs reset

help:            ## Show this help
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

data:            ## Regenerate the synthetic claims, policies and ground truth
	cd backend && python scripts/generate_data.py --out ../data

up:              ## Build and start the full stack (UI on http://localhost:8080)
	$(COMPOSE) up -d --build
	@echo "UI: http://localhost:8080   API docs: http://localhost:8000/docs"

down:            ## Stop the stack
	$(COMPOSE) down

seed:            ## Load the policies into pgvector and queue every sample claim
	$(COMPOSE) exec api python -m app.cli ingest-policies /data/policies
	$(COMPOSE) exec api python -m app.cli seed-claims /data/claims

eval:            ## Evaluate the offline baseline extractor and update the README
	$(RUN) python -m evaluation.run_eval --extractor heuristic --update-readme

eval-claude:     ## Evaluate the Claude extractor (needs ANTHROPIC_API_KEY in .env)
	$(RUN) python -m evaluation.run_eval --extractor claude --update-readme

test:            ## Run the backend test suite (including API tests against Postgres)
	$(RUN) pytest -q

lint:            ## Lint backend and type-check frontend
	$(RUN) ruff check .
	cd frontend && npm run typecheck

frontend-dev:    ## Run the Vite dev server against the API on :8000
	cd frontend && npm run dev

logs:            ## Tail API and worker logs
	$(COMPOSE) logs -f api worker

reset:           ## Stop the stack and delete its data volumes
	$(COMPOSE) down -v
