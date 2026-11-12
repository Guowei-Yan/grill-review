import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
CLI = ROOT / "scripts" / "grill-review.py"


def manifest():
    return {
        "schema": 1,
        "runId": "cli-run",
        "lens": "diff",
        "surface": {
            "mode": "file-set",
            "fingerprint": "abc",
            "allowRoundOneClean": False,
            "targets": ["target.md"],
            "references": ["oracle.md"],
            "globalIndex": [{"path": "oracle.md", "role": "authority"}],
        },
        "units": [
            {"id": "U-001", "groupId": "G-001", "path": "target.md",
             "location": "# one", "contentRef": "target.md:L1-9", "bytes": 90},
        ],
        "groups": [
            {"id": "G-001", "unitIds": ["U-001"], "links": [], "weight": 1},
        ],
    }


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        proc = subprocess.run(
            [sys.executable, str(CLI), *map(str, args)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        return json.loads(proc.stdout)

    def test_init_and_pack_write_compact_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "manifest.json"
            state_path = root / "state.json"
            packet_dir = root / "packets"
            manifest_path.write_text(json.dumps(manifest()))

            initial = self.run_cli(
                "init", "--manifest", manifest_path, "--state", state_path
            )
            packed = self.run_cli(
                "pack-review", "--state", state_path, "--slots", 1,
                "--out", packet_dir,
            )

            self.assertEqual("file-set", initial["surfaceMode"])
            self.assertEqual(1, packed["packets"])
            self.assertTrue((packet_dir / "R01-S01.json").is_file())
            self.assertTrue((packet_dir / "global-index.json").is_file())
            packet = json.loads((packet_dir / "R01-S01.json").read_text())
            self.assertEqual("global-index.json", packet["sharedContextRef"])
            self.assertNotIn("globalIndex", packet)
            state = json.loads(state_path.read_text())
            self.assertEqual("review", state["pending"]["kind"])

    def test_errors_are_short_and_nonzero(self):
        proc = subprocess.run(
            [sys.executable, str(CLI), "status", "--state", "/missing/state.json"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("error:", proc.stderr)
        self.assertLess(len(proc.stderr), 300)

    def test_malformed_state_errors_are_short_and_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            state.write_text("[]")
            proc = subprocess.run(
                [sys.executable, str(CLI), "status", "--state", str(state)],
                text=True, capture_output=True, check=False)

        self.assertNotEqual(0, proc.returncode)
        self.assertIn("error:", proc.stderr)
        self.assertLess(len(proc.stderr), 300)

    def test_manifest_template_exposes_both_surface_roles(self):
        template = self.run_cli(
            "manifest-template", "--mode", "file-set", "--lens", "diff"
        )

        self.assertEqual("file-set", template["surface"]["mode"])
        self.assertEqual([], template["surface"]["targets"])
        self.assertEqual([], template["surface"]["references"])
        self.assertFalse(template["surface"]["allowRoundOneClean"])
        self.assertEqual([], template["units"])
        self.assertEqual([], template["groups"])

    def test_full_single_group_lifecycle_persists_validation_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, state_path = root / "manifest.json", root / "state.json"
            manifest_path.write_text(json.dumps(manifest()))
            self.run_cli("init", "--manifest", manifest_path, "--state", state_path)
            for round_number in range(1, 4):
                packets, returns = root / f"pack-{round_number}", root / f"return-{round_number}"
                self.run_cli("pack-review", "--state", state_path, "--slots", 1,
                             "--out", packets)
                packet = json.loads(next(packets.glob("R*.json")).read_text())
                items = []
                if round_number == 1:
                    items = [{"tag": "BUG", "unitId": "U-001", "file": "target.md", "location": "L4",
                              "fingerprint": "missing bound", "problem": "No retry bound.",
                              "fix": "Add a limit.", "linkedGroupIds": []}]
                returns.mkdir()
                (returns / "result.json").write_text(json.dumps({
                    "packetId": packet["packetId"], "assignmentComplete": True,
                    "newItems": items, "challenges": [], "evidenceRefs": []}))
                self.run_cli("merge-review", "--state", state_path, "--results", returns)
            self.assertEqual(1, self.run_cli("status", "--state", state_path)["convergedGroups"])
            groups = root / "validation-groups.json"
            groups.write_text(json.dumps([{"id": "V-001", "itemIds": ["L-001"], "weight": 1}]))
            validation_packets, validation_returns = root / "validation", root / "validated"
            self.run_cli("pack-validation", "--state", state_path, "--groups", groups,
                         "--slots", 1, "--out", validation_packets)
            packet = json.loads(next(validation_packets.glob("V-*.json")).read_text())
            validation_returns.mkdir()
            (validation_returns / "result.json").write_text(json.dumps({
                "packetId": packet["packetId"], "decisions": [
                    {"ref": "L-001", "decision": "drop", "reason": "Not reproducible."}]}))
            summary = self.run_cli("merge-validation", "--state", state_path,
                                   "--results", validation_returns)
            self.assertEqual(1, summary["dropped"])
            self.assertTrue(self.run_cli("status", "--state", state_path)["validationComplete"])


if __name__ == "__main__":
    unittest.main()
