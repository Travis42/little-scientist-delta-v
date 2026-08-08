# Experiment Worksheet — Run [FILL IN RUN NUMBER]

*This worksheet is your scientific reasoning record. Fill it in completely each iteration before writing code. The validator does not enforce formatting, but your reasoning quality directly determines your algorithm quality. Show your work.*

---

## 1. Prior Run Falsification Check

**Last run's prediction:** [prediction_low]–[prediction_high]

**Last run's actual score:** [score]

**Last run's falsification condition:** *"What result would prove you wrong?"* → [copy from last run's worksheet or history.jsonl]

**Did falsification trigger?** [Yes / No / N/A — first run]

**If yes:** What does this mean for your hypothesis? Which assumption was wrong?

**If no:** Your hypothesis survived. But did it survive because it's right, or because the test was too weak to distinguish?

---

## 2. Evidence Synthesis

*Review your last ~10 experiments from `history.jsonl`. What do you actually know?*

| Run | Hypothesis (1-line) | Predicted | Actual | Verdict | What we learned |
|-----|---------------------|-----------|--------|---------|-----------------|
| N-9 | | | | | |
| N-8 | | | | | |
| N-7 | | | | | |
| N-6 | | | | | |
| N-5 | | | | | |
| N-4 | | | | | |
| N-3 | | | | | |
| N-2 | | | | | |
| N-1 | | | | | |
| N   | | | | | |

**Pattern across runs:** What trend do you see? Not what you hoped for — what actually happened?

**What is surprising?** Look at the last result through the lens of your previous hypothesis, causal model, and notes. What did you not expect?

---

## 2.5. Data Sources

*What external data did you use in this strategy? Check all that apply.*

- [ ] MSA only (default — no external data)
- [ ] approaches in `TECHNIQUES.md`
- [ ] `proteingym_data.get_model_scores()` — VenusREM / S3F_MSA / ESM2_15B / ProSST-2048 / GEMME predictions
- [ ] Physicochemical features (in `get_model_scores()`): `blosum62`, `delta_charge`, `delta_volume`, `delta_hydro`, `wt_aa`, `mut_aa`
- [ ] `proteingym_data.get_residue_structure()` — solvent accessibility, burial class
- [ ] `proteingym_data.get_protein_info()` — MSA stats, selection type, organism

**How used:** [1-2 sentences on what the model predictions/structure/features are doing in your strategy]

**Data you are NOT using and why:** [Required — list any available data sources you chose not to incorporate. "Nothing relevant left out" is not acceptable without justification.]

- Model predictions not used: [which of the 5? why? or "all 5 used"]
- Physicochemical features not used: [blosum62, delta_charge, delta_volume, delta_hydro — why?]
- Residue structure not used: [RSA, burial_class — why?]
- TECHNIQUES.md features not used: [epistatic fit, co-evolution coupling, etc. — why?]

⚠️ If you are not using a data source, you must explain what you would gain by ignoring it, or what you would lose by including it. Convenience is not a valid reason.

⚠️ **Remember:** The goal is to *beat the all-time best* (see `all_time_best.txt`). If you're not using all available signal sources, explain your reasoning.

---

## 2.7. Approach Audit

*Are you stuck in a loop? This section forces you to check.*

**Review your last 5 experiments** from `history.jsonl`. For each, categorize the **mechanism type** — the kind of change you made, not the specific parameter. Examples of mechanism types (not exhaustive — invent your own labels if needed):

