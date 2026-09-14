---
name: cell-intake
description: Extract and assess CellForge customer inputs without inventing missing facts.
---

# CellForge intake

1. Read `inputs/manifest.yaml` and `analysis/extraction.json`; never infer file types only
   from names when a manifest kind is present.
2. For PDFs, inspect every `page-NNN.txt`. Inspect the matching PNG when text is empty,
   damaged, tabular, or layout-dependent. Cite source filename and page in `intake.md`.
3. For spreadsheets, treat each extracted `RNNN` row as a source row. Preserve item numbers,
   limits, sampling rules, and pass/fail language. Never merge rows with different criteria.
4. Inspect every product photo through the review copy listed in `extraction.json`; the original
   remains under `inputs/`. Record visible faces, ports, covers, hinges, labels, and scale
   uncertainty. A visually estimated dimension is always `trust: inferred`.
5. Ask only questions that can materially change geometry, process, hardware, safety, site
   layout, or takt. Produce 5-15 questions, each with a useful default.
6. Keep confirmed, inferred, and unknown information distinct. Unknown is a question; a
   default becomes an assumption only after the user skips that question.
7. Validate YAML before finishing.

The checklist coverage denominator is the number of identifiable inspection rows. Map at
least 80%, and write `Coverage: M/N (P%)` exactly once at the end of checklist_map.md.
