#!/usr/bin/env python3
"""Official ProteinGym benchmark harness for the Delta V strategy.

Generates a `Delta_V` prediction column for every one of the 217 DMS
substitution assays and writes a new merged-score CSV (original columns +
Delta_V) per assay.  The resulting files are drop-in inputs for the official
`proteingym/performance_DMS_benchmarks.py` script.

Pipeline per protein:
  1. Load wild-type sequence + MSA (same loaders as proteingym_eval.py).
  2. Read the mutant list directly from the official merged-score file so the
     Delta_V vector is guaranteed row-aligned with every other model column.
  3. Run `best_so_far_strategy.score_mutations(...)`.
  4. Append the Delta_V column and write to results/official_merged_scores/.

Every step is logged to stderr with ISO timestamps so the run is fully
auditable when tee'd to a log file.

Usage:
    python3 scripts/official_benchmark.py
    python3 scripts/official_benchmark.py --smoke   # first 3 proteins only
"""
import sys
import os
import time
import glob
import importlib.util
import traceback

import numpy as np
import pandas as pd

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPTS_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, "data", "DMS_ProteinGym_substitutions")
REFERENCE_FILE = os.path.join(PROJECT_DIR, "data", "DMS_substitutions.csv")
MERGED_INPUT_DIR = "./data/proteingym_scores"
OUTPUT_DIR = os.path.join(PROJECT_DIR, "results", "official_merged_scores")
STRATEGY_PATH = os.path.join(PROJECT_DIR, "workspace", "best_so_far_strategy.py")

# Make scripts/ importable so the strategy can `import proteingym_data`, and so
# we can reuse proteingym_eval's loaders.
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)
os.environ.setdefault("PROTEINGYM_DB", os.path.join(PROJECT_DIR, "data", "proteingym_data.db"))

DELTA_V_COLUMN = "Delta_V"


