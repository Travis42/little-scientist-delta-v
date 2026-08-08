# Delta V — Official ProteinGym Benchmark Results

**Date:** 2026-08-08
**Benchmark:** ProteinGym DMS substitutions (217 assays)
**Strategy:** `workspace/best_so_far_strategy.py` (Pure CPCWE + power-transform dynamic-range expansion)
**Comparison set:** 96 zero-shot models with scores in the official merged files (+ 2 absent models reported as NaN)

---

## Headline result

Delta V is the **#1 model on all five official ProteinGym metrics**, evaluated against 96 scored
zero-shot substitution predictors. Aggregation follows the official ProteinGym pipeline
(mean of per-selection-type UniProt-level means).

| Rank | Model | Spearman | AUC | MCC | NDCG | Top_recall |
|---:|---|---:|---:|---:|---:|---:|
| **1** | **Delta V** | **0.551** | **0.801** | **0.430** | **0.800** | **0.254** |
| 2 | VenusREM | 0.518 | 0.783 | 0.404 | 0.770 | 0.244 |
| 3 | ProSST (K=2048) | 0.507 | 0.777 | 0.398 | 0.757 | 0.236 |
| 4 | ProSST (K=4096) | 0.498 | 0.773 | 0.385 | 0.774 | 0.232 |
| 5 | S3F-MSA | 0.496 | 0.771 | 0.387 | 0.792 | 0.243 |
| 6 | S2F-MSA | 0.488 | 0.767 | 0.381 | 0.790 | 0.240 |
| 7 | ProSST (K=1024) | 0.485 | 0.764 | 0.372 | 0.761 | 0.230 |
| 8 | ESCOTT | 0.476 | 0.761 | 0.370 | 0.779 | 0.213 |
| 9 | ProSST (K=512) | 0.471 | 0.757 | 0.360 | 0.759 | 0.222 |
| 10 | S3F | 0.470 | 0.757 | 0.371 | 0.769 | 0.233 |
| 11 | PoET (200M) | 0.470 | 0.759 | 0.368 | 0.784 | 0.226 |
| 12 | ProSST (K=128) | 0.469 | 0.757 | 0.363 | 0.754 | 0.227 |
| 13 | ESM3 open (1.4B) | 0.466 | 0.755 | 0.367 | 0.777 | 0.242 |
| 14 | RSALOR | 0.465 | 0.754 | 0.366 | 0.777 | 0.224 |
| 15 | VespaG | 0.458 | 0.754 | 0.362 | 0.776 | 0.205 |

> Ranking is by `Average_Spearman` (the official Summary ordering). Delta V holds rank 1 on every
> metric independently (confirmed against 96 scored models; 2 models absent from the merged files —
> `AIDO.Protein-RAG-16B` and `Protriever` — are NaN and excluded).

**Margin over the next-best model (VenusREM):**
Spearman +0.033, AUC +0.018, MCC +0.026, NDCG +0.030, Top_recall +0.010.

---

## Delta V detail

**Per-DMS Spearman** (217 assays): mean **0.569**, median 0.584, min 0.064, max 0.860.
Positive correlation on **217 / 217** assays.

**Spearman by selection type:**

| Activity | Binding | Expression | OrganismalFitness | Stability |
|---:|---:|---:|---:|---:|
| 0.549 | 0.486 | 0.554 | 0.523 | 0.642 |

**Spearman by MSA depth:** Low 0.530 · Medium 0.563 · High 0.597
**Spearman by taxon:** Human 0.555 · Other Eukaryote 0.605 · Prokaryote 0.575 · Virus 0.563
**Spearman by mutation depth:** 1 mut 0.563 · 2 mut 0.385 · 3 mut 0.423 · 4 mut 0.380 · 5+ 0.393

---

## Pipeline documentation

Every step below is logged with timestamps to the corresponding log file.

### Step 1 — Prediction generation
- **Script:** `scripts/official_benchmark.py` (new file)
- **Command:** `python3 scripts/official_benchmark.py 2>&1 | tee results/official_benchmark_log.txt`
- **Inputs:**
  - Strategy: `workspace/best_so_far_strategy.py`
  - Merged score files (per-assay, ~95 model columns): `./data/proteingym_scores/*.csv`
  - Reference: `data/DMS_substitutions.csv` · DMS data: `data/DMS_ProteinGym_substitutions/`
  - MSAs: `data/DMS_msa_files/` · Model scores/structure DB: `data/proteingym_data.db`
