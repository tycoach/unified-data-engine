# Unified Data Engine — Future Roadmap & Extension Guide

**Document version:** 1.0  
**Engine version:** 3.1.0  
**Date:** May 2026  
**Author:** Taiwo Hassan

---

## Purpose

This document captures planned features, architectural extensions, and design decisions deferred from the current release. It exists so that future contributors — and future versions of this project — have a clear record of what was considered, why certain things were deferred, and how they should be built when the time comes.

---

## Current State (v3.1.0 baseline)

Before the roadmap, a clear picture of what exists today:

### What's shipped

```
Core engine
  ✓ 30-second micro-batch loop with hot-reload
  ✓ Cloud Pub/Sub ingestion + direct HTTP ingest
  ✓ Schema inference, registry, MATCH/EVOLVED/BROKEN detection
  ✓ dbt transformation layer — SCD Type 1 + Type 2
  ✓ Edge case gate — null, dedup, type validation, late arrival
  ✓ BigQuery staging + quarantine
  ✓ Bigtable checkpointing + offset management
  ✓ Prometheus metrics + Grafana dashboards (auto-provisioned)

API + CLI
  ✓ FastAPI control plane — 7 routers, 25+ endpoints
  ✓ ude CLI — pip-installable, 8 command groups
  ✓ Self-service API key auth — Bearer tokens, 90-day TTL
  ✓ Multi-tenant project isolation via X-UDE-Project
  ✓ Rate limiting, audit logging, key expiry, HTTPS
  ✓ Email expiry notifications (Gmail SMTP)
  ✓ Suspicious activity webhook (Slack/Discord/HTTP)
  ✓ Grafana dashboards bundled in pip wheel

Operator experience
  ✓ ude up — one command full stack
  ✓ ude auth audit --watch — live audit stream
  ✓ ude schema show/diff/approve
  ✓ ude quarantine list/inspect/approve/reject
  ✓ Streamlit operator dashboard — 5 pages
```

### What's explicitly deferred

The following were discussed and deliberately not built yet, with reasoning documented below.

---

## Section 1 — Multi-Cloud Provider Abstraction

### The problem

UDE is currently GCP-native. Every service call is hardcoded to GCP APIs:
- Pub/Sub for message ingestion
- Bigtable for hot state
- BigQuery for staging and marts
- Cloud SQL for metadata

A user on AWS, Azure, or a private server cannot adopt UDE without rewriting the engine.

### The solution: Provider abstraction layer

Define abstract interfaces. Swap implementations via config.

```
engine/providers/
  __init__.py         — provider factory (reads config, returns correct impl)
  base.py             — abstract base classes
  gcp/
    message_bus.py    — Cloud Pub/Sub
    state_store.py    — Bigtable
    data_warehouse.py — BigQuery
  aws/
    message_bus.py    — SQS / Kinesis
    state_store.py    — DynamoDB
    data_warehouse.py — Redshift / Athena
  azure/
    message_bus.py    — Service Bus / Event Hubs
    state_store.py    — Cosmos DB
    data_warehouse.py — Synapse Analytics
  self_hosted/
    message_bus.py    — Kafka
    state_store.py    — RocksDB / PostgreSQL
    data_warehouse.py — DuckDB / PostgreSQL
```

### Abstract interfaces to define

```python
# engine/providers/base.py

class MessageBus(ABC):
    def publish(self, topic: str, records: list[dict]) -> list[str]: ...
    def pull(self, subscription: str, max_messages: int) -> list[dict]: ...
    def ack(self, subscription: str, message_ids: list[str]) -> None: ...
    def create_topic(self, topic: str) -> None: ...
    def create_subscription(self, topic: str, subscription: str) -> None: ...

class StateStore(ABC):
    def get(self, key: str) -> Optional[dict]: ...
    def set(self, key: str, value: dict) -> None: ...
    def delete(self, key: str) -> None: ...
    def all_keys(self) -> list[str]: ...

class DataWarehouse(ABC):
    def write_staging(self, dataset: str, table: str, records: list[dict]) -> int: ...
    def write_quarantine(self, pipeline_id: str, records: list[dict]) -> None: ...
    def create_dataset(self, dataset: str) -> None: ...
    def create_table(self, dataset: str, table: str, schema: dict) -> None: ...
```

### Config-driven provider selection

```yaml
# config/engine.yml
provider: gcp   # gcp | aws | azure | self_hosted

gcp:
  project_id: my-gcp-project
  region: us-central1
  minisky_url: http://localhost:8080   # for local dev

aws:
  region: us-east-1
  account_id: "123456789012"

azure:
  subscription_id: "..."
  resource_group: "ude-prod"

self_hosted:
  kafka_brokers: "localhost:9092"
  postgres_url: "postgresql://user:pass@localhost:5432/ude"
  rocksdb_path: ".state/"
```

### Build order recommendation

1. **Abstraction layer first** — define `base.py`, extract GCP implementations
2. **Self-hosted second** — Kafka + PostgreSQL + DuckDB (closest to original UDE v1, proven stack)
3. **AWS third** — largest alternative cloud user base
4. **Azure fourth** — enterprise segment

### Why this was deferred

The abstraction requires touching every file that calls GCP APIs directly. Without a comprehensive test suite for each provider, it's high-risk refactoring. The right time to build this is when there's a concrete user asking for AWS or self-hosted support — not speculatively.

**Note on dbt:** dbt already abstracts the warehouse layer. The same dbt models run on `dbt-bigquery`, `dbt-redshift`, `dbt-synapse`, `dbt-duckdb`, and `dbt-postgres` via `profiles.yml`. The transformation layer is already multi-cloud. Only the ingestion and state layers need the abstraction.

---

## Section 2 — Schema Layer Extensions

### 2.1 Dead letter queue for quarantine

**Current behaviour:** BROKEN batches go to quarantine and sit there until manually approved or rejected.

**Gap:** There is no automatic retry, no TTL on quarantined batches, and no way to route quarantined records to a secondary pipeline for manual inspection.

**Proposed design:**

```
Quarantine store (existing)
  ↓
Dead letter queue (new)
  - configurable TTL per pipeline (e.g. 7 days)
  - after TTL: auto-reject or escalate alert
  - DLQ inspector endpoint: GET /quarantine/dlq
  - DLQ CLI: ude quarantine dlq --pipeline customers
```

**Config addition:**

```yaml
# config/pipelines/customers.yml
quarantine:
  dlq_ttl_days: 7
  on_ttl_expire: reject   # reject | escalate | archive
  escalation_webhook: https://...
```

### 2.2 Cross-dataset referential integrity

**Current behaviour:** Each pipeline is validated in isolation. A `orders` record with a `customer_id` that doesn't exist in `customers` passes through silently.

**Proposed design:**

```yaml
# config/pipelines/orders.yml
referential_integrity:
  - field: customer_id
    references: customers.customer_id
    on_violation: quarantine   # quarantine | warn | pass
```

The engine checks the reference before staging. Unknown foreign keys are quarantined with reason `REFERENTIAL_INTEGRITY_VIOLATION`.

**Implementation note:** This requires a cross-pipeline read from BigQuery on every batch. Performance impact must be measured. Consider a bloom filter cache keyed by natural key for high-volume pipelines.

### 2.3 Schema migration approval workflow UI

**Current behaviour:** `ude schema approve <id>` works from the CLI. The Streamlit dashboard shows schema history but has no approve button.

**Gap:** An operator receiving a Slack alert about a BROKEN deviation has to open a terminal to approve it. A web UI button would be faster.

**Proposed addition:**

```
Streamlit — Schema History page
  Current: shows version timeline, locked schema, dbt contracts
  Add:     "Approve migration" button on BROKEN deviations
           Confirmation modal showing the diff
           Reason field (stored in audit log)
```

---

## Section 3 — dbt Extensions

### 3.1 dbt Mesh (cross-project model references)

**What it is:** dbt Mesh allows models in one dbt project to reference models in another project via `{{ ref('project_name', 'model_name') }}`. This enables a shared dimension layer across multiple UDE projects.

**Use case:** Multiple teams each have their own UDE project. They all want to reference a canonical `dim_customers` model maintained by the data platform team. Without dbt Mesh, each team maintains their own copy.

**Prerequisites:** dbt Core 1.6+, a shared dbt hub or private package registry.

**Why deferred:** Requires coordination between multiple engine deployments. Only relevant once multiple teams are running UDE in production.

### 3.2 dbt semantic layer integration

**What it is:** The dbt semantic layer (MetricFlow) defines business metrics in YAML and exposes them via a SQL API. Downstream tools (BI, notebooks) query metrics by name rather than writing SQL.

**Use case:**

```yaml
# dbt/metrics/orders.yml
metrics:
  - name: total_revenue
    label: Total Revenue
    model: ref('fct_orders')
    calculation_method: sum
    expression: order_total
    dimensions: [customer_id, order_date]
```

Any BI tool can then query: `SELECT total_revenue FROM ude_metrics WHERE date = today`.

**Why deferred:** Requires dbt Cloud or a self-hosted MetricFlow server. Adds significant infrastructure complexity. Best built when UDE has a clear BI integration story.

### 3.3 dbt model-level cost attribution

**What it is:** Track BigQuery bytes billed per dbt model run, per pipeline, per batch. Surface in Grafana and the operator dashboard.

**Implementation sketch:**

```python
# engine/dbt_runner/results.py
# After parsing run_results.json, also read:
#   target/run_results.json → adapter_response.bytes_billed
# Emit as Prometheus gauge:
#   ude_dbt_bytes_billed{pipeline, model}
```

**Why deferred:** Requires BigQuery job metadata API. Not available via MiniSky in local dev. Build when targeting production GCP deployments.

---

## Section 4 — Security Extensions

### 4.1 Key expiry email via SendGrid / Mailgun (production SMTP)

**Current behaviour:** Expiry emails use Gmail SMTP (`smtp.gmail.com:587`). Gmail App Passwords are limited to personal accounts and are not suitable for production deployments sending emails on behalf of an organisation.

**Proposed addition:**

```yaml
# ~/.ude/config.yml
email_provider: sendgrid   # gmail | sendgrid | mailgun | ses

sendgrid:
  api_key: SG.xxx
  from_email: noreply@yourcompany.com
  from_name: Unified Data Engine

mailgun:
  api_key: key-xxx
  domain: mg.yourcompany.com

ses:
  region: us-east-1
  from_email: noreply@yourcompany.com
```

**CLI addition:**

```bash
ude auth email-config --provider sendgrid --api-key SG.xxx
```

### 4.2 Production HTTPS (Let's Encrypt / CA-signed cert)

**Current behaviour:** `scripts/setup_https.py` generates a self-signed cert via `openssl`. Browsers warn about self-signed certs. Not suitable for production.

**Recommendation for production:**

Place UDE behind a reverse proxy with a CA-signed certificate. Two clean options:

**Option A — Caddy (simplest):**
```
# Caddyfile
ude.yourdomain.com {
    reverse_proxy localhost:8000
}
```
Caddy handles Let's Encrypt automatically. Zero configuration beyond the domain name.

**Option B — nginx + certbot:**
```bash
certbot --nginx -d ude.yourdomain.com
```

**Why not built into UDE:** Let's Encrypt requires a publicly accessible domain with DNS. UDE runs on `localhost` or private IPs in most deployments. The reverse proxy approach is the right separation of concerns — UDE handles the application, the proxy handles TLS termination.

**Future CLI addition (optional):**
```bash
ude setup caddy --domain ude.yourdomain.com
# Generates a Caddyfile and starts Caddy in Docker
```

### 4.3 IP allowlist per account

**Considered and rejected (for now).** See reasoning below.

An IP allowlist restricts an API key to specific IP addresses or CIDR ranges. The middleware would check `request.client.host` against the stored allowlist on every request.

**Why it was not built:**

Most developers have dynamic IPs — home broadband, mobile hotspots, CI/CD runners. An IP allowlist creates constant operational friction (updating the list whenever location changes) without meaningfully improving security. The right defense against a leaked key is **key rotation**, which is already implemented and takes 30 seconds.

**When to build it:** If UDE gains enterprise customers with static office IPs or VPC egress IPs who explicitly request it as a compliance requirement.

---

## Section 5 — Observability Extensions

### 5.1 `ude auth audit --watch` improvements

