---
name: SOP grounding contract
description: Durable safety rule for answer generation and citation rendering
---

The SOP answer contract is proposition-level: every factual proposition rendered to the user must carry a source quote located in the stored chunk and pass an independent support audit. Provenance and entailment are separate signals.

**Why:** A quote can exist in the document while failing to support the model’s broader conclusion; whole-answer verification allowed fabricated claims to appear trustworthy.

**How to apply:** Decompose compound questions, retrieve each sub-question separately, add targeted guaranty retrieval for ownership/trust terms, decline unsupported sub-points, and render source version, effective date, section, and page metadata with the citation.