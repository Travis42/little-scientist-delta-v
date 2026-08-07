#!/usr/bin/env python3
"""
Scientist-to-Kuhn plateau handoff for ProteinGym.

When the Scientist agent plateaus (5 consecutive non-accepted runs),
transfers control to the Kuhn agent:
1. Counts consecutive non-accepted verdicts in Scientist history
2. Copies best_so_far_strategy.py to Kuhn workspace
3. Cleans stale staging files, ensures bypass marker
4. Appends baseline entry to Kuhn history
5. Updates KUHN_STATE.json
6. Selects fresh injection via pg_kuhn_selector.py
7. Writes paradigm context
8. Disables Scientist cron, enables Kuhn cron
9. Sends notification

Usage:
    python3 scientist_to_kuhn_handoff.py                # Check + handoff if plateau
    python3 scientist_to_kuhn_handoff.py --force        # Handoff regardless of plateau
    python3 scientist_to_kuhn_handoff.py --check        # Report only
    python3 scientist_to_kuhn_handoff.py --plateau N    # Override threshold (default 5)
"""

import json, os, sys, shutil, subprocess, argparse, datetime

from pg_common import (
    REPO_ROOT, SCIENTIST_WS, KUHN_WS,
    SCIENTIST_CRON_ID, KUHN_CRON_ID,
    read_history, get_best_score, count_consecutive_rejections,
    toggle_cron, notify, copy_strategy,
)

PLATEAU_THRESHOLD = 5


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_next_run_number(kuhn_entries):
    """Get the next run number for Kuhn history."""
    if not kuhn_entries:
        return 1
    return max(e.get("run", 0) for e in kuhn_entries) + 1


