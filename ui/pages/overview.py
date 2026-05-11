# ui/pages/overview.py
# Engine overview — health, MiniSky status, quick stats

import streamlit as st
import urllib.request
import json
from datetime import datetime, timezone

API_BASE = "http://localhost:8000"


def _get(path: str) -> dict:
    try:
        req = urllib.request.Request(f"{API_BASE}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def render():
    st.title("⚙️ Unified Data Engine v1")
    st.caption(f"Last refreshed: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")

    # ── Health check ──────────────────────────────────────────────────────────
    health = _get("/health/")
    minisky = _get("/health/minisky")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        status = health.get("status", "unknown")
        color = "🟢" if status == "healthy" else "🔴"
        st.metric("Engine Status", f"{color} {status.upper()}")

    with col2:
        connected = minisky.get("connected", False)
        st.metric("MiniSky", "🟢 Connected" if connected else "🔴 Disconnected")

    with col3:
        state_data = _get("/health/state")
        st.metric("State Keys", state_data.get("total_keys", 0))

    with col4:
        pipelines = _get("/pipeline/")
        st.metric("Pipelines", pipelines.get("total", 0))

    st.divider()

    # ── Pipeline summary ──────────────────────────────────────────────────────
    st.subheader("Pipeline Summary")

    pipeline_list = pipelines.get("pipelines", [])
    if not pipeline_list:
        st.info("No pipelines found. Run the engine to start processing.")
        return

    for p in pipeline_list:
        status = p.get("last_status", "NEVER_RUN")
        icon = "✅" if status == "COMPLETE" else "❌" if status == "FAILED" else "⏳"

        with st.expander(f"{icon} {p['pipeline_id'].upper()} — {status}"):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Schema Version", f"v{p.get('schema_version', '?')}")
            c2.metric("Records Processed", p.get("records_processed", 0))
            c3.metric("Last Batch", p.get("last_batch_id", "—")[:8] + "..." if p.get("last_batch_id") else "—")
            c4.metric("Last Committed", p.get("last_committed_at", "—")[:19] if p.get("last_committed_at") else "—")

    st.divider()

    # ── Quick actions ─────────────────────────────────────────────────────────
    st.subheader("Quick Actions")
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("🌱 Seed customers data"):
            result = _get("/pipeline/customers/seed?num_records=50")
            if "error" not in result:
                st.success(f"Published {result.get('records_published', 0)} records")
            else:
                st.error(f"Seed failed: {result['error']}")

    with col2:
        if st.button("🔄 Refresh"):
            st.rerun()

    with col3:
        st.link_button("📖 API Docs", f"{API_BASE}/docs")