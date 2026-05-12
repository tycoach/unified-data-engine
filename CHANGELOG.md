# Changelog

All notable changes to `unified-data-engine` are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.0.0] — 2026-03

### Added
- `ude` CLI — `pip install unified-data-engine` now ships the `ude` command
- `ude up / down / status / seed / init` — lifecycle commands wrapping the Makefile
- `ude dbt run / test / snapshot / docs / lineage` — UDE-aware dbt passthrough
- `ude pipeline list / inspect / new / enable / disable` — pipeline management
- `ude schema sync / history / diff / approve` — schema operations
- `ude quarantine list / inspect / approve / reject / replay` — quarantine management
- `ude observe logs / metrics / watch` — live terminal observability
- `pyproject.toml` — replaces `requirements.txt` for the installable package
- MiniSky pre-flight check on all local commands
- Friendly error messages for all failure modes (no raw tracebacks)

### Changed
- dbt transformation layer replaces all custom MERGE SQL (v1 → v2 core change)
- Engine reduced to orchestrator role — dbt owns transformation correctness
- Schema registry auto-generates dbt source contracts (`schema.yml`)

### Removed
- v1 custom MERGE SQL (`engine/processing/scd/type1.py`, `type2.py`, `merge_engine.py`)

---

## [1.0.0] — 2025

### Added
- Initial release — micro-batch engine with Pub/Sub, BigQuery, dbt Core
- FastAPI control plane (15+ endpoints)
- Streamlit operator dashboard (5 pages)
- Prometheus + Grafana monitoring (2 dashboards, 7 alert rules)
- MiniSky local GCP emulation
- Terraform for MiniSky + real GCP provisioning