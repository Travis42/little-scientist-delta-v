# TECHNIQUES.md — Advanced MSA-Derived Features

*Persistent reference file. These techniques are computed from the MSA at runtime
inside your `score_mutations()` function. They capture signal that none of the 5
pre-computed models or physicochemical features provide.*

*To use: copy the relevant functions into your strategy and call them with the
`msa` argument passed to `score_mutations()`.*

---

## 1. Epistatic Fit (most recommended)

**What it captures:** For each mutation, computes whether evolution has already
"tried" this substitution. It measures the minimum Hamming distance from the
wild-type sequence to any MSA sequence that already carries the mutant amino
acid at the target position.

**Why it's different from model predictions:** The 5 models give you a point
prediction per mutation. Epistatic fit tells you whether close evolutionary
neighbors have tolerated this specific substitution — a direct query of the
MSA's empirical landscape. A mutation that appears in a sequence 2 substitutions
away from wild-type is almost certainly tolerated; one that only appears in
sequences 50 substitutions away (or never) is likely disruptive.

**Signal uniqueness:** GEMME uses conservation (how variable is this position).
Epistatic fit uses substitution history (has THIS specific AA change been seen
in near-neighbors). These are correlated but not identical — a position can be
variable overall yet never carry the specific mutant AA in close relatives.

### Code

```python
import numpy as np
from collections import defaultdict

_AA_INDEX = {aa: i for i, aa in enumerate('ACDEFGHIKLMNPQRSTVWY')}
_MAX_MSA_FOR_FULL_FIT = 2000

def build_epistatic_fit_map(msa, wild_type):
    """Build mutation-specific epistatic fit map.

    Call once per protein at the start of score_mutations().

    Returns:
        avg_distance: MSA-wide average Hamming distance from wild-type
        fit_map: {(position, amino_acid): [list of Hamming distances]}
    """
    if msa is None or len(msa) == 0:
        return 0.0, {}

    seq_len = len(wild_type)
    n_seqs = len(msa)

    if n_seqs > _MAX_MSA_FOR_FULL_FIT:
        indices = np.random.choice(n_seqs, _MAX_MSA_FOR_FULL_FIT, replace=False)
        msa = [msa[i] for i in indices]

    # Precompute Hamming distances from wild-type
    hamming_distances = np.zeros(len(msa), dtype=np.float32)
    for i, seq in enumerate(msa):
        dist = sum(1 for a, b in zip(wild_type, seq) if a != b and a != '-' and b != '-')
        hamming_distances[i] = dist

    avg_distance = max(np.mean(hamming_distances), 1.0)

    fit_map = defaultdict(lambda: defaultdict(list))
    for i, seq in enumerate(msa):
        dist = hamming_distances[i]
        for pos in range(min(seq_len, len(seq))):
            aa = seq[pos]
            if aa in _AA_INDEX:
                fit_map[pos][aa].append(dist)

    return avg_distance, fit_map

def get_epistatic_fit(pos, mut_aa, avg_distance, fit_map, conservation_val):
    """Get epistatic fit score for a single mutation.

    Returns: float in [0, 3+]
    - Low (< 1.0): mutation exists in close MSA neighbors → likely tolerated
    - ~1.0: mutation exists but only in distant sequences
    - High (> 1.0): mutation not observed in MSA → novel, scaled by conservation
    """
    if pos in fit_map and mut_aa in fit_map[pos]:
        distances = fit_map[pos][mut_aa]
        if distances:
            min_dist = min(distances)
            return np.clip(min_dist / (avg_distance + 1e-10), 0.0, 3.0)

    # Mutation not observed — novel substitution at conserved position is worse
    return 1.0 + conservation_val * 2.0
```

### Usage in a strategy

