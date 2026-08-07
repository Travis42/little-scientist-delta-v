#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# proteingym_validate_and_eval.sh — ProteinGym SEF Validator + Evaluator
#
# Validates agent-produced strategy code before evaluation.
# Usage: bash scripts/proteingym_validate_and_eval.sh
#
# Phases:
#   1. Existence — check staging_strategy.py exists
#   2. Validation — size, syntax, signature, forbidden patterns, allowed imports
#   3. Smoke test gate — verify smoke test was run and passed
#   4. Promote & Evaluate — copy to strategy.py, run eval, parse score
#   5. Commit or Revert — verification pass, history tracking
#   6. Report — notification on accepted/false_positive/eval_crash
#
# All diagnostic output goes to stderr. Score line goes to stdout.
# ---------------------------------------------------------------------------
set -euo pipefail

# ── paths ──────────────────────────────────────────────────────────────────
# Allow override via environment for Kuhn workspace or other tracks
PROJECT_ROOT="${PROTEINGYM_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TRACK_DIR="${PG_TRACK_DIR:-${PROJECT_ROOT}/workspace}"
# Eval active dir — relative to track to avoid collision between scientist/kuhn
TRACK_NAME=$(basename "${TRACK_DIR}")
EVAL_ACTIVE_DIR="${PROJECT_ROOT}/eval/${TRACK_NAME}"
LOCK_FILE="${TRACK_DIR}/.validator_lock"
STAGED="${TRACK_DIR}/staging_strategy.py"
STRATEGY="${EVAL_ACTIVE_DIR}/strategy.py"
BEST_SO_FAR="${TRACK_DIR}/best_so_far_strategy.py"
LAST_ATTEMPT="${TRACK_DIR}/last_attempt_strategy.py"
HISTORY="${TRACK_DIR}/history.jsonl"
EVAL_SCRIPT="${PROJECT_ROOT}/scripts/proteingym_eval.py"
REPO_ROOT="${PROJECT_ROOT}"
# Integrated data DB (model predictions + structure).
PROTEINGYM_DB_PATH="${PROTEINGYM_DB:-${PROJECT_ROOT}/data/proteingym_data.db}"
if [[ ! -f "$PROTEINGYM_DB_PATH" && -f "${PROJECT_ROOT}/data/proteingym_data.db" ]]; then
  PROTEINGYM_DB_PATH="${PROJECT_ROOT}/data/proteingym_data.db"
fi
SCRIPTS_DIR="${PROJECT_ROOT}/scripts"
HYPOTHESIS_FILE="${TRACK_DIR}/staging_hypothesis.txt"
PLAN_FILE="${TRACK_DIR}/staging_plan.md"
PREDICTION_FILE="${TRACK_DIR}/staging_prediction.json"
SMOKE_PASS_FILE="${TRACK_DIR}/staging_smoke_passed.json"
SMOKE_TRIGGER_FILE="${TRACK_DIR}/staging_smoke_trigger.json"
SMOKE_RESULT_FILE="${TRACK_DIR}/staging_smoke_result.json"

# ── helpers ────────────────────────────────────────────────────────────────
log()  { printf "[pg-sef] %s\n" "$*" >&2; }

# Load timing constants from config
TIMINGS_FILE="${REPO_ROOT}/config/timings.json"
if [[ -f "$TIMINGS_FILE" ]]; then
  STALE_LOCK_SECONDS=$(python3 -c "import json; print(json.load(open('$TIMINGS_FILE')).get('validator_stale_lock_seconds', 600))")
  SMOKE_PASS_MAX_AGE_MIN=$(python3 -c "import json; print(json.load(open('$TIMINGS_FILE')).get('smoke_pass_max_age_minutes', 90))")
else
  STALE_LOCK_SECONDS=600
  SMOKE_PASS_MAX_AGE_MIN=90
fi
die()  { printf "[pg-sef] ERROR: %s\n" "$*" >&2; exit 1; }

# Temp file for eval output
EVAL_OUTPUT_FILE=""
cleanup_on_exit() {
  [[ -n "${EVAL_OUTPUT_FILE}" && -f "${EVAL_OUTPUT_FILE}" ]] && rm -f "${EVAL_OUTPUT_FILE}" || true
  [[ -d "${TRACK_DIR}/.validator_lock_dir" ]] && rmdir "${TRACK_DIR}/.validator_lock_dir" 2>/dev/null || true
  [[ -f "${TRACK_DIR}/.validator_lock" ]] && rm -f "${TRACK_DIR}/.validator_lock" 2>/dev/null || true
}
trap cleanup_on_exit EXIT

mkdir -p "${EVAL_ACTIVE_DIR}"
mkdir -p "$(dirname "$HISTORY")"

# ── lock check (atomic via mkdir) ──────────────────────────────────────────
LOCK_DIR="${TRACK_DIR}/.validator_lock_dir"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  LOCK_AGE=$(( $(date +%s) - $(stat -c %Y "$LOCK_DIR") ))
  VALIDATOR_RUNNING=$(pgrep -f "proteingym_validate_and_eval.*$(basename "$TRACK_DIR")" | head -1)
  if [[ -z "$VALIDATOR_RUNNING" ]]; then
    log "Lock exists but no validator process found — removing orphaned lock ($LOCK_AGE s old)"
    rm -rf "$LOCK_DIR" 2>/dev/null
    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
      log "Could not acquire lock after cleanup, exiting"
      exit 0
    fi
  elif [[ $LOCK_AGE -gt $STALE_LOCK_SECONDS ]]; then
    log "Stale lock ($LOCK_AGE s old, process $VALIDATOR_RUNNING may be hung), removing"
    kill "$VALIDATOR_RUNNING" 2>/dev/null || true
    rm -rf "$LOCK_DIR" 2>/dev/null
    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
      log "Validator already running, exiting"
      exit 0
    fi
  else
    log "Validator already running (pid $VALIDATOR_RUNNING, $LOCK_AGE s), exiting"
    exit 0
  fi
fi

# ── helper functions ──────────────────────────────────────────────────────

append_history() {
  local entry="$1"
  mkdir -p "$(dirname "$HISTORY")"
  echo "$entry" >> "$HISTORY"
}

revert_strategy() {
  if [[ -f "$STRATEGY" ]]; then
    git -C "$REPO_ROOT" checkout -- "${STRATEGY}" 2>/dev/null || true
    if [[ -f "$STRATEGY" ]]; then
      cp "$STRATEGY" "$STAGED" 2>/dev/null || true
    fi
  fi
}

