# ui/pages/schema_history.py
# Schema history — locked schemas, version timeline, deviation log

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
    st.title("🔍 Schema History")
    st.caption("Locked schemas, version history, and dbt source contracts")

    # ── All schemas ───────────────────────────────────────────────────────────
    schemas_data = _get("/schema/")
    schemas = schemas_data.get("schemas", [])

    if not schemas:
        st.info("No locked schemas yet — run the engine to infer schemas.")
        return

    st.metric("Locked Schemas", len(schemas))

    # Pipeline selector
    pipeline_ids = [s["pipeline_id"] for s in schemas]
    selected = st.selectbox("Select Pipeline", pipeline_ids)

    if not selected:
        return

    schema = next((s for s in schemas if s["pipeline_id"] == selected), None)
    if not schema:
        return

    st.divider()

    # ── Schema detail ─────────────────────────────────────────────────────────
    st.subheader(f"Schema — {selected}")

    col1, col2, col3 = st.columns(3)
    col1.metric("Version", f"v{schema.get('version', '?')}")
    col2.metric("Status", schema.get("status", "?"))
    col3.metric("Fields", len(schema.get("fields", {})))

    locked_at = schema.get("locked_at", "")
    if locked_at:
        st.caption(f"Locked at: {locked_at[:19]} UTC")

    evolved_at = schema.get("evolved_at", "")
    if evolved_at:
        st.caption(f"Last evolved: {evolved_at[:19]} UTC")
        st.caption(f"Evolution reason: {schema.get('evolution_reason', '—')}")

    st.divider()

    # ── Fields table ──────────────────────────────────────────────────────────
    st.subheader("Schema Fields")

    fields = schema.get("fields", {})
    rows = [
        {
            "Field": name,
            "Type": meta.get("type", "?"),
            "Nullable": "✅ Yes" if meta.get("nullable") else "❌ No",
        }
        for name, meta in fields.items()
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.divider()

    # ── dbt source contract ───────────────────────────────────────────────────
    st.subheader("dbt Source Contract")

    contract_data = _get(f"/schema/{selected}/contract")
    contract_yaml = contract_data.get("contract_yaml", "")

    if contract_yaml:
        st.code(contract_yaml, language="yaml")
    else:
        st.info("No dbt contract found — run the engine first.")

    st.divider()

    # ── Actions ───────────────────────────────────────────────────────────────
    st.subheader("Actions")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("🔄 Sync dbt Contract", help="Regenerate _sources.yml from registry"):
            result = _get("/schema/")
            st.success("Contract synced — check dbt/models/staging/_sources.yml")

    with col2:
        if st.button(
            "⚠️ Reset Schema",
            help="Delete locked schema — next batch will re-infer",
        ):
            confirm = st.checkbox("I understand this will force schema re-inference")
            if confirm:
                req = urllib.request.Request(
                    f"{API_BASE}/schema/{selected}/reset",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        result = json.loads(resp.read())
                    st.success(f"Schema reset — {result.get('message', '')}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Reset failed: {e}")