```python
avg_dist, fit_map = build_epistatic_fit_map(msa, wild_type)

for pos, wt_aa, mut_aa in mutations_list:
    epi_fit = get_epistatic_fit(pos, mut_aa, avg_dist, fit_map, conservation[pos])
    # Multiply or add to conservation weight
    conservation_weight *= epi_fit
```

---

## 2. Co-Evolution Coupling

**What it captures:** Detects positions whose amino acid frequencies co-vary
across the MSA. Mutations at positions that co-evolve with neighbors have
amplified effects — the mutation doesn't just affect its own position, it
disrupts co-adapted pairs.

**Why it's different:** All 5 models predict mutation effects independently per
position. Co-evolution coupling captures inter-position dependencies — the
mutation's effect depends on what's happening at *other* positions. This is
genuinely orthogonal signal.

### Code

```python
def compute_coupling_scores(freq_matrix, conservation):
    """Compute co-evolution coupling scores from position frequency matrix.

    Call after computing position frequencies from the MSA.

    Args:
        freq_matrix: (seq_len × 20) position frequency matrix
        conservation: (seq_len,) conservation scores

    Returns: (seq_len,) coupling scores in [0, 1], or None if too short
    """
    seq_len = freq_matrix.shape[0]
    if seq_len < 5:
        return None
    if seq_len > 500:  # Skip for very long proteins (O(n²) memory)
        return conservation

    freq_centered = freq_matrix - np.mean(freq_matrix, axis=1, keepdims=True)
    freq_std = np.maximum(np.std(freq_matrix, axis=1, keepdims=True), 1e-10)
    freq_normalized = freq_centered / freq_std

    corr_matrix = np.dot(freq_normalized, freq_normalized.T) / 20.0
    corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)
    np.fill_diagonal(corr_matrix, 0.0)

    coupling = np.mean(np.abs(corr_matrix), axis=1)
    if np.max(coupling) > np.min(coupling):
        coupling = (coupling - np.min(coupling)) / (np.max(coupling) - np.min(coupling))

    return coupling
```

### Usage

```python
coupling = compute_coupling_scores(freq_matrix, conservation)
if coupling is not None:
    conservation_weight += 0.5 * coupling[pos]
```

---

## 3. Multi-Order Conservation (Hill Numbers + Gini-Simpson)

**What it captures:** Four complementary conservation metrics from the same MSA:

- **Hill q=0** (richness): counts how many amino acids are present
- **Hill q=1** (Shannon entropy): effective diversity weighting by frequency
- **Hill q=2** (Simpson): effective diversity weighting dominant amino acids more
- **Gini-Simpson**: probability that two random sequences differ at this position

**Why multiple metrics:** Each captures different aspects of variability. q=0
treats all amino acids equally regardless of frequency. q=1 down-weights rare
amino acids. q=2 focuses on the dominant amino acid. Gini-Simpson measures
difference probability. Together they give a richer conservation profile than
any single metric.

### Code

