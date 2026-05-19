# Unified Data Engine

A GCP-native, dbt-powered micro-batch data pipeline engine with a full operator CLI.

```bash
pip install unified-data-engine
ude init
ude up
```

---

## What It Does

UDE is a self-contained data processing platform for platform data engineers who need production-grade SCD handling, schema drift detection, and full observability — without the overhead of enterprise-scale tools.

**The core promise:** register a pipeline via `ude pipeline new`, publish data to Pub/Sub, and the engine handles everything else — schema inference, edge case gating, dbt transformations, checkpointing, and metrics.

### What happens on every 30-second batch cycle:

```
Cloud Pub/Sub (MiniSky)
        ↓
   Pull messages (30s window)
        ↓
   Schema check → MATCH / EVOLVED / BROKEN
        ↓
   Edge case gate → null check, dedup, type validation, late arrival
        ↓
   Write clean records → BigQuery raw_staging
        ↓
   dbt run → snapshot (SCD Type 2) → mart (SCD Type 1) → tests
        ↓
   Checkpoint + Pub/Sub ack  ← only after all tests pass
        ↓
   Push metrics → Prometheus → Grafana
```

Failed batches are nacked and reprocessed automatically on the next cycle.

---

## Pipelines Proven End to End

| Pipeline | SCD Type | Natural Key | Records/batch |
|---|---|---|---|
| customers | Type 2 (full history via snapshot) | customer_id | 20 |
| orders | Type 1 (overwrite) | order_id | 200 |
| products | Type 1 (overwrite) | product_id | 30 |

Adding a new pipeline = `ude pipeline new`. Zero engine code changes.

---

## Stack

| Component | Technology | Role |
|---|---|---|
| Message bus | Cloud Pub/Sub | Ingestion, micro-batch rhythm |
| Transformation | dbt Core | SCD via snapshots + incremental |
| Dev adapter | dbt-duckdb | Zero-config local development |
| Prod adapter | dbt-bigquery | Production GCP target |
| Batch processing | Polars | Schema inference, edge case validation |
| Hot state | Bigtable (local: JSON files) | Schema versions, offsets, checkpoints |
| Target store | BigQuery | Staging, snapshots, marts, quarantine |
| API | FastAPI | Control plane — 20+ REST endpoints |
| CLI | Typer + Rich | `ude` — operator CLI, pip-installable |
| Dashboard | Streamlit | Operator UI — 5 pages |
| Metrics | Prometheus + Pushgateway | Engine + dbt metrics pipeline |
| Dashboards | Grafana | 2 live dashboards |
| Local GCP | MiniSky | Emulates all GCP services locally |
| Infra-as-code | Terraform | Provisions MiniSky + real GCP |

100% open source. No vendor lock-in.

---

## Prerequisites

- WSL2 / Ubuntu 24.04 (or macOS/Linux)
- Docker Desktop with WSL2 backend enabled
- Python 3.12+
- MiniSky (local GCP emulator)

---

## Installation

### Option A — pipx (recommended for CLI-only use)

```bash
pipx install unified-data-engine
ude --version
```

### Option B — pip in a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install unified-data-engine
```

### Option C — uv

```bash
uv tool install unified-data-engine
```

> **Note:** On modern Debian/Ubuntu, `pip install` outside a venv fails with an
> "externally-managed-environment" error. Use pipx, uv, or a venv.

---

## Engine Setup (contributors + self-hosted)

```bash
# 1. Install MiniSky
curl -sSL https://minisky.bmics.com.ng/install.sh | sh

# 2. Clone and install
git clone https://github.com/tycoach/unified-data-engine
cd unified-data-engine
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 3. Initialise your project
ude init

# 4. Start everything — one command
ude up
```

`ude up` handles the full startup sequence automatically:

```
  [1/6] MiniSky          ✓ ready at :8080
  [2/6] Provisioning     ✓ 6 topics · 6 subscriptions · 4 datasets
  [3/6] dbt packages     ✓ already installed — skipping
  [4/6] FastAPI          ✓ ready at :8000
  [5/6] Streamlit UI     ✓ ready at :8501
  [6/6] Monitoring       ✓ Grafana at :3000
  
  ✓ UDE stack is up.
