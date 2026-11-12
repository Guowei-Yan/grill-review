import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
HELPERS = (
    "grill-review.py",
    "grill_review_engine.py",
    "grill_review_ingest.py",
    "grill_review_validation.py",
    "grill_review_returns.py",
)
PRIMARY_ROOTS = (".claude", ".codex", ".cursor")
OPTIONAL_ROOTS = (
    ".agents",
    ".config/opencode",
    ".config/muse",
    ".gemini/config",
    ".pi/agent",
    ".zcode",
    ".kimicode",
)


class SyncTests(unittest.TestCase):
    def run_sync(self, skill, home):
        env = os.environ.copy()
        env["HOME"] = str(home)
        proc = subprocess.run(
            ["bash", str(ROOT / skill / f"sync-{skill}.sh")],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)

    def assert_install(self, home, root, skill):
        installed = home / root / "skills" / skill
        self.assertEqual(
            (ROOT / skill / "SKILL.md").read_bytes(),
            (installed / "SKILL.md").read_bytes(),
        )
        for helper in HELPERS:
            self.assertEqual(
                (ROOT / "grill-review" / "scripts" / helper).read_bytes(),
                (installed / "scripts" / helper).read_bytes(),
            )

    def test_sync_only_creates_primary_roots_on_clean_home(self):
        for skill in ("grill-diff", "grill-yagni"):
            with self.subTest(skill=skill), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                self.run_sync(skill, home)
                for root in PRIMARY_ROOTS:
                    self.assert_install(home, root, skill)
                for root in OPTIONAL_ROOTS:
                    self.assertFalse((home / root).exists())

    def test_each_sync_installs_skill_and_helper_across_existing_roots(self):
        for skill in ("grill-diff", "grill-yagni"):
            with self.subTest(skill=skill), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                for opt in OPTIONAL_ROOTS:
                    (home / opt).mkdir(parents=True)
                (home / "project" / ".agents" / "skills").mkdir(parents=True)
                (home / "Library" / "proj" / ".agents" / "skills").mkdir(parents=True)
                (home / "project" / "node_modules" / "pkg" / ".agents" / "skills").mkdir(parents=True)
                cache = home / ".codex" / ".tmp" / "plugins" / ".agents" / "skills"
                cache.mkdir(parents=True)
                self.run_sync(skill, home)
                for root in (*PRIMARY_ROOTS, *OPTIONAL_ROOTS, "project/.agents"):
                    self.assert_install(home, root, skill)
                self.assertFalse((cache / skill).exists())
                self.assertFalse((home / "Library" / "proj" / ".agents" / "skills" / skill).exists())
                self.assertFalse(
                    (home / "project" / "node_modules" / "pkg" / ".agents" / "skills" / skill).exists()
                )
                cursor_rule = home / ".cursor" / "rules" / f"{skill}.mdc"
                self.assertTrue(cursor_rule.is_file())
                for helper in HELPERS:
                    shared = home / ".local" / "share" / "grill-review" / helper
                    self.assertEqual(
                        (ROOT / "grill-review" / "scripts" / helper).read_bytes(),
                        shared.read_bytes(),
                    )


if __name__ == "__main__":
    unittest.main()
