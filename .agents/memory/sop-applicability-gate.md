---
name: SOP applicability gate
description: Structured metadata and filtering rules that prevent provisions for the wrong transaction type from supporting an answer.
---

SOP chunks must carry structured transaction, entity, party-role, program-scope, product-line, and loan-size tags at ingestion. User facts receive the same tags, and sources are excluded only when both sides state conflicting values on a dimension; missing or unknown values default to applicable. Rejected evidence must never receive an affirmative support badge.

**Why:** Similarity retrieval surfaced ESOP and partial-change provisions for ordinary 7(a) transactions, and textual entailment alone accepted them because the quoted rule was paraphrased correctly despite its trigger not matching the facts. A broad chunk can also place an independent general rule beside unrelated transaction-specific routing language, so whole-chunk condition checks can suppress the rule.

**How to apply:** Treat empty tags as universal for every dimension. For indexed chunks, derive transaction/product/size scope from the nearest heading, with Appendix 15's explicit change-of-ownership default as the exception. Evaluate internal numeric/entity conditions in code after tag filtering, fail open when facts are silent or a condition cannot be parsed, and keep not-applicable evidence visibly distinct from unsupported and supported evidence. If a responsive standalone rule shares a chunk with unrelated conditions, evaluate those conditions against that exact clause while retaining the source's structured scope tags and requiring citations to quote the evaluated clause.

For compound questions, keep retrieval seeds scoped to each discrete issue while preserving the complete user-supplied facts for applicability checks. Apply issue-relevance checks to every renderable claim, including propositions used as a fallback answer.

**Why:** Mixed guaranty and seller-note questions allowed unrelated underwriting language into the seller-note issue, and a fallback proposition could bypass the conclusion-only relevance check.

**How to apply:** Derive and audit each source issue against its requested sub-question before rendering claims; do not let vocabulary from a separate issue make adjacent evidence appear responsive.