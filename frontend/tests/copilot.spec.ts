import { execFileSync } from 'node:child_process';
import { expect, test, type Page, type APIRequestContext } from '@playwright/test';

test.skip(!process.env.SDC_COPILOT_E2E, 'Guided planning needs the PostgreSQL/SMTP/provider fixture');
test.use({ actionTimeout: 10000 });
const headers = { Origin: 'http://127.0.0.1:5173', 'X-SDC-Request': '1' };

async function join(page: Page, request: APIRequestContext, label: string) {
  const email = `copilot-${label}-${Date.now()}@example.com`;
  const password = 'A scientific planning passphrase!';
  expect((await request.post('/api/v1/auth/register', { headers, data: { name: 'Planner', email, password } })).status()).toBe(202);
  let token = '';
  await expect.poll(async () => {
    const messages = (await (await request.get('http://127.0.0.1:8025/api/v1/search', { params: { query: `to:${email}` } })).json()).messages;
    if (!messages?.length) return false;
    const mail = await (await request.get(`http://127.0.0.1:8025/api/v1/message/${messages[0].ID}`)).json();
    token = String(mail.Text).match(/\/#\/verify\?token=([A-Za-z0-9_-]+)/)?.[1] ?? '';
    return Boolean(token);
  }).toBeTruthy();
  expect((await request.post('/api/v1/auth/verify', { headers, data: { token } })).status()).toBe(200);
  await page.goto('/#/signin');
  await page.getByRole('main').getByLabel(/^Email(?:\s*\*)?$/).fill(email);
  await page.getByRole('main').getByLabel(/^Password(?:\s*\*)?$/).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your account', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Your analyses', exact: true }).click();
}

test('clarify, review, edit, save and explicitly run a guided analysis', async ({ page, request }, testInfo) => {
  test.setTimeout(60000);
  await join(page, request, `guided-${testInfo.project.name}`);
  let guided = page.getByRole('region', { name: 'Guided planning', exact: true });
  await guided.getByLabel('What would you like to analyse?').fill('Show sea surface temperature near Madeira.');
  await guided.getByRole('button', { name: 'Prepare proposal', exact: true }).click();
  await expect(guided.getByText(/Which dates should be included/)).toBeVisible();
  await page.reload();
  guided = page.getByRole('region', { name: 'Guided planning', exact: true });
  await guided.getByLabel('Your clarification').fill('January 2020');
  await guided.getByRole('button', { name: 'Send clarification', exact: true }).click();
  const proposal = guided.getByRole('region', { name: 'Review proposal', exact: true });
  await expect(proposal.getByRole('heading', { name: 'Review your proposal', exact: true })).toBeVisible();
  expect((await (await page.request.get('/api/v1/analyses')).json()).length).toBe(0);
  await proposal.getByLabel('Proposal title').fill('Reviewed Canary Islands');
  await proposal.getByRole('combobox', { name: 'Proposal region' }).click();
  await page.getByRole('option', { name: 'Canary Islands — surrounding ocean', exact: true }).click();
  await expect(proposal.getByRole('button', { name: 'Confirm and save analysis', exact: true })).toHaveCount(0);
  await proposal.getByRole('button', { name: 'Validate edits', exact: true }).click();
  await expect(proposal.getByText(/Source metadata checked/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath('guided-proposal.png'), fullPage: true });
  await proposal.getByRole('button', { name: 'Confirm and save analysis', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Reviewed Canary Islands', exact: true })).toBeVisible();
  const saved = (await (await page.request.get('/api/v1/analyses')).json())[0];
  expect((await (await page.request.get(`/api/v1/analyses/${saved.id}/runs`)).json()).length).toBe(0);
  expect((await (await page.request.get('/api/v1/account/usage')).json()).reserved).toBe(0);
  await page.getByRole('button', { name: 'Run analysis', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Start run', exact: true }).click();
  const detail = page.getByRole('region', { name: 'Selected run', exact: true });
  await expect(detail.getByText('queued', { exact: true })).toBeVisible();
  execFileSync('python', ['backend/tests/analysis_fixture_worker.py', '--once'], { cwd: '..', timeout: 30000, encoding: 'utf8' });
  await expect(detail.getByText('succeeded', { exact: true })).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole('link', { name: 'Download CSV', exact: true })).toBeVisible();
  expect((await (await page.request.get('/api/v1/account/usage')).json()).consumed).toBe(1);
  expect((await (await page.request.get('/api/v1/copilot/status')).json()).remaining).toBe(18);
});

test('unsupported requests and provider outages leave the manual workflow usable', async ({ page, request }, testInfo) => {
  test.setTimeout(45000);
  await join(page, request, `fallback-${testInfo.project.name}`);
  const guided = page.getByRole('region', { name: 'Guided planning', exact: true });
  await guided.getByLabel('What would you like to analyse?').fill('Show rainfall around Madeira during 2020.');
  await guided.getByRole('button', { name: 'Prepare proposal', exact: true }).click();
  await expect(guided.getByText(/Other variables, regions and calculations are not available/)).toBeVisible();
  await expect(guided.getByRole('region', { name: 'Review proposal' })).toHaveCount(0);
  await guided.getByRole('button', { name: 'New request', exact: true }).click();
  await guided.getByLabel('What would you like to analyse?').fill('Simulate a provider outage');
  await guided.getByRole('button', { name: 'Prepare proposal', exact: true }).click();
  await expect(guided.getByText(/Planning could not be completed/)).toBeVisible();
  await guided.getByRole('button', { name: 'Use manual form', exact: true }).click();
  await page.getByRole('textbox', { name: 'Analysis title', exact: true }).fill('Manual after outage');
  await page.getByRole('button', { name: 'Save analysis', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Manual after outage', exact: true })).toBeVisible();
  expect((await (await page.request.get('/api/v1/account/usage')).json()).reserved).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath('planning-fallback.png'), fullPage: true });
});
