# Packaging Spec: Make Delta V Repo Fully Reproducible

**Date:** 2026-08-08
**Author:** Apprentice
**Goal:** A person who clones the repo can reproduce the entire SEF evolution pipeline — not just run the final strategy, but run the framework that discovered it.

---

## Current State Assessment

### What the public repo HAS (good):
- ✅ Final strategy code (`strategy/delta_v_strategy.py`)
- ✅ Full eval harness (`eval/proteingym_eval.py`, `proteingym_smoke.py`, `proteingym_data.py`)
- ✅ DB builder script (`sef/build_proteingym_db.py`)
- ✅ SEF orchestration scripts (`sef/*.py`, `sef/*.sh`)
- ✅ SEF architecture documentation (`sef/SEF_ARCHITECTURE.md`)
- ✅ Official benchmark results (`results/official_performance/`)
- ✅ Kuhn agent prompt (`kuhn/AGENTS.md`)
- ✅ Setup script (`sef/setup.sh`)

### What the public repo is MISSING:

#### Critical gaps (blocks reproduction):

1. **No agent workspace templates.** The SEF framework needs a workspace directory with agent-facing documents that tell the LLM what to do. These exist locally in `proteingym/workspace/` but aren't in the public repo:
   - `program.md` — problem description, function signature, rules
   - `AGENT_PROMPT.md` — full agent prompt (257 lines)
   - `DATA_REFERENCE.md` — data API docs the agent reads (141 lines)
   - `DATA_PRIMER.md` — model descriptions and known properties (387 lines)
   - `TECHNIQUES.md` — advanced MSA feature code the agent can use (295 lines)
   - `causal_model.md` — paradigm documentation for the agent
   - `paradigm_context.md` — Kuhn handoff context format
   - `worksheet_template.md` — the agent's iteration worksheet
   - `SOUL.md`, `IDENTITY.md`, `USER.md` — agent persona files
   - `HEARTBEAT.md` — agent heartbeat checklist
   - `TOOLS.md` — agent tools reference

2. **No `workspace/` directory at all.** The SEF scripts reference workspace paths (e.g., `proteingym/workspace/staging_strategy.py`) but the workspace directory structure doesn't exist in the public repo. Someone running `setup.sh` would have no templates to seed a new workspace from.

3. **DB builder is untested end-to-end.** `build_proteingym_db.py` exists but requires the user to download ~31GB of raw model scores from ProteinGym. The README says "one CSV per protein with columns mutant, VenusREM, S3F_MSA, ESM2_15B, ProSST-2048, GEMME" — but the actual ProteinGym download has ~100 model columns per file, not 5. The builder needs to handle the real file format (selecting the right 5 columns from the merged score files).

4. **No structure data pipeline.** The strategy uses `get_residue_structure()` which reads from the DB's `residue_structure` table. But the DB builder doesn't populate this table. Locally this was built by `scripts/compute_asa.py` and `scripts/download_structures.py` (not in public repo) which fetch AlphaFold structures and compute relative solvent accessibility.

5. **No MSA file download instructions.** The strategy can optionally use MSA files (4.9GB, 217 .a2m files). The eval script looks for them at `data/DMS_msa_files/` but there's no download script or instructions in the repo.

6. **Kuhn injection pairs not documented.** The `pg_kuhn_selector.py` reads from a list of (assumption, domain) pairs, but the actual pairs used (visible in `KUHN_STATE.json` locally) aren't in the public repo. A reproducer wouldn't know what paradigm challenges were tried.

#### Moderate gaps (inconvenient but not blocking):

7. **No evolution history.** The local `workspace/history.jsonl` and `archives/` directory contain the full evolution trajectory (100+ strategies tried). This is valuable for understanding how the agent arrived at Delta V. Not strictly needed to reproduce, but important for the paper.

8. **Kuhn workspace files missing.** `pg-kuhn-workspace/` has its own `best_so_far_strategy.py`, `program.md`, `SOUL.md`, etc. These are the Kuhn agent's working files. The SEF scripts reference them (`kuhn_handoff.py`, `scientist_to_kuhn_handoff.py`) but the templates aren't in the repo.

9. **`run_official_performance.py` missing.** This wrapper (which calls the official ProteinGym performance script with patched bootstrap) exists locally in `results/` but wasn't copied to the public repo.

10. **Tests missing.** Local `tests/test_proteingym_data.py` and `tests/test_validator.py` aren't in the public repo.

#### Minor gaps (nice to have):

11. **`.gitignore` for workspace artifacts.** Running the SEF framework generates staging files, history, etc. Need a .gitignore that keeps the templates but ignores generated files.

