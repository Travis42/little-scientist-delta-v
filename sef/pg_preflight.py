#!/usr/bin/env python3
"""
ProteinGym SEF timing pre-flight validator.

Run this after changing any timing value in config/timings.json.
Verifies all timing constraints are satisfiable and no component
will silently break.

Usage:
    python3 pg_preflight.py                    # check config consistency
    python3 pg_preflight.py --cron-interval N  # simulate changing cron interval
    python3 pg_preflight.py --fix              # auto-fix safe adjustments
"""

import json, os, sys

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "timings.json")
PROJECT_ROOT = os.environ.get(
    "PROTEINGYM_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

# Cron job IDs — set via environment if using a scheduler
SCIENTIST_CRON_ID = os.environ.get("SCIENTIST_CRON_ID", "")
KUHN_CRON_ID = os.environ.get("KUHN_CRON_ID", "")


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def get_cron_interval():
    """Get current Scientist cron interval from scheduler (if available)."""
    if not SCIENTIST_CRON_ID:
        return 1800  # default
    try:
        import subprocess
        scheduler_cmd = os.environ.get("CRON_CLI", "crontab")
        result = subprocess.run(
            [scheduler_cmd, "get", SCIENTIST_CRON_ID],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("schedule", {}).get("everyMs", 1800000) // 1000
    except Exception:
        pass
    return 1800  # default


def get_kuhn_cron_interval():
    """Get current Kuhn cron interval from scheduler (if available)."""
    if not KUHN_CRON_ID:
        return 1800
    try:
        import subprocess
        scheduler_cmd = os.environ.get("CRON_CLI", "crontab")
        result = subprocess.run(
            [scheduler_cmd, "get", KUHN_CRON_ID],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("schedule", {}).get("everyMs", 1800000) // 1000
    except Exception:
        pass
    return 1800


def get_agent_timeout():
    """Get Scientist agent timeout from cron payload (if available)."""
    if not SCIENTIST_CRON_ID:
        return 1200
    try:
        import subprocess
        scheduler_cmd = os.environ.get("CRON_CLI", "crontab")
        result = subprocess.run(
            [scheduler_cmd, "get", SCIENTIST_CRON_ID],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("payload", {}).get("timeoutSeconds", 1200)
    except Exception:
        pass
    return 1200


def check_timing_constraints(cfg, cron_interval, agent_timeout):
    """Verify all timing constraints. Returns list of (severity, message) issues."""
    issues = []
    warnings = []

    smoke_timeout = cfg.get("smoke_timeout_seconds", 600)
    validator_timeout = cfg.get("validator_timeout_seconds", 1800)
    code_review_grace = cfg.get("code_review_grace_seconds", 600)
    debounce = cfg.get("debounce_seconds", 60)
    eval_per_protein = cfg.get("eval_per_protein_timeout_seconds", 300)

    # Constraint 1: Cron interval must exceed TYPICAL cycle time
    typical_agent = int(agent_timeout * 0.6)
    typical_smoke = 60  # 1 min
    typical_eval = 360  # 6 min
    typical_cycle = typical_agent + typical_smoke + typical_eval
    if cron_interval <= typical_cycle:
        issues.append(
            f"CRITICAL: Cron interval ({cron_interval}s) <= typical cycle time "
            f"(agent ~{typical_agent}s + smoke ~{typical_smoke}s + eval ~{typical_eval}s = {typical_cycle}s). "
            f"Agent won't finish before next cycle fires."
        )
    elif cron_interval <= typical_cycle * 1.3:
        warnings.append(
            f"Cron interval ({cron_interval}s) is tight vs typical cycle ({typical_cycle}s). "
            f"Buffer is only {cron_interval - typical_cycle}s. Consider widening."
        )

    # Constraint 2: Agent timeout should allow for code review + smoke + write
    min_agent_time = code_review_grace + 120
    if agent_timeout < min_agent_time:
        issues.append(
            f"CRITICAL: Agent timeout ({agent_timeout}s) < minimum needed "
            f"(code review grace {code_review_grace}s + 120s buffer = {min_agent_time}s). "
            f"Agent will be killed before completing its cycle."
        )

    # Constraint 3: Code review grace must be less than agent timeout
    if code_review_grace >= agent_timeout:
        issues.append(
            f"CRITICAL: Code review grace ({code_review_grace}s) >= agent timeout ({agent_timeout}s). "
            f"Watcher will wait longer than the agent's lifetime."
        )

    # Constraint 4: Debounce should be less than cron interval
    if debounce >= cron_interval:
        warnings.append(
            f"Debounce window ({debounce}s) >= cron interval ({cron_interval}s). "
            f"Legitimate re-triggers within the same cycle will be dropped."
        )

    # Constraint 5: Eval per-protein timeout x 217 proteins should fit in validator timeout
    worst_eval = eval_per_protein * 217
    if worst_eval > validator_timeout:
        warnings.append(
            f"WARNING: Worst-case eval ({eval_per_protein}s x 217 proteins = {worst_eval}s) "
            f"exceeds validator timeout ({validator_timeout}s). Most proteins finish in <10s, "
            f"but a pathological strategy could timeout."
        )

    # Constraint 6: Smoke pass max age should be < cron interval x 2
    smoke_pass_age = cfg.get("smoke_pass_max_age_minutes", 90) * 60
    if smoke_pass_age < cron_interval:
        warnings.append(
            f"Smoke pass max age ({smoke_pass_age//60} min) < cron interval ({cron_interval//60} min). "
            f"Pass marker could expire between cycles."
        )

    return issues, warnings


def check_component_sync(cfg):
    """Verify scripts are reading from config, not hardcoded values."""
    issues = []
    warnings = []

    # Check watcher has config loading code
    watcher_path = os.path.join(PROJECT_ROOT, "scripts", "smoke_test_watcher.py")
    if os.path.exists(watcher_path):
        with open(watcher_path) as f:
            watcher = f.read()
        if "load_timings" not in watcher:
            issues.append("Watcher does not load timings.json — still using hardcoded values")

    # Check validator has config loading
    validator_path = os.path.join(PROJECT_ROOT, "scripts", "proteingym_validate_and_eval.sh")
    if os.path.exists(validator_path):
        with open(validator_path) as f:
            validator = f.read()
        if "TIMINGS_FILE" not in validator:
            issues.append("Validator does not load timings.json — still using hardcoded values")

    # Check eval has config loading
    eval_path = os.path.join(PROJECT_ROOT, "scripts", "proteingym_eval.py")
    if os.path.exists(eval_path):
        with open(eval_path) as f:
            eval_script = f.read()
        if "timings.json" not in eval_script:
            issues.append("Eval script does not load timings.json — still using hardcoded values")

    return issues, warnings


def main():
    import argparse
    p = argparse.ArgumentParser(description="ProteinGym SEF timing pre-flight validator")
    p.add_argument("--cron-interval", type=int, default=None, help="Simulate this cron interval (seconds)")
    p.add_argument("--fix", action="store_true", help="Auto-fix safe adjustments")
    args = p.parse_args()

    print("=" * 60)
    print("  ProteinGym SEF — Timing Pre-Flight Validator")
    print("=" * 60)

    cfg = load_config()
    cron_interval = args.cron_interval if args.cron_interval else get_cron_interval()
    kuhn_interval = get_kuhn_cron_interval()
    agent_timeout = get_agent_timeout()
    cfg_interval = cfg.get("cron_interval_seconds", 1800)

    print(f"\nCurrent Configuration:")
    print(f"  Config cron interval:    {cfg_interval}s ({cfg_interval//60} min)")
    print(f"  Actual Scientist cron:   {cron_interval}s ({cron_interval//60} min)")
    print(f"  Actual Kuhn cron:        {kuhn_interval}s ({kuhn_interval//60} min)")
    print(f"  Agent timeout:           {agent_timeout}s ({agent_timeout//60} min)")
    print(f"  Smoke timeout:           {cfg.get('smoke_timeout_seconds', 600)}s")
    print(f"  Validator timeout:       {cfg.get('validator_timeout_seconds', 1800)}s")
    print(f"  Code review grace:       {cfg.get('code_review_grace_seconds', 600)}s")
    print(f"  Debounce:                {cfg.get('debounce_seconds', 60)}s")
    print(f"  Eval per-protein:        {cfg.get('eval_per_protein_timeout_seconds', 300)}s")
    print(f"  Stale lock age:          {cfg.get('validator_stale_lock_seconds', 600)}s")
    print(f"  Smoke pass max age:      {cfg.get('smoke_pass_max_age_minutes', 90)} min")
    print(f"  Min progress delta:      {cfg.get('min_progress_delta', 0.0005)}")

    # Check config vs actual cron
    if cfg_interval != cron_interval:
        print(f"\n  Config interval ({cfg_interval}s) != actual cron ({cron_interval}s)")
        if args.fix:
            print("  Auto-fix: updating config to match actual cron...")
            cfg["cron_interval_seconds"] = cron_interval
            with open(CONFIG_PATH, "w") as f:
                json.dump(cfg, f, indent=2)
            print(f"  Config updated to {cron_interval}s")

    # Run constraint checks
    print(f"\nConstraint Checks:")
    issues, warnings = check_timing_constraints(cfg, cron_interval, agent_timeout)

    comp_issues, comp_warnings = check_component_sync(cfg)
    issues.extend(comp_issues)
    warnings.extend(comp_warnings)

    for issue in issues:
        print(f"  [FAIL] {issue}")
    for w in warnings:
        print(f"  [WARN] {w}")

    if not issues and not warnings:
        print(f"  [OK] All timing constraints satisfied.")

    # Summary
    print(f"\n{'=' * 60}")
    if issues:
        print(f"  [FAIL] {len(issues)} critical issue(s), {len(warnings)} warning(s)")
        print(f"  Fix these before relying on the system.")
        sys.exit(1)
    elif warnings:
        print(f"  [WARN] {len(warnings)} warning(s), no critical issues")
        sys.exit(0)
    else:
        print(f"  [OK] All clear.")
        sys.exit(0)


if __name__ == "__main__":
    main()
