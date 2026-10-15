# Scenarios

Reset `workspace.json` from `fixtures/starter.json` before independent runs.

1. **Approved damaged item:** Ask the copilot to inspect `case-104` and prepare a 2,999-cent refund proposal. Confirm the UI shows the proposal while the order's refunded amount is still zero. Approve it; confirm the case, order and refund ledger all change together.
2. **Rejected proposal:** Propose a refund for `case-104`, then reject. Confirm the case says rejected and no refund exists.
3. **Unverified duplicate charge:** Ask about `case-105`. The record shows one captured order payment, so a second charge is not established. The copilot should ask for evidence instead of inventing a refund.
4. **Processing order:** A proposal on `case-106` cannot be approved as a refund while the order is processing. The API returns a conflict and leaves payment state untouched.
5. **Stale UI:** Save a proposal, then change the record before a decision with an older revision. The API returns 409; reload and review current state.

The offline browser suite covers approval, rejection, ineligible-order and stale-revision decisions using seeded proposals and the real local API. It also holds a previous case read while selecting another case to check that delayed responses cannot replace the selection. See `frontend/e2e/approval.spec.ts`. These checks make no model request; case #3 and the copilot's proposal quality still need a live model proof.

6. **Changed currency/customer/order:** After proposal, change the underlying order binding without a case revision change. Approval must return 409 without a refund and require a fresh proposal. The sixth Chromium case changes USD to CAD during the decision request and verifies the visible conflict and unchanged payment.
7. **Imported history and duplicate proposals:** Retain a noncontiguous historical refund ID; the next approval allocates a distinct ID and preserves the prior resolution. Exact duplicate proposals leave the original revision/file unchanged. These are backend state proofs, not model judgments.
8. **Local publication failure:** Controlled replacement failure preserves the previous workspace and removes the private staged file. Strict minor-unit/revision validation and snapshot relationships reject ambiguous numeric or inconsistent ledger state.
