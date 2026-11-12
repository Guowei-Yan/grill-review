"""Return contracts shared by reviewer preflight and merge barriers."""

from copy import deepcopy
import hashlib
from pathlib import Path


DISCOVERY_FIELDS = {
    "packetId", "failed", "assignmentComplete", "omittedUnitIds", "examinedUnitIds",
    "newItems", "challenges", "evidenceRefs",
}
FINDING_FIELDS = {
    "tag", "unitId", "file", "location", "fingerprint", "linkedGroupIds", "relatedTo",
}
LENSES = {
    "diff": ({"BUG", "QUALITY"}, {"problem", "fix"}),
    "yagni": ({"delete", "stdlib", "native", "yagni", "shrink"},
              {"cut", "replacement", "linesSaved"}),
}


def _error(path, message):
    raise ValueError(f"{path}: {message}")


def _object(value, path, allowed):
    if not isinstance(value, dict):
        _error(path, "must be an object")
    unknown = set(value) - allowed
    if unknown:
        _error(path, f"{', '.join(sorted(unknown))}: unknown field(s)")


def _text(value, key, path):
    if key not in value:
        _error(f"{path}.{key}", "required")
    if not isinstance(value[key], str) or not value[key].strip():
        _error(f"{path}.{key}", "must be a non-empty string")


def _array(value, key, path):
    rows = value.get(key, [])
    if not isinstance(rows, list):
        _error(f"{path}.{key}", "must be an array")
    return rows


def _ids(value, key, path):
    rows = _array(value, key, path)
    if any(not isinstance(row, str) or not row.strip() for row in rows):
        _error(f"{path}.{key}", "must contain non-empty string ids")
    if len(rows) != len(set(rows)):
        _error(f"{path}.{key}", "must not contain duplicate ids")
    return rows


def _finding(row, path, lens):
    tags, fields = LENSES[lens]
    _object(row, path, FINDING_FIELDS | fields)
    for key in ("tag", "unitId", "file", "location", "fingerprint"):
        _text(row, key, path)
    if row["tag"] not in tags:
        _error(f"{path}.tag", f"must be one of {', '.join(sorted(tags))}")
    for key in sorted(fields - {"linesSaved"}):
        _text(row, key, path)
    if lens == "yagni":
        if type(row.get("linesSaved")) is not int or row["linesSaved"] < 0:
            _error(f"{path}.linesSaved", "must be a non-negative integer")
    _ids(row, "linkedGroupIds", path)
    if "relatedTo" in row:
        _text(row, "relatedTo", path)


def _evidence(row, path, assignment):
    fields = {"groupId", "path", "lines", "hash"}
    _object(row, path, fields)
    for key in ("groupId", "path", "lines", "hash"):
        _text(row, key, path)
    allowed = assignment["groupIds"]
    if row["groupId"] not in allowed:
        _error(f"{path}.groupId", "evidence must belong to an assigned cohesion group; "
               f"allowed: {', '.join(allowed)}")


def _decisions(result, path):
    if "decisions" not in result:
        _error(f"{path}.decisions", "required")
    for index, row in enumerate(_array(result, "decisions", path)):
        row_path = f"{path}.decisions[{index}]"
        _object(row, row_path, {"ref", "decision", "reason"})
        for key in ("ref", "decision", "reason"):
            _text(row, key, row_path)
        if row["decision"] not in ("confirm", "drop"):
            _error(f"{row_path}.decision", "validator decision must be confirm or drop")


def _coverage(result, path, assignment):
    if type(result.get("assignmentComplete")) is not bool:
        _error(path, "assignmentComplete must be boolean")
    omitted = _ids(result, "omittedUnitIds", path)
    examined = _ids(result, "examinedUnitIds", path)
    if set(omitted) & set(examined):
        _error(path, "a unit cannot be both omitted and examined")
    if "unitIds" not in assignment and result["assignmentComplete"] and omitted:
        _error(path, "integration cannot be complete with omitted units; "
               "set assignmentComplete to false")


