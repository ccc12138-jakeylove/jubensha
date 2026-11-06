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
      const base = process.env.SMOKE_URL || 'http://127.0.0.1:8100';
      const publicData = await (await page.request.get(`${base}/api/show/script`)).json();
      if ('clues' in publicData || 'timeline' in publicData) {
        throw new Error('pre-game response includes evidence or truth timeline');
      }
      await page.goto(base, { waitUntil: 'domcontentloaded' });
      if (process.env.SMOKE_IDLE_ONLY === '1') {
        await page.getByRole('button', { name: '进入对局', exact: true }).waitFor();
        await page.waitForTimeout(1400);
        for (const section of ['dossier', 'cast', 'signup']) {
          await page.locator(`#${section}`).scrollIntoViewIfNeeded();
          await page.waitForTimeout(750);
        }
        await page.evaluate(() => scrollTo(0, 0));
        await page.waitForTimeout(400);
        const home = path.join(os.tmpdir(), `jubensha-web-home-${name}.png`);
        await page.screenshot({ path: home, fullPage: true });
        console.log(`${name} home: ${home}`);
      }
      await page.getByRole('button', { name: '进入对局', exact: true }).click();
      if (process.env.SMOKE_IDLE_ONLY === '1') {
        await page.getByLabel('剧本').waitFor({ timeout: 30000 });
        if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2)) {
          throw new Error(`${name} idle screen has horizontal overflow`);
        }
        const idle = path.join(os.tmpdir(), `jubensha-web-idle-${name}.png`);
        await page.screenshot({ path: idle, fullPage: true });
        console.log(`${name}: ${idle}`);
        await page.close();
        continue;
      }
      await page.getByRole('button', { name: '开局', exact: true }).click();
      await page.getByRole('button', { name: '开始阅读' }).click();
      await page.getByRole('button', { name: '读完了，进入公聊' }).click();
      await page.locator('.play__composer .chip').first().click();
      await page.getByRole('button', { name: '私聊', exact: true }).click();
      await page.getByPlaceholder('你想问什么？').fill('你当时在哪？');
      await page.getByRole('button', { name: '发送' }).click();
      await page.locator('.play__log .bubble--npc').first().waitFor({ timeout: 30000 });
      if (await page.getByText('action talk is unavailable').count()) {
        throw new Error('private chat used public talk action');
      }
      const before = await page.locator('.play__log .bubble').count();
      await page.reload();
      await page.getByText('私聊对象：').waitFor({ timeout: 30000 });
      const after = await page.locator('.play__log .bubble').count();
      if (after < before) throw new Error('dialogue was lost on refresh');
      if (await page.locator('.play__log .bubble--npc').count() === 0) {
        throw new Error('private reply was lost on refresh');
      }
      if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2)) {
        throw new Error(`${name} has horizontal overflow`);
      }
      const screenshot = path.join(os.tmpdir(), `jubensha-web-${name}.png`);
      await page.screenshot({ path: screenshot, fullPage: true });
      console.log(`${name}: ${screenshot}`);
      await page.close();
    }
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
