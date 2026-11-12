---
name: grill-diff
description: >-
  Use when an exhaustive repeated review is needed for a branch, PR, pasted diff, or explicitly listed
  files; when every changed hunk or whole target-file section must be checked, supporting behaviour or
  planning documents may define correctness, and false positives must be filtered before reporting.
---

# Grill Diff

Review only; never modify the reviewed targets or post comments. Keep reviewer judgement fresh while
reusing raw evidence and deterministic state. Run the bundled `scripts/grill-review.py` for manifests,
packet slicing, ledger IDs, deduplication, coverage, convergence and validation ownership. Do not
reimplement those mechanics in the orchestrator context.

## Guarantees

- Use a new subagent context for every review packet, integration sweep and validation packet.
- Review every in-scope unit; every unit must be examined ≥2×.
- Require two consecutive clean passes per cohesion group; the second must be intensified.
- Round 1 does not count as clean unless the whole in-scope surface is at most 10 lines.
- Keep progress on cohesion groups, never temporary slot partitions. A finding resets only its owning
  group and explicitly linked groups.
- Keep the repository or reference corpus available read-only. Cached evidence is navigation, never a
  restriction on fresh investigation.
- Let validators confirm or drop findings. Discovery rounds hunt for new issues; they do not re-validate
  known findings.

## Choose the review surface

### Git-diff mode

Use for a branch/PR, several branches completing one task, or a pasted diff. Findings must trace to an
added or modified line. Unchanged code, merge-target code and repository files are evidence only.

- Single branch: use the merge-base surface, `git diff <target>...HEAD`.
- Multi-branch: create one temporary worktree, merge branches in the user's order, and share it read-only.
  On conflict, do not resolve automatically; offer the weaker union-of-diffs fallback and explain it.
- Dirty computed scope: ask whether to include uncommitted changes; default to committed-only.
- Pasted diff: warn that repository evidence may be unavailable.

### file-set mode

Use when the user says to grill named file(s) only. The explicitly listed targets' **entire current contents**
are in scope, including omissions. Other supplied files are reference-only.

- For Markdown, make stable units from heading/section paths; split an oversized section without
  separating one behavioural obligation from its acceptance evidence.
- For other files, use stable symbol/region units. Every target line belongs to exactly one unit.
- Locate a present defect at its target line. Locate an omission at the target section where the missing
  material belongs.
- Classify supplied material as authority, context or historical obligation. A prior review backlog is
  an obligation source, not a runtime ledger. Resume a prior ledger only from its matching helper state;
  without that state, start a new run and keep the backlog reference-only.
- Never report an issue against a supporting file.

An empty target surface stops cleanly. Hash the complete review surface; if a target changes during the
run, invalidate affected units before continuing.

## Compile the manifest once

Put run artefacts outside the reviewed targets/worktree. Resolve the synced helper once; an agent host
may override its installed location with `GRILL_REVIEW_HELPER`:

```bash
HELPER="${GRILL_REVIEW_HELPER:-$HOME/.local/share/grill-review/grill-review.py}"
test -f "$HELPER"
python3 "$HELPER" manifest-template --mode <git-diff|file-set> --lens diff > manifest.json
```

Fill the template:

- `surface.targets` and `surface.references` are disjoint; `globalIndex` contains compact paths,
  headings/symbols, roles and hashes—not copied document bodies.
- Each unit has `id`, `groupId`, `path`, `location`, `contentRef` and `bytes`.
- Cohesion groups tile units exactly once. Keep same function/section, caller/callee, shared state/type,
  and target/obligation pairs together. Record known cross-group links.
- Set `allowRoundOneClean: true` only for a whole surface of at most 10 in-scope lines.

Initialise durable state before dispatch:

```bash
python3 "$HELPER" init --manifest manifest.json --state state.json
```

The helper rejects overlap, missing units and invalid group links. Preserve `state.json` at every barrier;
on a later invocation offer resume or restart.

## Blocking review gate

Before round 1, show surface mode, target/reference files, unit count, cohesion groups, estimated packet
bytes and a recommended slot count. Then stop and ask for:

1. Reviewer model: offer up to three harness-exposed tiers; recommend most-capable.
2. Maximum reviewer slots `N`: recommend from cohesion and packet weight, with
   `1 <= N <= min(groups, 16)`. `N` is a concurrency ceiling, not a requirement to fill every slot.
