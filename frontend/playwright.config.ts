import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60000,
  reporter: [
    ["list"],
    [
      "json",
      {
        outputFile:
          process.env.PLAYWRIGHT_JSON_OUTPUT_NAME ??
          (process.argv.some((arg) => arg.includes("cancellation-payout.spec"))
            ? "evidence/m5-browser-results.json"
            : process.argv.some((arg) => arg.includes("booking.spec"))
              ? "evidence/m4-browser-results.json"
              : process.argv.some((arg) => arg.includes("discovery.spec"))
                ? "evidence/m3-browser-results.json"
                : process.argv.some((arg) => arg.includes("listings.spec"))
                  ? "evidence/m2-browser-results.json"
                  : "evidence/browser-results.json"),
      },
    ],
  ],
  use: {
    baseURL: process.env.SMOKE_BASE_URL ?? "http://localhost:5173",
    headless: true,
    screenshot: "only-on-failure",
    trace: "off",
  },
  outputDir: "test-results",
});
