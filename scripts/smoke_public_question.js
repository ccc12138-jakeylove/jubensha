const { chromium } = require('playwright');
const os = require('os');
const path = require('path');

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    headless: true,
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.goto(process.env.SMOKE_URL || 'http://127.0.0.1:8511/?view=library');
    await page.getByRole('button', { name: '开局', exact: true }).click();
    await page.getByRole('button', { name: '开始阅读' }).click();
    await page.getByRole('button', { name: '读完，进入公聊' }).click();
    await page.getByRole('textbox', { name: '你想问什么' }).fill('我觉得凶手在你们之中');
    await page.getByRole('button', { name: '询问', exact: true }).click();
    await page.getByText(/林素云：/).waitFor({ timeout: 60000 });
    await page.getByText(/陈砚秋：/).waitFor({ timeout: 60000 });
    const answers = await page.locator('[data-testid="stChatMessage"]').allTextContents();
    const npc = answers.filter((item) => ['林素云：', '陈砚秋：', '阿黛：'].some((name) => item.includes(name)));
    if (npc.length < 2 || new Set(npc).size !== npc.length) {
      throw new Error(`public answers were repeated: ${npc.length} NPC messages`);
    }
    const screenshot = path.join(os.tmpdir(), 'jubensha-public-question.png');
    await page.screenshot({ path: screenshot, fullPage: true });
    console.log(`npc_answers=${npc.length} screenshot=${screenshot}`);
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