- **Output:** `results/official_merged_scores/*.csv` (217 files, each original file + `Delta_V` column)
- **Per protein:** load WT + MSA (reservoir-subsampled exactly as `proteingym_eval.load_msa`) → run
  `score_mutations(sequences=…, protein_id=…, wild_type=…, mutations=…, msa=…)` → append `Delta_V`.
  Mutations are read directly from each merged file's `mutant` column to guarantee row alignment.
- **Result:** 217/217 succeeded, 0 failed, 0 skipped, 100% finite predictions, elapsed **718 s (~12 min)**.
- **Log:** `results/official_benchmark_log.txt` · manifest: `results/official_merged_scores/_manifest.json`

> **Strategy signature note.** The task brief stated the signature as
> `score_mutations(wt_seq, mutations, msa, all_sequences, workspace_dir)`. The actual function in
> `best_so_far_strategy.py` is `score_mutations(sequences, protein_id, wild_type, mutations, msa=None)`,
> which is exactly how `proteingym_eval._process_single_protein` (line 358) calls it. The harness uses
> the real signature.

### Step 2 — Performance computation (official ProteinGym pipeline)
- **Script:** official `proteingym/performance_DMS_benchmarks.py` (unmodified)
- **Command:**
  ```
  python3 ../../proteingym/performance_DMS_benchmarks.py \
    --input_scoring_files_folder results/official_merged_scores/ \
    --output_performance_file_folder results/official_performance/ \
    --DMS_reference_file_path data/DMS_substitutions.csv \
    --DMS_data_folder data/DMS_ProteinGym_substitutions/ \
    --config_file results/config_with_delta_v.json \
    --performance_by_depth
  ```
- **Config:** `results/config_with_delta_v.json` — a copy of the official `config.json` with a
  `Delta_V` entry added to `model_list_zero_shot_substitutions_DMS`. The official `config.json` was
  **not** modified (no existing source files were touched). The official `constants.json` is read
  from its own location; Delta V has no `model_details`/`references` entry there so those columns
  are blank for Delta V (cosmetic only).
- **Metrics computed (all official formulas):** Spearman (`scipy.stats.spearmanr`), AUC
  (`roc_auc_score` on `DMS_score_bin`), MCC (`matthews_corrcoef` vs median split), NDCG
  (`calc_ndcg`, top-10% quantile), Top_recall (`calc_toprecall`, top-10%). Aggregation is the
  official hierarchical mean: per-selection-type mean of per-UniProt means.
- **Bootstrap note.** The official 10 000-iteration bootstrap standard-error step (a secondary
  column, not one of the 5 required metrics) plus severe DataFrame fragmentation (~600 columns from
  98 models × 6 depth groups) exceeded the run timeout. It was run via `results/run_official_performance.py`,
  a thin wrapper that calls the **unaltered official `main()`** with the two bootstrap helpers
  monkey-patched to 200 iterations. All five metrics and every output file are produced by the
  official code path; only the non-essential `Bootstrap_standard_error` column is approximate.
- **Result:** official `main()` finished in **1975 s (~33 min)**. All 217 DMS scored for all 5 metrics.
- **Log:** `results/official_performance_log.txt`

### Output file inventory (`results/official_performance/`)
For each metric in {Spearman, AUC, MCC, NDCG, Top_recall}:
- `Summary_performance_DMS_substitutions_<metric>.csv` / `.html` — ranked model summary
- `DMS_substitutions_<metric>_DMS_level.csv` / `.html` — per-assay scores (217 rows)
- `DMS_substitutions_<metric>_Uniprot_level.csv` — per-UniProt
- `DMS_substitutions_<metric>_Uniprot_Selection_Type_level.csv` — per (UniProt, selection type)

### Other artifacts
- `results/config_with_delta_v.json` — config copy with Delta V
- `results/run_official_performance.py` — wrapper for the official performance script
- `results/official_benchmark_log.txt` — Step 1 log
- `results/official_performance_log.txt` — Step 2 log

---

## Methodology notes
- The Delta V strategy is an ensemble (CPCWE) of `venus_rem`, `s3f_msa`, `esm2_15b`, `prosst_2048`,
  `gemme` with quantile calibration, confidence-weighted residual propagation, conservation-modulated
  GEMME weighting, structure-aware penalties, and a `x^0.7` power transform for dynamic-range
  expansion. It consumes only model predictions + structure/MSA features — no ground-truth labels.
- Predictions are added as a single new `Delta_V` column; all 95 pre-existing model columns are
  carried through unchanged, so the comparison is apples-to-apples on the exact same 217 assays.
- Two models in the official config (`AIDO.Protein-RAG-16B`, `Protriever`) have no scores in the
  merged files and are reported as NaN (excluded from the 96 scored models).
