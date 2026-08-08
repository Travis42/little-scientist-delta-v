# USER.md — ProteinGym Scientist Context

## Current Baseline
VenusREM verbatim: 0.5547 (full eval).
SOTA single-model predictor. Starting point for all experiments.

## Goal
Beat 0.5547 by finding and correcting VenusREM's systematic errors.

## What Works
- Returning VenusREM predictions as-is (0.5547)
- Z-score normalized blending across models (smoke-tested, improves on VenusREM alone)

## What Fails
- Naive linear ensembles (raw model scores mixed by weight) — scale mismatch (0.02)
- Sign-flipping VenusREM scores — destroys correlation (0.02)
- Replacing VenusREM with MSA-derived scores — weaker signal (0.32)
