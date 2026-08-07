#!/usr/bin/env python3
"""
Kuhn-to-Scientist handoff for ProteinGym.

Transfers a winning Kuhn paradigm to the Scientist workspace:
1. Verifies Kuhn best_so_far beats the handoff threshold
2. Copies strategy to Scientist workspace
3. Resets Scientist's history and working files
4. Writes a paradigm context file for the Scientist
5. Disables Kuhn cron, enables Scientist cron
6. Sends notification

Usage:
    python3 kuhn_handoff.py                    # Check + handoff if threshold met
    python3 kuhn_handoff.py --force            # Handoff regardless of threshold
    python3 kuhn_handoff.py --check            # Just report, don't change anything
"""

import json, os, sys, re, shutil, argparse, datetime

from pg_common import (
    KUHN_WS, SCIENTIST_WS,
    SCIENTIST_CRON_ID, KUHN_CRON_ID,
    read_history, get_best_score, get_scientist_best,
    toggle_cron, notify, reset_history, copy_strategy,
)


def get_kuhn_best_score(from_run=None):
    """Read the best score from Kuhn's history.jsonl.
    If from_run is specified, use that run's score."""
    entries = read_history(os.path.join(KUHN_WS, "history.jsonl"))
    if not entries:
        return 0, None

    if from_run is not None:
        for entry in entries:
            if entry.get("run") == from_run:
                return entry.get("score", 0) or 0, entry

    # Fall back to best across all runs
    best_score = 0
    best_entry = None
    for entry in entries:
        score = entry.get("score", 0) or 0
        if score > best_score:
            best_score = score
            best_entry = entry
    return (best_score if best_entry else 0), best_entry


