---
name: SOP fact-facet retrieval
description: General retrieval practices for compound fact patterns and policy passages split across adjacent chunks.
---

Retrieve each material fact independently rather than relying only on a broad question embedding. Keep a lexical OR fallback so one salient term can surface the governing passage, then retain immediate same-section context so a condition and its operative rule are evaluated together.

**Why:** A broad question and a short phrase both missed relevant SOP text in semantic retrieval, while English `plainto_tsquery` required every query term and returned no hit. The policy wording used a different combination of relevant terms than the user's prompt.

**How to apply:** For compound or fact-rich SOP questions, query the original prompt, discrete issue, and material facts separately. Use general tokenization and OR matching instead of a fixed issue-type map; preserve nearby chunks only within the same section and corpus.