- Ensemble weighting (adjusting how models are combined)
- Calibration (transforming score distributions)
- Structure-based penalty (using RSA/burial to modify scores)
- Conservation modulation (using MSA entropy or evolutionary signal)
- MSA feature (epistatic fit, co-evolution, multi-order conservation)
- Physicochemical feature (BLOSUM62, charge/volume/hydrophobicity as independent signal)
- Multi-mutant handling (how combinations are processed)
- Novel combination (an approach that doesn't fit any above)

| Run | Mechanism Type | Score Delta |
|-----|---------------|-------------|
| N-4 |               |             |
| N-3 |               |             |
| N-2 |               |             |
| N-1 |               |             |
| N   |               |             |

**Plateau check:** Were all 5 experiments rejected (no score improvement)? Yes / No

**If Yes** (all 5 rejected, no progress): You are in a plateau. Look at the mechanism types above. If they are all or nearly all the same type, you MUST propose an experiment from a **different mechanism category** this cycle.

- State which category you've been in: ______
- State which category you're switching to: ______
- Justify the switch: Why is the new category worth trying? What signal or data source does it access that the previous category didn't?

**If No** (at least one accepted, or fewer than 5 experiments total): You may continue in the current direction. But still note whether your recent experiments share a mechanism type — diversity now prevents plateaus later.

---

## 3. Hypothesis Formation

**Observation:** What specific phenomenon in the data demands explanation?

**Hypothesis:** Why does this occur? (Propose a causal mechanism — not a restatement of the observation)

**Is this hypothesis consistent with your causal_model.md?** [Yes / No — if no, explain the conflict]

---

## 4. Assumption Chain (3 iterations)

*Your hypothesis rests on assumptions. Surface them. Challenge them. Repeat.*

### Pass 1
**Assumption 1a:** [What must be true for your hypothesis to hold?]
**Challenge 1a:** [Is this actually true? What evidence supports or contradicts it?]
**Verdict 1a:** [Holds / Questionable / Fails — and why]

**Assumption 1b:** [Another assumption]
**Challenge 1b:** [...]
**Verdict 1b:** [...]

### Pass 2
*Take the assumptions from Pass 1 that held. What do THEY assume?*

**Assumption 2a:** [Derived from 1a or 1b]
**Challenge 2a:** [...]
**Verdict 2a:** [...]

**Assumption 2b:** [...]
**Challenge 2b:** [...]
**Verdict 2b:** [...]

### Pass 3
*One more level down.*

**Assumption 3a:** [Derived from 2a or 2b]
**Challenge 3a:** [...]
**Verdict 3a:** [...]

**Discrepancies found:** [Did any assumption fail? Did you discover a contradiction? Did this process change your hypothesis?]

**Revised hypothesis (if any assumption failed):** [Updated hypothesis, or "unchanged" if all held]

---

## 5. Experiment Design

**Proposed change:** Modify what, from what, to what. Be specific about the code change.

**Alternative explanations:** What else could explain the pattern? Why is your hypothesis better than these alternatives?

**Prediction:** Expected Spearman range: [low]–[high]

**Falsification condition:** What specific result would prove this hypothesis wrong? (Not "score goes down" — what pattern in the data would contradict the *mechanism* you proposed?)

---

## 6. Causal Model Update

**What does the causal_model need to change?** Based on this worksheet, what should be added, revised, or removed?

---

*Worksheet sections 1-6 complete. Proceed to write code. Then write
`staging_review_trigger.json` to inject your diff into Section 7 for verification.*

---

## 7. Code Verification

*The watcher will inject a diff of your changes vs `best_so_far_strategy.py` here after
you write `staging_review_trigger.json`. Do NOT generate the diff yourself.*

*After injection, verify each change against your hypothesis. This is not a rubber stamp —
if a change doesn't match your intent, FIX THE CODE and re-trigger the review.*

Each change in the diff above gets a row:

| Change | What It Does | Matches Hypothesis? |
|--------|--------------|---------------------|
| [change 1 from diff] | [describe]   | Y/N                 |
| [change 2 from diff] | [describe]   | Y/N                 |

**Verdict:** [All match — proceed / Mismatch found — fixing code]

*If any row is N: rewrite `staging_strategy.py`, delete `staging_code_reviewed`
(if it exists), write `staging_review_trigger.json` again to re-inject the new diff.
Repeat until all rows are Y.*

*When all rows are Y, write an empty file `staging_code_reviewed` to signal
the review is complete. Then proceed to smoke testing.*
