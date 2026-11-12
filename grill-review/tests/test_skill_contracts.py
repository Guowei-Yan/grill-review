import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]


class SkillContractTests(unittest.TestCase):
    def read(self, skill):
        return (ROOT / skill / "SKILL.md").read_text()

    def test_grill_diff_declares_whole_file_mode(self):
        text = self.read("grill-diff")
        self.assertIn("file-set mode", text)
        self.assertRegex(text, r"entire current contents")
        self.assertIn("omissions", text)
        self.assertIn("reference-only", text)

    def test_both_skills_use_helper_and_local_fingerprints(self):
        for skill in ("grill-diff", "grill-yagni"):
            with self.subTest(skill=skill):
                text = self.read(skill)
                self.assertIn("grill-review.py", text)
                self.assertIn("compact local fingerprints", text)
                self.assertNotIn("full global ledger", text)

    def test_discovery_does_not_readjudicate_known_items(self):
        for skill in ("grill-diff", "grill-yagni"):
            with self.subTest(skill=skill):
                text = self.read(skill)
                self.assertRegex(text, r"(?i)do not (re-)?validate known")
                self.assertRegex(text, r"(?i)validator.*confirm or drop")

    def test_helper_commands_use_a_resolved_install_path(self):
        for skill in ("grill-diff", "grill-yagni"):
            with self.subTest(skill=skill):
                text = self.read(skill)
                self.assertIn('HELPER=', text)
                self.assertIn('python3 "$HELPER"', text)
                self.assertNotIn("python3 scripts/grill-review.py", text)

    def test_quality_invariants_remain_explicit(self):
        required = (
            "Round 1",
            "two consecutive clean",
            "intensified",
            "examined ≥2×",
            "fresh",
            "integration sweep",
        )
        for skill in ("grill-diff", "grill-yagni"):
            text = self.read(skill)
            for phrase in required:
                with self.subTest(skill=skill, phrase=phrase):
                    self.assertIn(phrase, text)

    def test_frontmatter_has_only_name_and_description(self):
        for skill in ("grill-diff", "grill-yagni"):
            text = self.read(skill)
            frontmatter = text.split("---", 2)[1]
            keys = re.findall(r"^([a-z][a-z-]*):", frontmatter, re.MULTILINE)
            self.assertEqual(["name", "description"], keys)


if __name__ == "__main__":
    unittest.main()
