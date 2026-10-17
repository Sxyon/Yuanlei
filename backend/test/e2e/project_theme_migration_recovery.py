"""S06导入写后响应丢失的浏览器恢复证据：先核实，再显式重试核实。"""

import hashlib
import json
import os
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parents[3]
OUT = Path(os.environ["THEME_EVIDENCE_OUTPUT"])
B_API = os.environ.get("THEME_EVIDENCE_B_API", "http://127.0.0.1:15065")
WEB_B = os.environ.get("THEME_EVIDENCE_WEB_B", "http://127.0.0.1:15175")
B = json.loads(Path(os.environ["THEME_EVIDENCE_B_SESSION"]).read_text())
ZIP = (OUT / "a-original.theme.zip").read_bytes()
DIGEST = hashlib.sha256(ZIP).hexdigest()
NAME = "B响应丢失验例"
OUT.mkdir(parents=True, exist_ok=True)


def sources():
    """真实目录回读，按名称确认是否只创建一次。"""
    response = httpx.get(
        B_API + "/api/theme-sources", headers={"Authorization": f"Bearer {B['token']}"}, timeout=30
    )
    response.raise_for_status()
    return response.json()["sources"]


def main():
    """响应已在服务端提交但客户端丢失时，不重复创建来源。"""
    before = [source for source in sources() if source["name"] == NAME]
    assert not before
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
            """仅在导入响应和紧随其后的目录核实上注入一次失败。"""
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
        modal.get_by_label("导入目标主题名称").fill(NAME)
        modal.get_by_role("button", name="确认保存草稿", exact=True).click()
        page.get_by_text("导入结果待核实", exact=True).wait_for(timeout=30000)
        checks.append("响应丢失后显示待核实入口")
        page.screenshot(path=OUT / "b-import-recovery-1440.png", full_page=True)
        assert state == {"import_failed": True, "catalog_failed": True}
        page.get_by_role("button", name="重新核实导入结果", exact=True).click()
        page.get_by_text("导入草稿已保存", exact=False).wait_for(timeout=30000)
        checks.append("显式重新核实后定位已保存草稿")
        matched = [source for source in sources() if source["name"] == NAME]
        assert len(matched) == 1, matched
        assert matched[0]["candidate_digest"] == DIGEST and matched[0]["candidate_revision"] == 1
        assert not matched[0]["versions"]
        checks.append("响应丢失只创建一个来源且未自动发布")
        definition = json.loads(page.get_by_label("编辑草稿JSON定义").input_value())
        assert definition["theme"]["id"] == "current-research" and definition["theme"]["version"] == "3.1.0-r2"
        context.close()
        browser.close()
    report = {"checks": checks, "source": matched[0]["id"], "digest": DIGEST, "name": NAME}
    (OUT / "recovery-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"checks": len(checks), "source": matched[0]["id"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
