#!/usr/bin/env python3
"""Delta V data setup script.

Downloads (or locates) ProteinGym data and builds the SQLite database.

Two modes:
    --download   Download everything from scratch (~36 GB)
    --local DIR  Use existing ProteinGym data directory

The "local" mode is for users who already have the ProteinGym data package
(e.g. competition participants, benchmark maintainers). It expects a directory
containing:
    DMS_ProteinGym_substitutions/   (217 CSV files)
    DMS_msa_files/                  (217 .a2m files)
    DMS_substitutions.csv           (reference metadata)
    zero_shot_substitutions_scores/ or *_scores/  (217 merged score CSVs)

Usage:
    # Full download (will take a while — ~36 GB)
    python3 setup_data.py --download

    # From existing ProteinGym data directory
    python3 setup_data.py --local /path/to/proteingym_data

    # Skip MSA files (strategy degrades gracefully without them)
    python3 setup_data.py --local /path/to/proteingym_data --no-msa

    # Skip AlphaFold structure download (skip RSA features)
    python3 setup_data.py --local /path/to/proteingym_data --no-structures
"""

import argparse
import os
import sys
import subprocess
import shutil
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR) if "sef" in SCRIPT_DIR else SCRIPT_DIR
DATA_DIR = os.path.join(REPO_ROOT, "data")

# ProteinGym download URLs
PG_BASE = "https://marks.hms.harvard.edu/proteingym"
URL_DMS_DATA = f"{PG_BASE}/ProteinGym_DMS_substitutions.zip"
URL_REFERENCE = f"{PG_BASE}/DMS_substitutions.csv"
URL_MSA = f"{PG_BASE}/ProteinGym_DMS_MSA_files.zip"
URL_MODEL_SCORES = f"{PG_BASE}/zero_shot_substitutions_scores.zip"

MODEL_COLUMNS = ["VenusREM", "S3F_MSA", "ESM2_15B", "ProSST-2048", "GEMME"]


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def download(url, dest):
    """Download a URL to a file with progress."""
    log(f"Downloading: {url}")
    log(f"Destination: {dest}")
    try:
        result = subprocess.run(
            ["wget", "-q", "--show-progress", "-O", dest, url],
            check=True,
        )
        log(f"Done: {dest}")
        return True
    except subprocess.CalledProcessError:
        # Fallback to urllib if wget not available
        log("wget failed or not found, trying urllib...")
        import urllib.request
        try:
            urllib.request.urlretrieve(url, dest)
            log(f"Done: {dest}")
            return True
        except Exception as e:
            log(f"ERROR downloading {url}: {e}")
            return False


def unzip(zip_path, dest_dir):
    """Unzip a file to a directory."""
    log(f"Extracting {zip_path} → {dest_dir}")
    subprocess.run(["unzip", "-q", "-o", zip_path, "-d", dest_dir], check=True)
    os.remove(zip_path)
    log(f"Cleaned up {zip_path}")


def find_scores_dir(local_dir):
    """Find the merged model scores directory in a local ProteinGym install."""
    # Common locations/names
    candidates = [
        os.path.join(local_dir, "zero_shot_substitutions_scores"),
        os.path.join(local_dir, "zero_shot_substitutions_scores.zip"),
        os.path.join(local_dir, "proteingym_scores"),
        os.path.join(local_dir, "model_scores"),
        local_dir,  # scores might be in the root
    ]
    for c in candidates:
        if os.path.isdir(c):
            csvs = [f for f in os.listdir(c) if f.endswith('.csv')]
            if len(csvs) >= 200:  # should be ~217
                log(f"Found score files in: {c} ({len(csvs)} CSVs)")
                return c
    return None


def verify_csv_columns(scores_dir):
    """Check that the merged score CSVs have our 5 required model columns."""
    import csv
    sample = None
    for f in sorted(os.listdir(scores_dir)):
        if f.endswith('.csv'):
            sample = os.path.join(scores_dir, f)
            break
    if not sample:
        return False, "No CSV files found in scores directory"

    with open(sample) as f:
        reader = csv.reader(f)
        header = next(reader)

    missing = [col for col in MODEL_COLUMNS if col not in header]
    if missing:
        return False, f"Missing required model columns: {missing}. Found columns: {header[:10]}..."

    found = [col for col in MODEL_COLUMNS if col in header]
    log(f"Verified: all 5 model columns present ({', '.join(found)})")
    return True, "OK"


