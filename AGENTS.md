# Agent working notes

- The Python FastAPI/LangGraph backend is in `backend/`; Next.js and CopilotKit v2 are in `frontend/`.
- The CopilotKit runtime forwards AG-UI to the backend `/agent` endpoint. The model has read and proposal tools only. Refund approval is the explicit REST decision endpoint and always revalidates order state.
- `workspace.json` is the sole committed state for cases, orders, proposals, revisions and refunds. Copy `fixtures/starter.json` to reset. The backend uses a process-local lock and atomic file replacement; run one backend process only.
- The UI reads `/cases` and `/cases/{id}` repeatedly. It displays the committed backend state, including revisions and resolution, not a separate success animation.
- Use fictional data and a local backend. Do not expose the unauthenticated demo API on a public interface.
- No live model/UI proof or Firedrill integration has been performed. Add Firedrill only when the new interface is officially qualified.
