# DATA_REFERENCE.md — ProteinGym Data API

*This is the single source of truth for all data available to your strategy.
Read this file to know what data exists and how to access it.*

---

## Quick Reference

```python
from proteingym_data import get_model_scores, get_residue_structure, get_protein_info

# Per-mutation predictions from 5 SOTA models + physicochemical features
ms = get_model_scores(protein_id, mutations)
# ms["A10C"] == {
#     "venus_rem": -1.23,      # VenusREM prediction
#     "s3f_msa": 0.20,         # S3F_MSA prediction
#     "esm2_15b": -4.04,       # ESM2_15B prediction
#     "prosst_2048": -0.45,    # ProSST K=2048 prediction
#     "gemme": -2.10,          # GEMME prediction
#     "wt_aa": "A",            # wild-type amino acid
#     "mut_aa": "C",           # mutant amino acid
#     "delta_charge": 0.0,     # net charge change
#     "delta_volume": 19.9,    # side-chain volume change (Å³)
#     "delta_hydro": 0.7,      # hydrophobicity shift (Kyte-Doolittle)
#     "blosum62": 0,           # BLOSUM62 substitution score
# }

# Per-residue structure (solvent accessibility, burial class)
st = get_residue_structure(protein_id)
# st[10] == {"wt_aa": "A", "asa": 45.2, "rsa": 0.18, "burial_class": "buried"}

# Protein metadata (MSA depth, organism, selection type)
info = get_protein_info(protein_id)
# info == {"msa_depth": 1234, "taxon": "Bacteria", "selection_type": "Activity", ...}
```

---

## Model Predictions (`get_model_scores`)

**Signature:** `get_model_scores(protein_id, mutations)`

**Args:**
- `protein_id` (str): ProteinGym protein identifier
- `mutations` (list[str]): Mutation codes like `"A10C"`, `"A10C,A15G"`

**Returns:** `{mutant_code: {field: value}}`

### Model fields

| Key           | Type  | Source         | Avg ρ   | Score Range  | Signal                                          |
|---------------|-------|----------------|---------|--------------|-------------------------------------------------|
| `venus_rem`   | float | VenusREM       | 0.518   | ~-8 to +2    | Structure + MSA retrieval (SOTA single model)    |
| `s3f_msa`     | float | S3F_MSA        | 0.496   | ~-5 to +4    | Structure + MSA frequencies                      |
| `esm2_15b`    | float | ESM2_15B       | 0.453   | ~-30 to +6   | Pure sequence protein language model (15B params)|
| `prosst_2048` | float | ProSST K=2048  | 0.507   | ~-30 to -20  | Quantized structure tokens (discrete 3D encoding)|
| `gemme`       | float | GEMME          | 0.455   | ~-30 to +5   | Pure alignment-based evolutionary model          |

**Score semantics:** All models — higher score = more harmful mutation (with model-specific scaling).

**Important:** These are zero-shot predictions from other models, NOT ground truth labels. The database contains no DMS_score — label leakage is impossible.

---

## Physicochemical Features (in `get_model_scores`)

These are deterministic from the mutation code — no model or label data involved. Orthogonal signal to all 5 models.

| Key            | Type   | Description                                                        | Example          |
|----------------|--------|--------------------------------------------------------------------|------------------|
| `wt_aa`        | str    | Wild-type amino acid (single letter)                               | `"A"`            |
| `mut_aa`       | str    | Mutant amino acid (single letter)                                  | `"C"`            |
| `delta_charge` | float  | Net charge change: -2 to +2 (positive gain, negative loss)         | K→E = -2.0       |
| `delta_volume` | float  | Side-chain volume change in Å³ (positive = larger)                 | G→W = +166.1     |
| `delta_hydro`  | float  | Hydrophobicity shift (Kyte-Doolittle scale, positive = more hydrophobic) | A→D = -5.3 |
| `blosum62`     | int    | BLOSUM62 substitution score (positive = conservative, negative = radical) | A→A = 4, W→C = -2 |

**Usage notes:**
- `delta_charge`: Charge reversals (positive↔negative) disrupt electrostatic interactions
- `delta_volume`: Large volume changes at buried positions disrupt packing
- `delta_hydro`: Hydrophobic→hydrophilic shifts at buried positions destabilize folding
- `blosum62`: Rare/radical substitutions (low scores) at conserved positions are most harmful

---

## Residue Structure (`get_residue_structure`)

**Signature:** `get_residue_structure(protein_id)`

**Returns:** `{position (int): {field: value}}`

| Key            | Type  | Description                                                        |
|----------------|-------|--------------------------------------------------------------------|
| `wt_aa`        | str   | Wild-type amino acid at that position                              |
| `asa`          | float | Absolute solvent-accessible surface area (Å²)                     |
| `rsa`          | float | Relative solvent accessibility (0.0 = fully buried, 1.0 = surface) |
| `burial_class` | str   | One of: `"core"`, `"buried"`, `"intermediate"`, `"surface"`       |

**Usage notes:**
- Combine with physicochemical features: a `delta_charge` of -2 at a `burial_class="core"` position is far more disruptive than at `"surface"`
- RSA is continuous — use it for graded penalties rather than the discrete burial_class
- Not available for all proteins (some lack structure data) — check for empty dict

---

## Protein Info (`get_protein_info`)

**Signature:** `get_protein_info(protein_id)`

**Returns:** `{field: value}`

| Key               | Type   | Description                                            |
|-------------------|--------|--------------------------------------------------------|
| `msa_depth`       | int    | Number of sequences in the MSA alignment               |
| `taxon`           | str    | Organism taxon: "Bacteria", "Virus", "Eukaryote", etc. |
| `selection_type`  | str    | Assay type: "Activity", "Stability", "Binding", etc.  |
| `upstream_domain` | str    | Protein domain/family if available                     |
| `uniprot_ac`      | str    | UniProt accession code                                 |

**Usage notes:**
- `msa_depth` is the strongest predictor of model accuracy — shallow MSAs (<100 sequences) make all models less reliable
- `selection_type` determines what "harmful" means — Stability assays favor structure-aware corrections, Activity assays favor active-site sensitivity
- Use for per-protein adaptive weighting

---

## Coverage

All data is stored in SQLite (`proteingym_data.db`) with 2,465,767 mutation rows across 217 proteins.

| Feature        | Coverage |
|----------------|----------|
| venus_rem      | 100%     |
| s3f_msa        | 100%     |
| esm2_15b       | 100%     |
| prosst_2048    | 100%     |
| gemme          | 100%     |
| physicochemical| 100%     |
| residue_structure | ~85% (some proteins lack structural data) |
| protein_info   | 100%     |