def build_db(scores_dir, reference_file, structures_db=None):
    """Run build_proteingym_db.py to create the SQLite database."""
    db_path = os.path.join(DATA_DIR, "proteingym_data.db")

    env = os.environ.copy()
    env["PROTEINGYM_SCORES_DIR"] = scores_dir
    env["PROTEINGYM_REFERENCE"] = reference_file
    env["PROTEINGYM_DB_OUTPUT"] = db_path
    if structures_db:
        env["PROTEINGYM_STRUCTURE_DB"] = structures_db

    builder = os.path.join(REPO_ROOT, "sef", "build_proteingym_db.py")
    if not os.path.exists(builder):
        builder = os.path.join(SCRIPT_DIR, "build_proteingym_db.py")

    log(f"Building database...")
    log(f"  Scores:    {scores_dir}")
    log(f"  Reference: {reference_file}")
    log(f"  Output:    {db_path}")
    if structures_db:
        log(f"  Structures: {structures_db}")
    else:
        log(f"  Structures: (none — residue_structure will be empty)")

    result = subprocess.run(
        [sys.executable, builder],
        env=env,
        cwd=REPO_ROOT,
    )

    if result.returncode != 0:
        log("ERROR: DB build failed!")
        return False

    # Verify
    if os.path.exists(db_path):
        size_mb = os.path.getsize(db_path) / (1024 * 1024)
        log(f"Database created: {db_path} ({size_mb:.0f} MB)")
        return True
    else:
        log("ERROR: Database file not created!")
        return False


def download_structures():
    """Run the structure download + ASA computation pipeline."""
    log("Downloading AlphaFold structures...")
    dl_script = os.path.join(REPO_ROOT, "sef", "download_structures.py")
    result = subprocess.run([sys.executable, dl_script], cwd=REPO_ROOT)
    if result.returncode != 0:
        log("WARNING: Structure download had issues (non-fatal)")
        return None

    log("Computing solvent accessibility...")
    asa_script = os.path.join(REPO_ROOT, "sef", "compute_asa.py")
    result = subprocess.run([sys.executable, asa_script], cwd=REPO_ROOT)
    if result.returncode != 0:
        log("WARNING: ASA computation had issues (non-fatal)")
        return None

    struct_db = os.path.join(DATA_DIR, "protein_structures.db")
    if os.path.exists(struct_db):
        log(f"Structure database ready: {struct_db}")
        return struct_db
    return None


