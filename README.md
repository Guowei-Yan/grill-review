# grill-review

[![CI](https://github.com/Guowei-Yan/grill-review/actions/workflows/ci.yml/badge.svg)](https://github.com/Guowei-Yan/grill-review/actions/workflows/ci.yml)

Multi-pass hunk-coverage ledger and false-positive filtering harness for diff, PR, and whole-file code reviews (`Python 3.10+` stdlib, MIT).

Single-pass LLM reviews miss large hunks, fabricate false positives, and re-litigate rejected findings across rounds. `grill-review` splits diffs or target files into deterministic review units, passes compact local fingerprints of prior candidates to each packet, enforces checked per-unit returns at `merge`, validates every candidate in a fresh context against primary code/specs, and only converges once **every unit has been examined ≥2× and two consecutive rounds confirm zero new findings**.

## Packages

| Path | Role |
| :--- | :--- |
| [`grill-review/scripts/`](grill-review/scripts/) | Core CLI & state engine (`grill-review.py`, `grill_review_ingest.py`, `grill_review_engine.py`, `grill_review_returns.py`, `grill_review_validation.py`) |
| [`grill-diff/`](grill-diff/) | Exhaustive correctness & spec-alignment review workflow (`sync-grill-diff.sh`) |
| [`grill-yagni/`](grill-yagni/) | Over-engineering & YAGNI simplification workflow (`sync-grill-yagni.sh`) |
| [`grill-review/tests/`](grill-review/tests/) | Unit & contract tests covering ingest boundaries, checked returns, validation routing, and skill sync |

## Running Tests & CLI

```bash
python3 -m unittest discover -s grill-review/tests -p 'test_*.py' -v
python3 grill-review/scripts/grill-review.py --help
```
