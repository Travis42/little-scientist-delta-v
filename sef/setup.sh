#!/bin/bash
# setup.sh — Provisioning for a ProteinGym SEF infrastructure
#
# Sets up the core SEF architecture for a new experiment domain:
#   - Validates Python dependencies
#   - Verifies data files, database, and workspace are present
#   - Installs the systemd smoke watcher service
#   - Configures logrotate
#   - Runs validator sanity checks
#   - Runs a self-test (end-to-end smoke -> eval -> diagnostics validation)
#
# Usage:
#   bash scripts/setup.sh                          # default paths
#   bash scripts/setup.sh --self-test              # run self-test only
#   bash scripts/setup.sh --verify                 # verify without self-test
#
# Prerequisites:
#   - Project scripts already in place
#   - Data files downloaded under data/

set -euo pipefail

# ─── Configuration ──────────────────────────────────────────────
PROJECT_DIR="${PROTEINGYM_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
WORKSPACE_DIR="${WORKSPACE_DIR:-${PROJECT_DIR}/workspace}"
KUHN_WORKSPACE_DIR="${KUHN_WORKSPACE_DIR:-${PROJECT_DIR}/../kuhn-workspace}"
SERVICE_NAME="proteingym-smoke-watcher"
PYTHON_DEPS="numpy scipy"

# Source model scores (from ProteinGym benchmark download)
SCORES_DIR="${PROTEINGYM_SCORES_DIR:-${PROJECT_DIR}/data/model_scores}"

# Database path (built by build_proteingym_db.py from source scores)
DB_PATH="${PROTEINGYM_DB:-${PROJECT_DIR}/data/proteingym_data.db}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ok()   { echo -e "  ${GREEN}OK${NC} $1"; }
fail() { echo -e "  ${RED}FAIL${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }
section() { echo ""; echo "--- $1 ---"; }

# ─── Argument parsing ───
SELF_TEST_ONLY=false
VERIFY_ONLY=false
case "${1:-}" in
    --self-test) SELF_TEST_ONLY=true ;;
    --verify)    VERIFY_ONLY=true ;;
esac

echo "============================================"
echo "   ProteinGym SEF Provisioning"
echo "============================================"
echo ""
echo "PROJECT_DIR:      $PROJECT_DIR"
echo "WORKSPACE_DIR:    $WORKSPACE_DIR"
echo "KUHN_WORKSPACE:   $KUHN_WORKSPACE_DIR"
echo "DB_PATH:          $DB_PATH"
echo ""

ERRORS=0

# ─── 1. PYTHON DEPENDENCIES ────────────────────────────────────
if [[ "$SELF_TEST_ONLY" == false ]]; then
section "[1/9] Python Dependencies"
python3 --version || { fail "Python 3 not found"; exit 1; }
for pkg in $PYTHON_DEPS; do
  if python3 -c "import $pkg" 2>/dev/null; then
    ok "$pkg installed"
  else
    echo "  Installing $pkg..."
    pip3 install "$pkg" && ok "$pkg installed" || { fail "$pkg install failed"; ERRORS=$((ERRORS+1)); }
  fi
done
fi

# ─── 2. SCRIPTS ────────────────────────────────────────────────
if [[ "$SELF_TEST_ONLY" == false ]]; then
section "[2/9] Required Scripts"
SCRIPTS=(
  "scripts/proteingym_smoke.py"
  "scripts/proteingym_eval.py"
  "scripts/proteingym_validate_and_eval.sh"
  "scripts/smoke_test_watcher.py"
  "scripts/pg_common.py"
  "scripts/pg_kuhn_selector.py"
  "scripts/pg_preflight.py"
  "scripts/proteingym_data.py"
  "scripts/build_proteingym_db.py"
  "scripts/kuhn_handoff.py"
  "scripts/scientist_to_kuhn_handoff.py"
)
for s in "${SCRIPTS[@]}"; do
  path="${PROJECT_DIR}/${s}"
  if [[ -f "$path" ]]; then
    ok "$s"
  else
    fail "$s missing"
    ERRORS=$((ERRORS+1))
  fi
done
fi

