"""
theme.py — UDE Operator Dashboard shared styling
Inject via: st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
"""

GLOBAL_CSS = """
<style>
/* ── Reset & root ─────────────────────────────────── */
[data-testid="stAppViewContainer"] {
    background: #0e0f11;
}
[data-testid="stSidebar"] {
    background: #13141a !important;
    border-right: 1px solid #1f2128 !important;
}
[data-testid="stSidebar"] > div:first-child {
    padding-top: 0 !important;
}

/* ── Hide Streamlit chrome ───────────────────────── */
#MainMenu, footer, header { visibility: hidden; }
[data-testid="stToolbar"] { display: none; }
.block-container {
    padding: 24px 28px 40px !important;
    max-width: 1100px !important;
}

/* ── Typography ──────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    color: #e2e4e9;
}

/* ── Sidebar brand header ────────────────────────── */
.ude-brand {
    padding: 18px 16px 14px;
    border-bottom: 1px solid #1f2128;
    margin-bottom: 8px;
}
.ude-brand-name {
    font-size: 13px;
    font-weight: 600;
    color: #e2e4e9;
    letter-spacing: -0.01em;
    display: flex;
    align-items: center;
    gap: 7px;
}
.ude-brand-sub {
    font-size: 11px;
    color: #5a5f6e;
    margin-top: 3px;
}
.ude-brand-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #1D9E75;
    display: inline-block;
    animation: pulse 2s infinite;
}
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }

/* ── Page header ─────────────────────────────────── */
.ude-page-header {
    margin-bottom: 22px;
}
.ude-page-title {
    font-size: 20px;
    font-weight: 600;
    color: #e2e4e9;
    display: flex;
    align-items: center;
    gap: 9px;
    line-height: 1.2;
}
.ude-page-icon {
    color: #1D9E75;
    font-size: 18px;
}
.ude-page-sub {
    font-size: 12px;
    color: #5a5f6e;
    margin-top: 4px;
}

/* ── Stat cards ──────────────────────────────────── */
.ude-stats {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
    margin-bottom: 22px;
}
.ude-stats-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.ude-stat {
    background: #13141a;
    border: 1px solid #1f2128;
    border-radius: 8px;
    padding: 14px 16px;
}
.ude-stat-label {
    font-size: 11px;
    color: #5a5f6e;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 7px;
}
.ude-stat-value {
    font-size: 24px;
    font-weight: 600;
    color: #e2e4e9;
    line-height: 1;
}
.ude-stat-value.green  { color: #1D9E75; }
.ude-stat-value.red    { color: #E24B4A; }
.ude-stat-value.amber  { color: #EF9F27; }
.ude-stat-sub {
    font-size: 11px;
    color: #5a5f6e;
    margin-top: 5px;
}
.ude-stat-indicator {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    font-weight: 600;
    color: #1D9E75;
    margin-top: 4px;
}
.minisky-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #0a2a1e;
    color: #1D9E75;
    font-size: 12px;
    font-weight: 500;
    padding: 4px 10px;
    border-radius: 99px;
    border: 1px solid #0F6E56;
    margin-top: 4px;
}

/* ── Section labels ──────────────────────────────── */
.ude-section-label {
    font-size: 10px;
    font-weight: 600;
    color: #5a5f6e;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    margin-bottom: 10px;
    margin-top: 20px;
}

/* ── Pipeline cards ──────────────────────────────── */
.ude-pipeline-card {
    background: #13141a;
    border: 1px solid #1f2128;
    border-radius: 8px;
    padding: 13px 16px;
    display: flex;
    align-items: center;
    gap: 13px;
    margin-bottom: 8px;
    transition: border-color 0.15s;
}
.ude-pipeline-card:hover { border-color: #2a2d38; }
.pl-icon {
    width: 34px;
    height: 34px;
    border-radius: 7px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 15px;
    flex-shrink: 0;
}
.pl-icon.green { background: #0a2a1e; color: #1D9E75; }
.pl-icon.amber { background: #1e1800; color: #EF9F27; }
.pl-icon.gray  { background: #1a1b21; color: #5a5f6e; }
.pl-info { flex: 1; min-width: 0; }
.pl-name { font-size: 13px; font-weight: 600; color: #e2e4e9; }
.pl-meta { font-size: 11px; color: #5a5f6e; margin-top: 2px; }
.pl-right { text-align: right; flex-shrink: 0; }
.pl-batch { font-size: 11px; color: #3a3f4e; margin-top: 3px; }

/* ── Status badges ───────────────────────────────── */
.badge {
    display: inline-block;
    font-size: 10px;
    font-weight: 600;
    padding: 2px 9px;
    border-radius: 99px;
    letter-spacing: 0.03em;
}
.badge-complete { background: #0a2a1e; color: #1D9E75; border: 1px solid #0F6E56; }
.badge-running  { background: #0a1a2e; color: #378ADD; border: 1px solid #185FA5; }
.badge-never    { background: #1a1b21; color: #5a5f6e; border: 1px solid #2a2d38; }
.badge-broken   { background: #2a0a0a; color: #E24B4A; border: 1px solid #A32D2D; }
.badge-evolved  { background: #1e1200; color: #EF9F27; border: 1px solid #854F0B; }
.badge-locked   { background: #0a2a1e; color: #1D9E75; border: 1px solid #0F6E56; }
.badge-critical { background: #2a0a0a; color: #E24B4A; border: 1px solid #A32D2D; }
.badge-warning  { background: #1e1200; color: #EF9F27; border: 1px solid #854F0B; }

/* ── Alert rows ──────────────────────────────────── */
.ude-alert-list {
    background: #13141a;
    border: 1px solid #1f2128;
    border-radius: 8px;
    padding: 4px 16px;
}
.ude-alert-row {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 11px 0;
    border-bottom: 1px solid #1a1b21;
}
.ude-alert-row:last-child { border-bottom: none; }
.ude-alert-msg {
    flex: 1;
    font-size: 12px;
    color: #9aa0b2;
    line-height: 1.5;
}
.ude-alert-msg code {
    font-family: 'JetBrains Mono', 'Fira Mono', monospace;
    font-size: 11px;
    background: #1a1b21;
    padding: 1px 5px;
    border-radius: 4px;
    color: #c2c8d8;
}
.ude-alert-time { font-size: 11px; color: #3a3f4e; flex-shrink: 0; padding-top: 2px; }

/* ── Cards (generic) ─────────────────────────────── */
.ude-card {
    background: #13141a;
    border: 1px solid #1f2128;
    border-radius: 8px;
    padding: 15px 16px;
    margin-bottom: 12px;
}
.ude-card-title {
    font-size: 11px;
    font-weight: 600;
    color: #5a5f6e;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 6px;
}

/* ── Data table ──────────────────────────────────── */
.ude-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
}
.ude-table th {
    font-size: 10px;
    font-weight: 600;
    color: #3a3f4e;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 0 0 9px;
    border-bottom: 1px solid #1f2128;
    text-align: left;
}
.ude-table td {
    padding: 9px 0;
    border-bottom: 1px solid #1a1b21;
    color: #9aa0b2;
    vertical-align: middle;
}
.ude-table tr:last-child td { border-bottom: none; }
.ude-table td.primary { color: #e2e4e9; }
.ude-table td.mono {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: #c2c8d8;
}

/* ── Quarantine cards ────────────────────────────── */
.q-card {
    background: #13141a;
    border: 1px solid #1f2128;
    border-left: 3px solid #E24B4A;
    border-radius: 8px;
    padding: 14px 16px;
    margin-bottom: 10px;
}
.q-card.warn { border-left-color: #EF9F27; }
.q-header {
    display: flex;
    align-items: center;
    gap: 9px;
    margin-bottom: 10px;
}
.q-title { font-size: 13px; font-weight: 600; color: #e2e4e9; }
.q-meta {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    font-size: 11px;
    color: #5a5f6e;
}
.q-diff {
    background: #0d0e12;
    border: 1px solid #1a1b21;
    border-radius: 6px;
    padding: 9px 12px;
    margin-top: 10px;
    font-size: 11px;
    font-family: 'JetBrains Mono', monospace;
}
.diff-removed { color: #E24B4A; }
.diff-added   { color: #1D9E75; }
.diff-label   { font-size: 10px; color: #3a3f4e; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.05em; }

/* ── Schema banner ───────────────────────────────── */
.schema-banner {
    background: #13141a;
    border: 1px solid #1f2128;
    border-radius: 8px;
    padding: 16px 18px;
    display: flex;
    align-items: center;
    gap: 20px;
    margin-bottom: 14px;
    flex-wrap: wrap;
}
.sb-version {
    font-size: 32px;
    font-weight: 700;
    color: #e2e4e9;
    line-height: 1;
    min-width: 40px;
}
.sb-divider { width: 1px; height: 44px; background: #1f2128; flex-shrink: 0; }
.sb-block { }
.sb-label { font-size: 10px; color: #3a3f4e; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 4px; }
.sb-val   { font-size: 13px; font-weight: 500; color: #e2e4e9; }

/* ── Field list ──────────────────────────────────── */
.field-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 0;
    border-bottom: 1px solid #1a1b21;
}
.field-row:last-child { border-bottom: none; }
.field-name {
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: #c2c8d8;
    flex: 1;
}
.field-type {
    font-size: 11px;
    color: #378ADD;
    background: #0a1a2e;
    padding: 2px 8px;
    border-radius: 4px;
}
.field-constraint {
    font-size: 10px;
    color: #1D9E75;
    background: #0a2a1e;
    padding: 2px 7px;
    border-radius: 4px;
    font-weight: 500;
}
.field-nullable { font-size: 11px; color: #3a3f4e; min-width: 55px; text-align: right; }
.field-new {
    font-size: 10px;
    color: #EF9F27;
    background: #1e1200;
    padding: 2px 7px;
    border-radius: 4px;
    font-weight: 500;
}

/* ── dbt contract code block ─────────────────────── */
.dbt-contract {
    background: #0d0e12;
    border: 1px solid #1a1b21;
    border-radius: 6px;
    padding: 12px 14px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: #5a5f6e;
    line-height: 1.8;
}
.dbt-contract .kw  { color: #378ADD; }
.dbt-contract .val { color: #1D9E75; }
.dbt-contract .str { color: #EF9F27; }

/* ── Two-column layout ───────────────────────────── */
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 14px; }

/* ── Lineage chip row ────────────────────────────── */
.lineage-chips { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
.lm-chip {
    background: #13141a;
    border: 1px solid #1f2128;
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 11px;
    color: #5a5f6e;
    display: inline-flex;
    align-items: center;
    gap: 6px;
}
.lm-chip strong { color: #e2e4e9; font-weight: 500; }

/* ── Streamlit widget overrides ──────────────────── */
div[data-testid="stSelectbox"] label,
div[data-testid="stSelectbox"] p { font-size: 12px; color: #5a5f6e; }
div[data-testid="stSelectbox"] > div > div {
    background: #13141a !important;
    border-color: #1f2128 !important;
    color: #e2e4e9 !important;
    font-size: 13px !important;
}
div[data-testid="stButton"] > button {
    background: #13141a;
    border: 1px solid #2a2d38;
    color: #9aa0b2;
    font-size: 12px;
    font-weight: 500;
    border-radius: 6px;
    padding: 6px 14px;
}
div[data-testid="stButton"] > button:hover {
    background: #1a1b21;
    border-color: #3a3f4e;
    color: #e2e4e9;
}
.stButton.primary > button {
    background: #0a2a1e;
    border-color: #0F6E56;
    color: #1D9E75;
}
.stButton.danger > button {
    background: #2a0a0a;
    border-color: #A32D2D;
    color: #E24B4A;
}
</style>
"""

