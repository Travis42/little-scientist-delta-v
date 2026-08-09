#!/usr/bin/env python3
"""
Smoke test watcher for ProteinGym experiment.

Runs as a systemd service. Continuously polls for staging_smoke_trigger.json
in both the scientist and Kuhn workspaces. When an agent writes a trigger:

1. Runs the smoke test (proteingym_smoke.py) on that workspace
2. Writes results to staging_smoke_result.json
3. If all proteins pass -> immediately runs the validator (event-driven)
4. Cleans up the trigger file

The validator is NOT on a cron. It triggers automatically when smoke passes.

Usage: python3 scripts/smoke_test_watcher.py
"""

import json, os, sys, time, subprocess, difflib

PROJECT_ROOT = os.environ.get(
    "PROTEINGYM_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
SMOKE_SCRIPT = os.path.join(PROJECT_ROOT, "eval", "proteingym_smoke.py")
VALIDATOR_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "proteingym_validate_and_eval.sh")
VALIDATOR_LOG = os.path.join(PROJECT_ROOT, "logs", "validator_triggered.log")

# Both workspaces — scientist and Kuhn
WORKSPACES = [
    os.path.join(PROJECT_ROOT, "workspace"),                          # scientist
    os.environ.get("KUHN_WORKSPACE",
        os.path.join(PROJECT_ROOT, "kuhn-workspace")),  # kuhn
]

TIMINGS_PATH = os.path.join(PROJECT_ROOT, "config", "timings.json")

def load_timings():
    """Load timing constants from config file."""
    defaults = {
        "poll_interval_seconds": 1.0,
        "smoke_timeout_seconds": 600,
        "validator_timeout_seconds": 1800,
        "debounce_seconds": 60,
        "code_review_grace_seconds": 600,
        "validator_stale_lock_seconds": 600,
    }
    try:
        with open(TIMINGS_PATH) as f:
            cfg = json.load(f)
        defaults.update({
            "poll_interval_seconds": cfg.get("poll_interval_seconds", 1.0),
            "smoke_timeout_seconds": cfg.get("smoke_timeout_seconds", 600),
            "validator_timeout_seconds": cfg.get("validator_timeout_seconds", 1800),
            "debounce_seconds": cfg.get("debounce_seconds", 60),
            "code_review_grace_seconds": cfg.get("code_review_grace_seconds", 600),
            "validator_stale_lock_seconds": cfg.get("validator_stale_lock_seconds", 600),
        })
    except Exception as e:
        log(f"WARNING: could not load timings.json ({e}), using defaults")
    return defaults

_T = load_timings()
POLL_INTERVAL = _T["poll_interval_seconds"]
SMOKE_TIMEOUT = _T["smoke_timeout_seconds"]
VALIDATOR_TIMEOUT = _T["validator_timeout_seconds"]
DEBOUNCE_SECONDS = _T["debounce_seconds"]
CODE_REVIEW_GRACE = _T["code_review_grace_seconds"]
STALE_LOCK_AGE = _T["validator_stale_lock_seconds"]
REVIEW_POLL_RETRIES = 3


def log(msg):
    print(f"[pg-watcher] {msg}", flush=True)


def run_smoke_test(workspace):
    """Run proteingym_smoke.py on the given workspace.
    Returns True if all proteins passed, False otherwise."""
    trigger_file = os.path.join(workspace, "staging_smoke_trigger.json")
    result_file = os.path.join(workspace, "staging_smoke_result.json")
    pass_file = os.path.join(workspace, "staging_smoke_passed.json")

    start = time.time()

    try:
        result = subprocess.run(
            [sys.executable, "-u", SMOKE_SCRIPT, "--workspace", workspace],
            capture_output=True, text=True,
            timeout=SMOKE_TIMEOUT, cwd=PROJECT_ROOT,
        )

        # Parse output
        try:
            parsed = json.loads(result.stdout.strip().split('\n')[-1])
        except (json.JSONDecodeError, IndexError):
            parsed = {
                "error": "smoke test produced invalid JSON",
                "raw_output": result.stdout[-2000:],
                "stderr": result.stderr[-500:],
                "profiles": {},
            }

        parsed["watcher_time_seconds"] = round(time.time() - start, 1)
        parsed["watcher_timestamp"] = time.time()

        # Write result file for agent to read
        with open(result_file, "w") as f:
            json.dump(parsed, f, indent=2)

        # Count outcomes
        crashed = sum(
            1 for p in parsed.get("profiles", {}).values()
            if p.get("status") in ("crash", "timeout")
        )
        ok = sum(
            1 for p in parsed.get("profiles", {}).values()
            if p.get("status") == "ok"
        )
        skipped = sum(
            1 for p in parsed.get("profiles", {}).values()
            if p.get("status") == "skip"
        )

        log(f"{os.path.basename(workspace)}: {ok} ok, {crashed} crashed, {skipped} skipped ({round(time.time() - start, 1)}s)")

        # Write pass marker if no crashes and at least 1 OK
        if crashed == 0 and ok > 0:
            with open(pass_file, "w") as f:
                json.dump({
                    "timestamp": time.time(),
                    "ok": ok,
                    "crashed": crashed,
                    "avg_spearman": parsed.get("avg_spearman", 0.0),
                }, f, indent=2)
            log(f"{os.path.basename(workspace)}: PASS marker written ({ok} proteins OK)")

            # Clean up trigger
            if os.path.exists(trigger_file):
                os.remove(trigger_file)

            return True  # Signal: run validator

        # Clean up trigger even on failure
        if os.path.exists(trigger_file):
            os.remove(trigger_file)

        return False

    except subprocess.TimeoutExpired:
        result = {
            "error": f"smoke test timed out after {SMOKE_TIMEOUT}s",
            "profiles": {},
            "watcher_timestamp": time.time(),
        }
        with open(result_file, "w") as f:
            json.dump(result, f, indent=2)
        if os.path.exists(trigger_file):
            os.remove(trigger_file)
        log(f"{os.path.basename(workspace)}: TIMED OUT")
        return False

    except Exception as e:
        result = {
            "error": f"watcher error: {e}",
            "profiles": {},
            "watcher_timestamp": time.time(),
        }
        with open(result_file, "w") as f:
            json.dump(result, f, indent=2)
        if os.path.exists(trigger_file):
            os.remove(trigger_file)
        log(f"{os.path.basename(workspace)}: ERROR: {e}")
        return False


