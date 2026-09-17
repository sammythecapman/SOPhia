---
name: SOP applicability gate
description: Structured metadata and filtering rules that prevent provisions for the wrong transaction type from supporting an answer.
---

SOP chunks must carry structured transaction, entity, party-role, and program-scope tags at ingestion. User facts receive the same tags, and sources with incompatible scoped tags are filtered before generation and entailment auditing; rejected evidence must never receive an affirmative support badge.

**Why:** Similarity retrieval surfaced ESOP and partial-change provisions for ordinary 7(a) transactions, and textual entailment alone accepted them because the quoted rule was paraphrased correctly despite its trigger not matching the facts.

**How to apply:** Treat empty tags as universal only for legacy rows that are classified on read; prefer backfilling those rows. Keep not-applicable evidence visibly distinct from unsupported and supported evidence.