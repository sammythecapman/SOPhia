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

The input can be one raw API answer, or an object mapping case IDs to answers.
Add cases to `tests/fixtures/sophia_issue_evals.json`, with a question, independently
labeled issue patterns, allowed supporting program tags, required query-expansion
terms, and an optional substance-framing pattern. Do not store credentials,
cookies, or private borrower facts in fixtures.

An explicit unsupported issue is an acceptable coverage result. The quote check
is deliberately nonvacuous: a response with no applied citations fails that
check. These are structural grounding checks, not a substitute for a lender's
hand-review of legal interpretation and factual application.

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

## Results for the supplied deposit-account / rate-step-up case

The development live eval passed all 14 checks. The rate issue uses exact
operative spread-change and default-rate quotes, includes fact-specific
explanations, and preserves missing rate-structure and agreement facts.
The Preference issue is visibly **Not addressed by retrieved provisions**:
the system does not treat a retrieved definition alone as sufficient
prohibiting authority. Explicit gaps are accepted by the requested coverage
checks, and are not represented as established legal conclusions.

The accompanying Python suite passed 68 tests, and the generated API
contracts and SOPhia frontend passed TypeScript checking. The metadata
refresh checked 395 chunks and updated 341 program-tag records in
development; chunk text, embeddings, and corpus hash were unchanged.
Production authentication and deployment are not tested by this development
eval.