def run_validator(workspace):
    """Run the validator immediately after smoke test passes."""
    log(f"Triggering validator for {os.path.basename(workspace)}...")

    try:
        env = os.environ.copy()
        env["PG_TRACK_DIR"] = workspace
        result = subprocess.run(
            ["bash", VALIDATOR_SCRIPT],
            capture_output=True, text=True,
            timeout=VALIDATOR_TIMEOUT, cwd=PROJECT_ROOT,
            env=env,
        )
        log_dir = os.path.join(PROJECT_ROOT, "logs")
        os.makedirs(log_dir, exist_ok=True)
        with open(VALIDATOR_LOG, "a") as f:
            f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            f.write(result.stdout[-2000:])
            if result.stderr:
                f.write("\n--- stderr ---\n")
                f.write(result.stderr[-1000:])
        log(f"Validator done (exit {result.returncode})")
    except subprocess.TimeoutExpired:
        log(f"Validator timed out after {VALIDATOR_TIMEOUT}s")
    except Exception as e:
        log(f"Validator error: {e}")


def write_no_review_failure(workspace):
    """Write a history entry for smoke trigger without code review.
    Called after grace period expires."""
    history_file = os.path.join(workspace, "history.jsonl")

    # Get next run number
    next_run = 1
    if os.path.exists(history_file):
        with open(history_file) as f:
            for line in f:
                try:
                    d = json.loads(line.strip())
                    if d.get("run", 0) >= next_run:
                        next_run = d["run"] + 1
                except (json.JSONDecodeError, ValueError):
                    continue

    # Try to read hypothesis from staging files for context
    hypothesis = ""
    hyp_file = os.path.join(workspace, "staging_hypothesis.txt")
    if os.path.exists(hyp_file):
        with open(hyp_file) as f:
            hypothesis = f.read().strip()[:500]

    entry = {
        "run": next_run,
        "score": None,
        "best_score": None,
        "improved": False,
        "verdict": "no_code_review",
        "reason": f"Agent wrote smoke trigger without completing code review ({CODE_REVIEW_GRACE}s timeout)",
        "hypothesis": hypothesis,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    with open(history_file, "a") as f:
        f.write(json.dumps(entry) + "\n")

    log(f"{os.path.basename(workspace)}: wrote no_code_review failure to history (run {next_run})")


def inject_diff_into_worksheet(workspace):
    """Detect review trigger, compute diff, inject into worksheet Section 7."""
    review_trigger = os.path.join(workspace, "staging_review_trigger.json")
    if not os.path.exists(review_trigger):
        return

    strategy_file = os.path.join(workspace, "staging_strategy.py")
    best_file = os.path.join(workspace, "best_so_far_strategy.py")
    worksheet_file = os.path.join(workspace, "staging_worksheet.md")

    if not (os.path.exists(strategy_file) and os.path.exists(worksheet_file)):
        log(f"{os.path.basename(workspace)}: review trigger found but strategy/worksheet missing, cleaning up")
        os.remove(review_trigger)
        return

    # Read both versions
    with open(strategy_file) as f:
        new_code = f.readlines()
    if os.path.exists(best_file):
        with open(best_file) as f:
            old_code = f.readlines()
    else:
        old_code = []

    # Compute unified diff (context lines = 2 for compactness)
    diff_lines = list(difflib.unified_diff(
        old_code, new_code,
        fromfile="best_so_far_strategy.py",
        tofile="staging_strategy.py",
        n=2, lineterm=""
    ))

    if diff_lines:
        diff_text = "\n".join(diff_lines)
    else:
        diff_text = "(No changes from best_so_far_strategy.py — identical code)"

    # Read worksheet
    with open(worksheet_file) as f:
        worksheet = f.read()

    # Remove any existing Code Verification section and re-inject
    marker = "## 7. Code Verification"
    if marker in worksheet:
        worksheet = worksheet[:worksheet.index(marker)]

    # Append fresh Code Verification section with diff
    worksheet += "\n\n" + marker + "\n\n"
    worksheet += "*Injected by watcher — diff of your changes vs best_so_far_strategy.py.*\n\n"
    worksheet += "```diff\n" + diff_text + "\n```\n\n"
    worksheet += "*For each change above, verify it matches your hypothesis. "
    worksheet += "Fill in the table, then write `staging_code_reviewed` when all rows match.*\n\n"
    worksheet += "| Change | What It Does | Matches Hypothesis? |\n"
    worksheet += "|--------|--------------|---------------------|\n"
    worksheet += "| | | |\n\n"

    with open(worksheet_file, "w") as f:
        f.write(worksheet)

    # Auto-write code_reviewed marker — the diff is injected for the agent to read,
    # but we don't block on the agent filling out the table (they often skip it).
    reviewed_marker = os.path.join(workspace, "staging_code_reviewed")
    if not os.path.exists(reviewed_marker):
        open(reviewed_marker, "w").close()

    # Clean up review trigger
    os.remove(review_trigger)
    log(f"{os.path.basename(workspace)}: diff injected + code_reviewed auto-written ({len(diff_lines)} diff lines)")


def main():
    if not os.path.isfile(SMOKE_SCRIPT):
        print(f"FATAL: {SMOKE_SCRIPT} not found", file=sys.stderr)
        sys.exit(1)

    log(f"Watching {len(WORKSPACES)} workspaces for trigger files")
    for ws in WORKSPACES:
        log(f"  - {ws}")

    # Track last smoke completion time per workspace (for debouncing)
    last_smoke_time = {}
    # Track when we first noticed a smoke trigger without code review
    pending_review = {}

    while True:
        for workspace in WORKSPACES:
            if not os.path.isdir(workspace):
                continue

            # Step 1: Check for review trigger (inject diff before smoke)
            inject_diff_into_worksheet(workspace)

            # Step 2: Check for smoke trigger
            trigger_file = os.path.join(workspace, "staging_smoke_trigger.json")
            if os.path.exists(trigger_file):
                # Gate: require code review completion (unless bypass marker exists)
                bypass_marker = os.path.join(workspace, "staging_kuhn_bypass")
                reviewed_marker = os.path.join(workspace, "staging_code_reviewed")
                if not os.path.exists(reviewed_marker) and not os.path.exists(bypass_marker):
                    ws_key = workspace
                    if ws_key not in pending_review:
                        pending_review[ws_key] = time.time()
                        log(f"{os.path.basename(workspace)}: smoke trigger waiting for code review (no timeout)")
                    continue
                else:
                    ws_key = workspace
                    if ws_key in pending_review:
                        del pending_review[ws_key]
                # Debounce: skip if we just finished a smoke for this workspace
                ws_key = workspace
                if ws_key in last_smoke_time:
                    elapsed = time.time() - last_smoke_time[ws_key]
                    if elapsed < DEBOUNCE_SECONDS:
                        try:
                            os.remove(trigger_file)
                            log(f"{os.path.basename(workspace)}: trigger debounced ({elapsed:.0f}s since last smoke, removing)")
                        except OSError:
                            pass
                        continue

                # Verify it's a real trigger
                try:
                    with open(trigger_file) as f:
                        data = json.load(f)
                    if data.get("request") != "run":
                        continue
                except (json.JSONDecodeError, OSError):
                    continue

                ws_name = os.path.basename(workspace)
                log(f"Trigger detected in {ws_name}")
                passed = run_smoke_test(workspace)
                last_smoke_time[ws_key] = time.time()

                if passed:
                    # Check validator lock before running
                    lock_file = os.path.join(workspace, ".validator_lock")
                    if os.path.exists(lock_file):
                        lock_age = time.time() - os.path.getmtime(lock_file)
                        import subprocess as _sp
                        try:
                            _proc = _sp.run(
                                ["pgrep", "-f", f"proteingym_validate_and_eval.{ws_name}"],
                                capture_output=True, text=True, timeout=5
                            )
                            _running = _proc.stdout.strip()
                        except Exception:
                            _running = ""

                        if not _running:
                            log(f"{ws_name}: orphaned lock (no validator process, {lock_age:.0f}s old) — removing")
                            os.remove(lock_file)
                            run_validator(workspace)
                        elif lock_age > STALE_LOCK_AGE:
                            log(f"{ws_name}: validator lock is stale ({lock_age:.0f}s old, pid {_running}), removing")
                            try:
                                os.kill(int(_running.split("\n")[0]), 9)
                            except Exception:
                                pass
                            os.remove(lock_file)
                            run_validator(workspace)
                        else:
                            log(f"{ws_name}: validator already running (pid {_running.split(chr(10))[0]}, {lock_age:.0f}s), skipping")
                    else:
                        run_validator(workspace)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
