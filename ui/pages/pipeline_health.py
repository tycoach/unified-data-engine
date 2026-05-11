# ui/pages/pipeline_health.py
# Pipeline health — checkpoint history, batch stats, status timeline

import streamlit as st
import urllib.request
import json
import pandas as pd

API_BASE = "http://localhost:8000"


def _get(path: str) -> dict:
    try:
        req = urllib.request.Request(f"{API_BASE}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def render():
    st.title("📊 Pipeline Health")

    # Pipeline selector
    pipelines_data = _get("/pipeline/")
    pipelines = [p["pipeline_id"] for p in pipelines_data.get("pipelines", [])]

    if not pipelines:
        st.warning("No pipelines found. Run the engine first.")
        return

    selected = st.selectbox("Select Pipeline", pipelines)

    if not selected:
        return

    # ── Pipeline detail ───────────────────────────────────────────────────────
    detail = _get(f"/pipeline/{selected}")
    status_data = _get(f"/pipeline/{selected}/status")

    if "error" in detail:
        st.error(f"Could not load pipeline: {detail['error']}")
        return

    # Status bar
    status = status_data.get("status", "UNKNOWN")
    icon = "✅" if status == "COMPLETE" else "❌" if "FAIL" in status else "⏳"
    st.subheader(f"{icon} {selected.upper()} — {status}")

    col1, col2, col3, col4 = st.columns(4)
    schema = detail.get("schema") or {}
    last = detail.get("last_checkpoint") or {}

    col1.metric("Schema Version", f"v{schema.get('version', '?')}")
    col2.metric("Records Processed", last.get("records_processed", 0))
    col3.metric("Records Quarantined", last.get("records_quarantined", 0))
    col4.metric("dbt Success", "✅" if last.get("dbt_success") else "❌")

    st.divider()

    # ── Checkpoint history ────────────────────────────────────────────────────
    st.subheader("Checkpoint History")

    history = detail.get("checkpoint_history", [])
    if not history:
        st.info("No checkpoints yet — run the engine to process batches.")
        return

    # Build dataframe
    rows = []
    for cp in history:
        rows.append({
            "Batch ID": cp.get("batch_id", "")[:8] + "...",
            "Status": cp.get("status", ""),
            "Processed": cp.get("records_processed", 0),
            "Quarantined": cp.get("records_quarantined", 0),
            "Schema v": f"v{cp.get('schema_version', '?')}",
            "dbt": "✅" if cp.get("dbt_success") else "❌",
            "Checkpointed At": cp.get("checkpointed_at", "")[:19],
            "Failed At": cp.get("failed_at", "—") or "—",
        })

    df = pd.DataFrame(rows)

    # Color status column
    def color_status(val):
        if val == "COMPLETE":
            return "background-color: #d4edda"
        elif val == "FAILED":
            return "background-color: #f8d7da"
        return ""

    st.dataframe(
        df.style.applymap(color_status, subset=["Status"]),
        use_container_width=True,
        hide_index=True,
    )

    st.divider()

    # ── Schema fields ─────────────────────────────────────────────────────────
    st.subheader("Locked Schema Fields")

    fields = schema.get("fields", {})
    if fields:
        field_rows = [
            {
                "Field": name,
                "Type": meta.get("type", "?"),
                "Nullable": "✅" if meta.get("nullable") else "❌",
            }
            for name, meta in fields.items()
        ]
        st.dataframe(pd.DataFrame(field_rows), use_container_width=True, hide_index=True)

    if st.button("🔄 Refresh"):
        st.rerun()