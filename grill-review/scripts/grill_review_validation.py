"""Validation-stage mechanics for the shared grill review engine."""

from copy import deepcopy

from grill_review_returns import validate_result

from grill_review_engine import (
    _active,
    _ensure_idle,
    _fail,
    _pack,
    _tile,
    _validate_results,
)


def _relevant_evidence(state, active, item_ids):
    group_ids = {active[item_id]["groupId"] for item_id in item_ids}
    for item_id in item_ids:
        group_ids.update(active[item_id].get("payload", {}).get("linkedGroupIds", []))
    evidence = []
    for group_id in sorted(group_ids):
        for reference in state["groupState"][group_id].get("evidenceRefs", []):
            if reference not in evidence:
                evidence.append(deepcopy(reference))
    return evidence


def prepare_validation(state, groups, slots):
    """Pack validation cohesion groups; every active item has one owner."""
    state = deepcopy(state)
    _ensure_idle(state)
    if not all(row["converged"] for row in state["groupState"].values()):
        _fail("review groups have not converged")
    if not state["integration"]["clean"]:
        _fail("integration sweep has not converged")
    active = {item["id"]: item for item in _active(state)}
    tiled = [item for group in groups for item in group.get("itemIds", [])]
    _tile(tiled, active, "validation groups must tile every active ledger item")
    bins = _pack(groups, slots)
    packets = []
    for index, packed in enumerate(bins, 1):
        ids = [item for group in packed["rows"] for item in group["itemIds"]]
        packets.append({
            "packetId": f"V-S{index:02d}",
            "kind": "validation",
            "validationGroupIds": [group["id"] for group in packed["rows"]],
            "itemIds": ids,
            "items": [active[item] for item in ids],
            "evidenceRefs": _relevant_evidence(state, active, ids),
            "sharedContextRef": "global-index.json",
        })
    state["pending"] = {"kind": "validation", "packets": {
        packet["packetId"]: {"itemIds": packet["itemIds"]} for packet in packets}}
    state["validation"] = {"complete": False, "decisions": {}}
    return state, packets, {"packets": len(packets), "items": len(active)}


def merge_validation(state, results):
    state = deepcopy(state)
    pending = state.get("pending")
    if not pending or pending["kind"] != "validation":
        _fail("no validation barrier is pending")
    _validate_results(results, pending)
    ledger = {item["id"]: item for item in state["ledger"]}
    unvalidated = []
    for result in results:
        assignment = pending["packets"][result["packetId"]]
        validate_result(result, assignment, state["lens"])
        assigned = assignment["itemIds"]
        if result.get("failed"):
            unvalidated.extend(assigned)
            continue
        decisions = result.get("decisions", [])
        _tile([row.get("ref") for row in decisions], assigned,
              "validator decisions must cover exactly the assigned ids")
        for decision in decisions:
            if decision.get("decision") not in ("confirm", "drop"):
                _fail("validator decision must be confirm or drop")
            ledger[decision["ref"]]["status"] = (
                "confirmed" if decision["decision"] == "confirm" else "dropped")
            state["validation"]["decisions"][decision["ref"]] = deepcopy(decision)
    state["validation"]["complete"] = not unvalidated
    state["validation"]["unvalidated"] = sorted(unvalidated)
    state["pending"] = None
    return state, {
        "confirmed": sum(item["status"] == "confirmed" for item in state["ledger"]),
        "dropped": sum(item["status"] == "dropped" for item in state["ledger"]),
        "unvalidated": len(unvalidated),
    }
