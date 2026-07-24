# Evaluation Runs

Each evaluation run writes artifacts under a run id:

```text
runs/
  baseline-prj0003/
    predictions.csv
    metrics.json
    failure_breakdown.json
    evidence_audit.csv
    report.md
```

Generated run artifacts should be committed only when they are deliberate
baseline or regression records.
