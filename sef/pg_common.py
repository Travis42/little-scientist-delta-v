#!/usr/bin/env python3
"""
Shared utilities for ProteinGym SEF scripts.

All handoff scripts and utilities import from here to avoid duplication.
Single source of truth for: paths, history parsing, workspace operations.
"""

import json
import os
import subprocess
import sys

# ─── Path Constants ──────────────────────────────────────────────────
REPO_ROOT = os.environ.get(
    "PROTEINGYM_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
SCIENTIST_WS = os.path.join(REPO_ROOT, "workspace")
KUHN_WS = os.environ.get(
    "KUHN_WORKSPACE",
    os.path.join(os.path.dirname(REPO_ROOT), "kuhn-workspace"),
)
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
DATA_DIR = os.path.join(REPO_ROOT, "data", "DMS_ProteinGym_substitutions")

# ─── Cron Job IDs ────────────────────────────────────────────────────
# These are placeholders — set SCIENTIST_CRON_ID and KUHN_CRON_ID in your
# environment if you wire up a cron/scheduler system.
SCIENTIST_CRON_ID = os.environ.get("SCIENTIST_CRON_ID", "")
KUHN_CRON_ID = os.environ.get("KUHN_CRON_ID", "")


# ─── History Operations ──────────────────────────────────────────────

def read_history(path):
    """Read all entries from a history.jsonl file.
    Returns a list of dicts. Empty list if file doesn't exist or is empty."""
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def get_best_score(entries):
    """Get the highest accepted score from history entries.
    Falls back to best_score field if no accepted entries exist."""
    best = 0
    for entry in entries:
        if entry.get("verdict") == "accepted":
            score = entry.get("score", 0) or 0
            if score > best:
                best = score
    if best == 0:
        for entry in entries:
            score = entry.get("best_score", 0) or 0
            if score > best:
                best = score
    return best


def count_consecutive_rejections(entries):
    """Count consecutive non-accepted runs from the end of history.
    Resets to 0 on any 'accepted' verdict or improved=True entry.
    no_code_review entries are skipped (neither count nor break)."""
    count = 0
    for entry in reversed(entries):
        verdict = entry.get("verdict", "")
        if verdict == "accepted" or entry.get("improved") is True:
            break
        if verdict in ("rejected", "false_positive", "git_error", "validation_failed"):
            count += 1
        elif verdict in ("", None) and entry.get("improved") is False:
            count += 1
        # else: no_code_review or other — skip without counting or breaking
    return count


def get_scientist_best():
    """Read the Scientist's current best score from its history.jsonl."""
    entries = read_history(os.path.join(SCIENTIST_WS, "history.jsonl"))
    return get_best_score(entries)


def get_all_time_best():
    """Read the all-time best score across all cycles. Used for Kuhn handoff threshold."""
    path = os.path.join(SCIENTIST_WS, "all_time_best.txt")
    try:
        with open(path) as f:
            return float(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0.0


def update_all_time_best(score):
    """Update all_time_best.txt if score exceeds current record."""
    path = os.path.join(SCIENTIST_WS, "all_time_best.txt")
    current = get_all_time_best()
    if score > current:
        with open(path, 'w') as f:
            f.write(f"{score:.4f}\n")
        return True
    return False


def get_kuhn_best():
    """Read the Kuhn workspace's best score from its history.jsonl."""
    entries = read_history(os.path.join(KUHN_WS, "history.jsonl"))
    return get_best_score(entries)


# ─── Cron Operations ─────────────────────────────────────────────────

def toggle_cron(job_id, enabled):
    """Toggle a cron job via scheduler CLI.
    Returns True on success, False on failure.
    No-op if job_id is empty."""
    if not job_id:
        print(f"  cron toggle skipped (no job_id configured)", file=sys.stderr)
        return False
    try:
        scheduler_cmd = os.environ.get("CRON_CLI", "crontab")
        cmd = [scheduler_cmd, "enable" if enabled else "disable", job_id]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print(f"  cron {'enabled' if enabled else 'disabled'}: {job_id[:8]}...")
            return True
        else:
            err = (result.stderr or result.stdout or "")[:200]
            print(f"  cron toggle failed: {err}")
            return False
    except Exception as e:
        print(f"  cron toggle error: {e}")
        return False


def enable_scientist():
    """Enable Scientist cron and disable Kuhn cron."""
    toggle_cron(KUHN_CRON_ID, False)
    toggle_cron(SCIENTIST_CRON_ID, True)


def enable_kuhn():
    """Disable Scientist cron and enable Kuhn cron."""
    toggle_cron(SCIENTIST_CRON_ID, False)
    toggle_cron(KUHN_CRON_ID, True)


# ─── Notification Operations ─────────────────────────────────────────

def notify(msg, topic=0):
    """Notification stub — prints to stderr instead of sending to a chat service.
    Replace this with your own notification backend if desired."""
    print(f"[notify] {msg}", file=sys.stderr)


# ─── Workspace Utilities ─────────────────────────────────────────────

def reset_history(workspace_path):
    """Clear a workspace's history.jsonl (truncate to empty)."""
    with open(os.path.join(workspace_path, "history.jsonl"), "w") as f:
        f.write("")


def copy_strategy(src_workspace, dst_workspace):
    """Copy best_so_far_strategy.py from src to dst workspace.
    Writes to best_so_far, staging_strategy, and last_attempt."""
    src = os.path.join(src_workspace, "best_so_far_strategy.py")
    for filename in ("best_so_far_strategy.py", "staging_strategy.py", "last_attempt_strategy.py"):
        dst = os.path.join(dst_workspace, filename)
        if os.path.exists(src):
            import shutil
            shutil.copy2(src, dst)
            os.chmod(dst, 0o644)
    return os.path.exists(src)