def do_handoff(force=False, check_only=False, plateau_threshold=PLATEAU_THRESHOLD):
    """Execute the Scientist-to-Kuhn handoff."""

    # ── 1. Read Scientist state ──────────────────────────────────────────
    scientist_history = read_history(os.path.join(SCIENTIST_WS, "history.jsonl"))
    consecutive = count_consecutive_rejections(scientist_history)
    best_score = get_best_score(scientist_history)

    print(f"Scientist status:")
    print(f"  Best score: {best_score:.4f}")
    print(f"  Consecutive rejections: {consecutive}")
    print(f"  Plateau threshold: {plateau_threshold}")

    if check_only:
        if consecutive >= plateau_threshold:
            print(f"  → PLATEAU DETECTED — would hand off to Kuhn")
        else:
            print(f"  → No plateau ({plateau_threshold - consecutive} more rejections until handoff)")
        return consecutive >= plateau_threshold

    if not force and consecutive < plateau_threshold:
        print(f"  → No plateau yet, exiting")
        return False

    if best_score == 0:
        best_score = 0.433  # fallback
        print(f"  → No accepted score found, using fallback: {best_score}")

    print(f"\nHandoff initiated...")

    # ── 2. Copy strategy to Kuhn workspace ───────────────────────────────
    scientist_best = os.path.join(SCIENTIST_WS, "best_so_far_strategy.py")
    if not os.path.exists(scientist_best):
        print("ERROR: Scientist best_so_far_strategy.py not found")
        return False

    for filename in ("best_so_far_strategy.py", "staging_strategy.py", "last_attempt_strategy.py"):
        dest = os.path.join(KUHN_WS, filename)
        shutil.copy2(scientist_best, dest)
        os.chmod(dest, 0o644)
        print(f"  Copied → {filename}")

    # ── 3. Clean stale staging files ─────────────────────────────────────
    stale_files = [
        "staging_smoke_trigger.json", "staging_smoke_result.json",
        "staging_smoke_passed.json", "staging_eval_result.json",
        "staging_eval_details.json", "staging_hypothesis.txt",
        "staging_plan.md", "staging_blockers.md",
        "staging_code_reviewed", "staging_worksheet.md",
        "staging_prediction.json", "staging_diagnostics.md",
        "staging_review_trigger.json", ".validator_lock",
    ]
    for fname in stale_files:
        path = os.path.join(KUHN_WS, fname)
        if os.path.exists(path):
            os.remove(path)
            print(f"  Removed stale: {fname}")

    bypass_path = os.path.join(KUHN_WS, "staging_kuhn_bypass")
    if not os.path.exists(bypass_path):
        open(bypass_path, "w").close()
        print(f"  Created: staging_kuhn_bypass")

    # ── 4. Append baseline to Kuhn history ───────────────────────────────
    kuhn_history_path = os.path.join(KUHN_WS, "history.jsonl")
    kuhn_entries = read_history(kuhn_history_path)
    next_run = get_next_run_number(kuhn_entries)

    baseline_entry = {
        "run": next_run,
        "score": best_score,
        "best_score": best_score,
        "verdict": "baseline",
        "note": f"Inherited from Scientist plateau at {best_score:.4f}",
        "timestamp": now_iso(),
    }
    with open(kuhn_history_path, "a") as f:
        f.write(json.dumps(baseline_entry) + "\n")
    print(f"  Kuhn history: baseline run {next_run} at {best_score:.4f}")

    # ── 5. Update KUHN_STATE.json ────────────────────────────────────────
    state_path = os.path.join(KUHN_WS, "KUHN_STATE.json")
    with open(state_path) as f:
        state = json.load(f)

    state["state"] = "EXPLOITING"
    state["kuhn_failures"] = 0
    state["plateau_count"] = 0
    state["best_smoke_score"] = best_score
    state["last_kuhn_run"] = now_iso()

    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)
    print(f"  KUHN_STATE.json updated")

    # ── 6. Select fresh injection ────────────────────────────────────────
    injection_path = os.path.join(KUHN_WS, "KUHN_INJECTION.json")
    selector_script = os.path.join(REPO_ROOT, "scripts", "pg_kuhn_selector.py")
    injection = {}

    if os.path.isfile(selector_script):
        sel_result = subprocess.run(
            ["python3", selector_script, "--state", state_path, "--out", injection_path],
            capture_output=True, text=True, timeout=30,
        )
        if sel_result.returncode == 0:
            with open(injection_path) as f:
                injection = json.load(f)
            assumption = injection.get("assumption", "?")
            domain = injection.get("domain", "?")
            remaining = injection.get("pairs_remaining", "?")
            print(f"  New injection: {assumption[:60]}...")
            print(f"  Domain: {domain[:60]}...")
            print(f"  Pairs remaining: {remaining}")
        elif sel_result.returncode == 2:
            print("ERROR: All injection pairs exhausted — SETTLED")
            notify(
                "⚠️ **Scientist→Kuhn Handoff FAILED**\n\n"
                "All 384 injection pairs have been tried. System is SETTLED.\n"
                "Manual intervention needed."
            )
            return False
        else:
            print(f"ERROR: Selector failed: {(sel_result.stderr or '')[:200]}")
            return False
    else:
        print(f"WARNING: pg_kuhn_selector.py not found — no fresh injection selected")
        assumption = "?"
        domain = "?"

    # ── 7. Write paradigm context ────────────────────────────────────────
    causal_path = os.path.join(SCIENTIST_WS, "causal_model.md")
    technique = "See causal_model.md"
    if os.path.exists(causal_path):
        with open(causal_path) as f:
            cm = f.read()
        for header in ("## Current Best Strategy", "## What Works", "## Best"):
            idx = cm.find(header)
            if idx >= 0:
                end = cm.find("\n## ", idx + len(header))
                technique = cm[idx:end].strip()[:500] if end > 0 else cm[idx:idx+500].strip()
                break

    paradigm_path = os.path.join(KUHN_WS, "paradigm_context.md")
    with open(paradigm_path, "w") as f:
        f.write(f"""# Paradigm Shift Context

## What Happened
The Scientist agent plateaued after {consecutive} consecutive rejections at score {best_score:.4f}.
Control has been transferred to the Kuhn agent for paradigm interrogation.

## Scientist's Best Strategy
Score: {best_score:.4f}
Key technique: {technique[:300]}

## Your Injection
Assumption: {assumption}
Domain: {domain}

## Your Mission
Violate the assumption using the domain's structural logic. Score must reach
at least {best_score:.4f} (Scientist's best) to trigger handoff back to Scientist.
""")
    print(f"  Paradigm context written")

    # ── 8. Toggle crons ──────────────────────────────────────────────────
    print(f"\nToggling crons...")
    toggle_cron(SCIENTIST_CRON_ID, False)
    toggle_cron(KUHN_CRON_ID, True)

    # ── 9. Log transition in Scientist history ───────────────────────────
    handoff_entry = {
        "run": scientist_history[-1].get("run", 0) if scientist_history else 0,
        "verdict": "plateau_handoff_to_kuhn",
        "best_score": best_score,
        "consecutive_rejections": consecutive,
        "timestamp": now_iso(),
    }
    with open(os.path.join(SCIENTIST_WS, "history.jsonl"), "a") as f:
        f.write(json.dumps(handoff_entry) + "\n")
    print(f"  Logged transition in Scientist history")

    # ── 10. Send notification ───────────────────────────────────
    pairs_remaining = injection.get("pairs_remaining", "?")
    msg = (
        f"🔄 **Scientist Plateau → Kuhn Activated**\n\n"
        f"Scientist stalled after {consecutive} rejections at score {best_score:.4f}.\n"
        f"Kuhn agent activated with fresh injection:\n"
        f"• Assumption: {assumption[:80]}\n"
        f"• Domain: {domain[:80]}\n\n"
        f"Pairs remaining: {pairs_remaining} out of 384."
    )
    notify(msg)

    print(f"\nHandoff complete.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Scientist-to-Kuhn plateau handoff")
    parser.add_argument("--force", action="store_true", help="Handoff regardless of plateau count")
    parser.add_argument("--check", action="store_true", help="Report only, don't change anything")
    parser.add_argument("--plateau", type=int, default=PLATEAU_THRESHOLD, help=f"Plateau threshold (default {PLATEAU_THRESHOLD})")
    args = parser.parse_args()

    do_handoff(force=args.force, check_only=args.check, plateau_threshold=args.plateau)


if __name__ == "__main__":
    main()
