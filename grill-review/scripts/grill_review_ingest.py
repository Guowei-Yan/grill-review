"""Finding, challenge, and raw-evidence ingestion for grill review barriers."""

from copy import deepcopy
import re

from grill_review_returns import validate_result


def _fail(message):
    raise ValueError(message)


def _normalise(value):
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _add_finding(state, packet, finding, existing):
    if (unit_id := finding.get("unitId")) not in state["units"]:
        _fail("finding references an unknown unit")
    unit = state["units"][unit_id]
    group_id = unit["groupId"]
    if group_id not in packet["groupIds"]:
        _fail("finding must belong to an assigned cohesion group")
    if finding.get("file") != unit["path"]:
        _fail("finding file must match its target unit file")
    key = (unit_id, _normalise(finding.get("fingerprint", "")))
    if not key[1]:
        _fail("finding fingerprint cannot be empty")
    if key in existing:
        return set(), False
    ledger_id = f"L-{state['nextLedgerId']:03d}"
    state["nextLedgerId"] += 1
    state["ledger"].append({
        "id": ledger_id, "groupId": group_id, "unitId": unit_id,
        "file": finding["file"], "location": finding["location"],
        "fingerprint": finding["fingerprint"], "status": "active",
        "payload": deepcopy(finding), "challenges": []})
    existing.add(key)
    affected = {group_id} | set(finding.get("linkedGroupIds", []))
    if not affected <= set(state["groups"]):
        _fail("finding links an unknown cohesion group")
    for linked in affected - {group_id}:
        for left, right in ((group_id, linked), (linked, group_id)):
            links = state["groups"][left].setdefault("links", [])
            if right not in links:
                links.append(right)
    return affected, True


def _add_challenges(state, packet, result):
    ledger = {item["id"]: item for item in state["ledger"]}
    for challenge in result.get("challenges", []):
        if challenge.get("ref") not in packet.get("knownIds", []):
            _fail("challenge must reference a known item in its packet")
        if challenge.get("ref") not in ledger:
            _fail("challenge references an unknown ledger id")
        ledger[challenge["ref"]]["challenges"].append({
            "packetId": result["packetId"], "reason": challenge["reason"]})


def _add_evidence(state, packet, result):
    for reference in result.get("evidenceRefs", []):
        group_id = reference.get("groupId")
        if group_id not in packet["groupIds"]:
            _fail("evidence must belong to an assigned cohesion group")
        raw = {key: reference[key] for key in ("groupId", "path", "lines", "hash")}
        refs = state["groupState"][group_id]["evidenceRefs"]
        if raw not in refs:
            refs.append(raw)


def ingest(state, results, pending):
    existing = {(item["unitId"], _normalise(item["fingerprint"]))
                for item in state["ledger"]}
    net_groups, net_count = set(), 0
    for result in results:
        packet = pending["packets"][result["packetId"]]
        validate_result(result, packet, state["lens"])
        if result.get("failed"):
            continue
        for finding in result.get("newItems", []):
            affected, added = _add_finding(state, packet, finding, existing)
            net_groups |= affected
            net_count += added
        _add_challenges(state, packet, result)
        _add_evidence(state, packet, result)
    return net_groups, net_count
