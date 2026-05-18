# ui/pages/dbt_lineage.py
# dbt lineage — model dependency graph from manifest.json
# Shows the DAG of models for each pipeline

import streamlit as st
import urllib.request
import json

API_BASE = "http://localhost:8000"


def _get(path: str) -> dict:
    try:
        req = urllib.request.Request(f"{API_BASE}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def render(client=None):
    if client is None:
        from auth import get_client
        client = get_client()
    st.title("🔗 dbt Lineage")
    st.caption("Model dependency graph from manifest.json — updated on every dbt run")

    # ── dbt artifacts ─────────────────────────────────────────────────────────
    artifacts = client.get("/dbt/artifacts")
    artifact_list = artifacts.get("artifacts", [])

    if not artifact_list:
        st.warning("No dbt artifacts found — run dbt compile or dbt run first.")
        return

    col1, col2 = st.columns(2)
    with col1:
        st.metric("dbt Artifacts", len(artifact_list))
    with col2:
        manifest = next((a for a in artifact_list if a["name"] == "manifest.json"), None)
        if manifest:
            st.metric("Manifest Updated", manifest.get("modified", "")[:19])

    st.divider()

    # ── Pipeline lineage ──────────────────────────────────────────────────────
    st.subheader("Model Lineage by Pipeline")

    pipeline_id = st.selectbox("Select Pipeline", ["customers", "orders"])

    lineage_data = client.get(f"/dbt/lineage/{pipeline_id}")

    if "error" in lineage_data:
        st.error(f"Could not load lineage: {lineage_data['error']}")
        return

    nodes = lineage_data.get("nodes", {})

    if not nodes:
        st.info(f"No lineage nodes found for '{pipeline_id}' — run dbt compile first.")
    else:
        st.metric("Nodes in DAG", len(nodes))

        for node_id, node in nodes.items():
            resource_type = node.get("resource_type", "model")
            name = node.get("name", node_id)
            depends_on = node.get("depends_on", [])
            schema = node.get("schema", "")

            icon = {
                "model": "📦",
                "snapshot": "📸",
                "test": "🧪",
                "source": "📥",
            }.get(resource_type, "🔷")

            with st.expander(f"{icon} {name} ({resource_type})"):
                st.write(f"**Schema:** `{schema}`")
                st.write(f"**Resource type:** `{resource_type}`")
                if depends_on:
                    st.write("**Depends on:**")
                    for dep in depends_on:
                        dep_name = dep.split(".")[-1]
                        st.write(f"  → `{dep_name}`")
                else:
                    st.write("**Depends on:** *(source — no upstream models)*")

    st.divider()

    # ── dbt run status ────────────────────────────────────────────────────────
    st.subheader("Last dbt Run")

    dbt_status = client.get("/dbt/status")
    status = dbt_status.get("status", "NO_RUNS")

    if status == "NO_RUNS":
        st.info("No dbt runs triggered yet.")
    else:
        icon = "✅" if dbt_status.get("success") else "❌" if status == "FAILED" else "🔄"
        st.write(f"**Status:** {icon} {status}")
        st.write(f"**Pipeline:** {dbt_status.get('pipeline_id', '—')}")
        st.write(f"**Batch ID:** {dbt_status.get('batch_id', '—')}")
        if dbt_status.get("completed_at"):
            st.write(f"**Completed:** {dbt_status['completed_at'][:19]}")

    st.divider()

    # ── Manual dbt trigger ────────────────────────────────────────────────────
    st.subheader("Manual dbt Run")

    col1, col2 = st.columns(2)
    with col1:
        batch_id = st.text_input("Batch ID", value="manual-run-001")
    with col2:
        scd_type = st.selectbox("SCD Type", [2, 1])

    if st.button("▶️ Trigger dbt Run"):
        data = json.dumps({
            "batch_id": batch_id,
            "scd_type": scd_type,
            "target": "dev",
        }).encode()
        req = urllib.request.Request(
            f"{API_BASE}/dbt/run/{pipeline_id}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
            st.success(f"dbt run triggered — status: {result.get('status')}")
            st.info("Poll /dbt/status for result or refresh this page.")
        except Exception as e:
            st.error(f"Trigger failed: {e}")