12. **No `requirements.txt`.** The README says "pip install numpy scipy" but there's no requirements file. Also need `pandas` for the DB builder and benchmark scripts.

---

## Proposed Structure

```
little_scientist-delta-v/
├── README.md                          (update: add full reproduction instructions)
├── LICENSE
├── requirements.txt                   (NEW)
├── .gitignore                         (NEW)
│
├── strategy/
│   └── delta_v_strategy.py            (existing — final algorithm)
│
├── eval/
│   ├── proteingym_eval.py             (existing)
│   ├── proteingym_smoke.py            (existing)
│   ├── proteingym_data.py             (existing)
│   └── run_official_performance.py    (NEW — from local results/)
│
├── sef/
│   ├── SEF_ARCHITECTURE.md            (existing)
│   ├── build_proteingym_db.py         (existing — FIX: handle real score format)
│   ├── proteingym_validate_and_eval.sh (existing)
│   ├── smoke_test_watcher.py          (existing)
│   ├── pg_common.py                   (existing)
│   ├── pg_kuhn_selector.py            (existing)
│   ├── pg_preflight.py                (existing)
│   ├── kuhn_handoff.py                (existing)
│   ├── scientist_to_kuhn_handoff.py   (existing)
│   ├── setup.sh                       (existing — update for new dirs)
│   ├── compute_asa.py                 (NEW — from local scripts/)
│   ├── download_structures.py         (NEW — from local scripts/)
│   └── config/
│       └── timings.json               (existing)
│
├── workspace/                         (NEW — agent workspace templates)
│   ├── program.md                     (from local workspace/)
│   ├── AGENT_PROMPT.md                (from local workspace/)
│   ├── DATA_REFERENCE.md              (from local workspace/)
│   ├── DATA_PRIMER.md                 (from local workspace/)
│   ├── TECHNIQUES.md                  (from local workspace/)
│   ├── causal_model.md                (from local workspace/)
│   ├── paradigm_context.md            (from local workspace/)
│   ├── worksheet_template.md          (from local workspace/)
│   ├── SOUL.md                        (from local workspace/)
│   ├── IDENTITY.md                    (from local workspace/)
│   ├── USER.md                        (from local workspace/)
│   ├── HEARTBEAT.md                   (from local workspace/)
│   ├── TOOLS.md                       (from local workspace/)
│   └── .gitignore                     (NEW — ignore staging_*, history.jsonl, etc.)
│
├── kuhn/                              (NEW — Kuhn workspace templates)
│   ├── AGENTS.md                      (existing)
│   ├── program.md                     (from pg-kuhn-workspace/)
│   ├── SOUL.md                        (from pg-kuhn-workspace/)
│   ├── IDENTITY.md                    (from pg-kuhn-workspace/)
│   ├── DATA_REFERENCE.md              (from pg-kuhn-workspace/)
│   ├── TECHNIQUES.md                  (from pg-kuhn-workspace/)
│   ├── TOOLS.md                       (from pg-kuhn-workspace/)
│   ├── USER.md                        (from pg-kuhn-workspace/)
│   ├── worksheet_template.md          (from pg-kuhn-workspace/)
│   └── .gitignore                     (NEW)
│
├── tests/                             (NEW)
│   ├── test_proteingym_data.py        (from local tests/)
│   └── test_validator.py              (from local tests/)
│
├── data/
│   └── README.md                      (NEW — download instructions for all 3 data sources)
│
└── results/                           (existing)
    ├── official_performance/          (existing)
    ├── official_benchmark_summary.md  (existing)
    ├── official_benchmark_log.txt     (existing)
    ├── config_with_delta_v.json       (existing)
    ├── findings_2026-08-07.md         (existing)
    ├── full_eval_2026-08-07.json      (existing)
    └── run_official_performance.py    (REMOVE — moved to eval/)
```

---

## Work Items

### Phase 1: Agent Workspace Templates (critical, ~1 hour)

Copy 13 workspace template files from `proteingym/workspace/` to `workspace/` in the public repo. Sanitize any local paths. Create `.gitignore` for generated artifacts.

Copy 8 Kuhn workspace templates from `pg-kuhn-workspace/` to `kuhn/` in the public repo.

**Effort:** Low. Files exist, just need copying and path sanitization.

### Phase 2: Data Pipeline (critical, ~3 hours)

**2a. Fix `build_proteingym_db.py`:** The current builder expects 5-column CSVs. The real ProteinGym download (`zero_shot_substitutions_scores.zip`) provides merged score files with ~100 columns. Fix the builder to:
- Read the real merged score file format
- Select the correct 5 model columns by name
- Handle the `mutant` and `mutated_sequence` column naming
- Populate `residue_structure` table (or split into separate builder)

