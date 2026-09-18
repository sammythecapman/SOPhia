---
name: SOP stage diagnostics
description: Durable observability rules for the staged SOP retrieval and answer pipeline.
---

Per-chunk gate decisions, conclusion synthesis, sub-question routing, and guarantor-row citation selection must remain separately observable in both the API response and server logs.

**Why:** The same visible failure can originate in retrieval, applicability, synthesis, audit, routing, or rendering; aggregate output alone cannot identify the broken stage.

**How to apply:** Include stable sub-question IDs, source breadcrumbs/pages, all gate dimensions and condition states, synthesizer input/output, artifact ownership, and row-trigger citations in debug telemetry. Product scope must come from breadcrumb ancestry because leaf headings can be generic.