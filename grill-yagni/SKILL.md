---
name: grill-yagni
description: >-
  Use when an exhaustive repeated over-engineering review is needed for a branch, PR, pasted diff, or
  explicitly listed files; when every changed hunk or whole target-file section must be checked for code
  or prose that can be deleted or shrunk without changing requested behaviour.
---

# Grill Yagni

Review only; never apply cuts or post comments. Hunt unnecessary complexity with fresh judgement while
reusing raw evidence and deterministic state. Run the bundled `scripts/grill-review.py` for manifests,
packet slicing, ledger IDs, deduplication, coverage, convergence and validation ownership. Do not
reimplement those mechanics in the orchestrator context.

Every finding names a concrete target location, what to cut, what replaces it and estimated lines saved.
Find cuts only—correctness, security and performance bugs belong to `grill-diff`.

## Guarantees

- Use a new subagent context for every review packet, integration sweep and validation packet.
- Review every in-scope unit; every unit must be examined ≥2×.
- Require two consecutive clean passes per cohesion group; the second must be intensified.
- Round 1 does not count as clean unless the whole in-scope surface is at most 10 lines.
- Keep progress on cohesion groups, never temporary slot partitions. A finding resets only its owning
  group and explicitly linked groups.
- Keep the repository or reference corpus available read-only. Cached evidence is navigation, never a
  restriction on fresh investigation.
- Let validators confirm or drop findings. Discovery rounds hunt for new cuts; they do not re-validate
  known findings.

## Choose the review surface

### Git-diff mode

Use for a branch/PR, several branches completing one task, or a pasted diff. Cuts must trace to an added
or modified line. Unchanged code, merge-target code and repository files are evidence only.

- Single branch: use the merge-base surface, `git diff <target>...HEAD`.
- Multi-branch: create one temporary worktree, merge branches in the user's order, and share it read-only.
  On conflict, do not resolve automatically; offer the weaker union-of-diffs fallback and explain it.
- Dirty computed scope: ask whether to include uncommitted changes; default to committed-only.
- Pasted diff: warn that repository-wide duplication/native-alternative checks may be incomplete.

### file-set mode

Use when the user says to grill named file(s) only. The listed targets' entire current contents are in
scope. Other supplied files are reference-only and establish which complexity is actually necessary.

- For Markdown, make stable units from heading/section paths; split oversized sections without
  separating one proposed mechanism from the behaviour claimed to require it.
- For other files, use stable symbol/region units. Every target line belongs to exactly one unit.
- Report cuts only against target lines. An omission is not a YAGNI finding because there is nothing to
  delete; use references to prove that existing target complexity is unnecessary.
- Classify supplied material as authority, context or historical obligation. A prior review backlog is
  not a runtime ledger. Resume a prior ledger only from matching helper state; without that state, start
  a new run and keep the backlog reference-only.
- Never report pre-existing bloat in supporting files.

An empty target surface stops cleanly. Hash the complete review surface; if a target changes during the
run, invalidate affected units before continuing.

## Compile the manifest once

Put run artefacts outside the reviewed targets/worktree. Resolve the synced helper once; an agent host
may override its installed location with `GRILL_REVIEW_HELPER`:

```bash
HELPER="${GRILL_REVIEW_HELPER:-$HOME/.local/share/grill-review/grill-review.py}"
test -f "$HELPER"
python3 "$HELPER" manifest-template --mode <git-diff|file-set> --lens yagni > manifest.json
```

Fill the template:

- `surface.targets` and `surface.references` are disjoint; `globalIndex` contains compact paths,
  headings/symbols, roles and hashes—not copied document bodies.
- Each unit has `id`, `groupId`, `path`, `location`, `contentRef` and `bytes`.
- Cohesion groups tile units exactly once. Keep same function/section, caller/callee, shared state/type,
  target/obligation pairs and likely duplication together. Record known cross-group links.
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
   for known items. `global-index.json` is shared and read only when useful. Do not attach the whole
   reference corpus or global issue history to every dispatch.

2. Dispatch one fresh reviewer per packet, in parallel or capability-limited waves. It must read every
   assigned unit. Repository/reference expansion is on demand.