```

No `make`. No separate provision script. No separate `docker compose up`.

---

## Verify

```bash
ude status
```

![ude status](assets/udee.png)

---

## The CLI — `ude`

The `ude` CLI ships with `pip install unified-data-engine`.

![ude help](assets/ude-help.png)

### Lifecycle

```bash
ude up                        # Start the full stack — one command
ude down                      # Stop all components
ude status                    # Health of all 6 components
ude seed                      # Publish synthetic test data to Pub/Sub
ude init                      # Scaffold a new project + generate project token
ude --version                 # Show installed version
```

### Pipeline management

```bash
ude pipeline list             # All pipelines — status, schema version, last batch
ude pipeline inspect <id>     # Full config, schema fields, last batch detail
ude pipeline new              # Interactive scaffold + register with engine
ude pipeline register <id>    # Register an existing local YAML with the engine
ude pipeline delete  <id>     # Deregister a pipeline
ude pipeline enable  <id>     # Resume a paused pipeline
ude pipeline disable <id>     # Pause without deleting
```

![ude pipeline inspect](assets/ude_inspect_customer.png)

### Schema operations

```bash
ude schema show    <id>       # Inspect locked schema — fields, types, constraints
ude schema history <id>       # Version timeline — INITIAL → EVOLVED → BROKEN
ude schema diff    <id>       # Locked schema vs what's arriving live
ude schema sync               # Regenerate dbt contracts from registry
ude schema approve <id>       # Approve a BROKEN migration, unblock pipeline
```

![ude schema history](assets/ude_schema_history.png)

### Quarantine management

```bash
ude quarantine list                   # All quarantined batches
ude quarantine inspect <batch_id>     # Full detail + schema diff + records
ude quarantine approve <batch_id>     # Release for replay
ude quarantine reject  <batch_id>     # Discard permanently
ude quarantine replay  <batch_id>     # Force immediate replay
```

### dbt commands

```bash
ude dbt run                   # Run all dbt models (auto-injects --profiles-dir, --vars)
ude dbt test                  # Run dbt tests
ude dbt snapshot              # Run dbt snapshots (SCD Type 2)
ude dbt docs                  # Generate + serve dbt docs
ude dbt lineage               # Render model dependency DAG in terminal
```

![ude dbt help](assets/ude_dbt_help.png)

### Observability

```bash
ude observe start             # Start Prometheus + Pushgateway + Grafana (Docker)
ude observe stop              # Stop the monitoring stack
ude observe watch             # Live batch feed — records, dbt, schema, quarantine rate
ude observe logs              # Stream engine logs (filter by pipeline, level)
ude observe metrics           # Prometheus metrics snapshot as a Rich table
```

![ude observe watch — live batch cycles](assets/ude_watch_live.png)

![ude observe metrics](assets/ude_metrics_observe.png)

---

## Project Tokens — Multi-Tenant Isolation

`ude init` generates a project token saved to `~/.ude/config.yml`. Every CLI command sends this token as `X-UDE-Project` on every API call.

```
ude init
→ Project token: proj_acme-analytics-a3f9b2
  Saved to: ~/.ude/config.yml
```

**What this means:**
- `ude pipeline list` only shows pipelines you registered — never the engine owner's internal pipelines
- Engine-internal filesystem pipelines (`customers`, `orders`, `products`) are never exposed to external callers
- Two users with different tokens are fully isolated from each other
- Share your token with teammates who need access to the same project

```yaml
# ~/.ude/config.yml
host: <engine-host>
port: 8000
env: local
minisky_url: http://localhost:8080
project_token: proj_acme-analytics-a3f9b2
project_name: acme-analytics
```

Override via env var:
```bash
export UDE_PROJECT_TOKEN=proj_acme-analytics-a3f9b2
ude pipeline list
```

---

## Fresh Install — 3rd Party User

```bash
# 1. Install
pipx install unified-data-engine

# 2. Initialise project (generates your token)
ude init

# 3. Configure engine host
# Edit ~/.ude/config.yml:
#   host: <engine-host>
#   port: 8000

# 4. Start monitoring
ude observe start

# 5. Register your first pipeline
ude pipeline new

# 6. Confirm it's registered
ude pipeline list

# 7. Watch it process
ude observe watch
```

---

## Registering a New Pipeline

### Option A — Interactive CLI (recommended)

```bash
ude pipeline new
```

Scaffolds locally and registers with the engine in one shot:
- `config/pipelines/{id}.yml`
- `dbt/models/staging/{id}_staged.sql`
- `dbt/models/marts/dim_{id}.sql`
- `dbt/snapshots/{id}_snapshot.sql` (SCD Type 2 only)

Engine picks it up on the next cycle — no restart needed.

### Option B — Manual YAML + register

```yaml
# config/pipelines/events.yml
pipeline_id: events
subscription_id: raw.events-sub
natural_key: event_id
scd_type: 1
edge_case_mode: quarantine
null_threshold: 0.02
late_arrival_window: 24h
duplicate_window: 30m

