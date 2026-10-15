"use client";

import { CopilotChat, CopilotChatAssistantMessage, useAgent } from "@copilotkit/react-core/v2";
import { useEffect, useState, type ComponentProps } from "react";
import { defaultRehypePlugins } from "streamdown";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import rehypeKatex from "rehype-katex";

// Sanitize source HTML first, then render math with matching patched CSS and
// retain Streamdown's URL hardening for the resulting output.
const markdownPlugins: ComponentProps<typeof CopilotChatAssistantMessage.MarkdownRenderer>["rehypePlugins"] = [
  defaultRehypePlugins.raw,
  [rehypeSanitize, { ...defaultSchema, attributes: { ...defaultSchema.attributes,
    code: [["className", /^language-./, "math-inline", "math-display"]] } }],
  [rehypeKatex, { trust: false, errorColor: "var(--color-muted-foreground)" }],
  defaultRehypePlugins.harden,
];

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
    {isReady && <CopilotChat agentId="support_agent" className="chat"
      messageView={{ assistantMessage: { markdownRenderer: { rehypePlugins: markdownPlugins } } }} onError={() => {
      setError("The support copilot could not complete this request. Review the case and try again.");
    }} />}
  </>;
}
