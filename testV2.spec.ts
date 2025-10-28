import { test, expect, type Page, type Locator } from '@playwright/test';
import path from 'path';
import fs from 'fs';
test.use({ acceptDownloads: true });

/* ============================================= EDITABLE VALUES ============================================= */
const BASE_URL = 'https://staging.faybl.com';
const SIGNIN_URL = `${BASE_URL}/signin`;
const INPUT_DIR = path.resolve('C:/Users/Tony/testdata/input_files'); // folder for files to upload
const OUTPUT_DIR = path.resolve('C:/Users/Tony/testdata/output_files'); // folder for downloaded files
const jsonPath = path.resolve('C:/Users/Tony/testdata/input_files/input.json');  // path to JSON file with login and client data
const data = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
const { email, password, protectedCode, clients, clientid } = data;
/* =========================================================================================================== */

function listfiles(dir: string): string[] {
  if (!fs.existsSync(dir)) throw new Error(`Folder not found: ${dir}`);
  const files = fs.readdirSync(dir)
    .filter(f => !f.startsWith('.')) // skip hidden/system files
    .map(f => path.join(dir, f));
  if (!files.length) throw new Error(`No files found in ${dir}`);
  return files;
}

function formatBytes(bytes: number): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  const precision = value < 10 && i > 0 ? 1 : 0;
  return `${value.toFixed(precision)} ${units[i]}`;
}

function logUploadReport(files: string[]): void {
  console.log(`Uploading ${files.length} file(s):`);
  files.forEach((file, idx) => {
    const { size } = fs.statSync(file);
    console.log(
      ` [${idx + 1}] ${path.basename(file)} — ${formatBytes(size)} — ${file}`
    );
  });
}
/* =========================================================================================================== */

test('Fact-Find and KYC', async ({ page, context }) => {
  const emailInput = page.locator('#email');
  const passwordInput = page.locator('#password');
  const protectedInput = page.locator('#protectedCode');
  const signInButton = page.locator('button.brand-origin-btn', { hasText: 'Sign in' });
  const loginError = page.locator('div.self-center.flex-1', {
    hasText: 'Unable to sign in with the provided credentials.'
  });
  const promptBtn = page.locator('#send-message-button');
  const chatInput = page.locator('textarea.rce-input.rce-input-textarea');
  const nextBtn = page.getByRole('button', { name: 'Next' });
  const heading = page.locator('div.text-h4.font-semibold.text-text-lm-heading-color.overflow-hidden.text-ellipsis');  // client data heading
  const spinner = page.locator('svg.text-status-in-progress-color.animate-spin');  // spinning dots (processing files)
  const done_icon = page.locator('svg.text-status-success-color');                 // green tick (processing done)

  const uploadBtn = page.locator('button[data-ga-id="Upload Files Button"]');
  const uploadInput  = uploadBtn.locator('input[type="file"]');
  const autoFormFilling = page.getByRole('tab', { name: 'Auto Form Filling' });
  const editor = page.frameLocator('iframe[name="frameEditor"]');
  const fileBtn = editor.locator('#file').first();
  const pdfBtn = editor.locator('div.svg-format-pdf');

  await context.clearCookies();

  // Sign in
  await page.goto(SIGNIN_URL, { waitUntil: 'domcontentloaded' });
  await expect(emailInput).toBeVisible({ timeout: 10_000 });
  await expect(passwordInput).toBeVisible();
  await expect(protectedInput).toBeVisible();
  await emailInput.fill(email);
  await passwordInput.fill(password);
  await protectedInput.fill(protectedCode);
  await signInButton.click();

  //login test
  try {
    await expect(chatInput).toBeVisible({ timeout: 10_000 });
  } catch (error: any) {
    console.error('Login failed, please check credentials.');
    console.error(`Error: ${error?.message ?? String(error)}`);
    await page.screenshot({ path: 'login-failed.png', fullPage: true });
    throw error;
  }

  // Get client data from Xplan
  const clientName = data.clients[0];
  await chatInput.fill(`/xplan-get-client-details for ${clientName}`);  // first client name
  await page.keyboard.press('Enter');
  await expect(nextBtn).toBeVisible({ timeout: 30_000 });
  await nextBtn.click();
  // Ensure document canvas is open
  await page.waitForTimeout(3000);
  const clientIdCell = page.getByRole('cell', { name: data.clientid[0] })  // first client ID
  const clientDataEntry = page.getByRole('button', { name: /xplan - get client details/i });
  if (!(await clientIdCell.isVisible().catch(() => false))) {
    await clientDataEntry.click();
  }
  await expect(clientIdCell).toBeVisible({ timeout: 300_000 });
  await clientIdCell.click();
  await expect(nextBtn).toBeVisible({ timeout: 10_000 });
  await nextBtn.click();

  // Retrieve client details test
  try {
    const t0 = Date.now();
    await heading.first().waitFor({ state: 'visible', timeout: 900_000 }); // wait for client details to load
    await page.screenshot({ path: path.join(OUTPUT_DIR, 'client_details.png'), fullPage: true });
    console.log(`Retrieved client details for ${clientName} in ${((Date.now() - t0) / 1000).toFixed(2)}s`);
  } catch (error: any) {
    console.error(`Timeout after 15 minutes waiting for Faybl to retrieve client details.`);
    console.error(`Error: ${error?.message ?? String(error)}`);
    await page.screenshot({ path: 'xplan-timeout.png', fullPage: true });
    throw error;
  }

  // Choose files to upload (File ending with ClientProfileForm)
  const allFiles = listfiles(INPUT_DIR);
  const matches = allFiles.filter(f =>
    path.parse(f).name.trim().toLowerCase().endsWith('clientprofileform')
  );
  if (!matches.length) {
    throw new Error(
      `No file in ${INPUT_DIR} with a name ending in 'ClientProfileForm' (ignoring extension).`
    );
  }
  // If multiple matches, pick the most recently modified one
  const files = [
    matches.length === 1
      ? matches[0]
      : matches
          .map(f => ({ f, m: fs.statSync(f).mtimeMs }))
          .sort((a, b) => b.m - a.m)[0].f
  ];
  // Start the upload
  const start = Date.now();
  await uploadInput.setInputFiles(files);
  await expect(promptBtn).toBeEnabled({ timeout: 120_000 }); // waits until uploads complete
  // Click the Prompt button
  await promptBtn.hover();
  await promptBtn.click({ trial: true });
  await promptBtn.click();
  // Report upload results
  const secs = ((Date.now() - start) / 1000).toFixed(2);
  logUploadReport(files);
  console.log(`${files.length} files uploaded in ${secs}s`);

  // Ensure document canvas is open
  await page.waitForTimeout(5000);
  const fileEntry = page
  .locator('div.font-semibold.text-main-body.text-text-lm-heading-color')
  .filter({ hasText: 'ClientProfileForm' })
  .first();
  if (!(await autoFormFilling.isVisible().catch(() => false))) {
    await fileEntry.click();
  }
  await page.waitForTimeout(3000);
  await expect(autoFormFilling).toBeVisible({ timeout: 30_000 });
  await autoFormFilling.click(); // switch to Auto Form Filling tab

  // Auto form filling test
  await spinner.first().waitFor({ state: 'visible', timeout: 10_000 }).catch(() => {});
  try {
    const t0 = Date.now();
    await spinner.first().waitFor({ state: 'detached', timeout: 900_000 });  // wait for loading animation to disappear
    console.log(`Auto form filling completed in ${((Date.now() - t0) / 1000).toFixed(2)}s`);
  } catch (error: any) {
    console.error(`Timeout after 15 minutes waiting for Faybl to fill the form.`);
    console.error(`Error: ${error?.message ?? String(error)}`);
    await page.screenshot({ path: 'autofill-timeout.png', fullPage: true });
    throw error;
  }

  // Download the filled PDF
  await page.waitForTimeout(15000);
  await page.screenshot({ path: path.join(OUTPUT_DIR, 'filled_form.png'), fullPage: true });
  await expect(fileBtn).toBeVisible({ timeout: 10_000 });
  await fileBtn.click();
  await page.waitForTimeout(3000);
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    pdfBtn.click(),
  ]);
  const suggested = download.suggestedFilename();
  const savePath  = path.join(OUTPUT_DIR, suggested);
  await download.saveAs(savePath);

  // Pause
  //await page.pause();
});
