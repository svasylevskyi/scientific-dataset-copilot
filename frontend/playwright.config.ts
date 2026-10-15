import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  globalTimeout: process.env.CI ? 120_000 : undefined,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? 'list' : undefined,
  use: { baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure' },
  webServer: [
    {
      command: process.env.SDC_COPILOT_E2E
        ? 'python -m uvicorn copilot_fixture_api:app --app-dir backend/tests --host 127.0.0.1 --port 8000'
        : 'python -m uvicorn app.main:app --host 127.0.0.1 --port 8000',
      cwd: '..',
      url: 'http://127.0.0.1:8000/api/v1/health',
      reuseExistingServer: !process.env.CI,
    },
    {
      command: 'npm run dev -- --port 5173 --strictPort',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: !process.env.CI,
    },
  ],
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
});
