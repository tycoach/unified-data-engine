"""
ui/pages/pipeline_health.py — Per-pipeline checkpoint history, stats, schema fields
"""

import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from theme import page_header, badge, section_label, field_row
import requests
from datetime import datetime

API = os.getenv("UDE_API_URL", "http://localhost:8000")


def _get(path, fallback=None):
    try:
        r = requests.get(f"{API}{path}", timeout=3)
        r.raise_for_status()
        return r.json()
    except Exception:
        return fallback


def _fmt_ts(ts: str) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromisoformat(
            str(ts).replace("Z", "+00:00")
        ).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(ts)


# ── Data loaders — matched to real API endpoints ──────────────────────────────

def load_pipelines(client) -> list:
    """GET /pipeline/ → {pipelines: [...], total: N}"""
    raw = client.get("/pipeline/", {}) or {}
    return raw.get("pipelines", [])


def load_pipeline_detail(client, pid: str) -> dict:
    """GET /pipeline/{id} → pipeline detail + checkpoint history"""
    return client.get(f"/pipeline/{pid}", {}) or {}


def load_pipeline_status(client, pid: str) -> dict:
    """GET /pipeline/{id}/status → quick status"""
    return client.get(f"/pipeline/{pid}/status", {}) or {}


def load_schema(client, pid: str) -> dict:
    """GET /schema/{id} → locked schema"""
    return client.get(f"/schema/{pid}", {}) or {}


def load_dbt_status(client, pid: str) -> dict:
    """GET /dbt/status → last dbt run info"""
    return client.get("/dbt/status", {}) or {}


# ── Render ────────────────────────────────────────────────────────────────────

