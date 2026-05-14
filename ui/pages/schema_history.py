"""
ui/pages/schema_history.py — Locked schemas, version timeline, dbt source contracts
"""

import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from theme import page_header, badge, field_row
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


def _contract_html(pid: str, schema: dict) -> str:
    fields = schema.get("fields", {})
    locked_at = _fmt_ts(schema.get("locked_at", schema.get("inferred_at", "")))
    _type_map = {
        "string": "varchar", "datetime": "timestamp",
        "float": "float64", "integer": "int64",
        "boolean": "bool", "date": "date",
    }

    col_lines = []
    for fname, fdef in (fields.items() if isinstance(fields, dict) else {}):
        pg_type = _type_map.get(fdef.get("type", "string"), fdef.get("type", "varchar"))
        nullable = fdef.get("nullable", True)
        constraints = ""
        if not nullable:
            constraints = (
                "<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
                "<span class='kw'>constraints:</span>"
                "<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
                "- type: not_null"
            )
        col_lines.append(
            f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
            f"<span class='kw'>- name:</span> <span class='str'>{fname}</span><br>"
            f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
            f"<span class='kw'>data_type:</span> <span class='val'>{pg_type}</span>"
            f"{constraints}<br>"
        )

    cols_html = "".join(col_lines)
    return f"""<div class="dbt-contract">
<span class="kw"># AUTO-GENERATED</span> by schema registry — {locked_at}<br>
<span class="kw"># DO NOT EDIT MANUALLY</span><br><br>
<span class="kw">version:</span> <span class="val">2</span><br>
<span class="kw">sources:</span><br>
&nbsp;&nbsp;<span class="kw">- name:</span> <span class="str">staging</span><br>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="kw">tables:</span><br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span class="kw">- name:</span> <span class="str">{pid}_staged</span><br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span class="kw">config:</span><br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span class="kw">contract:</span> {{<span class="kw">enforced:</span> <span class="val">true</span>}}<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span class="kw">columns:</span><br>
{cols_html}
</div>"""


