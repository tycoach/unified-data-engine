# ui/pages/quarantine.py
# Quarantine viewer — inspect dirty records, approve migrations

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


def _post(path: str, body: dict) -> dict:
    try:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{API_BASE}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def render():
    st.title("🚨 Quarantine Viewer")
    st.caption("Records that failed the edge case gate — review and take action")

    # ── Quarantine summary ────────────────────────────────────────────────────
    summary = _get("/quarantine/")

    if "error" in summary:
        st.error(f"Could not connect to API: {summary['error']}")
        return

    tables = summary.get("quarantine_tables", [])

    if not tables:
        st.success("✅ No quarantined records — all batches processed cleanly.")
        return

    st.metric("Quarantine Tables", len(tables))

    # Pipeline selector
    pipelines = [t.get("pipeline", "") for t in tables]
    selected = st.selectbox("Select Pipeline", pipelines)

    if not selected:
        return

    st.divider()

    # ── Quarantined records ───────────────────────────────────────────────────
    st.subheader(f"Quarantined Records — {selected}")

    records_data = _get(f"/quarantine/{selected}/records?limit=100")
    records = records_data.get("records", [])

    if not records:
        st.info("No records retrieved — quarantine table may be empty or unreadable.")
    else:
        rows = []
        for r in records:
            rows.append({
                "Batch ID": (r.get("batch_id") or "")[:8] + "...",
                "Failure Reason": r.get("failure_reason", "UNKNOWN"),
                "Quarantined At": (r.get("quarantined_at") or "")[:19],
                "Raw Record": r.get("raw_record", ""),
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()

    # ── Schema migration approval ─────────────────────────────────────────────
    st.subheader("Approve Schema Migration")
    st.caption(
        "If the quarantine was caused by a BROKEN schema deviation, "
        "approve the migration here to update the schema registry."
    )

    schema_data = _get(f"/schema/{selected}")
    current_fields = schema_data.get("fields", {})

    with st.expander("Current locked schema"):
        st.json(current_fields)

    reason = st.text_input(
        "Migration reason",
        placeholder="e.g. Upstream removed 'country' column intentionally",
    )

    updated_fields_json = st.text_area(
        "Updated fields (JSON)",
        value=json.dumps(current_fields, indent=2),
        height=200,
    )

    if st.button("✅ Approve Migration"):
        if not reason:
            st.error("Please provide a migration reason.")
            return
        try:
            updated_fields = json.loads(updated_fields_json)
            result = _post(
                f"/schema/{selected}/approve-migration",
                {"reason": reason, "updated_fields": updated_fields},
            )
            if "error" not in result:
                st.success(
                    f"✅ Migration approved — schema updated to v{result.get('new_version')}"
                )
            else:
                st.error(f"Migration failed: {result['error']}")
        except json.JSONDecodeError:
            st.error("Invalid JSON in updated fields.")