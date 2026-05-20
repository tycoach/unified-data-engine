# api/main.py
"""
FastAPI control plane — UDE v2.0.0

Security: API key authentication via Bearer token.
Public routes: GET /, GET /health, POST /auth/signup, GET /metrics
All other routes require: Authorization: Bearer ude_live_<key>
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from api.middleware.auth import APIKeyMiddleware
from api.routers import dbt, health, pipeline, quarantine, schema
from api.routers.auth import router as auth_router
from api.routers.observe import install_log_handler, metrics_router, logs_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    install_log_handler()
    yield


app = FastAPI(
    title="Unified Data Engine",
    description=(
        "Control plane for UDE v2 — GCP-native dbt-powered micro-batch pipeline engine.\n\n"
        "**Authentication:** All endpoints (except `/`, `/health`, `/auth/signup`) "
        "require `Authorization: Bearer <api_key>`.\n\n"
        "Get an API key: `POST /auth/signup` or `ude auth signup`\n\n"
        "Install the CLI: `pip install unified-data-engine`"
    ),
    version="2.0.0",
    lifespan=lifespan,
)

# ── Middleware ────────────────────────────────────────────────────────────────
# Order matters — CORS first, then auth

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*", "Authorization"],
)

app.add_middleware(APIKeyMiddleware)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(auth_router,       prefix="/auth",       tags=["Auth"])
app.include_router(health.router,     prefix="/health",     tags=["Health"])
app.include_router(pipeline.router,   prefix="/pipeline",   tags=["Pipeline"])
app.include_router(schema.router,     prefix="/schema",     tags=["Schema"])
app.include_router(quarantine.router, prefix="/quarantine", tags=["Quarantine"])
app.include_router(dbt.router,        prefix="/dbt",        tags=["dbt"])
app.include_router(metrics_router,    prefix="/metrics-api", tags=["Observe"])
app.include_router(logs_router,       prefix="/logs",        tags=["Observe"])


# ── Root ──────────────────────────────────────────────────────────────────────

@app.get("/", tags=["Root"])
def root():
    return {
        "engine":  "Unified Data Engine v2.0.0",
        "status":  "running",
        "auth":    "POST /auth/signup to get an API key",
        "docs":    "/docs",
        "cli":     "pip install unified-data-engine",
    }


# ── Prometheus scrape endpoint (public — no auth) ─────────────────────────────

@app.get("/metrics", tags=["Observe"], include_in_schema=False)
def metrics():
    """Raw Prometheus text — scraped by Prometheus every 15s."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )