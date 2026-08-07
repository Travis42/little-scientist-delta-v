# SEF (Scientific Experiment Framework) — Architecture

**Project:** ProteinGym — Protein Mutation Effect Prediction
**Last updated:** 2026-08-06

---

## Overview

An autonomous LLM agent iteratively improves a protein mutation effect prediction algorithm using a structured scientific method. The agent writes strategy code that scores how harmful amino acid mutations are to proteins, tests it locally via a sandboxed smoke test, then submits it for external evaluation against real deep mutational scanning (DMS) data from the ProteinGym benchmark. The agent never sees experimental labels — it receives only performance metrics (Spearman correlation + diagnostics) and must form hypotheses about why its algorithm improves or fails.

This is the second deployment of the SEF framework. The first was Motif Discovery (DNA ChIP-seq). ProteinGym reuses the same architecture — two-agent system, smoke test gating, event-driven validator, Kuhn paradigm exploration — adapted to a fundamentally different domain: protein biophysics instead of DNA sequence analysis.

## Why Classic Algorithms? The Interpretability Advantage

SEF produces **human-readable algorithms**, not black-box models. Each iteration proposes a hand-written scoring function — classic Python code with interpretable parameters. The end result isn't a neural network with billions of opaque weights. It's a function you can read, understand, and reason about.

This matters because the classic ML tradeoff has been: *ML performs better but you can't understand it.* If SEF closes that gap, the classic algorithm wins on multiple axes:

- **Interpretability** — you can point to exactly which features matter and why. The algorithm is a sequence of named operations with meaningful parameters, not a matrix of floating-point weights.
- **Auditability** — the evolution history (`history.jsonl`) shows *why* each change was made. Every accepted improvement records the hypothesis that motivated it, the score delta, and which proteins improved or regressed.
- **Deployability** — no GPU, no model server, no framework dependencies beyond numpy/scipy. The final algorithm runs anywhere Python runs, in under 2 seconds per protein.
- **Trust** — a computational biologist or structural scientist can read the code and say "yes, that makes biological sense" or "this is overfitting to a quirk of the benchmark."
- **Distillation of learning** — the agent's iterative discoveries become permanent, readable knowledge. Each accepted strategy encodes something the system learned about the problem domain.

The SEF framework makes this possible because the agent writes code, not parameters. The search space is the space of *algorithms*, not the space of *weights*.

## What Makes ProteinGym Different from Motif

The Motif project (SEF v1) had the agent write a scoring algorithm from scratch — a PWM-scoring function over DNA sequences. The agent had to discover signal extraction techniques itself.

ProteinGym is fundamentally different: **five state-of-the-art pre-computed models** are available via a data library (`proteingym_data`). The agent's job is not to build a predictor from raw data, but to find systematic errors in the best available models and correct them. This shifts the problem from *signal extraction* to *error correction* — a different cognitive task that requires different reasoning.

The agent builds an ensemble of 5 models (VenusREM, S3F_MSA, ESM2_15B, ProSST-2048, GEMME) and applies per-mutation corrections based on physicochemical features, structural context, and evolutionary signals that the models may have missed.

---

## Scoring

**Primary metric: Spearman rank correlation** — how well the strategy's predicted harm scores rank mutations in the same order as experimental DMS measurements. Perfect = 1.0, random = 0.0.

**Speed bonus (small):** Sigmoid, max +0.002, inflection at 10 seconds per protein. Formula: `0.002 / (1 + exp(0.5 * (elapsed_s - 10)))`. Current best strategy takes <2s/protein, so bonus is near max.

**Score = average Spearman across all 217 DMS proteins + average speed bonus.** Current all-time best: **0.5691**.

**Baseline reference points:**
- VenusREM verbatim (SOTA single model): 0.5547
- Naive ensemble (no calibration): ~0.02 (scale mismatch destroys signal)
- Random: 0.0

---

## The Pre-Computed Model Data

Five SOTA models are available via `proteingym_data.get_model_scores()`:

| Model | What it is | Avg Spearman | Score Range |
|-------|-----------|--------------|-------------|
| VenusREM | Structure + MSA retrieval ensemble (current SOTA) | 0.518 | ~-8 to +2 |
| ProSST K=2048 | Quantized 3D structure tokens + sequence | 0.507 | ~-30 to -20 |
| S3F_MSA | Sequence-based statistical model using MSA frequencies | 0.496 | ~-5 to +4 |
| GEMME | Pure alignment-based evolutionary model (no ML) | 0.455 | ~-30 to +5 |
| ESM2_15B | Pure-sequence protein language model (largest ESM2) | 0.453 | ~-30 to +6 |

These five span the maximum diversity of signal sources: structure-aware retrieval, discrete 3D encoding, statistical frequencies, pure evolutionary conservation, and neural language modeling.

**Additional data per mutation:**
- Physicochemical features: `blosum62`, `delta_charge`, `delta_volume`, `delta_hydro`
- Per-residue structure: `rsa` (relative solvent accessibility), `burial_class` (buried/core/intermediate/surface)
- Protein metadata: `msa_num_seqs`, `msa_n_eff`, `coarse_selection_type` (Stability/Activity/Expression/OrganismalFitness/Binding), `taxon`, `source_organism`

