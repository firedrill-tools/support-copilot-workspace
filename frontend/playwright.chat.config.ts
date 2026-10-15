import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e-chat", outputDir: "test-results/chat", fullyParallel: false, workers: 1, retries: 0, timeout: 30000,
  use: { baseURL: "http://127.0.0.1:3300", viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure", screenshot: "only-on-failure" },
  webServer: [
    { command: "uv run --project ../backend --locked python ../backend/tests/browser_chat_api.py",
      url: "http://127.0.0.1:38123/cases", reuseExistingServer: false, timeout: 30000,
      env: { SUPPORT_WEB_ORIGIN: "http://127.0.0.1:3300", OPENAI_API_KEY: "synthetic-not-a-secret", OPENAI_MODEL: "gpt-6.1-sol",
        LANGSMITH_TRACING: "false", LANGCHAIN_TRACING_V2: "false" },
      gracefulShutdown: { signal: "SIGTERM", timeout: 3000 } },
    { command: "npm run start -- --port 3300",
      url: "http://127.0.0.1:3300", reuseExistingServer: false, timeout: 60000,
      env: { SUPPORT_AGENT_URL: "http://127.0.0.1:38123/agent", NEXT_TELEMETRY_DISABLED: "1", COPILOTKIT_TELEMETRY_DISABLED: "true" },
      gracefulShutdown: { signal: "SIGTERM", timeout: 3000 } },
  ],
});
