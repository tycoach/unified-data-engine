# Unified Data Engine

A GCP-native, dbt-powered micro-batch data pipeline engine. Register a pipeline with one YAML file. The engine handles the rest.

```bash
make up
```

---

## What It Does

UDE is a self-contained data processing platform for platform data engineers who need production-grade SCD handling, schema drift detection, and full observability — without the overhead of enterprise-scale tools.

**The core promise:** drop a YAML file in `config/pipelines/`, the engine picks it up automatically. No code changes. No custom MERGE SQL. No schema wrangling.

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

Adding a new pipeline = one YAML file + two dbt SQL files. Zero engine code changes.

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
| API | FastAPI | Control plane — 15+ REST endpoints |
| Dashboard | Streamlit | Operator UI — 5 pages |
| Metrics | Prometheus + Pushgateway | Engine + dbt metrics pipeline |
| Dashboards | Grafana | 2 live dashboards (Engine Overview + dbt Health) |
| Local GCP | MiniSky | Emulates all GCP services locally |
| Infra-as-code | Terraform | Provisions MiniSky + real GCP |

100% open source. No vendor lock-in.

---

## Prerequisites

- WSL2 / Ubuntu 24.04 (or macOS/Linux)
- Docker Desktop with WSL2 backend enabled
- Python 3.12+

---

## Installation

### 1. Install MiniSky (local GCP emulator)

```bash
curl -sSL https://minisky.bmics.com.ng/install.sh | sh
minisky start
```

### 2. Clone and set up

```bash
git clone https://github.com/tycoach/unified-data-engine
cd unified-data-engine

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Start the monitoring stack (Prometheus + Grafana)

```bash
docker compose up -d
```

This starts:
- **Prometheus** on `:9090` — scrapes engine metrics
- **Prometheus Pushgateway** on `:9091` — receives metrics from engine batches
- **Grafana** on `:3000` — visualizes everything (login: `admin` / `admin`)

### 4. Start everything

```bash
make up
```

`make up` runs in this order:

1. Starts MiniSky (local GCP emulator)
2. Provisions Pub/Sub topics + BigQuery datasets on MiniSky
3. Seeds DuckDB with test data (for dbt dev target)
4. Installs dbt packages
5. Starts FastAPI on `:8000`
6. Starts Streamlit dashboard on `:8501`
7. Starts the micro-batch engine loop

---

## Quick Start

```bash
# Publish synthetic test data to Pub/Sub
make seed

# Open the operator dashboard
open http://localhost:8501

# View API docs
open http://localhost:8000/docs

# View live metrics in Grafana
open http://localhost:3000   # admin / admin

# View raw Prometheus metrics
open http://localhost:8000/metrics
```

---

## Registering a New Pipeline

Drop a YAML file in `config/pipelines/`. No code changes.

```yaml
# config/pipelines/products.yml
pipeline_id: products
subscription_id: raw.products-sub
natural_key: product_id
scd_type: 1              # 1 = overwrite, 2 = full history
edge_case_mode: quarantine
null_threshold: 0.02
late_arrival_window: 24h
duplicate_window: 30m

dbt:
  staging_model: products_staged
  mart_model: dim_products
  snapshot: null

fields:
  product_id: { type: string,  nullable: false }
  sku:        { type: string,  nullable: false }
  name:       { type: string,  nullable: true }
  price:      { type: float,   nullable: false }
  updated_at: { type: datetime, nullable: false }
```

Then add:
- `dbt/models/staging/products_staged.sql`
- `dbt/models/marts/dim_products.sql`
- Add `products_staged` to `dbt/models/staging/_sources.yml`

For SCD Type 2, also add `dbt/snapshots/products_snapshot.sql`.

---

## Schema Deviation Handling

| Outcome | What happened | Engine action |
|---|---|---|
| **MATCH** | Schema identical | Fast path — continue |
| **EVOLVED** | New column added, type widened | Update registry, regenerate dbt contract, continue |
| **BROKEN** | Column removed, type incompatible | Quarantine batch, alert operator, hold schema |

Approving a BROKEN migration:

```bash
POST /schema/{pipeline_id}/approve-migration
{
  "reason": "Upstream removed column intentionally",
  "updated_fields": { ... }
}
```

Or use the Quarantine page in the Streamlit dashboard.

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

## Grafana Dashboards

Two pre-built dashboards at `http://localhost:3000`:

### Dashboard 1 — Engine Overview
- **Batch Throughput** — records/batch per pipeline over time
- **End-to-End Batch Duration (p95)** — batch processing time trends
- **Quarantine Rate** — per pipeline, alerts if > 10%
- **Active Pipelines** — count of running pipelines
- **Schema Version** — current locked version per pipeline
- **Staging Rows Written** — rows written to BigQuery per batch

### Dashboard 2 — dbt Health
- **dbt Run Duration (p95)** — snapshot vs mart run times
- **dbt Test Failures** — failures block checkpoint — zero = healthy
- **Snapshot Records Opened vs Closed** — SCD Type 2 change tracking
- **dbt Run Status** — 1=success, 0=failure per pipeline
- **Contract Violations** — edge case gate gap detection

---

## Monitoring & Alerting

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

## Make Commands

```bash
make up            # Start everything
make down          # Stop all services
make engine        # Run engine only
make api           # Start FastAPI only
make ui            # Start Streamlit only
make seed          # Publish synthetic data
make provision     # Reprovision MiniSky after restart
make dbt-run       # Run all dbt models
make dbt-test      # Run dbt tests
make dbt-docs      # Generate + serve dbt docs
make schema-sync   # Regenerate dbt contracts from registry
make test          # Run all unit + integration tests
make reset         # Wipe all state, fresh start
make help          # Show all commands
```

---

## Project Structure

```
unified-data-engine/
├── config/
│   ├── engine.yml              Global engine settings
│   ├── loader.py               Config-driven pipeline loader
│   └── pipelines/              One YAML per pipeline
│       ├── customers.yml
│       ├── orders.yml
│       └── products.yml
├── engine/
│   ├── main.py                 Micro-batch loop
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
├── api/                        FastAPI — 5 routers, 15+ endpoints
├── ui/                         Streamlit — 5 operator pages
├── monitoring/
│   ├── prometheus/             prometheus.yml + alerts.yml (7 rules)
│   └── grafana/
│       ├── dashboards/         engine_overview.json + dbt_health.json
│       └── provisioning/       Auto-loaded datasources + dashboards
├── data-generator/
│   └── scenarios/              happy_path.py, products.py
├── scripts/                    Phase test scripts
├── terraform/                  Infra-as-code for MiniSky + GCP
├── docker-compose.yml          Monitoring stack (Prometheus + Grafana)
├── Makefile
├── requirements.txt
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

| Problem | UDE  solution |
|---|---|
| Writing SCD MERGE SQL for every dataset | dbt snapshots + incremental — zero custom SQL |
| Schema changes breaking pipelines silently | MATCH / EVOLVED / BROKEN on every batch |
| Nulls, duplicates, late arrivals handled inconsistently | Edge case gate — configurable per pipeline |
| New pipeline takes days to set up | One YAML file — engine handles the rest |
| No visibility into what's happening | FastAPI + Streamlit + Prometheus + Grafana |
| Vendor lock-in to expensive platforms | 100% open source, GCP-native, MiniSky for local dev |

---

## License

MIT — use it, fork it, build on it.

---

Built by [Taiwo Hassan](https://github.com/tycoach) · Powered by [MiniSky](https://github.com/qamarudeenm/minisky)