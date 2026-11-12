import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_engine_boundaries import completed, integration_ready, manifest
import grill_review_engine as engine


CLI = Path(__file__).parents[1] / "scripts" / "grill-review.py"


class ReturnTests(unittest.TestCase):
    def setUp(self):
        self.state, self.packets, _ = engine.prepare_review(
            engine.initialise(manifest()), 2)
        self.result = completed(self.packets[0])
        self.group = self.packets[0]["groupIds"][0]

    def merge(self, result):
        return engine.merge_review(self.state, [result, completed(self.packets[1])])

    def test_wrong_evidence_group_reports_packet_field_and_allowed_values(self):
        wrong = self.packets[1]["groupIds"][0]
        self.result["evidenceRefs"] = [{"groupId": wrong, "path": "service.ts",
                                        "lines": "L73-L83", "hash": "abc"}]
        with self.assertRaises(ValueError) as caught:
            self.merge(self.result)
        for text in (self.result["packetId"], "evidenceRefs[0].groupId", self.group):
            self.assertIn(text, str(caught.exception))

    def test_missing_evidence_hash_is_an_actionable_validation_error(self):
        self.result["evidenceRefs"] = [{"groupId": self.group,
                                        "path": "service.ts", "lines": "L73-L83"}]
        with self.assertRaisesRegex(ValueError, r"evidenceRefs\[0\].hash.*required"):
            self.merge(self.result)

    def test_misnamed_findings_are_never_silently_treated_as_clean(self):
        self.result["findings"] = [{"problem": "A defect"}]
        with self.assertRaisesRegex(ValueError, "findings.*unknown"):
            self.merge(self.result)

    def test_missing_finding_content_is_rejected_before_state_changes(self):
        unit = self.packets[0]["unitIds"][0]
        self.result["newItems"] = [{"unitId": unit, "file": "target.md",
                                    "location": "L4", "fingerprint": "missing bound"}]
        before = copy.deepcopy(self.state)
        with self.assertRaisesRegex(ValueError, r"newItems\[0\].tag.*required"):
            self.merge(self.result)
        self.assertEqual(before, self.state)

    def test_bad_evidence_shapes_have_field_specific_errors(self):
        for reference, field in ((None, "evidenceRefs[0]"),
                                 ({"groupId": self.group, "path": "service.ts",
                                   "lines": "L1", "hash": ""}, "hash")):
            with self.subTest(reference=reference):
                self.result["evidenceRefs"] = [reference]
                with self.assertRaises(ValueError) as caught:
                    self.merge(self.result)
                self.assertIn(field, str(caught.exception))

    def test_yagni_returns_keep_their_own_finding_fields(self):
        self.state["lens"] = "yagni"
        self.result["newItems"] = [{
            "tag": "shrink", "unitId": self.packets[0]["unitIds"][0],
            "file": "target.md", "location": "L4", "fingerprint": "repeated guard",
            "cut": "Repeated condition.", "replacement": "Keep the first guard.",
            "linesSaved": 3, "linkedGroupIds": []}]
        state, summary = self.merge(self.result)
        self.assertEqual(1, summary["netNew"])
        self.assertEqual("shrink", state["ledger"][0]["payload"]["tag"])

    def test_failure_record_receives_no_coverage(self):
        state, _ = self.merge({"packetId": self.result["packetId"], "failed": True})
        self.assertEqual(0, sum(state["groupState"][self.group]["coverage"].values()))

    def test_failed_flag_cannot_hide_content_or_use_truthy_strings(self):
        for failure in (True, "false"):
            with self.subTest(failure=failure):
                self.result["failed"] = failure
                with self.assertRaises(ValueError):
                    self.merge(self.result)

    def test_partial_return_only_credits_explicitly_examined_units(self):
        self.result["assignmentComplete"] = False
        self.result["examinedUnitIds"] = []
        state, _ = self.merge(self.result)
        self.assertEqual(0, sum(state["groupState"][self.group]["coverage"].values()))

    def test_unknown_nested_evidence_fields_are_rejected(self):
        self.result["evidenceRefs"] = [{"groupId": self.group, "path": "source.ts",
                                        "lines": "L1", "hash": "abc", "analysis": "opinion"}]
        with self.assertRaisesRegex(ValueError, "analysis.*unknown"):
            self.merge(self.result)

    def test_integration_omissions_cannot_be_certified_as_complete(self):
        state, packet, _ = engine.prepare_integration(integration_ready())
        result = completed(packet)
        result["omittedUnitIds"] = ["U-001"]
        with self.assertRaisesRegex(ValueError, "integration.*omitted"):
            engine.merge_integration(state, result)


class ReturnCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state, self.packets, _ = engine.prepare_review(
            engine.initialise(manifest()), 2)
        self.state_path = self.root / "state.json"
        self.result_path = self.root / "result.json"
        self.state_path.write_text(json.dumps(self.state))
        self.result_path.write_text(json.dumps(completed(self.packets[0])))

    def cli(self, *args, success=True):
        proc = subprocess.run([sys.executable, str(CLI), *map(str, args)],
                              text=True, capture_output=True, check=False)
        self.assertEqual(0 if success else 2, proc.returncode, proc.stderr)
        return proc

    def check(self, **kwargs):
        return self.cli("check-return", "--state", self.state_path,
                        "--result", self.result_path, **kwargs)

    def test_check_one_packet_does_not_require_other_returns_or_write_state(self):
        before = self.state_path.read_bytes()
        result_before = self.result_path.read_bytes()
        proc = self.check()
        self.assertTrue(json.loads(proc.stdout)["valid"])
        self.assertEqual(before, self.state_path.read_bytes())
        self.assertEqual(result_before, self.result_path.read_bytes())

    def test_check_rejects_malformed_json_with_short_error(self):
        self.result_path.write_text('```json\n{"packetId":')
        proc = self.check(success=False)
        self.assertIn("error:", proc.stderr)
        self.assertIn("Expecting value", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_duplicate_json_keys_cannot_silently_replace_findings(self):
        packet = self.packets[0]["packetId"]
        self.result_path.write_text('{"packetId": "' + packet + '", '
                                    '"assignmentComplete": true, '
                                    '"newItems": [{"problem": "hidden"}], "newItems": []}')
        proc = self.check(success=False)
        self.assertIn("duplicate JSON key: newItems", proc.stderr)

    def test_finding_writer_serialises_text_and_derives_target_file(self):
        problem, fix = self.root / "problem.txt", self.root / "fix.txt"
        problem.write_text('Quotes "inside" and\nnewlines with \\ paths.')
        fix.write_text("Add a retry bound.")
        self.cli("add-finding", "--state", self.state_path, "--result", self.result_path,
                 "--unit-id", self.packets[0]["unitIds"][0], "--tag", "BUG",
                 "--location", "L4", "--fingerprint", "missing bound",
                 "--problem-file", problem, "--fix-file", fix)
        finding = json.loads(self.result_path.read_text())["newItems"][0]
        self.assertEqual(problem.read_text(), finding["problem"])
        self.assertEqual("target.md", finding["file"])
        self.check()

    def test_failed_merge_preserves_state_and_reports_field_path(self):
        before = self.state_path.read_bytes()
        result = completed(self.packets[0])
        result["evidenceRefs"] = [{"groupId": self.packets[0]["groupIds"][0],
                                   "path": "service.ts", "lines": "L73-L83"}]
        returns = self.root / "returns"
        returns.mkdir()
        (returns / "first.json").write_text(json.dumps(result))
        (returns / "second.json").write_text(json.dumps(completed(self.packets[1])))
        proc = self.cli("merge-review", "--state", self.state_path,
                        "--results", returns, success=False)
        self.assertIn("evidenceRefs[0].hash", proc.stderr)
        self.assertEqual(before, self.state_path.read_bytes())

    def test_template_does_not_claim_review_was_completed(self):
        proc = self.cli("return-template", "--state", self.state_path,
                        "--packet-id", self.packets[0]["packetId"])
        result = json.loads(proc.stdout)
        self.assertFalse(result["assignmentComplete"])
        self.assertEqual([], result["examinedUnitIds"])
        self.assertEqual([], result["evidenceRefs"])

    def test_evidence_writer_hashes_raw_bytes_and_escapes_paths(self):
        evidence = self.root / 'source "quoted".ts'
        evidence.write_bytes(b"line one\r\nline two\n")
        before = self.state_path.read_bytes()
        self.cli("add-evidence", "--state", self.state_path,
                 "--result", self.result_path, "--group-id", self.packets[0]["groupIds"][0],
                 "--path", evidence, "--lines", "L1-L2")
        reference = json.loads(self.result_path.read_text())["evidenceRefs"][0]
        self.assertEqual(hashlib.sha256(evidence.read_bytes()).hexdigest(), reference["hash"])
        self.assertEqual(str(evidence), reference["path"])
        self.assertEqual(before, self.state_path.read_bytes())
        self.check()

    def test_evidence_writer_rejects_wrong_group_without_changing_return(self):
        evidence = self.root / "source.ts"
        evidence.write_text("contents\n")
        before = self.result_path.read_bytes()
        proc = self.cli("add-evidence", "--state", self.state_path,
                        "--result", self.result_path,
                        "--group-id", self.packets[1]["groupIds"][0],
                        "--path", evidence, "--lines", "L1", success=False)
        self.assertIn(self.packets[0]["groupIds"][0], proc.stderr)
        self.assertEqual(before, self.result_path.read_bytes())

    def test_evidence_writer_missing_file_does_not_change_return(self):
        before = self.result_path.read_bytes()
        self.cli("add-evidence", "--state", self.state_path,
                 "--result", self.result_path, "--group-id", self.packets[0]["groupIds"][0],
                 "--path", self.root / "missing.ts", "--lines", "L1", success=False)
        self.assertEqual(before, self.result_path.read_bytes())

    def test_check_integration_and_validation_use_their_own_contracts(self):
        state, packet, _ = engine.prepare_integration(integration_ready())
        self.state_path.write_text(json.dumps(state))
        self.result_path.write_text(json.dumps(completed(packet)))
        self.check()
        state["pending"] = {"kind": "validation", "packets": {
            "V-S01": {"itemIds": ["L-001"]}}}
        state["ledger"] = [{"id": "L-001", "status": "active"}]
        self.state_path.write_text(json.dumps(state))
        self.result_path.write_text(json.dumps({"packetId": "V-S01", "decisions": [
            {"ref": "L-001", "decision": "confirm", "reason": "Evidence confirms it."}]}))
        self.check()
        self.result_path.write_text(json.dumps({"packetId": "V-S01", "decisions": [
            {"ref": "L-001", "decision": "confirm"}]}))
        proc = self.check(success=False)
        self.assertIn("decisions[0].reason", proc.stderr)


if __name__ == "__main__":
    unittest.main()
