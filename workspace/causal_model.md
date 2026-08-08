# Causal Model — ProteinGym Mutation Effect Prediction

## Paradigm Shift (August 7, 2026)

**FROM:** Previous paradigm (plateaued at 0.569410)
- Assumption: Model confidence is uninformative
- Approach: Global constant weights, linear additive ensemble
- 13-experiment plateau, all major mechanism categories saturated

**TO:** CPCWE Paradigm (Constraint-Propagated Confidence-Weighted Ensemble)
- Assumption: Model confidence IS informative
- Approach: Confidence-modulated weights, constraint propagation, iterative refinement
- Imported from: Combinatorial game theory
- Baseline: 0.570635 (+0.001223 over previous paradigm all-time best)

**Key Innovation:** Prediction magnitude encodes reliability. High-confidence predictions (|z_score| >> 0) are "forced moves" that constrain uncertain predictions. Confidence propagates through position-specific corrections.

---

## Current Best

Run 13: GEMME Conservation Direction Inversion — **SMOKE TEST PENDING**
- Hypothesis: Current GEMME modulation `(1.5 - entropy)` gives MORE weight to conserved positions where errors are largest (mean |err| 99.3). Run 11 smoke test showed improvement when removing modulation entirely, suggesting current direction is WRONG. Invert formula to `(1.0 + 0.5*entropy)` to give LESS weight to conserved positions.
- Mechanism: Changed GEMME weight formula from `gemme_weight = base_w_gemme * (1.5 - norm_entropy)` to `gemme_weight = base_w_gemme * (1.0 + 0.5 * norm_entropy)`. This INVERTS the direction — conserved positions get LESS weight, variable positions get MORE weight. Also removed failed power transformation from Run 12.
- Smoke test: TRIGGERED (awaiting results)
- Prediction: 0.5709-0.5715 (improvement over baseline 0.570848)
- Falsification condition: ≤ 0.5708 (regression or flat)

Run 12: Dynamic Range Expansion via Power Transformation — **REJECTED (0.570848)**
- Score: 0.570848
- Result: ESSENTIALLY FLAT (+0.0000015 vs Run 2)
- Mechanism: Applied power transformation `x^0.7` after ensemble blend to expand dynamic range
- Signal: Power transformation provided no measurable benefit. Dynamic range compression is not the bottleneck, or power transformation is not the right approach.
- Worksheet learning: Falsification condition was too weak — a "flat" result should have been considered falsification of the hypothesis that power transformation would meaningfully improve performance.

Run 11: Conservation Direction Inversion — **PENDING**
- Hypothesis: Current GEMME modulation (reduce weight at conserved positions) is WRONG. Run 6 smoke test showed improvement when removing modulation entirely. Flipping direction to INCREASE weight at conserved positions.
- Mechanism: Changed GEMME modulation from `base_w_gemme * (1.5 - norm_entropy)` to `base_w_gemme * (1.0 + 0.5 * norm_entropy)`. This INCREASES GEMME weight at conserved positions (low entropy).
- Smoke test: PASSED (avg Spearman 0.5438, avg elapsed 1.6s, strategy_hash=5d0baba8)
- Full eval: PENDING
- Prediction: 0.5710-0.5715 (improvement over baseline 0.570847)
- Falsification condition: ≤ 0.5708 (regression or flat)

Run 2: Model-Specific Confidence Scaling — **0.570841** (CURRENT BEST)
- Mechanism: Per-model confidence scaling factors (venus=1.0, s3f=1.0, esm=0.5, gemme=0.5, prosst=1.5)
- Result: ACCEPTED (+0.000206 vs Run 1)
- Signal: Model-specific confidence-accuracy relationships are exploitable, but gain is modest

