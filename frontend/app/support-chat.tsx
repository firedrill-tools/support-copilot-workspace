"use client";

import { CopilotChat, useAgent } from "@copilotkit/react-core/v2";
import { useEffect, useState } from "react";

export function SupportChat() {
  const { agent, isReady } = useAgent({ agentId: "support_agent" });
  const [error, setError] = useState("");
  useEffect(() => {
    const subscription = agent.subscribe({ onRunInitialized: () => { setError(""); } });
    return () => subscription.unsubscribe();
  }, [agent]);
  return <>
    {!isReady && <p role="status">Connecting to the support copilot…</p>}
    {error && <p className="error-banner" role="alert">{error}</p>}
    {isReady && <CopilotChat agentId="support_agent" className="chat" onError={() => {
      setError("The support copilot could not complete this request. Review the case and try again.");
    }} />}
  </>;
}
