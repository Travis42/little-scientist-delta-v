#!/usr/bin/env python3
"""
Tests for the proteingym_data library and proteingym_data.db integrity.

Run: python3 -m pytest tests/test_proteingym_data.py -q
"""

import os
import sqlite3
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
DATA_DIR = PROJECT_ROOT / "data"

sys.path.insert(0, str(SCRIPTS_DIR))

# Resolve the DB path the same way the library does.
_DB_PATH = os.environ.get(
    "PROTEINGYM_DB",
    str(DATA_DIR / "proteingym_data.db"),
)
DB_PRESENT = os.path.exists(_DB_PATH) and os.path.getsize(_DB_PATH) > 0

# A protein we know exists in the benchmark (used by the SPEC example).
KNOWN_PROTEIN = "ARGR_ECOLI_Tsuboyama_2023_1AOY"
EXPECTED_PROTEIN_COUNT = 217


@unittest.skipUnless(DB_PRESENT, "proteingym_data.db not built — run scripts/build_proteingym_db.py")
class TestDBIntegrity(unittest.TestCase):
    """Verify the DB schema and row counts match the SPEC."""

    def setUp(self):
        self.conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)

    def tearDown(self):
        self.conn.close()

    def test_protein_info_has_217_rows(self):
        n = self.conn.execute("SELECT COUNT(*) FROM protein_info").fetchone()[0]
        self.assertEqual(n, EXPECTED_PROTEIN_COUNT)

    def test_model_scores_has_rows(self):
        n = self.conn.execute("SELECT COUNT(*) FROM model_scores").fetchone()[0]
        self.assertGreater(n, 1_000_000, "model_scores should have ~2.5M rows")

    def test_model_scores_covers_all_proteins(self):
        n = self.conn.execute(
            "SELECT COUNT(DISTINCT protein_id) FROM model_scores"
        ).fetchone()[0]
        self.assertEqual(n, EXPECTED_PROTEIN_COUNT)

    def test_residue_structure_has_rows(self):
        n = self.conn.execute("SELECT COUNT(*) FROM residue_structure").fetchone()[0]
        self.assertGreater(n, 50000, "residue_structure should have ~90K rows")

    def test_model_scores_has_three_model_columns(self):
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(model_scores)").fetchall()]
        for expected in ("venus_rem", "s3f_msa", "esm2_15b"):
            self.assertIn(expected, cols)

    def test_no_label_columns_anywhere(self):
        """Label leakage is impossible by construction — verify it."""
        forbidden = ("DMS_score", "DMS_score_bin", "mutated_sequence")
        for table in ("protein_info", "model_scores", "residue_structure"):
            cols = [r[1] for r in self.conn.execute(f"PRAGMA table_info({table})").fetchall()]
            for bad in forbidden:
                self.assertNotIn(bad, cols, f"{table} must not contain {bad}")

    def test_model_scores_primary_key_unique(self):
        """(protein_id, mutant) must be unique."""
        dup = self.conn.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT protein_id, mutant, COUNT(*) c FROM model_scores "
            "  GROUP BY protein_id, mutant HAVING c > 1)"
        ).fetchone()[0]
        self.assertEqual(dup, 0)

    def test_indexes_exist(self):
        idx = [r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()]
        self.assertIn("idx_model_scores_protein", idx)
        self.assertIn("idx_model_scores_mutant", idx)
        self.assertIn("idx_residue_protein", idx)


@unittest.skipUnless(DB_PRESENT, "proteingym_data.db not built — run scripts/build_proteingym_db.py")
class TestReadOnlyConnection(unittest.TestCase):
    """Read-only URI connections must never allow writes."""

    def test_write_is_blocked(self):
        conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("CREATE TABLE should_fail (x INTEGER)")
        finally:
            conn.close()

    def test_insert_is_blocked(self):
        conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("INSERT INTO protein_info VALUES ('HACK','x')")
        finally:
            conn.close()