**2b. Add structure pipeline:** Copy `compute_asa.py` and `download_structures.py` from local `scripts/` to `sef/`. These download AlphaFold structures and compute RSA per position. Sanitize paths.

**2c. Write `data/README.md`:** Step-by-step instructions for:
1. Downloading DMS substitution CSVs from ProteinGym (link, expected size)
2. Downloading MSA files from ProteinGym (link, expected size)
3. Downloading pre-computed model scores (`zero_shot_substitutions_scores.zip`) (link, expected size, which CSVs to use)
4. Running `build_proteingym_db.py` to produce the SQLite database
5. Running the structure pipeline to populate residue structures
6. Verification: expected DB size, table row counts

**Effort:** Medium. Builder needs real-format fix. Structure pipeline needs AlphaFold API access (internet required, but deterministic).

### Phase 3: Missing Scripts (moderate, ~1 hour)

- Copy `run_official_performance.py` from `results/` to `eval/`
- Add `requirements.txt` with numpy, scipy, pandas, requests (for AlphaFold API)
- Update `setup.sh` to validate the new directory structure

### Phase 4: README Update (~1 hour)

Add a "Full Reproduction" section to README.md:
1. Clone repo
2. Download data (follow `data/README.md`)
3. Build database
4. Run evaluation
5. (Optional) Set up SEF framework for new evolution runs

### Phase 5: Tests (~30 min)

Copy test files, verify they pass against the public structure.

---

## What Does NOT Need to Be Done

- **No need to include the 617MB database.** The builder script + download instructions are the right approach.
- **No need to include raw DMS data (1GB) or MSA files (4.9GB).** These are downloadable from ProteinGym.
- **No need to include evolution history.** The `history.jsonl` and `archives/` are research artifacts, not reproduction requirements. Could be added later as supplementary material.
- **No need to include the merged score files (4.9GB).** Downloadable from ProteinGym.

---

## Critical Assessment

**How close are we?** Closer than I thought. The public repo already has the hard parts — strategy, eval, SEF orchestration, architecture docs. What's missing is:

1. **Workspace templates** — pure file copies, no logic changes needed
2. **DB builder fix** — needs to handle the real file format (~2 hours of coding)
3. **Structure pipeline** — two scripts need copying and sanitizing
4. **Data download instructions** — one README file

Total estimated effort: **~6 hours of focused work**, most of which is file copying, path sanitizing, and writing clear documentation. The only non-trivial coding task is fixing the DB builder to handle the real merged score format.

The hint that I'll be using this soon suggests we're about to start a new SEF domain (likely supervised substitutions). The packaging work IS the prep — making the framework reusable so a new domain can be spun up by copying the structure and swapping the data layer.

---

## Post-Mortem: Lessons from Supervised Substitutions Setup (2026-08-09)

When we adapted the Delta V framework for supervised substitutions, we hit several infrastructure issues that only surfaced during actual runs:

### Issues Found and Fixed

1. **Eval script path mismatch.** The validator referenced `scripts/proteingym_eval.py` but the file lives in `eval/`. Same for the smoke test. Fix: update `EVAL_SCRIPT` in validator and `SMOKE_SCRIPT` in watcher.

2. **PYTHONPATH missing eval/.** The strategy code imports `proteingym_data` from `eval/`, but the validator only added `scripts/` to PYTHONPATH. Fix: add `${PROJECT_ROOT}/eval` to PYTHONPATH in validator.

3. **Kuhn workspace path bug.** `pg_common.py` and `smoke_test_watcher.py` computed KUHN_WS as `dirname(REPO_ROOT)/kuhn-workspace`, which resolves to the parent directory — wrong when the repo and workspace are siblings. Fix: use `REPO_ROOT/kuhn-workspace` instead.

4. **last_attempt_strategy.py not saved on accept.** The validator only saved last_attempt on the reject path. On accept, best_so_far was overwritten without preserving the previous version. Fix: copy old best → last_attempt before overwriting.

5. **Diagnostics referenced old model names.** The diagnostic output hardcoded "VenusREM, S3F_MSA, ESM2_15B" and "VenusREM floor 0.50". Fix: parameterize model names and SOTA references.

6. **Transient staging files deleted by sanitizer.** `staging_code_reviewed`, `staging_smoke_trigger.json`, etc. were not in the sanitizer's whitelist and got cleaned up mid-flow. Fix: add to allowed set.

### Takeaway

When adapting the framework to a new domain, do a dry-run of the validator before starting the agent. The path and naming assumptions are baked into shell scripts and Python files that aren't obvious from the templates.
