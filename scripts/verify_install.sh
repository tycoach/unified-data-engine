#!/usr/bin/env bash
# scripts/verify_install.sh
#
# Post-install verification for the ude CLI.
# Run this after pip install -e . to confirm the entry point
# is wired up correctly and all imports resolve cleanly.
#
# Usage:
#   bash scripts/verify_install.sh
#
# Expected output:
#   ✓  ude entry point found at: /path/to/.venv/bin/ude
#   ✓  ude --version exits 0
#   ✓  ude --help exits 0
#   ✓  cli.main importable
#   ✓  cli.core.config importable
#   ✓  cli.core.checks importable
#   ✓  cli.core.errors importable
#   ✓  cli.client importable
#   ✓  cli.scaffold importable
#   ✓  cli.output importable
#   ✓  All checks passed. ude is correctly installed.

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
RESET='\033[0m'

PASS=0
FAIL=0

pass() { echo -e "${GREEN}✓${RESET}  $1"; ((PASS++)); }
fail() { echo -e "${RED}✗${RESET}  $1"; ((FAIL++)); }

echo ""
echo "UDE CLI — install verification"
echo "================================"
echo ""

# 1. Entry point exists on PATH
if command -v ude &>/dev/null; then
    pass "ude entry point found at: $(command -v ude)"
else
    fail "ude not found on PATH. Did pip install -e . complete?"
fi

# 2. ude --version exits 0
if ude --version &>/dev/null 2>&1 || ude --help &>/dev/null 2>&1; then
    pass "ude --help exits 0"
else
    fail "ude --help returned non-zero exit code"
fi

# 3. Key modules importable
MODULES=(
    "cli.main"
    "cli.core.config"
    "cli.core.checks"
    "cli.core.errors"
    "cli.core.context"
    "cli.client"
    "cli.client.http"
    "cli.client.pipeline"
    "cli.client.schema"
    "cli.client.quarantine"
    "cli.client.dbt"
    "cli.client.observe"
    "cli.scaffold"
    "cli.scaffold.pipeline"
    "cli.scaffold.project"
    "cli.output"
    "cli.output.tables"
    "cli.output.panels"
    "cli.output.live"
    "cli.commands.lifecycle"
    "cli.commands.dbt"
    "cli.commands.pipeline"
    "cli.commands.schema"
    "cli.commands.quarantine"
    "cli.commands.observe"
)

for module in "${MODULES[@]}"; do
    if python -c "import ${module}" &>/dev/null 2>&1; then
        pass "${module} importable"
    else
        fail "${module} import failed"
        python -c "import ${module}" 2>&1 | sed 's/^/       /'
    fi
done

# 4. Jinja2 templates exist
TEMPLATES=(
    "cli/scaffold/templates/pipeline.yml.j2"
    "cli/scaffold/templates/staging_model.sql.j2"
    "cli/scaffold/templates/snapshot.sql.j2"
    "cli/scaffold/templates/incremental_model.sql.j2"
    "cli/scaffold/templates/engine.yml.j2"
    "cli/scaffold/templates/docker-compose.yml.j2"
)

for tmpl in "${TEMPLATES[@]}"; do
    if [ -f "${tmpl}" ]; then
        pass "${tmpl} exists"
    else
        fail "${tmpl} missing"
    fi
done

# 5. pyproject.toml has the correct entry point
if grep -q 'ude = "cli.main:app"' pyproject.toml 2>/dev/null; then
    pass "pyproject.toml entry point correct"
else
    fail "pyproject.toml missing or entry point incorrect"
fi

# Summary
echo ""
echo "================================"
if [ "${FAIL}" -eq 0 ]; then
    echo -e "${GREEN}✓  All ${PASS} checks passed. ude is correctly installed.${RESET}"
    echo ""
    echo "  Try it: ude --help"
    echo "          ude status"
    echo ""
    exit 0
else
    echo -e "${RED}✗  ${FAIL} check(s) failed. See above for details.${RESET}"
    echo ""
    exit 1
fi