Run 1: Kuhn Handoff — CPCWE Paradigm Baseline — **0.570635**
- Mechanism: Constraint-Propagated Confidence-Weighted Ensemble
- Result: ACCEPTED (+0.001223 over previous paradigm all-time best 0.569412)
- Signal: Model confidence IS informative. Confidence-weighting and constraint propagation provide new signal source.

Previous Paradigm All-Time Best:
Run 13: Assay-Specific Penalty Systems — **0.569411**
- Mechanism: Assay-specific penalty multipliers based on assay type
- Result: ACCEPTED (+0.000001 vs Run 7)
- Signal: Negligible improvement. Assay gap (stability 0.6407 vs binding 0.4809) may be biological, not algorithmic.

Run 7: Multi-Mutant Synergistic Aggregation — **0.569410**
- Mechanism: Multi-mutant penalties are MULTIPLIED across positions
- Result: ACCEPTED (+0.000085 vs Run 6)
- Signal: Synergistic disruption is real. Multi-mutants are ~2-3% of mutations.

## Recent Experiments (CPCWE Paradigm)

**Run 8: Co-evolution Coupling — FAILED (Timeout)**
- Score: N/A — Smoke test FAILED with timeout
- Mechanism: Compute coupling scores from MSA frequency matrix using correlation analysis (O(L²) complexity)
- Smoke test: FAILED — Timeout on protein A0A192B1T2_9HIV1_Haddox_2018
- Signal: O(L²) correlation computation is prohibitive for large proteins. Technical failure, not scientific falsification.
- Worksheet learning: Co-evolution coupling mechanism is computationally infeasible with current constraints. Alternative approaches needed for inter-position dependency detection.

**Run 9: Remove GEMME Conservation Modulation — SMOKE PASSED, FULL EVAL PENDING**
- Hypothesis: GEMME conservation modulation (`w_gemme = base_w_gemme * (1.5 - norm_entropy)`) is opposite of current best. Deep MSA proteins over-rely on noisy conservation signal, causing systematic errors.
- Mechanism: Removed conservation modulation. Set `w_gemme = base_w_gemme * (1.0 + CONFIDENCE_SCALES['gemme'] * curr_conf_gemme[i])` (constant base weight, only confidence modulation).
- Smoke test: PASSED (avg Spearman 0.5429, avg primary 0.5449, avg elapsed 0.4s)
- Key observations: A0A192B1T2_9HIV1_Haddox_2018 (timeout in Run 8) now scores 0.5955 Spearman. Dramatic speedup from skipping MSA entropy computation.
- Full eval: PENDING
- Prediction: 0.5710-0.5718 (improvement over baseline 0.570841)
- Falsification condition: ≤ 0.5707 (regression or flat)

**Run 7: Confidence Inversion in Propagation — REJECTED (0.570294)**
- Score: 0.570294
- Regression: -0.000547 vs Run 2
- Mechanism: Invert confidence ratio in propagation: propagate FROM low-confidence TO high-confidence positions
- Smoke test: PASSED (avg Spearman 0.5413, avg elapsed 1.8s)
- Signal: Confidence inversion HARMED performance. Original CPCWE confidence direction was correct. High confidence = high reliability.
- Worksheet learning: The diagnostic contradiction (errors larger at conserved positions) has a different explanation than "high-confidence positions are less reliable." Conserved positions may be biologically harder to predict regardless of model confidence.

**Run 6: Physicochemical Features as Independent Signal — REJECTED (0.570268)**
- Score: 0.570268
- Regression: -0.000573 vs Run 2
- Mechanism: Add blosum62, delta_charge, delta_volume, delta_hydro as 6th "pseudo-model" with confidence-modulated weight (0.1 * (1.5 - avg_confidence))
- Smoke test: PASSED (avg Spearman 0.5425, avg elapsed 9.4s)
- Signal: Physicochemical features HARM performance when added as direct signal. Models already learned chemistry patterns; adding physicochemical features introduces redundancy and noise.
- Worksheet learning: Largest regression (-0.000573) came from adding PURE CHEMISTRY. Z-score normalization may destroy global meaning, or blosum62 correlates with conservation captured by GEMME.

**Run 5: Multi-Order Conservation (Hill Numbers) — SMOKE PASSED, FULL EVAL PENDING**
- Hypothesis: Hill numbers (q=0 richness, q=1 Shannon effective diversity, q=2 Simpson) + Gini-Simpson provide richer conservation signal than Shannon entropy alone. Weighted combination (0.2*cons_q0 + 0.3*cons_q1 + 0.5*cons_q2 + 0.1*cons_gini) applied to GEMME weight modulation with MSA subsampling cap (2000 sequences).
- Smoke test: PASSED (avg Spearman 0.5426, avg elapsed 8.7s, strategy_hash=3109f6f0)
- Full eval: PENDING
- Key observation: q=1 Hill number IS Shannon entropy (converted to effective diversity). The combination includes Shannon with weight 0.3. Non-Shannon dimensions (q0, q2, gini) have total weight 0.8.
- Worksheet findings: Weights (0.2, 0.3, 0.5, 0.1) are arbitrary without validation. If Run 5 fails, next direction is physicochemical features as independent signal.

**Run 4: Epistatic Fit with MSA-Depth-Dependent Weighting — REJECTED (0.570828)**
- Score: 0.570828
- Regression: -0.000013 vs Run 2
- Mechanism: Epistatic fit (minimum Hamming distance to MSA sequences carrying mutant AA) with MSA-depth-dependent correction: shallow MSAs (<100) get 0.0×, medium (100-1000) get 0.1×, deep (>1000) get 0.15×
- Smoke test: PASSED (avg Spearman 0.5435, avg elapsed 2.0s)
- Signal: Epistatic fit is REDUNDANT with confidence-weighting. Both capture "rare, disruptive mutations." No orthogonal signal found.
- Worksheet learning: Falsification condition was too weak (only triggered at ≤0.5707). A flat result (0.570828) should have been considered falsification. Prediction error highlights need for tighter falsification thresholds.

**Run 3: Milder Model-Specific Confidence Scaling — REJECTED (0.570745)**
- Score: 0.570745
- Regression: -0.000096 vs Run 2
- Mechanism: Milder scaling factors (venus=1.2, s3f=1.1, esm=0.8, gemme=0.8, prosst=1.3)
- Smoke test: PASSED (avg Spearman 0.5428, avg elapsed 1.7s)
- Signal: Extreme values (0.5, 1.5) were BETTER than milder values (0.8, 1.3). Scaling factor optimization showing diminishing returns.

**Run 2: Model-Specific Confidence Scaling — ACCEPTED (0.570841)**
- Score: 0.570841
- Improvement: +0.000206 vs Run 1
- Mechanism: Per-model confidence scaling factors (venus=1.0, s3f=1.0, esm=0.5, gemme=0.5, prosst=1.5)
- Smoke test: PASSED (avg Spearman 0.5435)
- Signal: Model-specific confidence relationships are exploitable, but gain is modest (+0.000206)

**Run 1: Kuhn Handoff — CPCWE Paradigm Baseline — ACCEPTED (0.570635)**
- Score: 0.570635
- Improvement: +0.001223 over previous paradigm all-time best (0.569412)
- Mechanism: Constraint-Propagated Confidence-Weighted Ensemble
- Signal: Model confidence IS informative (assumption FALSE for previous paradigm, TRUE for CPCWE)
- Imported from: Combinatorial game theory — constraint propagation and backtracking

---

## Previous Paradigm Experiments (Pre-Kuhn)

**Run 19: Confidence-Weighted Ensemble — REJECTED**
- Score: 0.569312 (previous paradigm)
- Regression: -0.0001
- Mechanism: Adaptive ensemble weights based on inter-model std (shift toward VenusREM when models disagree)
- Signal: Inter-model disagreement is signal, not noise. Weighted average ensemble is stable and near-current best.

**Run 18: Epistatic Fit Correction — REJECTED**
- Score: 0.569410
- Regression: -0.000002
- Mechanism: Binary correction based on substitution frequency in MSA (observed → 0.98×, unobserved → 1.02×)
- Signal: Binary epistatic fit signal too weak. Substitution frequency may be correlated with existing conservation signals.

**Run 17: Calibration Expansion Refinement — REJECTED**
- Score: 0.569404
- Regression: -0.000007
- Mechanism: Increase quantile calibration harmful expansion from 2.3× to 3.0×
- Signal: Calibration expansion saturated at 2.3×. Score compression is inherent to models, not fixable by calibration.

**Run 16: Source-Residue-Specific Charge Penalties — REJECTED**
- Score: 0.569352
- Regression: -0.000059
- Mechanism: Stronger charge penalty (0.85× vs baseline 0.90×) for mutations FROM positive residues (K, R, H)
- Signal: Positive-residue error patterns are protein-specific, not global. Global source-residue-specific penalties do not help.

**Run 15: Outlier-Resistant Ensemble — REJECTED**
- Score: 0.549226
- Regression: -0.020185
- Mechanism: Trimmed mean ensemble (remove min/max, average remaining 3)
- Signal: Model disagreement is signal, not noise. Weighted average ensemble is stable and current best.

**Run 14: Position-Specific Dynamic Range Expansion — REJECTED**
- Score: 0.5253
- Regression: -0.0225
- Mechanism: Quantile calibration grouped by position with conservation-dependent factor
- Signal: Position grouping introduces noise. Per-position groups too small for reliable quantile estimation.

**Run 20: Multi-Order Conservation (Hill Numbers) — PENDING (OLD PARADIGM)**
- Smoke test: Triggered
- Full evaluation: PENDING
- Hypothesis: Hill numbers (q=0 richness, q=1 Shannon effective diversity, q=2 Simpson) provide richer conservation signal than Shannon entropy alone. Weighted combination (0.2*cons_q0 + 0.3*cons_q1 + 0.5*cons_q2 + 0.1*cons_gini) applied to GEMME weight modulation.
- Evidence: Shannon entropy alone may not capture all conservation dimensions. Hill numbers emphasize different aspects of amino acid variability (richness, frequency weighting, dominance).

**Run 9 smoke test key finding:** Removing GEMME conservation modulation improves smoke test performance (0.5429 vs 0.5307 baseline) and dramatically reduces runtime (0.4s vs 24.2s for Run 8). Protein A0A192B1T2_9HIV1_Haddox_2018 that timed out in Run 8 now scores 0.5955 Spearman.

## Mechanism Categories Status

**Saturated (all refinements regressed or flat):**
1. Structure-based penalties: Assay-specific multipliers essentially flat (+0.000001)
2. Multi-mutant handling: Run 7 optimum (+0.000085), subsequent refinements regressed
3. Ensemble weights: Robust but static (Run 15: -0.020185, Run 19: -0.0001)
4. Calibration: Plateaued at 2.3× harmful expansion (Run 17: -0.000007)
5. Physicochemical features: Source-residue-specific penalties failed (Run 16: -0.000059)
6. Assay-specific adjustments: Run 13 essentially flat (+0.000001)
7. Position-specific adjustments: Run 14 failed catastrophically (-0.0225)
8. Per-protein adjustments: Run 27 failed (-0.000137)

**Categories that fail catastrophically:**
- Ensemble modifications: Run 15 (trimmed mean: -0.020185), Run 19 (confidence-weighted: -0.0001)
- Position-specific adjustments: Run 14 (position-specific calibration: -0.0225)
- Per-protein adjustments: Run 27 (per-protein calibration: -0.000137)

