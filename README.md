# grill-review

[![CI](https://github.com/Guowei-Yan/grill-review/actions/workflows/ci.yml/badge.svg)](https://github.com/Guowei-Yan/grill-review/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)

Deterministic multi-pass coverage ledger and candidate-validation engine for exhaustive diff, pull-request, and whole-file code reviews (**zero third-party runtime dependencies**).

Single-pass LLM code reviews routinely skip large hunks, hallucinate false positives, or re-litigate previously rejected items across rounds. `grill-review` partitions diffs or whole target files into deterministic review units, emits compact local fingerprints so discovery subagents never re-adjudicate known items, enforces checked per-unit reviewer returns, separates candidate discovery from fresh-context false-positive filtering, and requires **every unit examined ≥2× plus two consecutive clean rounds** before convergence.

---

## Architecture & Workflow Suite

| Component | Purpose |
| :--- | :--- |
| [`grill-review/scripts/`](grill-review/scripts/) | Shared deterministic state engine (`grill-review.py`, `grill_review_ingest.py`, `grill_review_engine.py`, `grill_review_returns.py`, `grill_review_validation.py`) |
| [`grill-diff/`](grill-diff/) | Correctness, specification-alignment, and edge-case review skill across diffs, branches, PRs, or explicit file sets |
| [`grill-yagni/`](grill-yagni/) | Over-engineering & YAGNI review skill surfacing code or prose removable without changing requested behavior |
| [`grill-review/tests/`](grill-review/tests/) | **55 unit & contract tests** verifying ingest boundaries, checked return invariants, validation routing, and skill sync |

---

## Key Guarantees

- **Checked Unit Coverage**: Discovery packets list explicit hunk/section IDs; `merge` rejects any subagent return that omits assigned unit IDs or violates return schemas.
- **Compact Local Fingerprints**: Instead of bloating worker prompts with the entire global finding ledger, each packet receives only compact fingerprints of already-recorded candidates touching its local file slice.
- **Two-Stage False-Positive Filtering**: Discovery workers propose candidates; independent fresh-context validator packets confirm or drop each candidate against primary code and supporting spec/plan documents before reporting.
- **Strict Convergence Gate**: Runs terminate cleanly only after every in-scope unit has been examined at least twice, intensified passes complete, and two consecutive rounds surface zero new confirmed findings, followed by a final cross-unit integration sweep.

---

## Quickstart

### Run the Test Suite

```bash
python3 -m unittest discover -s grill-review/tests -p 'test_*.py' -v
```

### Inspect CLI Subcommands

```bash
python3 grill-review/scripts/grill-review.py --help
```

### Install Companion Skills Locally

```bash
./grill-diff/sync-grill-diff.sh
./grill-yagni/sync-grill-yagni.sh
```

---

## License

[MIT](LICENSE)