def get_kuhn_injection():
    """Read the current Kuhn injection (assumption + domain)."""
    path = os.path.join(KUHN_WS, "KUHN_INJECTION.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def get_rationale_from_history(history_entry):
    """Extract the assumption, domain, and hypothesis from a history entry."""
    if not history_entry:
        return None, None, ""

    hypothesis = history_entry.get("hypothesis", "") or ""
    plan = history_entry.get("plan", "") or ""
    combined = hypothesis + "\n" + plan

    assumption = None
    domain = None

    m = re.search(r'(?:Current paradigm(?:\s+assumes?)?(?:\s*:\s*)|assumption(?:\s+is)?(?:\s*:\s*))\*?"([^"]+)"', combined, re.IGNORECASE)
    if not m:
        m = re.search(r'"(Each mutation[^"]+)"', combined)
    if not m:
        m = re.search(r'"(Harm can be[^"]+)"', combined)
    if m:
        assumption = m.group(1)

    domain_patterns = [
        r'[Ii]mported domain:?\s*\*?"?([^\n"])',
        r'[Dd]omain:?\s*\*?"?([^\n"])',
        r'[Ff]rom\s+(\w[^\n]{10,80})',
    ]
    for pat in domain_patterns:
        m = re.search(pat, combined)
        if m:
            domain = m.group(1).strip().rstrip('.')
            break

    if not assumption or not domain:
        injection = get_kuhn_injection()
        if injection:
            if not assumption:
                assumption = injection.get("assumption") or injection.get("assumption_to_violate")
            if not domain:
                domain = injection.get("domain") or injection.get("imported_domain")

    return assumption, domain, hypothesis


def do_handoff(force=False, check_only=False, from_run=None):
    """Perform the Kuhn→Scientist handoff."""
    kuhn_score, kuhn_entry = get_kuhn_best_score(from_run=from_run)
    scientist_score = get_scientist_best()
    if scientist_score == 0.0:
        print("Scientist history empty — cannot handoff")
        return False
    threshold = scientist_score  # Must beat the current best to hand off

    print(f"Kuhn best: {kuhn_score:.4f} (run {kuhn_entry.get('run', '?') if kuhn_entry else '?'})")
    print(f"Scientist best: {scientist_score:.4f}")
    print(f"Threshold (must beat best): {threshold:.4f}")

    if kuhn_score <= threshold and not force:
        if not check_only:
            print(f"Below threshold — no handoff.")
        return False

    if check_only:
        print("Would handoff (use without --check to execute)")
        return False

    # 0. CRITICAL: Disable Kuhn cron FIRST to prevent race condition
    toggle_cron(KUHN_CRON_ID, enabled=False)

    # 1. Copy Kuhn best strategy → Scientist workspace
    if not copy_strategy(KUHN_WS, SCIENTIST_WS):
        print("  ERROR: Kuhn best_so_far_strategy.py not found")
        return False
    print("  Copied Kuhn best → Scientist strategy files")

    # 1b. Git commit the handoff so the winning strategy is never lost
    import subprocess as _sp
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        scientist_best_rel = os.path.relpath(os.path.join(SCIENTIST_WS, "best_so_far_strategy.py"), repo_root)
        scientist_hist_rel = os.path.relpath(os.path.join(SCIENTIST_WS, "history.jsonl"), repo_root)
        _sp.run(["git", "-C", repo_root, "add", scientist_best_rel, scientist_hist_rel],
                capture_output=True, text=True, timeout=30)
        _sp.run(["git", "-C", repo_root, "commit", "-m",
                 f"kuhn→scientist handoff: score {kuhn_score:.4f} (run {kuhn_entry.get('run', '?')})"],
                capture_output=True, text=True, timeout=30)
        print("  Git committed handoff strategy")
    except Exception as e:
        print(f"  WARNING: git commit failed: {e}")

    # 2. Set Scientist history baseline to the Kuhn handoff score
    #    (don't wipe — the Scientist needs to know what it's beating)
    import json as _json
    scientist_hist = os.path.join(SCIENTIST_WS, "history.jsonl")
    handoff_entry = {
        "run": 1,
        "score": round(kuhn_score, 6),
        "best_score": round(kuhn_score, 6),
        "verdict": "baseline",
        "note": f"Kuhn handoff (run {kuhn_entry.get('run', '?')}). Scientist previous best: {round(scientist_score, 6)}.",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    with open(scientist_hist, "w") as f:
        f.write(_json.dumps(handoff_entry) + "\n")
    print(f"  Set Scientist history baseline: {kuhn_score:.4f} (Kuhn handoff)")

    # 3. Write paradigm context
    assumption, domain, hypothesis = get_rationale_from_history(kuhn_entry)

    # Read full reasoning from Kuhn workspace artifacts
    kuhn_output = ""
    output_path = os.path.join(KUHN_WS, "KUHN_OUTPUT.md")
    if os.path.exists(output_path):
        with open(output_path) as f:
            kuhn_output = f.read()

    kuhn_plan = (kuhn_entry.get("plan", "") or "") if kuhn_entry else ""

    # Get injection directly (more reliable than regex)
    injection = get_kuhn_injection()
    if not assumption and injection:
        assumption = injection.get("assumption", "")
    if not domain and injection:
        domain = injection.get("domain", "")

    context_path = os.path.join(SCIENTIST_WS, "paradigm_context.md")
    with open(context_path, "w") as f:
        f.write("# Paradigm Context from Kuhn Handoff\n\n")
        f.write("## Previous Paradigm Limitation\n")
        f.write(f"The Scientist plateaued at {scientist_score:.4f} avg Spearman.\n\n")
        f.write("## Kuhn Paradigm\n\n")
        f.write(f"**Assumption violated:** {assumption}\n\n")
        f.write(f"**Imported domain:** {domain}\n\n")
        f.write(f"**Hypothesis:**\n\n{hypothesis}\n")
        if kuhn_plan:
            f.write(f"\n## Paradigm Plan (Steps 1-4)\n\n{kuhn_plan}\n")
        if kuhn_output:
            f.write("\n## Full Kuhn Agent Reasoning\n\n")
            f.write("*The following is the Kuhn agent's extended reasoning, "
                     "analogies, and reflections that led to this paradigm.*\n\n")
            f.write(kuhn_output)
    print("  Wrote paradigm_context.md")

    # 4. Enable Scientist cron (Kuhn already disabled in step 0)
    toggle_cron(SCIENTIST_CRON_ID, enabled=True)

    print("\nHandoff complete — Scientist activated with new paradigm.")
    return True


def send_handoff_notification(score, assumption, domain, from_run=None):
    """Send a formatted handoff notification."""
    assumption_short = (assumption or "?")[:80]
    domain_short = (domain or "?")[:80]
    run_str = f" (Kuhn run #{from_run})" if from_run else ""
    beat = get_scientist_best()

    msg = (
        f"🔬 **Kuhn Paradigm Handoff**\n\n"
        f"Score: {score:.4f}{run_str}\n"
        f"Scientist best was: {beat:.4f}\n\n"
        f"Assumption violated: {assumption_short}\n"
        f"Imported domain: {domain_short}\n\n"
        f"The Scientist agent has been updated with the new paradigm. "
        f"History reset. Ready to iterate."
    )
    notify(msg)


def main():
    parser = argparse.ArgumentParser(description="Kuhn-to-Scientist handoff")
    parser.add_argument("--force", action="store_true", help="Handoff regardless of threshold")
    parser.add_argument("--check", action="store_true", help="Just report, don't change anything")
    parser.add_argument("--from-run", type=int, default=None, help="Use rationale from a specific Kuhn run")
    args = parser.parse_args()

    success = do_handoff(force=args.force, check_only=args.check, from_run=args.from_run)

    if success and not args.check:
        score, entry = get_kuhn_best_score(from_run=args.from_run)
        assumption, domain, _ = get_rationale_from_history(entry)
        send_handoff_notification(score, assumption, domain, from_run=args.from_run)


if __name__ == "__main__":
    main()
