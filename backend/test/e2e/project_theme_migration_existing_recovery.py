"""S06既有来源导入响应丢失：先核revision前进，再显式重试核实。"""

import hashlib
import json
import os
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

OUT = Path(os.environ["THEME_EVIDENCE_OUTPUT"])
B_API = os.environ.get("THEME_EVIDENCE_B_API", "http://127.0.0.1:15065")
WEB_B = os.environ.get("THEME_EVIDENCE_WEB_B", "http://127.0.0.1:15175")
B = json.loads(Path(os.environ["THEME_EVIDENCE_B_SESSION"]).read_text())
ZIP = (OUT / "a-original.theme.zip").read_bytes()
DIGEST = hashlib.sha256(ZIP).hexdigest()
NAME = "B迁移草稿-UI"


def sources():
    """回读全部有权来源。"""
    response = httpx.get(
        B_API + "/api/theme-sources", headers={"Authorization": f"Bearer {B['token']}"}, timeout=30
    )
    response.raise_for_status()
    return response.json()["sources"]


def catalog():
    """回读真实目录，读取既有草稿当前修订。"""
    return next(source for source in sources() if source["name"] == NAME)


def main():
    """既有来源写入成功后响应丢失，不得误报或重复创建来源。"""
    before = catalog()
    before_sources = len(sources())
    assert before["candidate_digest"] == DIGEST
    before_revision = before["candidate_revision"]
    before_versions = len(before["versions"])
    state = {"import_failed": False, "catalog_failed": False}
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
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.goto(f"{WEB_B}/login")
        page.get_by_label("登录账号").wait_for()
        page.wait_for_timeout(700)
        page.locator('input[type="checkbox"]').first.check()
        page.get_by_label("登录账号").fill(B["uid"])
        page.get_by_label("密码").fill(B["password"])
        page.locator('button[type="submit"]').click()
        page.wait_for_function("() => location.pathname !== '/login'", timeout=30000)

        cdp = context.new_cdp_session(page)
        cdp.send(
            "Fetch.enable",
            {
                "patterns": [
                    {"urlPattern": "*api/theme-imports*", "requestStage": "Response"},
                    {"urlPattern": "*api/theme-sources*", "requestStage": "Request"},
                ]
            },
        )

        def paused(event):
            """只注入一次导入响应与紧随其后的目录核实失败。"""
            url = event["request"]["url"]
            if "/api/theme-imports" in url and "/preflight" not in url and not state["import_failed"]:
                state["import_failed"] = True
                cdp.send("Fetch.failRequest", {"requestId": event["requestId"], "errorReason": "Failed"})
                return
            if (
                state["import_failed"]
                and not state["catalog_failed"]
                and "/api/theme-sources" in url
                and event["request"]["method"] == "GET"
            ):
                state["catalog_failed"] = True
                cdp.send("Fetch.failRequest", {"requestId": event["requestId"], "errorReason": "Failed"})
                return
            if "responseStatusCode" in event:
                cdp.send("Fetch.continueResponse", {"requestId": event["requestId"]})
            else:
                cdp.send("Fetch.continueRequest", {"requestId": event["requestId"]})

        cdp.on("Fetch.requestPaused", paused)
        page.goto(f"{WEB_B}/projects?tab=themes")
        page.get_by_text("来源目录", exact=True).wait_for()
        page.get_by_role("button", name="导入主题包", exact=True).click()
        modal = page.locator(".ant-modal").filter(has_text="导入主题包")
        modal.wait_for()
        modal.locator('input[aria-label="导入主题包ZIP"]').set_input_files(str(OUT / "a-original.theme.zip"))
        modal.get_by_text("只读预检", exact=True).wait_for()
        modal.get_by_text("写入既有主题草稿", exact=True).click()
        modal.get_by_label("导入目标既有主题").click()
        page.get_by_text(NAME, exact=False).last.click()
        modal.get_by_role("button", name="确认保存草稿", exact=True).click()
        page.get_by_text("导入结果待核实", exact=True).wait_for(timeout=30000)
        checks.append("既有来源响应丢失后显示待核实入口")
        page.screenshot(path=OUT / "b-import-existing-recovery-1440.png", full_page=True)
        assert state == {"import_failed": True, "catalog_failed": True}
        page.get_by_role("button", name="重新核实导入结果", exact=True).click()
        page.get_by_text("导入草稿已保存", exact=False).wait_for(timeout=30000)
        after = catalog()
        assert after["id"] == before["id"] and len(sources()) == before_sources
        assert after["candidate_revision"] == before_revision + 1
        assert after["candidate_digest"] == DIGEST and len(after["versions"]) == before_versions
        checks.append("既有来源核实要求revision前进且未新增版本")
        checks.append("显式重新核实后定位原有来源草稿")
        context.close()
        browser.close()
    report = {
        "checks": checks,
        "source": after["id"],
        "beforeRevision": before_revision,
        "afterRevision": after["candidate_revision"],
        "versions": len(after["versions"]),
        "digest": DIGEST,
        "sourcesBefore": before_sources,
        "sourcesAfter": len(sources()),
    }
    (OUT / "existing-recovery-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