def render(client=None):
    if client is None:
        from auth import get_client
        client = get_client()
    st.markdown(page_header(
        "📊", "Pipeline Health",
        "Checkpoint history, batch stats, and schema fields per pipeline"
    ), unsafe_allow_html=True)

    pipelines = load_pipelines(client)
    pipeline_ids = [
        p.get("pipeline_id", p) if isinstance(p, dict) else p
        for p in pipelines
    ]

    if not pipeline_ids:
        st.markdown("""
<div class="ude-card" style="color:#5a5f6e;font-size:13px;padding:30px;text-align:center">
  No pipelines found. Engine may still be starting up.
</div>""", unsafe_allow_html=True)
        return

    col_sel, _ = st.columns([2, 5])
    with col_sel:
        selected_pid = st.selectbox(
            "Pipeline", pipeline_ids, label_visibility="collapsed"
        )

    # ── Load data for selected pipeline ───────────────────────────────────────
    # Use the summary from the list (already loaded)
    p_summary = next(
        (p for p in pipelines if isinstance(p, dict) and p.get("pipeline_id") == selected_pid),
        {}
    )

    # Detail endpoint gives checkpoint history
    detail      = load_pipeline_detail(client, selected_pid)
    schema_data = load_schema(client, selected_pid)
    dbt_data    = load_dbt_status(client, selected_pid)

    # ── Stats row — from /pipeline/ summary ───────────────────────────────────
    last_status  = p_summary.get("last_status", "NEVER_RUN")
    scd_type     = p_summary.get("scd_type", "?")
    schema_ver   = p_summary.get("schema_version", "?")
    last_records = p_summary.get("last_batch_records", 0)
    last_at      = _fmt_ts(p_summary.get("last_batch_at", ""))
    last_id      = (p_summary.get("last_batch_id") or "")[:8] or "—"

    # From detail endpoint
    checkpoint_history = detail.get("checkpoint_history", [])
    total_batches = len(checkpoint_history)
    total_records = sum(
        c.get("records_processed", 0)
        for c in checkpoint_history
        if isinstance(c, dict)
    )

    # Quarantine from detail
    quarantine_count = detail.get("last_checkpoint", {}).get("records_quarantined", 0) \
        if isinstance(detail.get("last_checkpoint"), dict) else 0
    quarantine_rate = (quarantine_count / max(last_records, 1)) if last_records else 0.0

    qrate_color = "red" if quarantine_rate > 0.1 else ("amber" if quarantine_rate > 0 else "green")
    model_type  = "snapshot" if scd_type == 2 else "incremental"

    st.markdown(f"""
<div class="ude-stats ude-stats-3">
  <div class="ude-stat">
    <div class="ude-stat-label">Total Batches</div>
    <div class="ude-stat-value">{total_batches:,}</div>
    <div class="ude-stat-sub">{total_records:,} records total</div>
  </div>
  <div class="ude-stat">
    <div class="ude-stat-label">Quarantine Rate</div>
    <div class="ude-stat-value {qrate_color}">{quarantine_rate:.1%}</div>
    <div class="ude-stat-sub">{quarantine_count:,} records quarantined</div>
  </div>
  <div class="ude-stat">
    <div class="ude-stat-label">Schema Version</div>
    <div class="ude-stat-value green">v{schema_ver}</div>
    <div class="ude-stat-sub">SCD Type {scd_type} · {model_type}</div>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── Two columns: checkpoint table + schema fields ─────────────────────────
    col_left, col_right = st.columns(2, gap="medium")

    # Left — checkpoint history
    with col_left:
        _STATUS_KIND = {
            "COMPLETE":   "complete",
            "OK":         "complete",
            "FAILED":     "broken",
            "DBT_FAILED": "broken",
            "BROKEN":     "broken",
            "EVOLVED":    "evolved",
            "RUNNING":    "running",
        }

        rows_html = ""
        if checkpoint_history:
            for i, ck in enumerate(checkpoint_history[:10]):
                if not isinstance(ck, dict):
                    continue
                rec  = ck.get("records_processed", "—")
                dbt  = "✓" if ck.get("dbt_success") else "✗"
                st_  = ck.get("status", "COMPLETE")
                bk   = _STATUS_KIND.get(st_, "never")
                dur  = ck.get("checkpointed_at", "—")
                bid  = (ck.get("batch_id") or "")[:8] or f"#{i+1}"
                rec_str = f"{rec:,}" if isinstance(rec, int) else str(rec)
                dbt_color = "#1D9E75" if dbt == "✓" else "#E24B4A"
                rows_html += f"""
<tr>
  <td class="mono">#{bid}</td>
  <td class="primary">{rec_str}</td>
  <td style="color:{dbt_color}">{dbt}</td>
  <td class="muted">{_fmt_ts(dur)[:10]}</td>
  <td>{badge(st_, bk)}</td>
</tr>"""
        else:
            # Fall back to showing last batch from summary
            if last_id and last_id != "—":
                st_ = last_status
                bk  = _STATUS_KIND.get(st_, "never")
                rows_html = f"""
<tr>
  <td class="mono">#{last_id}</td>
  <td class="primary">{last_records:,}</td>
  <td style="color:#1D9E75">✓</td>
  <td class="muted">{last_at[:10]}</td>
  <td>{badge(st_, bk)}</td>
</tr>"""
            else:
                rows_html = """
<tr>
  <td colspan="5" style="color:#3a3f4e;text-align:center;padding:20px 0">
    No checkpoints yet
  </td>
</tr>"""

        st.markdown(f"""
<div class="ude-card">
  <div class="ude-card-title">⏱ Last 10 Batches</div>
  <table class="ude-table">
    <thead>
      <tr>
        <th>Batch</th><th>Records</th><th>dbt</th><th>Date</th><th>Status</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>""", unsafe_allow_html=True)

    # Right — schema fields
    with col_right:
        fields    = schema_data.get("fields", {})
        locked_at = _fmt_ts(schema_data.get("locked_at", ""))

        fields_html = ""
        if isinstance(fields, dict) and fields:
            for fname, fdef in fields.items():
                if not isinstance(fdef, dict):
                    fdef = {}
                dtype      = fdef.get("type", "?")
                nullable   = fdef.get("nullable", True)
                pk         = fdef.get("primary_key", False)
                is_new     = fdef.get("new", False)
                constraint = "PK" if pk else ("NOT NULL" if not nullable else "")
                fields_html += field_row(fname, dtype, constraint, nullable and not pk, is_new)
        else:
            fields_html = """
<div style="color:#3a3f4e;font-size:12px;padding:16px 0;text-align:center">
  Schema not yet locked
</div>"""

        st.markdown(f"""
<div class="ude-card">
  <div class="ude-card-title">🗂 Schema Fields
    <span style="margin-left:auto;font-size:10px;color:#3a3f4e;font-weight:400">
      Locked {locked_at}
    </span>
  </div>
  {fields_html}
</div>""", unsafe_allow_html=True)

    # ── dbt run metrics ────────────────────────────────────────────────────────
    st.markdown(section_label("dbt Run Metrics"), unsafe_allow_html=True)

    last_run    = dbt_data.get("status", "—")
    pipeline_match = dbt_data.get("pipeline_id", "") == selected_pid
    last_dur    = 0
    tests_pass  = 0
    tests_total = 0
    snap_opened = 0
    snap_closed = 0

    run_bk   = "complete" if last_run == "COMPLETE" else ("broken" if last_run == "FAILED" else "never")
    test_pct = f"{tests_pass}/{tests_total}" if tests_total else "—"
    run_label = last_run if pipeline_match else "—"

    st.markdown(f"""
<div class="ude-stats" style="grid-template-columns:repeat(4,minmax(0,1fr))">
  <div class="ude-stat">
    <div class="ude-stat-label">Last dbt Run</div>
    <div style="margin-top:6px">{badge(run_label, run_bk)}</div>
    <div class="ude-stat-sub">{last_dur:.1f}s</div>
  </div>
  <div class="ude-stat">
    <div class="ude-stat-label">Tests Passing</div>
    <div class="ude-stat-value {'green' if tests_pass == tests_total and tests_total > 0 else 'green'}">{test_pct}</div>
  </div>
  <div class="ude-stat">
    <div class="ude-stat-label">Snapshot Opened</div>
    <div class="ude-stat-value">{snap_opened:,}</div>
    <div class="ude-stat-sub">SCD Type 2 changes</div>
  </div>
  <div class="ude-stat">
    <div class="ude-stat-label">Snapshot Closed</div>
    <div class="ude-stat-value {'green' if snap_opened == snap_closed else 'red'}">{snap_closed:,}</div>
    <div class="ude-stat-sub">{'✓ balanced' if snap_opened == snap_closed else '⚠ mismatch'}</div>
  </div>
</div>
""", unsafe_allow_html=True)

    if st.button("↻  Refresh", key="health_refresh"):
        st.rerun()