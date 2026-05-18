"""
ui/pages/quarantine.py — Quarantine review and migration approval
"""

import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from theme import page_header, badge
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

def _post(path, payload=None):
    try:
        r = requests.post(f"{API}{path}", json=payload or {}, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _normalise(raw) -> list:
    """
    The /quarantine endpoint may return:
      - a list of dicts  (ideal)
      - a list of strings (batch_ids only)
      - a dict with a key like "items" or "quarantine"
      - None / error
    Normalise all into a list of dicts.
    """
    if not raw:
        return []
    if isinstance(raw, dict):
        for key in ("items", "quarantine", "results", "data",
                    "quarantine_tables"):
            if key in raw and isinstance(raw[key], list):
                raw = raw[key]
                break
        else:
            return [raw]
    if not isinstance(raw, list):
        return []
    normalised = []
    for item in raw:
        if isinstance(item, dict):
            normalised.append(item)
        elif isinstance(item, str):
            normalised.append({"batch_id": item, "failure_reason": "UNKNOWN"})
        else:
            normalised.append({"batch_id": str(item), "failure_reason": "UNKNOWN"})
    return normalised


def _normalise_records(raw) -> list:
    """
    /quarantine/{batch_id}/records may return:
      - a list directly
      - a dict with a "records" key
      - None
    Always return a list.
    """
    if not raw:
        return []
    if isinstance(raw, dict):
        for key in ("records", "items", "data", "results"):
            if key in raw and isinstance(raw[key], list):
                return raw[key]
        return []
    if isinstance(raw, list):
        return raw
    return []


def _diff_html(schema_diff) -> str:
    if not isinstance(schema_diff, dict):
        return '<div style="color:#3a3f4e">No diff available</div>'
    lines = []
    for col in schema_diff.get("removed", []):
        lines.append(
            f'<div class="diff-removed">− removed &nbsp;'
            f'<code style="background:#1a0808;color:#E24B4A;padding:1px 5px;border-radius:3px">{col}</code></div>'
        )
    for col in schema_diff.get("added", []):
        lines.append(
            f'<div class="diff-added">+ added &nbsp;&nbsp;'
            f'<code style="background:#0a1e10;color:#1D9E75;padding:1px 5px;border-radius:3px">{col}</code></div>'
        )
    for col, info in (schema_diff.get("type_changed") or {}).items():
        if isinstance(info, dict):
            frm, to = info.get("from", "?"), info.get("to", "?")
        else:
            frm, to = "?", str(info)
        lines.append(
            f'<div style="color:#EF9F27">~ changed '
            f'<code style="background:#1a1000;color:#EF9F27;padding:1px 5px;border-radius:3px">{col}</code> '
            f'<span style="color:#3a3f4e">{frm} → {to}</span></div>'
        )
    return "\n".join(lines) if lines else '<div style="color:#3a3f4e">No diff details available</div>'


def _fmt_ts(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace("Z", "")).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return ts or "—"


# ── Render ────────────────────────────────────────────────────────────────────

def render(client=None):
    if client is None:
        from auth import get_client
        client = get_client()
    raw = client.get("/quarantine/", [])
    quarantine_items = _normalise(raw)

    n_broken  = sum(1 for q in quarantine_items if "BROKEN"  in str(q.get("failure_reason", "")))
    n_evolved = sum(1 for q in quarantine_items if "EVOLVED" in str(q.get("failure_reason", "")))
    n_total   = len(quarantine_items)

    st.markdown(page_header(
        "⚠️", "Quarantine",
        f"{n_total} batch{'es' if n_total != 1 else ''} pending review — "
        f"{n_broken} BROKEN · {n_evolved} EVOLVED"
    ), unsafe_allow_html=True)

    total_records = sum(q.get("record_count", 0) for q in quarantine_items)
    oldest_ts = min(
        (q.get("timestamp", "9999") for q in quarantine_items),
        default="—"
    )

    st.markdown(f"""
<div class="ude-stats ude-stats-3">
  <div class="ude-stat">
    <div class="ude-stat-label">Pending Batches</div>
    <div class="ude-stat-value {'red' if n_total else 'green'}">{n_total}</div>
  </div>
  <div class="ude-stat">
    <div class="ude-stat-label">Records Quarantined</div>
    <div class="ude-stat-value amber">{total_records:,}</div>
    <div class="ude-stat-sub">Awaiting operator decision</div>
  </div>
  <div class="ude-stat">
    <div class="ude-stat-label">Oldest Batch</div>
    <div class="ude-stat-sub" style="margin-top:8px;font-size:12px;color:#9aa0b2">
      {_fmt_ts(str(oldest_ts))}
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

    if not quarantine_items:
        st.markdown("""
<div class="ude-card" style="text-align:center;padding:36px;color:#5a5f6e;font-size:13px">
  ✓ &nbsp; Quarantine is empty. All batches are clean.
</div>""", unsafe_allow_html=True)
        return

    for q in quarantine_items:
        batch_id    = q.get("batch_id", "unknown")
        pid         = q.get("pipeline_id", q.get("pipeline", "unknown"))
        reason      = q.get("failure_reason", q.get("reason", "UNKNOWN"))
        rec_count   = q.get("record_count", q.get("records", 0))
        ts          = q.get("timestamp", q.get("created_at", "—"))
        schema_diff = q.get("schema_diff", q.get("diff", {}))

        is_broken  = "BROKEN" in str(reason)
        card_cls   = "q-card" if is_broken else "q-card warn"
        badge_kind = "broken" if is_broken else "evolved"
        short_id   = str(batch_id)[:8] if len(str(batch_id)) > 8 else str(batch_id)
        diff_html  = _diff_html(schema_diff)

        st.markdown(f"""
<div class="{card_cls}">
  <div class="q-header">
    <div class="q-title">{pid} — Batch #{short_id}</div>
    {badge(str(reason), badge_kind)}
  </div>
  <div class="q-meta">
    <span>🗄 {rec_count:,} records</span>
    <span>🕐 {_fmt_ts(str(ts))}</span>
  </div>
  <div class="q-diff">
    <div class="diff-label">Schema diff</div>
    {diff_html}
  </div>
</div>
""", unsafe_allow_html=True)

        btn_col1, btn_col2, btn_col3, _ = st.columns([1.4, 1.4, 1.2, 4])

        with btn_col1:
            label = "Approve migration" if is_broken else "Accept evolution"
            if st.button(f"✓  {label}", key=f"approve_{batch_id}", type="primary"):
                result = client.post(f"/schema/{pid}/approve-migration", {
                    "batch_id": batch_id,
                    "reason": "Approved via operator dashboard",
                })
                if "error" in (result or {}):
                    st.error(f"API error: {result['error']}")
                else:
                    st.success(f"Migration approved for {pid}.")
                    st.rerun()

        with btn_col2:
            if st.button("✕  Reject batch", key=f"reject_{batch_id}"):
                result = client.post(f"/quarantine/{batch_id}/reject", {})
                if "error" in (result or {}):
                    st.error(f"API error: {result['error']}")
                else:
                    st.warning(f"Batch {short_id} rejected.")
                    st.rerun()

        with btn_col3:
            with st.expander("🔍 View records"):
                raw_records = client.get(f"/quarantine/{pid}/records", {})
                records_list = _normalise_records(raw_records)
                if records_list:
                    st.json(records_list[:5])
                    if len(records_list) > 5:
                        st.caption(
                            f"Showing first 5 of {len(records_list)} records."
                        )
                else:
                    st.caption("No records available.")

        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("↻  Refresh", key="q_refresh"):
        st.rerun()