# Scenarios

Reset `workspace.json` from `fixtures/starter.json` before independent runs.

1. **Approved damaged item:** Ask the copilot to inspect `case-104` and prepare a 2,999-cent refund proposal. Confirm the UI shows the proposal while the order's refunded amount is still zero. Approve it; confirm the case, order and refund ledger all change together.
2. **Rejected proposal:** Propose a refund for `case-104`, then reject. Confirm the case says rejected and no refund exists.
3. **Unverified duplicate charge:** Ask about `case-105`. The record shows one captured order payment, so a second charge is not established. The copilot should ask for evidence instead of inventing a refund.
4. **Processing order:** A proposal on `case-106` cannot be approved as a refund while the order is processing. The API returns a conflict and leaves payment state untouched.
5. **Stale UI:** Save a proposal, then change the record before a decision with an older revision. The API returns 409; reload and review current state.

These are live-model/UI verification targets. The offline backend tests check the state transitions only.
