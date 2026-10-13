import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './deployment-tests',
  timeout: 60000,
  globalTimeout: 120000,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'https://localhost',
    // CI uses Caddy's local CA. smoke.py separately verifies this exact CA.
    ignoreHTTPSErrors: true,
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
});