fields:
  event_id:   { type: string,   nullable: false }
  user_id:    { type: string,   nullable: false }
  event_type: { type: string,   nullable: false }
  payload:    { type: string,   nullable: true }
  created_at: { type: datetime, nullable: false }
```

```bash
ude pipeline register events   # register with running engine
```

---

## Schema Operations

```bash
# Inspect the locked schema for a pipeline
ude schema show git_repos
```

```
╭──────────────── git_repos · locked schema ─────────────────╮
│  Pipeline    git_repos                                      │
│  Version     v1                                             │
│  Locked at   2026-05-15T23:02:17+00:00                      │
│  Fields      5                                              │
╰─────────────────────────────────────────────────────────────╯
╭──────────────── git_repos · fields ────────────────────────╮
│  Field        Type       Nullable                           │
│  repo_id      string     no                                 │
│  name         string     no                                 │
│  stars        integer    yes                                │
│  language     string     yes                                │
│  updated_at   datetime   no                                 │
╰─────────────────────────────────────────────────────────────╯
```

### Schema Deviation Handling

| Outcome | What happened | Engine action |
|---|---|---|
| **MATCH** | Schema identical | Fast path — continue |
| **EVOLVED** | New column added, type widened | Update registry, regenerate dbt contract, continue |
| **BROKEN** | Column removed, type incompatible | Quarantine batch, alert operator, hold schema |

```bash
ude schema diff    customers   # Preview what changed
ude schema approve customers   # Approve + unblock pipeline
```

---

## Operator Dashboard

Five pages at `http://localhost:8501`:

| Page | What it shows |
|---|---|
| **Overview** | Engine health, MiniSky status, pipeline summary |
| **Pipeline Health** | Checkpoint history, batch stats, schema fields |
| **Quarantine** | Dirty records with failure reasons, migration approval |
| **Schema History** | Locked schemas, version timeline, dbt source contracts |
| **dbt Lineage** | Model dependency DAG from manifest.json |

---

## API — Control Plane

```

![ude controlpanel](assets/ude-cp.png)

---

FastAPI at `http://localhost:8000/docs` — 20+ endpoints across 6 routers.

| Router | Key endpoints |
|---|---|
| `/health` | Stack health, MiniSky connectivity |
| `/pipeline` | List, inspect, register, enable/disable, batch history |
| `/schema` | Show, history, diff, sync, approve migration |
| `/quarantine` | List batches, inspect, approve, reject, replay |
| `/dbt` | Trigger runs, status, lineage, artifacts |
| `/metrics/structured` | JSON metrics scraped from Pushgateway |
| `/logs/stream` | NDJSON log stream for `ude observe logs` |

All endpoints are scoped to `X-UDE-Project` header — external callers only see their own pipelines.

---

## Monitoring & Alerting

```bash
ude observe start   # starts Prometheus + Pushgateway + Grafana via Docker
```

Prometheus scrapes `http://localhost:8000/metrics` + Pushgateway at `:9091`.

### Key metrics

| Metric | What it tracks |
|---|---|
| `ude_batch_records_total` | Records pulled per batch |
| `ude_quarantine_rate` | Quarantine rate (0.0–1.0) |
| `ude_schema_deviation_total` | MATCH / EVOLVED / BROKEN counts |
| `ude_dbt_run_duration_seconds` | dbt run time histogram |
| `ude_dbt_test_failures_total` | Test failures — each blocks checkpoint |
| `ude_snapshot_records_opened_total` | SCD Type 2 changes per batch |
| `ude_dbt_run_status` | Last dbt run: 1=success, 0=failure |
| `ude_checkpoints_total` | Successful vs failed checkpoints |

### Alert rules (7 total)

| Alert | Condition | Severity |
|---|---|---|
| HighQuarantineRate | quarantine_rate > 10% | Critical |
| DbtTestFailure | any not_null or unique failure | Critical |
| SchemaDeviationDetected | BROKEN deviation | Critical |
| SnapshotMismatch | opened != closed | Critical |
| SlowBatchProcessing | p95 > 60s | Warning |
| DbtRunExceedsWindow | p95 > 25s | Warning |
| ZeroRowsProcessed | 0 rows for 3 batches | Warning |

---

