const { chromium } = require('playwright');
const os = require('os');
const path = require('path');

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    headless: true,
  });
  try {
  const review = Boolean(process.env.SMOKE_REVIEW_URL);
  const url = process.env.SMOKE_REVIEW_URL || process.env.SMOKE_URL || 'http://localhost:8510/?view=library';
  for (const [name, viewport] of [
    ['desktop', { width: 1440, height: 900 }],
    ['mobile', { width: 390, height: 844 }],
  ]) {
    const page = await browser.newPage({ viewport, deviceScaleFactor: 1 });
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await page.getByRole('heading', { name: review ? '雾港谜案' : '剧本库', exact: true }).waitFor({ timeout: 30000 });
    await page.getByRole('button', { name: review ? '保存字段' : '开局', exact: true }).waitFor({ timeout: 30000 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2);
    if (overflow) throw new Error(`${name} has horizontal overflow`);
    const screenshot = path.join(os.tmpdir(), `jubensha-v2-${review ? 'review-' : ''}${name}.png`);
    await page.screenshot({ path: screenshot, fullPage: true });
    console.log(`${name}: ${screenshot}`);
    await page.close();
  }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
