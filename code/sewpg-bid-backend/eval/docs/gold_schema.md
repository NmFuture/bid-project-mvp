# Gold CSV Schema

Gold files hold human answers at field level. Each row is one fillable or
auditable field.

## Required Columns

| column | required | description |
|---|---:|---|
| `project_id` | yes | Project id, for example `PRJ-0003`. |
| `doc_type` | yes | `appendix` or `body`. |
| `locator` | yes | Stable field location, such as table name plus row number, or chapter path plus placeholder id. |
| `field_name` | yes | Human-readable field name. |
| `human_answer` | no | Human-filled answer. Empty is allowed only for `difficulty_tier=T5` or `field_type=not_fillable`. |
| `field_type` | yes | `numeric`, `enum`, `phrase`, `paragraph`, `list`, or `not_fillable`. |
| `difficulty_tier` | yes | `T1`, `T2`, `T3`, `T4`, or `T5`. |
| `evidence_source` | no | Optional source note for the human answer. |

## Primary Key

The primary key is:

```text
project_id + doc_type + locator + field_name
```

The tuple must be unique across all gold CSV files loaded for one evaluation.

## Field Type Rules

- `numeric`: numeric values with units or tolerance rules handled by diff code.
- `enum`: closed set values after normalization.
- `phrase`: short text, exact after normalization and synonym handling.
- `paragraph`: long text judged by an independent paragraph judge.
- `list`: set-like answer evaluated with IoU.
- `not_fillable`: the correct behavior is to mark as needing human input.

## Difficulty Rules

- `T1`: direct tender-file copy.
- `T2`: core project fact.
- `T3`: material library retrieval.
- `T4`: cross-field derivation.
- `T5`: not safely fillable by automation.

`T5` rows should normally leave `human_answer` empty. Non-`T5` rows should
normally have `human_answer`.

## Example

```csv
project_id,doc_type,locator,field_name,human_answer,field_type,difficulty_tier,evidence_source
PRJ-0003,appendix,附表C/表1/行3,投标机型,SE-15530,phrase,T2,投标机型参数表
```
