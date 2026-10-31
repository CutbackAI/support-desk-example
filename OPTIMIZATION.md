# Follow a source change through Cutback

This lesson runs a complete source optimization loop against the independent
support application. All responses come from the checked-in HTTP fixture. No
provider account, real API key, paid inference or deployment is involved.

Run from a clean clone of this repository. Keep the three public inputs unchanged:
`business.py`, `fixture_provider.py` and `fixtures/tickets.jsonl`. The command
checks their exact SHA-256 digests before it can import the provider fixture or
upload cases. Edited data is refused. This lesson is deliberately restricted to
this public synthetic application; it is not an integration command for your own
application.

Start Docker Desktop, stop the interactive support application, then run:

```sh
uv run --extra cutback python -m example_supportdesk.optimize_demo run
```

The optional Cutback source pin must include the native fixture execution
contract. The command refuses an older installed version before starting the
collector. The feature and dependency pin are under qualification.

The command performs these steps:

1. Scan the actual application and select its web ticket workflow. The scanner
   parses source without importing it.
2. Start the owned local collector with encrypted synthetic case storage enabled.
   An existing metadata-only collector is stopped and restarted using the same
   owned database and encryption key. Existing metadata is retained. Credentials
   remain in ignored private files; no key is sent to the browser.
3. Import 72 independently labelled synthetic cases, keeping related variants in
   the same dataset split. Automatically freeze the supported model/output-cap
   search. The maximum modeled budget is $5/1,000 requests per stage; actual
   external model requests are zero.
   Every observed label must match, with at least six cases and three independent
   groups required per evaluation split. This is an exact sample gate, not a
   population-quality claim. The separate application checks require every one
   of the 72 golden cases to match exactly. A perfect observed sample cannot
   establish a 100% population lower confidence bound.
4. Execute the saved validation run using the native SDK and a closed
   `httpx.MockTransport`, through the ordinary PostgreSQL worker, reservations,
   evidence and quality gates. A normal live worker refuses these fixture plans.
5. Select a cheaper candidate only if its recorded quality and complete usage
   gates pass. The deliberately bad 16-token alternative must fail quality.
6. Freeze that one candidate for a separate confirmation on unused test groups.
   Validation alone cannot produce the source proposal.
7. Generate the actual source diff and rollback diff. Check the proposal in two
   local Git worktrees, with all application contract tests run on both the
   original and proposed trees using Cutback's application-check runner.
8. Apply the rollback in the disposable review worktree and verify byte-for-byte
   restoration, then restore the candidate for review. The original application
   source is unchanged. No patch is accepted or deployed automatically.

Inspect the result:

```sh
uv run --extra cutback python -m example_supportdesk.optimize_demo report
git -C .cutback/example-optimization/proposed show --stat HEAD
git -C .cutback/example-optimization/proposed show HEAD
```

The JSON lists validation/confirmation run IDs, candidates and quality gates,
modeled fixture cost differences, the application-check receipt and exact rollback
result. The generated diff is in
`.cutback/example-optimization/proposal.json`; the local proposed source is in
`.cutback/example-optimization/proposed`. Review those files locally. They are
ignored publication inputs and never need to be committed.

Running the command again after completion reads the same saved result and
creates no new model run. An interrupted preparation reuses its saved identity;
an uncertain approval, crashed/running/blocked operation, changed source identity
or partially created review worktree stops for inspection. Do not erase the
journal to bypass a stop. Application-check receipts cover tracked files and the
declared commands in a minimal environment, not an operating-system sandbox.

All fixture token counts and model behavior are scripted. Passing these gates
demonstrates the mechanics; it does not establish real model quality, a provider
invoice, production savings or a complete external-consumer inventory. The real
quality gate remains closed. Whole-application and hosting costs remain unknown.

Stop the owned collector when finished:

```sh
uv run --extra cutback python -m example_supportdesk.local down
```

It preserves the database volume and encrypted synthetic artifacts. To return to
the metadata-only observation lesson, run its `prepare` command after stopping
the collector. That restarts it with payload capture disabled.
