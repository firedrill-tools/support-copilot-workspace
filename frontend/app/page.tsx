"use client";

import { CopilotChat } from "@copilotkit/react-core/v2";
import { useCallback, useEffect, useState } from "react";

type Proposal = { amount_cents: number; currency: string; reason: string } | null;
type SupportCase = {
  id: string; customer: string; email: string; subject: string; message: string;
  order_id: string; status: string; revision: number; proposal: Proposal;
  resolution: Record<string, unknown> | null;
};
type Order = { id: string; total_cents: number; paid_cents: number; refunded_cents: number; currency: string; status: string };
type Detail = { case: SupportCase; order: Order; refunds: Array<{ id: string; amount_cents: number }> };
const api = process.env.NEXT_PUBLIC_SUPPORT_API_URL || "http://localhost:8123";

function money(cents: number, currency = "USD") {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(cents / 100);
}

export default function Page() {
  const [cases, setCases] = useState<SupportCase[]>([]);
  const [selectedId, setSelectedId] = useState("case-104");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [listResponse, detailResponse] = await Promise.all([
        fetch(`${api}/cases`, { cache: "no-store" }),
        fetch(`${api}/cases/${selectedId}`, { cache: "no-store" }),
      ]);
      if (!listResponse.ok || !detailResponse.ok) throw new Error("Workspace API is unavailable");
      setCases(await listResponse.json());
      setDetail(await detailResponse.json());
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load workspace");
    }
  }, [selectedId]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => window.clearInterval(timer);
  }, [refresh]);

  async function decide(decision: "approve" | "reject") {
    if (!detail) return;
    setBusy(true);
    try {
      const response = await fetch(`${api}/cases/${detail.case.id}/decision`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, revision: detail.case.revision }),
      });
      if (!response.ok) {
        const problem = await response.json();
        throw new Error(problem.detail || "Decision failed");
      }
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Decision failed");
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  const current = detail?.case;
  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="wordmark"><span className="wordmark-square" />SUPPORT DESK</div>
        <div className="topbar-center">Case workspace <span className="topbar-divider">/</span> October 2026</div>
        <span className="environment">SYNTHETIC DATA</span>
      </header>

      <div className="workspace-grid">
        <aside className="case-rail">
          <div className="eyebrow">WORK QUEUE <span>{cases.length.toString().padStart(2, "0")}</span></div>
          <h1>Cases</h1>
          <p className="rail-intro">Review the record before approving any payment change.</p>
          <div className="case-list">
            {cases.map((item) => (
              <button key={item.id} className={`case-item ${item.id === selectedId ? "selected" : ""}`}
                onClick={() => setSelectedId(item.id)}>
                <span className="case-item-top"><span>{item.id.toUpperCase()}</span><span className={`status-dot ${item.status}`} /></span>
                <strong>{item.subject}</strong>
                <small>{item.customer}</small>
              </button>
            ))}
          </div>
          <div className="rail-footer">Local workspace · one operator at a time</div>
        </aside>

        <section className="case-main">
          {error && <div className="error-banner" role="alert">{error}</div>}
          {!detail ? <div className="empty-state">Loading case record…</div> : <>
            <div className="case-heading">
              <div className="eyebrow">CASE FILE / {current?.id.toUpperCase()}</div>
              <div className="title-row"><h2>{current?.subject}</h2><span className={`status-badge ${current?.status}`}>{current?.status}</span></div>
              <p>{current?.customer} <span className="separator">/</span> {current?.email}</p>
            </div>

            <div className="section-label">CUSTOMER REQUEST</div>
            <blockquote>{current?.message}</blockquote>

            <div className="record-grid">
              <div className="record-card">
                <div className="section-label">ORDER RECORD</div>
                <strong>{detail.order.id}</strong>
                <div className="record-line"><span>Status</span><span>{detail.order.status}</span></div>
                <div className="record-line"><span>Captured</span><span>{money(detail.order.paid_cents, detail.order.currency)}</span></div>
                <div className="record-line"><span>Refunded</span><span>{money(detail.order.refunded_cents, detail.order.currency)}</span></div>
              </div>
              <div className="record-card proposal-card">
                <div className="section-label">COPILOT PROPOSAL</div>
                {current?.proposal ? <>
                  <strong>{money(current.proposal.amount_cents, current.proposal.currency)}</strong>
                  <p>{current.proposal.reason}</p>
                </> : <p className="muted">No proposal yet. Ask the copilot to inspect this case.</p>}
              </div>
            </div>

            <div className="decision-area">
              <div><div className="section-label">OPERATOR DECISION</div>
                <p>The copilot can prepare a proposal. Only these controls change the refund record.</p></div>
              <div className="decision-actions">
                <button className="secondary-button" disabled={!current?.proposal || current.status !== "open" || busy}
                  onClick={() => void decide("reject")}>Reject proposal</button>
                <button className="primary-button" disabled={!current?.proposal || current.status !== "open" || busy}
                  onClick={() => void decide("approve")}>Approve refund</button>
              </div>
            </div>
            {current?.resolution && <div className="resolution"><span className="section-label">COMMITTED RESULT</span>
              <p>{current.status === "refunded" ? `Refund ${String(current.resolution.id)} recorded for ${money(Number(current.resolution.amount_cents), detail.order.currency)}.` : "Proposal rejected. No refund was recorded."}</p>
            </div>}
          </>}
        </section>

        <aside className="copilot-panel">
          <div className="copilot-header"><span className="eyebrow">ASSISTANT</span><h2>Case copilot</h2>
            <p>Ask it to inspect a case and prepare a proposal. Check the record before approving.</p></div>
          <div className="chat-wrap"><CopilotChat agentId="support_agent" className="chat" /></div>
        </aside>
      </div>
    </main>
  );
}