## MiniSky — Important Notes

MiniSky loses all Pub/Sub and BigQuery state on restart. Simply run:

```bash
ude up
```

`ude up` automatically detects MiniSky is running and re-provisions all topics and subscriptions for every registered pipeline — filesystem and API-registered — before starting any other service. No manual `make provision` needed.

---

## Project Structure

```
unified-data-engine/
├── config/
│   ├── engine.yml              Global engine settings
│   ├── loader.py               Pipeline loader — filesystem + Bigtable
│   └── pipelines/              One YAML per pipeline (engine-internal)
├── engine/
│   ├── main.py                 Micro-batch loop (hot-reloads pipelines per cycle)
│   ├── ingestion/              Pub/Sub consumer + offset manager
│   ├── schema/                 Inference, registry, deviation, contract writer
│   ├── staging/                Edge case gate + BigQuery staging writer
│   ├── dbt_runner/             dbt orchestration + results parser
│   ├── state/                  Bigtable client + checkpoint manager
│   └── metrics/                Prometheus metric emitters
├── dbt/
│   ├── models/staging/         One view per dataset
│   ├── models/marts/           SCD Type 1 incremental models
│   └── snapshots/              SCD Type 2 snapshot declarations
├── api/                        FastAPI — 20+ endpoints, 6 routers
├── cli/                        ude CLI — Typer + Rich, pip-installable
│   ├── commands/               lifecycle, dbt, pipeline, schema, quarantine, observe
│   ├── client/                 HTTP client wrapping FastAPI endpoints
│   ├── scaffold/               ude init + ude pipeline new generators
│   ├── output/                 Rich tables, panels, live watch display
│   └── core/                   Config, errors, checks, context
├── ui/                         Streamlit — 5 operator pages
├── monitoring/
│   ├── prometheus/             prometheus.yml + alerts.yml (7 rules)
│   └── grafana/dashboards/     engine_overview.json + dbt_health.json
├── data-generator/scenarios/   happy_path.py, products.py
├── tests/
│   ├── unit/cli/               92 passing unit tests
│   └── integration/cli/        Integration test stubs
├── assets/                     CLI screenshots
├── pyproject.toml              Package manifest — pip install unified-data-engine
├── Makefile                    Engine dev commands
└── .env.example
```

---

## Deploying to Real GCP

No engine code changes needed:

1. Set `GOOGLE_APPLICATION_CREDENTIALS` to your service account key
2. Update `config/engine.yml` → `environment: production`
3. Update `dbt/profiles.yml` → `target: prod`
4. Run `terraform apply` in `terraform/`

---

## Why UDE?

| Problem | UDE solution |
|---|---|
| Writing SCD MERGE SQL for every dataset | dbt snapshots + incremental — zero custom SQL |
| Schema changes breaking pipelines silently | MATCH / EVOLVED / BROKEN on every batch |
| Nulls, duplicates, late arrivals handled inconsistently | Edge case gate — configurable per pipeline |
| New pipeline takes days to set up | `ude pipeline new` — scaffold + register in 2 minutes |
| No visibility into what's happening | CLI + FastAPI + Streamlit + Prometheus + Grafana |
| Operator commands require SSH + curl | `ude quarantine approve`, `ude schema diff` from anywhere |
| 3rd party users can see internal pipelines | Project token scoping — full multi-tenant isolation |
| Startup requires 6 separate commands | `ude up` — one command, all 6 components |
| Vendor lock-in to expensive platforms | 100% open source, GCP-native, MiniSky for local dev |

---

## Releases

| Version | PyPI | What shipped |
|---|---|---|
| `2.6.0` | ✓ latest | `ude up` one-command startup, auto-provision, monitoring included |
| `1.6.0` | — | `ude up` full stack — no make required |
| `1.5.0` | — | Engine hot-reload + `ude observe start/stop` |
| `1.4.0` | — | Project token scoping — multi-tenant pipeline isolation |
| `1.2.0` | — | `POST /pipeline/` — register pipelines without filesystem access |
| `1.1.0` | — | FastAPI endpoints wired — full CLI to API round trip |
| `1.0.0-cli` | — | `ude` CLI complete — 92/92 unit tests, all 6 command groups |
| `2.0.0` | ✓ | Initial PyPI release — baseline engine + CLI |

---

## License

MIT — use it, fork it, build on it.

---

Built by [Taiwo Hassan](https://github.com/tycoach) · Powered by [MiniSky](https://github.com/qamarudeenm/minisky)