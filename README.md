# Support copilot workspace with CopilotKit, LangGraph and Next.js

A support workspace pairs a LangGraph/OpenAI agent with CopilotKit chat. The copilot reads fictional cases/orders and can save a refund proposal. Only the operator's approval endpoint changes the order and refund ledger. The browser polls committed records, so chat output and actual financial state can be inspected separately.

## Simulate with Firedrill

[Firedrill](https://firedrill.run/) is a simulation platform for AI agents.
Start from this repository’s root:

```sh
npx firedrill-run init
```

Sign in and choose your project, then follow the [simulation run guide](firedrill/README.md)
for application dependencies, a preview and the reviewed scenarios. Your agent runs
locally or in your CI; model credentials stay separate from Firedrill sign-in.
The included recipes record outcomes without an automatic quality score or CI gate.

## Run one case

Requires Python 3.12, Node.js 24 (used in CI), `uv` and npm. Listing/initialization need no credentials and make no model calls.

```sh
cd backend
uv sync --dev --locked
uv run support-workspace-api --list-cases
uv run support-workspace-api --init-case busy --workspace ../.runs/busy.json
OPENAI_API_KEY=... uv run support-workspace-api --workspace ../.runs/busy.json
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open `http://localhost:3000`, select `case-104`, and ask the copilot to inspect it and prepare a proposal if justified. Review the record before approving. The API binds `127.0.0.1:8123`; frontend dev/start scripts also bind loopback. The self-hosted CopilotKit runtime forwards chat to `/agent` through AG-UI. No Intelligence project key is required; managed threads/inspector features are outside this example. Missing OpenAI credentials fail startup without a canned model fallback.

`OPENAI_MODEL` defaults to `gpt-6.1-sol`; availability and quality remain to be qualified live. `OPENAI_BASE_URL` can select HTTPS or a loopback HTTP test endpoint. `SUPPORT_WORKSPACE_FILE` selects the JSON path when `--workspace` is omitted. `NEXT_PUBLIC_SUPPORT_API_URL` selects the browser's case API, `SUPPORT_AGENT_URL` selects its server-side AG-UI destination, and `SUPPORT_WEB_ORIGIN` sets the API's allowed origin. Set public frontend values **before building** Next.js. The unauthenticated application is a local, one-operator demonstration; it has no real payment processor, mailbox or hosted customer records.

## Proposal and approval

A proposal binds the order ID, customer email and currency observed when created. Approval rechecks that binding, delivery status, identity, current revision and remaining captured balance. Changed/unknown bindings require a fresh proposal; legacy unbound proposals can still be rejected. Exact duplicate proposals preserve the displayed revision. Amounts/revisions must be integers: boolean/fractional inputs and extra decision fields are rejected. Refund IDs preserve noncontiguous imported history.

A proposal never issues a refund. Chat failure can follow a committed proposal, so inspect current state before retrying. Earlier effects are not rolled back. Approval/rejection publishes the case, order and ledger in one private staged JSON replacement with flush/fsync and failure cleanup. Snapshot validation checks unique identities, captured/refunded amounts and committed resolution relationships. Fixtures use integer USD cents; the CAD correction is a deliberate rejection situation, not currency conversion.

## Runtime, completion and evidence

The pinned path is LangChain `1.4.6` / `langchain-openai==1.7.2` / LangGraph with CopilotKit `0.1.96` / AG-UI LangGraph `0.0.47` and native OpenAI Python `3.31.0` / httpx2 `2.13.1`. Actual Chat Completions JSON/SSE passes through these SDKs. Calls are bounded to eight per chat run, 30-second HTTP timeouts, no automatic retries/redirects, 4,096 output tokens, and disabled model cache/storage.

Completion middleware rejects nonfinal, refused, malformed or parallel tool output **before dispatch** on synchronous and asynchronous paths. The managed stream must also have an observed `[DONE]` marker. Provisional text/tool fragments can appear before validation; `RUN_FINISHED` and committed records determine completion. Errors emit `RUN_ERROR`, and the browser displays a persistent failure until a new run starts. Input is gated on agent discovery. Later turns remove rejected unanswered calls from provider context while retaining the original evidence.

The workspace stores two observation collections:

- `provider_observations`: actual HTTP attempt, caller thread/run IDs, requested/returned model, response/request IDs, input/state hashes, bounded raw JSON/SSE, completion/transport errors and provider-reported usage.
- `agent_observations`: returned SDK message/usage, acceptance reason and correlated provider observation. SDK defaults are kept separate from raw provider counters.

Query `GET /evidence/{thread_id}?run_id=...` to inspect a run or omit `run_id` for its thread. The response counts HTTP attempts and aggregates usage only when every attempt has complete nonnegative integer counters. Missing/partial usage is unknown, distinct from reported zero. Failed attempts can retain reported usage without being accepted. Cost is always unknown. [OpenAI's streaming contract](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events) allows an interrupted stream to lose its final usage chunk. Capture is limited to 1 MiB per response; truncation/decoding problems are explicit and cannot qualify a tool call. Compressed or fragmented SSE is decoded through HTTPX without replaying bytes when the SDK drains HTTP/1.1.

ASGI lifespan owns both native SDK/HTTP clients and its in-memory checkpointer. Shutdown and startup failure close constructed clients. Each consumed, failed or cancelled HTTP response is closed; the running service retains its client pool for later turns. Shutdown deletes owned conversation checkpoints while business state and durable observations remain. Restart clears conversation memory, not the workspace. `AgentRuntime.invoke` / `ainvoke` provide callable entrypoints with explicit thread/run IDs inside an async runtime context. `build_agent` accepts caller-owned model/checkpointer dependencies and closes neither.

Chat runs are serialized within one ASGI runtime, including across threads; REST decisions retain revision/locking checks. **Run one backend process/worker per workspace** and serialize direct callable invocations. Atomic file replacement and process-local locks do not coordinate other processes. A disconnected observer or closed client does not prove provider-side generation/billing stopped. There is no background job/scheduler or external-state rollback.

## Dataset 1.0.0

`northstar-support-workspace` has eight hash-bound snapshots across all four profiles:

| Profile | Cases | Starting conditions |
| --- | --- | --- |
| Starter | `starter` | Three cases/orders: damage, unverified duplicate charge and replacement update |
| Busy | `busy` | Eighteen cases/orders, two prior refunds, rejected work and pending proposals |
| Ambiguous | `identity-conflict`, `investigate-charge` | Same name with mismatched identity; customer requests investigation before a refund |
| Boundary | `changed-currency`, `exhausted-balance`, `already-refunded`, `hostile-message` | Stale USD proposal after CAD correction, prior linked full refund, completed case or malicious customer instructions |

The manifest binds exact state bytes, selected case and a suggested prompt. Listing validates all digests, paths, identities and relationships. Initialization exclusively creates a private file and refuses overwrite. Historical receipts/proposals are explicitly fictional business state, never invented model executions. No SDK/provider observations are seeded. The agent reads business records; the manifest, dataset labels and scenario criteria do not enter tool/model context.

Choose a fresh path for each independent case/trial. Reset covers local JSON only; stopping/restarting the owner also clears volatile conversations. `scripts/build_fixtures.py` reproduces every JSON byte. The backend's wheel and self-contained source archive bundle the same data; their CLI is verified outside the checkout without keys. Initial provider observations record the actual starting-file hash, business-state hash and declared dataset; modified state remains distinguishable from qualified original bytes.

## Verification

```sh
cd backend
uv run --no-sync pytest -q
uv build
uv run --no-sync python ../scripts/check_package.py
cd ../frontend
npm run typecheck
npm run test:e2e
NEXT_PUBLIC_SUPPORT_API_URL=http://127.0.0.1:38123 COPILOTKIT_TELEMETRY_DISABLED=true npm run build
npm run test:chat
```

Install Chromium first with `npx playwright install chromium`, and keep `uv` on PATH. Run one browser suite at a time. Both suites own API port 38123 and UI port 3300, refuse existing listeners, reset ignored `.e2e` state between cases and stop owned servers. CI uses the same gates and retains only synthetic browser artifacts for seven days.

**63 backend checks and eight Chromium cases passed locally.** Six browser cases use seeded proposals and the real decision API without a model endpoint. Two additional cases run the **production-built browser → CopilotKit → AG-UI → actual LangChain/OpenAI SDK → tools/API** path with test-only controlled model HTTP: read/proposal/approval, plus provider/nonfinal failures followed by recovery. They exposed and fixed early submission before discovery and invisible errors. A real approval screenshot is retained in ignored test output.

Backend checks cover JSON/SSE completion, missing/partial/zero usage, compressed fragmentation, cancellation, provider failure after a proposal, client/checkpoint cleanup, concurrent chat serialization, caller ownership, financial guards, all eight datasets and preservation of unrelated busy history. The build verifies a wheel produced from its source archive, then exercises both artifacts outside the checkout. The pinned AG-UI adapter currently emits a third-party deprecation warning for its LangGraph schema call; the exercised interface still passes. The frontend pins KaTeX `0.18.2` with matching CSS, addressing the [inherited trust-setting advisory](https://github.com/advisories/GHSA-238p-pmpm-9mq7). Source HTML is sanitized before math rendering, with URL hardening retained. The production chat case verifies a styled fraction and removal of script/JavaScript-link output. Full npm audit is clean at this snapshot.

These controlled HTTP responses are not paid model judgments or billing evidence. Live factuality, ambiguity handling and injection resistance remain unmeasured. [Scenario briefs](scenarios/README.md) keep semantic criteria separate from exact financial checks. Live provider access, authenticated persisted Firedrill runs and publication/license choices remain external gates. The included [Firedrill integration](firedrill/README.md) uses the actual backend and AG-UI runtime.

Related applications: [Firedrill example catalog](https://github.com/firedrill-tools/firedrill-example-catalog). Product/setup: [Firedrill](https://firedrill.run/) and [official developer documentation](https://docs.firedrill.run/), matched to the qualified release.

## Current Firedrill connection — 2026-10-19

The [agent-first integration](firedrill/README.md) exact-pins CLI/SDK 2.2.2 and invokes the real backend API and AG-UI agent through the local ASGI callable seam. Chat uses the normal owned provider runtime; explicit state inspection needs no model. Operator approvals remain a separate API/UI action. Earlier pending-release notes are historical; authenticated saved runs and live model proof remain pending.
