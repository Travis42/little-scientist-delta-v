# DATA PRIMER — External Model & Structure Predictions

*Reference for using the `proteingym_data` library in your strategy. Read this
once; it stays true across runs.*

---

## What is available

The eval gives you an MSA at runtime (the `msa` argument to `score_mutations`).
On top of that, you can import a library that exposes **pre-computed
state-of-the-art model predictions**, **per-residue structure data**, and
**protein metadata** for all 217 ProteinGym assays.

```python
from proteingym_data import get_model_scores, get_residue_structure, get_protein_info
```

These are *optional*. A pure-MSA strategy still works. But the model
predictions encode information that is extremely hard to recover from an MSA
alone (learned long-range structure, side-chain chemistry, etc.), and using
them can substantially boost Spearman correlation.

---

## The five models in `get_model_scores()`

```python
scores = get_model_scores(protein_id, mutations)
# scores["A10C"] == {"venus_rem": -1.23, "s3f_msa": 0.20, "esm2_15b": -4.04,
#                       "prosst_2048": -0.45, "gemme": -2.1,
#                       "wt_aa": "A", "mut_aa": "C",
#                       "delta_charge": 0.0, "delta_volume": 19.9,
#                       "delta_hydro": 0.7, "blosum62": 0}

```

In addition to model predictions, each mutation includes **physicochemical
features** computed from the amino acid substitution:
- `wt_aa` / `mut_aa` — wild-type and mutant amino acid identities
- `delta_charge` — change in net charge (e.g., A→D = -1.0)
- `delta_volume` — change in side-chain volume in Å³ (e.g., A→W = +137.6)
- `delta_hydro` — change in hydrophobicity (Kyte-Doolittle scale)
- `blosum62` — BLOSUM62 substitution score for this AA pair (positive = conservative, negative = radical)

These features are deterministic from the mutation code — no model or label
data involved. They provide signal orthogonal to all 5 models: charge changes
affect electrostatic interactions, volume changes affect packing, and
hydrophobicity shifts affect folding. BLOSUM62 captures evolutionary
substitution frequency, complementing GEMME's alignment-based signal.
```

**Mutations must be mutation codes** (e.g. `"A10C"`, `"A10C:A20G"` for
multi-mutants), NOT full amino acid sequences. The eval passes mutation codes
in the `mutations` parameter — use them directly for DB lookups.

### Model overview

| Key          | Source model  | What it is                                                     | Avg Spearman | Score range    |
|--------------|---------------|----------------------------------------------------------------|--------------|----------------|
| `venus_rem`  | VenusREM      | Ensemble of structure-aware + MSA models (current SOTA)        | 0.518        | ~-8 to +2     |
| `s3f_msa`    | S3F_MSA       | Sequence-based statistical model using MSA frequencies         | 0.496        | ~-5 to +4     |
| `esm2_15b`   | ESM2_15B      | Pure-sequence protein language model (largest ESM2)            | 0.453        | ~-30 to +6    |
| `prosst_2048`| ProSST K=2048 | Quantized structure tokens + sequence (discrete 3D encoding)   | 0.507        | ~-30 to -20   |
| `gemme`      | GEMME         | Pure alignment-based evolutionary model (no ML, no structure)  | 0.455        | ~-30 to +5    |

### Why these five models

The five models span the maximum diversity of signal sources:

- **VenusREM** — structure + MSA retrieval (best single model)
- **S3F_MSA** — structure + MSA frequencies (different structure encoding)
- **ESM2_15B** — pure sequence, no structure or MSA (largest language model)
- **ProSST K=2048** — quantized structure as discrete tokens (unique 3D representation, no other model uses this encoding)
- **GEMME** — pure alignment/evolutionary signal (no neural network, captures different signal from ML models)

ProSST K=2048 encodes 3D structure as discrete tokens — a fundamentally different representation from the continuous RSA/ASA features. It scores 0.653 on Stability assays (best-in-class). GEMME uses only evolutionary conservation patterns from MSAs, with no machine learning — it captures raw evolutionary signal that ML models may overfit past.

### Critical: scale mismatch

The three models are on **completely different scales**. A naive weighted
average of raw scores produces garbage (Spearman ≈ 0). You MUST normalize
before blending:

```python
# Z-score normalize each model's predictions, THEN blend
v_z = (venus_arr - venus_arr.mean()) / (venus_arr.std() + 1e-9)
s_z = (s3f_arr - s3f_arr.mean()) / (s3f_arr.std() + 1e-9)
p_z = (prosst_arr - prosst_arr.mean()) / (prosst_arr.std() + 1e-9)
g_z = (gemme_arr - gemme_arr.mean()) / (gemme_arr.std() + 1e-9)
blend = 0.35 * v_z + 0.25 * s_z + 0.15 * e_z + 0.15 * p_z + 0.10 * g_z
```

### Sign convention

All three models correlate **positively** with DMS experimental scores.
Negative = more harmful, positive = less harmful. **Return predictions as-is
— never flip signs or invert rankings.** VenusREM verbatim scores 0.5547 on
full eval.

### Per-protein variation

S3F_MSA has a lower global average (0.496) but **outperforms VenusREM on many
individual proteins**. ProSST-2048 scores 0.507 globally but **beats VenusREM
on Stability assays (0.653 vs 0.650)**. GEMME excels on viral proteins. The
global average hides per-protein strength. Do not assume any single model is
always best — on some proteins S3F, ProSST, or even GEMME wins. This variation
is why ensembling works.

### Coverage

- All 217 proteins have predictions for all mutations (100% coverage)
- Multi-mutant entries (e.g. `"A10C:A20G"`) are included — 72% of all entries
- Missing predictions are rare; handle gracefully with a fallback to 0.0

---

## Per-residue structure: `get_residue_structure()`

```python
struct = get_residue_structure(protein_id)
# struct[10] == {"wt_aa": "A", "asa": 45.2, "rsa": 0.18, "burial_class": "buried"}
```

Derived from AlphaFold/PDB structures (solvent accessibility computed via
FreeSASA). Returns one entry per residue position (1-indexed).

| Field         | Type | Meaning                                                       |
|---------------|------|---------------------------------------------------------------|
| `wt_aa`       | str  | Wild-type amino acid at that position                          |
| `asa`         | float| Absolute solvent-accessible surface area (Å²)                 |
| `rsa`         | float| Relative solvent accessibility (0 = fully buried, 1 = exposed) |
| `burial_class`| str  | `buried` / `core` / `intermediate` / `surface`                |

**Coverage:** All 217 proteins have structure data. Proteins without it
return `{}` (historically some lacked data, now all covered).

### Why structure matters for mutation effects

The same amino acid substitution can be benign or devastating depending on
where it occurs in the 3D structure:

- **Buried residues (rsa < 0.2):** These pack the protein core. Mutations
  here disrupt the hydrophobic core that holds the protein together. A
  hydrophobic→charged substitution at a buried site (e.g. L→D in the core)
  can destabilize the entire fold. Models often underweight this.

- **Surface residues (rsa > 0.5):** These interact with solvent and other
  molecules. Substitutions here are usually tolerated unless they hit a
  functional site (active site, binding interface, PTM site).

- **Intermediate (0.2 < rsa < 0.5):** Boundary region. Effects depend on
  the specific structural context.

**How to use it:** Structure data is most valuable as a *correction* to model
predictions, not a standalone signal. When a model predicts a mutation is
harmful but the residue is surface-exposed, the model may be wrong (surface
mutations are usually tolerated). When a model predicts benign but the
residue is buried with a radical substitution, the model may be missing the
structural impact.

**Concrete approach:** Scale model predictions by a position-specific factor
derived from `rsa`. Or use `burial_class` to select different correction
strengths per structural context.

**Extracting position from a mutation code:**

```python
def parse_position(mutant):
    # "A673C" -> 673
    # "A673E:A692E" -> 673 (first mutation, for multi-mutants
    # you may want to process each component separately)
    first = mutant.split(":")[0].strip()
    import re
    m = re.match(r'[A-Z](\d+)[A-Z]', first)
    return int(m.group(1)) if m else None
