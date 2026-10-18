"""S06审查回归：连续导入与切回新建后的真实写后响应丢失恢复。"""

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from project_theme_migration_browser import B, B_API, OUT, WEB_B, api, isolated_session, pg, sha256, wait_health


def main():
    """只在隔离B写合成来源，回读DOM、PG与原包，不修改项目绑定。"""
    stamp = str(time.time_ns())
    names = [f"S06审查连续导入-{stamp}", f"S06审查切回新建-{stamp}"]
    raw = (OUT / "a-original.theme.zip").read_bytes()
    digest = sha256(raw)
    wait_health(B_API)
    before = [api(B_API, B["token"], f"/api/projects/{p['id']}/theme")["binding"] for p in B["projects"]]
    with sync_playwright() as playwright:
        executable = os.environ.get(
            "THEME_EVIDENCE_CHROMIUM",
            str(
                Path.home()
                / "Library/Caches/ms-playwright/chromium_headless_shell-1243"
                / "chrome-headless-shell-mac-x64/chrome-headless-shell"
            ),
        )
        browser = playwright.chromium.launch(headless=True, executable_path=executable)
        context, page = isolated_session(browser, WEB_B, B)
        page.goto(f"{WEB_B}/projects?tab=themes")
        button = page.get_by_role("button", name="导入主题包", exact=True)
        modal = page.locator(".ant-modal").filter(has_text="导入主题包")
        for index, name in enumerate(names):
            button.click()
            modal.wait_for()
            modal.get_by_label("导入主题包ZIP").set_input_files(str(OUT / "a-original.theme.zip"))
            modal.get_by_text("只读预检", exact=True).wait_for()
            if index:
                modal.get_by_text("写入既有主题草稿", exact=True).click()
                modal.get_by_label("导入目标既有主题").click()
                page.locator(".ant-select-item-option", has_text=names[0]).click()
                modal.get_by_text("新建我的主题草稿（默认）", exact=True).click()
                cdp = context.new_cdp_session(page)
                cdp.send(
                    "Fetch.enable", {"patterns": [{"urlPattern": "*api/theme-imports?*", "requestStage": "Response"}]}
                )

                def lost(event):
                    """请求真实提交后仅丢弃响应，不模拟API结果。"""
                    cdp.send("Fetch.failRequest", {"requestId": event["requestId"], "errorReason": "Failed"})

                cdp.on("Fetch.requestPaused", lost)
            modal.get_by_label("导入目标主题名称").fill(name)
            modal.get_by_role("button", name="确认保存草稿", exact=True).click()
            modal.wait_for(state="hidden", timeout=60000)
            page.get_by_text("导入草稿已保存", exact=False).wait_for()
            assert not button.is_disabled()
            assert name in page.locator(".source[aria-current]").inner_text()
            page.screenshot(
                path=OUT / ("after-repeat-import.png" if not index else "after-new-target-recovery.png"), full_page=True
            )
        browser.close()
    sources = api(B_API, B["token"], "/api/theme-sources")["sources"]
    saved = []
    for name in names:
        matches = [source for source in sources if source["name"] == name]
        assert len(matches) == 1
        source = matches[0]
        assert source["candidate_digest"] == digest and source["candidate_revision"] == 1 and not source["versions"]
        row = pg(
            "yuanlei_s06_evidence_b",
            f"SELECT candidate_digest||'|'||candidate_revision FROM project_theme_sources WHERE id='{source['id']}'",
        )
        assert row == digest + "|1"
        saved.append({"id": source["id"], "revision": 1, "digest": digest, "publishedVersions": 0, "pg": row})
    after = [api(B_API, B["token"], f"/api/projects/{p['id']}/theme")["binding"] for p in B["projects"]]
    assert after == before
    report = {
        "checks": [
            "连续导入不残留忙碌态",
            "既有目标切回新建后响应丢失定位新来源",
            "排除另一个同摘要不同名称来源",
            "每次只创建一个来源且未发布",
            "既有草稿修订不变",
            "项目绑定不变",
        ],
        "sources": saved,
        "bindingsUnchanged": True,
    }
    (OUT / "import-review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"checks": len(report["checks"]), "bindingsUnchanged": True}))


if __name__ == "__main__":
    main()
