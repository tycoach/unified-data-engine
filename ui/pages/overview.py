"""
ui/pages/overview.py — Engine overview (project-scoped)
"""

import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from theme import page_header, badge, section_label
from datetime import datetime


def _fmt_ts(ts: str) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromisoformat(
            str(ts).replace("Z", "+00:00")
        ).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(ts)


def render(client=None):
    # Fallback client if called without one (dev mode)
    if client is None:
        from auth import get_client
        client = get_client()

    # ── Fetch data ────────────────────────────────────────────────────────────
    health_raw   = client.get("/health/", {}) or {}
    pipeline_raw = client.get("/pipeline/", {}) or {}
    pipelines    = pipeline_raw.get("pipelines", [])

    engine_status = health_raw.get("status", "UNKNOWN").upper()
    minisky_ok    = health_raw.get("minisky_connected", False)
    state_keys    = health_raw.get("state_keys", 0)
    n_pipelines   = len(pipelines)
    n_degraded    = sum(
        1 for p in pipelines
        if p.get("last_status") not in ("COMPLETE", "NEVER_RUN")
    )

    engine_color  = "#1D9E75" if engine_status == "HEALTHY" else "#E24B4A"
    minisky_color = "#1D9E75" if minisky_ok else "#E24B4A"
    minisky_label = "Connected" if minisky_ok else "Disconnected"

    st.markdown(page_header(
        "⚙️", "Overview",
        f"Engine health, MiniSky status, and pipeline summary "
        f"— project: {client.project_name}"
    ), unsafe_allow_html=True)

    # ── Stat row ──────────────────────────────────────────────────────────────
    st.markdown(f"""
<div class="ude-stats">
  <div class="ude-stat">
    <div class="ude-stat-label">Engine Status</div>
    <div class="ude-stat-indicator" style="color:{engine_color}">
      <span style="width:9px;height:9px;border-radius:50%;background:{engine_color};
                   display:inline-block;animation:pulse 2s infinite"></span>
      {engine_status}
    </div>
  </div>
  <div class="ude-stat">
    <div class="ude-stat-label">MiniSky</div>
    <div class="minisky-chip"
         style="margin-top:6px;border-color:{minisky_color};color:{minisky_color}">
      <span style="width:7px;height:7px;border-radius:50%;background:{minisky_color};
                   animation:pulse 2s infinite"></span>
      {minisky_label}
    </div>
  </div>
  <div class="ude-stat">
    <div class="ude-stat-label">State Keys</div>
    <div class="ude-stat-value">{state_keys:,}</div>
    <div class="ude-stat-sub">Bigtable checkpoints</div>
  </div>
  <div class="ude-stat">
    <div class="ude-stat-label">Your Pipelines</div>
    <div class="ude-stat-value {'green' if n_degraded == 0 else 'amber'}">{n_pipelines}</div>
    <div class="ude-stat-sub">{n_degraded} degraded</div>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── Pipeline summary ──────────────────────────────────────────────────────
    st.markdown(section_label("Pipeline Summary"), unsafe_allow_html=True)

    if not pipelines:
        st.markdown(f"""
<div class="ude-card" style="color:#5a5f6e;font-size:13px;text-align:center;padding:30px">
  No pipelines found for project <code>{client.project_name}</code>.<br>
  Run <code>ude pipeline new</code> to register your first pipeline.
</div>
""", unsafe_allow_html=True)
    else:
        _ICONS = {
            "customers": ("👤", "green"),
            "orders":    ("🛒", "amber"),
            "products":  ("📦", "green"),
        }
        _STATUS_MAP = {
            "COMPLETE":   ("complete", "COMPLETE"),
            "NEVER_RUN":  ("never",    "NEVER RUN"),
            "RUNNING":    ("running",  "RUNNING"),
            "BROKEN":     ("broken",   "BROKEN"),
            "EVOLVED":    ("evolved",  "EVOLVED"),
            "FAILED":     ("broken",   "FAILED"),
            "DBT_FAILED": ("broken",   "DBT FAILED"),
        }

        cards_html = ""
        for p in pipelines:
            pid        = p.get("pipeline_id", "unknown")
            status     = p.get("last_status", "NEVER_RUN")
            scd        = p.get("scd_type", "?")
            schema_ver = p.get("schema_version", "?")
            last_at    = _fmt_ts(p.get("last_batch_at", ""))
            last_rec   = p.get("last_batch_records", 0)
            last_id    = (p.get("last_batch_id") or "")[:8]
            model      = "snapshot" if scd == 2 else "incremental"

            icon, icon_cls = _ICONS.get(pid, ("📁", "gray"))
            bk, bl = _STATUS_MAP.get(status, ("never", status))

            b_line = (
                f"Batch #{last_id} · {last_rec:,} records · {last_at}"
                if last_id else "Awaiting first batch"
            )

            cards_html += f"""
<div class="ude-pipeline-card">
  <div class="pl-icon {icon_cls}">{icon}</div>
  <div class="pl-info">
    <div class="pl-name">{pid}</div>
    <div class="pl-meta">SCD Type {scd} · {model} · schema v{schema_ver}</div>
  </div>
  <div class="pl-right">
    {badge(bl, bk)}
    <div class="pl-batch">{b_line}</div>
  </div>
</div>"""

        st.markdown(cards_html, unsafe_allow_html=True)

    # ── Alerts ────────────────────────────────────────────────────────────────
    st.markdown(section_label("Recent Alerts"), unsafe_allow_html=True)

    alerts = []
    for p in pipelines:
        status = p.get("last_status", "NEVER_RUN")
        pid    = p.get("pipeline_id", "?")
        last_at = _fmt_ts(p.get("last_batch_at", ""))
        if status in ("BROKEN", "SCHEMA_BROKEN"):
            alerts.append({
                "level":   "critical",
                "message": f"Pipeline <code>{pid}</code> has a BROKEN schema — batch quarantined.",
                "time":    last_at,
            })
        elif status in ("FAILED", "DBT_FAILED"):
            alerts.append({
                "level":   "warning",
                "message": f"Pipeline <code>{pid}</code> last batch FAILED — retrying.",
                "time":    last_at,
            })

    if not alerts:
        alerts = [{"level": "info", "message": "No recent alerts — all pipelines nominal.", "time": ""}]

    _LEVEL_MAP = {"critical": "critical", "warning": "warning", "info": "never"}
    rows_html = ""
    for a in alerts:
        lvl = a.get("level", "info")
        bk  = _LEVEL_MAP.get(lvl, "never")
        rows_html += f"""
<div class="ude-alert-row">
  {badge(lvl.upper(), bk)}
  <div class="ude-alert-msg">{a.get('message', '')}</div>
  <div class="ude-alert-time">{a.get('time', '')}</div>
</div>"""

    st.markdown(f'<div class="ude-alert-list">{rows_html}</div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("↻  Refresh", key="overview_refresh"):
        st.rerun()