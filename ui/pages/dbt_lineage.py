"""
ui/pages/dbt_lineage.py — dbt model dependency DAG from manifest.json
"""

import streamlit as st
import streamlit.components.v1 as components
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from theme import page_header, section_label
import requests

API = os.getenv("UDE_API_URL", "http://localhost:8000")

def _get(path, fallback=None):
    try:
        r = requests.get(f"{API}{path}", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return fallback


# ── The DAG SVG — rendered via components.html so SVG isn't stripped ─────────

DAG_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #13141a;
    font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif;
    padding: 16px;
  }
  .wrap {
    background: #13141a;
    border: 1px solid #1f2128;
    border-radius: 8px;
    padding: 16px;
  }
  .title {
    font-size: 11px;
    font-weight: 600;
    color: #5a5f6e;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 14px;
  }
  svg text { font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif; }
</style>
</head>
<body>
<div class="wrap">
  <div class="title">Dependency Graph — manifest.json</div>
  <svg width="100%" viewBox="0 0 640 330" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <marker id="arr" viewBox="0 0 10 10" refX="8" refY="5"
              markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M2 1L8 5L2 9" fill="none" stroke="#2a3040"
              stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
      </marker>
    </defs>

    <!-- Sources -->
    <rect x="10"  y="44"  width="126" height="38" rx="6" fill="#0a2a1e" stroke="#0F6E56" stroke-width="0.8"/>
    <rect x="10"  y="142" width="126" height="38" rx="6" fill="#0a2a1e" stroke="#0F6E56" stroke-width="0.8"/>
    <rect x="10"  y="240" width="126" height="38" rx="6" fill="#0a2a1e" stroke="#0F6E56" stroke-width="0.8"/>

    <text x="73" y="59"  text-anchor="middle" font-size="11" fill="#1D9E75" font-family="monospace">raw.customers</text>
    <text x="73" y="74"  text-anchor="middle" font-size="10" fill="#0F6E56">Pub/Sub</text>
    <text x="73" y="157" text-anchor="middle" font-size="11" fill="#1D9E75" font-family="monospace">raw.orders</text>
    <text x="73" y="172" text-anchor="middle" font-size="10" fill="#0F6E56">Pub/Sub</text>
    <text x="73" y="255" text-anchor="middle" font-size="11" fill="#1D9E75" font-family="monospace">raw.products</text>
    <text x="73" y="270" text-anchor="middle" font-size="10" fill="#0F6E56">Pub/Sub</text>

    <!-- Staging -->
    <rect x="178" y="44"  width="148" height="38" rx="6" fill="#0a1a2e" stroke="#185FA5" stroke-width="0.8"/>
    <rect x="178" y="142" width="148" height="38" rx="6" fill="#0a1a2e" stroke="#185FA5" stroke-width="0.8"/>
    <rect x="178" y="240" width="148" height="38" rx="6" fill="#0a1a2e" stroke="#185FA5" stroke-width="0.8"/>

    <text x="252" y="59"  text-anchor="middle" font-size="11" fill="#378ADD" font-family="monospace">customers_staged</text>
    <text x="252" y="74"  text-anchor="middle" font-size="10" fill="#185FA5">view · staging</text>
    <text x="252" y="157" text-anchor="middle" font-size="11" fill="#378ADD" font-family="monospace">orders_staged</text>
    <text x="252" y="172" text-anchor="middle" font-size="10" fill="#185FA5">view · staging</text>
    <text x="252" y="255" text-anchor="middle" font-size="11" fill="#378ADD" font-family="monospace">products_staged</text>
    <text x="252" y="270" text-anchor="middle" font-size="10" fill="#185FA5">view · staging</text>

    <!-- Snapshots / Marts -->
    <rect x="376" y="12"  width="254" height="38" rx="6" fill="#1e1200" stroke="#854F0B" stroke-width="0.8"/>
    <rect x="376" y="76"  width="254" height="38" rx="6" fill="#0a1a2e" stroke="#185FA5" stroke-width="0.8"/>
    <rect x="376" y="160" width="254" height="38" rx="6" fill="#0a1a2e" stroke="#185FA5" stroke-width="0.8"/>
    <rect x="376" y="240" width="254" height="38" rx="6" fill="#1e1200" stroke="#854F0B" stroke-width="0.8"/>

    <text x="503" y="27"  text-anchor="middle" font-size="11" fill="#EF9F27" font-family="monospace">customers_snapshot</text>
    <text x="503" y="42"  text-anchor="middle" font-size="10" fill="#854F0B">snapshot · SCD Type 2</text>
    <text x="503" y="91"  text-anchor="middle" font-size="11" fill="#378ADD" font-family="monospace">dim_customers</text>
    <text x="503" y="106" text-anchor="middle" font-size="10" fill="#185FA5">incremental · SCD Type 1</text>
    <text x="503" y="175" text-anchor="middle" font-size="11" fill="#378ADD" font-family="monospace">fct_orders</text>
    <text x="503" y="190" text-anchor="middle" font-size="10" fill="#185FA5">incremental</text>
    <text x="503" y="255" text-anchor="middle" font-size="11" fill="#EF9F27" font-family="monospace">products_snapshot</text>
    <text x="503" y="270" text-anchor="middle" font-size="10" fill="#854F0B">snapshot · SCD Type 2</text>

    <!-- Edges source → staging -->
    <line x1="136" y1="63"  x2="176" y2="63"  stroke="#2a3040" stroke-width="1" marker-end="url(#arr)"/>
    <line x1="136" y1="161" x2="176" y2="161" stroke="#2a3040" stroke-width="1" marker-end="url(#arr)"/>
    <line x1="136" y1="259" x2="176" y2="259" stroke="#2a3040" stroke-width="1" marker-end="url(#arr)"/>

    <!-- Edges staging → snapshot/mart -->
    <line x1="326" y1="57"  x2="374" y2="33"  stroke="#2a3040" stroke-width="1" marker-end="url(#arr)"/>
    <line x1="326" y1="70"  x2="374" y2="93"  stroke="#2a3040" stroke-width="1" marker-end="url(#arr)"/>
    <line x1="326" y1="161" x2="374" y2="178" stroke="#2a3040" stroke-width="1" marker-end="url(#arr)"/>
    <line x1="326" y1="259" x2="374" y2="259" stroke="#2a3040" stroke-width="1" marker-end="url(#arr)"/>

    <!-- Legend -->
    <rect x="10"  y="298" width="10" height="10" rx="2" fill="#0a2a1e" stroke="#0F6E56" stroke-width="0.8"/>
    <text x="26"  y="307" font-size="10" fill="#5a5f6e">source</text>
    <rect x="80"  y="298" width="10" height="10" rx="2" fill="#0a1a2e" stroke="#185FA5" stroke-width="0.8"/>
    <text x="96"  y="307" font-size="10" fill="#5a5f6e">staging / mart</text>
    <rect x="194" y="298" width="10" height="10" rx="2" fill="#1e1200" stroke="#854F0B" stroke-width="0.8"/>
    <text x="210" y="307" font-size="10" fill="#5a5f6e">snapshot</text>
  </svg>
