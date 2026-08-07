#!/usr/bin/env python3
"""
ProteinGym Kuhn injection selector.

Sequentially picks the next untried (assumption, domain) pair and writes it
to KUHN_INJECTION.json. Pairs are ordered deterministically (assumption-major,
domain-minor) so progress through the space is trackable and reproducible.

When all pairs are exhausted, sends a notification and exits with
code 2 (SETTLED).

Usage:
    python3 pg_kuhn_selector.py --state KUHN_STATE.json --out KUHN_INJECTION.json
"""

import json, sys, os, argparse, datetime

from pg_common import notify

# Assumptions specific to mutation effect prediction / ProteinGym paradigm
ASSUMPTIONS = [
    # ── Model prediction assumptions (VenusREM era) ──
    "VenusREM predictions are equally accurate across all protein families — per-family corrections cannot improve the global score",
    "All three models (VenusREM, S3F_MSA, ESM2) make independent errors — ensembling them cannot reduce variance",
    "Model prediction errors are symmetric — overpredictions and underpredictions occur with equal frequency and magnitude",
    "Model confidence is uninformative — predictions near zero are as accurate as predictions far from zero",
    "The raw model score is the best predictor — non-linear transformations (ranking, binning, clipping) cannot improve accuracy",
    "Structural context adds nothing to model predictions — solvent accessibility and burial class are fully captured by the language model",
    "Model predictions for single mutants generalize to multi-mutant variants without interaction terms",
    "All mutations at the same position should trust the model equally — the specific substitution (e.g. A→V vs A→D) doesn't matter",

    # ── Cross-model and ensemble assumptions ──
    "Disagreement between models is uninformative — when VenusREM and ESM2 disagree, neither is more trustworthy",
    "The optimal blend weight between models is constant across all proteins — no protein-specific weighting is needed",
    "Model predictions are already calibrated — their scores map linearly to experimental DMS scores without transformation",

    # ── Protein-family and context assumptions ──
    "Assay type (binding, stability, growth, activity) does not affect which model is most accurate",
    "Protein length and MSA depth are irrelevant to model accuracy — small proteins and large proteins are equally well-predicted",
    "Conservation signal from the MSA is fully redundant with model predictions — adding MSA features cannot correct model errors",

    # ── Error structure assumptions ──
    "Model errors are uncorrelated with amino acid properties — hydrophobicity, charge, and size of the mutation don't predict error direction",
    "Position-specific error patterns don't exist — if the model overpredicts at one position, it doesn't systematically overpredict at structurally similar positions",
]

DOMAINS = [
    "Crystallography — phase problem and direct methods for structure determination from sparse data",
    "Signal processing — compressed sensing and sparse signal recovery from undersampled measurements",
    "Speech recognition — hidden Markov models and temporal dynamics in spectral features",
    "Cryptography — frequency analysis, known-plaintext attacks, and statistical pattern breaking",
    "Image registration — feature-based alignment under unknown transformations",
    "Seismology — deconvolution and separating overlapping wave arrivals",
    "Astronomy — period-folding and harmonic analysis for weak periodic signals in noise",
    "Music theory — motivic development and transformational geometry in tonal space",
    "Thermodynamics — free energy minimization and equilibrium distributions over states",
    "Operations research — facility location problems and assignment under uncertainty",
    "Linguistics — morpheme segmentation and unsupervised word boundary detection",
    "Radar — matched filter design and Doppler-shifted target detection",
    "Ecology — species distribution modeling and diversity metrics (Hill numbers, effective species count)",
    "Topological data analysis — persistent homology and feature detection in point clouds",
    "Quantum computing — amplitude amplification and Grover-style search",
    "Compiler design — register allocation and graph coloring under constraints",
    "Neuroscience — receptive field estimation from spike-triggered averages",
    "Economics — market segmentation, revealed preference, and portfolio risk assessment",
    "Information theory — minimum description length, rate-distortion theory, and channel capacity",
    "Combinatorial game theory — solving games through constraint propagation and backtracking",
    "Materials science — phase diagrams, grain boundaries, and deformation under stress",
    "Hydrology — groundwater flow, contaminant transport, and watershed partitioning",
    "Epidemiology — SIR models, contact tracing, and superspreader detection in networks",
    "Architecture — load-bearing analysis, redundancy, and graceful failure in structural systems",
]

