---
name: SOP applicability gate
description: Structured metadata and filtering rules that prevent provisions for the wrong transaction type from supporting an answer.
---

SOP chunks must carry structured transaction, entity, party-role, program-scope, product-line, and loan-size tags at ingestion. User facts receive the same tags, and sources are excluded only when both sides state conflicting values on a dimension; missing or unknown values default to applicable. Rejected evidence must never receive an affirmative support badge.

**Why:** Similarity retrieval surfaced ESOP and partial-change provisions for ordinary 7(a) transactions, and textual entailment alone accepted them because the quoted rule was paraphrased correctly despite its trigger not matching the facts.

**How to apply:** Treat empty tags as universal for every dimension. For indexed chunks, derive transaction/product/size scope from the nearest heading, with Appendix 15's explicit change-of-ownership default as the exception. Evaluate internal numeric/entity conditions in code after tag filtering, fail open when facts are silent or a condition cannot be parsed, and keep not-applicable evidence visibly distinct from unsupported and supported evidence.