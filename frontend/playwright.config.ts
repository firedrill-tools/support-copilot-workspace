import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30000,
  use: {
    baseURL: "http://127.0.0.1:3300",
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "uv run --project ../backend --locked python ../backend/tests/browser_api.py",
      url: "http://127.0.0.1:38123/cases",
      env: { SUPPORT_WEB_ORIGIN: "http://127.0.0.1:3300", OPENAI_API_KEY: "" },
      reuseExistingServer: false,
      timeout: 30000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 3000 },
    },
    {
      command: "npm run dev -- --port 3300",
      url: "http://127.0.0.1:3300",
      env: { NEXT_PUBLIC_SUPPORT_API_URL: "http://127.0.0.1:38123", SUPPORT_AGENT_URL: "http://127.0.0.1:38123/agent", NEXT_TELEMETRY_DISABLED: "1", COPILOTKIT_TELEMETRY_DISABLED: "true" },
      reuseExistingServer: false,
      timeout: 60000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 3000 },
    },
  ],
});