**Current behaviour:** Polls every 5 seconds, shows last N entries, updates the table in place.

**Gaps:**
- No colour-coded anomaly highlighting (e.g. red rows for 4xx/5xx)
- No sound/desktop notification on suspicious events
- No export to CSV

**Proposed additions:**

```bash
ude auth audit --watch --alert-on 401   # highlight 401s in red
ude auth audit --export audit.csv       # export to CSV
```

### 5.2 Engine health score

**What it is:** A single 0–100 score that summarises engine health, shown prominently in `ude status` and the Streamlit overview page.

**Inputs to the score:**

```
Quarantine rate      < 1%   → +25 pts
dbt test pass rate   100%   → +25 pts
Batch duration       < 30s  → +25 pts
Schema stability     no BROKEN in 24h → +25 pts
```

**Display:**

```
╭─── Engine Health ───╮
│  Score: 87/100      │
│  ● Excellent        │
│  ↓ Quarantine: 3%   │  ← deducted 13pts
╰─────────────────────╯
```

### 5.3 Streaming SCD (true streaming, not micro-batch)

**Current behaviour:** 30-second micro-batch windows. Records wait up to 30 seconds before processing.

**When this matters:** Real-time fraud detection, live inventory, sub-second event processing.

**Proposed architecture:**

Replace the micro-batch consumer with a streaming consumer using Pub/Sub push subscriptions or Dataflow. dbt snapshots don't support streaming — would need a custom merge layer or Apache Iceberg for streaming upserts.

**Why deferred:** Massive complexity increase. The 30-second window is sufficient for the vast majority of data engineering use cases. Build only if a concrete use case demands sub-second latency.

---

## Section 6 — Platform Extensions

### 6.1 dbt docs auto-deploy

**What it is:** After every `dbt docs generate`, automatically deploy the static site to a hosting URL so the team can browse the lineage graph and model documentation without running `dbt docs serve` locally.

**Implementation sketch:**

```bash
# Post dbt-docs generate, upload to GCS bucket with public access
gsutil -m rsync -r target/ gs://your-bucket/dbt-docs/
# Or push to GitHub Pages / Netlify
```

**CLI addition:**

```bash
ude dbt docs --deploy --bucket gs://your-bucket
```

### 6.2 dbt-external-tables for S3/GCS sources

**What it is:** `dbt-external-tables` allows dbt to manage external tables pointing at files in S3, GCS, or Azure Blob Storage. This would let UDE ingest from object storage in addition to Pub/Sub.

**Use case:** A daily export from a SaaS tool drops a CSV to S3. UDE picks it up, infers schema, runs edge case gate, writes to BigQuery.

**Why deferred:** Requires the multi-cloud provider abstraction first. Object storage paths are cloud-specific.

### 6.3 Terraform modules for real GCP

**Current state:** `terraform/` directory exists with basic MiniSky provisioning. No production GCP Terraform.

**Proposed modules:**

```
terraform/
  modules/
    pubsub/         — topics, subscriptions, IAM
    bigtable/       — instance, tables, IAM
    bigquery/       — datasets, tables, column-level security
    cloud_sql/      — instance, databases, users
    iam/            — service accounts, roles
    networking/     — VPC, firewall rules for private deployment
  environments/
    dev/            — MiniSky
    staging/        — real GCP, small instances
    prod/           — real GCP, production sizing
```

---

## Section 7 — Developer Experience

### 7.1 `ude test` — integration test runner

**What it is:** A CLI command that runs the full integration test suite against a live stack.

```bash
ude test                    # run all integration tests
ude test --suite schema     # run schema layer tests only
ude test --suite auth       # run auth layer tests only
ude test --pipeline events  # test a specific pipeline end to end
```

**Why this matters:** Currently integration tests require running `make test` inside the engine repo. 3rd party contributors have no way to run integration tests against their own deployment.

### 7.2 `ude doctor` — pre-flight diagnostic

**What it is:** A command that checks everything required to run UDE and reports what's missing.

