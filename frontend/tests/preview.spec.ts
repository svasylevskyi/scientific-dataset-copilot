import { expect, test } from '@playwright/test';

test('reference is inspectable and exportable; query planning does not replace it', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'A decade around the Canaries' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Download chart' })).toBeEnabled();
  await page.screenshot({ path: test.info().outputPath('reference.png'), fullPage: true });
  const csvDownload = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Download CSV' }).click();
  expect((await csvDownload).suggestedFilename()).toBe('canaries-sst-reference.csv');
  const chartDownload = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download chart' }).click();
  expect((await chartDownload).suggestedFilename()).toMatch(/\.png$/);
  await page.getByRole('button', { name: 'Query planner' }).click();
  await page.getByRole('button', { name: 'Preview query' }).click();
  await expect(page.getByRole('heading', { name: 'Your query plan' })).toBeVisible();
  await expect(page.getByText('1,052,064 estimated cell-time values in 10 bounded requests.')).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('query-planner.png'), fullPage: true });
  await page.getByLabel(/^From/).fill('2026-10-01');
  await page.getByLabel(/^To/).fill('2026-10-12');
  await expect(page.getByRole('heading', { name: 'Your query plan' })).not.toBeVisible();
  await page.getByRole('button', { name: 'Preview query' }).click();
  await expect(page.getByText(/Requested dates exceed/)).toBeVisible();
  await page.getByRole('button', { name: 'Reference analysis' }).click();
  await expect(page.getByRole('heading', { name: 'A decade around the Canaries' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  expect(errors).toEqual([]);
});

test('API failure shows a retry action', async ({ page }) => {
  await page.route('**/api/v1/reference', route => route.fulfill({ status: 503, body: '{}' }));
  await page.goto('/');
  await expect(page.getByText('The reference analysis could not be loaded.', { exact: false })).toBeVisible();
  await page.unroute('**/api/v1/reference');
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.getByRole('heading', { name: 'A decade around the Canaries' })).toBeVisible();
});
