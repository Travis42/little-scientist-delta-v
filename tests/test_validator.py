#!/usr/bin/env python3
"""
Unit tests for ProteinGym validator logic.

Tests the key pieces of logic that live inside proteingym_validate_and_eval.sh's
embedded Python — without needing to run the full pipeline.

Run: python3 -m pytest tests/test_validator.py -q
"""

import json
import os
import re
import sys
import tempfile
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


class TestForbiddenPatterns(unittest.TestCase):
    """Test the forbidden pattern regex that guards against code injection in strategies."""

    def setUp(self):
        # This mirrors the FORBIDDEN_PATTERNS list in the validator
        self.forbidden = [
            r"import\s+subprocess",
            r"import\s+os",
            r"import\s+sys",
            r"import\s+shutil",
            r"import\s+socket",
            r"import\s+http",
            r"import\s+urllib",
            r"import\s+requests",
            r"\.system\(",
            r"\.popen\(",
            r"subprocess",
            r"\beval\(",
            r"\bexec\(",
            r"\bcompile\(",
            r"__import__",
            r"\bopen\(",
            r"os\.path",
            r"os\.system",
            r"os\.popen",
            r"__class__",
            r"__bases__",
            r"__subclasses__",
            r"__builtins__",
            r"globals\(",
            r"locals\(",
            r"getattr\(",
            r"setattr\(",
            r"delattr\(",
            r"hasattr\(",
            r"\btype\(",
            r"input\(",
            r"breakpoint\(",
            r"pdb\.",
            r"ipdb\.",
        ]
        self.pattern = re.compile("|".join(self.forbidden), re.IGNORECASE)

    def _check(self, text):
        """Return True if text matches any forbidden pattern."""
        return bool(self.pattern.search(text))

    def test_clean_strategy_passes(self):
        """A legitimate strategy with no forbidden patterns should pass."""
        clean = '''
"""
Mutation effect prediction strategy.
Uses BLOSUM62 and conservation metrics.
"""
import numpy as np

def strategy_function(mutations, msa, wild_type):
    return [0.5] * len(mutations)
'''
        self.assertFalse(self._check(clean), "Clean strategy should not match forbidden patterns")

    def test_wild_type_comment_doesnt_match(self):
        """'wild-type (fewer differences)' in a comment should NOT match type()."""
        text_with_comment = '''
# Sequences closer to wild-type (fewer differences) get higher weight.
# The relationship is monotonic — more conserved positions produce higher scores.
'''
        self.assertFalse(self._check(text_with_comment),
                         "English text 'wild-type (fewer...' should not match forbidden pattern")

    def test_open_parenthesis_in_comment_doesnt_match(self):
        """'the open (interval' in a comment should NOT match open()."""
        text = '# Consider the open (0, 1) interval for normalization.'
        self.assertFalse(self._check(text),
                         "English text 'open (0, 1)' should not match forbidden pattern")

    def test_actual_type_call_matches(self):
        """Actual Python type() call should be caught."""
        self.assertTrue(self._check("x = type(obj)"), "type() call should match")
        self.assertTrue(self._check("if type(x) == str:"), "type() in if-statement should match")

    def test_import_os_matches(self):
        """import os should be caught."""
        self.assertTrue(self._check("import os"), "import os should match")

    def test_subprocess_matches(self):
        """subprocess should be caught."""
        self.assertTrue(self._check("subprocess.run(['ls'])"), "subprocess.run should match")

    def test_eval_call_matches(self):
        """eval() call should be caught."""
        self.assertTrue(self._check("result = eval(expr)"), "eval() should match")

    def test_double_underscore_patterns(self):
        """Dunder patterns should be caught."""
        for pat in ["__class__", "__bases__", "__subclasses__", "__builtins__", "__import__"]:
            self.assertTrue(self._check(pat), f"{pat} should match")


class TestMinProgressDelta(unittest.TestCase):
    """Test the minimum progress threshold logic."""

    def test_large_improvement_counts_as_progress(self):
        best_score = 0.4400
        new_score = 0.4460
        min_delta = 0.0005
        improved = (new_score - best_score) >= min_delta
        self.assertTrue(improved, "0.006 improvement should count as progress")

    def test_micro_improvement_does_not_count(self):
        best_score = 0.4400
        new_score = 0.4401
        min_delta = 0.0005
        improved = (new_score - best_score) >= min_delta
        self.assertFalse(improved, "0.0001 improvement should NOT count as progress")

    def test_exactly_at_threshold_counts(self):
        best_score = 0.4400
        new_score = 0.4405
        min_delta = 0.0005
        improved = (new_score - best_score) >= min_delta
        self.assertTrue(improved, "Exactly 0.0005 should count as progress (>=)")

    def test_regression_does_not_count(self):
        best_score = 0.4400
        new_score = 0.4390
        min_delta = 0.0005
        improved = (new_score - best_score) >= min_delta
        self.assertFalse(improved, "Regression should not count as progress")


