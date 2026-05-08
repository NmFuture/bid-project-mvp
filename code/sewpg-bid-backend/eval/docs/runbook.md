# Evaluation Runbook

This runbook maps the implementation to `doc/17`.

## Stage A - Scaffold

Already present:

- `eval/README.md`
- `eval/docs/gold_schema.md`
- `eval/docs/prediction_schema.md`
- `eval/scripts/gold_schema.py`
- `eval/scripts/load_gold.py`
- `eval/scripts/validate_gold.py`

Smoke command:

```bash
python3 eval/scripts/validate_gold.py eval/gold/PRJ-0003/sample.csv
```

## Stage B - PRJ-0003 Gold

Required external inputs:

- Human appendix docx.
- Human body docx.

Draft extraction:

```bash
python3 eval/scripts/extract_gold_draft.py \
  --project-id PRJ-0003 \
  --doc-type appendix \
  --input /path/to/投标文件-附表.docx \
  --output eval/gold/PRJ-0003/appendix.csv

python3 eval/scripts/extract_gold_draft.py \
  --project-id PRJ-0003 \
  --doc-type body \
  --input /path/to/投标文件-正文.docx \
  --output eval/gold/PRJ-0003/body.csv
```

The generated CSV is only a draft. A human must fill or correct:

- `human_answer`
- `field_type`
- `difficulty_tier`
- `evidence_source`

Validation:

```bash
python3 eval/scripts/validate_gold.py \
  eval/gold/PRJ-0003/appendix.csv \
  eval/gold/PRJ-0003/body.csv
```

## Stage C - Evaluation Engine

Extract predictions from fill reports when available:

```bash
python3 eval/scripts/extract_predictions.py \
  --project-id PRJ-0003 \
  --doc-type appendix \
  --reports /path/to/*.fill_report.json \
  --output eval/runs/baseline-prj0003/predictions.csv
```

Run once predictions are extracted into CSV:

```bash
python3 eval/scripts/run_eval.py \
  --gold eval/gold/PRJ-0003/appendix.csv eval/gold/PRJ-0003/body.csv \
  --predictions eval/runs/baseline-prj0003/predictions.csv \
  --run-dir eval/runs/baseline-prj0003
```

Outputs:

- `metrics.json`
- `failure_breakdown.json`
- `evidence_audit.csv`
- `report.md`

## Stage E - Isolation Checks

```bash
python3 eval/scripts/lint_eval_isolation.py --repo-root .
python3 eval/scripts/lint_skill_hardcode.py --skill-dir opencode/skill
```

## Stage F - Blind Test

Repeat Stage B and Stage C for a hold-out project. Do not tune prompts or
skills against that project before the first blind run.