def render():
    # GET /schema/ → {"schemas": [...], "total": N}
    raw = _get("/schema/", {}) or {}

    # Extract list from {"schemas": [...]}
    schemas_list = raw.get("schemas", [])
    if not isinstance(schemas_list, list):
        schemas_list = []

    # Build dict keyed by pipeline_id
    all_schemas: dict = {}
    for s in schemas_list:
        if not isinstance(s, dict):
            continue
        pid = s.get("pipeline_id", "unknown")
        all_schemas[pid] = s

    pipeline_ids = list(all_schemas.keys())

    # Count deviation events
    n_evolved = sum(
        1 for s in all_schemas.values()
        for h in (s.get("history") or [])
        if isinstance(h, dict) and h.get("event") == "EVOLVED"
    )
    n_broken = sum(
        1 for s in all_schemas.values()
        for h in (s.get("history") or [])
        if isinstance(h, dict) and h.get("event") == "BROKEN"
    )
    n_locked = len(pipeline_ids)

    st.markdown(page_header(
        "🗄️", "Schema History",
        "Locked schemas, version timeline, and dbt source contracts"
    ), unsafe_allow_html=True)

    st.markdown(f"""
<div class="ude-stats ude-stats-3">
  <div class="ude-stat">
    <div class="ude-stat-label">Locked Schemas</div>
    <div class="ude-stat-value green">{n_locked}</div>
  </div>
  <div class="ude-stat">
    <div class="ude-stat-label">EVOLVED Events</div>
    <div class="ude-stat-value {'amber' if n_evolved else 'green'}">{n_evolved}</div>
    <div class="ude-stat-sub">last 24 h</div>
  </div>
  <div class="ude-stat">
    <div class="ude-stat-label">BROKEN Events</div>
    <div class="ude-stat-value {'red' if n_broken else 'green'}">{n_broken}</div>
    <div class="ude-stat-sub">last 24 h</div>
  </div>
</div>
""", unsafe_allow_html=True)

    if not pipeline_ids:
        st.markdown("""
<div class="ude-card" style="text-align:center;padding:30px;color:#5a5f6e;font-size:13px">
  No schemas locked yet. Run <code>make seed</code> to trigger the first batch.
</div>""", unsafe_allow_html=True)
        return

    col_sel, _ = st.columns([2, 5])
    with col_sel:
        selected_pid = st.selectbox(
            "Pipeline", pipeline_ids, label_visibility="collapsed"
        )

    # Load full schema for selected pipeline
    # Try dedicated endpoint first, fall back to list data
    schema = _get(f"/schema/{selected_pid}", None)
    if not isinstance(schema, dict) or not schema:
        schema = all_schemas.get(selected_pid, {})
    if not isinstance(schema, dict):
        schema = {}

    fields   = schema.get("fields", {})
    if not isinstance(fields, dict):
        fields = {}

    version  = schema.get("version", schema.get("locked_version", "1"))
    locked_at = _fmt_ts(
        schema.get("locked_at", schema.get("inferred_at", ""))
    )
    status   = schema.get("status", "LOCKED")
    n_fields = len(fields)
    history  = schema.get("history", [])
    if not isinstance(history, list):
        history = []

    status_kind = {
        "LOCKED": "locked", "BROKEN": "broken", "EVOLVED": "evolved"
    }.get(status, "locked")

    # ── Version banner ────────────────────────────────────────────────────────
    st.markdown(f"""
<div class="schema-banner">
  <div class="sb-version">v{version}</div>
  <div class="sb-divider"></div>
  <div class="sb-block">
    <div class="sb-label">Status</div>
    <div class="sb-val">{badge(status, status_kind)}</div>
  </div>
  <div class="sb-divider"></div>
  <div class="sb-block">
    <div class="sb-label">Locked at</div>
    <div class="sb-val">{locked_at}</div>
  </div>
  <div class="sb-divider"></div>
  <div class="sb-block">
    <div class="sb-label">Fields</div>
    <div class="sb-val">{n_fields}</div>
  </div>
</div>
""", unsafe_allow_html=True)

    col_left, col_right = st.columns(2, gap="medium")

    # Left — field definitions
    with col_left:
        fields_html = ""
        for fname, fdef in fields.items():
            if not isinstance(fdef, dict):
                fdef = {}
            dtype      = fdef.get("type", "string")
            nullable   = fdef.get("nullable", True)
            pk         = fdef.get("primary_key", False)
            is_new     = fdef.get("new", False)
            constraint = "PK" if pk else ("NOT NULL" if not nullable else "")
            fields_html += field_row(fname, dtype, constraint, nullable and not pk, is_new)

        if not fields_html:
            fields_html = '<div style="color:#3a3f4e;padding:16px 0;text-align:center;font-size:12px">No fields recorded</div>'

        st.markdown(f"""
<div class="ude-card">
  <div class="ude-card-title">🗂 Field Definitions</div>
  {fields_html}
</div>""", unsafe_allow_html=True)

    # Right — version timeline + dbt contract
    with col_right:
        _EV_KIND = {
            "LOCKED": "locked", "EVOLVED": "evolved",
            "BROKEN": "broken", "MATCH": "complete",
        }
        history_rows = ""
        for h in sorted(
            history,
            key=lambda x: x.get("timestamp", "") if isinstance(x, dict) else "",
            reverse=True,
        ):
            if not isinstance(h, dict):
                continue
            ev    = h.get("event", "?")
            ev_ts = _fmt_ts(h.get("timestamp", ""))
            ver   = h.get("version", "?")
            bk    = _EV_KIND.get(ev, "never")
            history_rows += f"""
<tr>
  <td>{badge(f'v{ver}', 'locked')}</td>
  <td>{badge(ev, bk)}</td>
  <td class="muted">{ev_ts}</td>
</tr>"""

        if not history_rows:
            history_rows = """
<tr>
  <td colspan="3" style="color:#3a3f4e;text-align:center;padding:16px 0">
    No history yet
  </td>
</tr>"""

        st.markdown(f"""
<div class="ude-card">
  <div class="ude-card-title">📅 Version Timeline</div>
  <table class="ude-table">
    <thead><tr><th>Version</th><th>Event</th><th>Date</th></tr></thead>
    <tbody>{history_rows}</tbody>
  </table>
</div>""", unsafe_allow_html=True)

        enforced_color = "#1D9E75" if status == "LOCKED" else "#E24B4A"
        enforced_label = "enforced" if status == "LOCKED" else "HELD — pending approval"

        st.markdown(f"""
<div class="ude-card">
  <div class="ude-card-title">
    &lt;/&gt; dbt Source Contract
    <span style="margin-left:auto;font-size:10px;color:{enforced_color};font-weight:500">
      {enforced_label}
    </span>
  </div>
  {_contract_html(selected_pid, schema)}
</div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    col1, col2, _ = st.columns([1.5, 1.5, 5])
    with col1:
        if st.button("↻  Refresh", key="schema_refresh"):
            st.rerun()
    with col2:
        if st.button("⟳  Schema Sync", key="schema_sync"):
            _get(f"/schema/{selected_pid}/sync", {})
            st.success("schema.yml regenerated from registry.")