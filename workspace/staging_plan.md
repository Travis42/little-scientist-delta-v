# Run 12: Dynamic Range Expansion via Power Transformation

## Experiment Plan

**What change:**
After computing the final ensemble scores, apply power transformation `final_scores = sign(x) * |x|^0.7` to expand dynamic range while preserving rank order.

**Why:**
Diagnostics show predicted IQR is 0.3× narrower than experimental IQR. Ensemble averaging inherently compresses variance. Power transformation (exponent < 1) expands tails to recover lost signal.

**Expect:**
Modest improvement to 0.5708-0.5715 (vs baseline 0.570847). This is a refinement, not new signal.

**Falsification:**
- ≤ 0.5707: Power transformation amplifies noise, not signal
- = 0.570847: Dynamic range compression is not the bottleneck

**Status:**
- Code written (staging_strategy.py)
- Smoke test triggered (waiting for debounce to clear)
- Full eval will run automatically after smoke passes