3. Soft round cap: default 12; minimum 2 only for an at-most-10-line surface, otherwise 3.

Do not dispatch until the user answers or explicitly delegates the choices. Model choice here does not
carry into validation.

## Review loop

1. Generate the next packets:

   ```bash
   python3 "$HELPER" pack-review --state state.json --slots N --out packets/round-N
   ```

   Each packet contains assigned units, group modes, raw evidence references and **compact local fingerprints**
   for known items. `global-index.json` is shared and read only when useful. Do not attach
   the whole reference corpus or global issue history to every dispatch.

2. Dispatch one fresh reviewer per packet, in parallel or capability-limited waves. It must read every
   assigned unit. Repository/reference expansion is on demand. Include the **Checked return protocol**
   below verbatim, plus absolute helper/state/return paths and its packet ID. Give each reviewer its own
   return file; the state is read-only. Do not paraphrase required fields as optional.

3. Each reviewer checks its own return before handing back its file path. On a failed check, send the
   exact stderr to that same reviewer for one repair attempt within its current round. This uses the
   existing one-slot retry allowance, not an extra review round. Wait for the barrier; independently run
   `check-return` on each saved return. Record a persistent failure as
   `{"packetId":"...","failed":true}`; it receives no coverage or clean credit.

4. Save one JSON return per packet, then merge mechanically:

   ```bash
   python3 "$HELPER" merge-review --state state.json --results returns/round-N
   python3 "$HELPER" status --state state.json
   ```

5. Repeat until every group converges or the cap is reached. At the cap, retain the existing one-round
   overrun only when one intensified confirmation is the sole missing condition; otherwise report
   incomplete convergence prominently.

Moving a group between packets never resets it. A finding with `linkedGroupIds` reopens every implicated
group and extends the topology. Fresh reviewers may expand the evidence cache using exact raw references;
never store their analysis or conclusions as cached evidence.

### Discovery return

Return only:

```json
{
  "packetId": "R02-S01",
  "assignmentComplete": true,
  "omittedUnitIds": [],
  "newItems": [{
    "tag": "BUG",
    "unitId": "U-001",
    "file": "target.md",
    "location": "L18",
    "fingerprint": "bounded retry count missing",
    "problem": "The recovery loop has no terminating bound.",
    "fix": "State the maximum attempts and terminal outcome.",
    "linkedGroupIds": []
  }],
  "challenges": [],
  "evidenceRefs": [{
    "groupId": "G-001", "path": "oracle.md", "lines": "L40-52", "hash": "<blob>"
  }]
}
```

Use `BUG` for correctness/security/data-integrity/crash/requirement failure and `QUALITY` for concrete
maintainability, convention, SDK misuse, naming, comment or performance problems introduced by the
surface. Do not propose speculative features or merely different designs.

Known fingerprints are duplicate suppression only: **do not validate known items** and do not repeat an
exact or materially equivalent issue. If independent investigation directly disproves one, add a short
`challenges` entry; validation owns the decision. A materially different consequence may use
`relatedTo` in its payload.

`assignmentComplete: true` credits assigned units except `omittedUnitIds`; this is equivalent to the old
self-reported hunk list without repeating every ID. For partial work, set it false and provide
`examinedUnitIds`.

### Checked return protocol

Deliver a checked JSON **file**, then its path in the final message. Python writes the JSON; review prose
belongs in text fields. This also applies to integration and validation. `check-return` checks format
and assignment, not whether a finding is correct.

1. Set `HELPER`, `STATE`, `RETURN` and `PACKET_ID` to the absolute paths/ID supplied at dispatch. Create
   the draft once; never recreate it over collected findings:

   ```bash
   python3 "$HELPER" return-template --state "$STATE" --packet-id "$PACKET_ID" > "$RETURN"
   ```

2. For each discovery finding, write plain UTF-8 problem/fix text to private scratch files, then add it:

   ```bash
   python3 "$HELPER" add-finding --state "$STATE" --result "$RETURN" \
     --unit-id U-001 --tag BUG --location L18 --fingerprint 'bounded retry count missing' \
     --problem-file /absolute/scratch/problem.txt --fix-file /absolute/scratch/fix.txt
   ```

   Substitute the actual unit, tag, location and fingerprint; the helper derives the target file.
   `--linked-group-id` is repeatable; `--related-to` names a related ledger item. Both are optional.
   Invalid additions leave the return unchanged. Never remove a finding merely to pass.

