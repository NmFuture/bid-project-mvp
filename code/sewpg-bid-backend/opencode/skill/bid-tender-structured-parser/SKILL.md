---
name: bid-tender-structured-parser
description: Parse one or more tender documents into structured bid requirements, scoring tables, fixed project and wind turbine fields, requirement presence, source evidence, and project dates.
---

# Bid Tender Structured Parser

Use this skill for S1 tender parsing when the backend provides an `s1_parse_manifest.json`.

Run exactly:

```bash
s1parse <manifest>
```

The command reads extracted tender text from the manifest, writes the full JSON result to `structuredResultPath`, and prints a compact summary JSON to stdout.

Parse every document in `manifest.documents`; do not assume the user uploaded a single file. Treat first/third volume evaluation documents and second-volume technical specifications as complementary sources, then merge them into one JSON result.

The full output JSON must preserve:

- `structured.sourceDocuments[]` with `id`, `name`, `role` (`evaluation`, `technical_spec`, `commercial_volume`, or `unknown`), and text length.
- `structured.scoringCriteria` split into `technical`, `business`, `price`, `lcoe`, and `compliance`. Each row must include `order`, `scoringItem`, `score`, `scorePoint`, `proofRequirement`, `sourceFile`, `sourceDocumentId`, `section`, `evidence`, and `evidenceLocation`.
- `structured.fieldGroups.projectBasics` for project name, tender number, tenderer, management unit, bid section scale, delivery period, warranty period, and technical commitment.
- `structured.fieldGroups.turbineCoreParameters` for single capacity, rotor diameter, hub height, blade tip clearance, tower type, box transformer type, safety class, air density, wind speed, and turbulence intensity.
- `structured.fieldGroups.performanceGuarantees` for power curve, availability, generation, and grid performance.
- `structured.fieldGroups.environmentAdaptation` for low temperature, icing/condensation, humidity, lightning, sandstorm, and high temperature.
- `structured.requirementPresence` for topic plans, supply scope, and assessment terms, each with present/missing status, summary, evidence, and sources.
- `structured.coverage[]` summarizing whether each target area is present, partial, complete, or missing.
- `structured.projectDates.startDate` and `structured.projectDates.endDate` only for bidding-stage dates, such as tender document acquisition/registration start and bid submission deadline/opening date.
- `sourceFile`, `sourceDocumentId`, `evidence`, and `evidenceLocation` for every extracted item, fixed field, and scoring row.

Important parsing rules:

- Prefer actual Word tables and body sections over table-of-contents entries.
- Classify scoring tables only when the section title is a scoring/evaluation title such as `附表2：技术评分标准表`, `附表3：商务评分标准表`, `附表4：投标报价评分标准`, `附表5：投标度电成本评分标准`, or `附表1：符合性审查标准表`.
- Do not treat supply scope, brand lists, appendix templates, or quotation/supply tables as scoring criteria merely because their cells mention “报价” or “评分”.
- Preserve section/title evidence for fields extracted from technical specification tables such as `招标机型要求`, `风资源情况`, `特殊防护要求`, `交货进度`, and `质保期`.
- Do not write delivery, supply, service-period, construction-period, completion, installation, commissioning, warranty, grid-connection, or production dates into `structured.projectDates`.
