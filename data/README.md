# Data Setup

This directory holds the data files needed to reproduce the Delta V evaluation and (optionally) run the SEF evolution framework.

## Quick Start (Evaluation Only)

To run the final Delta V strategy on the ProteinGym benchmark, you need three data files:

### 1. DMS Substitution Assays (1 GB)

Download from ProteinGym:
```
https://marks.hms.harvard.edu/proteingym/ProteinGym_DMS_substitutions.zip
```

Unzip into:
```
data/DMS_ProteinGym_substitutions/
```

Expected: 217 CSV files, one per DMS assay.

### 2. Reference File

Download:
```
https://marks.hms.harvard.edu/proteingym/DMS_substitutions.csv
```

Place at:
```
data/DMS_substitutions.csv
```

### 3. Pre-computed Model Scores + Database

Download the merged model scores from ProteinGym:
```
https://marks.hms.harvard.edu/proteingym/zero_shot_substitutions_scores.zip
```

Unzip into:
```
data/model_scores/
```

Expected: 217 CSV files with ~100 model score columns including `VenusREM`, `S3F_MSA`, `ESM2_15B`, `ProSST-2048`, `GEMME`.

Build the database:
```bash
export PROTEINGYM_SCORES_DIR=./data/model_scores
export PROTEINGYM_REFERENCE=./data/DMS_substitutions.csv
export PROTEINGYM_DB_OUTPUT=./data/proteingym_data.db
python3 sef/build_proteingym_db.py
```

This creates `data/proteingym_data.db` (~600 MB) with:
- `protein_info` — metadata for all 217 assays
- `model_scores` — predictions from 5 SOTA models + physicochemical features
- `residue_structure` — per-position solvent accessibility (requires structure pipeline)

### 4. MSA Files (Optional, 4.9 GB)

```
https://marks.hms.harvard.edu/proteingym/ProteinGym_DMS_MSA_files.zip
```

Unzip into:
```
data/DMS_msa_files/
```

## Structure Data (Optional)

```bash
python3 sef/download_structures.py
python3 sef/compute_asa.py
```

Requires internet access to the AlphaFold database.

## Verification

```bash
python3 -c "
import sqlite3
db = sqlite3.connect('data/proteingym_data.db')
print('protein_info:', db.execute('SELECT COUNT(*) FROM protein_info').fetchone()[0], 'proteins')
print('model_scores:', db.execute('SELECT COUNT(*) FROM model_scores').fetchone()[0], 'mutations')
"
```

Expected: 217 proteins, ~150,000+ mutations.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PROTEINGYM_DATA` | `data/DMS_ProteinGym_substitutions` | DMS assay CSVs |
| `PROTEINGYM_REFERENCE` | `data/DMS_substitutions.csv` | Reference metadata |
| `PROTEINGYM_MSA` | `data/DMS_msa_files` | MSA alignment files |
| `PROTEINGYM_DB` | `data/proteingym_data.db` | SQLite database |
| `PROTEINGYM_SCORES_DIR` | `data/model_scores` | Merged model score CSVs |
