const { chromium } = require('playwright');
const os = require('os');
const path = require('path');

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    headless: true,
  });
  try {
    for (const [name, viewport] of [
      ['desktop', { width: 1440, height: 900 }],
      ['mobile', { width: 390, height: 844 }],
    ]) {
    const page = await browser.newPage({ viewport });
    await page.goto(process.env.SMOKE_URL || 'http://localhost:8510/?view=library');
    if (process.env.SMOKE_DRAFT === '1') {
      await page.getByRole('button', { name: '本机试玩', exact: true }).click();
      await page.getByText('草稿试玩：内容和结果尚未通过正式验收。').waitFor({ timeout: 30000 });
    } else {
      await page.getByRole('button', { name: '开局', exact: true }).click();
    }
    await page.getByRole('button', { name: '开始阅读' }).click();
    await page.getByRole('button', { name: '读完，进入公聊' }).click();
    if (process.env.SMOKE_DRAFT === '1') {
      await page.getByRole('button', { name: '进入搜证' }).click();
      await page.getByRole('button', { name: '搜查地点' }).click();
      await page.getByText('这里没有当前可搜查的线索。').waitFor({ timeout: 30000 });
      await page.reload();
      await page.getByText('草稿试玩：内容和结果尚未通过正式验收。').waitFor({ timeout: 30000 });
    }
    await page.getByText('推理板', { exact: true }).click();
    await page.locator('[data-testid="stGraphVizChart"]').first().waitFor({ timeout: 30000 });
    await page.locator('[data-testid="stGraphVizChart"] svg').first().waitFor({ timeout: 30000 });
    await page.waitForTimeout(800);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2);
    if (overflow) throw new Error(`${name} has horizontal overflow`);
    if (await page.getByText('ModuleNotFoundError').count()) {
      throw new Error('graph visualization dependency is missing');
    }
    const screenshot = path.join(os.tmpdir(), `jubensha-v2-game-${name}.png`);
    await page.screenshot({ path: screenshot, fullPage: true });
    console.log(screenshot);
    await page.close();
    }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
