"""S06重启等待超时后的独立浏览器回读与显式切回，不再次重启或修改A。"""

import json
import re
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

from project_theme_migration_browser import A, A_API, B, B_API, OUT, WEB_B, api, isolated_session, pg, sha256


def verify_reexport(version_id):
    """回读B原ZIP，与A真实下载原字节及响应摘要比较。"""
    raw = (OUT / "a-original.theme.zip").read_bytes()
    response = httpx.get(
        f"{B_API}/api/theme-versions/{version_id}/package",
        headers={"Authorization": f"Bearer {B['token']}"}, timeout=60,
    )
    response.raise_for_status()
    assert response.content == raw and response.headers["x-theme-sha256"] == sha256(raw)
    return sha256(response.content)


def main():
    """已重启B需从真实页面证明资料可读、旧版可恢复及原包一致。"""
    a_before = api(A_API, A["token"], f"/api/projects/{A['projects'][0]['id']}/theme")
    b1, b2 = B["projects"]
    before = api(B_API, B["token"], f"/api/projects/{b1['id']}/theme")
    control = api(B_API, B["token"], f"/api/projects/{b2['id']}/theme")
    version_id = before["binding"]["version_id"]
    raw = (OUT / "a-original.theme.zip").read_bytes()
    assert before["package"]["digest"] == sha256(raw)
    reexport_digest = verify_reexport(version_id)
    with sync_playwright() as playwright:
        executable = Path.home() / "Library/Caches/ms-playwright/chromium_headless_shell-1243"
        executable /= "chrome-headless-shell-mac-x64/chrome-headless-shell"
        browser = playwright.chromium.launch(headless=True, executable_path=str(executable))
        context, page = isolated_session(browser, WEB_B, B)
        page.goto(f"{WEB_B}/projects/{b1['id']}/dashboard")
        page.wait_for_function(
            "id => document.querySelector('.project-space')?.dataset.themeVersion === id", arg=version_id
        )
        page.get_by_role("link", name="项目证据", exact=True).click()
        page.get_by_text("B项目真实资料").first.wait_for()
        assert page.locator(".theme-host img").evaluate("img => img.complete && img.naturalWidth > 0")
        page.screenshot(path=OUT / "restart-browser-recovered.png", full_page=True)
        page.goto(f"{WEB_B}/projects?tab=themes")
        page.get_by_role("button", name="项目主题设置", exact=True).click()
        modal = page.locator(".ant-modal").filter(has_text="项目主题设置")
        modal.get_by_label("主题目标项目").click()
        page.get_by_text(b1["name"], exact=True).last.click()
        modal.get_by_label("主题发布版本").click()
        page.get_by_text("默认 · 项目管理 · 3.0.0", exact=True).last.click()
        modal.get_by_role("button", name="应用主题", exact=True).click()
        page.get_by_text(re.compile("选择已保存并核实")).wait_for()
        restored = api(B_API, B["token"], f"/api/projects/{b1['id']}/theme")
        assert restored["binding"]["version_id"] == B["default_version_id"]
        assert restored["generation"] == before["generation"] + 1
        page.keyboard.press("Escape")
        page.goto(f"{WEB_B}/projects/{b1['id']}/dashboard")
        page.wait_for_function(
            "id => document.querySelector('.project-space')?.dataset.themeVersion === id",
            arg=B["default_version_id"],
        )
        page.screenshot(path=OUT / "restart-browser-restored.png", full_page=True)
        browser.close()
    assert api(A_API, A["token"], f"/api/projects/{A['projects'][0]['id']}/theme") == a_before
    assert api(B_API, B["token"], f"/api/projects/{b2['id']}/theme") == control
    row = pg(
        "yuanlei_s06_evidence_b",
        f"SELECT version_id||'|'||generation FROM project_theme_bindings WHERE project_id='{b1['id']}'",
    )
    assert row == B["default_version_id"] + "|" + str(restored["generation"])
    report = {
        "restartBrowserRecovered": True,
        "targetJsonAndPngRead": True,
        "before": before["binding"],
        "restored": restored["binding"],
        "pgRestored": row,
        "AUnchangedDuringRecovery": True,
        "B2Unchanged": True,
        "reexportDigest": reexport_digest,
        "scope": "既有隔离证据入口，正式startup与migrator仍未验证",
    }
    (OUT / "restart-browser-review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"recovered": True, "restored": True, "AUnchanged": True}))


if __name__ == "__main__":
    main()
