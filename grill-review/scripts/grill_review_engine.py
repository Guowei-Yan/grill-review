"""Deterministic state and packet engine shared by the grill review skills."""
from copy import deepcopy

from grill_review_ingest import ingest as _ingest


def _fail(message):
    raise ValueError(message)

def _pack(rows, slots):
    if not isinstance(slots, int) or slots < 1:
        _fail("slots must be a positive integer")
    bins = [{"rows": [], "weight": 0} for _ in range(min(slots, len(rows)))]
    for row in sorted(rows, key=lambda x: (-x.get("weight", 1), x["id"])):
        target = min(enumerate(bins), key=lambda x: (x[1]["weight"], x[0]))[1]
        target["rows"].append(row)
        target["weight"] += row.get("weight", 1)
    return bins


def _active(state):
    return [item for item in state["ledger"] if item["status"] == "active"]

def _known(item):
    return {key: item[key] for key in
            ("id", "groupId", "unitId", "file", "location", "fingerprint")}


def _ensure_idle(state):
    if state.get("pending"):
        _fail("a barrier is already pending")

def _tile(actual, expected, message):
    if len(actual) != len(set(actual)) or sorted(actual) != sorted(expected):
        _fail(message)


def _manifest_surface(data):
    if data.get("schema") != 1:
        _fail("unsupported manifest schema")
    if data.get("lens") not in ("diff", "yagni"):
        _fail("unsupported review lens")
    surface = data.get("surface", {})
    if surface.get("mode") not in ("git-diff", "file-set"):
        _fail("unsupported surface mode")
    targets = surface.get("targets", [])
    references = surface.get("references", [])
    if set(targets) & set(references):
        _fail("targets and references overlap")
    return targets, references


def initialise(manifest):
    """Validate a semantic manifest and return JSON-serialisable run state."""
    data = deepcopy(manifest)
    targets, _ = _manifest_surface(data)
    units, groups = data.get("units", []), data.get("groups", [])
    unit_ids, group_ids = ([row.get("id") for row in units],
                           [row.get("id") for row in groups])
    if any(unit.get("path") not in targets for unit in units):
        _fail("units must belong to target files")
    if None in unit_ids or len(unit_ids) != len(set(unit_ids)):
        _fail("unit ids must be unique")
    if None in group_ids or len(group_ids) != len(set(group_ids)):
        _fail("group ids must be unique")
    tiled = [unit for group in groups for unit in group.get("unitIds", [])]
    _tile(tiled, unit_ids, "groups must tile every unit exactly once")
    unit_map = {row["id"]: row for row in units}
    group_map = {row["id"]: row for row in groups}
    for group in groups:
        for unit_id in group["unitIds"]:
            if unit_map[unit_id].get("groupId") != group["id"]:
                _fail("unit groupId disagrees with group membership")
        unknown = set(group.get("links", [])) - set(group_ids)
        if unknown:
            _fail("group links contain unknown ids")
    group_state = {}
    for group in groups:
        group_state[group["id"]] = {
            "coverage": {unit: 0 for unit in group["unitIds"]},
            "cleanStreak": 0, "nextMode": "normal", "converged": False,
            "evidenceRefs": []}
    integration_required = len(groups) > 1
    return {
        "schema": 1,
        "runId": data["runId"],
        "lens": data["lens"],
        "surface": data["surface"],
        "units": unit_map,
        "groups": group_map,
        "groupState": group_state,
        "round": 0,
        "ledger": [],
        "nextLedgerId": 1,
        "metrics": {"packets": 0, "legacySurfaceBytes": 0,
                    "actualSurfaceBytes": 0, "legacyKnownRows": 0,
                    "actualKnownRows": 0},
        "pending": None,
        "integration": {"required": integration_required,
                        "clean": not integration_required, "attempts": 0},
        "validation": {"complete": False, "decisions": {}},
    }


def _review_packet(state, number, groups, round_index):
    group_ids = [row["id"] for row in groups]
    unit_ids = [unit for row in groups for unit in row["unitIds"]]
    known = [_known(item) for item in _active(state) if item["groupId"] in group_ids]
    evidence = []
    for group_id in group_ids:
        evidence.extend(state["groupState"][group_id]["evidenceRefs"])
    return {
        "packetId": f"R{round_index:02d}-S{number:02d}",
        "kind": "review",
        "round": round_index,
        "surfaceMode": state["surface"]["mode"],
        "sharedContextRef": "global-index.json",
        "groupIds": group_ids,
        "unitIds": unit_ids,
        "modes": {group: state["groupState"][group]["nextMode"]
                  for group in group_ids},
        "groups": [{**row, "units": [state["units"][unit]
                                      for unit in row["unitIds"]]} for row in groups],
        "known": known,
        "evidenceRefs": evidence,
    }