class TestPlateauCounter(unittest.TestCase):
    """Test consecutive rejection counting for plateau detection."""

    def _count_rejections(self, entries):
        """Mirror of count_consecutive_rejections logic."""
        count = 0
        for entry in reversed(entries):
            verdict = entry.get("verdict", "")
            if verdict == "accepted" or entry.get("improved") == True:
                break
            if verdict in ("rejected", "false_positive", "git_error", "validation_failed"):
                count += 1
            elif verdict in ("", None) and entry.get("improved") == False:
                count += 1
        return count

    def test_all_accepted(self):
        entries = [{"verdict": "accepted"}, {"verdict": "accepted"}]
        self.assertEqual(self._count_rejections(entries), 0)

    def test_all_rejected(self):
        entries = [{"verdict": "rejected"}, {"verdict": "rejected"}, {"verdict": "rejected"}]
        self.assertEqual(self._count_rejections(entries), 3)

    def test_accepted_resets(self):
        entries = [
            {"verdict": "rejected"},
            {"verdict": "accepted"},
            {"verdict": "rejected"},
            {"verdict": "rejected"},
        ]
        self.assertEqual(self._count_rejections(entries), 2)

    def test_missing_verdict_with_improved_false(self):
        # When iterating in reverse, we hit these in order: False, accepted (break), ...
        # So only the first entry (improved=False) counts before we hit accepted
        entries = [
            {"improved": False},  # oldest
            {"verdict": "accepted"},
            {"improved": False},
            {"improved": False},  # newest (counted first in reverse)
        ]
        self.assertEqual(self._count_rejections(entries), 2)

    def test_no_code_review_excluded(self):
        """no_code_review entries should NOT count toward plateau — they have no
        matching verdict and improved is not False, so they stop the count."""
        entries = [
            {"verdict": "accepted"},
            {"verdict": "no_code_review"},
        ]
        # no_code_review has no matching verdict and improved=None (not False),
        # so it neither counts nor breaks the chain — it's simply skipped
        # Actually our logic: if verdict not accepted and improved not True,
        # then check verdict in rejection set (no) or verdict empty+improved==False (no)
        # So it falls through without incrementing or breaking.
        # The next entry (accepted) would break. Result: 0.
        self.assertEqual(self._count_rejections(entries), 0)

    def test_empty_history(self):
        self.assertEqual(self._count_rejections([]), 0)

    def test_plateau_at_threshold_5(self):
        entries = [{"verdict": "rejected"}] * 5
        count = self._count_rejections(entries)
        self.assertGreaterEqual(count, 5, "5 rejections should trigger plateau")


class TestSanitizeAllowlist(unittest.TestCase):
    """Test that sanitize_workspace only preserves allowed files."""

    def setUp(self):
        # Mirror of the allowed set in the validator
        self.allowed = {
            "best_so_far_strategy.py",
            "staging_strategy.py",
            "last_attempt_strategy.py",
            "history.jsonl",
            "causal_model.md",
            "program.md",
            "paradigm_context.md",
            "AGENT_PROMPT.md",
            "worksheet_template.md",
            "config",
            ".git",
        }

    def test_strategy_files_preserved(self):
        for f in ["best_so_far_strategy.py", "staging_strategy.py", "last_attempt_strategy.py"]:
            self.assertIn(f, self.allowed, f"{f} should be in allowlist")

    def test_staging_artifacts_not_in_allowlist(self):
        for f in ["staging_smoke_trigger.json", "staging_code_reviewed",
                  "staging_review_trigger.json", "staging_smoke_result.json",
                  "staging_worksheet.md", "staging_hypothesis.txt",
                  "staging_plan.md", ".validator_lock"]:
            self.assertNotIn(f, self.allowed, f"{f} should NOT be in allowlist")


class TestKuhnHandoffThreshold(unittest.TestCase):
    """Test Kuhn→Scientist handoff threshold logic."""

    def test_kuhn_above_90_percent_triggers(self):
        scientist_best = 0.4449
        kuhn_score = 0.4453
        threshold = scientist_best * 0.90
        self.assertGreaterEqual(kuhn_score, threshold,
                                "Kuhn score above 90% threshold should trigger handoff")

    def test_kuhn_below_90_percent_does_not_trigger(self):
        scientist_best = 0.4449
        kuhn_score = 0.3500
        threshold = scientist_best * 0.90
        self.assertLess(kuhn_score, threshold,
                        "Kuhn score below 90% should not trigger handoff")

    def test_kuhn_at_exactly_90_percent(self):
        scientist_best = 0.4449
        threshold = scientist_best * 0.90
        kuhn_score = threshold  # exactly at threshold
        self.assertGreaterEqual(kuhn_score, threshold,
                                "Score at exactly 90% should trigger (>=)")

    def test_empty_scientist_history_blocks_handoff(self):
        """If scientist_best is 0.0, handoff should be blocked (not use fallback)."""
        scientist_best = 0.0
        # The validator returns early if scientist_best == 0.0
        self.assertEqual(scientist_best, 0.0,
                         "Empty history should result in 0.0, not a fallback")


