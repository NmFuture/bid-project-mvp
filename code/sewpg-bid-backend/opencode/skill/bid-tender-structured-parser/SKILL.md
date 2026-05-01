---
name: bid-tender-structured-parser
description: Parse one or more tender documents into structured bid requirements with evidence and project dates.
---

# Bid Tender Structured Parser

Use this skill for S1 tender parsing when the backend provides an `s1_parse_manifest.json`.

Run exactly:

```bash
s1parse <manifest>
```

The command reads extracted tender text from the manifest, writes the full JSON result to `structuredResultPath`, and prints a compact summary JSON to stdout.

The output must preserve:

- structured requirement items for scoring criteria, project basics, turbine parameters, performance guarantees, environment adaptation, topic plans, tables/supply scope, and assessment terms
- project start and end dates when visible in the tender text
- `sourceFile`, `sourceDocumentId`, `evidence`, and `evidenceLocation` for every item