**Sign convention:** All model scores correlate positively with DMS experimental scores (negative = more harmful). Predictions are returned as-is — never sign-flipped.

**Label safety:** The database contains no `DMS_score` — label leakage is impossible by construction.

---

## Feedback Design: Structured Diagnostics

The evaluator does not return only a scalar score. It produces two levels of structured feedback:

### Level 1: Raw per-protein data

Per-protein breakdowns: Spearman correlation, speed bonus, elapsed time, mutation count, MSA depth for all 217 evaluation proteins.

### Level 2: Curated analysis

Generated by the validator's `write_diagnostics()` function:
- Aggregate Spearman stats (mean, best, worst, bottom quartile)
- Speed statistics
- **Key Insights** — computed interpretation of results: score calibration, error direction bias, worst/best substitution classes, MSA depth effect, mutation load effect, assay type effect, conservation-error correlation, structural context (core vs surface errors)
- Weakest 20 proteins with MSA depth and mutation count
- **Mutation-Level Error Analysis** — for each bottom-5 protein: 3 worst-predicted mutations with position, substitution class, predicted vs expected scores, and error direction
- MSA depth vs performance grouping (high >=100 seqs vs low vs none)
- SOTA reference points and gap

This curated analysis is the agent's primary lens for forming hypotheses. Without it, the agent would be blind to *why* a score changed. The diagnostics surface enables targeted hypotheses like "core positions show 5x larger errors than surface — structure-based penalties at buried sites should help."

---

## Two-Agent System

### SEF Scientist (Exploitation)

Iteratively refines the current best algorithm. Runs on a continuous schedule. Each cycle: reads context -> fills out a scientific reasoning worksheet -> writes `staging_strategy.py` -> triggers smoke test -> validator scores it. If accepted (score > best), becomes new `best_so_far_strategy.py`.

### Kuhn Paradigm-Interrogation Agent (Exploration) — Currently Disabled

The Kuhn agent's purpose is not to top the Scientist's score on its own. It is to **change the paradigm** — to find a structurally different approach that the Scientist can then exploit to escape a local optimum that normal iterative refinement cannot overcome. A successful Kuhn run produces a strategy that is not reachable by parameter adjustment of the current best; it opens a new basin of the search space for the Scientist to explore. Whether the Kuhn agent's own score is higher is secondary — what matters is whether it gives the Scientist access to a region of strategy space it couldn't reach by incremental refinement.

It works by **reframing the problem** rather than refining within the existing paradigm:

**How it works:**

1. An assumption from the current paradigm is selected for violation (e.g., "Model predictions are already calibrated")
2. A domain outside bioinformatics is imported (e.g., economics, crystallography, materials science) that contains structurally analogous problems
3. The Kuhn agent receives a prompt that forces it to reason within this reframed space — it must violate the chosen assumption and build an algorithm inspired by the imported domain
4. The agent iterates using the same smoke test infrastructure
5. If the result beats the all-time best, it is handed off to the Scientist workspace as `best_so_far_strategy.py` for exploitation refinement

The key design property is that the injection is **externally assigned** — the Kuhn agent does not choose its own assumption or domain. This forces a search-radius jump beyond what it would naturally select.

**Injection space:** 16 assumptions x 24 domains = **384 pairs**, tried sequentially and tracked in `KUHN_STATE.json`.

---

## Benchmark Tiers

| Tier | Data | Timeout | Purpose |
|------|------|---------|---------|
| Smoke test (Tier 1) | 5 DMS proteins, full mutation sets | 300s/protein | Agent's local iteration loop. Results are reused by eval. |
| Validator eval (Tier 2) | 217 DMS proteins, full mutation sets | 300s/protein | Scoring surface for accept/reject. Reuses smoke results for the 5 shared proteins. |
| Industry benchmark | Published ProteinGym leaderboard | — | Comparison vs published SOTA models (VenusREM, Tranception, ESM-if, etc.) |

### Smoke Test Proteins (Tier 1)

The 5 proteins are chosen to span the signal diversity of the benchmark:

| Protein | Taxon | Assay Type | MSA N_eff |
|---------|-------|-----------|-----------|
| A4_HUMAN_Seuma_2022 | Human | Stability | 62 |
| PTEN_HUMAN_Mighell_2018 | Human | Activity | 1,501 |
| SPIKE_SARS2_Starr_2020_binding | Virus | Binding | 1,347 |
| A0A192B1T2_9HIV1_Haddox_2018 | Virus | OrganismalFitness | 36,470 |
| A0A247D711_LISMN_Stadelmann_2021 | Prokaryote | Activity | 9 |

### Validator Eval (Tier 2)

The full ProteinGym substitution benchmark — 217 deep mutational scanning datasets spanning:
- **Taxa:** Viral, bacterial, human, yeast, plant, archaeal
- **Assay types:** Stability, Activity, Expression, OrganismalFitness, Binding
- **MSA depths:** 0 (no alignment) to 1.9M sequences (subsampled to 10K)
- **Mutation counts:** ~900 to ~500K per protein
- **Multi-mutants:** 72% of entries are multi-mutant combinations

