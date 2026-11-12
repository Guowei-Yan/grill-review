#!/usr/bin/env python3
"""CLI for deterministic grill review state, packets, and barriers."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

import grill_review_engine as engine
import grill_review_returns as returns


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=unique_object)


def write_json(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=target.parent, delete=False) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = handle.name
    os.replace(temporary, target)


def emit(value):
    json.dump(value, sys.stdout, separators=(",", ":"), sort_keys=True)
    sys.stdout.write("\n")


def global_index(state):
    return {
        "runId": state["runId"],
        "lens": state["lens"],
        "surface": state["surface"],
        "groups": [state["groups"][key] for key in sorted(state["groups"])],
        "units": [state["units"][key] for key in sorted(state["units"])],
    }


def write_packets(state, packets, out_dir):
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    write_json(destination / "global-index.json", global_index(state))
    for packet in packets:
        write_json(destination / f"{packet['packetId']}.json", packet)


def read_results(directory):
    paths = sorted(Path(directory).glob("*.json"))
    if not paths:
        raise ValueError("results directory contains no JSON returns")
    return [load_json(path) for path in paths]


def command_init(args):
    state = engine.initialise(load_json(args.manifest))
    write_json(args.state, state)
    return {"runId": state["runId"], "surfaceMode": state["surface"]["mode"],
            "groups": len(state["groups"]), "units": len(state["units"])}


def command_pack_review(args):
    state, packets, metrics = engine.prepare_review(load_json(args.state), args.slots)
    write_packets(state, packets, args.out)
    write_json(args.state, state)
    return metrics


def command_merge_review(args):
    state, summary = engine.merge_review(load_json(args.state), read_results(args.results))
    write_json(args.state, state)
    return summary


def command_pack_integration(args):
    state, packet, metrics = engine.prepare_integration(load_json(args.state))
    write_packets(state, [packet], args.out)
    write_json(args.state, state)
    return metrics | {"packetId": packet["packetId"]}


def command_merge_integration(args):
    state, summary = engine.merge_integration(
        load_json(args.state), load_json(args.result))
    write_json(args.state, state)
    return summary


def command_pack_validation(args):
    groups = load_json(args.groups)
    if isinstance(groups, dict):
        groups = groups.get("groups", [])
    state, packets, metrics = engine.prepare_validation(
        load_json(args.state), groups, args.slots)
    write_packets(state, packets, args.out)
    write_json(args.state, state)
    return metrics


def command_merge_validation(args):
    state, summary = engine.merge_validation(
        load_json(args.state), read_results(args.results))
    write_json(args.state, state)
    return summary


def command_status(args):
    state = load_json(args.state)
    groups = state["groupState"].values()
    active = [item for item in state["ledger"] if item["status"] == "active"]
    coverage = [count for group in groups for count in group["coverage"].values()]
    return {
        "runId": state["runId"],
        "round": state["round"],
        "convergedGroups": sum(group["converged"] for group in groups),
        "groups": len(state["groups"]),
        "coveragePercent": round(100 * sum(min(value, 2) for value in coverage)
                                 / (2 * len(coverage)), 1) if coverage else 100.0,
        "activeLedger": len(active),
        "pending": state["pending"]["kind"] if state.get("pending") else None,
        "integrationClean": state["integration"]["clean"],
        "validationComplete": state["validation"]["complete"],
        "payloadEstimates": state.get("metrics", {}),
    }


def command_manifest_template(args):
    return {
        "schema": 1,
        "runId": "replace-me",
        "lens": args.lens,
        "surface": {
            "mode": args.mode,
            "fingerprint": "replace-with-content-hash",
            "allowRoundOneClean": False,
            "targets": [],
            "references": [],
            "globalIndex": [],
        },
        "units": [],
        "groups": [],
    }


def add_state(parser):
    parser.add_argument("--state", required=True)


def command_return_template(args):
    return returns.return_template(load_json(args.state), args.packet_id)


def command_check_return(args):
    return returns.check_return(load_json(args.state), load_json(args.result))


def command_add_evidence(args):
    result = returns.add_evidence(load_json(args.state), load_json(args.result), {
        "groupId": args.group_id, "path": args.path, "lines": args.lines})
    write_json(args.result, result)
    return {"packetId": result["packetId"], "evidenceRefs": len(result["evidenceRefs"])}


def command_add_finding(args):
    finding = {"tag": args.tag, "unitId": args.unit_id, "location": args.location,
               "fingerprint": args.fingerprint, "linkedGroupIds": args.linked_group_id,
               "problem": Path(args.problem_file).read_text(encoding="utf-8"),
               "fix": Path(args.fix_file).read_text(encoding="utf-8")}
    if args.related_to:
        finding["relatedTo"] = args.related_to
    result = returns.add_finding(load_json(args.state), load_json(args.result), finding)
    write_json(args.result, result)
    return {"packetId": result["packetId"], "newItems": len(result["newItems"])}


def add_finding_command(commands):
    finding = commands.add_parser("add-finding", help="Build a diff finding from text files")
    add_state(finding)
    for field in ("result", "unit-id", "location", "fingerprint", "problem-file", "fix-file"):
        finding.add_argument(f"--{field}", required=True)
    finding.add_argument("--tag", choices=("BUG", "QUALITY"), required=True)
    finding.add_argument("--linked-group-id", action="append", default=[])
    finding.add_argument("--related-to")
    finding.set_defaults(run=command_add_finding)


def add_return_commands(commands):
    add_finding_command(commands)
    template = commands.add_parser("return-template", help="Create an incomplete return draft")
    add_state(template)
    template.add_argument("--packet-id", required=True)
    template.set_defaults(run=command_return_template)

    check = commands.add_parser("check-return", help="Check one return without changing state")
    add_state(check)
    check.add_argument("--result", required=True)
    check.set_defaults(run=command_check_return)

    evidence = commands.add_parser("add-evidence", help="Hash a cited file and append its reference")
    add_state(evidence)
    evidence.add_argument("--result", required=True)
    evidence.add_argument("--group-id", required=True)
    evidence.add_argument("--path", required=True)
    evidence.add_argument("--lines", required=True)
    evidence.set_defaults(run=command_add_evidence)


def parser():
    root = argparse.ArgumentParser(description="Manage compact, deterministic grill review runs")
    commands = root.add_subparsers(dest="command", required=True)
    add_return_commands(commands)
    template = commands.add_parser("manifest-template")
    template.add_argument("--mode", choices=("git-diff", "file-set"), required=True)
    template.add_argument("--lens", choices=("diff", "yagni"), required=True)
    template.set_defaults(run=command_manifest_template)

    init = commands.add_parser("init")
    init.add_argument("--manifest", required=True)
    add_state(init)
    init.set_defaults(run=command_init)

    pack_review = commands.add_parser("pack-review")
    add_state(pack_review)
    pack_review.add_argument("--slots", type=int, required=True)
    pack_review.add_argument("--out", required=True)
    pack_review.set_defaults(run=command_pack_review)

    merge_review = commands.add_parser("merge-review")
    add_state(merge_review)
    merge_review.add_argument("--results", required=True)
    merge_review.set_defaults(run=command_merge_review)

    pack_integration = commands.add_parser("pack-integration")
    add_state(pack_integration)
    pack_integration.add_argument("--out", required=True)
    pack_integration.set_defaults(run=command_pack_integration)

    merge_integration = commands.add_parser("merge-integration")
    add_state(merge_integration)
    merge_integration.add_argument("--result", required=True)
    merge_integration.set_defaults(run=command_merge_integration)

    pack_validation = commands.add_parser("pack-validation")
    add_state(pack_validation)
    pack_validation.add_argument("--groups", required=True)
    pack_validation.add_argument("--slots", type=int, required=True)
    pack_validation.add_argument("--out", required=True)
    pack_validation.set_defaults(run=command_pack_validation)

    merge_validation = commands.add_parser("merge-validation")
    add_state(merge_validation)
    merge_validation.add_argument("--results", required=True)
    merge_validation.set_defaults(run=command_merge_validation)

    status = commands.add_parser("status")
    add_state(status)
    status.set_defaults(run=command_status)
    return root


def main():
    args = parser().parse_args()
    try:
        emit(args.run(args))
    except (OSError, ValueError, TypeError, AttributeError, KeyError,
            json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
