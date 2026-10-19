# Firedrill agent-first integration

This optional toolchain exact-pins released CLI and TypeScript SDK **2.2.2**, verified October 19, 2026. Node 22+ is required. The application and frontend retain their original locked dependencies. A supported command target invokes the actual backend factory/router through production HTTPX ASGI transport; it does not inject a model/runtime factory or serve a hosted endpoint.

## Prepare

From the repository root:

```sh
cd backend
uv sync --locked --dev
cd ..
npm ci --prefix firedrill --ignore-scripts --no-audit --no-fund
npm test --prefix firedrill
firedrill_cli=firedrill/node_modules/@firedrill-run/cli/bin/firedrill.mjs
node "$firedrill_cli" validate firedrill/scenario.json --json --non-interactive
```

Keep `uv` on PATH. For a self-contained backend source distribution, run `uv sync --locked --dev` at the archive's project root instead; the adapter supports that layout too. Reviewed integration files and the backend lock are included individually, with installed Node dependencies and private state excluded.

## Select scope and execute

Authorize/select the actual project/environment with `node "$firedrill_cli" init` in a human terminal. Automation supplies `FIREDRILL_TOKEN`, `FIREDRILL_PROJECT_ID` and `FIREDRILL_ENVIRONMENT_ID` through its secret store. Native chat independently requires `OPENAI_API_KEY` and an enabled `OPENAI_MODEL` or recipe `configuration.parameters.model`. Keep credentials out of recipes and Git.

With an authorized model budget:

```sh
node firedrill/simulate.mjs --preview
node "$firedrill_cli" simulate firedrill/scenario.json --scenario starter-chat --json --non-interactive
```

The adapter initializes a fresh hash-bound workspace, constructs the normal `AgentRuntime`, sends the application's real AG-UI request, reads actual stream events, and inspects the selected case and correlated evidence. Accepted chat completion requires the exact inner thread/run `RUN_FINISHED`, no `RUN_ERROR`, and successful HTTP. A returned HTTP response alone cannot finish a chat.

Three scenarios cover ordinary chat, conflicting identity and explicit busy-state inspection, with one repetition and concurrency one. Inspection uses the API's existing `include_agent=False` mode and makes no model request; it is not a model-quality proof. `node firedrill/simulate.mjs` executes the same full recipe through the SDK. Existing model-call/output/deadline bounds apply, not billing guarantees.

The model retains read/proposal tools only. The adapter exposes no operator decision action and never approves a refund. Real operator approval remains a separate revision-bound API/UI operation. Inspect actual state and proposal provenance independently of model prose. This API seam does not replace or claim to exercise the frontend; the existing production browser/chat CI remains in place.

Each invocation retains `.runs/firedrill/attempt-*`, its private workspace, outer execution mapping in `invocation.json`, prepared inner AG-UI IDs in `application-run.json`, and actual raw `ag-ui.sse` bytes when a chat response exists. New attempts never reset old state. Output contains actual API/events/evidence under `application` and local paths under `localState`; file paths are not uploaded artifacts. Runtime closure is reported from its actual owned lifecycle, not inferred from HTTP completion. Interrupted/failed work can retain proposals or evidence and must be inspected before retry.

The current command envelope is `2026-10-17-target-invocation.1` with ID-only scenario context. Controller/evaluation data and unsupported Tool bindings are rejected. Operator/CI credentials are removed before application dispatch. No Firedrill synthetic Tool is required for this local data seam. State reset does not erase provider retention/billing or imply remote cancellation/rollback.

## Operator MCP, recovery and CI

Configure remote OAuth MCP **https://mcp.firedrill.run/mcp** with the [host-specific setup](https://docs.firedrill.run/guides/coding-agents); no local MCP package is required. Host OAuth and local CLI/SDK login are separate. MCP prepares/queues/inspects; a local execution client runs the actual app. Attach an existing batch with `node firedrill/simulate.mjs --run BATCH_ID`.

Preserve operation IDs and private journals after uncertainty. Use `--resume OPERATION_ID` for the exact execution or `--result BATCH_ID` for a retained read; a fresh simulation is new work. The local identity files are locators, separate from SDK recovery authority. Runner exit codes preserve errors, pending work/assessment and optional gates. This observation-only recipe requests no grading or gate.

Ordinary CI is offline, including the existing real Chromium flows. Configure actual scope, protected credentials and budgets before using the [live CI generator](https://docs.firedrill.run/guides/ci). Authenticated persisted cases, live model quality/cost, hosted-network proof, publication and licensing remain separate gates. Controlled loopback provider responses/usage in tests are synthetic.

References: [SDK](https://docs.firedrill.run/sdk/typescript), [command targets](https://docs.firedrill.run/guides/callbacks), [operator MCP](https://docs.firedrill.run/guides/control-mcp).
