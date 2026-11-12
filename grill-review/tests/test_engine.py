import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import grill_review_engine as engine  # noqa: E402


def manifest(*, allow_round_one_clean=False):
    return {
        "schema": 1,
        "runId": "run-1",
        "lens": "diff",
        "surface": {
            "mode": "file-set",
            "fingerprint": "surface-sha",
            "allowRoundOneClean": allow_round_one_clean,
            "targets": ["target.md"],
            "references": ["oracle.md"],
            "globalIndex": [
                {"path": "target.md", "role": "target"},
                {"path": "oracle.md", "role": "authority"},
            ],
        },
        "units": [
            {
                "id": "U-001",
                "groupId": "G-001",
                "path": "target.md",
                "location": "# first",
                "contentRef": "target.md:L1-20",
                "bytes": 500,
            },
            {
                "id": "U-002",
                "groupId": "G-002",
                "path": "target.md",
                "location": "# second",
                "contentRef": "target.md:L21-40",
                "bytes": 600,
            },
        ],
        "groups": [
            {"id": "G-001", "unitIds": ["U-001"], "links": [], "weight": 5},
            {"id": "G-002", "unitIds": ["U-002"], "links": [], "weight": 6},
        ],
    }


def completed(packet, *, items=None, refs=None):
    return {
        "packetId": packet["packetId"],
        "assignmentComplete": True,
        "newItems": items or [],
        "challenges": [],
        "evidenceRefs": refs or [],
    }


def item(unit="U-001", fingerprint="missing retry bound", linked=None):
    return {
        "tag": "BUG",
        "unitId": unit,
        "file": "target.md",
        "location": "L8",
        "fingerprint": fingerprint,
        "problem": "The retry loop has no bound.",
        "fix": "State the maximum attempts.",
        "linkedGroupIds": linked or [],
    }


class InitialStateTests(unittest.TestCase):
    def test_rejects_groups_that_do_not_tile_units(self):
        bad = manifest()
        bad["groups"][1]["unitIds"] = ["U-001"]

        with self.assertRaisesRegex(ValueError, "tile every unit exactly once"):
            engine.initialise(bad)

    def test_rejects_target_reference_overlap(self):
        bad = manifest()
        bad["surface"]["references"] = ["target.md"]

        with self.assertRaisesRegex(ValueError, "targets and references overlap"):
            engine.initialise(bad)


class ReviewRoundTests(unittest.TestCase):
    def test_round_one_credits_coverage_but_not_clean_streak(self):
        state = engine.initialise(manifest())
        state, packets, _ = engine.prepare_review(state, 2)

        state, summary = engine.merge_review(
            state, [completed(packet) for packet in packets]
        )

        self.assertEqual(1, summary["round"])
        for group in state["groupState"].values():
            self.assertEqual(0, group["cleanStreak"])
            self.assertEqual({next(iter(group["coverage"])): 1}, group["coverage"])
            self.assertFalse(group["converged"])

    def test_clean_group_converges_on_normal_then_intensified_pass(self):
        state = engine.initialise(manifest())
        for expected_round in range(1, 4):
            state, packets, _ = engine.prepare_review(state, 2)
            if expected_round == 3:
                self.assertTrue(all(p["modes"] == {g: "intensified" for g in p["groupIds"]}
                                    for p in packets))
            state, _ = engine.merge_review(
                state, [completed(packet) for packet in packets]
            )

        self.assertTrue(all(g["converged"] for g in state["groupState"].values()))
        self.assertTrue(state["integration"]["required"])
        self.assertFalse(state["integration"]["clean"])

    def test_new_item_resets_only_its_owner_group(self):
        state = engine.initialise(manifest())
        state["round"] = 1
        for group in state["groupState"].values():
            group["coverage"] = {unit: 1 for unit in group["coverage"]}

        state, packets, _ = engine.prepare_review(state, 2)
        returns = []
        for packet in packets:
            items = [item()] if "G-001" in packet["groupIds"] else []
            returns.append(completed(packet, items=items))
        state, _ = engine.merge_review(state, returns)

        self.assertEqual(0, state["groupState"]["G-001"]["cleanStreak"])
        self.assertEqual(1, state["groupState"]["G-002"]["cleanStreak"])

    def test_linked_finding_reopens_every_implicated_group(self):
        state = engine.initialise(manifest(allow_round_one_clean=True))
        for group in state["groupState"].values():
            group.update({"cleanStreak": 2, "converged": True, "nextMode": "intensified"})
            group["coverage"] = {unit: 2 for unit in group["coverage"]}
        state["integration"]["clean"] = False

        state, packet, _ = engine.prepare_integration(state)
        result = completed(packet, items=[item(linked=["G-002"])])
        state, summary = engine.merge_integration(state, result)

        self.assertEqual(1, summary["netNew"])
        self.assertFalse(state["groupState"]["G-001"]["converged"])
        self.assertFalse(state["groupState"]["G-002"]["converged"])
        self.assertIn("G-002", state["groups"]["G-001"]["links"])

    def test_next_packet_has_local_fingerprints_and_raw_refs_only(self):
        state = engine.initialise(manifest())
        state, packets, first_metrics = engine.prepare_review(state, 2)
        returns = []
        evidence = [{"groupId": "G-001", "path": "oracle.md", "lines": "L4-12",
                     "hash": "blob-1"}]
        for packet in packets:
            items = [item()] if "G-001" in packet["groupIds"] else []
            refs = evidence if "G-001" in packet["groupIds"] else []
            returns.append(completed(packet, items=items, refs=refs))
        state, _ = engine.merge_review(state, returns)

        state, next_packets, metrics = engine.prepare_review(state, 2)
        by_group = {group: packet for packet in next_packets for group in packet["groupIds"]}

        self.assertEqual(["L-001"], [x["id"] for x in by_group["G-001"]["known"]])
        self.assertNotIn("problem", by_group["G-001"]["known"][0])
        self.assertEqual([], by_group["G-002"]["known"])
        self.assertEqual(evidence, by_group["G-001"]["evidenceRefs"])
        self.assertEqual(2, metrics["legacyKnownRows"])
        self.assertEqual(1, metrics["actualKnownRows"])
        self.assertEqual(first_metrics["legacySurfaceBytes"] + metrics["legacySurfaceBytes"],
                         state["metrics"]["legacySurfaceBytes"])
        self.assertEqual(first_metrics["actualKnownRows"] + metrics["actualKnownRows"],
                         state["metrics"]["actualKnownRows"])


