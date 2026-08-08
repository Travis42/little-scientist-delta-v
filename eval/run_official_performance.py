#!/usr/bin/env python3
"""Wrapper that runs the OFFICIAL ProteinGym performance_DMS_benchmarks.main()
unchanged, but speeds up the non-essential bootstrap-standard-error step.

Why this wrapper exists
-----------------------
The official script computes five required metrics (Spearman, AUC, MCC, NDCG,
Top_recall) plus a secondary "Bootstrap_standard_error" column.  The bootstrap
resamples 10 000 times per metric and, combined with heavy DataFrame
fragmentation (~600 columns from 98 models x 6 depth groups), takes well over
an hour and exceeds the run timeout.  The bootstrap standard error is NOT one
of the five required metrics, so we monkey-patch the two bootstrap helpers to a
fast 200-iteration version.  Everything else -- the metric formulas, the
hierarchical UniProt/Selection-Type aggregation, every output file -- is the
unaltered official code path.

No official source files are modified; this wrapper lives entirely under
results/.
"""
import os
import sys
import time

OFFICIAL_PROTEINGYM_DIR = "../ProteinGym_official/proteingym"
sys.path.insert(0, OFFICIAL_PROTEINGYM_DIR)

import performance_DMS_benchmarks as perf  # noqa: E402
import pandas as pd  # noqa: E402
import numpy as np  # noqa: E402

FAST_BOOTSTRAP_ITERS = 200


def _fast_bootstrap_se(df, number_assay_reshuffle=FAST_BOOTSTRAP_ITERS):
    """Drop-in replacement for compute_bootstrap_standard_error (fast)."""
    model_names = df.columns
    means = []
    for _ in range(number_assay_reshuffle):
        means.append(df.sample(frac=1.0, replace=True).mean(axis=0))
    out = pd.DataFrame(data=means, columns=model_names)
    return out.std(ddof=1)


def _fast_bootstrap_se_func(df, number_assay_reshuffle=FAST_BOOTSTRAP_ITERS):
    """Drop-in replacement for compute_bootstrap_standard_error_functional_categories (fast)."""
    model_names = df.columns
    mean_performance_across_samples = {}
    for category, group in df.groupby("Selection Type"):
        samples = []
        for _ in range(number_assay_reshuffle):
            samples.append(group.sample(frac=1.0, replace=True).mean(axis=0))
        mean_performance_across_samples[category] = pd.DataFrame(data=samples)
    categories = list(mean_performance_across_samples.keys())
    combined = mean_performance_across_samples[categories[0]].copy()
    for category in categories[1:]:
        combined += mean_performance_across_samples[category]
    combined /= len(categories)
    return combined.std(ddof=1)


def main():
    perf.compute_bootstrap_standard_error = _fast_bootstrap_se
    perf.compute_bootstrap_standard_error_functional_categories = _fast_bootstrap_se_func

    argv = [
        "performance_DMS_benchmarks.py",
        "--input_scoring_files_folder", "./results/official_merged_scores/",
        "--output_performance_file_folder", "./results/official_performance/",
        "--DMS_reference_file_path", "./data/DMS_substitutions.csv",
        "--DMS_data_folder", "./data/DMS_ProteinGym_substitutions/",
        "--config_file", "./results/config_with_delta_v.json",
        "--performance_by_depth",
    ]
    sys.argv = argv
    t0 = time.time()
    print(f"[wrapper] bootstraps patched to {FAST_BOOTSTRAP_ITERS} iters", file=sys.stderr, flush=True)
    perf.main()
    print(f"[wrapper] official main() finished in {time.time()-t0:.0f}s", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