---

## Components

### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/proteingym_validate_and_eval.sh` | The validator. Validates code security, runs eval, records result, archives strategy, runs sanitizer. |
| `scripts/proteingym_eval.py` | Tier 2 eval: 217 DMS proteins, Spearman + speed bonus. |
| `scripts/proteingym_smoke.py` | Tier 1 smoke test: 5 DMS proteins, 300s timeout each. |
| `scripts/smoke_test_watcher.py` | systemd service. Watches both workspaces for triggers, runs smoke test, triggers validator on pass. Also handles code review injection (diff computation). |
| `scripts/pg_kuhn_selector.py` | Selects next untried (assumption, domain) pair for Kuhn injection. 384 total pairs. |
| `scripts/kuhn_handoff.py` | Copies Kuhn strategy to Scientist workspace on successful handoff. |
| `scripts/pg_common.py` | Shared utilities: paths, history parsing, notification stubs, workspace operations. |
| `scripts/proteingym_data.py` | Data library exposing model predictions, structure data, and protein metadata via SQLite. |
| `scripts/build_proteingym_db.py` | Builds the SQLite database from raw model outputs and structure files. |
| `scripts/setup.sh` | Provisioning script: validates deps, installs watcher service, configures logrotate, runs sanity checks. |

### Data

| Path | Purpose |
|------|---------|
| `data/DMS_ProteinGym_substitutions/` | 217 DMS CSV files (experimental mutation scores) |
| `data/DMS_msa_files/` | Multiple sequence alignments (A2M format) per protein |
| `data/proteingym_data.db` | SQLite DB: model predictions, physicochemical features, structure data, protein metadata |

---

## Security Model

**Strategy code can:**
- Import: numpy, math, scipy, sklearn, collections, re, itertools, any Python standard library, `proteingym_data`
- Use: function arguments (`sequences`, `protein_id`, `wild_type`, `mutations`, `msa`)
- Return: list of floats (same length as `mutations`), higher = more harmful

**Strategy code cannot:**
- Import: `subprocess`, `os`, `sys`, `socket`, `shutil`, `http`, `urllib`, `requests`
- Use: `open()`, `eval()`, `exec()`, `__import__`, `globals()`, `locals()`, `getattr()`, `setattr()`
- Access: any file I/O, any network, any process spawning
- Exceed: 200 KB source size, 300s per protein runtime

**Enforcement:** Pattern matching on source code (regex scan before evaluation). The `proteingym_data` library opens a read-only SQLite connection (`mode=ro`) that cannot lock or corrupt the database.

---

## Agent Workflow (Scientist)

Each cycle:

1. **Read context** — `history.jsonl` (last line), `staging_diagnostics.md` (full), `scratch.md`, `causal_model.md`, `best_so_far_strategy.py`, `structure_summaries/` (selective)
2. **Handle crashes** — if last run scored 0.0, fix bug in `best_so_far_strategy.py`
3. **Fill out worksheet** — copy `worksheet_template.md` -> `staging_worksheet.md`, fill all 6 sections:
   - Prior Run Falsification Check
   - Evidence Synthesis (last ~10 experiments)
   - Hypothesis Formation
   - Assumption Chain (3 iterations)
   - Experiment Design
   - Causal Model Update
4. **Write prediction** — `staging_prediction.json` with expected Spearman range
5. **Write code** — copy `best_so_far_strategy.py` -> `staging_strategy.py`, make changes
6. **Code review (mandatory)** — trigger diff injection, verify each change matches hypothesis, write `staging_code_reviewed` marker
7. **Smoke test (mandatory)** — trigger, wait ~30s, read result, iterate if needed
8. **Finalize** — write hypothesis, update causal model, write blockers
9. **Submit and exit** — validator runs automatically after smoke passes

---

## Validator Workflow

1. **Acquire lock** — atomic mkdir-based lock in workspace
2. **Check staging** — `staging_strategy.py` exists, passes security scan
3. **Smoke gate** — verify `staging_smoke_passed.json` exists and is fresh (<90 min)
4. **Promote** — copy staging -> `eval/<workspace_name>/strategy.py`
5. **Run eval** — `proteingym_eval.py` on 217 proteins (~8 min)
6. **Parse score** — average Spearman + average speed bonus
7. **Compare to best** — strictly greater to accept
8. **If accepted:** commit, update `all_time_best.txt`, copy to `best_so_far_strategy.py`, archive
9. **If rejected:** save to `last_attempt_strategy.py`, archive, revert staging
10. **Write feedback** — `staging_eval_result.json`, `staging_eval_details.json`, `staging_diagnostics.md`
11. **Append history** — `history.jsonl` (run, score, delta, verdict, hypothesis, top improved/regressed)
12. **Sanitize workspace** — remove non-allowlisted files
13. **Kuhn handoff check** — if Kuhn workspace and score > all_time_best, trigger handoff
14. **Select next Kuhn injection** — if Kuhn workspace, pick next untried pair
15. **Notification** — post result summary
