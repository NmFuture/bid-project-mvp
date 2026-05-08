---
name: bid-business-tender-structured-parser
description: Parse one or more business tender documents into business-specific structured requirements, scoring tables, response fields, qualification support, commitment letters, and source evidence.
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
- `structured.fieldGroups.projectBasics` for project name, tender number, tenderer, management unit, bid section scale, delivery period, and warranty period.
- `structured.fieldGroups.businessResponse` for bid letter, authorization letter, integrity commitment, seal validity statement, price/specification/deviation/supply-scope tables, bid security, performance bond commitment, and attachment-9 requirements.
- `structured.fieldGroups.qualificationSupport` for qualification, performance, financial, credit, certification, and customer-specific proof requirements.
- `structured.fieldGroups.commitmentRequirements` for commitment count, disqualification commitment, other-commitment section, and commitment-generation basis.
- `structured.requirementPresence` for qualification documents, performance documents, deviation response, bid security, other commitments, and disqualification clauses.
- `structured.commitmentLetters[]` with commitment type, trigger evidence, placement hint, and preview metadata.
- `structured.coverage[]` summarizing business response coverage.
- `structured.projectDates.startDate` and `structured.projectDates.endDate` only for bidding-stage dates, not delivery/service/construction dates.
- `sourceFile`, `sourceDocumentId`, `section`, `evidence`, and `evidenceLocation` for every extracted scoring row, field, and commitment trigger.

Important parsing rules:

- Business parsing is separate from the technical contract. Do not emit technical-only field groups such as turbine parameters, performance guarantees, or environment adaptation.
- Search the full tender text for `承诺` and `不得存在下列情形` to build commitment requirements and commitment-letter candidates.
- Keep commitment letters as structured artifacts; do not try to invent final legal wording in this step.
- If a business scoring table appears in Markdown table form, parse it and classify it into `business`, `price`, or `compliance` by section title.