@unittest.skipUnless(DB_PRESENT, "proteingym_data.db not built — run scripts/build_proteingym_db.py")
class TestGetModelScores(unittest.TestCase):
    """get_model_scores returns the right shape and values."""

    def test_returns_all_mutations_for_protein(self):
        from proteingym_data import get_model_scores
        scores = get_model_scores(KNOWN_PROTEIN)
        self.assertGreater(len(scores), 0)
        for mutant, vals in scores.items():
            self.assertIn("venus_rem", vals)
            self.assertIn("s3f_msa", vals)
            self.assertIn("esm2_15b", vals)

    def test_returns_float_values(self):
        from proteingym_data import get_model_scores
        scores = get_model_scores(KNOWN_PROTEIN)
        mutant, vals = next(iter(scores.items()))
        for key in ("venus_rem", "s3f_msa", "esm2_15b"):
            self.assertIsInstance(
                vals[key], (int, float, type(None)),
                f"{key} should be numeric or None",
            )

    def test_filtered_lookup_matches_subset(self):
        from proteingym_data import get_model_scores
        all_scores = get_model_scores(KNOWN_PROTEIN)
        some = list(all_scores.keys())[:5]
        filtered = get_model_scores(KNOWN_PROTEIN, some)
        self.assertEqual(set(filtered.keys()), set(some))
        for m in some:
            self.assertEqual(filtered[m], all_scores[m])

    def test_missing_protein_returns_empty(self):
        from proteingym_data import get_model_scores
        self.assertEqual(get_model_scores("DOES_NOT_EXIST"), {})

    def test_missing_mutants_return_empty(self):
        from proteingym_data import get_model_scores
        self.assertEqual(
            get_model_scores(KNOWN_PROTEIN, ["ZZZ999"]),
            {},
        )


@unittest.skipUnless(DB_PRESENT, "proteingym_data.db not built — run scripts/build_proteingym_db.py")
class TestGetResidueStructure(unittest.TestCase):
    """get_residue_structure returns per-residue data."""

    def test_returns_residues_for_known_protein(self):
        from proteingym_data import get_residue_structure
        struct = get_residue_structure(KNOWN_PROTEIN)
        self.assertGreater(len(struct), 0)
        pos, data = next(iter(struct.items()))
        self.assertIn("wt_aa", data)
        self.assertIn("asa", data)
        self.assertIn("rsa", data)
        self.assertIn("burial_class", data)

    def test_burial_class_is_valid(self):
        from proteingym_data import get_residue_structure
        struct = get_residue_structure(KNOWN_PROTEIN)
        valid = {"buried", "core", "intermediate", "surface"}
        for data in struct.values():
            self.assertIn(data["burial_class"], valid)

    def test_missing_protein_returns_empty(self):
        from proteingym_data import get_residue_structure
        self.assertEqual(get_residue_structure("DOES_NOT_EXIST"), {})


@unittest.skipUnless(DB_PRESENT, "proteingym_data.db not built — run scripts/build_proteingym_db.py")
class TestGetProteinInfo(unittest.TestCase):
    """get_protein_info returns metadata dict."""

    def test_returns_known_fields(self):
        from proteingym_data import get_protein_info
        info = get_protein_info(KNOWN_PROTEIN)
        self.assertEqual(info.get("protein_id"), KNOWN_PROTEIN)
        for key in ("seq_len", "coarse_selection_type", "msa_num_seqs",
                    "has_structure", "source_organism"):
            self.assertIn(key, info)

    def test_seq_len_positive(self):
        from proteingym_data import get_protein_info
        info = get_protein_info(KNOWN_PROTEIN)
        self.assertGreater(info["seq_len"], 0)

    def test_missing_protein_returns_empty(self):
        from proteingym_data import get_protein_info
        self.assertEqual(get_protein_info("DOES_NOT_EXIST"), {})


@unittest.skipUnless(DB_PRESENT, "proteingym_data.db not built — run scripts/build_proteingym_db.py")
class TestEndToEndStrategyImport(unittest.TestCase):
    """Acceptance #8: a strategy that imports proteingym_data works end-to-end."""

    def test_strategy_can_import_and_score(self):
        """Simulate what a strategy does: import the library, score mutations."""
        # Strategy code that uses the library (would live in staging_strategy.py).
        strategy_src = (
            "import numpy as np\n"
            "from proteingym_data import get_model_scores, get_residue_structure\n"
            "\n"
            "def score_mutations(sequences, protein_id, wild_type, mutations, msa=None):\n"
            "    scores_lookup = get_model_scores(protein_id, mutations)\n"
            "    out = []\n"
            "    for mut in mutations:\n"
            "        ms = scores_lookup.get(mut, {})\n"
            "        v = ms.get('venus_rem')\n"
            "        out.append(float(v) if v is not None else 0.0)\n"
            "    return out\n"
        )
        ns = {}
        exec(compile(strategy_src, "<test_strategy>", "exec"), ns)
        score_fn = ns["score_mutations"]

        # Pull real mutations from the DB so we pass valid mutant strings.
        conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT mutant FROM model_scores WHERE protein_id=? LIMIT 20",
                [KNOWN_PROTEIN],
            ).fetchall()
        finally:
            conn.close()
        mutations = [r[0] for r in rows]

        result = score_fn(
            sequences={},
            protein_id=KNOWN_PROTEIN,
            wild_type="",
            mutations=mutations,
            msa=None,
        )
        self.assertEqual(len(result), len(mutations))
        self.assertTrue(all(isinstance(x, float) for x in result))


if __name__ == "__main__":
    unittest.main()