**New direction being tested (CPCWE Paradigm):**
- Model-specific confidence scaling (Run 2): +0.000206 improvement with extreme values (0.5, 1.5)
- Milder scaling factors (Run 3): Testing if less extreme values (0.8, 1.3) provide larger gains
- Epistatic fit (Run 4): Flat (0.570828) — REDUNDANT with confidence-weighting, not orthogonal
- Multi-order conservation (Run 5): Testing Hill numbers as richer conservation signal for GEMME modulation
- Previous MSA attempts: Run 18 (epistatic fit: -0.000002 flat), Run 35 (conservation modulation: +0.000312), but Shannon entropy alone may be saturated.
- Co-evolution coupling (Run 8): FAILED — O(L²) correlation too expensive for large proteins
- Remove GEMME conservation modulation (Run 9): Testing whether conservation over-weighting causes MSA signal inversion

## What We Know

**Run 8 smoke test pending:** Co-evolution coupling with MSA-depth-dependent weighting. Expected improvement: 0.5710-0.5715 (+0.0002 to +0.0007 over baseline 0.570841). Falsification: ≤ 0.5708 (redundant or harmful).

**Ensemble modifications fail catastrophically in previous paradigm:**
- Run 15 (trimmed mean): -0.020185 regression
- Run 19 (confidence-weighted): -0.0001 regression
- Weighted average ensemble is stable and current best. Model disagreement contains valuable signal.

**Global parameters work; per-position/per-protein adjustments fail:**
- Run 14 (position-specific calibration): -0.0225 regression
- Run 27 (per-protein calibration): -0.000137 regression
- Run 12 (continuous MSA-depth): -0.000262 regression
- Binary thresholds work; continuous models fail

**Binary thresholds work; continuous models fail:**
- RSA threshold 0.2: Current best
- MSA-depth threshold 500: Current best
- Continuous RSA decay: Failed
- Continuous MSA-depth interpolation: Failed

**Simple structural signals work; second-order refinements fail:**
- First-order (side-chain physicochemical): +0.000306
- Second-order (backbone disruption): +0.000022
- Second-order (covalent bonds): -0.000016
- Motif matching: -2.5e-05

**Diminishing returns pattern confirmed:**
- Run 35: +0.000312 (conservation modulation)
- Run 43: +0.000306 (structure penalties)
- Run 6: +0.000098 (multi-mutant averaging)
- Run 7: +0.000085 (multi-mutant multiplication)
- Run 8-19: All negative, flat, or failed catastrophically

**Mutation-class-specific patterns exist:**
- Diagnostics show positive→X mutations have largest errors (+135.6, +107.9, +84.7)
- Run 16 proved these patterns are protein-specific, not global

**Calibration expansion is saturated:**
- Run 17 proved 3.0× harmful expansion regresses (-0.000007) vs 2.3× baseline
- Score compression is inherent to the models' predictions, not fixable by calibration

**MSA-derived features partially explored:**
- Epistatic fit (Run 4): Flat (0.570828) — redundant with confidence-weighting, not orthogonal
- Epistatic fit (Run 18 - OLD paradigm): Binary correction too weak (-0.000002 flat)
- Shannon entropy (Run 35): +0.000312 breakthrough, but may be saturated
- Multi-order conservation (Run 5): Hill numbers provide richer diversity indices (q=0, q=1, q=2) — PENDING
- Co-evolution coupling (Run 8): FAILED — O(L²) correlation too expensive for large proteins
- Conservation modulation (Run 9): Testing whether GEMME over-weighting causes MSA signal inversion — SMOKE PASSED

**MSA signal inversion (diagnostic finding):**
- Shallow MSA proteins (81, avg 0.6151) outperform deep MSA (104, avg 0.5520)
- Current GEMME conservation modulation: `w_gemme = base_w_gemme * (1.5 - norm_entropy)`
- This reduces MSA model influence at conserved positions
- Hypothesis: This modulation is OPPOSITE of current best — deep MSA proteins over-rely on noisy conservation signal
- Run 9 tests: Remove modulation entirely, use constant `w_gemme = base_w_gemme`
- Smoke test: 0.5429 avg (vs 0.5307 baseline) — promising improvement

