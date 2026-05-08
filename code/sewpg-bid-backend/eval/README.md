# Technical Bid Evaluation

This directory contains the field-level evaluation system described in
`../../../doc/17-评测体系建设计划.md`.

The evaluation code is intentionally isolated from the production S3 filling
skills. Files under `eval/` may read exported skill artifacts and generated
documents, but production code and skill code must not import from `eval/`.
Evaluation data such as gold answers must never be mounted into the skill
runtime.

## Directory Layout

```text
eval/
  docs/      Schema and operating notes.
  gold/      Human gold answers, grouped by project.
  judge/     Paragraph judge prompt and calibration assets.
  runs/      Evaluation outputs by run id.
  scripts/   Standalone loaders, validators, and metrics code.
```

## Current Scope

The first milestone only locks the CSV contracts and validates gold files:

- `gold_schema.py` defines the gold and prediction row contracts.
- `extract_gold_draft.py` creates a human-review draft CSV from a docx.
- `extract_predictions.py` creates prediction CSV rows from fill report JSON.
- `validate_gold.py` checks primary-key uniqueness and legal enum values.
- `load_gold.py` loads one or more gold CSV files.
- `lint_eval_isolation.py` enforces physical import isolation.
- `lint_skill_hardcode.py` blocks obvious gold/sample hardcoding in skills.

Later milestones will add prediction extraction, diff engines, metrics,
evidence audit, and report rendering.

## Smoke Run

```bash
python3 eval/scripts/run_eval.py \
  --gold eval/gold/PRJ-0003/sample.csv \
  --predictions eval/runs/sample/predictions.csv \
  --run-dir eval/runs/sample
```

## Isolation Rules

- `eval/scripts` must use only the Python standard library unless a later
  evaluation task explicitly adds an eval-only dependency.
- `eval/scripts` must not import `app.*` or `opencode.skill.*`.
- Production backend code under `app/` and skill code under `opencode/skill/`
  must not import from `eval/`.
- Gold files are read-only evaluation inputs. Filling skills must not receive
  gold paths, gold metadata, or human answers.
