import os

from playwright.sync_api import sync_playwright


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", headless=True)
    page = browser.new_page()
    page.goto(os.getenv("SMOKE_URL", "http://localhost:8501"), wait_until="domcontentloaded")
    page.get_by_role("heading", name="雾港谜案").wait_for(timeout=15000)
    if page.get_by_role("button", name="开局", exact=True).count():
        page.get_by_role("button", name="开局", exact=True).click()
    else:
        page.get_by_role("button", name="新开一局").click()
    page.get_by_role("button", name="开始阅读").click()
    page.get_by_role("button", name="读完，进入公聊").click()
    page.get_by_label("你想问什么").fill("你昨晚在哪里？")
    page.get_by_role("button", name="询问", exact=True).click()
    page.get_by_label("询问对象").click()
    page.get_by_role("option", name="陈砚秋").click()
    page.get_by_label("你想问什么").fill("你看见了什么？")
    page.get_by_role("button", name="询问", exact=True).click()
    page.get_by_role("button", name="进入私聊").click()
    page.get_by_label("私聊内容").fill("你认识死者吗？")
    page.get_by_role("button", name="询问", exact=True).click()
    page.get_by_text("你认识死者吗？", exact=False).last.wait_for(timeout=10000)
    page.get_by_role("button", name="结束私聊").click()
    page.get_by_role("button", name="进入搜证").wait_for(timeout=10000)
    page.get_by_role("button", name="进入搜证").click()
    page.get_by_role("button", name="搜查", exact=True).click()
    page.get_by_text("地毯酒渍").first.wait_for(timeout=10000)
    page.reload(wait_until="domcontentloaded")
    page.get_by_text("地毯酒渍").first.wait_for(timeout=10000)
    page.get_by_role("button", name="返回公聊").click()
    page.get_by_role("button", name="进入对质").click()
    page.get_by_label("对质内容").fill("这条线索你怎么解释？")
    page.get_by_role("button", name="追问").click()
    page.get_by_label("动机与推理").fill("欠条纠纷")
    page.get_by_role("button", name="提交指认").click()
    page.get_by_role("button", name="查看复盘").click()
    page.get_by_text("真实凶手", exact=False).first.wait_for(timeout=10000)
    print("UI smoke: 2 NPC turns, private chat, clue, refresh, confrontation, vote and recap passed")
    browser.close()
