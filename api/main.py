# api/main.py
"""
FastAPI control plane — UDE v1.0.0
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from api.routers import dbt, health, pipeline, quarantine, schema
from api.routers.observe import install_log_handler, metrics_router, logs_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Install log handler at startup so ude observe logs works."""
    install_log_handler()
    yield


app = FastAPI(
    title="Unified Data Engine",
    description=(
        "Control plane for UDE v1 — GCP-native dbt-powered micro-batch pipeline engine.\n\n"
        "Install the CLI: `pip install unified-data-engine`\n"
        "CLI docs: `ude --help`"
    ),
    version="1.0.0",
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

# Observe: two separate routers so routes don't bleed across prefixes
app.include_router(metrics_router,    prefix="/metrics",    tags=["Observe"])
app.include_router(logs_router,       prefix="/logs",       tags=["Observe"])


# ── Root ──────────────────────────────────────────────────────────────────────

@app.get("/", tags=["Root"])
def root():
    return {
        "engine":  "Unified Data Engine v1.0.0",
        "status":  "running",
        "docs":    "/docs",
        "metrics": "/metrics",
        "cli":     "pip install unified-data-engine",
    }


# ── Prometheus scrape endpoint ────────────────────────────────────────────────

@app.get("/metrics", tags=["Observe"], include_in_schema=False)
def metrics():
    """Raw Prometheus text — scraped by Prometheus every 15s."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )