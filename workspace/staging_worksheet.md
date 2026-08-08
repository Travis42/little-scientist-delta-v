# Experiment Worksheet — Run 13

*This worksheet is your scientific reasoning record. Fill it in completely each iteration before writing code. The validator does not enforce formatting, but your reasoning quality directly determines your algorithm quality. Show your work.*

---

## 1. Prior Run Falsification Check

**Last run's prediction:** 0.5708–0.5715 (Run 4: Dynamic Range Expansion via Power Transformation)

**Last run's actual score:** 0.570848495731123

**Last run's falsification condition:** ≤ 0.5707 (power transformation amplifies noise) OR = 0.570847 (flat)

**Did falsification trigger?** NO

**Analysis:**
- Score improved from 0.570847 to 0.570848 (+0.0000015)
- This is ESSENTIALLY flat — the power transformation provided no measurable benefit
- The improvement is so small it could be noise or random variation
- Falsification condition was too weak — a "flat" result (essentially no change) should have been considered falsification of the hypothesis that power transformation would meaningfully improve performance

**What this means:** The dynamic range compression hypothesis was wrong. Ensemble averaging compression is not the bottleneck, or power transformation is not the right approach to fix it. The diagnostics showed predicted IQR is 0.3× narrower than experimental, but simply expanding tails with x^0.7 doesn't recover useful signal.

---

## 2. Evidence Synthesis

*Review your last ~10 experiments from `history.jsonl`. What do you actually know?*

| Run | Hypothesis | Predicted | Actual | Verdict | What we learned |
|-----|-----------|-----------|--------|---------|-----------------|
| N-5 | Remove GEMME conservation modulation | 0.5710-0.5718 | PENDING | PENDING | Testing whether conservation direction is wrong |
| N-4 | Multi-order conservation (Hill numbers) | 0.5710-0.5715 | PENDING | PENDING | Richer conservation signal |
| N-3 | Co-evolution coupling | 0.5710-0.5715 | TIMEOUT | FAILED | O(L²) correlation too expensive |
| N-2 | Epistatic fit with MSA-depth weighting | 0.5710-0.5715 | 0.570828 | REJECTED | Redundant with confidence-weighting |
| N-1 | Milder confidence scaling | 0.5710-0.5715 | 0.570745 | REJECTED | Extreme values (0.5, 1.5) better than mild (0.8, 1.3) |
| N | Power transformation (x^0.7) | 0.5708-0.5715 | 0.570848 | REJECTED | No benefit — dynamic range compression not the bottleneck |

**Pattern across runs:**
- CPCWE paradigm baseline: 0.570635
- Model-specific scaling: +0.000206 (to 0.570841)
- Subsequent refinements: All regressed, flat, or timed out
- Diminishing returns pattern confirmed — small tweaks to existing mechanism yield ~0 gains
- All experiments are REFINING existing categories (ensemble, calibration, conservation)
- No NEW signal sources have been successfully integrated

**What is surprising?**
- Run 9 smoke test (remove GEMME modulation) showed improvement (0.5429 vs 0.5307 baseline) suggesting current conservation modulation direction is WRONG
- But Run 9 full eval is PENDING — we don't know if it holds on full dataset
- The paradigm_context.md file mentions TGAEC (Topologically-Guided Asymmetric Error Correction) but we haven't tested it
- Multiple approaches (epistatic fit, physicochemical features) that seemed promising showed no gain

---

## 2.5. Data Sources

*What external data did you use in this strategy? Check all that apply.*

- [X] MSA only (default — no external data)
- [ ] approaches in `TECHNIQUES.md`
- [X] `proteingym_data.get_model_scores()` — VenusREM / S3F_MSA / ESM2_15B / ProSST-2048 / GEMME predictions
- [X] Physicochemical features (in `get_model_scores()`): `blosum62`, `delta_charge`, `delta_volume`, `delta_hydro`, `wt_aa`, `mut_aa`
- [X] `proteingym_data.get_residue_structure()` — solvent accessibility, burial class
- [X] `proteingym_data.get_protein_info()` — MSA stats, selection type, organism

**How used:**
- Model predictions: Used in confidence-weighted ensemble with model-specific scaling factors
- Physicochemical features: Used in structure-based penalty system (charge, volume, hydrophobicity, aromatic, GP)
- Residue structure: Used for burial-based penalty modulation (core positions get stronger penalties)
- Protein info: Used for assay-specific penalty multipliers

**Data you are NOT using and why:**

- TECHNIQUES.md features not used:
  - **Epistatic fit**: Tested in Run 4 (old paradigm) and Run N-2 (CPCWE) — showed flat performance (0.570828), appears redundant with confidence-weighting
  - **Co-evolution coupling**: Tested in Run N-3 — FAILED due to O(L²) computational complexity, not falsified scientifically
  - **Multi-order conservation (Hill numbers)**: Tested in Run N-4 — PENDING full eval
  - **Secondary structure propensity**: Not tested — could be orthogonal to current signals

**Key gap:** We haven't successfully integrated ANY novel signal source from TECHNIQUES.md. All accepted improvements have been refinements to existing mechanisms (confidence scaling, calibration, ensemble weights).

---

## 2.7. Approach Audit

*Are you stuck in a loop? This section forces you to check.*

**Review your last 5 experiments** from `history.jsonl`. For each, categorize the **mechanism type**:

| Run | Mechanism Type | Score Delta |
|-----|---------------|-------------|
| N-4 | Conservation modulation | PENDING |
| N-3 | MSA feature (co-evolution) | TIMEOUT |
| N-2 | MSA feature (epistatic fit) | -0.000013 (flat) |
| N-1 | Ensemble weighting (confidence scaling) | -0.000096 (regressed) |
| N | Calibration (power transformation) | +0.000001 (essentially flat) |

**Plateau check:** Were all 5 experiments rejected (no score improvement)? YES (Run N had +0.000001 which is noise)

**If Yes** (all 5 rejected, no progress): You are in a plateau.

- State which category you've been in: **Refining existing CPCWE mechanisms** (conservation, ensemble weighting, calibration)
- State which category you're switching to: **Asymmetric error correction based on prediction direction**

**Justify the switch:**
1. All refinements to existing categories are exhausted — 4/5 experiments regressed or flat, 1/5 timed out
2. `paradigm_context.md` explicitly proposes TGAEC (Topologically-Guided Asymmetric Error Correction) based on the violation of the "model errors are symmetric" assumption
3. Current CPCWE treats overpredictions and underpredictions identically in residual propagation and confidence weighting
4. Diagnostics show asymmetric error patterns (e.g., positive→aromatic: +135.2 mean error, negative→hydrophobic: 3.1 mean |error|)
5. This is a fundamentally different mechanism — it doesn't tweak existing weights but detects and corrects DIRECTIONAL bias

**What signal does this access that previous categories didn't?**
- Previous categories: "How much should we trust this prediction?" (confidence, conservation, structure)
- New category: "What DIRECTION is the error in?" (overprediction vs underprediction, model-specific bias, position-specific bias)
- This accesses the SIGN of residuals, not just their MAGNITUDE

---

## 3. Hypothesis Formation

**Observation:** Diagnostics from `staging_diagnostics.md` show that error magnitudes are highly asymmetric across substitution classes:
- Worst classes: positive→aromatic (+135.2), positive→positive (+107.8), positive→negative (+71.7)
- Best classes: negative→hydrophobic (3.1), special→negative (3.3)
- A 40× difference in error magnitude between worst and best classes suggests systematic directional bias

**Hypothesis:** Model prediction errors are ASYMMETRIC — overpredictions and underpredictions have different stability in prediction space. When models overpredict harmfulness (score too high), the error is more stable and consistent than when they underpredict. This asymmetry can be detected via residual stability analysis and corrected directionally.

**Is this hypothesis consistent with your causal_model.md?** YES — causal_model.md explicitly notes "Error distributions are skewed, not symmetric" in the paradigm context, and TGAEC is listed as the imported domain logic.

---

## 4. Assumption Chain (3 iterations)

### Pass 1
**Assumption 1a:** Residual stability differs between overpredictions and underpredictions.
**Challenge 1a:** Does the data show this? We don't have residual stability metrics in diagnostics. But the asymmetric error magnitudes across substitution classes (+135 vs 3.1) strongly suggest directional bias.
**Verdict 1a:** **Questionable** — We need to COMPUTE residual stability to test this, not assume it.

**Assumption 1b:** Asymmetric bias is consistent across proteins (same models overpredict in same contexts).
**Challenge 1b:** Diagnostics show assay type effects (stability: 0.6417 vs binding: 0.4805). This suggests bias is assay-dependent, not globally consistent.
**Verdict 1b:** **Fails** — Asymmetric bias is likely protein/assay-specific, not globally uniform.

### Pass 2
*Take the assumptions from Pass 1 that held. None did.*

**Revised approach:** If global asymmetry doesn't exist, perhaps we can detect PER-PROTEIN asymmetry and apply protein-specific corrections.

**Assumption 2a:** We can detect per-protein asymmetry from the distribution of model vs ensemble residuals.
**Challenge 2a:** How? We have no ground truth labels to compute true residuals (prediction - experimental). We only have model vs ensemble residuals (VenusREM - ensemble), which are circular.
**Verdict 2a:** **Fails** — We cannot compute true asymmetry without labels.

**Assumption 2b:** We can use substitution-class-specific error patterns (from diagnostics) as a proxy for directional bias.
**Challenge 2b:** These are AGGREGATE patterns across all proteins. Applying them uniformly would be a global correction, which contradicts Assumption 1b (bias is protein-specific).
**Verdict 2b:** **Questionable** — This would be a heuristic correction, not a data-driven asymmetry detection.

### Pass 3
*One more level down.*

**Assumption 3a:** We can detect asymmetry from INTERNAL consensus patterns without ground truth.
**Challenge 3a:** How? If all models agree on a prediction, we call it "high confidence." But we don't know if they're agreeing on the CORRECT value or jointly hallucinating. The paradigm_context.md mentions "cluster stability analysis" for TGAEC, but it's vague.
**Verdict 3a:** **Fails** — No clear mechanism for label-free asymmetry detection.

**Assumption 3b:** The substitution-class error patterns in diagnostics are stable enough to encode as a correction system.
**Challenge 3b:** These patterns are based on the CURRENT algorithm's predictions. If we add a correction system, the patterns will shift. This is a circular dependency.
**Verdict 3b:** **Fails** — Correcting based on errors from the algorithm you're correcting is unstable.

**Discrepancies found:**
- Assumption 1a, 2a, 3a all FAIL — we cannot detect true asymmetry without ground truth
- Assumption 1b, 2b, 3b all FAIL or questionable — global corrections are contradicted by assay-specific patterns
- The TGAEC paradigm assumes we can detect asymmetry, but the mechanism is unclear

**Revised hypothesis:** The TGAEC paradigm is NOT viable as stated. We cannot detect asymmetric bias without ground truth labels. The substitution-class error patterns are a symptom, not a solution.

**Alternative direction:** Since we cannot detect asymmetry, let's look at what we CAN detect from the diagnostics that we haven't exploited:

1. **MSA signal inversion:** Shallow MSA proteins (0.6156) outperform deep MSA (0.5525)
2. **Conservation-error correlation:** Errors are larger at conserved positions (99.3) than variable positions (5.0)
3. **Structural context:** Errors are larger at core positions (50.3) than surface (21.5)

These are all things we CAN compute at runtime (MSA depth, conservation, burial). The GEMME conservation modulation attempt (Run N-5 smoke test passed) suggests we're on the right track but have the WRONG direction.

**Final hypothesis:** CURRENT GEMME CONSERVATION MODULATION HAS THE WRONG SIGN. Reducing GEMME weight at conserved positions (via `1.5 - entropy`) is causing errors at conserved positions. We should INCREASE GEMME weight at conserved positions instead.

---

## 5. Experiment Design

**Proposed change:** Invert GEMME conservation modulation direction.

Current code (best_so_far_strategy.py, line ~336):
```python
norm_entropy = (entropy - min_entropy) / max(1.0, max_entropy - min_entropy)
gemme_weight = base_w_gemme * (1.5 - norm_entropy)
```

New code:
```python
norm_entropy = (entropy - min_entropy) / max(1.0, max_entropy - min_entropy)
gemme_weight = base_w_gemme * (1.0 + 0.5 * norm_entropy)
```

This changes the formula from `(1.5 - entropy)` to `(1.0 + 0.5*entropy)`:
- At low entropy (conserved positions): weight goes from 1.5× to 1.0× (DECREASE)
- At high entropy (variable positions): weight goes from 0.5× to 1.5× (INCREASE)
- This FLIPS the direction — we now GIVE MORE WEIGHT to GEMME at variable positions, LESS at conserved positions

**Wait — this contradicts the hypothesis in Section 4.** Let me re-read.

Section 4 says: "Errors are larger at conserved positions (99.3) than variable positions (5.0)" and suggests we should INCREASE GEMME weight at conserved positions.

But Run N-5 (smoke test passed) removed conservation modulation entirely (constant weight), which would HELP if current modulation is harmful.

If current modulation `(1.5 - entropy)` gives MORE weight to conserved positions, and this is causing large errors, then we should GIVE LESS weight to conserved positions.

So the new formula `(1.0 + 0.5*entropy)` is CORRECT — it gives LESS weight to conserved positions, MORE to variable positions.

**Alternative explanations:**
1. Maybe the issue isn't GEMME weight direction, but the CONFIDENCE_SCALE for GEMME (currently 0.5). Maybe we should increase it.
2. Maybe the issue is that GEMME signal is simply noisy at deep MSA depths (MSA signal inversion diagnostic).
3. Maybe we need MSA-depth-dependent GEMME weighting (similar to the epistatic fit attempt).