def prepare_review(state, slots):
    """Schedule unconverged cohesion groups and create compact local packets."""
    state = deepcopy(state)
    _ensure_idle(state)
    active_groups = [state["groups"][group] for group, progress
                     in state["groupState"].items() if not progress["converged"]]
    if not active_groups:
        _fail("all cohesion groups are already converged")
    round_index = state["round"] + 1
    bins = _pack(active_groups, slots)
    packets = [_review_packet(state, index + 1, row["rows"], round_index)
               for index, row in enumerate(bins)]
    state["pending"] = {
        "kind": "review",
        "round": round_index,
        "packets": {packet["packetId"]: {
            "groupIds": packet["groupIds"], "unitIds": packet["unitIds"],
            "modes": packet["modes"],
            "knownIds": [item["id"] for item in packet["known"]]}
            for packet in packets},
    }
    active_bytes = sum(state["units"][unit]["bytes"] for packet in packets
                       for unit in packet["unitIds"])
    known_rows = sum(len(packet["known"]) for packet in packets)
    metrics = {
        "packets": len(packets),
        "legacySurfaceBytes": active_bytes * len(packets),
        "actualSurfaceBytes": active_bytes,
        "legacyKnownRows": len(_active(state)) * len(packets),
        "actualKnownRows": known_rows,
    }
    totals = state.setdefault("metrics", {key: 0 for key in metrics})
    for key, value in metrics.items():
        totals[key] += value
    return state, packets, metrics


def _validate_results(results, pending):
    expected = set(pending["packets"])
    actual = [result.get("packetId") for result in results]
    _tile(actual, expected, "results must contain exactly one return per packet")


def merge_review(state, results):
    """Merge one barrier and update coverage/convergence per cohesion group."""
    state = deepcopy(state)
    pending = state.get("pending")
    if not pending or pending["kind"] != "review":
        _fail("no review barrier is pending")
    _validate_results(results, pending)
    net_groups, net_count = _ingest(state, results, pending)
    by_packet = {result["packetId"]: result for result in results}
    for packet_id, assignment in pending["packets"].items():
        result = by_packet[packet_id]
        if result.get("failed"):
            continue
        if not isinstance(result.get("assignmentComplete"), bool):
            _fail("assignmentComplete must be boolean")
        omitted = set(result.get("omittedUnitIds", []))
        examined = set(result.get("examinedUnitIds", []))
        if not (omitted | examined) <= set(assignment["unitIds"]):
            _fail("coverage ids must be assigned to the packet")
        for group_id in assignment["groupIds"]:
            units = set(state["groups"][group_id]["unitIds"])
            credited = (units - omitted if result["assignmentComplete"]
                        else units & examined)
            progress = state["groupState"][group_id]
            for unit_id in credited:
                progress["coverage"][unit_id] += 1
            if group_id in net_groups:
                progress.update({"cleanStreak": 0, "nextMode": "normal",
                                 "converged": False})
            elif credited != units:
                continue
            elif pending["round"] == 1 and not state["surface"].get("allowRoundOneClean", False):
                progress["nextMode"] = "normal"
            else:
                progress["cleanStreak"] += 1
                mode = assignment["modes"][group_id]
                covered = all(value >= 2 for value in progress["coverage"].values())
                progress["converged"] = (progress["cleanStreak"] >= 2
                                          and mode == "intensified" and covered)
                progress["nextMode"] = "intensified"
    for group_id in net_groups:
        state["groupState"][group_id].update(
            {"cleanStreak": 0, "nextMode": "normal", "converged": False})
    if net_groups and state["integration"]["required"]:
        state["integration"]["clean"] = False
    state["round"] = pending["round"]
    state["pending"] = None
    converged = sum(row["converged"] for row in state["groupState"].values())
    return state, {"round": state["round"], "netNew": net_count,
                   "converged": converged, "groups": len(state["groups"])}


def prepare_integration(state):
    """Create the mandatory cross-group integration packet."""
    state = deepcopy(state)
    _ensure_idle(state)
    if not all(row["converged"] for row in state["groupState"].values()):
        _fail("cohesion groups must converge before integration")
    if not state["integration"]["required"] or state["integration"]["clean"]:
        _fail("integration sweep is not required")
    attempt = state["integration"]["attempts"] + 1
    packet = {
        "packetId": f"I{attempt:02d}", "kind": "integration",
        "sharedContextRef": "global-index.json",
        "groupIds": sorted(state["groups"]),
        "groups": [state["groups"][key] for key in sorted(state["groups"])],
        "known": [_known(item) for item in _active(state)],
        "evidenceRefs": [ref for key in sorted(state["groups"])
                         for ref in state["groupState"][key]["evidenceRefs"]],
    }
    state["pending"] = {"kind": "integration", "packets": {
        packet["packetId"]: {
            "groupIds": packet["groupIds"],
            "knownIds": [item["id"] for item in packet["known"]]}}}
    return state, packet, {"knownRows": len(packet["known"])}


def merge_integration(state, result):
    state = deepcopy(state)
    pending = state.get("pending")
    if not pending or pending["kind"] != "integration":
        _fail("no integration barrier is pending")
    _validate_results([result], pending)
    if not result.get("failed") and not isinstance(result.get("assignmentComplete"), bool):
        _fail("assignmentComplete must be boolean")
    net_groups, net_count = _ingest(state, [result], pending)
    for group_id in net_groups:
        state["groupState"][group_id].update(
            {"cleanStreak": 0, "nextMode": "normal", "converged": False})
    state["integration"]["attempts"] += 1
    completed = not result.get("failed") and result["assignmentComplete"]
    state["integration"]["clean"] = completed and not net_groups
    state["pending"] = None
    return state, {"netNew": net_count,
                   "integrationClean": state["integration"]["clean"]}


from grill_review_validation import merge_validation, prepare_validation  # noqa: E402,F401