def validate_result(result, assignment, lens):
    """Check structure; ownership and coverage are also checked by the engine."""
    path = str(result.get("packetId", "return")) if isinstance(result, dict) else "return"
    validating = "itemIds" in assignment
    allowed = {"packetId", "failed", "decisions"} if validating else DISCOVERY_FIELDS
    _object(result, path, allowed)
    _text(result, "packetId", path)
    if "failed" in result and type(result["failed"]) is not bool:
        _error(f"{path}.failed", "must be boolean")
    if result.get("failed"):
        _object(result, path, {"packetId", "failed"})
        return
    if validating:
        _decisions(result, path)
        return
    _coverage(result, path, assignment)
    for index, row in enumerate(_array(result, "newItems", path)):
        _finding(row, f"{path}.newItems[{index}]", lens)
    for index, row in enumerate(_array(result, "challenges", path)):
        row_path = f"{path}.challenges[{index}]"
        _object(row, row_path, {"ref", "reason"})
        _text(row, "ref", row_path)
        _text(row, "reason", row_path)
    for index, row in enumerate(_array(result, "evidenceRefs", path)):
        _evidence(row, f"{path}.evidenceRefs[{index}]", assignment)


def select_packet(state, packet_id):
    pending = state.get("pending")
    if not pending or packet_id not in pending["packets"]:
        _error(str(packet_id), "does not name a pending packet")
    return pending["packets"][packet_id]


def return_template(state, packet_id):
    assignment = select_packet(state, packet_id)
    if "itemIds" in assignment:
        return {"packetId": packet_id, "decisions": []}
    return {"packetId": packet_id, "assignmentComplete": False,
            "omittedUnitIds": [], "examinedUnitIds": [],
            "newItems": [], "challenges": [], "evidenceRefs": []}


def check_return(state, result):
    """Dry-run the real merge with only this packet; never persist its state."""
    import grill_review_engine as engine

    if not isinstance(result, dict):
        _error("return", "must be an object")
    packet_id = result.get("packetId")
    if not isinstance(packet_id, str):
        _error("return.packetId", "must be a string")
    assignment = select_packet(state, packet_id)
    validate_result(result, assignment, state["lens"])
    scratch = deepcopy(state)
    scratch["pending"]["packets"] = {packet_id: assignment}
    kind = scratch["pending"]["kind"]
    if kind == "integration":
        engine.merge_integration(scratch, result)
    else:
        merge = {"review": engine.merge_review, "validation": engine.merge_validation}[kind]
        merge(scratch, [result])
    return {"packetId": packet_id, "valid": True, "failed": result.get("failed", False)}


def add_evidence(state, result, reference):
    """Hash the cited file and append evidence to a private return draft."""
    if state.get("pending", {}).get("kind") not in ("review", "integration"):
        _error("evidenceRefs", "only discovery packets can add evidence")
    if not isinstance(result, dict):
        _error("return", "must be an object")
    assignment = select_packet(state, result.get("packetId"))
    reference = dict(reference)
    reference["hash"] = hashlib.sha256(Path(reference["path"]).read_bytes()).hexdigest()
    _evidence(reference, f"{result['packetId']}.evidenceRefs[new]", assignment)
    result = deepcopy(result)
    result.setdefault("evidenceRefs", []).append(reference)
    check_return(state, result)
    return result


def add_finding(state, result, finding):
    """Build a diff finding without making the reviewer serialise JSON."""
    if state["lens"] != "diff":
        _error("add-finding", "requires the diff lens")
    if not isinstance(result, dict):
        _error("return", "must be an object")
    unit = state["units"].get(finding["unitId"])
    if unit is None:
        _error("newItems.unitId", "finding references an unknown unit")
    finding = dict(finding, file=unit["path"])
    result = deepcopy(result)
    result.setdefault("newItems", []).append(finding)
    check_return(state, result)
    return result
