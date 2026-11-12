import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import grill_review_engine as engine  # noqa: E402


def manifest():
    return {
        "schema": 1,
        "runId": "boundary-run",
        "lens": "diff",
        "surface": {
            "mode": "file-set",
            "fingerprint": "surface-hash",
            "allowRoundOneClean": False,
            "targets": ["target.md"],
            "references": ["oracle.md"],
            "globalIndex": [{"path": "oracle.md", "role": "authority"}],
        },
        "units": [
            {"id": "U-001", "groupId": "G-001", "path": "target.md",
             "location": "# one", "contentRef": "target.md:L1-9", "bytes": 90},
            {"id": "U-002", "groupId": "G-002", "path": "target.md",
             "location": "# two", "contentRef": "target.md:L10-20", "bytes": 110},
        ],
        "groups": [
            {"id": "G-001", "unitIds": ["U-001"], "links": [], "weight": 1},
            {"id": "G-002", "unitIds": ["U-002"], "links": [], "weight": 1},
        ],
    }


def integration_ready():
    state = engine.initialise(manifest())
    for group in state["groupState"].values():
        group["converged"] = True
    return state


def completed(packet, *, items=None, challenges=None):
    return {
        "packetId": packet["packetId"],
        "assignmentComplete": True,
        "newItems": items or [],
        "challenges": challenges or [],
        "evidenceRefs": [],
    }


def finding(unit_id, file="target.md"):
    return {
        "tag": "BUG",
        "unitId": unit_id,
        "file": file,
        "location": "L4",
        "fingerprint": "missing bound",
        "problem": "The retry has no bound.",
        "fix": "Add a maximum attempt count.",
        "linkedGroupIds": [],
    }


class ManifestBoundaryTests(unittest.TestCase):
    def test_every_review_unit_must_belong_to_a_target_file(self):
        data = manifest()
        data["units"][0]["path"] = "oracle.md"

        with self.assertRaisesRegex(ValueError, "units must belong to target files"):
            engine.initialise(data)

    def test_manifest_accepts_only_supported_modes_and_lenses(self):
        for field, value, message in (
                ("lens", "style", "unsupported review lens"),
                ("mode", "whole-repo", "unsupported surface mode")):
            with self.subTest(field=field):
                data = manifest()
                if field == "lens":
                    data[field] = value
                else:
                    data["surface"][field] = value
                with self.assertRaisesRegex(ValueError, message):
                    engine.initialise(data)


class ReviewBoundaryTests(unittest.TestCase):
    def test_packet_cannot_report_a_finding_for_an_unassigned_group(self):
        state, packets, _ = engine.prepare_review(engine.initialise(manifest()), 2)
        returns = []
        for packet in packets:
            items = [finding("U-002")] if "G-001" in packet["groupIds"] else []
            returns.append(completed(packet, items=items))

        with self.assertRaisesRegex(ValueError, "assigned cohesion group"):
            engine.merge_review(state, returns)

    def test_finding_location_must_be_on_its_target_unit_file(self):
        state, packets, _ = engine.prepare_review(engine.initialise(manifest()), 2)
        returns = []
        for packet in packets:
            items = [finding("U-001", "oracle.md")] if "G-001" in packet["groupIds"] else []
            returns.append(completed(packet, items=items))

        with self.assertRaisesRegex(ValueError, "target unit file"):
            engine.merge_review(state, returns)

    def test_discovery_can_challenge_only_a_known_item_in_its_packet(self):
        state = engine.initialise(manifest())
        state["ledger"] = [{
            "id": "L-001", "groupId": "G-001", "unitId": "U-001",
            "file": "target.md", "location": "L4", "fingerprint": "old item",
            "status": "active", "payload": finding("U-001"), "challenges": [],
        }]
        state["nextLedgerId"] = 2
        state, packets, _ = engine.prepare_review(state, 2)
        returns = []
        for packet in packets:
            challenges = ([{"ref": "L-001", "reason": "unrelated evidence"}]
                          if "G-002" in packet["groupIds"] else [])
            returns.append(completed(packet, challenges=challenges))

        with self.assertRaisesRegex(ValueError, "known item in its packet"):
            engine.merge_review(state, returns)

    def test_coverage_claims_cannot_name_unassigned_units(self):
        state, packets, _ = engine.prepare_review(engine.initialise(manifest()), 2)
        returns = []
        for packet in packets:
            result = completed(packet)
            if "G-001" in packet["groupIds"]:
                result["omittedUnitIds"] = ["U-002"]
            returns.append(result)

        with self.assertRaisesRegex(ValueError, "coverage ids must be assigned"):
            engine.merge_review(state, returns)

    def test_assignment_complete_must_be_a_boolean(self):
        state, packets, _ = engine.prepare_review(engine.initialise(manifest()), 2)
        returns = [completed(packet) for packet in packets]
        returns[0]["assignmentComplete"] = "true"

        with self.assertRaisesRegex(ValueError, "assignmentComplete must be boolean"):
            engine.merge_review(state, returns)


class IntegrationBoundaryTests(unittest.TestCase):
    def test_failed_integration_sweep_never_counts_as_clean(self):
        state, packet, _ = engine.prepare_integration(integration_ready())

        state, summary = engine.merge_integration(
            state, {"packetId": packet["packetId"], "failed": True}
        )

        self.assertFalse(summary["integrationClean"])
        self.assertFalse(state["integration"]["clean"])

    def test_partial_integration_sweep_never_counts_as_clean(self):
        state, packet, _ = engine.prepare_integration(integration_ready())

        state, _ = engine.merge_integration(
            state, {"packetId": packet["packetId"], "assignmentComplete": False}
        )

        self.assertFalse(state["integration"]["clean"])

    def test_integration_assignment_complete_must_be_a_boolean(self):
        state, packet, _ = engine.prepare_integration(integration_ready())

        with self.assertRaisesRegex(ValueError, "assignmentComplete must be boolean"):
            engine.merge_integration(state, {
                "packetId": packet["packetId"], "assignmentComplete": "true"})

    def test_integration_packet_reuses_raw_evidence_without_conclusions(self):
        state = integration_ready()
        evidence = []
        for group_id in ("G-001", "G-002"):
            reference = {"groupId": group_id, "path": "oracle.md",
                         "lines": "L1-4", "hash": f"hash-{group_id}"}
            state["groupState"][group_id]["evidenceRefs"] = [reference]
            evidence.append(reference)

        _, packet, _ = engine.prepare_integration(state)

        self.assertEqual(evidence, packet["evidenceRefs"])


if __name__ == "__main__":
    unittest.main()