class ValidationTests(unittest.TestCase):
    def state_ready_for_validation(self):
        state = engine.initialise(manifest())
        state["ledger"] = [
            {"id": "L-001", "groupId": "G-001", "unitId": "U-001",
             "file": "target.md", "location": "L8", "fingerprint": "one",
             "status": "active", "payload": item(fingerprint="one"), "challenges": []},
            {"id": "L-002", "groupId": "G-002", "unitId": "U-002",
             "file": "target.md", "location": "L28", "fingerprint": "two",
             "status": "active", "payload": item("U-002", "two"), "challenges": []},
        ]
        state["nextLedgerId"] = 3
        for group in state["groupState"].values():
            group["converged"] = True
        state["integration"]["clean"] = True
        return state

    def test_validation_groups_must_tile_active_ledger(self):
        state = self.state_ready_for_validation()
        groups = [{"id": "V-001", "itemIds": ["L-001"], "weight": 1}]

        with self.assertRaisesRegex(ValueError, "tile every active ledger item"):
            engine.prepare_validation(state, groups, 1)

    def test_validation_packets_include_only_owner_group_raw_evidence(self):
        state = self.state_ready_for_validation()
        evidence = {group_id: [{"groupId": group_id, "path": "oracle.md",
                                "lines": "L1-4", "hash": f"hash-{group_id}"}]
                    for group_id in ("G-001", "G-002")}
        for group_id, refs in evidence.items():
            state["groupState"][group_id]["evidenceRefs"] = refs
        groups = [
            {"id": "V-001", "itemIds": ["L-001"], "weight": 1},
            {"id": "V-002", "itemIds": ["L-002"], "weight": 1},
        ]

        _, packets, _ = engine.prepare_validation(state, groups, 2)
        by_item = {item_id: packet for packet in packets
                   for item_id in packet["itemIds"]}

        self.assertEqual(evidence["G-001"], by_item["L-001"]["evidenceRefs"])
        self.assertEqual(evidence["G-002"], by_item["L-002"]["evidenceRefs"])

    def test_validation_requires_exactly_one_decision_per_item(self):
        state = self.state_ready_for_validation()
        groups = [
            {"id": "V-001", "itemIds": ["L-001"], "weight": 1},
            {"id": "V-002", "itemIds": ["L-002"], "weight": 1},
        ]
        state, packets, _ = engine.prepare_validation(state, groups, 2)
        results = [
            {"packetId": packet["packetId"], "decisions": []} for packet in packets
        ]

        with self.assertRaisesRegex(ValueError, "exactly the assigned ids"):
            engine.merge_validation(state, results)

        complete = []
        for packet in packets:
            complete.append({
                "packetId": packet["packetId"],
                "decisions": [
                    {"ref": item_id, "decision": "confirm", "reason": "evidence"}
                    for item_id in packet["itemIds"]
                ],
            })
        state, summary = engine.merge_validation(state, complete)
        self.assertEqual(2, summary["confirmed"])
        self.assertTrue(state["validation"]["complete"])


if __name__ == "__main__":
    unittest.main()
