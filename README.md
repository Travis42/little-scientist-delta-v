# The Little Scientist: Delta V

**Autonomous LLM-driven protein mutation effect prediction via the Little Scientist framework**

This repository contains the Delta V strategy and evaluation pipeline that achieved state-of-the-art results on the [ProteinGym](https://proteingym.org) benchmark for zero-shot prediction of mutation effects. The strategy was discovered autonomously by LLM agents operating within the SEF (Scientific Experiment Framework), an iterative code-search system where agents write, test, and refine interpretable scoring algorithms.

---
## Results

Full evaluation on all 217 ProteinGym DMS substitution assays (2026-08-07):

| Aggregation Method | Delta V (ours) | VenusREM (SOTA) | Advantage |
|---|---|---|---|
| Flat mean (217 assays) | 0.5690 | 0.5357 | +6.2% |
| UniProt mean (186 proteins) | 0.5698 | 0.5379 | +5.9% |
| **Official (category mean)** | **0.5511** | **0.5151** | **+7.0%** |

### Category Breakdown vs ProteinGym Leaderboard

| Category | Delta V | AIDO Protein-RAG | VenusREM | ProSST-2048 | S3F_MSA | GEMME |
|---|---|---|---|---|---|---|
| Activity | **0.551** | 0.517 | 0.495 | 0.476 | 0.502 | 0.487 |
| Binding | 0.470 | 0.426 | 0.454 | 0.445 | 0.440 | 0.396 |
| Expression | **0.572** | 0.522 | 0.533 | 0.487 | 0.510 | 0.439 |
| OrganismalFitness | **0.520** | 0.491 | 0.459 | 0.438 | 0.430 | 0.399 |
| Stability | 0.642 | 0.635 | **0.650** | **0.653** | 0.581 | 0.537 |

Bold = best in column. Delta V leads 3 of 5 categories.

Full per-protein results: [`results/full_eval_2026-08-07.json`](results/full_eval_2026-07-07.json)
Detailed findings: [`results/findings_2026-08-07.md`](results/findings_2026-08-07.md)

---

## Method

### Delta V Strategy

The strategy (`strategy/delta_v_strategy.py`) implements a multi-stage pipeline:

1. **Quantile calibration** — redistributes model score distributions to correct systematic compression/expansion (2.3x harmful-tail expansion)
2. **Z-score normalization** — brings all five models to a common scale
3. **Confidence-weighted ensemble** — blends predictions from VenusREM, S3F_MSA, ESM2_15B, ProSST-2048, and GEMME using per-model confidence scaling
4. **Residual propagation** — 3 iterations of position-specific correction using structural similarity (RSA-based weighting)
5. **Power transformation** — x^0.7 dynamic range expansion to amplify tail signal
6. **Structure-based penalties** — assay-specific multipliers for charge, volume, hydrophobicity changes at buried residues
7. **GEMME conservation modulation** — Shannon entropy-based per-position weight adjustment

The algorithm is pure Python with numpy — no GPU, no neural network inference, runs in under 2 seconds per protein.

### How It Was Discovered

The strategy was produced by autonomous LLM agents using the SEF framework:

- A **Scientist agent** iteratively refined the algorithm across hundreds of cycles, each time forming a hypothesis, writing code, testing it on a 5-protein smoke test, and submitting it for full evaluation
- A **Kuhn agent** attempted paradigm-breaking approaches by importing structural logic from outside domains (e.g., signal processing, thermodynamics, crystallography) to challenge fixed assumptions in the current paradigm
- The agent received only Spearman correlation scores and structured diagnostics — never the ground-truth labels — and had to reason about *why* changes helped or hurt

See [`sef/SEF_ARCHITECTURE.md`](sef/SEF_ARCHITECTURE.md) for the full framework architecture.

---

## Requirements

- Python 3.10+
- numpy
- scipy

```bash
pip install numpy scipy
```

---

## Repository Structure

```
little_scientist-delta-v/
├── strategy/
│   └── delta_v_strategy.py           Delta V strategy (the final algorithm)
├── eval/
│   ├── proteingym_eval.py            Full 217-protein evaluation harness
│   ├── proteingym_smoke.py           5-protein smoke test
│   ├── proteingym_data.py            Read-only data access library (SQLite)
│   └── run_official_performance.py   Official ProteinGym 5-metric scorer
├── sef/
│   ├── SEF_ARCHITECTURE.md           Framework architecture documentation
│   ├── proteingym_validate_and_eval.sh   Validator + evaluator pipeline
│   ├── smoke_test_watcher.py         Watcher service (triggers smoke/eval)
│   ├── pg_common.py                  Shared utilities
│   ├── pg_kuhn_selector.py           Kuhn injection pair selector
│   ├── pg_preflight.py              Timing pre-flight validator
│   ├── kuhn_handoff.py               Kuhn->Scientist handoff
│   ├── scientist_to_kuhn_handoff.py  Scientist->Kuhn handoff
│   ├── build_proteingym_db.py        Database builder from raw model outputs
│   ├── compute_asa.py                Solvent accessibility from structures
│   ├── download_structures.py        AlphaFold structure downloader
│   ├── setup.sh                      Infrastructure provisioning
│   └── config/
│       └── timings.json              Timing configuration
├── workspace/                        Agent workspace templates
│   ├── program.md                    Problem description and function signature
│   ├── AGENT_PROMPT.md               Full scientist agent prompt
│   ├── DATA_REFERENCE.md             Data API docs (single source of truth)
│   ├── DATA_PRIMER.md                Model descriptions and properties
│   ├── TECHNIQUES.md                 Advanced MSA feature code
│   ├── causal_model.md               Paradigm documentation
│   ├── paradigm_context.md           Kuhn handoff context format
│   ├── worksheet_template.md         Agent iteration worksheet
│   └── ... (SOUL.md, IDENTITY.md, etc.)
├── kuhn/                             Kuhn agent workspace templates
│   ├── AGENT_PROMPT.md               Kuhn agent prompt
│   ├── program.md                    Problem description
│   └── ... (DATA_REFERENCE.md, TECHNIQUES.md, etc.)
├── tests/
│   ├── test_proteingym_data.py       Data library tests
│   └── test_validator.py             Validator tests
├── data/
│   └── README.md                     Data download instructions
└── results/
    ├── official_performance/         Official ProteinGym results (5 metrics)
    ├── official_benchmark_summary.md Full benchmark writeup
    ├── official_benchmark_log.txt    Complete run log
    ├── full_eval_2026-08-07.json     Per-protein results (217 assays)
    └── findings_2026-08-07.md        Analysis and findings
```

---

## Usage

### Quick Start

```bash
git clone https://github.com/Travis42/little-scientist-delta-v.git
cd little-scientist-delta-v
pip install -r requirements.txt

# Option A: Download all data from ProteinGym (~36 GB)
python3 sef/setup_data.py --download

# Option B: Use existing ProteinGym data you already have
python3 sef/setup_data.py --local /path/to/your/proteingym_data

# Verify: run the final strategy on all 217 proteins
python3 eval/proteingym_eval.py --dir strategy/
```

The `setup_data.py` script handles everything: downloading DMS assays, model scores, MSA files, building the SQLite database, and optionally downloading AlphaFold structures for RSA features. Use `--local` if you already have the ProteinGym data package — it'll skip re-downloading 36 GB and go straight to building the database.

For full data setup details, see [`data/README.md`](data/README.md).

### Running the Evaluation

The strategy requires a pre-built SQLite database containing model predictions from the five SOTA models. Data paths are configured via environment variables:

```bash
export PROTEINGYM_DATA=/path/to/DMS_ProteinGym_substitutions
export PROTEINGYM_REFERENCE=/path/to/DMS_substitutions.csv
export PROTEINGYM_MSA=/path/to/DMS_msa_files
export PROTEINGYM_DB=/path/to/proteingym_data.db

# Run full evaluation (217 proteins)
python3 eval/proteingym_eval.py --dir strategy/

# Run smoke test (5 proteins)
python3 eval/proteingym_smoke.py --workspace strategy/
```

The strategy module (`delta_v_strategy.py`) must expose:

```python
def score_mutations(sequences, protein_id, wild_type, mutations, msa=None):
    """Returns list of floats (same length as mutations). Higher = more harmful."""
    ...
```

### Building the Database

The database is built automatically by `setup_data.py`. To build manually:

```bash
export PROTEINGYM_SCORES_DIR=/path/to/model_score_csvs
export PROTEINGYM_REFERENCE=/path/to/DMS_substitutions.csv
export PROTEINGYM_DB_OUTPUT=/path/to/proteingym_data.db

python3 sef/build_proteingym_db.py
```

**What goes into the DB:**
- **model_scores table** — predictions from VenusREM, S3F_MSA, ESM2_15B, ProSST-2048, GEMME (the 5 ensemble inputs), plus computed physicochemical features (delta_charge, delta_volume, delta_hydrophobicity, BLOSUM62)
- **residue_structure table** — per-position relative solvent accessibility (RSA) and burial class from AlphaFold structures
- **protein_info table** — metadata (MSA depth, taxon, selection type, mutation counts)

**What the strategy ALSO needs (not in the DB):**
- **MSA files** (`.a2m`, 4.9 GB) — loaded at runtime by the eval harness and passed to the strategy as the `msa` parameter. The strategy uses them for Shannon entropy position-conservation features. **These are required to reproduce the reported Spearman scores.** Without them, the strategy degrades gracefully (conservation features zero out) but scores will be lower. Both our eval harness (`proteingym_eval.py`) and the smoke test load these files — it's not the official ProteinGym script that needs them, it's ours.
- **DMS assay CSVs** — ground-truth experimental data. Only used by the eval harness to compute Spearman correlation. The strategy never sees these values.

No ground-truth labels (`DMS_score`) are ever stored in the database; label leakage is impossible by construction.

### Setting Up the SEF Framework (Autonomous Evolution)

To run the full SEF framework with autonomous LLM agents iterating on the strategy:

1. Read [`docs/OPENCLAW_SETUP.md`](docs/OPENCLAW_SETUP.md) for OpenClaw agent and cron job configuration
2. Copy workspace templates: `cp -r workspace/ /path/to/your/workspace/`
3. Copy Kuhn templates: `cp -r kuhn/ /path/to/your/kuhn-workspace/`
4. Install the smoke test watcher service
5. Configure the Scientist and Kuhn agent cron jobs

The framework runs two agents: a **Scientist** that iteratively refines the algorithm, and a **Kuhn** agent that attempts paradigm-breaking approaches when the Scientist plateaus.

### Data Access API

Strategies access model predictions via the `proteingym_data` library:

```python
from proteingym_data import get_model_scores, get_residue_structure, get_protein_info

scores = get_model_scores(protein_id, mutations)
# -> {mutant: {"venus_rem": float, "s3f_msa": float, "esm2_15b": float,
#              "prosst_2048": float, "gemme": float, "wt_aa": str, ...}}

structure = get_residue_structure(protein_id)
# -> {position: {"rsa": float, "burial_class": str, ...}}

info = get_protein_info(protein_id)
# -> {"coarse_selection_type": str, "msa_num_seqs": int, ...}
```

---

## Benchmark

This code evaluates against the **ProteinGym** benchmark — the standard suite of 217 deep mutational scanning substitution assays for zero-shot mutation effect prediction.

- Benchmark site: [https://proteingym.org](https://proteingym.org)
- Leaderboard: [https://proteingym.org/benchmarks](https://proteingym.org/benchmarks)

---

## Code Availability

All code needed to reproduce the evaluation results is provided in this repository. The strategy algorithm (`strategy/delta_v_strategy.py`) is fully self-contained and deterministic. Pre-computed model predictions from VenusREM, S3F_MSA, ESM2_15B, ProSST-2048, and GEMME can be obtained from the ProteinGym benchmark download.

---

## Citation

Smith, Travis. (2026). The Little Scientist: Hypothesis-Driven Iterative Algorithm Discovery by LLM Agents. Zenodo. https://doi.org/10.5281/zenodo.21907349

If you use this code or build on the Delta V strategy before the paper is published, please reference this repository and the Zenodo deposit.

---

## License

Apache License 2.0. See [LICENSE](LICENSE).

Includes an explicit patent grant and patent retaliation clause — anyone who contributes grants patent rights to all users, and loses their license if they initiate patent litigation against the project.

Copyright (c) 2026 Travis Smith.