3. Add each raw evidence reference through the helper, using the actual group/path/line range:

   ```bash
   python3 "$HELPER" add-evidence --state "$STATE" --result "$RETURN" \
     --group-id G-001 --path /absolute/repository/oracle.md --lines L40-L52
   ```

   `groupId` is the **assigned review group this evidence supports**, not the evidence file's owning
   group. Choose only from this packet's `groupIds`; cross-group links belong in `linkedGroupIds`.
   Every reference requires `groupId`, `path`, `lines` and `hash`. The helper computes SHA-256 of the
   entire cited file's raw bytes; it never invents a hash or assigns an unrelated group.

4. Use Python `json.load` / `json.dump` to add challenges or validation decisions and to update coverage.
   The template starts incomplete. Set `assignmentComplete: true` only after examining all assigned
   units; otherwise leave it false and list exactly those examined in `examinedUnitIds`. Integration
   cannot claim completion with omitted units. Validators fill `decisions` for every assigned item
   and do not use the finding/evidence builders. Then run:

   ```bash
   python3 "$HELPER" check-return --state "$STATE" --result "$RETURN"
   ```

   Exit 0 is required before handoff. On failure, read the exact field-path error, repair the file and
   rerun once. A second failure exhausts the slot's retry allowance: report failure with the file path
   and stderr. Do not rewrite shared state, invent evidence or turn an invalid result into a clean one.

## Mandatory integration sweep

After provisional convergence, skip only when there is one cohesion group. Otherwise run:

```bash
python3 "$HELPER" pack-integration --state state.json --out packets/integration
```

Dispatch one fresh reviewer to inspect cross-group contracts and the compact global topology. In
Git-diff mode hunt interface mismatches, partial migrations and shared-state consequences. In file-set
mode check cross-section consistency and coverage of every supporting obligation. Use the checked return
protocol and the same item/challenge/evidence shapes, including the one-repair limit.

Merge at the barrier:

```bash
python3 "$HELPER" merge-integration --state state.json --result returns/integration.json
```

Any net-new issue reopens affected groups; reconverge them and repeat the integration sweep. One clean
integration result is required before validation.

## Blocking validation gate

Build validation cohesion groups from active items; keep shared root cause, target section, caller/callee,
duplicate and challenge relationships together. If the set is empty, skip validation and report clean.
Otherwise show item/file/group counts and recommend:

```text
V = max(1, min(validation_groups, 16, ceil(active_items / 8)))
```

Stop and ask separately for validator model and `V`. Then generate packets:

```bash
python3 "$HELPER" pack-validation --state state.json \
  --groups validation-groups.json --slots V --out packets/validation
```

Each validator receives full details only for its assigned IDs and relevant raw evidence. Include the
checked return protocol and absolute paths in its dispatch. It must confirm or drop every assigned ID,
must not add issues, and writes exactly:

```json
{"packetId":"V-S01","decisions":[
  {"ref":"L-001","decision":"confirm","reason":"Directly contradicted by oracle.md:L40-52."}
]}
```

Merge only at the validation barrier:

```bash
python3 "$HELPER" merge-validation --state state.json --results returns/validation
```

Use the checked protocol's one-repair allowance; do not grant another retry at merge. Mark persistent
failure with `failed:true`, report its IDs as unvalidated, and never infer decisions.

## Reporting and cleanup

Report only validated findings, plus convergence/incomplete-validation warnings. Include helper metrics
for actual versus legacy surface bytes and known-fingerprint rows; call them payload estimates unless the
harness exposes exact token usage. Optionally write the dated report under `docs/grill-diff/` with the
audit summary. Delete completed scratch state and always tear down temporary worktrees after cancelling
in-flight agents. Never modify reviewed targets.

## Stop signs

- A discovery reviewer is asked to adjudicate old findings → remove that work; validators own it.
- A packet contains unrelated issue history or copied supporting documents → regenerate local packets.
- A prior review backlog is silently treated as the current ledger → keep it as an obligation source.
- A group stops after one clean pass, Round 1 advances illegally, or coverage is below 2× → continue.
- Multiple groups reach validation without a clean integration sweep → run it first.
- The orchestrator manually merges or rewrites state instead of using the helper → stop and use the CLI.
- Defaults are announced and agents start before either blocking gate is answered → stop and wait.
