# Agent working notes

- The Python FastAPI/LangGraph backend is in `backend/`; Next.js and CopilotKit v2 are in `frontend/`.
- The CopilotKit runtime forwards AG-UI to the backend `/agent` endpoint. The model has read and proposal tools only. Refund approval is the explicit REST decision endpoint and always revalidates order state.
- `workspace.json` is the sole committed state for cases, orders, proposals, revisions and refunds. Copy `fixtures/starter.json` to reset. The backend uses a process-local lock and atomic file replacement; run one backend process only.
- The UI reads `/cases` and `/cases/{id}` repeatedly. It displays the committed backend state, including revisions and resolution, not a separate success animation.
- Keep decision errors visible after a successful record refresh. Abort superseded reads and prevent a response for the previous selection from replacing the current case. Operator decisions still carry the exact displayed revision.
- Browser proof: after backend `uv sync --dev --locked`, run `cd frontend && npm ci && npx playwright install chromium && npm run test:e2e` with `uv` on PATH. Playwright owns API port 38123 and UI port 3300, refuses existing listeners, and stops both processes. The test-only `backend/tests/browser_api.py` serves the real decision API without a model endpoint; starting proposals are seeded into ignored `frontend/.e2e/workspace.json`. Cases run serially and reset between tests. Artifacts stay under ignored `frontend/test-results/` and CI's synthetic evidence artifact.
- Use fictional data and a local backend. Do not expose the unauthenticated demo API on a public interface.
- Seventeen backend and six local Chromium approval/state checks passed. No live model chat or Firedrill integration has been performed. Add Firedrill only when the new interface is officially qualified.

- Proposals bind exact order/customer/currency. Approval must recheck that binding and current eligibility/balance; unknown legacy scope needs a fresh proposal. Exact duplicate proposals preserve revisions. Reject fractional/boolean amounts/revisions; imported refund IDs must remain unique. Private atomic publication must clean its stage on failure. The snapshot schema preserves committed refund/resolution relationships.
