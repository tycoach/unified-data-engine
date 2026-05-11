# api/main.py
# FastAPI control plane — UDE v1
# Exposes REST endpoints + /metrics for Prometheus scraping

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from api.routers import pipeline, schema, quarantine, dbt, health

app = FastAPI(
    title="Unified Data Engine",
    description="Control plane for UDE v1 — GCP-native data pipeline",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health.router,     prefix="/health",     tags=["Health"])
app.include_router(pipeline.router,   prefix="/pipeline",   tags=["Pipeline"])
app.include_router(schema.router,     prefix="/schema",     tags=["Schema"])
app.include_router(quarantine.router, prefix="/quarantine", tags=["Quarantine"])
app.include_router(dbt.router,        prefix="/dbt",        tags=["dbt"])


@app.get("/")
def root():
    return {
        "engine": "Unified Data Engine v2",
        "status": "running",
        "docs": "/docs",
        "metrics": "/metrics",
    }


@app.get("/metrics")
def metrics():
    """Prometheus scrape endpoint — emits all engine + dbt metrics."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )