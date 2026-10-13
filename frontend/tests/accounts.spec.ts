import { expect, test, type APIRequestContext } from '@playwright/test';

const password = 'A browser testing passphrase 123!';
const inbox = process.env.SDC_MAILPIT_URL ?? 'http://127.0.0.1:8025';

test.skip(!process.env.SDC_ACCOUNT_E2E, 'Account journey requires PostgreSQL and Mailpit');

async function emailLink(request: APIRequestContext, email: string, action: string) {
  let link = '';
  await expect.poll(async () => {
    const response = await request.get(`${inbox}/api/v1/search`, { params: { query: `to:${email}` } });
    expect(response.ok()).toBeTruthy();
    const data = await response.json();
    for (const message of data.messages ?? []) {
      const detail = await (await request.get(`${inbox}/api/v1/message/${message.ID}`)).json();
      const match = String(detail.Text).match(new RegExp(`http://127\\.0\\.0\\.1:5173/#/${action}\\?token=[A-Za-z0-9_-]+`));
      if (match) { link = match[0]; return true; }
    }
    return false;
  }, { timeout: 10000 }).toBeTruthy();
  return link;
}

test('independent signup, profile, return, recovery, and verified email change', async ({ page, request }, testInfo) => {
  const email = `journey-${testInfo.project.name}-${Date.now()}@example.com`;
  const newEmail = `changed-${testInfo.project.name}-${Date.now()}@example.com`;
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#/signup');
  const main = page.getByRole('main');
  await main.getByLabel(/^Name(?:\s*\*)?$/).fill('Explorer');
  await main.getByLabel(/^Email(?:\s*\*)?$/).fill(email);
  await main.getByLabel(/^Password(?:\s*\*)?$/).fill(password);
  await main.getByLabel(/^Confirm password(?:\s*\*)?$/).fill(password);
  await main.getByRole('button', { name: 'Create your account', exact: true }).click();
  await expect(main.getByText(/an email is on its way/)).toBeVisible();
  await page.goto(await emailLink(request, email, 'verify'));
  // Merely opening a link does not consume it (safe for email link scanners).
  await main.getByRole('button', { name: 'Verify your email', exact: true }).click();
  await expect(main.getByText('Email verified. You can now sign in.')).toBeVisible();
  await main.getByRole('link', { name: 'Sign in', exact: true }).click();
  await main.getByLabel(/^Email(?:\s*\*)?$/).fill(email);
  await main.getByLabel(/^Password(?:\s*\*)?$/).fill(password);
  await main.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(main.getByRole('heading', { name: 'Your account', exact: true })).toBeVisible();
  await main.getByLabel(/^Name(?:\s*\*)?$/).fill('Ocean Explorer');
  await main.getByRole('button', { name: 'Save profile' }).click();
  await expect(main.getByText('Profile saved.')).toBeVisible();
  await page.reload();
  await expect(main.getByLabel(/^Name(?:\s*\*)?$/)).toHaveValue('Ocean Explorer');
  await page.screenshot({ path: testInfo.outputPath('account.png'), fullPage: true });
  await main.getByRole('button', { name: 'Sign out here' }).click();
  await expect(main.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible();
  await main.getByRole('link', { name: 'Forgot password?' }).click();
  // Both screens have an Email field; wait for the hash-route render before filling it.
  await expect(main.getByRole('heading', { name: 'Reset your password', exact: true })).toBeVisible();
  await main.getByLabel(/^Email(?:\s*\*)?$/).fill(email);
  await expect(main.getByLabel(/^Email(?:\s*\*)?$/)).toHaveValue(email);
  await main.getByRole('button', { name: 'Reset your password', exact: true }).click();
  await expect(main.getByText(/an email is on its way/)).toBeVisible();
  await page.goto(await emailLink(request, email, 'reset'));
  const nextPassword = 'A replacement browser passphrase!';
  await main.getByLabel(/^Password(?:\s*\*)?$/).fill(nextPassword);
  await main.getByLabel(/^Confirm password(?:\s*\*)?$/).fill(nextPassword);
  await main.getByRole('button', { name: 'Choose a new password', exact: true }).click();
  await expect(main.getByText('Password reset. Sign in with your new password.')).toBeVisible();
  await main.getByRole('link', { name: 'Sign in', exact: true }).click();
  await main.getByLabel(/^Email(?:\s*\*)?$/).fill(email);
  await main.getByLabel(/^Password(?:\s*\*)?$/).fill(nextPassword);
  await main.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(main.getByRole('heading', { name: 'Your account', exact: true })).toBeVisible();
  await main.getByLabel(/^New email(?:\s*\*)?$/).fill(newEmail);
  await main.locator('form').filter({ has: page.getByLabel(/^New email(?:\s*\*)?$/) }).getByLabel('Current password').fill(nextPassword);
  await main.getByRole('button', { name: 'Send confirmation link' }).click();
  await expect(main.getByText(/an email is on its way/)).toBeVisible();
  await expect(main.getByLabel(/^Email(?:\s*\*)?$/)).toHaveValue(email);
  await page.goto(await emailLink(request, newEmail, 'email'));
  await main.getByRole('button', { name: 'Confirm your new email', exact: true }).click();
  await expect(main.getByText('Email changed. Sign in using your new email.')).toBeVisible();
  await main.getByRole('link', { name: 'Sign in', exact: true }).click();
  await main.getByLabel(/^Email(?:\s*\*)?$/).fill(newEmail);
  await main.getByLabel(/^Password(?:\s*\*)?$/).fill(nextPassword);
  await main.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(main.getByLabel(/^Name(?:\s*\*)?$/)).toHaveValue('Ocean Explorer');
  await expect(main.getByLabel(/^Email(?:\s*\*)?$/)).toHaveValue(newEmail);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  expect(errors).toEqual([]);
});

test('account errors explain a failed request and passwords must match', async ({ page }) => {
  await page.goto('/#/signup');
  const main = page.getByRole('main');
  await main.getByLabel(/^Name(?:\s*\*)?$/).fill('Test');
  await main.getByLabel(/^Email(?:\s*\*)?$/).fill('mismatch@example.com');
  await main.getByLabel(/^Password(?:\s*\*)?$/).fill(password);
  await main.getByLabel(/^Confirm password(?:\s*\*)?$/).fill('a different password');
  await main.getByRole('button', { name: 'Create your account' }).click();
  await expect(main.getByText('Passwords do not match.')).toBeVisible();
  await page.goto('/#/signin');
  await page.route('**/api/v1/auth/login', route => route.fulfill({ status: 503, json: { detail: 'Account storage is unavailable. Please try again shortly.' } }));
  await main.getByLabel(/^Email(?:\s*\*)?$/).fill('test@example.com');
  await main.getByLabel(/^Password(?:\s*\*)?$/).fill(password);
  await main.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(main.getByText('Account storage is unavailable. Please try again shortly.')).toBeVisible();
});