def log(msg):
    """Timestamped stderr logger."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr, flush=True)


def load_strategy(path):
    """Import the strategy module and return its score_mutations callable."""
    spec = importlib.util.spec_from_file_location("delta_v_strategy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "score_mutations"):
        raise RuntimeError("strategy module has no score_mutations")
    return mod.score_mutations


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Official ProteinGym Delta V benchmark")
    parser.add_argument("--smoke", action="store_true", help="Run first 3 proteins only")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of proteins (0 = all)")
    args = parser.parse_args()

    t_start = time.time()
    log("=" * 72)
    log("Official ProteinGym Delta V benchmark starting")
    log(f"  merged input dir : {MERGED_INPUT_DIR}")
    log(f"  output dir       : {OUTPUT_DIR}")
    log(f"  strategy         : {STRATEGY_PATH}")
    log(f"  reference        : {REFERENCE_FILE}")
    log(f"  data dir         : {DATA_DIR}")
    log(f"  DB               : {os.environ['PROTEINGYM_DB']}")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load the reference + reusable loaders from proteingym_eval.  These handle
    # MSA subsampling (reservoir sampling) exactly as the eval harness does.
    import proteingym_eval as peval

    log("Loading reference file ...")
    reference = peval.load_reference()
    log(f"  {len(reference)} proteins in reference")

    # Wild-type sequences (lightweight strings)
    all_sequences = {}
    for pid, ref in reference.items():
        wt = ref.get("target_seq", "")
        if wt:
            all_sequences[pid] = wt
    log(f"  {len(all_sequences)} wild-type sequences loaded")

    # Discover merged score files (one per DMS assay), ordered deterministically
    merged_files = sorted(glob.glob(os.path.join(MERGED_INPUT_DIR, "*.csv")))
    log(f"  {len(merged_files)} merged score files discovered")

    if args.smoke:
        merged_files = merged_files[:3]
        log(f"  SMOKE mode: limited to {len(merged_files)} files")
    elif args.limit > 0:
        merged_files = merged_files[: args.limit]
        log(f"  --limit: processing {len(merged_files)} files")

    # Load strategy
    log("Loading Delta V strategy ...")
    score_mutations = load_strategy(STRATEGY_PATH)
    log("  strategy loaded OK")

    n_ok = 0
    n_fail = 0
    n_skipped = 0
    failures = []

    for idx, mfile in enumerate(merged_files, 1):
        dms_id = os.path.splitext(os.path.basename(mfile))[0]
        out_path = os.path.join(OUTPUT_DIR, dms_id + ".csv")

        # Skip if already done (idempotent re-runs)
        if os.path.exists(out_path):
            n_skipped += 1
            continue

        ref = reference.get(dms_id)
        wt_seq = all_sequences.get(dms_id)
        if not ref or not wt_seq:
            log(f"[{idx}/{len(merged_files)}] {dms_id}: SKIP (no reference/WT)")
            n_skipped += 1
            continue

        try:
            merged = pd.read_csv(mfile)
        except Exception as exc:  # noqa: BLE001
            log(f"[{idx}/{len(merged_files)}] {dms_id}: FAIL reading merged file: {exc}")
            n_fail += 1
            failures.append((dms_id, f"read merged: {exc}"))
            continue

        if "mutant" not in merged.columns:
            log(f"[{idx}/{len(merged_files)}] {dms_id}: SKIP (no 'mutant' column)")
            n_skipped += 1
            continue

        mutations = merged["mutant"].astype(str).tolist()

        # Load MSA (subsampled exactly as proteingym_eval does)
        t0 = time.time()
        msa = None
        try:
            msa = peval.load_msa(dms_id, ref, protein_length=len(wt_seq))
        except Exception as exc:  # noqa: BLE001
            log(f"[{idx}/{len(merged_files)}] {dms_id}: WARNING MSA load failed ({exc}); continuing without MSA")
        msa_depth = len(msa) if msa else 0

        # Run the strategy.  Calling convention matches _process_single_protein
        # in proteingym_eval.py:
        #   score_mutations(sequences=all_sequences, protein_id=..,
        #                   wild_type=wt_seq, mutations=mut_list, msa=msa)
        try:
            predicted = score_mutations(
                sequences=all_sequences,
                protein_id=dms_id,
                wild_type=wt_seq,
                mutations=mutations,
                msa=msa,
            )
        except Exception:
            elapsed = time.time() - t0
            log(f"[{idx}/{len(merged_files)}] {dms_id}: FAIL strategy crashed after {elapsed:.1f}s")
            traceback.print_exc(file=sys.stderr)
            n_fail += 1
            failures.append((dms_id, "strategy crash"))
            del msa
            continue

        elapsed = time.time() - t0

        # Validate alignment; fall back to NaN vector on mismatch so the official
        # performance script treats Delta_V as missing for this assay.
        if predicted is None or len(predicted) != len(mutations):
            log(
                f"[{idx}/{len(merged_files)}] {dms_id}: WARN predicted length "
                f"{None if predicted is None else len(predicted)} != {len(mutations)}; filling NaN"
            )
            merged[DELTA_V_COLUMN] = np.nan
        else:
            pred_arr = np.asarray(predicted, dtype=np.float64)
            if not np.all(np.isfinite(pred_arr)):
                n_nan = int(np.sum(~np.isfinite(pred_arr)))
                log(f"[{idx}/{len(merged_files)}] {dms_id}: WARN {n_nan} non-finite predictions coerced to NaN")
                pred_arr = np.where(np.isfinite(pred_arr), pred_arr, np.nan)
            merged[DELTA_V_COLUMN] = pred_arr

        merged.to_csv(out_path, index=False)
        n_ok += 1
        finite = int(np.sum(np.isfinite(np.asarray(predicted, dtype=np.float64)))) if predicted is not None and len(predicted) == len(mutations) else 0
        log(
            f"[{idx}/{len(merged_files)}] {dms_id}: OK  n_mut={len(mutations)} "
            f"finite={finite} msa_depth={msa_depth} time={elapsed:.1f}s"
        )

        del msa
        # Periodic GC keeps peak memory bounded across 217 proteins.
        if idx % 25 == 0:
            import gc
            gc.collect()

    elapsed_total = time.time() - t_start
    log("=" * 72)
    log(f"DONE in {elapsed_total:.0f}s")
    log(f"  succeeded : {n_ok}")
    log(f"  failed    : {n_fail}")
    log(f"  skipped   : {n_skipped}")
    if failures:
        log("  failure list:")
        for fid, reason in failures:
            log(f"    - {fid}: {reason}")
    log(f"  output dir: {OUTPUT_DIR}")

    # Guard clause: only import json at the end for the manifest.
    import json
    manifest = {
        "total_files": len(merged_files),
        "succeeded": n_ok,
        "failed": n_fail,
        "skipped": n_skipped,
        "failures": failures,
        "output_dir": OUTPUT_DIR,
        "elapsed_s": round(elapsed_total, 1),
    }
    manifest_path = os.path.join(OUTPUT_DIR, "_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    log(f"  manifest  : {manifest_path}")

    if n_fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
