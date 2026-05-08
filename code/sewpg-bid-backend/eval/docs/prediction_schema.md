# Prediction CSV Schema

Prediction files hold automation outputs aligned to the gold primary key. Each
row is one automated field attempt.

## Required Columns

| column | required | description |
|---|---:|---|
| `project_id` | yes | Project id. Must match gold. |
| `doc_type` | yes | `appendix` or `body`. Must match gold. |
| `locator` | yes | Stable field location. Must match gold. |
| `field_name` | yes | Field name. Must match gold. |
| `predicted_answer` | no | Automation-filled answer. Empty means no fill attempt unless `mark_yellow=true`. |
| `mark_yellow` | yes | `true` or `false`; whether the automation marked the field for human handling. |
| `evidence_refs` | no | JSON string or semicolon-separated evidence references. |
| `skill_name` | yes | Skill or component that produced the value. |
| `fill_path` | no | Planned route, such as `direct_quote`, `kb_lookup`, `material_rag`, `derive`, or `mark_yellow`. |
| `confidence` | no | Numeric confidence between `0` and `1`, if available. |

## Alignment Key

Predictions align to gold using the same primary key:

```text
project_id + doc_type + locator + field_name
```

Rows that cannot align to gold must be reported as extraction or locator
errors, not silently ignored.

## Notes

The prediction schema intentionally does not include `human_answer`,
`field_type`, or `difficulty_tier`. Those fields belong to gold and must not be
available to the filling skill.
