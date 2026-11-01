import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


fixture = json.loads(Path("fixtures/wugang_01.json").read_text(encoding="utf-8"))
fixture["script_id"] = "wugang_ui_test"
fixture["title"] = "雾港测试剧本"
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", headless=True)
    page = browser.new_page()
    page.goto(os.getenv("SMOKE_URL", "http://localhost:8505"), wait_until="domcontentloaded")
    page.get_by_role("button", name="剧本库").wait_for(timeout=15000)
    page.get_by_role("button", name="剧本库").click()
    page.locator("input[type=file]").set_input_files({
        "name": "wugang_ui_test.json", "mimeType": "application/json",
        "buffer": json.dumps(fixture, ensure_ascii=False).encode(),
    })
    page.get_by_role("checkbox", name="我确认拥有此剧本的使用权或已获授权").check(force=True)
    page.get_by_role("button", name="编译并保存草稿").click()
    page.get_by_role("button", name="发布剧本").wait_for(timeout=15000)
    page.get_by_role("button", name="发布剧本").click()
    page.get_by_role("heading", name="剧本库").wait_for(timeout=15000)
    page.get_by_label("选择剧本").click()
    page.get_by_role("option", name="雾港测试剧本").click()
    page.get_by_role("button", name="开局", exact=True).click()
    page.get_by_role("button", name="开始阅读").wait_for(timeout=15000)
    print("P4 UI smoke: upload, review, publish and start passed")
    browser.close()
