# OpenClaw Agent Setup for SEF Framework

This guide explains how to configure OpenClaw agents and cron jobs to run the SEF (Scientific Experiment Framework) autonomously.

## Prerequisites

- [OpenClaw](https://github.com/openclaw/openclaw) installed and running
- Data set up (see `data/README.md` or run `python3 sef/setup_data.py`)
- The smoke test watcher systemd service installed (see below)

## Agent Configuration

Add two agents to your OpenClaw config (`openclaw.json` under `agents.list`):

### Scientist Agent

```json
{
  "id": "pg-scientist",
  "name": "ProteinGym SEF Agent",
  "workspace": "/path/to/repo/workspace",
  "model": {
    "primary": "zai/glm-4.7",
    "fallbacks": ["zai/glm-5-turbo"]
  },
  "heartbeat": { "every": "0s" },
  "tools": {
    "allow": ["read", "write", "edit", "web_search", "web_fetch"],
    "deny": ["sessions_spawn", "sessions_send", "message", "browser",
             "cron", "gateway", "image", "tts", "pdf", "memory_search",
             "memory_get", "canvas", "exec", "process"],
    "fs": { "workspaceOnly": true }
  }
}
```

The Scientist agent is sandboxed: it can only read/write files in its workspace, edit its strategy code, and search the web for ideas. It cannot run shell commands, spawn sub-agents, or send messages. This prevents label leakage and keeps the agent focused.

### Kuhn Agent

```json
{
  "id": "pg-kuhn",
  "name": "ProteinGym Kuhn Agent",
  "workspace": "/path/to/repo/../pg-kuhn-workspace",
  "model": {
    "primary": "zai/glm-4.7",
    "fallbacks": ["zai/glm-5-turbo"]
  },
  "heartbeat": { "every": "0s" },
  "tools": {
    "allow": ["read", "write", "edit", "web_search", "web_fetch"],
    "deny": ["sessions_spawn", "sessions_send", "message", "browser",
             "cron", "gateway", "image", "tts", "pdf", "memory_search",
             "memory_get", "canvas", "exec", "process"],
    "fs": { "workspaceOnly": true }
  }
}
```

The Kuhn agent has the same sandbox. Its workspace contains `KUHN_INJECTION.json` — the externally-assigned paradigm challenge that forces it to explore outside the current paradigm.

### Key design choices

- **Heartbeat off (`"every": "0s"`)**: Both agents are event-driven, not heartbeat-driven. They wake when triggered by cron or by the orchestrator (main agent).
- **No `exec`/`process`**: Agents cannot run shell commands. The only code execution happens through the smoke test / eval pipeline, which is controlled by the orchestrator.
- **`workspaceOnly: true`**: Agents cannot read outside their workspace. This means they cannot access the database or ground-truth labels directly. Data access is mediated by the eval harness.

## Cron Jobs

The SEF framework uses two cron jobs to drive the evolution loop:

### 1. Scientist Iteration (continuous)

```json
{
  "name": "ProteinGym Scientist Iteration",
  "schedule": { "kind": "every", "everyMs": 600000 },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "You are a research scientist optimizing a protein mutation prediction algorithm. Read your workspace files (AGENT_PROMPT.md, program.md, DATA_REFERENCE.md). Review your last attempt's results in staging_smoke_result.json. Form a hypothesis, write an improved strategy in staging_strategy.py, then signal readiness.",
    "model": "zai/glm-4.7",
    "timeoutSeconds": 600
  },
  "delivery": { "mode": "none" },
  "agentId": "pg-scientist",
  "enabled": false
}
```

Runs every 10 minutes. Each run, the agent reviews feedback from the previous attempt, forms a hypothesis, writes new code, and saves it to `staging_strategy.py`. The smoke test watcher picks up the new strategy, validates it, runs the eval, and feeds results back.

### 2. Kuhn Paradigm Cycle (nightly or on-demand)

```json
{
  "name": "ProteinGym Kuhn Cycle",
  "schedule": { "kind": "cron", "expr": "0 2 * * *", "tz": "UTC" },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "You are a paradigm-shifting researcher. Read KUHN_INJECTION.json for your assigned assumption to violate and imported domain to draw from. Study best_so_far_strategy.py and propose a fundamentally different approach.",
    "model": "zai/glm-4.7",
    "timeoutSeconds": 1800
  },
  "delivery": { "mode": "none" },
  "agentId": "pg-kuhn",
  "enabled": false
}
```

Runs nightly at 2 AM UTC. The Kuhn agent gets a new (assumption, domain) injection each cycle, produced by `pg_kuhn_selector.py`. If it produces a strategy that beats the current best on the smoke test, the handoff script promotes it back to the Scientist agent's workspace.

## Smoke Test Watcher

The systemd service that bridges agent output and evaluation:

```bash
# Install the watcher
sudo cp sef/smoke_test_watcher.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable smoke_test_watcher
sudo systemctl start smoke_test_watcher
```

The watcher monitors `workspace/staging_smoke_trigger.json`. When an agent writes a trigger:
1. Checks for `staging_code_reviewed` marker (agent verified code matches hypothesis)
2. Runs `eval/proteingym_smoke.py` (5-protein test, ~60 seconds)
3. If smoke passes: triggers `sef/proteingym_validate_and_eval.sh` (217 proteins, ~10 minutes)
4. Validator writes diagnostics, history, archives strategy, commits to git
3. Writes results to `workspace/staging_smoke_result.json`
4. If the new strategy beats the current best: promotes it to `best_so_far_strategy.py`, saves old best as `last_attempt_strategy.py`, git commits

## Orchestrator (Main Agent)

The main OpenClaw agent (your primary assistant) manages the meta-loop:

- Monitors Scientist progress via `workspace/history.jsonl`
- Triggers Kuhn cycles when the Scientist plateaus (5+ runs without improvement)
- Runs `scientist_to_kuhn_handoff.py` to transfer context
- Runs `kuhn_handoff.py` to promote winning Kuhn strategies back

This orchestration is done manually or via the main agent's heartbeat — not a fixed cron schedule.

## Directory Structure

The repo uses a specific layout that the scripts depend on:

```
sef/    ← SEF orchestration scripts (validator, watcher, handoff, db builder)
eval/   ← Evaluation scripts (eval, smoke test, data library)
workspace/  ← Scientist agent workspace templates
kuhn/       ← Kuhn agent workspace templates
data/       ← Data directory (DMS CSVs, MSA files, DB — not committed)
```

**Critical:** The eval scripts (`proteingym_eval.py`, `proteingym_smoke.py`, `proteingym_data.py`) live in `eval/`, not `scripts/`. The validator and watcher reference `eval/` paths. If you reorganize, update `EVAL_SCRIPT` in `proteingym_validate_and_eval.sh` and `SMOKE_SCRIPT` in `smoke_test_watcher.py`.

## Environment Variables

The eval scripts read these variables (with defaults):

``````
PROTEINGYM_DATA=data/DMS_ProteinGym_substitutions
PROTEINGYM_REFERENCE=data/DMS_substitutions.csv
PROTEINGYM_MSA=data/DMS_msa_files
PROTEINGYM_DB=data/proteingym_data.db
```

For the systemd watcher, set these in the service file's `Environment=` lines. Also set `PYTHONPATH` to include both `sef/` and `eval/` so the strategy can import `proteingym_data`.

## Full Configuration Sequence

```bash
# 1. Clone and set up data
git clone https://github.com/Travis42/little-scientist-delta-v.git
cd little-scientist-delta-v
pip install -r requirements.txt

# 2. Download data (or use --local if you already have ProteinGym data)
python3 sef/setup_data.py --download

# 3. Verify eval works on the final strategy
python3 eval/proteingym_eval.py --dir strategy/

# 4. Set up agents in openclaw.json (see above)

# 5. Install smoke test watcher
sudo cp sef/smoke_test_watcher.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now smoke_test_watcher

# 6. Create workspace from templates
cp -r workspace/ /path/to/sef-workspace/
cp -r kuhn/ /path/to/pg-kuhn-workspace/

# 7. Enable cron jobs via OpenClaw
# (Use the OpenClaw cron tool or UI to create the jobs described above)

# 8. Start the Scientist agent
# Send it its first message to bootstrap:
# "Read AGENT_PROMPT.md and program.md, then write your first strategy."
```

## Troubleshooting

**Eval crashes with "can't open file ... No such file or directory":**
The validator looks for eval scripts in `eval/`. If you moved them, update `EVAL_SCRIPT` in `sef/proteingym_validate_and_eval.sh` and `SMOKE_SCRIPT` in `sef/smoke_test_watcher.py`.

**Smoke test passes but eval crashes:**
Check that `PYTHONPATH` includes `eval/` so `proteingym_data` is importable. The systemd service should have `Environment=PYTHONPATH=/path/to/repo/eval:/path/to/repo/sef`.

**Agent can't import `proteingym_data`:**
The data library lives in `eval/proteingym_data.py`. The eval scripts add `eval/` to `sys.path` automatically, but if you run scripts from a different directory, set `PYTHONPATH` manually.

**Watcher finds wrong Kuhn workspace:**
`pg_common.py` and `smoke_test_watcher.py` compute `KUHN_WS` as `REPO_ROOT/../kuhn-workspace` by default. If your Kuhn workspace is inside the repo, set the `KUHN_WORKSPACE` environment variable.

**`last_attempt_strategy.py` not created:**
The validator saves the previous best as `last_attempt_strategy.py` before overwriting `best_so_far_strategy.py` on accept. It's also saved on reject (the rejected strategy becomes `last_attempt`).

**Git commits not happening:**
The validator auto-commits on accept. Ensure the repo has git configured (`git config user.name` and `user.email`) and the workspace is inside the git repo.