```

---

## Protein metadata: `get_protein_info()`

```python
info = get_protein_info(protein_id)
# info["seq_len"], info["msa_num_seqs"], info["coarse_selection_type"], ...
```

Key fields:

| Field                    | What it tells you                                              |
|--------------------------|----------------------------------------------------------------|
| `seq_len`                | Protein length                                                 |
| `coarse_selection_type`  | `Activity` / `Expression` / `OrganismalFitness` / `Stability` — what the assay measures |
| `selection_type`         | Finer-grained assay type                                       |
| `source_organism`, `taxon` | Organism context                                             |
| `msa_num_seqs`           | Number of sequences in the full MSA                            |
| `msa_n_eff`, `msa_neff_l`| Effective sequences (diversity) — confidence in conservation   |
| `msa_perc_cov`           | MSA coverage fraction                                          |
| `has_structure`, `pdb_file` | Whether structure data exists for this protein              |
| `includes_multiple_mutants`, `total_mutants`, etc. | Mutation-count context      |

### Why assay type matters

Different DMS experiments measure different biological properties. A mutation
can be structurally benign (no stability impact) but catalytically dead
(activity destroyed), or vice versa. The models don't always know which
property is being measured.

The `coarse_selection_type` categories:

- **Stability:** Measures whether the protein still folds correctly.
  Buried mutations dominate the signal. Structure-based corrections
  should help most here.
  
- **Activity:** Measures whether the protein still performs its function
  (enzyme catalysis, ligand binding, etc.). Active-site mutations dominate,
  regardless of burial. Structure data helps less unless you know where the
  active site is.
  
- **Expression:** Measures how much protein is produced. Regulatory and
  folding-quality-control signals dominate. Model predictions may be less
  relevant here.
  
- **OrganismalFitness:** Measures overall impact on the organism
  (growth, survival). Combines stability, activity, and expression effects.
  Hardest to predict; may benefit from the broadest ensemble.
  
- **Binding:** Measures specific interaction (antibody-antigen,
  receptor-ligand). Interface residues matter most. General structure data
  (burial class) is less useful than knowing the binding interface.

**How to use it:** Build per-category correction functions. Or use
`coarse_selection_type` to select different ensemble weights — Stability
assays might weight structure-aware corrections higher, while Activity assays
might benefit from different corrections.

### Why MSA diversity matters

`msa_n_eff` (effective number of sequences) tells you how much evolutionary
information is available for this protein:

- **High N_eff (>100):** Rich evolutionary signal. Conservation patterns are
  reliable. MSA-derived corrections may complement model predictions.
  
- **Low N_eff (<20):** Sparse evolutionary signal. Conservation is
  unreliable. Trust model predictions more heavily; MSA corrections likely
  add noise.
  
- **`msa_neff_l`** is N_eff normalized by sequence length — useful for
  comparing across proteins of different sizes.

**How to use it:** Modulate the strength of MSA-based corrections by N_eff.
Or detect proteins where models might be overconfident (low N_eff proteins
are harder for everyone).

### Multi-mutant context

72% of mutations in the database are multi-mutant combinations (e.g.
`"A673E:A692E"` — two simultaneous mutations). Models predict these
differently than single mutations:

- Some models handle epistasis (mutation interactions) well; others just
  sum individual effects.
- Multi-mutant effects are non-additive: two individually harmful mutations
  may be neutral together (compensation) or worse than either alone
  (synergy).
- `includes_multiple_mutants=1` and the single/multiple counts tell you
  how much of each protein's data is multi-mutant.

**How to use it:** If a protein is mostly multi-mutants, look at whether
the models disagree on those entries — disagreement may reveal epistatic
effects the models handle poorly.

---

## Example strategy

```python
import numpy as np
from proteingym_data import get_model_scores

def score_mutations(sequences, protein_id, wild_type, mutations, msa=None):
    model_scores = get_model_scores(protein_id, mutations)

    venus, s3f, esm, prosst, gemme = [], [], [], [], []
    for mut in mutations:
        ms = model_scores.get(mut, {})
        venus.append(ms.get("venus_rem", 0.0) or 0.0)
        s3f.append(ms.get("s3f_msa", 0.0) or 0.0)
        esm.append(ms.get("esm2_15b", 0.0) or 0.0)
        prosst.append(ms.get("prosst_2048", 0.0) or 0.0)
        gemme.append(ms.get("gemme", 0.0) or 0.0)

    v = np.array(venus)
    s = np.array(s3f)
    e = np.array(esm)
    p = np.array(prosst)
    g = np.array(gemme)

    # Z-score normalize each model
    def z(a):
        std = a.std()
        return (a - a.mean()) / std if std > 1e-9 else a - a.mean()

    # Weighted blend in z-score space
    blend = 0.35 * z(v) + 0.25 * z(s) + 0.15 * z(e) + 0.15 * z(p) + 0.10 * z(g)
    return blend.tolist()
