import { expect, test } from '@playwright/test';

test('one tester prompt survives reloads, failed login, session loss and logout', async ({ page, context, request, baseURL }, testInfo) => {
  const gatePassword = process.env.SDC_TESTER_PASSWORD;
  if (!gatePassword || !baseURL) throw new Error('The disposable deployment and SDC_TESTER_PASSWORD are required');
  const origin = new URL(baseURL).origin;
  const gateHeaders = { Authorization: `Basic ${Buffer.from(`tester:${gatePassword}`).toString('base64')}` };
  const appHeaders = { ...gateHeaders, Origin: origin, 'X-SDC-Request': '1' };

  // Missing or incorrect tester credentials still protect the app and API.
  const rejectedGateHeaders: Record<string, string>[] = [
    {}, { Authorization: `Basic ${Buffer.from('tester:incorrect-gate-password').toString('base64')}` },
  ];
  for (const path of ['/', '/api/v1/auth/me']) {
    for (const headers of rejectedGateHeaders) {
      const response = await request.get(path, { headers });
      expect(response.status()).toBe(401);
      expect(response.headers()['www-authenticate']).toMatch(/^Basic /);
      expect(response.headers()['x-sdc-app-status']).toBeUndefined();
    }
  }
  // A real app permission denial is not relabeled as a missing session.
  const csrfDenied = await request.post('/api/v1/auth/logout', { headers: gateHeaders, data: {} });
  expect(csrfDenied.status()).toBe(403);
  expect(csrfDenied.headers()['x-sdc-app-status']).toBeUndefined();

  const email = `gate-${testInfo.project.name}-${Date.now()}@example.com`;
  const password = 'A development browser test passphrase!';
  expect((await request.post('/api/v1/auth/register', {
    headers: appHeaders, data: { email, password, name: 'Gate tester' },
  })).status()).toBe(202);
  const inbox = await request.get('http://127.0.0.1:8025/api/v1/search', { params: { query: `to:${email}` } });
  const messages = (await inbox.json()).messages;
  expect(messages).toHaveLength(1);
  const mail = await (await request.get(`http://127.0.0.1:8025/api/v1/message/${messages[0].ID}`)).json();
  const token = String(mail.Text).match(/\/#\/verify\?token=([A-Za-z0-9_-]+)/)?.[1];
  expect(token).toBeTruthy();
  expect((await request.post('/api/v1/auth/verify', { headers: appHeaders, data: { token } })).status()).toBe(200);

  // Do not use Playwright httpCredentials or inject Authorization into the page:
  // those would silently answer repeated prompts and hide the original bug.
  const cdp = await context.newCDPSession(page);
  let prompts = 0;
  cdp.on('Fetch.requestPaused', event => cdp.send('Fetch.continueRequest', { requestId: event.requestId }));
  cdp.on('Fetch.authRequired', event => {
    prompts++;
    return cdp.send('Fetch.continueWithAuth', {
      requestId: event.requestId,
      authChallengeResponse: prompts === 1
        ? { response: 'ProvideCredentials', username: 'tester', password: gatePassword }
        : { response: 'CancelAuth' },
    });
  });
  await cdp.send('Fetch.enable', { handleAuthRequests: true });
  const main = page.getByRole('main');
  await page.goto('/#/account');
  await expect(main.getByText('Sign in to access your personal workspace.')).toBeVisible();
  await expect(main.getByRole('alert')).toHaveCount(0);
  expect(prompts).toBe(1);
  for (let reload = 0; reload < 3; reload++) {
    await page.reload();
    await expect(main.getByText('Sign in to access your personal workspace.')).toBeVisible();
    expect(prompts).toBe(1);
  }

  await main.getByRole('link', { name: 'Sign in', exact: true }).click();
  const signIn = async (value: string) => {
    await main.getByLabel(/^Email(?:\s*\*)?$/).fill(email);
    await main.getByLabel(/^Password(?:\s*\*)?$/).fill(value);
    await main.getByRole('button', { name: 'Sign in', exact: true }).click();
  };
  await signIn('An incorrect application password');
  await expect(main.getByText('Email or password is incorrect.')).toBeVisible();
  await page.reload();
  await expect(main.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible();
  expect(prompts).toBe(1);

  await signIn(password);
  await expect(main.getByLabel(/^Name(?:\s*\*)?$/)).toHaveValue('Gate tester');
  await page.reload();
  await expect(main.getByLabel(/^Name(?:\s*\*)?$/)).toHaveValue('Gate tester');

  // Losing the app cookie still signs the app out on a failed protected action.
  await context.clearCookies();
  await main.getByRole('button', { name: 'Save profile' }).click();
  await expect(main.getByText('Sign in to access your personal workspace.')).toBeVisible();
  await page.reload();
  await expect(main.getByText('Sign in to access your personal workspace.')).toBeVisible();
  expect(prompts).toBe(1);
  await main.getByRole('link', { name: 'Sign in', exact: true }).click();
  await signIn(password);
  await main.getByRole('button', { name: 'Sign out here' }).click();
  await expect(main.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible();
  await page.reload();
  await expect(main.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible();
  expect(prompts).toBe(1);
});