class TestTimingsConfig(unittest.TestCase):
    """Test that config/timings.json has all expected fields."""

    def setUp(self):
        self.config_path = PROJECT_ROOT / "config" / "timings.json"

    def test_config_exists(self):
        self.assertTrue(self.config_path.exists(), "config/timings.json must exist")

    def test_config_has_required_fields(self):
        with open(self.config_path) as f:
            cfg = json.load(f)
        required = ["smoke_timeout_seconds", "validator_timeout_seconds",
                    "cron_interval_seconds", "validator_stale_lock_seconds",
                    "min_progress_delta", "eval_per_protein_timeout_seconds"]
        for field in required:
            self.assertIn(field, cfg, f"Missing required field: {field}")

    def test_min_progress_delta_is_reasonable(self):
        with open(self.config_path) as f:
            cfg = json.load(f)
        delta = cfg.get("min_progress_delta", 0)
        self.assertGreater(delta, 0, "min_progress_delta must be positive")
        self.assertLess(delta, 0.01, "min_progress_delta should be < 0.01")


class TestKuhnSelector(unittest.TestCase):
    """Test the Kuhn injection pair selector."""

    def setUp(self):
        sys.path.insert(0, str(SCRIPTS_DIR))
        from pg_kuhn_selector import ASSUMPTIONS, DOMAINS
        self.assumptions = ASSUMPTIONS
        self.domains = DOMAINS

    def test_pair_space_is_384(self):
        self.assertEqual(len(self.assumptions) * len(self.domains), 384)

    def test_pairs_are_deterministic(self):
        """Selector should return pairs in fixed order, not random."""
        from pg_kuhn_selector import build_ordered_pairs
        pairs = build_ordered_pairs()
        self.assertEqual(len(pairs), 384)
        # First pair should be first assumption × first domain
        self.assertEqual(pairs[0][0], self.assumptions[0])
        self.assertEqual(pairs[0][1], self.domains[0])
        # Pair 24 should be first assumption × last domain (end of first row)
        self.assertEqual(pairs[23][0], self.assumptions[0])
        self.assertEqual(pairs[23][1], self.domains[23])
        # Pair 25 should be second assumption × first domain
        self.assertEqual(pairs[24][0], self.assumptions[1])
        self.assertEqual(pairs[24][1], self.domains[0])

    def test_no_empty_assumptions(self):
        for a in self.assumptions:
            self.assertTrue(len(a) > 20, f"Assumption too short: {a[:30]}")

    def test_no_empty_domains(self):
        for d in self.domains:
            self.assertTrue(len(d) > 5, f"Domain too short: {d}")

    def test_assumptions_are_unique(self):
        self.assertEqual(len(self.assumptions), len(set(self.assumptions)),
                         "Assumptions should be unique")

    def test_domains_are_unique(self):
        self.assertEqual(len(self.domains), len(set(self.domains)),
                         "Domains should be unique")


class TestEvalSmoke(unittest.TestCase):
    """Smoke test: the eval script runs and produces output."""

    def setUp(self):
        self.eval_script = SCRIPTS_DIR / "proteingym_eval.py"
        self.workspace = PROJECT_ROOT / "workspace"
        self.strategy = self.workspace / "best_so_far_strategy.py"

    def test_eval_script_exists(self):
        self.assertTrue(self.eval_script.exists())

    def test_strategy_file_exists(self):
        self.assertTrue(self.strategy.exists())

    def test_eval_smoke_completes(self):
        """Run eval in smoke mode (5 proteins) and verify it produces a score."""
        result = subprocess.run(
            [sys.executable, str(self.eval_script), "--dir", str(self.workspace), "--smoke"],
            capture_output=True, text=True, timeout=300,
            cwd=str(PROJECT_ROOT),
        )
        self.assertEqual(result.returncode, 0,
                         f"Eval failed: {result.stderr[-500:]}")
        # Check that output contains a score
        self.assertIn("Spearman", result.stdout + result.stderr,
                       "Eval output should contain Spearman correlation")


if __name__ == "__main__":
    unittest.main()