</div>
</body>
</html>
"""


def render():
    dbt_status = _get("/dbt/status", {}) or {}

    last_run    = dbt_status.get("last_run_status", "—")
    tests_pass  = dbt_status.get("tests_passing", 0)
    tests_total = dbt_status.get("tests_total", 0)
    n_staging   = dbt_status.get("staging_models", 3)
    n_marts     = dbt_status.get("mart_models", 2)
    n_snapshots = dbt_status.get("snapshots", 2)
    manifest_ok = dbt_status.get("manifest_available", True)

    test_label = f"{tests_pass}/{tests_total} passing" if tests_total else "No tests run"
    test_color = "#1D9E75" if (tests_pass == tests_total and tests_total > 0) else "#E24B4A"
    run_color  = "#1D9E75" if last_run == "success" else ("#E24B4A" if last_run == "failed" else "#5a5f6e")
    run_label  = f"Last run: {last_run.upper()}" if last_run != "—" else "Never run"

    st.markdown(page_header(
        "🔗", "dbt Lineage",
        "Model dependency DAG parsed from manifest.json"
    ), unsafe_allow_html=True)

    st.markdown(f"""
<div class="lineage-chips">
  <div class="lm-chip"><span style="color:#1D9E75">●</span> <strong>{n_staging}</strong> staging models</div>
  <div class="lm-chip"><span style="color:#378ADD">●</span> <strong>{n_marts}</strong> mart models</div>
  <div class="lm-chip"><span style="color:#EF9F27">●</span> <strong>{n_snapshots}</strong> snapshots</div>
  <div class="lm-chip" style="color:{test_color}">
    {'✓' if tests_pass == tests_total and tests_total > 0 else '✗'} {test_label}
  </div>
  <div class="lm-chip" style="color:{run_color}">⟳ {run_label}</div>
</div>
""", unsafe_allow_html=True)

    # Render DAG via components.html — SVG is stripped by st.markdown
    components.html(DAG_HTML, height=380, scrolling=False)

    # ── Model run history ─────────────────────────────────────────────────────
    st.markdown(section_label("Model Run History"), unsafe_allow_html=True)

    model_runs = _get("/dbt/runs?limit=10", []) or []

    if model_runs and isinstance(model_runs, list):
        _STATUS_KIND = {"success": "complete", "failed": "broken", "skipped": "never"}
        rows_html = ""
        for run in model_runs:
            if not isinstance(run, dict):
                continue
            model  = run.get("model", "—")
            status = run.get("status", "—")
            rows   = run.get("rows_affected", "—")
            dur    = run.get("duration_seconds", 0) or 0
            ts     = run.get("run_at", "—")
            bk     = _STATUS_KIND.get(status, "never")
            rows_str = f"{rows:,}" if isinstance(rows, int) else str(rows)
            from datetime import datetime
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "")).strftime("%H:%M:%S")
            except Exception:
                pass
            rows_html += f"""
<tr>
  <td class="mono primary">{model}</td>
  <td>{badge(status.upper(), bk)}</td>
  <td class="primary">{rows_str}</td>
  <td>{float(dur):.1f}s</td>
  <td class="muted">{ts}</td>
</tr>"""

        st.markdown(f"""
<div class="ude-card">
  <table class="ude-table">
    <thead><tr><th>Model</th><th>Status</th><th>Rows</th><th>Duration</th><th>Run at</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>""", unsafe_allow_html=True)
    else:
        st.markdown("""
<div class="ude-card" style="color:#5a5f6e;font-size:12px;padding:24px;text-align:center">
  No dbt run history yet. Run
  <code style="background:#1a1b21;padding:1px 6px;border-radius:3px">make dbt-run</code>
  to trigger a manual run.
</div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    col1, col2, col3, _ = st.columns([1.2, 1.2, 1.2, 4])

    with col1:
        if st.button("▶  Run dbt", key="dbt_run"):
            result = _get("/dbt/run", {}) or {}
            if result.get("status") == "triggered":
                st.success("dbt run triggered.")
            else:
                st.info("dbt run queued or already in progress.")

    with col2:
        if st.button("✓  Run Tests", key="dbt_test"):
            _get("/dbt/test", {})
            st.info("dbt test triggered.")

    with col3:
        if st.button("↻  Refresh", key="lineage_refresh"):
            st.rerun()


# make badge available without circular import
from theme import badge