```bash
ude doctor

Checking UDE prerequisites...
  ✓ Python 3.12.3
  ✓ Docker Desktop running
  ✓ MiniSky installed
  ✓ dbt-core 1.8.2
  ✓ openssl available
  ✗ Gmail App Password not configured — run: ude auth email-config
  ✗ API key not configured — run: ude auth signup
  ⚠ Port 8000 in use — run: ude down first

2 errors, 1 warning. Fix errors before running: ude up
```

### 7.3 Pipeline templates library

**What it is:** A collection of pre-built pipeline configurations for common data sources.

```bash
ude pipeline new --template github-repos
ude pipeline new --template hacker-news
ude pipeline new --template stripe-events
ude pipeline new --template postgres-cdc
ude pipeline new --template s3-export
```

Each template includes:
- Pre-filled `pipeline.yml` with sensible defaults
- Matching dbt staging model
- Sample data generator for local testing
- README with authentication setup

---

## Section 8 — Design Principles for Future Contributors

These principles shaped every decision in the current codebase. Future work should follow them.

**1. One command. Always.**
Any operation that requires more than one command and a config file is a bug in the developer experience. `ude up` starts everything. `ude doctor` diagnoses everything. If something requires manual steps, add a CLI command for it.

**2. The engine does not own transformation correctness. dbt does.**
Never add custom MERGE SQL to the engine. If a new SCD type or transformation pattern is needed, implement it as a dbt model. The engine's job is orchestration — trigger dbt, wait for results, checkpoint.

**3. Dirty data never reaches dbt.**
The edge case gate runs before staging. dbt source contracts are the second line of defence. If a contract violation fires, the edge case gate has a gap — fix the gate, not the contract.

**4. batch_id everywhere.**
Every staged record, every snapshot record, every audit entry carries the batch_id. End-to-end traceability is non-negotiable. Do not add any pipeline stage that drops the batch_id.

**5. Provider interfaces must be symmetric.**
Every provider must implement the full abstract interface. Partial implementations cause subtle failures at runtime. If a provider can't support a method (e.g. DynamoDB doesn't have SQL queries), redesign the interface — don't add conditional logic to the engine.

**6. Security is not optional.**
Every new API endpoint requires authentication by default. Public routes must be explicitly declared in `PUBLIC_ROUTES` in `api/middleware/auth.py`. No exceptions.

**7. The pip wheel must be self-contained.**
A user who runs `pip install unified-data-engine` and `ude up` should get the full experience — dashboards, monitoring, HTTPS setup — without cloning the repo. Any new file needed at runtime must be added to `cli/data/` and included in `pyproject.toml`.

---

## Appendix A — Version History

| Version | Released | What shipped |
|---|---|---|
| `3.1.0` | May 2026 | Email expiry notifications, audit --watch, suspicious activity webhook |
| `3.0.0` | May 2026 | HTTPS, list-keys, audit viewer, expiry warnings |
| `2.9.0` | May 2026 | Rate limiting, 90-day key TTL, audit log, Grafana password |
| `2.8.0` | May 2026 | Self-service API keys, Bearer token auth, project scoping |
| `2.7.2` | May 2026 | Grafana dashboards bundled, Prometheus scrapes Pushgateway |
| `2.6.0` | May 2026 | `ude up` one-command, auto-provision, context-aware for pip users |
| `2.0.0` | May 2026 | Initial PyPI release |

---

## Appendix B — Rejected Ideas

These were considered and explicitly rejected, not just deferred.

**IP allowlist per account** — creates operational friction (dynamic IPs) without meaningfully improving security. Key rotation is the correct defence against leaked keys.

**Go rewrite of the API** — Python + FastAPI is fast enough for the control plane. The bottleneck is the engine's 30-second batch window, not API latency. Introducing a second language increases contributor friction with no measurable benefit.

**Embedded database for auth state** — SQLite was considered for API key storage instead of Bigtable. Rejected because it would require a separate migration path when moving from local dev to production. Bigtable (local: JSON files) is already the state store for everything else — consistency matters more than simplicity here.

**Kafka as the default message bus** — Kafka was the original UDE v1 message bus. Replaced with Pub/Sub for the GCP-native architecture. Will return as the `self_hosted` provider implementation in the multi-cloud abstraction layer.

---

*End of document. Last updated: May 2026. Maintained by Taiwo Hassan.*