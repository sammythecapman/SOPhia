# SOPhia answer review — 2026-10-08

**Scope:** Live development responses, not authenticated production proof or legal advice.
The final responses are saved in `sophia-issue-eval-results.json` and
`sophia-trust-development-answer.json`. They were captured against source SHA
`0fb0c4692cf529380827746e5fe812e42ea82b6f6fdf97a71d1093677d963183`
and source-content build SHA
`c3bbfe00f886711c40d97ddbbfe3b154e7f61f5b26b9206d937d7ca179a511c7`.
Eight fact-changing responses and the separate original trust response were
captured from the running API. The unchanged raw eight-case capture is saved
as `sophia-issue-eval-live-capture.json`. Its response hashes and questions were
preserved when rescored with the current evaluator, including recognition of
a source-cited guarantor table as a visible answer.

**Result: PARTIAL, NOT DEMO-READY.** Automated checks: **108/112**.
Four named-Trustor coverage checks fail. Hand review additionally finds an
own-quote alignment defect in the original trust answer. Thirteen of the
fifteen subanswers in the eight-case suite remain unresolved/not established.
Neither structural passes nor safely withheld answers establish legal accuracy.

## Fact-changing covenant questions

The six covenant questions produced eleven issue-specific subanswers. All
eleven now remain `not_established`; these are not complete legal resolutions.
The reproduced signed-consent overclaim is withheld by a source-logic gate
independent of the semantic auditor's yes/no approval.

- Unspecified rate/consent, 504 Preference, and $125,000 balance with specific
  SBA written consent: each has a saved real response. The contrast answer
  visibly preserves both the balance and consent; the balance is no longer
  inferred to be a $125,000 *loan*.
- Variable-rate with the Borrower's signed written agreement to this specific
  change, variable-rate with expressly no written agreement, and fixed-rate
  with a specific signed agreement: the responses retain each materially
  different rate/agreement fact rather than saying the facts did not establish
  them. The signed variable-rate response now explains: “The selected quotes
  state prerequisites or restrictions, not affirmative authority for the
  claimed permission. Meeting a necessary condition does not establish
  overall permissibility.” It visibly retains the signed agreement fact.
  It no longer calls that agreement sufficient authorization for the increase.

Earlier real failures remain useful counterexamples, not successful tests.
Verbatim excerpts of observed failures are retained in
`tests/fixtures/sophia_observed_failures.json`. No code-generated legal
conclusion is substituted for a rejected model answer. Broader permission
proof and useful resolution of these covenant issues remain unproven.

## Trust aggregation, development only

For two revocable trusts owning 12% and 8%, the visible aggregation answer
correctly uses **20% exactly**, not "exceeds 20%." The cited SOP 50 10 8.1
Guaranties passage (page 93) says: “When one or more trusts (revocable or
irrevocable) own, in the aggregate, 20% or more of the applicant, each trust
must provide an unlimited full guaranty.” The aggregation conclusion and
two trust guaranties are supported for the stated facts.

The separate original “who must sign” answer now includes the trustee's
execution duty and the Trustor's personal guaranty, citing the operative rule:
“In addition, when a trust guaranty is required, the Trustor must also
personally guarantee the loan.” Source-role output slots, quote bindings and
admission checks prevent a silently omitted role from counting as complete.
Rejected applications retain explicit unresolved source-role rows.

**Hand-review failure: own-quote alignment.** The application attached to the
ownership/aggregation quote also says “the trustee must execute the guaranty
on behalf of each trust.” That duty is stated in the separate trustee quote,
not the selected ownership quote. The yes/no auditor admitted the compound
application. Having the right paragraph elsewhere and covering all roles
does not fix this explanation-to-quote defect. Additional purpose statements
such as “adds an additional layer of security” also need source scrutiny.

The named-capacity counterexample supplies Person A/B for Trust A and Person
C/D for Trust B. Both signer subanswers remain explicitly unresolved, so
four checks requiring visible Trustor/personal-guaranty/Person B/Person D
conclusions fail. The facts are preserved; this is not missing user input.
The 12% + 6% counterexample correctly concludes **18% does not meet 20%**,
without claiming a blanket waiver of all guaranty obligations.

The final fact echo quotes only the declarative ownership premise, not the
user's question about whether ownership aggregates. That fact-label defect
was fixed and checked against this live response.

## Published-build verification

The historical public observations in the production status file showed
the correct corpus SHA, 395 chunks and an unsigned query's 401. They are not
a new verification of the currently published build. Those observations
do not prove authorized production answers or a genuine-account 403. The
`sophia-production-verification-status.json` correctly marks authenticated
regression, production trust review, and the genuine-account 403 **NOT_RUN**.

`sophia-production-verification.html` is a pinned, credential-free browser
capture guide, **not a completed verification**. It currently pins the
development build above, which is not yet demo-ready. After the remaining
legal defects are fixed, regenerate it for the approved build before
publication and genuine-account testing. Its start/end build and corpus
gates reject a different build. Never upload session data, identities, or
callback URLs with captures. No publication was performed in this work.

GitHub sync settings and credentials were not changed. No GitHub push was
attempted as a test.