# Total pair space
TOTAL_PAIRS = len(ASSUMPTIONS) * len(DOMAINS)  # 384


def build_ordered_pairs():
    """Generate all (assumption, domain) pairs in deterministic order.
    Assumption-major: iterate assumptions first, then domains within each."""
    return [(a, d) for a in ASSUMPTIONS for d in DOMAINS]


def select_next_pair(all_pairs, tried):
    """Pseudo-random selection from untried pairs.
    
    Uses a seeded shuffle so selection order is deterministic across runs
    (same seed = same sequence), but pair order is not sequential.
    This prevents the agent from cycling through domains while stuck on
    the same assumption, and spreads exploration across the full space.
    """
    import random
    
    untried = [(i, p) for i, p in enumerate(all_pairs) if p not in tried]
    if not untried:
        return None, -1
    
    # Deterministic seed — same tried set always yields same next pair
    seed_str = str(sorted(tried))
    seed = hash(seed_str) % (2**31)
    rng = random.Random(seed)
    
    # Shuffle just the indices, pick first
    indices = [i for i, _ in untried]
    rng.shuffle(indices)
    chosen_global_idx = indices[0]
    
    return all_pairs[chosen_global_idx], chosen_global_idx


def main():
    parser = argparse.ArgumentParser(description="Select next Kuhn injection pair for ProteinGym")
    parser.add_argument("--state", required=True, help="Path to KUHN_STATE.json")
    parser.add_argument("--out", required=True, help="Path to write KUHN_INJECTION.json")
    args = parser.parse_args()

    with open(args.state) as f:
        state = json.load(f)

    tried = set(tuple(p) for p in state.get("tried_pairs", []))
    all_pairs = build_ordered_pairs()

    # Pseudo-random selection from untried pairs
    next_pair, pair_index = select_next_pair(all_pairs, tried)

    if next_pair is None:
        # All pairs exhausted
        state["state"] = "SETTLED"
        state["settled"] = True
        with open(args.state, "w") as f:
            json.dump(state, f, indent=2)
        print("ALL 384 PAIRS EXHAUSTED — marking as SETTLED", file=sys.stderr)
        notify(
            "⚠️ **ProteinGym Kuhn: All Injection Pairs Exhausted**\n\n"
            f"All {TOTAL_PAIRS} assumption×domain pairs have been tried.\n"
            "The Kuhn agent has explored the full paradigm space.\n\n"
            "**Options:**\n"
            "• Add new assumptions to ASSUMPTIONS list\n"
            "• Add new domains to DOMAINS list\n"
            "• Reset tried_pairs for a second pass\n"
            "• Accept current best as the ceiling for this approach"
        )
        sys.exit(2)

    assumption, domain = next_pair
    remaining = TOTAL_PAIRS - len(tried) - 1

    injection = {
        "assumption": assumption,
        "domain": domain,
        "selected_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pair_index": pair_index,
        "pairs_tried": len(tried),
        "pairs_remaining": remaining,
        "pairs_total": TOTAL_PAIRS,
        "rationale": f"This injection challenges: '{assumption[:80]}...' using ideas from: {domain[:80]}...",
    }

    with open(args.out, "w") as f:
        json.dump(injection, f, indent=2)

    print(f"Selected pair {pair_index + 1}/{TOTAL_PAIRS}", file=sys.stderr)
    print(f"  assumption: {assumption[:60]}...", file=sys.stderr)
    print(f"  domain: {domain[:60]}...", file=sys.stderr)
    print(f"  tried: {len(tried)}, remaining: {remaining}", file=sys.stderr)


if __name__ == "__main__":
    main()
