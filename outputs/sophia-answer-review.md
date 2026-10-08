# SOPhia answer review — 2026-10-08

**Scope:** Live development responses, not authenticated production proof or legal advice.
The final responses are saved in `sophia-issue-eval-results.json` and
`sophia-trust-development-answer.json`. They were captured against source SHA
`0fb0c4692cf529380827746e5fe812e42ea82b6f6fdf97a71d1093677d963183`
and source-content build SHA
`7f6d64de265556d519bd29d2238d504b4b92ab9f6f8a3fd5a8ee10ba76061891`.
The six captured answers and their hashes were preserved when rescored
against an added guard for the reproduced unsupported permission claim.

## Fact-changing covenant questions

Six distinct live questions produced eleven issue-specific subanswers. Ten
remain `not_established`. The eleventh claims that a signed agreement makes
the proposed increase valid, **but fails legal hand-review**. The report now
honestly fails the added consent-sufficiency counterexample check: 87 of 88
checks pass. This is not a legal-answer or demo pass.

- Unspecified rate/consent, 504 Preference, and $125,000 balance with specific
  SBA written consent: each has a saved real response. The contrast answer
  visibly preserves both the balance and consent; the balance is no longer
  inferred to be a $125,000 *loan*.
- Variable-rate with the Borrower's signed written agreement to this specific
  change, variable-rate with expressly no written agreement, and fixed-rate
  with a specific signed agreement: the responses retain each materially
  different rate/agreement fact rather than saying the facts did not establish
  them. The signed variable-rate answer is nevertheless an overclaim: it
  calls the agreement “valid under the note-rate rules” because it supplies
  “necessary consent.” Its quote says the spread “may not be changed ...
  without the written agreement of the Borrower.” That is a necessary
  condition, not proof of overall permissibility. Another selected quote
  requires consent **and** notification to the LGPC or a change through
  E-Tran Servicing; that additional action is not established by the facts.
  The independent citation audit admitted the conclusion anyway. This is a
  reproduced answer-pipeline defect, not just a stale-report problem.

An earlier live pass incorrectly called an account covenant a prohibited
Preference from the prohibition alone and treated consent as sufficient
permission for a rate increase. These were actual answer failures, even where
structural checks were green. The hard-coded covenant conclusion and automatic
post-audit conclusion substitution have been removed. However, a live model
can still make the consent-sufficiency error through the remaining semantic
audit. The new eval catches the observed wording; it does not fix the
answer generator or prove every other formulation safe.

## Trust aggregation, development only

For two revocable trusts owning 12% and 8%, the visible aggregation answer
correctly uses **20% exactly**, not "exceeds 20%." The cited SOP 50 10 8.1
Guaranties passage (page 93) says: “When one or more trusts (revocable or
irrevocable) own, in the aggregate, 20% or more of the applicant, each trust
must provide an unlimited full guaranty.” The aggregation conclusion and
two trust guaranties are supported for the stated facts.

**The separate “who must sign” answer is incomplete.** The final live answer
correctly cites the trustee's execution rule, but omits the retrieved rule:
“In addition, when a trust guaranty is required, the Trustor must also
personally guarantee the loan.” It labels the signer issue `supported` and
has no Trustor row or explicit unresolved capacity. An earlier live run
instead attached a Note-signing exception to its proposed Trustor
explanation, which the audit rejected; dropping the capacity altogether is
not a completeness fix. Do not present source text I located manually as a
completed, cited user answer. This signer-capacity gap remains a blocker.

The final fact echo quotes only the declarative ownership premise, not the
user's question about whether ownership aggregates. That fact-label defect
was fixed and checked against this live response.

## Published-build verification

The public production `/api/healthz` returned the correct corpus SHA and
395 chunks, but did **not** return this new build SHA. An unsigned query
returned 401. Those public checks do not prove authorized production answers
or a real non-allowlisted account's 403. The separate
`sophia-production-verification-status.json` correctly marks authenticated
regression, production trust review, and the genuine-account 403 **NOT_RUN**.

`sophia-production-verification.html` is a pinned, credential-free browser
capture guide, **not a completed verification**. Publish the build above
before using it; its start/end build and corpus gates prevent recording
answers from a different build. A real authorized session and a separate
real non-allowlisted account are still needed. Never upload session data,
identities, or callback URLs with the captures.

GitHub sync settings and credentials were not changed. No GitHub push was
attempted as a test.
