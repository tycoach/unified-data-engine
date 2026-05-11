# ui/app.py
# Unified Data Engine v1 — Operator Dashboard
# Start: streamlit run ui/app.py --server.port 8501
#
# Pages:
#   Pipeline Health   — live pipeline status + checkpoint history
#   Quarantine        — review dirty records
#   Schema History    — schema versions + deviation log
#   dbt Lineage       — model dependency graph

import streamlit as st

st.set_page_config(
    page_title="Unified Data Engine v1",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar navigation ────────────────────────────────────────────────────────
st.sidebar.title("⚙️ UDE v1")
st.sidebar.caption("Unified Data Engine — Operator Dashboard")
st.sidebar.divider()

page = st.sidebar.radio(
    "Navigate",
    [
        "🏠 Overview",
        "📊 Pipeline Health",
        "🚨 Quarantine",
        "🔍 Schema History",
        "🔗 dbt Lineage",
    ],
)

st.sidebar.divider()
st.sidebar.caption("API: http://localhost:8000")
st.sidebar.caption("Docs: http://localhost:8000/docs")

# ── Route to pages ────────────────────────────────────────────────────────────
if page == "🏠 Overview":
    from ui.pages.overview import render
    render()
elif page == "📊 Pipeline Health":
    from ui.pages.pipeline_health import render
    render()
elif page == "🚨 Quarantine":
    from ui.pages.quarantine import render
    render()
elif page == "🔍 Schema History":
    from ui.pages.schema_history import render
    render()
elif page == "🔗 dbt Lineage":
    from ui.pages.dbt_lineage import render
    render()