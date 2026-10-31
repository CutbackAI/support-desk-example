# Example Support Desk

A small, independent Python application for understanding what Cutback observes.

A ticket arrives. One native OpenAI SDK call assigns it to **access**, **billing** or **incident**. Open the app, try a ticket, connect a local collector, then inspect the recorded calls. The business application works without Cutback.

**Every model response is a local fixture. No provider account, API key or paid inference is needed.** Token counts are fixed demonstration values. No result here establishes real model quality, customer savings or an invoice charge.

## 1. Run the application

Install Python 3.11+, Git and [uv](https://docs.astral.sh/uv/getting-started/installation/), then run:

```sh
git clone https://github.com/CutbackAI/support-desk-example.git
cd support-desk-example
uv sync --locked
uv run support-desk
```

Open **http://127.0.0.1:8010**. Choose **Duplicate charge**, then **Route with local fixture**. The result should be **Billing queue**. Choose **Missing usage**: the route remains billing, but both token counts become **Unknown**.

Press Ctrl+C in the terminal to stop the application.

## 2. Run the application checks

```sh
uv run pytest -q
```

The checks cover expected ticket routes, missing usage, input bounds and a deliberately bad token-cap alternative. The fixture returns incorrect labels when `max_output_tokens` is reduced to 16 or less. Changing the business call to that cap makes the ordinary ticket checks fail. This illustrates why an application check must accompany an optimization; it does not predict a real model's response to a token cap.

## 3. Connect Cutback locally

Start Docker Desktop. The collector uses a labelled local PostgreSQL container and persistent volume; the model transport remains local. The optional dependency is pinned to an unreleased public Cutback source commit that includes Python package workflow attribution. It is separate from the currently published PyPI build; this example is under qualification.

```sh
uv run --extra cutback cutback scan .
uv run --extra cutback python -m example_supportdesk.local prepare
uv run --extra cutback python -m example_supportdesk.local serve
```

`prepare` starts the collector on **127.0.0.1:8091**, uploads the parse-only inventory, writes an exact source map and creates separate ingest/viewer keys that expire after one day. Prompt/content capture is disabled. Credentials stay in ignored `.cutback/` files and are never printed. Observation writes use the ingest key; report reads use the viewer key. The application receives those two scoped keys and no collector-admin key. The browser receives neither key.

Open **http://127.0.0.1:8010** again. The footer should say observation is enabled. Route several tickets, including **Missing usage**, then select **Refresh collector report**. **What reached Cutback?** shows actual collected calls and unknown complete cost. For the full report, in a second terminal at the repository root:

```sh
uv run --extra cutback python -m example_supportdesk.local report
```

Read `report.summary.observed_requests`, `missing_usage_count` and `known_modeled_cost_subtotal_usd`. A missing-usage call keeps the complete `modeled_cost_usd` **null**, even when some other calls have known modeled subtotals. `actual_billed_cost_usd`, population coverage and semantic quality remain unverified. The report explicitly filters **simulation** traffic.

The pipeline you just ran is:

```text
your Python source → offline scanner → exact source map
native SDK call → metadata observer → HTTP collector → PostgreSQL → usage report
```

After editing application source, stop the application and run `prepare` again before `serve`. A stale source map must not claim an old identity. If setup stops partway through a credential write, it retains an uncertain phase and refuses to mint replacements automatically. Inspect the owned project's key list/revoke uncertain keys before deliberately repairing the local connection; do not erase the journal to bypass the stop. Expired keys require explicit reauthorization.

Stop the application with Ctrl+C, then stop the owned collector:

```sh
uv run --extra cutback python -m example_supportdesk.local down
```

The database volume and ignored workspace remain available for the next run. This command does not delete your stored metadata.

To verify the collector journey automatically, stop the interactive application and run:

```sh
uv run --extra cutback python scripts/check_collector.py
```

This makes two local fixture calls and checks their HTTP delivery, PostgreSQL report, scanner workflow identity, unknown usage and metadata privacy. It leaves the owned collector running for inspection. The repository CI additionally runs desktop/mobile browser and accessibility checks against the same application. For browser checks locally, install Node.js 24+, run `npm ci --ignore-scripts` and `npx playwright install chromium`, start the application, then run `npm run test:browser` in a second terminal.

## What is where?

| File | Purpose |
| --- | --- |
| `src/example_supportdesk/business.py` | The single native SDK request and application model/output-cap choices |
| `src/example_supportdesk/fixture_provider.py` | Closed local transport, synthetic usage and deliberately bad alternative |
| `src/example_supportdesk/web.py` | Ticket API and small browser interface |
| `src/example_supportdesk/observability.py` | Optional metadata-only observation and bounded delivery counters |
| `src/example_supportdesk/local.py` | Owned local collector, credentials, source map and report commands |
| `tests/test_application.py` | Application-owned behavioral checks |

## Let an agent inspect it

Give an agent this prompt from this repository:

> Read README.md and AGENTS.md. Run the offline application checks and Cutback scanner. Explain the single workflow, its current evidence and its unknowns in plain English. If Docker is available, run the metadata-only local collector walkthrough and verify the report. Do not call a model API, enable content capture, claim real savings, or weaken application tests. Propose any code change as a reviewable diff and run the original application checks before and after it.

For authorized evaluation, approvals and source-change gates beyond this introductory walkthrough, continue with [Cutback's application-agent guide](https://github.com/CutbackAI/cutback/blob/main/docs/agent-workflow.md). This repository is intentionally a consumer application, not another collector implementation.

## License

Apache-2.0. See [LICENSE](LICENSE).
