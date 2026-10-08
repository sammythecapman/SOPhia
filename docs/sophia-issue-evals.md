# SOPhia issue and evidence evals

Run from the project root against the running development preview:

```sh
uv run python scripts/run_sophia_evals.py
```

The default target is the development proxy at `http://localhost:80`. This
uses the existing development access behavior; it does not bypass production
authentication. The command calls the real retrieval and answer pipeline,
prints PASS/FAIL for each check, exits nonzero on failure, and saves the full
answer and checks in `outputs/sophia-issue-eval-results.json`. Model calls
occur only when collecting a new answer.

To reevaluate saved responses without model calls:

```sh
uv run python scripts/run_sophia_evals.py --response path/to/answer.json
```

The input can be a complete saved report or an object mapping case IDs to answers.
A raw API answer is accepted only with a single-case fixture file; it cannot be
reused for other questions. Missing saved answers fail instead of silently inheriting
another case's response. The report records fixture/evaluator hashes, request questions,
response hashes, timestamps, and the health endpoint's build SHA before and after.
Add cases to `tests/fixtures/sophia_issue_evals.json`, with a question, independently
labeled issue patterns, allowed supporting program tags, required query-expansion
terms, and an optional substance-framing pattern. Do not store credentials,
cookies, or private borrower facts in fixtures.

An explicit unsupported issue is an acceptable coverage result when its fixture
permits a gap. Supplied-fact checks still inspect the visible answer on that path;
they cannot pass by finding the fact only in the input fixture or rejected evidence.
These are structural grounding checks, not a substitute for a lender's
hand-review of whether the returned answer actually resolves the requested
issue. A report can pass all structural checks while every sub-answer is
unresolved; do not describe that as a legal-accuracy or demo pass.

## Program metadata

The normal DOCX ingest already calls the shared heading classifier. Program
scope is now explicit (`general`, `7a`, `504`, or the existing ESOP scope), and
product tags distinguish Standard 7(a), Small, SBA Express, Export Express,
EWCP, International Trade, CAPLines, MARC, and 504. Body cross-references do not
assign another program's scope. The runtime gate also infers heading metadata
so older rows cannot evade an Export Express exclusion.

No source text or embeddings need to change for this metadata-only correction.
Preview or apply the correction to the development corpus with its verified hash:

```sh
uv run python scripts/refresh_sophia_program_tags.py --sha256 <current-corpus-hash>
uv run python scripts/refresh_sophia_program_tags.py --sha256 <current-corpus-hash> --apply
```

This utility does not support running writes in a production environment.
Do not substitute a production connection string. It changes only program
metadata; it does not ingest, delete chunks, change the corpus hash, or re-embed.
Publishing remains a separate step.

## Results and review

Fixtures can include `forbidden_claims` with a label and regex for a reproduced
unsupported visible claim. The current live signed-agreement response fails
the consent-sufficiency guard; the saved report records that failure. A lexical
counterexample guard is not a complete legal entailment audit. See
`outputs/sophia-answer-review.md` for the remaining semantic and signer-coverage
defects before calling this build demo-ready.

The earlier single-case “14/14” claim was stale and is withdrawn. Read the current
case-by-case report rather than a historical total. The default fixture now includes
the three original questions plus variable-rate/signed agreement,
variable-rate/no agreement, and fixed-rate/signed agreement counterexamples.

The covenant legal-answer template has been removed. Stated facts come from
validated exact quotes of the user's question, and legal claims still require
operative source quotations and issue-specific application auditing.

See `outputs/sophia-answer-review.md` for the separate review of real answers.
Production proof belongs in captured authenticated results and a real-account
403 record. `outputs/sophia-production-verification-status.json` is explicitly
incomplete until those exist; the HTML file is only a capture guide.
