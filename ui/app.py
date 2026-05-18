"""
ui/app.py — UDE Operator Dashboard entry point
Run with: PYTHONPATH=. streamlit run ui/app.py
"""

import os
import sys
import importlib.util
import streamlit as st

st.set_page_config(
    page_title="UDE Operator Dashboard",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Path setup ────────────────────────────────────────────────────────────────
_UI_DIR    = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR  = os.path.dirname(_UI_DIR)
_PAGES_DIR = os.path.join(_UI_DIR, "pages")

for p in (_ROOT_DIR, _UI_DIR, _PAGES_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

# ── Hide Streamlit multipage nav ──────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stSidebarNav"]          { display: none !important; }
[data-testid="stSidebarNavItems"]     { display: none !important; }
[data-testid="stSidebarNavSeparator"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

# ── Global CSS ────────────────────────────────────────────────────────────────
import theme
st.markdown(theme.GLOBAL_CSS, unsafe_allow_html=True)

# ── Auth — resolve project token ──────────────────────────────────────────────
from auth import get_client
client = get_client()

# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.markdown("""
<div class="ude-brand">
  <div class="ude-brand-name">
    <span class="ude-brand-dot"></span>UDE v2
  </div>
  <div class="ude-brand-sub">Unified Data Engine — Operator Dashboard</div>
</div>
""", unsafe_allow_html=True)

PAGE_ICONS = {
    "Overview":        "🏠",
    "Pipeline Health": "📊",
    "Quarantine":      "⚠️",
    "Schema History":  "🗄️",
    "dbt Lineage":     "🔗",
}

FILE_MAP = {
    "Overview":        "overview.py",
    "Pipeline Health": "pipeline_health.py",
    "Quarantine":      "quarantine.py",
    "Schema History":  "schema_history.py",
    "dbt Lineage":     "dbt_lineage.py",
}

selected = st.sidebar.radio(
    label="Navigate",
    options=list(PAGE_ICONS.keys()),
    format_func=lambda x: f"{PAGE_ICONS[x]}  {x}",
    label_visibility="collapsed",
)

st.sidebar.markdown("---")

# ── Project identity in sidebar ───────────────────────────────────────────────
if client.is_engine_owner:
    token_badge_color = "#EF9F27"
    token_badge_label = "Engine Owner"
    token_badge_bg    = "#1e1200"
    token_badge_border = "#854F0B"
else:
    token_badge_color  = "#1D9E75"
    token_badge_label  = client.project_name
    token_badge_bg     = "#0a2a1e"
    token_badge_border = "#0F6E56"

st.sidebar.markdown(f"""
<div style="padding: 0 8px;">
  <div style="
    background: {token_badge_bg};
    border: 1px solid {token_badge_border};
    border-radius: 6px;
    padding: 8px 10px;
    margin-bottom: 6px;
  ">
    <div style="font-size:10px;color:#5a5f6e;text-transform:uppercase;
                letter-spacing:0.06em;margin-bottom:4px">Project</div>
    <div style="font-size:12px;font-weight:600;color:{token_badge_color}">
      {token_badge_label}
    </div>
    <div style="font-size:10px;color:#3a3f4e;margin-top:3px;
                font-family:monospace">
      {client.token_display()}
    </div>
  </div>
  <div class="minisky-chip" style="margin-bottom:6px">
    <span class="ude-brand-dot"></span>MiniSky connected
  </div>
  <div style="font-size:11px;color:#3a3f4e;padding:0 2px">
    {client.base_url}
  </div>
</div>
""", unsafe_allow_html=True)


# ── Page loader ───────────────────────────────────────────────────────────────

def load_page(filename: str):
    """Load a page module directly from its file path."""
    filepath = os.path.join(_PAGES_DIR, filename)
    mod_name = filename.replace(".py", "")
    spec = importlib.util.spec_from_file_location(mod_name, filepath)
    mod  = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── Render ────────────────────────────────────────────────────────────────────
try:
    page = load_page(FILE_MAP[selected])
    # Pass the authenticated client to every page
    page.render(client=client)
except Exception as e:
    st.error(f"Failed to load page: {e}")
    st.exception(e)