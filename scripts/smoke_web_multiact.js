const { chromium } = require('playwright');
const os = require('os');
const path = require('path');

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    headless: true,
  });
  try {
    const base = process.env.SMOKE_URL || 'http://127.0.0.1:8101';
    for (const [name, viewport] of [
      ['desktop', { width: 1440, height: 900 }],
      ['mobile', { width: 390, height: 844 }],
    ]) {
      const page = await browser.newPage({ viewport });
      const publicData = await (await page.request.get(`${base}/api/show/script`)).json();
      if (JSON.stringify(publicData).includes('储藏室的保险柜被打开')) {
        throw new Error('second act leaked before the game');
      }
      await page.goto(`${base}/#play`, { waitUntil: 'domcontentloaded' });
      await page.getByRole('button', { name: '开局', exact: true }).click();
      await page.getByRole('button', { name: '开始阅读' }).click();
      await page.getByRole('button', { name: '读完了，进入公聊' }).click();
      await page.getByRole('button', { name: '进入对质' }).click();
      await page.locator('.play__composer .chip').first().click();
      await page.getByPlaceholder('动机与推理过程').fill('为了遗产');
      await page.getByRole('button', { name: /投票指认/ }).click();
      await page.locator('.play__main').getByRole('button', { name: '进入下一幕' }).click();
      await page.getByText('储藏室的保险柜被打开，旧案重新浮出水面。').waitFor({ timeout: 30000 });
      if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2)) {
        throw new Error(`${name} has horizontal overflow`);
      }
      const screenshot = path.join(os.tmpdir(), `jubensha-web-multiact-${name}.png`);
      await page.screenshot({ path: screenshot, fullPage: true });
      console.log(`${name}: ${screenshot}`);
      await page.close();
    }
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