# ── Reusable HTML helpers ─────────────────────────────────────────────────────

def badge(text: str, kind: str = "complete") -> str:
    """Return a status badge span."""
    return f'<span class="badge badge-{kind}">{text}</span>'


def stat_card(label: str, value: str, sub: str = "", color: str = "") -> str:
    cls = f" {color}" if color else ""
    sub_html = f'<div class="ude-stat-sub">{sub}</div>' if sub else ""
    return f"""
<div class="ude-stat">
  <div class="ude-stat-label">{label}</div>
  <div class="ude-stat-value{cls}">{value}</div>
  {sub_html}
</div>"""


def field_row(name: str, dtype: str, constraint: str = "", nullable: bool = False, new: bool = False) -> str:
    if new:
        tag = f'<span class="field-new">new</span>'
    elif constraint:
        tag = f'<span class="field-constraint">{constraint}</span>'
    elif nullable:
        tag = '<span class="field-nullable">nullable</span>'
    else:
        tag = ""
    return f"""
<div class="field-row">
  <span class="field-name">{name}</span>
  <span class="field-type">{dtype}</span>
  {tag}
</div>"""


def section_label(text: str) -> str:
    return f'<div class="ude-section-label">{text}</div>'


def page_header(icon: str, title: str, subtitle: str = "") -> str:
    sub = f'<div class="ude-page-sub">{subtitle}</div>' if subtitle else ""
    return f"""
<div class="ude-page-header">
  <div class="ude-page-title">
    <span class="ude-page-icon">{icon}</span>{title}
  </div>
  {sub}
</div>"""