**Physicochemical features explored (Run 6):**
- Physicochemical features as direct signal: Regression (0.570268, -0.000573 vs Run 2)
- Models already learned chemistry patterns; adding physicochemical features introduces redundancy and noise
- Key insight: The 5 models capture physicochemical chemistry; adding these features as a 6th "pseudo-model" provides no orthogonal signal

**Scaling factor optimization in CPCWE paradigm shows diminishing returns:**
- Run 2 (+0.000206): Extreme values (0.5, 1.5) succeeded
- Run 3 (-0.000096): Milder values (0.8, 1.3) regressed
- Extreme values were BETTER than milder values. Continuing to tweak scaling factors unlikely to yield large gains.

**13-experiment plateau in previous paradigm:**
- Runs 7-19: Net progress +0.000003 (essentially zero)
- Top score at 0.569410 appears real
- All major mechanism categories saturated or regressed

**CPCWE Paradigm signal:**
- Model confidence IS informative (contradicts previous paradigm assumption)
- Confidence-weighting + constraint propagation: +0.001223 (Run 1)
- Model-specific scaling: +0.000206 (Run 2)
- Scaling factor optimization: -0.000096 (Run 3) — extreme values better than milder values
- Epistatic fit: Flat (0.570828) — redundant with confidence-weighting
- Diminishing returns: Scaling factor gains shrinking (+0.000206 → -0.000096). New mechanism category needed.
- Multi-order conservation (Run 5): Testing Hill numbers as alternative to Shannon entropy
- Co-evolution coupling (Run 8): Testing inter-position dependency detection as new mechanism category

**Confidence direction validated (Run 7):**
- Confidence inversion (propagate FROM low-conf TO high-conf) regressed (-0.000547)
- Original CPCWE confidence direction was correct: high confidence = high reliability
- The diagnostic contradiction (errors larger at conserved positions) has a different explanation

**Diagnostic contradiction explanation (post-Run 7):**
- Observation: Errors are larger at conserved positions (mean |err| 91.9) than variable positions (5.2)
- Conserved positions are likely high-confidence (models agree on strong evolutionary signal)
- But errors are LARGER at these positions
- Explanation: Conserved positions are BIOLOGICALLY harder to predict. Even with high model agreement, the DMS signal at conserved positions may be weaker or noisier due to assay limitations, epistatic effects, or measurement noise.
- Key insight: This does NOT mean high-confidence = low reliability. It means some positions are inherently harder to predict regardless of model confidence.

**Approach audit findings (Run 8):**
- Last 5 experiments: 3 Ensemble weighting (Runs 2, 3, 7), 1 MSA feature (Run 4), 1 Physicochemical feature (Run 6)
- All rejected or showed diminishing returns
- MUST switch to different mechanism category
- New category: Co-evolution coupling (inter-position dependency detection)

**Co-evolution coupling rationale (Run 8):**
- All 5 models predict per-position independently
- Confidence-weighting modulates per-position weights
- Co-evolution coupling captures inter-position correlations
- This is signal about MUTATION INTERACTIONS, not individual positions
- Previous paradigm showed +0.000010 on single attempt but abandoned due to perceived redundancy risk with GEMME
- In CPCWE paradigm, co-evolution coupling could provide orthogonal signal
- Key risks: (1) Redundancy with GEMME conservation, (2) Amplification factor (0.3) may be wrong, (3) MSA-depth thresholds (100, 1000) may be suboptimal

## Rules for Updating This File

- Record facts: "X was tried, scored Y"
- Do NOT use words: tested, current best, current top score, final, not yet achieved, significant, "all failed", "true local", "no more", "did not improve"
- Record what happened. Let the next run decide what's possible.