```

**Tips:**
- Call `get_model_scores(protein_id, mutations)` once per protein (not per
  mutation) — it's indexed and fast (~5-20ms for the whole protein).
- Handle missing predictions gracefully (`ms.get(...)` may return `None`).
- The `mutations` list from the eval is already in mutation code format.
- Multi-mutants (e.g. `"A10C:A20G"`) are valid DB keys.

---

## API Reference

```python
from proteingym_data import get_model_scores, get_residue_structure, get_protein_info
```

### `get_model_scores(protein_id: str, mutants: list[str] | None = None) -> dict[str, dict[str, float]]`

Returns `{mutant_code: {"venus_rem": float, "s3f_msa": float, "esm2_15b": float, "prosst_2048": float, "gemme": float}}`.

- `protein_id`: e.g. `"A4_HUMAN_Seuma_2022"`
- `mutants`: list of mutation codes (e.g. `["A673C", "A673E:A692E"]`). If `None`, returns all mutations for the protein.
- Keys are mutation codes: single (`"A673C"`) or multi (`"A673E:A692E"`).
- Values are floats. Missing predictions are `None` — use `or 0.0` as fallback.
- 100% coverage: every mutation in every protein has predictions.

### `get_residue_structure(protein_id: str) -> dict[int, dict[str, str|float]]`

Returns `{position: {"wt_aa": str, "asa": float, "rsa": float, "burial_class": str}}`.

- `position`: 1-indexed residue position (int).
- `wt_aa`: wild-type amino acid (single letter).
- `asa`: absolute solvent-accessible surface area in Å².
- `rsa`: relative solvent accessibility (0.0 = fully buried, 1.0 = fully exposed).
- `burial_class`: one of `"buried"`, `"core"`, `"intermediate"`, `"surface"`.
- Returns `{}` for 0 proteins without structure data.

### `get_protein_info(protein_id: str) -> dict[str, str|int|float]`

Returns per-protein metadata. Key fields:

| Field | Type | Values |
|---|---|---|
| `seq_len` | int | Protein length |
| `coarse_selection_type` | str | `"Activity"`, `"Expression"`, `"OrganismalFitness"`, `"Stability"`, `"Binding"` |
| `selection_type` | str | Finer assay description |
| `source_organism` | str | e.g. `"Homo sapiens"` |
| `taxon` | str | e.g. `"Human"`, `"Virus"`, `"Eukaryote"` |
| `msa_num_seqs` | int | MSA sequence count |
| `msa_n_eff` | float | Effective sequences (diversity) |
| `msa_neff_l` | float | N_eff normalized by sequence length |
| `msa_perc_cov` | float | MSA coverage fraction (0–1) |
| `has_structure` | int | 1 if structure data exists, 0 otherwise |
| `pdb_file` | str | PDB filename (or empty) |
| `includes_multiple_mutants` | int | 1 if multi-mutant variants present |
| `total_mutants` | int | Total mutation entries |
| `single_mutants` | int | Single-mutation entries |
| `multiple_mutants` | int | Multi-mutation entries |

Returns `{}` for unknown proteins.

---

## Performance

- **Lookup time:** ~5-20 ms per `get_model_scores(protein_id, mutations)` call
  (indexed by `(protein_id, mutant)`).
- **Memory:** near-zero — the library opens a read-only SQLite connection per
  call and never loads the whole DB. Safe alongside large MSAs.
- **Connection:** always read-only (`mode=ro`). Cannot lock or corrupt the DB.

---

## What is NOT in the database

For label-leakage safety, the database contains **no ground-truth labels**:
no `DMS_score`, no `DMS_score_bin`, no `mutated_sequence`. You cannot
accidentally (or deliberately) read the answer. Your score comes only from
predictive signals: models, structure, and the MSA you are given.