3. Wait for the barrier. Retry a failed or malformed slot once. Record a persistent failure as
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
    "tag": "yagni",
    "unitId": "U-001",
    "file": "target.md",
    "location": "L18-31",
    "fingerprint": "single implementation strategy interface",
    "cut": "RecoveryStrategy interface and only implementation",
    "replacement": "Use the implementation directly until a second strategy exists.",
    "linesSaved": 18,
    "linkedGroupIds": []
  }],
  "challenges": [],
  "evidenceRefs": [{
    "groupId": "G-001", "path": "src/recovery.py", "lines": "L40-90", "hash": "<blob>"
  }]
}
```

Use exactly five tags:

- `delete`: dead/speculative code or flexibility; replacement is nothing.
- `stdlib`: hand-rolled standard-library behaviour; name the function.
- `native`: dependency/code replaced by a real platform feature; name it.
- `yagni`: abstraction/configuration/layer without a present second use.
- `shrink`: behaviour-preserving shorter form; show it.

Do not report a bug, a requested feature itself, necessary validation/error handling/security/accessibility,
or a merely different style. Do not flag the single smoke test/assert-based self-check minimum.

Known fingerprints are duplicate suppression only: **do not validate known items** and do not repeat an
exact or materially equivalent cut. If independent investigation directly disproves one, add a short
`challenges` entry; validation owns the decision. A materially different cut may use `relatedTo`.

`assignmentComplete: true` credits assigned units except `omittedUnitIds`; this replaces repeated arrays
of every examined ID. For partial work, set it false and provide `examinedUnitIds`.

## Mandatory integration sweep

After provisional convergence, skip only when there is one cohesion group. Otherwise run:

```bash
python3 "$HELPER" pack-integration --state state.json --out packets/integration
```

Dispatch one fresh reviewer over the compact global topology. In Git-diff mode hunt duplicated helpers,
reinvented repository utilities, redundant dependencies and cross-group abstractions. In file-set mode
check repeated mechanisms and whether supporting behaviour actually requires each planned layer. It
returns the same item/challenge/evidence shapes.

Merge at the barrier:

```bash
python3 "$HELPER" merge-integration --state state.json --result returns/integration.json
```

Any net-new cut reopens affected groups; reconverge them and repeat the integration sweep. One clean
integration result is required before validation.

## Blocking validation gate

Build validation cohesion groups from active items; keep shared replacement, target section, root cause,
duplicate and challenge relationships together. If the set is empty, skip validation and report
`Lean already. Ship.` Otherwise show item/file/group counts and recommend:

```text
V = max(1, min(validation_groups, 16, ceil(active_items / 8)))
```

Stop and ask separately for validator model and `V`. Then generate packets:

```bash
python3 "$HELPER" pack-validation --state state.json \
  --groups validation-groups.json --slots V --out packets/validation
```

Each validator receives full details only for its assigned IDs and relevant raw evidence. It must confirm
or drop every assigned ID and must prove that the replacement is real and behaviour-preserving; it must
not add cuts. Return exactly:

```json
{"packetId":"V-S01","decisions":[
  {"ref":"L-001","decision":"confirm","reason":"Only one implementation exists and callers are direct."}
]}
```

Drop a proposed replacement that removes behaviour, validation, error handling, security or accessibility.
Merge only at the validation barrier:

```bash
python3 "$HELPER" merge-validation --state state.json --results returns/validation
```

Retry an invalid slot once; mark a persistent failure with `failed:true`, report its IDs as unvalidated,
and never infer decisions.

## Reporting and cleanup

Report only validated cuts in concise cut-ledger format:

```text
<file>:L<lines>: <tag>: <what to cut>. <what replaces it>.
net: -<N> lines possible.
```

Include convergence/incomplete-validation warnings and helper metrics for actual versus legacy surface
bytes and known-fingerprint rows; call them payload estimates unless the harness exposes exact token
usage. Optionally write the dated report under `docs/grill-yagni/` with the audit summary. Delete
completed scratch state and always tear down temporary worktrees after cancelling in-flight agents.
Never modify reviewed targets.

## Stop signs

- A discovery reviewer is asked to adjudicate old cuts → remove that work; validators own it.
- A packet contains unrelated issue history or copied supporting documents → regenerate local packets.
- A prior review backlog is silently treated as the current ledger → keep it as an obligation source.
- A group stops after one clean pass, Round 1 advances illegally, or coverage is below 2× → continue.
- Multiple groups reach validation without a clean integration sweep → run it first.
- A cut changes behaviour or names an unverified replacement → validation must drop it.
- The orchestrator manually merges or rewrites state instead of using the helper → stop and use the CLI.
- Defaults are announced and agents start before either blocking gate is answered → stop and wait.
