# Protein Mutation Effect Prediction

## Your Task

You are predicting how harmful single amino acid mutations are to proteins.

**Input:** A wild-type protein sequence and a list of mutated sequences (same length, single or few positions changed).
**Output:** A harm score for each mutation. Higher = more harmful.

You write a Python function that scores mutations. The framework tests it against real experimental data.

## Function Signature

```python
def score_mutations(sequences, protein_id, wild_type, mutations, msa=None):
    """
    Given protein context and mutations, return predicted effect scores.
    
    Args:
        sequences: dict of {protein_id: wild_type_sequence_string}
        protein_id: string, the protein being scored
        wild_type: string, the wild-type sequence
        mutations: list of mutated sequence strings (same length as wild_type)
        msa: list of aligned sequences (subsampled to 10K max), or None
    
    Returns:
        list of float scores (same length as mutations). Higher = more harmful.
    """
```

## Scoring

Your scores are compared to experimental DMS (deep mutational scanning) measurements using **Spearman rank correlation**. Higher Spearman = better.

**Speed bonus:** max +0.002, sigmoid with inflection at 10s per protein.

**Score = average Spearman + average speed bonus across all 217 eval proteins.**

## What You Have

- `staging_smoke_trigger.json` — Write `{"request": "run"}` to trigger a 5-protein smoke test
- `staging_smoke_result.json` — Smoke test results (per-protein Spearman, elapsed)
- `best_so_far_strategy.py` — the current best algorithm
- `history.jsonl` — past experiment results and scores. **Read this** to see what approaches have been tried and what scores they achieved.
- MSAs are passed as the `msa` argument (list of aligned sequences, max 10K)
- **Pre-computed data** — import `proteingym_data` for:
  - 5 SOTA model predictions per mutation (VenusREM, S3F_MSA, ESM2_15B, ProSST-2048, GEMME)
  - Physicochemical features per mutation (blosum62, delta_charge, delta_volume, delta_hydro, wt_aa, mut_aa)
  - Per-residue structure (RSA, burial class)
  - Protein metadata (MSA depth, taxon, assay type)
  - **Read `DATA_REFERENCE.md` for complete API documentation** — all functions, return types, and fields
  - **Read `TECHNIQUES.md` for advanced MSA-derived features** (epistatic fit, co-evolution coupling, multi-order conservation) with copy-paste code

## Evaluation

- **Smoke test:** 5 proteins, ~30 seconds
- **Full eval:** 217 proteins, ~8 minutes
- **Baseline:** 0.2364 (BLOSUM62 + MSA conservation)

## Security

You may import: numpy, math, scipy.stats, collections, proteingym_data, any python standard library
You may NOT: use open(), eval(), exec(), subprocess, os, sys, socket, or any file I/O.
All data is passed to your function as arguments or via the proteingym_data library.

## Key Insight

Five pre-computed SOTA models are available via `proteingym_data.get_model_scores()`, spanning maximum signal diversity: structure+MSA (VenusREM, S3F_MSA), pure sequence (ESM2_15B), quantized structure tokens (ProSST-2048), and pure evolutionary alignment (GEMME). Individual models score 0.45-0.52 Spearman. Ensembling and correction functions on top of these can push higher. The question is: what fundamentally different approach to combining or correcting these signals could break through?