log_validation_fail() {
  local reason="$1"
  local matched="${2:-}"
  local detail="${3:-}"

  export _SEF_FAIL_DETAIL="$detail"
  local output
  output=$(python3 -u - "$HISTORY" "$TRACK_DIR" "$reason" "$matched" << 'PYEOF'
import json, sys, os, datetime
history_path, track_dir = sys.argv[1], sys.argv[2]
reason = sys.argv[3]
matched = sys.argv[4] if len(sys.argv) > 4 else ""
detail = os.environ.get("_SEF_FAIL_DETAIL", "")

run_num = 0
if os.path.isfile(history_path):
    with open(history_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try: run_num = max(run_num, json.loads(line).get("run", 0))
                except: pass
run_num += 1

hypothesis = None
hyp_path = os.path.join(track_dir, "staging_hypothesis.txt")
if os.path.isfile(hyp_path):
    with open(hyp_path) as f:
        hypothesis = f.read().strip()[:2000]

prediction = None
pred_path = os.path.join(track_dir, "staging_prediction.json")
if os.path.isfile(pred_path):
    try:
        with open(pred_path) as f:
            prediction = json.load(f)
    except:
        prediction = None

ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
entry = {"run": run_num, "score": None, "best_score": None, "improved": False,
         "verdict": "validation_failed", "reason": reason, "timestamp": ts}
if matched:
    entry["matched_pattern"] = matched
if detail:
    entry["error_detail"] = detail[:2000]
if hypothesis:
    entry["hypothesis"] = hypothesis
if prediction:
    entry["prediction_low"] = prediction.get("prediction_low")
    entry["prediction_high"] = prediction.get("prediction_high")
print(f"__RUN__{run_num}")
print(json.dumps(entry))
PYEOF
)

  local payload
  payload=$(echo "$output" | grep -v "^__RUN__")
  if [[ -n "$payload" ]]; then
    append_history "$payload"
  fi
}

# ── Phase 1: Existence ────────────────────────────────────────────────────
log "Phase 1: Checking for ${STAGED}"
if [[ ! -f "$STAGED" ]]; then
  log "staging_strategy.py not found, exiting"
  exit 0
fi

if [[ ! -s "$STAGED" ]]; then
  log "staging_strategy.py is empty, exiting"
  exit 0
fi

log "Found staging strategy ($(wc -c < "$STAGED") bytes)"

# ── Phase 2: Validation ────────────────────────────────────────────────────
log "Phase 2: Validating ${STAGED}"

# 2a. Size check (< 200 KiB)
FILE_SIZE=$(stat -c%s "$STAGED" 2>/dev/null || echo 0)
if [[ "$FILE_SIZE" -ge 204800 ]]; then
  log "2a FAIL: file is ${FILE_SIZE} bytes (max 204800)"
  log_validation_fail "file_too_large" "" "File size ${FILE_SIZE} bytes exceeds 204800 limit"
  exit 1
fi
log "2a OK: ${FILE_SIZE} bytes"

# 2b. Python syntax check
if ! python3 -c "compile(open('${STAGED}').read(), 'strategy.py', 'exec')" 2>/dev/null; then
  log "2b FAIL: syntax error"
  SYNTAX_ERR=$(python3 -c "compile(open('${STAGED}').read(), 'strategy.py', 'exec')" 2>&1 | tail -5)
  log_validation_fail "syntax_error" "" "Python syntax error: ${SYNTAX_ERR}"
  exit 1
fi
log "2b OK: syntax valid"

# 2c. Function signature check
EXPECTED_SIG="def score_mutations("
if ! grep -q "$EXPECTED_SIG" "$STAGED" 2>/dev/null; then
  log "2c FAIL: expected function signature '${EXPECTED_SIG}' not found"
  log_validation_fail "missing_signature" "" "Expected signature '${EXPECTED_SIG}' not found in staging_strategy.py"
  exit 1
fi
log "2c OK: found '${EXPECTED_SIG}'"

# 2d. Forbidden pattern check
FORBIDDEN=(
  'import subprocess'
  'import os'
  'import sys'
  'import shutil'
  'import socket'
  'import http'
  'import urllib'
  'import requests'
  '\.system\('
  '\.popen\('
  'subprocess'
  '\beval\('
  'exec\('
  '\bcompile\('
  '__import__'
  '\bopen\('
  'os\.path'
  'os\.system'
  'os\.popen'
  '__class__'
  '__bases__'
  '__subclasses__'
  '__builtins__'
  'globals\('
  'locals\('
  'getattr\('
  'setattr\('
  'delattr\('
  'hasattr\('
  '\btype\('
  'input\('
  'breakpoint\('
  'pdb\.'
  'ipdb\.'
)

FORBIDDEN_RE=$(printf '|%s' "${FORBIDDEN[@]}" | tail -c +2)
MATCHED=$(grep -iE "${FORBIDDEN_RE}" "$STAGED" || true)

if [[ -n "$MATCHED" ]]; then
  FIRST_MATCH=$(echo "$MATCHED" | head -1)
  log "2d FAIL: forbidden pattern found: ${FIRST_MATCH}"
  log_validation_fail "forbidden_pattern" "$FIRST_MATCH" "Forbidden pattern: ${FIRST_MATCH}"
  exit 1
fi
log "2d OK: no forbidden patterns"

# 2e. Allowed imports check (blacklist mode)
IMPORTED=$(python3 -c "
import ast, sys
try:
    with open('${STAGED}') as f:
        tree = ast.parse(f.read())
except SyntaxError:
    print('PARSE_ERROR')
    sys.exit(1)

modules = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        for alias in node.names:
            modules.add(alias.name.split('.')[0])
    elif isinstance(node, ast.ImportFrom):
        if node.module:
            modules.add(node.module.split('.')[0])

for m in sorted(modules):
    print(m)
" 2>/dev/null)

if [[ "$IMPORTED" == "PARSE_ERROR" ]]; then
  log "2e FAIL: could not parse imports"
  log_validation_fail "import_parse_error" "" "Could not parse Python imports"
  exit 1
fi

FORBIDDEN_MODULES="subprocess os sys shutil socket http urllib requests"
DISALLOWED=""
for mod in $IMPORTED; do
  if echo "$FORBIDDEN_MODULES" | grep -qw "$mod"; then
    DISALLOWED="${DISALLOWED}${mod} "
  fi
done

if [[ -n "$DISALLOWED" ]]; then
  log "2e FAIL: forbidden imports: ${DISALLOWED}"
  log_validation_fail "forbidden_imports" "" "Forbidden imports: ${DISALLOWED}"
  exit 1
fi
log "2e OK: imports allowed (blacklist mode)"

log "Phase 2 complete: all validation checks passed"

# ── Phase 2b: Code verification compliance ────────────────────────────────
log "Phase 2b: Code verification compliance"

if [[ -f "${TRACK_DIR}/staging_kuhn_bypass" ]]; then
    log "2b SKIP: kuhn bypass marker detected"
elif [[ ! -f "${TRACK_DIR}/staging_code_reviewed" ]]; then
    log "2b FAIL: code review not completed (staging_code_reviewed missing)"
    log_validation_fail "code_review_missing" "" \
        "Code review not completed. Fill in Section 7 of staging_worksheet.md and write staging_code_reviewed."
    exit 1
fi

if [[ ! -f "${TRACK_DIR}/staging_kuhn_bypass" ]] && ! grep -q "## 7. Code Verification" "${TRACK_DIR}/staging_worksheet.md" 2>/dev/null; then
    log "2b FAIL: Code Verification section missing from worksheet"
    log_validation_fail "code_review_section_missing" "" \
        "Section 7 (Code Verification) missing from staging_worksheet.md."
    exit 1
fi
if [[ ! -f "${TRACK_DIR}/staging_kuhn_bypass" ]]; then
    log "2b OK: code review completed"
fi

# ── Read best_score from history ───────────────────────────────────────────
BEST_SCORE="0.0"
if [[ -f "$HISTORY" ]]; then
  BEST_SCORE=$(python3 -c "
import json, sys
best = 0.0
for line in open('$HISTORY'):
    try:
        obj = json.loads(line.strip())
        if obj.get('verdict') == 'false_positive':
            continue
        s = obj.get('best_score') or obj.get('score')
        if s is not None and isinstance(s, (int, float)):
            best = max(best, float(s))
    except:
        pass
print(best)
" 2>/dev/null || echo "0.0")
fi

# ── Phase 3: Smoke test gate ─────────────────────────────────────────────
log "Phase 3: Smoke test gate"

if [[ ! -f "$SMOKE_PASS_FILE" ]]; then
  if [[ ! -f "$SMOKE_RESULT_FILE" ]]; then
    log "3 FAIL: smoke test not run (no trigger/result found)"
    log_validation_fail "smoke_test_not_run" "" "Smoke test must be triggered before submitting."
    exit 1
  fi
  log "3 FAIL: smoke test had crashes (no pass marker)"
  log_validation_fail "smoke_test_crashed" "" "Smoke test had crashes. Fix and re-trigger."
  exit 1
fi

SMOKE_AGE=$(( $(date +%s) - $(python3 -c "import json; print(int(json.load(open('$SMOKE_PASS_FILE'))['timestamp']))" 2>/dev/null || echo 0) ))
if [[ "$SMOKE_AGE" -gt 5400 ]]; then
  log "3 FAIL: smoke test result is stale (${SMOKE_AGE}s old)"
  log_validation_fail "smoke_test_stale" "" "Smoke test result is stale (${SMOKE_AGE}s old). Re-trigger smoke test."
  rm -f "$SMOKE_PASS_FILE" "$SMOKE_RESULT_FILE" "$SMOKE_TRIGGER_FILE"
  exit 1
fi
log "3 OK: smoke test passed (${SMOKE_AGE}s ago)"

# ── Phase 3.5: Data DB health check ───────────────────────────────────────
log "Phase 3.5: Data DB health check (${PROTEINGYM_DB_PATH})"
if [[ ! -f "$PROTEINGYM_DB_PATH" ]]; then
  log "3.5 FAIL: proteingym_data.db not found at ${PROTEINGYM_DB_PATH}"
  log_validation_fail "data_db_missing" "" \
      "proteingym_data.db not found at ${PROTEINGYM_DB_PATH}. Run scripts/build_proteingym_db.py."
  exit 1
fi
if ! DB_ROW_COUNT=$(sqlite3 "$PROTEINGYM_DB_PATH" "SELECT COUNT(*) FROM model_scores" 2>/dev/null); then
  log "3.5 FAIL: model_scores query failed (DB locked or corrupt)"
  log_validation_fail "data_db_corrupt" "" \
      "proteingym_data.db at ${PROTEINGYM_DB_PATH} is locked or corrupt. Rebuild with scripts/build_proteingym_db.py."
  exit 1
fi
if [[ "$DB_ROW_COUNT" -lt 1000000 ]]; then
  log "3.5 FAIL: model_scores has only ${DB_ROW_COUNT} rows (expected ~2.5M)"
  log_validation_fail "data_db_incomplete" "" \
      "proteingym_data.db model_scores has ${DB_ROW_COUNT} rows (expected ~2.5M). Rebuild with scripts/build_proteingym_db.py."
  exit 1
fi
log "3.5 OK: DB healthy (${DB_ROW_COUNT} model_scores rows)"

export PROTEINGYM_DB="$PROTEINGYM_DB_PATH"
export PYTHONPATH="${SCRIPTS_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
log "3.5 OK: PROTEINGYM_DB=${PROTEINGYM_DB}, PYTHONPATH includes scripts/"

# ── Phase 4: Promote & Evaluate ────────────────────────────────────────────
log "Phase 4: Promoting staged -> strategy and evaluating"

touch "$LOCK_FILE"

cp "$STAGED" "$STRATEGY"
chmod 444 "$STRATEGY"
log "Copied staging_strategy.py -> strategy.py"

log "Running eval: ${EVAL_SCRIPT} --dir ${TRACK_DIR}"
EVAL_OUTPUT_FILE=$(mktemp /tmp/pg_sef_eval_XXXXXX.txt)
EVAL_EXIT=0
python3 -u "$EVAL_SCRIPT" --dir "$TRACK_DIR" --workers 2 > "$EVAL_OUTPUT_FILE" 2>&1 || EVAL_EXIT=$?
EVAL_OUTPUT=$(cat "$EVAL_OUTPUT_FILE")

if [[ $EVAL_EXIT -ne 0 ]]; then
  log "4 FAIL: eval exited with code ${EVAL_EXIT}"
  log "Eval output:\n${EVAL_OUTPUT}" >&2
  EVAL_DETAIL="Eval exited with code ${EVAL_EXIT}. Output (last 1500 chars): ${EVAL_OUTPUT: -1500}"
  log_validation_fail "eval_crash" "" "$EVAL_DETAIL"
  rm -f "$LOCK_FILE"
  exit 1
fi

log "Eval completed successfully"

# Parse score
PARSED_SCORE=$(python3 - "$EVAL_OUTPUT_FILE" << 'PYEOF'
import sys, json, re

eval_file = sys.argv[1]
with open(eval_file) as f:
    output = f.read()

score = None

for line in reversed(output.strip().splitlines()):
    line = line.strip()
    if not line.startswith('{'):
        continue
    try:
        obj = json.loads(line)
        if isinstance(obj, dict) and 'score' in obj:
            score = obj['score']
            break
    except (json.JSONDecodeError, KeyError):
        continue

if score is None:
    m = re.search(r'"score"\s*:\s*([0-9eE.+-]+)', output)
    if m:
        score = float(m.group(1))

if score is None:
    print('ERROR_NO_SCORE')
    sys.exit(1)

print(score)
PYEOF
) || {
  log "4 FAIL: could not parse score from eval output"
  log_validation_fail "score_parse_error" "" "Could not parse score"
  rm -f "$LOCK_FILE"
  exit 1
}

if [[ "$PARSED_SCORE" == "ERROR_NO_SCORE" ]]; then
  log "4 FAIL: no score found in eval output"
  log_validation_fail "no_score_in_output" "" "No score in eval output"
  rm -f "$LOCK_FILE"
  exit 1
fi

log "Parsed score: ${PARSED_SCORE}"
log "Best score so far: ${BEST_SCORE}"

# ── Phase 5: Commit or Revert ──────────────────────────────────────────────
TRACK_DIR_E="${TRACK_DIR}" \
STRATEGY_E="${STRATEGY}" \
STAGED_E="${STAGED}" \
BEST_SO_FAR_E="${BEST_SO_FAR}" \
LAST_ATTEMPT_E="${LAST_ATTEMPT}" \
EVAL_SCRIPT_E="${EVAL_SCRIPT}" \
REPO_ROOT_E="${REPO_ROOT}" \
HISTORY_E="${HISTORY}" \
HYPOTHESIS_E="${HYPOTHESIS_FILE}" \
PLAN_E="${PLAN_FILE}" \
PREDICTION_E="${PREDICTION_FILE}" \
SMOKE_PASS_E="${SMOKE_PASS_FILE}" \
PARSED_SCORE_E="${PARSED_SCORE}" \
BEST_SCORE_E="${BEST_SCORE}" \
TRACK_E="${TRACK_NAME}" \
EVAL_OUTPUT_FILE_E="${EVAL_OUTPUT_FILE}" \
python3 -u << 'PYEOF'
import json, subprocess, datetime, os, sys, re, shutil

track_dir       = os.environ["TRACK_DIR_E"]
strategy_path   = os.environ["STRATEGY_E"]
staged_path     = os.environ["STAGED_E"]
best_so_far_path = os.environ["BEST_SO_FAR_E"]
last_attempt_path = os.environ["LAST_ATTEMPT_E"]
eval_script     = os.environ["EVAL_SCRIPT_E"]
repo_root       = os.environ["REPO_ROOT_E"]
history_path    = os.environ["HISTORY_E"]
hypothesis_file = os.environ["HYPOTHESIS_E"]
plan_file       = os.environ["PLAN_E"]
parsed_score    = float(os.environ["PARSED_SCORE_E"])
best_score      = float(os.environ["BEST_SCORE_E"])
track           = os.environ["TRACK_E"]
eval_output_file = os.environ["EVAL_OUTPUT_FILE_E"]
smoke_pass_file = os.environ.get("SMOKE_PASS_E", "")

ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

run_num = 0
if os.path.exists(history_path):
    try:
        with open(history_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    r = obj.get("run", 0)
                    if r is not None:
                        run_num = max(run_num, r)
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
    except OSError:
        pass
run_num += 1

hypothesis = ""
if os.path.exists(hypothesis_file):
    try:
        with open(hypothesis_file) as f:
            hypothesis = f.read().strip()[:2000]
    except OSError:
        hypothesis = ""

prediction_low = None
prediction_high = None
prediction_file = os.environ.get("PREDICTION_E", "")
if os.path.exists(prediction_file):
    try:
        with open(prediction_file) as f:
            pred = json.load(f)
            prediction_low = pred.get("prediction_low")
            prediction_high = pred.get("prediction_high")
    except (OSError, json.JSONDecodeError):
        pass

plan = ""
if os.path.exists(plan_file):
    try:
        with open(plan_file) as f:
            plan = f.read().strip()[:3000]
    except OSError:
        plan = ""

blockers_file = os.path.join(track_dir, "staging_blockers.md")
blockers = ""
if os.path.exists(blockers_file):
    try:
        with open(blockers_file) as f:
            blockers = f.read().strip()[:1000]
    except OSError:
        blockers = ""

details = {}
try:
    with open(eval_output_file) as f:
        eval_output_text = f.read()
    for line in reversed(eval_output_text.strip().splitlines()):
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and 'score' in obj:
                details = obj
                break
        except (json.JSONDecodeError, KeyError):
            continue
except (OSError, IOError):
    details = {}

improved = parsed_score > best_score
new_best = max(parsed_score, best_score)

try:
    sys.path.insert(0, os.path.join(repo_root, "scripts"))
    from pg_common import update_all_time_best
    update_all_time_best(new_best)
except Exception:
    pass
score_str = f"{parsed_score:.6f}"
best_str  = f"{best_score:.6f}"
score_delta = parsed_score - best_score

protein_details = details.get("details", {}) if isinstance(details, dict) else {}
if not protein_details and isinstance(details, dict):
    protein_details = {k: v for k, v in details.items() if isinstance(v, dict) and "spearman" in v}

prev_proteins = {}
if os.path.exists(history_path):
    try:
        prev_entries = []
        with open(history_path) as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try: prev_entries.append(json.loads(line))
                except: continue
        for pe in reversed(prev_entries):
            if pe.get("top_improved"):
                for item in pe["top_improved"]:
                    prev_proteins[item["protein"]] = item["spearman"]
                for item in pe.get("top_regressed", []):
                    prev_proteins[item["protein"]] = item["spearman"]
                break
            elif pe.get("details", {}).get("details"):
                old_d = pe["details"]["details"]
                if isinstance(old_d, dict):
                    prev_proteins = {k: v.get("spearman", 0) for k, v in old_d.items()}
                break
    except: pass

protein_deltas = []
for pid, v in protein_details.items():
    cur_sp = v.get("spearman", 0)
    prev_sp = prev_proteins.get(pid)
    if prev_sp is not None:
        protein_deltas.append((pid, cur_sp, cur_sp - prev_sp))

top_improved = [{"protein": p, "spearman": s, "delta": d}
                for p, s, d in sorted(protein_deltas, key=lambda x: x[2], reverse=True)[:5] if d > 0]
top_regressed = [{"protein": p, "spearman": s, "delta": d}
                 for p, s, d in sorted(protein_deltas, key=lambda x: x[2])[:5] if d < 0]

entry = {
    "run": run_num,
    "score": parsed_score,
    "best_score": new_best,
    "score_delta": round(score_delta, 6),
    "improved": improved,
    "best_hash": __import__('hashlib').md5(open(best_so_far_path, 'rb').read()).hexdigest()[:8],
    "hypothesis": hypothesis,
    "plan": plan,
    "blockers": blockers,
    "top_improved": top_improved,
    "top_regressed": top_regressed,
    "prediction_low": prediction_low,
    "prediction_high": prediction_high,
    "timestamp": ts,
}

def write_diagnostics(details_dict):
    details = details_dict.get("details", {})
    if not details:
        details = {k: v for k, v in details_dict.items() if isinstance(v, dict) and 'spearman' in v}
    if not details:
        return

    total = len(details)
    spearmans = {k: v.get('spearman', 0.0) for k, v in details.items()}
    sp_vals = list(spearmans.values())
    sp_avg = sum(sp_vals) / total if total else 0
    sp_sorted = sorted(sp_vals)
    sp_low = sp_sorted[:max(1, total // 4)]
    sp_low_avg = sum(sp_low) / len(sp_low) if sp_low else 0
    elapsed_vals = [v.get('time_s', 0) for v in details.values()]
    avg_elapsed = sum(elapsed_vals) / total if total else 0
    n_muts = [v.get('n_mutations', 0) for v in details.values()]
    total_muts = sum(n_muts)

    lines = []
    lines.append("# Evaluation Diagnostics")
    lines.append("")

    lines.append(f"Score: {sp_avg:.4f} avg Spearman")
    lines.append(f"Range: {min(sp_vals):.4f} (worst) to {max(sp_vals):.4f} (best)")
    lines.append(f"Bottom quartile avg: {sp_low_avg:.4f} — this is where gains come from")
    lines.append(f"Speed: {avg_elapsed:.1f}s/protein avg, {total_muts:,} total mutations scored")
    gap = 0.50 - sp_avg
    if gap > 0:
        lines.append(f"Gap to VenusREM floor: {gap:+.4f}.")
    else:
        lines.append(f"Above VenusREM floor by {-gap:+.4f}. Well done.")
    lines.append("")
    lines.append("**Data available:** VenusREM, S3F_MSA, ESM2_15B predictions + structure data.")
    lines.append("**Import:** `from proteingym_data import get_model_scores, get_residue_structure, get_protein_info`")
    lines.append("")

    mut_diag = details_dict.get("mutation_diagnostics", {})
    sub_analysis = details_dict.get("substitution_analysis", {})
    insights = []

    if mut_diag:
        all_preds = []
        all_exps = []
        for mdata in mut_diag.values():
            for m in mdata.get('worst_mutations', []):
                all_preds.append(m.get('predicted', 0))
                all_exps.append(m.get('expected', 0))
        if all_preds and all_exps:
            sp_sorted = sorted(all_preds)
            se_sorted = sorted(all_exps)
            n = len(sp_sorted)
            pred_q1, pred_q3 = sp_sorted[int(n*0.25)], sp_sorted[int(n*0.75)]
            exp_q1, exp_q3 = se_sorted[int(n*0.25)], se_sorted[int(n*0.75)]
            pred_iqr = pred_q3 - pred_q1
            exp_iqr = exp_q3 - exp_q1
            ratio = pred_iqr / exp_iqr if exp_iqr > 0.01 else float('inf')
            if ratio > 2.0:
                insights.append(f"**Score calibration:** Predicted IQR is {ratio:.1f}x wider than experimental. Scores are exaggerated.")
            elif ratio < 0.5:
                insights.append(f"**Score calibration:** Predicted IQR is {ratio:.1f}x narrower than experimental. Scores are compressed.")

    if mut_diag:
        all_errors = []
        for mdata in mut_diag.values():
            for m in mdata.get('worst_mutations', []):
                all_errors.append(m.get('error', 0))
        if all_errors:
            import statistics as stats_mod
            med_err = stats_mod.median(all_errors)
            neg_pct = sum(1 for e in all_errors if e < 0) / len(all_errors) * 100
            if neg_pct > 70:
                insights.append(f"**Systematic over-prediction of harm:** {neg_pct:.0f}% of worst errors are negative, median {med_err:+.1f}.")
            elif neg_pct < 30:
                insights.append(f"**Systematic under-prediction of harm:** {100-neg_pct:.0f}% of worst errors are positive, median {med_err:+.1f}.")
            else:
                insights.append(f"**Error direction:** Balanced ({neg_pct:.0f}% negative, median {med_err:+.1f}).")

    if sub_analysis:
        sorted_subs = sorted(sub_analysis.items(), key=lambda x: x[1].get('mean_abs_error', 0), reverse=True)
        worst_3 = sorted_subs[:3]
        class_summaries = []
        for sc, stats in worst_3:
            n = stats.get('count', 0)
            mae = stats.get('mean_abs_error', 0)
            class_summaries.append(f"{sc} (n={n}, mae {mae:.1f})")
        insights.append(f"**Worst substitution classes:** {'; '.join(class_summaries)}.")

    if insights:
        lines.append("## Key Insights")
        lines.append("")
        for insight in insights:
            lines.append(f"- {insight}")
        lines.append("")

    lines.append("## Weakest Proteins (focus here)")
    sorted_proteins = sorted(details.items(), key=lambda x: x[1].get('spearman', 0))
    for pid, v in sorted_proteins[:20]:
        sp = v.get('spearman', 0)
        msa_d = v.get('msa_depth', 0)
        n = v.get('n_mutations', 0)
        lines.append(f"  {pid}: {sp:.4f} (MSA={msa_d}, n={n})")
    lines.append("")

    if mut_diag:
        lines.append("## Worst Mutations (examples for debugging)")
        lines.append("")
        for pid, mdata in list(mut_diag.items())[:5]:
            sp = mdata.get('spearman', 0)
            worst = mdata.get('worst_mutations', [])
            if not worst:
                continue
            lines.append(f"**{pid}** (Spearman={sp:.4f}):")
            for m in worst[:3]:
                mut_str = m.get('mutant', '?')[:10]
                sc = m.get('sub_class', '?')
                pred = m.get('predicted', 0)
                exp = m.get('expected', 0)
                lines.append(f"  {mut_str} ({sc}): pred={pred:+.1f}, exp={exp:+.1f}")
            lines.append("")

    diag_file = os.path.join(track_dir, "staging_diagnostics.md")
    try:
        with open(diag_file, "w") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass

def append_entry(entry_dict):
    os.makedirs(os.path.dirname(history_path), exist_ok=True)
    with open(history_path, "a") as f:
        f.write(json.dumps(entry_dict) + "\n")

def send_notification(track_dir, run_num, verdict, score, best_score, details, agent_type="scientist"):
    """Notification stub — prints to stderr instead of sending to a chat service."""
    avg_sp = details.get("avg_spearman", 0) if isinstance(details, dict) else 0
    n_proteins = details.get("n_proteins", 0) if isinstance(details, dict) else 0
    icon = "[OK]" if verdict == "accepted" else "[--]"
    print(f"{icon} PG {agent_type.title()} Run {run_num}: "
          f"Score={score:.4f} {'(new best!)' if verdict == 'accepted' else f'(best: {best_score:.4f})'} "
          f"Spearman={avg_sp:.4f} ({n_proteins} proteins)", file=sys.stderr)
    if hypothesis:
        print(f"  Tried: {hypothesis[:200]}", file=sys.stderr)


def kill_rogue_watchers():
    import subprocess as sp
    our_script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "smoke_test_watcher.py")
    try:
        result = sp.run(["pgrep", "-f", "proteingym.*smoke_test_watcher"], capture_output=True, text=True, timeout=5)
        pids = [int(p) for p in result.stdout.strip().split("\n") if p.strip()]
    except Exception:
        return

    if not pids:
        return

    systemd_pids = set()
    for svc in ("proteingym-smoke-watcher",):
        try:
            r = sp.run(["systemctl", "show", svc, "-p", "MainPID"], capture_output=True, text=True, timeout=5)
            pid = int(r.stdout.strip().split("=")[1]) if "=" in r.stdout else 0
            if pid:
                systemd_pids.add(pid)
        except Exception:
            pass

    for pid in pids:
        if pid not in systemd_pids and pid != os.getpid():
            try:
                os.kill(pid, 15)
                print(f"[guard] Killed rogue watcher PID {pid} (not systemd-managed)", file=sys.stderr)
            except (ProcessLookupError, PermissionError):
                pass


def check_kuhn_handoff(track_dir, parsed_score, run_num, repo_root):
    if "kuhn" not in track_dir:
        return
    sys.path.insert(0, os.path.join(repo_root, "scripts"))
    from pg_common import get_scientist_best, get_all_time_best, update_all_time_best
    all_time_best = get_all_time_best()
    scientist_best = get_scientist_best()
    handoff_threshold = all_time_best if all_time_best > 0 else scientist_best
    if scientist_best == 0.0 and all_time_best == 0.0:
        print("[handoff] No scores recorded — skipping handoff check", file=sys.stderr)
        return
    if parsed_score > handoff_threshold:
        print(f"[handoff] Kuhn workspace scored {parsed_score:.4f} > {handoff_threshold:.4f} — auto-handoff", file=sys.stderr)
        handoff_script = os.path.join(repo_root, "scripts", "kuhn_handoff.py")
        try:
            handoff_result = subprocess.run(
                [sys.executable, handoff_script, "--from-run", str(run_num)],
                capture_output=True, text=True, timeout=60,
                cwd=repo_root,
            )
            handoff_output = (handoff_result.stdout or "") + (handoff_result.stderr or "")
            print(f"[handoff] Result: {handoff_output[:500]}", file=sys.stderr)
        except Exception as e:
            print(f"[handoff] ERROR: {e}", file=sys.stderr)


def sanitize_workspace():
    import shutil

    kill_rogue_watchers()

    allowed = {
        "AGENTS.md", "SOUL.md", "USER.md", "IDENTITY.md",
        "TOOLS.md", "HEARTBEAT.md", "MEMORY.md", "BOOTSTRAP.md",
        "AGENT_PROMPT.md", "program.md", "DATA_PRIMER.md",
        "DATA_REFERENCE.md", "TECHNIQUES.md",
        "staging_strategy.py", "best_so_far_strategy.py", "last_attempt_strategy.py",
        "staging_hypothesis.txt", "staging_plan.md",
        "staging_prediction.json", "staging_blockers.md", "staging_worksheet.md",
        "worksheet_template.md",
        "staging_diagnostics.md", "staging_smoke_result.json",
        "scratch.md",
        "history.jsonl", "causal_model.md",
        "all_time_best.txt",
        "KUHN_INJECTION.json", "KUHN_STATE.json", "KUHN_OUTPUT.md",
        "paradigm_context.md", "staging_kuhn_bypass",
        "structure_summaries",
        ".validator_lock_dir",
        ".git",
        ".gitignore",
    }

    removed = []
    for item in os.listdir(track_dir):
        full_path = os.path.join(track_dir, item)
        if os.path.isdir(full_path):
            if item not in allowed:
                shutil.rmtree(full_path)
                removed.append(item + "/")
        elif item not in allowed:
            os.remove(full_path)
            removed.append(item)

    if removed:
        print(f"[sanitize] Removed: {', '.join(removed)}", file=sys.stderr)

    template_path = os.path.join(track_dir, "worksheet_template.md")
    if os.path.exists(template_path):
        os.chmod(template_path, 0o444)

def kuhn_reset():
    if "kuhn" not in track_dir:
        return

    clear_files = [
        "KUHN_OUTPUT.md", "scratch.md", "staging_plan.md",
        "staging_hypothesis.txt", "staging_diagnostics.md",
        "staging_worksheet.md", "staging_prediction.json",
        "staging_blockers.md",
    ]
    cleared = []
    for fname in clear_files:
        fpath = os.path.join(track_dir, fname)
        if os.path.isfile(fpath):
            os.remove(fpath)
            cleared.append(fname)

    if os.path.isfile(history_path):
        with open(history_path) as hf:
            all_hist = [json.loads(l.strip()) for l in hf if l.strip()]
        if len(all_hist) > 5:
            with open(history_path, 'w') as hf:
                for e in all_hist[-5:]:
                    hf.write(json.dumps(e) + '\n')
            print(f"[kuhn-reset] Trimmed history {len(all_hist)} -> 5", file=sys.stderr)

    if cleared:
        print(f"[kuhn-reset] Cleared: {', '.join(cleared)}", file=sys.stderr)


defeatist_replacements = [
    (r'(?i)\bexhausted\b', 'tested'),
    (r'(?i)\boptimal\b', 'current best'),
    (r'(?i)\bceiling\b', 'current top score'),
    (r'(?i)\bimpossible\b', 'not yet achieved'),
    (r'(?i)\bcatastrophic\b', 'significant'),
    (r'(?i)\btrue local optimum\b', 'stable configuration'),
    (r'(?i)\bno (?:more |further )?(?:improvement|progress|gain)\b', 'no improvement found'),
    (r'(?i)\bcannot improve\b', 'did not improve'),
    (r'(?i)\ball approaches? have failed\b', 'all tested approaches regressed'),
    (r'(?i)\bapproach space is tested\b', 'approach space needs new ideas'),
]

def scrub_defeatism(text, label=""):
    import re as _re
    scrubbed = text
    total = 0
    for pattern, replacement in defeatist_replacements:
        new, n = _re.subn(pattern, replacement, scrubbed)
        total += n
        scrubbed = new
    if total > 0 and label:
        print(f"[scrub] {label}: replaced {total} defeatist terms", file=sys.stderr)
    return scrubbed, total


def trim_causal_model():
    cm = os.path.join(track_dir, "causal_model.md")
    if not os.path.exists(cm):
        return

    with open(cm, 'r') as f:
        content = f.read()

    scrubbed, _ = scrub_defeatism(content, "causal_model.md")

    lines = scrubbed.split('\n')
    hyp_positions = [(i, line) for i, line in enumerate(lines) if line.startswith("### Hypothesis ")]
    if len(hyp_positions) <= 10:
        with open(cm, 'w') as f:
            f.write('\n'.join(lines))
        return
    keep_from = hyp_positions[-10][0]
    header_search = keep_from
    while header_search > 0 and not lines[header_search].startswith("## "):
        header_search -= 1
    first_hyp = hyp_positions[0][0]
    section_start = first_hyp
    while section_start > 0 and not lines[section_start].startswith("## "):
        section_start -= 1
    trimmed = lines[:section_start + 1] + [""] + lines[keep_from:]
    with open(cm, 'w') as f:
        f.write('\n'.join(trimmed))


def scrub_history():
    hist = os.path.join(track_dir, "history.jsonl")
    if not os.path.exists(hist):
        return
    with open(hist, 'r') as f:
        entries = [json.loads(l.strip()) for l in f if l.strip()]

    changed = False
    for entry in entries:
        for field in ("hypothesis", "plan", "note", "verdict"):
            if field in entry and isinstance(entry[field], str):
                scrubbed, n = scrub_defeatism(entry[field], "")
                if n > 0:
                    entry[field] = scrubbed
                    changed = True

    if changed:
        with open(hist, 'w') as f:
            for entry in entries:
                f.write(json.dumps(entry) + '\n')
        print(f"[scrub] history.jsonl: defeatist terms replaced", file=sys.stderr)

def get_diff_summary():
    rel = os.path.relpath(strategy_path, repo_root)
    try:
        r = subprocess.run(
            ["git", "-C", repo_root, "diff", "--stat", "HEAD", "--", rel],
            capture_output=True, text=True, timeout=30,
        )
        return r.stdout.strip()
    except Exception:
        return ""


if improved:
    print(f"IMPROVED: {score_str} > {best_str}", file=sys.stderr)

    try:
        shutil.copy2(strategy_path, best_so_far_path)
        print(f"Updated best_so_far_strategy.py", file=sys.stderr)
    except Exception as e:
        print(f"best_so_far copy failed: {e}", file=sys.stderr)

    if "kuhn" not in track_dir:
        best_rel = os.path.relpath(best_so_far_path, repo_root)
        staged_rel = os.path.relpath(staged_path, repo_root)
        hist_rel = os.path.relpath(history_path, repo_root)
        add_result = subprocess.run(
            ["git", "-C", repo_root, "add", best_rel, staged_rel, hist_rel],
            capture_output=True, text=True, timeout=30,
        )
        if add_result.returncode != 0:
            add_err = (add_result.stdout or "") + (add_result.stderr or "")
            print(f"git add failed: {add_err}", file=sys.stderr)
            entry["verdict"] = "git_error"
            entry["git_error"] = add_err[:1000]
            entry["diff_summary"] = ""
            append_entry(entry)
            trim_causal_model()
            scrub_history()
            sanitize_workspace()
            kuhn_reset()
            sys.exit(1)

        commit_result = subprocess.run(
            ["git", "-C", repo_root, "commit", "-m",
             f"pg-sef: run {run_num}, score {score_str} (was {best_str})"],
            capture_output=True, text=True, timeout=30,
        )
        commit_combined = (commit_result.stdout or "") + (commit_result.stderr or "")
        if commit_result.returncode != 0:
            if "nothing to commit" in commit_combined or "no changes added" in commit_combined:
                entry["verdict"] = "false_positive"
                entry["best_score"] = best_score
                entry["diff_summary"] = ""
                append_entry(entry)
                trim_causal_model()
                scrub_history()
                sanitize_workspace()
                kuhn_reset()
                print(f"REPORT: false_positive {run_num} {score_str}")
                sys.exit(1)
            else:
                entry["verdict"] = "git_error"
                entry["git_error"] = commit_combined[:1000]
                append_entry(entry)
                trim_causal_model()
                scrub_history()
                sanitize_workspace()
                kuhn_reset()
                print(f"REPORT: git_error {run_num} {commit_combined[:200]}", file=sys.stderr)
                sys.exit(1)
    else:
        print(f"Git operations skipped (Kuhn workspace)", file=sys.stderr)

    diff_summary = get_diff_summary()
    entry["diff_summary"] = diff_summary
    entry["verdict"] = "accepted"
    append_entry(entry)

    write_diagnostics(details)

    try:
        all_entries = []
        with open(history_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    all_entries.append(json.loads(line))
                except (json.JSONDecodeError, KeyError):
                    continue

        kept = [e for e in all_entries if e.get("improved", False)]
        with open(history_path, 'w') as f:
            for e in kept:
                f.write(json.dumps(e) + "\n")
        pruned = len(all_entries) - len(kept)
        if pruned:
            print(f"[history] Pruned {pruned} non-improvement entries", file=sys.stderr)
    except Exception as e:
        print(f"History prune error: {e}", file=sys.stderr)

    trim_causal_model()
    scrub_history()
    sanitize_workspace()
    kuhn_reset()
    send_notification(track_dir, run_num, "accepted", parsed_score, parsed_score, details,
                       "kuhn" if "kuhn" in track_dir else "scientist")
    print(f"REPORT: accepted {run_num} {score_str}")

    _track_name = os.path.basename(track_dir)
    _archive_agent = "kuhn" if "kuhn" in track_dir else "scientist"
    archive_dir = os.path.join(repo_root, "archives", _archive_agent)
    os.makedirs(archive_dir, exist_ok=True)
    archive_file = os.path.join(archive_dir, f"run_{run_num:04d}_{parsed_score:.4f}.py")
    shutil.copy2(staged_path, archive_file)
    meta_file = os.path.join(archive_dir, f"run_{run_num:04d}_{parsed_score:.4f}.json")
    with open(meta_file, "w") as mf:
        json.dump({
            "run": run_num,
            "score": parsed_score,
            "best_score": parsed_score,
            "verdict": "accepted",
            "hypothesis": hypothesis,
            "timestamp": entry.get("timestamp", ""),
        }, mf, indent=2)

    check_kuhn_handoff(track_dir, parsed_score, run_num, repo_root)

    if "kuhn" in track_dir:
        state_file = os.path.join(track_dir, "KUHN_STATE.json")
        injection_file = os.path.join(track_dir, "KUHN_INJECTION.json")
        selector_script = os.path.join(repo_root, "scripts", "pg_kuhn_selector.py")
        if os.path.isfile(selector_script):
            try:
                with open(injection_file) as inf:
                    curr_inj = json.load(inf)
                curr_pair = [curr_inj.get("assumption", ""), curr_inj.get("domain", "")]
                with open(state_file) as sf:
                    state = json.load(sf)
                tried = state.get("tried_pairs", [])
                if curr_pair not in tried:
                    tried.append(curr_pair)
                state["tried_pairs"] = tried
                state["kuhn_run_number"] = state.get("kuhn_run_number", 0) + 1
                state["last_kuhn_run"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                with open(state_file, "w") as sf:
                    json.dump(state, sf, indent=2)
            except Exception as e:
                print(f"[selector] state update error: {e}", file=sys.stderr)
            sel_result = subprocess.run(
                ["python3", selector_script, "--state", state_file, "--out", injection_file],
                capture_output=True, text=True, timeout=30,
            )
            if sel_result.returncode == 0:
                print(f"[selector] Next injection selected", file=sys.stderr)
            elif sel_result.returncode == 2:
                print(f"[selector] All pairs exhausted — SETTLED", file=sys.stderr)
            else:
                print(f"[selector] Error: {(sel_result.stderr or '')[:200]}", file=sys.stderr)
    sys.exit(0)

else:
    print(f"REJECTED: {score_str} <= {best_str}", file=sys.stderr)

    if os.path.isfile(staged_path):
        _track_name = os.path.basename(track_dir)
        _archive_agent = "kuhn" if "kuhn" in track_dir else "scientist"
        archive_dir = os.path.join(repo_root, "archives", _archive_agent)
        os.makedirs(archive_dir, exist_ok=True)
        archive_file = os.path.join(archive_dir, f"run_{run_num:04d}_{parsed_score:.4f}.py")
        shutil.copy2(staged_path, archive_file)
        meta_file = os.path.join(archive_dir, f"run_{run_num:04d}_{parsed_score:.4f}.json")
        with open(meta_file, "w") as mf:
            json.dump({
                "run": run_num,
                "score": parsed_score,
                "best_score": best_score,
                "verdict": "rejected",
                "hypothesis": hypothesis,
                "timestamp": entry.get("timestamp", ""),
            }, mf, indent=2)

        shutil.copy2(staged_path, last_attempt_path)

    if os.path.isfile(best_so_far_path):
        shutil.copy2(best_so_far_path, staged_path)

    diff_summary = get_diff_summary()
    entry["diff_summary"] = diff_summary

    details_proteins = details.get("details", details)
    n_proteins = len(details_proteins) if isinstance(details_proteins, dict) else 0

    parts = []
    if n_proteins == 0:
        parts.append("No protein results returned.")
    else:
        parts.append(f"Scored {score_str} vs best {best_str}. "
                     f"Proteins scored: {n_proteins}/217. "
                     f"Avg Spearman={details.get('avg_spearman', 0):.4f}, "
                     f"avg time={details.get('avg_time_s', 0):.1f}s.")
    entry["rejection_note"] = " ".join(parts)
    entry["verdict"] = "rejected"

    subprocess.run(["git", "-C", repo_root, "checkout", "--", strategy_path],
                   timeout=30, capture_output=True)

    append_entry(entry)
    write_diagnostics(details)

    trim_causal_model()
    scrub_history()
    sanitize_workspace()
    kuhn_reset()
    send_notification(track_dir, run_num, "rejected", parsed_score, best_score, details,
                       "kuhn" if "kuhn" in track_dir else "scientist")
    print(f"REPORT: rejected {run_num} {score_str}")

    if entry.get("verdict") == "git_error":
        check_kuhn_handoff(track_dir, parsed_score, run_num, repo_root)

    if "kuhn" not in track_dir:
        import hashlib as _hl
        with open(best_so_far_path, 'rb') as _bf:
            current_best_hash = _hl.md5(_bf.read()).hexdigest()[:8]
        last_accepted_delta = 0.0
        with open(history_path) as hf:
            hist_entries = [json.loads(l.strip()) for l in hf if l.strip()]
        for he in reversed(hist_entries):
            if he.get("verdict") == "accepted" or he.get("improved") == True:
                last_accepted_delta = abs(he.get("score_delta", 0.0) or 0.0)
                break
        if last_accepted_delta >= 0.01:
            rejection_threshold = 10
        elif last_accepted_delta >= 0.001:
            rejection_threshold = 5
        else:
            rejection_threshold = 0
        print(f"[plateau] Last accepted delta: {last_accepted_delta:.6f} -> threshold: {rejection_threshold} rejections", file=sys.stderr)
        consec_plateau = 0
        rejections_vs_current = 0
        for he in reversed(hist_entries):
            if he.get("verdict") == "accepted" or he.get("improved") == True:
                break
            if he.get("verdict") in ("rejected", "false_positive", "git_error", "validation_failed"):
                consec_plateau += 1
                if he.get("best_hash") == current_best_hash:
                    rejections_vs_current += 1
            elif he.get("verdict") in ("", None) and he.get("improved") == False:
                consec_plateau += 1
                if he.get("best_hash") == current_best_hash:
                    rejections_vs_current += 1
        if (rejection_threshold == 0 and consec_plateau >= 1) or \
           (rejection_threshold > 0 and consec_plateau >= rejection_threshold and rejections_vs_current >= 1):
            print(f"[plateau] {consec_plateau} consecutive rejections — triggering handoff", file=sys.stderr)
            s2k_script = os.path.join(repo_root, "scripts", "scientist_to_kuhn_handoff.py")
            if os.path.isfile(s2k_script):
                s2k_result = subprocess.run(
                    ["python3", s2k_script, "--force"],
                    capture_output=True, text=True, timeout=120,
                )
                print(f"[plateau] Handoff output: {(s2k_result.stdout or '')[:500]}", file=sys.stderr)
                if s2k_result.returncode != 0:
                    print(f"[plateau] Handoff ERROR: {(s2k_result.stderr or '')[:200]}", file=sys.stderr)

    if "kuhn" in track_dir:
        state_file = os.path.join(track_dir, "KUHN_STATE.json")
        injection_file = os.path.join(track_dir, "KUHN_INJECTION.json")
        selector_script = os.path.join(repo_root, "scripts", "pg_kuhn_selector.py")
        if os.path.isfile(selector_script):
            try:
                with open(injection_file) as inf:
                    curr_inj = json.load(inf)
                curr_pair = [curr_inj.get("assumption", ""), curr_inj.get("domain", "")]
                with open(state_file) as sf:
                    state = json.load(sf)
                tried = state.get("tried_pairs", [])
                if curr_pair not in tried:
                    tried.append(curr_pair)
                state["tried_pairs"] = tried
                state["kuhn_run_number"] = state.get("kuhn_run_number", 0) + 1
                state["last_kuhn_run"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                with open(state_file, "w") as sf:
                    json.dump(state, sf, indent=2)
            except Exception as e:
                print(f"[selector] state update error: {e}", file=sys.stderr)
            sel_result = subprocess.run(
                ["python3", selector_script, "--state", state_file, "--out", injection_file],
                capture_output=True, text=True, timeout=30,
            )
            if sel_result.returncode == 0:
                print(f"[selector] Next injection selected", file=sys.stderr)
            elif sel_result.returncode == 2:
                print(f"[selector] All pairs exhausted — SETTLED", file=sys.stderr)
            else:
                print(f"[selector] Error: {(sel_result.stderr or '')[:200]}", file=sys.stderr)
    sys.exit(0)
PYEOF
