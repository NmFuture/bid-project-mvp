---
name: bid-business-tender-structured-parser
description: Parse one or more business tender documents into business-specific structured requirements, core review fields, bidder instruction table rows, commercial rejection clauses, scoring tables, commitment letters, and source evidence.
---

# Bid Business Tender Structured Parser

Use this skill for `S1` business tender parsing when the backend provides an `s1_parse_manifest.json`.

Run exactly:

```bash
s1parse <manifest>
```

The command reads extracted tender text from the manifest, writes the full JSON result to `structuredResultPath`, and prints a compact summary JSON to stdout.

Parse every document in `manifest.documents`; do not assume the user uploaded only one file. Preserve source evidence and merge complementary business volume, evaluation volume, and appendix/attachment sources into one business-parse contract.

The full output JSON must preserve:

- `structured.sourceDocuments[]` with `id`, `name`, `role`, and text length.
- `structured.scoringCriteria` split into `business`, `price`, and `compliance`.
- `structured.fieldGroups.projectBasics` for `projectName`, `tenderNo`, `tenderer`, `tenderAgency`, and `bidDeadline`. Prefer cover table and bidder instruction preface table over generic full-text matches; do not use reference-only values such as `见投标人须知前附表` as final values.
- `structured.fieldGroups.businessResponse` for bid letter, authorization letter, integrity commitment, seal validity statement, price/specification/deviation/supply-scope tables, bid security, performance bond commitment, and attachment-9 requirements.
- `structured.fieldGroups.qualificationSupport` for qualification, performance, financial, credit, certification, and customer-specific proof requirements.
- `structured.fieldGroups.qualificationRequirements[]` as concise bidder qualification requirement rows, reusing existing qualification support evidence where possible.
- `structured.fieldGroups.bidderInstructions[]` as row-level records extracted from the `投标人须知前附表` table, with `clauseNo`, `clauseName`, `content`, and source evidence.
- `structured.fieldGroups.commercialRejectionClauses[]` as row-level commercial rejection/disqualification clauses matching `否决`, `废标`, `无效投标`, `不予受理`, `★`, `实质性响应`, `投标人不得存在`, or `不得存在下列情形`.
- `structured.fieldGroups.commitmentRequirements` for commitment count, disqualification commitment, other-commitment section, and commitment-generation basis.
- `structured.requirementPresence` for qualification documents, performance documents, deviation response, bid security, other commitments, and disqualification clauses.
- `structured.commitmentLetters[]` with commitment type, trigger evidence, placement hint, and preview metadata.
- `structured.projectFactFields[]` with stable project facts for downstream S3/S4 filling, including project name, tender number, tenderer, management unit, section scale, delivery period, warranty period, bid start date, and bid deadline.
- `structured.coverage[]` summarizing business response coverage.
- `structured.projectDates.startDate` and `structured.projectDates.endDate` only for bidding-stage dates, not delivery/service/construction dates.
- `sourceFile`, `sourceDocumentId`, `section`, `evidence`, and `evidenceLocation` for every extracted scoring row, field, and commitment trigger.

Important parsing rules:

- Business parsing is separate from the technical contract. Do not emit technical-only field groups such as turbine parameters, performance guarantees, or environment adaptation.
- Search the full tender text for `承诺` and `不得存在下列情形` to build commitment requirements and commitment-letter candidates.
- Keep commitment letters as structured artifacts; do not try to invent final legal wording in this step.
- If a business scoring table appears in Markdown table form, parse it and classify it into `business`, `price`, or `compliance` by section title.
