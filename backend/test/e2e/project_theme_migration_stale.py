"""S06导入既有草稿的revision并发：外部HTTP推进后，409刷新目录并保留输入。"""

import hashlib
import json
import os
import re
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parents[3]
OUT = Path(os.environ["THEME_EVIDENCE_OUTPUT"])
B_API = os.environ.get("THEME_EVIDENCE_B_API", "http://127.0.0.1:15065")
WEB_B = os.environ.get("THEME_EVIDENCE_WEB_B", "http://127.0.0.1:15175")
B = json.loads(Path(os.environ["THEME_EVIDENCE_B_SESSION"]).read_text())
RAW = (OUT / "a-original.theme.zip").read_bytes()
DIGEST = hashlib.sha256(RAW).hexdigest()


def sources():
    """回读全部有权来源。"""
    response = httpx.get(
        B_API + "/api/theme-sources", headers={"Authorization": f"Bearer {B['token']}"}, timeout=30
    )
    response.raise_for_status()
    return response.json()["sources"]


def catalog():
    """回读真实目录，取导入目标的当前候选修订。"""
    return next(source for source in sources() if source["name"] == "B迁移草稿-UI")


def main():
    """外部窗口先推进修订，旧窗口确认必须409并刷新。"""
    source = catalog()
    source_count = len(sources())
    stale_revision = source["candidate_revision"]
    assert source["candidate_digest"] == DIGEST
    checks = []
    with sync_playwright() as playwright:
        executable = os.environ.get(
            "THEME_EVIDENCE_CHROMIUM",
            str(
                Path.home()
                / "Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-x64/chrome-headless-shell"
            ),
        )
        browser = playwright.chromium.launch(
            headless=True, executable_path=executable if Path(executable).exists() else None
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(f"{WEB_B}/login")
        page.get_by_label("登录账号").wait_for()
        page.wait_for_timeout(700)
        page.locator('input[type="checkbox"]').first.check()
        page.get_by_label("登录账号").fill(B["uid"])
        page.get_by_label("密码").fill(B["password"])
        page.locator('button[type="submit"]').click()
        page.wait_for_function("() => location.pathname !== '/login'", timeout=30000)
        page.goto(f"{WEB_B}/projects?tab=themes")
        page.get_by_text("来源目录", exact=True).wait_for()
        page.get_by_role("button", name="导入主题包", exact=True).click()
        modal = page.locator(".ant-modal").filter(has_text="导入主题包")
        modal.wait_for()
        modal.locator('input[aria-label="导入主题包ZIP"]').set_input_files(str(OUT / "a-original.theme.zip"))
        modal.get_by_text("只读预检", exact=True).wait_for()
        modal.get_by_text("写入既有主题草稿", exact=True).click()
        modal.get_by_label("导入目标既有主题").click()
        page.get_by_text("B迁移草稿-UI", exact=False).last.click()

        # 另一窗口在同一目标上推进候选修订；本窗口仍持有旧修订。
        external = httpx.post(
            B_API + "/api/theme-imports",
            params={"digest": DIGEST, "source_id": source["id"], "expected_revision": stale_revision},
            headers={"Authorization": f"Bearer {B['token']}"},
            content=RAW,
            timeout=60,
        )
        assert external.status_code == 200, external.text
        assert catalog()["candidate_revision"] == stale_revision + 1

        modal.get_by_role("button", name="确认保存草稿", exact=True).click()
        page.get_by_text("已刷新目录", exact=False).wait_for(timeout=30000)
        checks.append("旧revision确认409后显示已刷新目录")
        refreshed = catalog()
        assert len(sources()) == source_count
        assert refreshed["candidate_revision"] == stale_revision + 1
        checks.append("目标候选修订已从目录刷新")
        modal_text = modal.inner_text()
        assert "已选择：a-original.theme.zip" in modal_text and "只读预检" in modal_text
        assert DIGEST in modal_text
        checks.append("409后文件、预检摘要和目标输入保留")
        selected = [text for text in modal.locator(".ant-select-selection-item").all_inner_texts() if "B迁移草稿-UI" in text]
        assert selected and f"草稿修订 {stale_revision + 1}" in selected[0], selected
        checks.append("409后UI目标显示刷新后的修订")
        assert modal.locator('input[aria-label="导入主题包ZIP"]').count() == 1
        page.screenshot(path=OUT / "b-import-stale-1440.png", full_page=True)
        modal.get_by_role("button", name=re.compile(r"取\s*消")).click()
        page.get_by_role("button", name="放弃并关闭", exact=True).click()
        page.wait_for_timeout(300)
        browser.close()
    report = {"checks": checks, "staleRevision": stale_revision, "currentRevision": refreshed["candidate_revision"], "sources": source_count, "digest": DIGEST}
    (OUT / "stale-revision-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