def verify_database():
    """Verify the built database has expected content."""
    import sqlite3
    db_path = os.path.join(DATA_DIR, "proteingym_data.db")
    if not os.path.exists(db_path):
        log("ERROR: No database file found")
        return False

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    checks = []
    for table in ["protein_info", "model_scores", "residue_structure"]:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            checks.append((table, count))
        except sqlite3.OperationalError:
            checks.append((table, "MISSING"))

    conn.close()

    log("Database verification:")
    for table, count in checks:
        status = "✓" if (isinstance(count, int) and count > 0) else "✗"
        log(f"  {status} {table}: {count} rows")

    # Check model columns
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(model_scores)").fetchall()]
        model_cols = ["venus_rem", "s3f_msa", "esm2_15b", "prosst_2048", "gemme"]
        missing = [c for c in model_cols if c not in cols]
        if missing:
            log(f"  ✗ Missing model columns: {missing}")
        else:
            log(f"  ✓ All 5 model columns present")
    except:
        pass
    conn.close()

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Set up Delta V data (download + build database)"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--download", action="store_true",
                      help="Download all ProteinGym data from scratch (~36 GB)")
    mode.add_argument("--local", metavar="DIR",
                      help="Use existing ProteinGym data directory")

    parser.add_argument("--no-msa", action="store_true",
                        help="Skip MSA files (strategy degrades gracefully)")
    parser.add_argument("--no-structures", action="store_true",
                        help="Skip AlphaFold structure download (skip RSA features)")
    parser.add_argument("--output-dir", metavar="DIR", default=DATA_DIR,
                        help=f"Output data directory (default: {DATA_DIR})")

    args = parser.parse_args()
    global DATA_DIR
    DATA_DIR = args.output_dir
    os.makedirs(DATA_DIR, exist_ok=True)

    log("=" * 60)
    log("Delta V Data Setup")
    log("=" * 60)

    # ── Locate or download data ────────────────────────────────────────

    if args.download:
        # Full download mode
        log("MODE: Full download from ProteinGym")
        log("This will download ~36 GB. Estimated time: 20-60 minutes.")
        log("")

        # 1. DMS substitution data
        zip_path = os.path.join(DATA_DIR, "DMS_substitutions.zip")
        if not os.path.exists(os.path.join(DATA_DIR, "DMS_ProteinGym_substitutions")):
            if download(URL_DMS_DATA, zip_path):
                unzip(zip_path, DATA_DIR)
        else:
            log("DMS substitution data already present, skipping")

        # 2. Reference file
        ref_path = os.path.join(DATA_DIR, "DMS_substitutions.csv")
        if not os.path.exists(ref_path):
            download(URL_REFERENCE, ref_path)
        else:
            log("Reference file already present, skipping")

        # 3. Model scores
        scores_dir = os.path.join(DATA_DIR, "model_scores")
        if not os.path.isdir(scores_dir) or len(os.listdir(scores_dir)) < 200:
            zip_path = os.path.join(DATA_DIR, "model_scores.zip")
            if download(URL_MODEL_SCORES, zip_path):
                os.makedirs(scores_dir, exist_ok=True)
                unzip(zip_path, scores_dir)
        else:
            log("Model scores already present, skipping")

        # 4. MSA files (optional)
        if not args.no_msa:
            msa_dir = os.path.join(DATA_DIR, "DMS_msa_files")
            if not os.path.isdir(msa_dir) or len(os.listdir(msa_dir)) < 200:
                zip_path = os.path.join(DATA_DIR, "DMS_msa_files.zip")
                if download(URL_MSA, zip_path):
                    unzip(zip_path, DATA_DIR)
            else:
                log("MSA files already present, skipping")
        else:
            log("Skipping MSA files (--no-msa)")

        scores_dir_final = scores_dir

    else:
        # Local mode — locate data in existing directory
        log(f"MODE: Using existing ProteinGym data at {args.local}")
        local = args.local

        if not os.path.isdir(local):
            log(f"ERROR: Directory not found: {local}")
            sys.exit(1)

        # Find DMS substitution data
        dms_dir = os.path.join(local, "DMS_ProteinGym_substitutions")
        if not os.path.isdir(dms_dir):
            # Maybe the CSVs are directly in the root
            csvs = [f for f in os.listdir(local) if f.endswith('.csv') and 'DMS_substitutions' not in f]
            if len(csvs) >= 200:
                dms_dir = local
            else:
                log(f"ERROR: Cannot find DMS_ProteinGym_substitutions/ in {local}")
                sys.exit(1)

        # Find reference file
        ref_path = os.path.join(local, "DMS_substitutions.csv")
        if not os.path.exists(ref_path):
            log(f"ERROR: Cannot find DMS_substitutions.csv in {local}")
            sys.exit(1)

        # Find model scores
        scores_dir_final = find_scores_dir(local)
        if not scores_dir_final:
            log(f"ERROR: Cannot find merged model score CSVs in {local}")
            log("Expected a directory with 217 CSVs containing columns:")
            log(f"  {', '.join(MODEL_COLUMNS)}")
            sys.exit(1)

        # Symlink or copy data into our data directory
        log("Linking data files...")

        target_dms = os.path.join(DATA_DIR, "DMS_ProteinGym_substitutions")
        if not os.path.exists(target_dms):
            os.symlink(dms_dir, target_dms)
            log(f"  Linked: {target_dms} → {dms_dir}")

        target_ref = os.path.join(DATA_DIR, "DMS_substitutions.csv")
        if not os.path.exists(target_ref):
            os.symlink(ref_path, target_ref)
            log(f"  Linked: {target_ref} → {ref_path}")

        target_scores = os.path.join(DATA_DIR, "model_scores")
        if not os.path.exists(target_scores):
            os.symlink(scores_dir_final, target_scores)
            log(f"  Linked: {target_scores} → {scores_dir_final}")

        # MSA files
        if not args.no_msa:
            msa_dir = os.path.join(local, "DMS_msa_files")
            if os.path.isdir(msa_dir):
                target_msa = os.path.join(DATA_DIR, "DMS_msa_files")
                if not os.path.exists(target_msa):
                    os.symlink(msa_dir, target_msa)
                    log(f"  Linked: {target_msa} → {msa_dir}")
            else:
                log("WARNING: No DMS_msa_files/ found — MSA features will be disabled")
        else:
            log("Skipping MSA files (--no-msa)")

    # ── Verify data ────────────────────────────────────────────────────

    log("")
    log("Verifying data...")

    ref_path = os.path.join(DATA_DIR, "DMS_substitutions.csv")
    scores_dir_final = os.path.join(DATA_DIR, "model_scores")

    ok, msg = verify_csv_columns(scores_dir_final)
    if not ok:
        log(f"ERROR: Score verification failed: {msg}")
        log("")
        log("The merged score CSVs must contain these columns:")
        for col in MODEL_COLUMNS:
            log(f"  - {col}")
        log("")
        log("If you downloaded from ProteinGym, the zero_shot_substitutions_scores.zip")
        log("file contains these. Make sure you extracted them correctly.")
        sys.exit(1)

    # ── Download structures (optional) ─────────────────────────────────

    structures_db = None
    if not args.no_structures:
        struct_db_path = os.path.join(DATA_DIR, "protein_structures.db")
        if os.path.exists(struct_db_path):
            log(f"Structure database already exists: {struct_db_path}")
            structures_db = struct_db_path
        else:
            log("")
            log("Downloading AlphaFold structures (optional, ~20 min)...")
            log("Press Ctrl+C to skip and continue without structure data.")
            try:
                structures_db = download_structures()
            except KeyboardInterrupt:
                log("Skipped structure download")

    # ── Build database ─────────────────────────────────────────────────

    log("")
    log("Building SQLite database...")
    if not build_db(scores_dir_final, ref_path, structures_db):
        log("Database build failed!")
        sys.exit(1)

    # ── Final verification ─────────────────────────────────────────────

    log("")
    log("=" * 60)
    verify_database()
    log("=" * 60)
    log("")
    log("Data setup complete!")
    log("")
    log("Next steps:")
    log("  1. Run evaluation:  python3 eval/proteingym_eval.py --dir strategy/")
    log("  2. Run smoke test:  python3 eval/proteingym_smoke.py --workspace strategy/")
    log("")


if __name__ == "__main__":
    main()
