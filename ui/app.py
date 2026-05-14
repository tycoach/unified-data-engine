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
_UI_DIR   = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_UI_DIR)
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

# Map page name → filename in ui/pages/
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
st.sidebar.markdown("""
<div style="padding: 0 8px;">
  <div class="minisky-chip" style="margin-bottom:6px">
    <span class="ude-brand-dot"></span>MiniSky connected
  </div>
  <div style="font-size:11px;color:#3a3f4e;padding:0 2px">
    localhost:8080 · local-dev-project
  </div>
</div>
""", unsafe_allow_html=True)


# ── Page loader ───────────────────────────────────────────────────────────────

def load_page(filename: str):
    """
    Load a page module directly from its file path.
    Bypasses Python's package system entirely — no parent module issues.
    Each page is loaded as a standalone module named by its stem.
    """
    filepath = os.path.join(_PAGES_DIR, filename)
    mod_name = filename.replace(".py", "")

    spec = importlib.util.spec_from_file_location(mod_name, filepath)
    mod  = importlib.util.module_from_spec(spec)

    # Register so the module can import siblings if needed
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── Render ────────────────────────────────────────────────────────────────────
try:
    page = load_page(FILE_MAP[selected])
    page.render()
except Exception as e:
    st.error(f"Failed to load page: {e}")
    st.exception(e)