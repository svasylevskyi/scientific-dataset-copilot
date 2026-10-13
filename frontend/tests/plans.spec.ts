import { execFileSync } from 'node:child_process';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

test.skip(!process.env.SDC_ACCOUNT_E2E, 'Plan journey requires PostgreSQL and Mailpit');
const password = 'A plan browser testing passphrase!';
const headers = { Origin: 'http://127.0.0.1:5173', 'X-SDC-Request': '1' };

async function createAccount(request: APIRequestContext, email: string) {
  const result = await request.post('/api/v1/auth/register', { headers, data: { name: 'Plan tester', email, password } });
  expect(result.status()).toBe(202);
  let token = '';
  await expect.poll(async () => {
    const inbox = await request.get('http://127.0.0.1:8025/api/v1/search', { params: { query: `to:${email}` } });
    const messages = (await inbox.json()).messages;
    if (!messages?.length) return false;
    const message = await (await request.get(`http://127.0.0.1:8025/api/v1/message/${messages[0].ID}`)).json();
    token = String(message.Text).match(/\/#\/verify\?token=([A-Za-z0-9_-]+)/)?.[1] ?? '';
    return Boolean(token);
  }).toBeTruthy();
  expect((await request.post('/api/v1/auth/verify', { headers, data: { token } })).status()).toBe(200);
}

async function signIn(page: Page, email: string) {
  await page.goto('/#/signin');
  const main = page.getByRole('main');
  await main.getByLabel(/^Email(?:\s*\*)?$/).fill(email);
  await main.getByLabel(/^Password(?:\s*\*)?$/).fill(password);
  await main.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(main.getByRole('heading', { name: 'Your account', exact: true })).toBeVisible();
}

async function confirm(page: Page) {
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('main').getByText('Changes saved.', { exact: true })).toBeVisible();
}

test('admin manages plans and defaults; members see their own allowance', async ({ page, request }, testInfo) => {
  test.setTimeout(60000);
  const suffix = `${testInfo.project.name}-${Date.now()}`;
  const adminEmail = `plan-admin-${suffix}@example.com`;
  const memberEmail = `plan-member-${suffix}@example.com`;
  const planName = `Research ${suffix}`;
  await createAccount(request, adminEmail);
  execFileSync('python', ['-m', 'app.accounts.cli', 'promote', adminEmail], { cwd: '..', encoding: 'utf8' });
  expect((await request.post('/api/v1/auth/login', { headers, data: { email: adminEmail, password } })).status()).toBe(200);
  const original = (await (await request.get('/api/v1/admin/plans')).json()).find((p: { is_default: boolean }) => p.is_default);
  try {
    await signIn(page, adminEmail);
    await page.goto('/#/admin/plans');
    const main = page.getByRole('main');
    await expect(main.getByRole('heading', { name: 'Plan administration', exact: true })).toBeVisible();
    await main.getByRole('button', { name: 'Create plan', exact: true }).click();
    await main.getByLabel('Plan name', { exact: true }).fill(planName);
    await main.getByLabel('Description', { exact: true }).fill('Browser-tested research allowance.');
    await main.getByLabel('Analyses per month').fill('3');
    await main.getByLabel('Simultaneous analyses').fill('2');
    await main.getByLabel('Maximum date range (days)').fill('365');
    await main.getByLabel('Result retention (days)').fill('60');
    await main.getByRole('button', { name: 'Save plan', exact: true }).click();
    const card = main.getByRole('region', { name: planName, exact: true });
    await expect(card.getByText('3 analyses / month · 2 at a time')).toBeVisible();
    await card.getByRole('button', { name: 'Edit', exact: true }).click();
    await main.getByLabel('Analyses per month').fill('4');
    await main.getByRole('button', { name: 'Save plan', exact: true }).click();
    await expect(card.getByText('4 analyses / month · 2 at a time')).toBeVisible();
    await card.getByRole('button', { name: 'Make default', exact: true }).click();
    await confirm(page);
    await expect(card.getByText('Registration default')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await page.screenshot({ path: testInfo.outputPath('plan-administration.png'), fullPage: true });

    await createAccount(request, memberEmail);
    await signIn(page, memberEmail);
    await page.getByRole('link', { name: 'Plan and usage', exact: true }).click();
    await expect(main.getByRole('heading', { name: planName, exact: true })).toBeVisible();
    await expect(main.getByText('of 4 monthly')).toBeVisible();
    await expect(main.getByText('No analyses yet. Your allowance is ready for live runs.')).toBeVisible();
    await page.reload();
    await expect(main.getByRole('heading', { name: planName, exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await page.screenshot({ path: testInfo.outputPath('plan-and-usage.png'), fullPage: true });
    await page.goto('/#/admin/plans');
    await expect(main.getByText('Administrator access is required.')).toBeVisible();
    expect((await page.request.get('/api/v1/admin/plans')).status()).toBe(403);

    await signIn(page, adminEmail);
    await page.goto('/#/admin/plans');
    await main.getByRole('region', { name: original.name, exact: true }).getByRole('button', { name: 'Make default', exact: true }).click();
    await confirm(page);
    await card.getByRole('button', { name: 'Archive', exact: true }).click();
    await confirm(page);
    await expect(card.getByText('Archived', { exact: true })).toBeVisible();
    await card.getByRole('button', { name: 'Activate', exact: true }).click();
    await confirm(page);
    await main.getByLabel('Account email').fill(memberEmail);
    await main.getByLabel('Analysis access').click();
    await page.getByRole('option', { name: 'Suspended', exact: true }).click();
    await main.getByRole('button', { name: 'Save assignment', exact: true }).click();
    await confirm(page);
    await signIn(page, memberEmail);
    await page.goto('/#/usage');
    await expect(main.getByRole('heading', { name: original.name, exact: true })).toBeVisible();
    await expect(main.getByText('Analysis access is suspended. Contact an administrator.')).toBeVisible();
    // Existing preview functionality is free and does not consume allowance.
    expect((await page.request.post('/api/v1/query-preview', { data: { region_id: 'canaries', start: '2020-01-01', end: '2020-01-31' } })).status()).toBe(200);
    const usage = await (await page.request.get('/api/v1/account/usage')).json();
    expect(usage.consumed).toBe(0);
    expect(usage.reserved).toBe(0);
  } finally {
    // Restore the registration default even if a browser assertion fails.
    const current = (await (await request.get('/api/v1/admin/plans')).json()).find((p: { id: string }) => p.id === original.id);
    expect((await request.post(`/api/v1/admin/plans/${original.id}/default`, { headers, data: { version: current.version } })).status()).toBe(200);
  }
});
