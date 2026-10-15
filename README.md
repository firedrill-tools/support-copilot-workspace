# Support copilot workspace

A browser-facing support workspace pairs a LangGraph/OpenAI agent with CopilotKit chat. The agent can inspect synthetic cases and save a refund proposal. A support operator approves or rejects the proposal in the main case view. Only that explicit decision updates the order's refunded amount and the refund ledger. The view polls the backend's committed case state, so the displayed result agrees with the records.

## Run locally

Requires Python 3.12, Node.js 20+, `uv`, npm and an OpenAI API key for chat. In one terminal:

```sh
cp fixtures/starter.json workspace.json
cd backend
uv sync --dev
OPENAI_API_KEY=... uv run support-workspace-api
```

In a second terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open `http://localhost:3000`. The API binds `127.0.0.1:8123`; the Next.js runtime forwards CopilotKit chat to its `/agent` AG-UI endpoint. The frontend fetches case records directly from that local API. Without an OpenAI key the backend fails at startup rather than showing canned agent responses. The self-hosted CopilotKit path does not need an Intelligence project key; optional managed threads and inspector features are outside this example.

Copy the fixture to a new `workspace.json` to reset. One backend process owns the file; the lock is process-local and does not support multiple server workers. The API has no user authentication and is for local demonstration only. No real refund processor or customer mailbox is connected.

## Verification and limits

Run `cd backend && uv run pytest` and `cd frontend && npm run typecheck && npm run build`. Backend tests cover proposal without payment change, approval, rejection, stale revisions and ineligible orders. `scenarios/README.md` lists model/UI cases still to run with a provider key. No live model call or end-to-end chat proof has been made here. The Firedrill integration will use the new official interface after it is released and qualified. No public license has been selected.
