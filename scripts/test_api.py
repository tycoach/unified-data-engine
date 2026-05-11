# scripts/test_api.py
# End-to-end test of Phase 7 — FastAPI control plane
# Starts the API server and hits every endpoint
# Run: python scripts/test_api.py

import sys
import json
import time
import logging
import threading
import urllib.request

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_BASE = "http://localhost:8000"


def _get(path: str) -> dict:
    url = f"{API_BASE}{path}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        logger.warning(f"GET {path} → HTTP {e.code}: {body}")
        return {"error": e.code, "body": body}
    except Exception as e:
        logger.error(f"GET {path} → {e}")
        return {"error": str(e)}


def _post(path: str, body: dict) -> dict:
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        logger.warning(f"POST {path} → HTTP {e.code}: {body}")
        return {"error": e.code, "body": body}
    except Exception as e:
        logger.error(f"POST {path} → {e}")
        return {"error": str(e)}


def start_server():
    """Start FastAPI in background thread."""
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, log_level="warning")


def wait_for_api(retries: int = 10):
    """Wait for API to be ready."""
    for i in range(retries):
        try:
            with urllib.request.urlopen(f"{API_BASE}/", timeout=2) as resp:
                if resp.status == 200:
                    logger.info(" API is ready")
                    return True
        except Exception:
            time.sleep(1)
    return False


if __name__ == "__main__":
    # Start API server in background
    logger.info("Starting FastAPI server...")
    thread = threading.Thread(target=start_server, daemon=True)
    thread.start()

    if not wait_for_api():
        logger.error(" API failed to start")
        sys.exit(1)

    # ── Test endpoints ────────────────────────────────────────────────────────

    logger.info("\n=== GET / ===")
    r = _get("/")
    logger.info(f"{r}")

    logger.info("\n=== GET /health ===")
    r = _get("/health/")
    logger.info(f" status={r.get('status')} minisky={r.get('minisky_connected')}")

    logger.info("\n=== GET /health/state ===")
    r = _get("/health/state")
    logger.info(f" state_keys={r.get('total_keys')}")

    logger.info("\n=== GET /health/minisky ===")
    r = _get("/health/minisky")
    logger.info(f" minisky connected={r.get('connected')}")

    logger.info("\n=== GET /pipeline ===")
    r = _get("/pipeline/")
    logger.info(f"pipelines={[p['pipeline_id'] for p in r.get('pipelines', [])]}")

    logger.info("\n=== GET /pipeline/customers ===")
    r = _get("/pipeline/customers")
    logger.info(f" schema_version={r.get('schema', {}).get('version')}")

    logger.info("\n=== GET /pipeline/customers/status ===")
    r = _get("/pipeline/customers/status")
    logger.info(f" status={r.get('status')}")

    logger.info("\n=== GET /schema ===")
    r = _get("/schema/")
    logger.info(f"schemas={[s['pipeline_id'] for s in r.get('schemas', [])]}")

    logger.info("\n=== GET /schema/customers ===")
    r = _get("/schema/customers")
    logger.info(f" version={r.get('version')} fields={list(r.get('fields', {}).keys())}")

    logger.info("\n=== GET /schema/customers/contract ===")
    r = _get("/schema/customers/contract")
    logger.info(f" contract present={bool(r.get('contract_yaml'))}")

    logger.info("\n=== GET /quarantine ===")
    r = _get("/quarantine/")
    logger.info(f" quarantine_tables={r.get('total')}")

    logger.info("\n=== GET /dbt/status ===")
    r = _get("/dbt/status")
    logger.info(f"dbt status={r.get('status')}")

    logger.info("\n=== GET /dbt/artifacts ===")
    r = _get("/dbt/artifacts")
    logger.info(f" artifacts={[a['name'] for a in r.get('artifacts', [])]}")

    logger.info("\n=== POST /dbt/run/customers ===")
    r = _post("/dbt/run/customers", {
        "batch_id": "api-test-batch-001",
        "scd_type": 2,
        "target": "dev"
    })
    logger.info(f" dbt run triggered: {r.get('status')}")

    logger.info("\nFastAPI control plane — all endpoints tested.")
    logger.info(f"Interactive docs at: {API_BASE}/docs")