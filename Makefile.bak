# Makefile — Unified Data Engine v2
# Usage: make help

.PHONY: all up down engine api ui seed provision dbt-run dbt-test dbt-docs \
        schema-sync test reset logs install help

PYTHON   := .venv/bin/python
PIP      := .venv/bin/pip
DBT      := .venv/bin/dbt
UVICORN  := .venv/bin/uvicorn
STREAMLIT := .venv/bin/streamlit

# ── Startup ───────────────────────────────────────────────────────────────────

up: ## Start everything — MiniSky + provision + API + UI + engine
	@echo "🚀 Starting Unified Data Engine v2..."
	@echo ""
	@echo "── [1/6] Starting MiniSky (local GCP emulator)..."
	@minisky start &
	@sleep 4
	@echo "── [2/6] Provisioning GCP resources on MiniSky..."
	@$(MAKE) provision
	@echo "── [3/6] Seeding DuckDB for dbt dev target..."
	@$(PYTHON) dbt/seed_duckdb.py
	@echo "── [4/6] Installing dbt packages..."
	@cd dbt && $(DBT) deps --quiet
	@echo "── [5/6] Starting FastAPI control plane on :8000..."
	@$(UVICORN) api.main:app --host 0.0.0.0 --port 8000 --log-level warning &
	@sleep 2
	@echo "── [6/6] Starting Streamlit dashboard on :8501..."
	@PYTHONPATH=. $(STREAMLIT) run ui/app.py --server.port 8501 \
		--server.address 0.0.0.0 --server.headless true &
	@sleep 2
	@echo ""
	@echo "✅ UDE v2 is running:"
	@echo "   Engine:    python engine/main.py"
	@echo "   API:       http://localhost:8000/docs"
	@echo "   Dashboard: http://localhost:8501"
	@echo "   Metrics:   http://localhost:8000/metrics"
	@echo ""
	@echo "── Starting engine (Ctrl+C to stop)..."
	@$(PYTHON) engine/main.py

down: ## Stop all services
	@echo "🛑 Stopping UDE ..."
	@pkill -f "minisky start"    2>/dev/null || true
	@pkill -f "uvicorn api.main" 2>/dev/null || true
	@pkill -f "streamlit run"    2>/dev/null || true
	@pkill -f "engine/main.py"   2>/dev/null || true
	@echo "✅ All services stopped"

# ── Individual services ───────────────────────────────────────────────────────

engine: ## Run the micro-batch engine only
	@echo "⚙️  Starting engine..."
	@$(PYTHON) engine/main.py

api: ## Start FastAPI control plane only
	@echo "🌐 Starting API on :8000..."
	@$(UVICORN) api.main:app --host 0.0.0.0 --port 8000 --reload

ui: ## Start Streamlit dashboard only
	@echo "📊 Starting dashboard on :8501..."
	@PYTHONPATH=. $(STREAMLIT) run ui/app.py \
		--server.port 8501 --server.address 0.0.0.0

# ── MiniSky provisioning (runs on every make up) ──────────────────────────────

provision: ## Provision all GCP resources on MiniSky
	@echo "📦 Provisioning MiniSky resources..."
	@curl -sf -X POST http://localhost:8080/bigquery/v2/projects/local-dev-project/datasets \
		-H "Content-Type: application/json" \
		-d '{"datasetReference":{"datasetId":"raw_staging","projectId":"local-dev-project"}}' \
		>/dev/null 2>&1 || true
	@curl -sf -X POST http://localhost:8080/bigquery/v2/projects/local-dev-project/datasets \
		-H "Content-Type: application/json" \
		-d '{"datasetReference":{"datasetId":"snapshots","projectId":"local-dev-project"}}' \
		>/dev/null 2>&1 || true
	@curl -sf -X POST http://localhost:8080/bigquery/v2/projects/local-dev-project/datasets \
		-H "Content-Type: application/json" \
		-d '{"datasetReference":{"datasetId":"marts","projectId":"local-dev-project"}}' \
		>/dev/null 2>&1 || true
	@curl -sf -X POST http://localhost:8080/bigquery/v2/projects/local-dev-project/datasets \
		-H "Content-Type: application/json" \
		-d '{"datasetReference":{"datasetId":"quarantine","projectId":"local-dev-project"}}' \
		>/dev/null 2>&1 || true
	@curl -sf -X PUT http://localhost:8080/v1/projects/local-dev-project/topics/raw.customers \
		-H "Content-Type: application/json" -d '{}' >/dev/null 2>&1 || true
	@curl -sf -X PUT http://localhost:8080/v1/projects/local-dev-project/topics/raw.orders \
		-H "Content-Type: application/json" -d '{}' >/dev/null 2>&1 || true
	@curl -sf -X PUT \
		http://localhost:8080/v1/projects/local-dev-project/subscriptions/raw.customers-sub \
		-H "Content-Type: application/json" \
		-d '{"topic":"projects/local-dev-project/topics/raw.customers","ackDeadlineSeconds":60}' \
		>/dev/null 2>&1 || true
	@curl -sf -X PUT \
		http://localhost:8080/v1/projects/local-dev-project/subscriptions/raw.orders-sub \
		-H "Content-Type: application/json" \
		-d '{"topic":"projects/local-dev-project/topics/raw.orders","ackDeadlineSeconds":60}' \
		>/dev/null 2>&1 || true
	@echo "✅ MiniSky resources provisioned"

# ── Data ──────────────────────────────────────────────────────────────────────

seed: ## Publish synthetic data to Pub/Sub
	@echo "🌱 Seeding Pub/Sub..."
	@$(PYTHON) data-generator/scenarios/happy_path.py

# ── dbt ───────────────────────────────────────────────────────────────────────

dbt-run: ## Run all dbt models
	@cd dbt && $(DBT) run --target dev

dbt-test: ## Run dbt tests
	@cd dbt && $(DBT) test --target dev

dbt-docs: ## Generate + serve dbt docs on :8080
	@cd dbt && $(DBT) docs generate --target dev
	@cd dbt && $(DBT) docs serve --port 8080

dbt-deps: ## Install dbt packages
	@cd dbt && $(DBT) deps

dbt-compile: ## Compile + validate SQL
	@cd dbt && $(DBT) compile --target dev

dbt-seed-db: ## Seed DuckDB with test data
	@$(PYTHON) dbt/seed_duckdb.py

# ── Schema ────────────────────────────────────────────────────────────────────

schema-sync: ## Regenerate dbt _sources.yml from schema registry
	@echo "🔄 Syncing schema → dbt contracts..."
	@$(PYTHON) -c "\
from config.loader import load_pipelines; \
from engine.schema.registry import SchemaRegistry; \
from engine.schema.contract_writer import write_contract; \
registry = SchemaRegistry(); \
schemas = registry.all_schemas(); \
[write_contract(s) for s in schemas]; \
print(f'✅ Synced {len(schemas)} schema(s)')"

# ── Testing ───────────────────────────────────────────────────────────────────

test: ## Run all tests
	@echo "🧪 Running all tests..."
	@$(PYTHON) scripts/test_schema.py
	@$(PYTHON) scripts/test_staging.py
	@$(PYTHON) scripts/test_state.py
	@$(PYTHON) scripts/test_dbt.py
	@echo "✅ All tests passed"

# ── Maintenance ───────────────────────────────────────────────────────────────

reset: ## Wipe all local state — fresh start
	@echo "⚠️  Resetting state..."
	@rm -rf .schema_registry/ .state/ dbt/target/
	@echo "✅ State cleared — run 'make up' to restart"

install: ## Install Python dependencies
	@$(PIP) install -r requirements.txt -q

logs: ## Tail engine logs
	@tail -f /tmp/ude_engine.log 2>/dev/null || echo "Run engine first"

# ── Help ──────────────────────────────────────────────────────────────────────

help: ## Show available commands
	@echo ""
	@echo "  Unified Data Engine  — commands"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""

.DEFAULT_GOAL := help