```python
_AA_INDEX = {aa: i for i, aa in enumerate('ACDEFGHIKLMNPQRSTVWY')}
_PSEUDOCOUNT = 1.0

def compute_weighted_frequencies(msa):
    """Compute position frequencies with phylogenetic cluster weighting."""
    if msa is None or len(msa) == 0:
        return None

    n_seqs = len(msa)
    seq_len = len(msa[0])

    # Cluster weighting: down-weight overrepresented clades
    threshold = max(int(0.1 * seq_len), 1)
    cluster_id = np.arange(n_seqs, dtype=np.int32)
    current = 0
    for i in range(n_seqs):
        if cluster_id[i] != i:
            continue
        cluster_id[i] = current
        for j in range(i + 1, n_seqs):
            if cluster_id[j] == j:
                dist = sum(1 for a, b in zip(msa[i], msa[j])
                          if a != b and a != '-' and b != '-')
                if dist <= threshold:
                    cluster_id[j] = current
        current += 1

    sizes = np.bincount(cluster_id, minlength=current)
    weights = 1.0 / sizes[cluster_id]

    freq = np.full((seq_len, 20), _PSEUDOCOUNT)
    for idx, seq in enumerate(msa):
        w = weights[idx]
        for pos in range(seq_len):
            aa = seq[pos]
            if aa in _AA_INDEX:
                freq[pos, _AA_INDEX[aa]] += w

    return freq / np.sum(freq, axis=1, keepdims=True)

def compute_multi_order_conservation(freq_matrix):
    """Compute 4 conservation metrics and combine them."""
    freq = np.clip(freq_matrix, 1e-10, 1.0)

    # Hill q=0: species richness
    hill_q0 = np.sum(freq > 1e-6, axis=1).astype(float)
    # Hill q=1: Shannon entropy → effective diversity
    hill_q1 = np.exp(-np.sum(freq * np.log(freq), axis=1))
    # Hill q=2: Simpson → effective diversity
    hill_q2 = 1.0 / np.sum(freq ** 2, axis=1)
    # Gini-Simpson: probability of difference
    gini_simpson = 1.0 - np.sum(freq ** 2, axis=1)

    max_hill = 20.0
    cons_q0 = np.clip(1.0 - (hill_q0 - 1) / (max_hill - 1), 0, 1)
    cons_q1 = np.clip(1.0 - (hill_q1 - 1) / (max_hill - 1), 0, 1)
    cons_q2 = np.clip(1.0 - (hill_q2 - 1) / (max_hill - 1), 0, 1)
    cons_gini = 1.0 - gini_simpson  # invert: high diversity = low conservation

    # Weighted combination (tunable)
    conservation = 0.2 * cons_q0 + 0.3 * cons_q1 + 0.5 * cons_q2 + 0.1 * cons_gini
    return conservation, freq
```

---

## 4. Secondary Structure Propensity (Chou-Fasman)

**What it captures:** Penalties for mutations that break helices or sheets
based on Chou-Fasman propensity values. Uses conservation as a proxy for
structural context (conserved positions are likely buried/structured).

### Code

```python
_HELIX_FORMERS = {'A', 'E', 'L', 'M', 'Q', 'K'}
_HELIX_BREAKERS = {'P', 'G'}
_SHEET_FORMERS = {'V', 'I', 'Y', 'F', 'C', 'T'}
_SHEET_BREAKERS = {'E', 'D', 'P', 'G', 'K', 'S'}

def compute_secstruct_penalty(wt_aa, mut_aa, conservation_val):
    """Penalty for helix/sheet breaking mutations."""
    penalty = 0.0

    # Helix breaking: removing a former or adding a breaker
    if wt_aa in _HELIX_FORMERS and mut_aa in _HELIX_BREAKERS:
        penalty += 1.5 * conservation_val
    elif wt_aa in _HELIX_FORMERS and mut_aa not in _HELIX_FORMERS:
        penalty += 0.8 * conservation_val

    # Sheet breaking
    if wt_aa in _SHEET_FORMERS and mut_aa in _SHEET_BREAKERS:
        penalty += 1.5 * conservation_val
    elif wt_aa in _SHEET_FORMERS and mut_aa not in _SHEET_FORMERS:
        penalty += 0.8 * conservation_val

    return penalty
```

---

## Summary: Which to try first

| Technique         | Novelty   | Compute Cost  | Best For                          |
|-------------------|-----------|---------------|-----------------------------------|
| Epistatic fit     | Very high | Moderate (O(N×L)) | Improving per-mutation scoring   |
| Co-evolution      | High      | High (O(L²))  | Proteins < 500 residues           |
| Multi-order cons. | Medium    | Low           | Replacing Shannon entropy         |
| Secstruct penalty | Medium    | Low           | Stability assay proteins          |

**Recommended starting point:** Epistatic fit. It's the most novel signal
(none of the 5 models query the MSA this way) and directly improves
per-mutation scoring without needing a completely new approach.
