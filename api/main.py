# api/main.py
"""
FastAPI control plane — UDE v2.0.0
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from api.routers import dbt, health, pipeline, quarantine, schema
from api.routers.observe import install_log_handler, metrics_router, logs_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    install_log_handler()
    yield


app = FastAPI(
    title="Unified Data Engine",
    description=(
        "Control plane for UDE v2 — GCP-native dbt-powered micro-batch pipeline engine.\n\n"
        "Install the CLI: `pip install unified-data-engine`\n"
        "CLI docs: `ude --help`"
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(health.router,     prefix="/health",     tags=["Health"])
app.include_router(pipeline.router,   prefix="/pipeline",   tags=["Pipeline"])
app.include_router(schema.router,     prefix="/schema",     tags=["Schema"])
app.include_router(quarantine.router, prefix="/quarantine", tags=["Quarantine"])
app.include_router(dbt.router,        prefix="/dbt",        tags=["dbt"])

# /metrics-api/structured — JSON metrics for CLI + UI
app.include_router(metrics_router,    prefix="/metrics-api", tags=["Observe"])

# /logs/stream — NDJSON log stream
app.include_router(logs_router,       prefix="/logs",        tags=["Observe"])


# ── Root ──────────────────────────────────────────────────────────────────────

@app.get("/", tags=["Root"])
def root():
    return {
        "engine":             "Unified Data Engine v2.0.0",
        "status":             "running",
        "docs":               "/docs",
        "metrics_prometheus": "/metrics",
        "metrics_structured": "/metrics-api/structured",
        "logs":               "/logs/stream",
        "cli":                "pip install unified-data-engine",
    }


# ── Prometheus scrape endpoint — keep at /metrics ─────────────────────────────
# prometheus.yml scrapes this path — no change needed there

@app.get("/metrics", tags=["Observe"], include_in_schema=False)
def metrics():
    """Raw Prometheus text — scraped by Prometheus every 15s."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
