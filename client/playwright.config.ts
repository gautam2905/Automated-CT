import { defineConfig } from '@playwright/test'

const PORT = 8791
// The installed Google Chrome is used unless SIM_CHROME names another Chrome or Chromium to run instead.
const CHROME = process.env.SIM_CHROME
const browser = CHROME ? { launchOptions: { executablePath: CHROME } } : { channel: 'chrome' }

export default defineConfig({
  testDir: 'e2e',
  workers: 1,
  timeout: 60_000,
  reporter: 'list',
  use: {
    ...browser,
    headless: true,
    viewport: { width: 1600, height: 950 },
    baseURL: `http://127.0.0.1:${PORT}`,
  },
  webServer: {
    command: `../run_sim.sh --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/catalog`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
})