**Why this hypothesis is better:**
- Run N-5 smoke test showed improvement when removing modulation, suggesting current modulation is harmful
- Diagnostics show large errors at conserved positions, which are currently HIGHER-weighted for GEMME
- This is a SINGLE, TESTABLE change (invert the formula)
- It addresses a concrete pattern (conserved positions = high error) with a concrete mechanism (reduce weight at those positions)

**Prediction:** Expected Spearman range: 0.5709–0.5715

**Falsification condition:**
- ≤ 0.5708: GEMME modulation direction is not the issue (or current direction was correct)
- = 0.570847: Modulation is irrelevant (constant weight from Run N-5 is already optimal)

---

## 6. Causal Model Update

**What does the causal_model need to change?**
- Add Run 13: GEMME conservation direction inversion
- Note: Power transformation (Run N) failed — dynamic range compression is not the bottleneck
- Note: TGAEC paradigm not viable without ground truth for asymmetry detection
- Note: Shifting focus to conservation modulation direction based on Run N-5 smoke test improvement

---

*Worksheet sections 1-6 complete. Proceed to write code. Then write
`staging_review_trigger.json` to inject your diff into Section 7 for verification.*

## 7. Code Verification

*Injected by watcher — diff of your changes vs best_so_far_strategy.py.*

```diff
--- best_so_far_strategy.py
+++ staging_strategy.py
@@ -2,6 +2,6 @@
 Pure CPCWE (Constraint-Propagated Confidence-Weighted Ensemble)

 

-DYNAMIC RANGE EXPANSION: Power transformation (x^0.7) to expand ensemble output tails.

-Testing whether ensemble compression is limiting performance.

+GEMME CONSERVATION DIRECTION INVERSION: Invert GEMME weight modulation formula from (1.5 - entropy) to (1.0 + 0.5*entropy).

+Current formula gives MORE weight to conserved positions (where errors are largest). New formula gives LESS weight to conserved positions.

 

 Mechanism:

@@ -10,7 +10,6 @@
 3. Confidence-weighted ensemble with model-specific scaling

 4. Residual propagation (3 iterations)

-5. Power transformation (x^0.7) to expand dynamic range

-6. Structure-based penalties with assay-specific multipliers

-7. GEMME conservation modulation (Shannon entropy)

+5. Structure-based penalties with assay-specific multipliers

+6. GEMME conservation modulation (INVERTED direction - weight decreases with conservation)

 """

 

@@ -33,5 +32,5 @@
 def score_mutations(sequences, protein_id, wild_type, mutations, msa=None):

     """

-    Pure CPCWE with power transformation for dynamic range expansion.

+    Pure CPCWE with inverted GEMME conservation modulation.

     """

     model_scores = get_model_scores(protein_id, mutations)

@@ -336,5 +335,8 @@
             if pos < len(position_conservation):

                 norm_entropy = position_conservation[pos]

-                gemme_weight = base_w_gemme * (1.5 - norm_entropy)

+                # INVERTED CONSERVATION MODULATION: Give LESS weight to conserved positions

+                # Old formula: (1.5 - norm_entropy) -> high weight at low entropy (conserved)

+                # New formula: (1.0 + 0.5 * norm_entropy) -> low weight at low entropy (conserved)

+                gemme_weight = base_w_gemme * (1.0 + 0.5 * norm_entropy)

             else:

                 gemme_weight = base_w_gemme

@@ -395,10 +397,4 @@
                 final_scores[i] *= product_penalty

 

-    # DYNAMIC RANGE EXPANSION: Apply power transformation to expand tails

-    # Power < 1 expands tails (makes extreme values more extreme)

-    # Power > 1 compresses tails (makes extreme values less extreme)

-    power = 0.7

-    final_scores = np.sign(final_scores) * np.power(np.abs(final_scores), power)

-

     return final_scores.tolist()

 

```

*For each change above, verify it matches your hypothesis. Fill in the table, then write `staging_code_reviewed` when all rows match.*

| Change | What It Does | Matches Hypothesis? |
|--------|--------------|---------------------|
| Updated docstring (line 2-6) | Documents GEMME direction inversion instead of power transformation | Y |
| Updated function docstring (line 35) | Documents inverted GEMME modulation | Y |
| Changed GEMME weight formula (line 338) | Inverts from (1.5 - entropy) to (1.0 + 0.5*entropy) | Y |
| Added explanatory comments (lines 336-338) | Explains the inversion logic | Y |
| Removed power transformation (lines 395-401) | Removes failed dynamic range expansion | Y |

**Verdict:** All match — proceed

| Change | What It Does | Matches Hypothesis? |
|--------|--------------|---------------------|
| | | |

