# Paradigm Context from Kuhn Handoff

## Previous Paradigm Limitation
The Scientist plateaued at 0.5708 avg Spearman.

## Kuhn Paradigm

**Assumption violated:** Model prediction errors are symmetric — overpredictions and underpredictions occur with equal frequency and magnitude

**Imported domain:** TGAEC correction than proteins with ratios near 1.0

**Hypothesis:**

# Falsifiable Prediction — Topologically-Guided Asymmetric Error Correction (TGAEC)

## Paradigm Shift
**FROM:** Model prediction errors are symmetric — overpredictions and underpredictions occur with equal frequency and magnitude
**TO:** Model errors are ASYMMETRIC — overpredictions and underpredictions have different stability in prediction space, indicating systematic directional bias

## Primary Prediction

**If model errors are asymmetric (assumption FALSE):**

**Score improvement:** +0.002 to +0.010 Spearman → 0.5714 to 0.5794

This would beat the current best (0.5708) and validate the paradigm shift.

## Secondary Predictions (Falsification Tests)

### 1. Asymmetry ratio distribution across proteins
- **Prediction:** Asymmetry ratio (overpred_stability / underpred_stability) will show non-uniform distribution across 217 proteins
  - Ratio > 1.2: Systematic overprediction (VenusREM too high)
  - Ratio < 0.8: Systematic underprediction (VenusREM too low)
  - Ratio ≈ 1.0: Symmetric errors (no correction needed)
- **Falsification:** If ALL proteins have ratio ≈ 1.0 (±0.1), asymmetry doesn't exist

### 2. Correction factor correlates with score improvement
- **Prediction:** Proteins with extreme asymmetry ratios (>1.5 or <0.7) will show larger score improvements from TGAEC correction than proteins with ratios near 1.0
- **Falsification:** If correction factor is uncorrelated with per-protein Spearman improvement, asymmetry detection is not driving performance

### 3. Direction-specific error patterns
- **Prediction:** Overprediction stability will correlate with structural context (e.g., higher on buried positions RSA < 0.2, lower on surface)
- **Falsification:** If asymmetry ratio is independent of RSA, conservation, or assay type, the detected asymmetry is not structurally meaningful

### 4. Model-specific asymmetry
- **Prediction:** Different models will show different asymmetry patterns (VenusREM might overpredict, ESM2 might underpredict)
- **Falsification:**

## Paradigm Plan (Steps 1-4)

# Paradigm-Interrogation Protocol — ProteinGym Kuhn Agent

## STEP 1 — Surface the Fixed Assumptions

The current `best_so_far_strategy.py` (CPCWE, score: 0.5706) treats these assumptions as given:

1. **Model prediction errors are symmetric:** The algorithm treats positive and negative residuals identically. When VenusREM overpredicts (prediction > ensemble) by +0.3, this receives the same treatment as underpredicting by -0.3. Quantile calibration uses different expansion factors (2.3 harmful vs 1.0 benign), but residual propagation, confidence weighting, and all correction mechanisms are symmetric. The algorithm never asks: "Are overpredictions systematically different from underpredictions?"

2. **Residuals are zero-mean noise:** The algorithm computes residuals (prediction - ensemble) and propagates them, but assumes the distribution is centered at zero. Corrections push predictions toward the ensemble equally in both directions. No mechanism to detect asymmetric bias (e.g., VenusREM consistently overpredicts harmfulness).

3. **Confidence is magnitude-based, not error-direction-aware:** Confidence = |z_score| / max|z_score|. A confident overprediction (z=+2.5) and confident underprediction (z=-2.5) have identical confidence. The algorithm doesn't distinguish between "confident wrong direction" vs "confident right direction."

4. **All models share the same error symmetry:** The confidence scaling factors (venus: 1.0, esm: 0.5, gemme: 0.5, prosst: 1.5) modulate confidence uniformly. No model-specific asymmetry detection (e.g., VenusREM might overpredict, ESM2 might underpredict).

5. **Position-wise residuals are direction-agnostic:** When computing per-position residuals for propagation, the algorithm averages all residuals at a position regardless of sign. A position with [+0.3, -0.2, +0.4, -0.1] has mean residual +0.1, losing the directional information (2 overpredictions, 2 underpredictions).

**Injected assumption from KUHN_INJECTION.json:**
"Model prediction errors are symmetric — overpredictions and underpredictions occur with equal frequency and magnitude"

This is CLEARLY Assumption #1. The current algorithm explicitly assumes symmetry in all error correction mechanisms. Quantile calibration is the ONLY asymmetry (2.3× expansion for harmful predictions), but this is a calibration choice, not an error-correction mechanism. Residual propagation, confidence weighting, and ensemble blending are all symmetric.

---

## STEP 2 — Understand the Violation

If the assumption "Model prediction errors are symmetric" is FALSE, then:

- **Overpredictions and underpredictions have different causes:** If VenusREM overpredicts harmfulness (prediction too high) on conserved core positions, but underpredicts on variable surface positions, these are TWO DIFFERENT ERROR MODES that should be corrected differently.

- **Error distributions are skewed, not symmetric:** The residual distribution might have a non-zero mean (systematic bias) or different vari