# ─── 3. DATA FILES ─────────────────────────────────────────────
if [[ "$SELF_TEST_ONLY" == false ]]; then
section "[3/9] Data Files"
DATA_DIR="${PROJECT_DIR}/data"
DMS_DIR="${DATA_DIR}/DMS_ProteinGym_substitutions"
MSA_DIR="${DATA_DIR}/DMS_msa_files"
REF_FILE="${DATA_DIR}/DMS_substitutions.csv"

if [[ -f "$REF_FILE" ]]; then
  ok "DMS_substitutions.csv"
else
  fail "DMS_substitutions.csv missing at $REF_FILE"
  ERRORS=$((ERRORS+1))
fi

if [[ -d "$DMS_DIR" ]]; then
  CSV_COUNT=$(ls "$DMS_DIR"/*.csv 2>/dev/null | wc -l)
  if [[ "$CSV_COUNT" -ge 20 ]]; then
    ok "$CSV_COUNT DMS protein files"
  else
    fail "Expected >=20 DMS files, found $CSV_COUNT"
    ERRORS=$((ERRORS+1))
  fi
else
  fail "DMS data directory missing: $DMS_DIR"
  ERRORS=$((ERRORS+1))
fi

if [[ -d "$MSA_DIR" ]]; then
  MSA_COUNT=$(ls "$MSA_DIR"/*.a2m 2>/dev/null | wc -l)
  if [[ "$MSA_COUNT" -ge 15 ]]; then
    ok "$MSA_COUNT MSA files"
  else
    warn "Only $MSA_COUNT MSA files (some proteins may lack MSAs)"
  fi
else
  warn "MSA directory missing: $MSA_DIR (strategies will get msa=None)"
fi
fi

# ─── 4. DATABASE ───────────────────────────────────────────────
if [[ "$SELF_TEST_ONLY" == false ]]; then
section "[4/9] Database"
if [[ -f "$DB_PATH" ]]; then
  ok "proteingym_data.db exists"
  DB_CHECK=$(python3 -c "
import sqlite3, sys
db = sqlite3.connect('$DB_PATH')
tables = [r[0] for r in db.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
expected = {'protein_info', 'model_scores', 'residue_structure'}
missing = expected - set(tables)
if missing:
    print(f'MISSING_TABLES:{missing}')
    sys.exit(1)
cols = [r[1] for r in db.execute('PRAGMA table_info(model_scores)').fetchall()]
model_cols = ['venus_rem', 's3f_msa', 'esm2_15b', 'prosst_2048', 'gemme']
missing_cols = [c for c in model_cols if c not in cols]
if missing_cols:
    print(f'MISSING_COLS:{missing_cols}')
    sys.exit(1)
row_count = db.execute('SELECT COUNT(*) FROM model_scores').fetchone()[0]
if row_count == 0:
    print('EMPTY')
    sys.exit(1)
cols_all = [r[1] for r in db.execute('PRAGMA table_info(model_scores)').fetchall()]
if 'DMS_score' in cols_all or 'DMS_score_bin' in cols_all:
    print('LABEL_LEAKAGE')
    sys.exit(1)
print(f'OK:{row_count}')
db.close()
" 2>&1) || true
  if echo "$DB_CHECK" | grep -q "^OK:"; then
    ROWS=$(echo "$DB_CHECK" | sed 's/OK://')
    ok "DB schema valid ($ROWS rows in model_scores)"
  elif echo "$DB_CHECK" | grep -q "LABEL_LEAKAGE"; then
    fail "DMS_score found in model_scores — label leakage risk!"
    ERRORS=$((ERRORS+1))
  elif echo "$DB_CHECK" | grep -q "MISSING"; then
    fail "DB schema incomplete: $DB_CHECK"
    ERRORS=$((ERRORS+1))
  else
    fail "DB validation failed: $DB_CHECK"
    ERRORS=$((ERRORS+1))
  fi
else
  fail "proteingym_data.db missing at $DB_PATH"
  echo "  Build it: python3 scripts/build_proteingym_db.py"
  echo "  Requires source scores in: $SCORES_DIR"
  ERRORS=$((ERRORS+1))
fi

if [[ -d "$SCORES_DIR" ]]; then
  SCORE_COUNT=$(ls "$SCORES_DIR"/*.csv 2>/dev/null | wc -l)
  if [[ "$SCORE_COUNT" -ge 100 ]]; then
    ok "$SCORE_COUNT source score files available for DB rebuild"
  else
    warn "Only $SCORE_COUNT source score files in $SCORES_DIR"
  fi
else
  warn "Source scores directory not found: $SCORES_DIR"
  echo "  Needed for: python3 scripts/build_proteingym_db.py"
fi
fi

# ─── 5. WORKSPACE FILES ────────────────────────────────────────
if [[ "$SELF_TEST_ONLY" == false ]]; then
section "[5/9] Workspace Files"
WS_FILES=(
  "AGENT_PROMPT.md"
  "best_so_far_strategy.py"
  "staging_strategy.py"
  "history.jsonl"
)
for f in "${WS_FILES[@]}"; do
  path="${WORKSPACE_DIR}/${f}"
  if [[ -f "$path" && -s "$path" ]]; then
    ok "$f"
  elif [[ -f "$path" ]]; then
    warn "$f exists but is empty"
  else
    fail "$f missing"
    ERRORS=$((ERRORS+1))
  fi
done

if [[ -f "${WORKSPACE_DIR}/all_time_best.txt" ]]; then
  BEST=$(cat "${WORKSPACE_DIR}/all_time_best.txt")
  ok "all_time_best.txt: $BEST"
else
  warn "all_time_best.txt missing (validator will use 0.0 as baseline)"
fi
fi

# ─── 6. KUHN WORKSPACE ─────────────────────────────────────────
if [[ "$SELF_TEST_ONLY" == false ]]; then
section "[6/9] Kuhn Workspace"
KUHN_REQUIRED=(
  "AGENTS.md"
  "best_so_far_strategy.py"
  "history.jsonl"
  "KUHN_STATE.json"
  "KUHN_INJECTION.json"
)
for kf in "${KUHN_REQUIRED[@]}"; do
  path="${KUHN_WORKSPACE_DIR}/${kf}"
  if [[ -f "$path" ]]; then
    ok "Kuhn: ${kf}"
  else
    warn "Kuhn workspace missing: ${kf}"
  fi
done
fi

# ─── 7. SYSTEMD SERVICE ────────────────────────────────────────
if [[ "$SELF_TEST_ONLY" == false ]]; then
section "[7/9] Systemd Service"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
  systemctl stop "$SERVICE_NAME"
  echo "  Stopped existing service"
fi

mkdir -p "${PROJECT_DIR}/logs"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=ProteinGym Smoke Test Watcher
After=network.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
Environment=HOME=/root
ExecStart=/usr/bin/python3 ${PROJECT_DIR}/scripts/smoke_test_watcher.py
Restart=always
RestartSec=10
StandardOutput=append:${PROJECT_DIR}/logs/smoke_watcher.log
StandardError=append:${PROJECT_DIR}/logs/smoke_watcher.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
ok "Service installed and enabled (not started yet)"

cat > "/etc/logrotate.d/${SERVICE_NAME}" << EOF
${PROJECT_DIR}/logs/smoke_watcher.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    copytruncate
}
EOF
ok "Logrotate configured (daily, 7-day retention)"
fi

# ─── 8. VALIDATOR SANITY CHECKS ────────────────────────────────
section "[8/9] Validator Sanity Checks"
VALIDATOR="${PROJECT_DIR}/scripts/proteingym_validate_and_eval.sh"
EVAL_SCRIPT="${PROJECT_DIR}/scripts/proteingym_eval.py"
WATCHER="${PROJECT_DIR}/scripts/smoke_test_watcher.py"

if grep -q "rejection_threshold" "$VALIDATOR" 2>/dev/null; then
  ok "Adaptive delta-based handoff present"
else
  warn "Adaptive handoff logic not found in validator"
fi

if grep -q "staging_eval_details.json" "$EVAL_SCRIPT" 2>/dev/null; then
  fail "Eval script still writes staging_eval_details.json to disk (should only use stdout)"
  ERRORS=$((ERRORS+1))
else
  ok "Eval script outputs JSON to stdout only"
fi

if ! grep -q "write_diagnostics" "$VALIDATOR" 2>/dev/null; then
  fail "Validator doesn't call write_diagnostics()"
  ERRORS=$((ERRORS+1))
else
  ok "Validator writes diagnostics"
fi

S2K_SCRIPT="${PROJECT_DIR}/scripts/scientist_to_kuhn_handoff.py"
if [[ -f "$S2K_SCRIPT" ]]; then
  ok "scientist_to_kuhn_handoff.py present"
else
  fail "scientist_to_kuhn_handoff.py missing"
  ERRORS=$((ERRORS+1))
fi

if grep -q "kuhn-workspace" "$WATCHER" 2>/dev/null; then
  ok "Watcher polls both scientist and Kuhn workspaces"
else
  warn "Watcher may not be polling the Kuhn workspace"
fi

echo "  Running preflight timing check..."
PREFLIGHT_OUT=$(python3 "${PROJECT_DIR}/scripts/pg_preflight.py" 2>&1) || true
if echo "$PREFLIGHT_OUT" | grep -qE "^[[:space:]]*\[FAIL\].*CRITICAL"; then
  fail "Preflight found critical timing issues"
  echo "$PREFLIGHT_OUT" | grep "\[FAIL\]" | sed 's/^/    /'
  ERRORS=$((ERRORS+1))
elif echo "$PREFLIGHT_OUT" | grep -q "warning"; then
  warn "Preflight passed with warnings (non-critical)"
else
  ok "Preflight timing constraints OK"
fi

if python3 -c "import json; json.load(open('${PROJECT_DIR}/config/timings.json'))" 2>/dev/null; then
  ok "config/timings.json is valid JSON"
else
  fail "config/timings.json is missing or invalid"
  ERRORS=$((ERRORS+1))
fi

# ─── 9. SELF-TEST ──────────────────────────────────────────────
section "[9/9] Self-Test (end-to-end smoke -> eval -> diagnostics)"

if [[ "$VERIFY_ONLY" == true ]]; then
  echo "  Skipped (--verify mode)"
else
  systemctl start "$SERVICE_NAME" 2>/dev/null || true
  sleep 2
  if systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "Watcher service running"
  else
    fail "Watcher service failed to start"
    ERRORS=$((ERRORS+1))
  fi

  ROGUE_PIDS=$(pgrep -f "proteingym.*smoke_test_watcher" | while read pid; do
    SYSTEMD_PID=$(systemctl show proteingym-smoke-watcher -p MainPID 2>/dev/null | cut -d= -f2)
    if [[ "$pid" != "$SYSTEMD_PID" && "$pid" != "$$" ]]; then
      echo "$pid"
    fi
  done)
  if [[ -n "$ROGUE_PIDS" ]]; then
    for pid in $ROGUE_PIDS; do
      kill "$pid" 2>/dev/null
      warn "Killed rogue watcher PID $pid"
    done
  else
    ok "No rogue watcher processes"
  fi

  echo "  Running eval on current best_so_far_strategy.py..."
  EVAL_OUTPUT=$(cd "$PROJECT_DIR" && python3 -u scripts/proteingym_eval.py --dir workspace 2>&1) || {
    fail "Eval script failed:"
    echo "$EVAL_OUTPUT" | tail -5 | sed 's/^/    /'
    ERRORS=$((ERRORS+1))
    EVAL_OUTPUT=""
  }

  if [[ -n "$EVAL_OUTPUT" ]] && echo "$EVAL_OUTPUT" | grep -q '"score"'; then
    SCORE=$(echo "$EVAL_OUTPUT" | python3 -c "import sys,json; lines=[l for l in sys.stdin if l.strip().startswith('{')]; print(json.loads(lines[-1])['score'])" 2>/dev/null || echo "?")
    ok "Eval produced score: $SCORE"
  else
    fail "Eval didn't produce valid JSON output"
    ERRORS=$((ERRORS+1))
  fi
fi

# ─── Summary ───
echo ""
if [[ $ERRORS -gt 0 ]]; then
  echo -e "${RED}============================================"
  echo -e "   $ERRORS ERROR(S) — FIX BEFORE PROCEEDING"
  echo -e "${NC}============================================"
  exit 1
fi

echo "============================================"
echo "   All checks passed"
echo "============================================"
echo ""
echo "Watcher service: $SERVICE_NAME (running)"
if [[ -n "${SCORE:-}" ]]; then
  echo "Eval score on current best: $SCORE"
fi
