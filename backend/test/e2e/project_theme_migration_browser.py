"""S06跨实例迁移的真实浏览器证据：A导出、B预检草稿、目标预览、发布、分配、重启与切回。"""

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parents[3]
OUT = Path(os.environ["THEME_EVIDENCE_OUTPUT"])
A_API = os.environ.get("THEME_EVIDENCE_A_API", "http://127.0.0.1:15064")
B_API = os.environ.get("THEME_EVIDENCE_B_API", "http://127.0.0.1:15065")
WEB_A = os.environ.get("THEME_EVIDENCE_WEB_A", "http://127.0.0.1:15174")
WEB_B = os.environ.get("THEME_EVIDENCE_WEB_B", "http://127.0.0.1:15175")
IMPORT_NAME = os.environ.get("THEME_EVIDENCE_IMPORT_NAME", "B迁移草稿-UI")
TOPIC_TITLE = f"B跨实例议题标题 · {IMPORT_NAME}"
A = json.loads(Path(os.environ["THEME_EVIDENCE_A_SESSION"]).read_text())
B = json.loads(Path(os.environ["THEME_EVIDENCE_B_SESSION"]).read_text())
OUT.mkdir(parents=True, exist_ok=True)

checks, requests, errors = [], [], []


def check(value, title):
    """任一检查失败立即终止，未执行项不记通过。"""
    assert value, title
    checks.append(title)


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def api(base, token, route, method="GET", body=None):
    """真实HTTP读写，不使用产品内部函数替代。"""
    response = httpx.request(
        method, base + route, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=60
    )
    assert response.is_success, f"{route} -> {response.status_code} {response.text[:300]}"
    return response.json() if response.content else None


def pg(db, sql):
    """独立PG回读，不把HTTP返回当最终事实。"""
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "postgres", "-d", db, "-tAc", sql],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def docker_sha(container, file):
    """独立读取容器存储文件摘要。"""
    result = subprocess.run(
        ["docker", "exec", container, "sha256sum", file], check=True, capture_output=True, text=True
    )
    return result.stdout.split()[0]


def wait_health(base):
    """证据服务只提供真实路由而非完整startup lifespan，按liveness等待后以真实API回读。"""
    for _ in range(90):
        try:
            if httpx.get(base + "/api/system/health", timeout=2).is_success:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise AssertionError("隔离实例重启后未恢复健康")


def isolated_session(browser, origin, credentials):
    """独立前端源与真实登录；代理目标由各Vite实例固定到对应隔离API。"""
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("response", lambda response: requests.append(
        {"origin": origin, "path": urlsplit(response.url).path, "method": response.request.method, "status": response.status}
    ) if "/api/" in response.url else None)
    page.goto(f"{origin}/login")
    page.get_by_label("登录账号").wait_for()
    page.wait_for_load_state("networkidle")
    page.evaluate("sessionStorage.setItem('redirect', '/projects?tab=themes')")
    agreement = page.locator('input[type="checkbox"]')
    if agreement.count():
        agreement.first.check()
    page.get_by_label("登录账号").fill(credentials["uid"])
    page.get_by_label("密码").fill(credentials["password"])
    page.locator('button[type="submit"]').click()
    page.wait_for_function("() => location.pathname !== '/login'", timeout=30000)
    return context, page


def main():
    """按真实A→B链路执行并留下截图、DOM与独立对账。"""
    a_catalog = api(A_API, A["token"], "/api/theme-sources")
    a_source = next(source for source in a_catalog["sources"] if source["name"] == "S05-R2证据 · 调研 · 阅读工作室")
    a_version = next(version for version in a_source["versions"] if version["version"] == "3.1.0-r2")
    a_project = A["projects"][0]
    a_binding_before = api(A_API, A["token"], f"/api/projects/{a_project['id']}/theme")
    a_source_before = pg(
        "yuanlei_s04_repair_evidence",
        f"SELECT candidate_digest||'|'||candidate_revision FROM project_theme_sources WHERE id='{a_source['id']}'",
    )
    a_before = {
        "sources": pg("yuanlei_s04_repair_evidence", "SELECT count(*) FROM project_theme_sources"),
        "versions": pg("yuanlei_s04_repair_evidence", "SELECT count(*) FROM project_theme_versions"),
        "binding": pg(
            "yuanlei_s04_repair_evidence",
            "SELECT version_id||'|'||generation||'|'||files::text FROM project_theme_bindings "
            f"WHERE project_id='{a_project['id']}'",
        ),
    }

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
        try:
            a_context, page_a = isolated_session(browser, WEB_A, A)
            page_a.goto(f"{WEB_A}/projects?tab=themes")
            page_a.get_by_text("来源目录", exact=True).wait_for()
            page_a.get_by_text("我的主题", exact=True).click()
            page_a.locator(".source", has_text=a_source["name"]).click()
            page_a.get_by_role("button", name="已发布版本", exact=True).click()
            a_version_row = page_a.locator(".version", has_text=a_version["version"])
            a_version_row.wait_for()
            a_version_row.get_by_role("button", name="包成员", exact=True).click()
            package_modal = page_a.locator(".ant-modal").filter(has_text="原包成员与导出说明")
            package_modal.wait_for()
            package_text = package_modal.inner_text()
            check(
                "facts" in package_text and "chart" in package_text and "不承诺自动脱敏" in package_text,
                "A导出前展示包成员与不携内容",
            )
            page_a.wait_for_timeout(600)
            page_a.screenshot(path=OUT / "a-package-details-1440.png", full_page=True)
            package_modal.get_by_role("button", name=re.compile(r"关\s*闭")).click()
            package_modal.wait_for(state="hidden")
            download_path = OUT / "a-original.theme.zip"
            with page_a.expect_download(timeout=30000) as download_info:
                a_version_row.get_by_role("button", name="导出原包", exact=True).click()
            download_info.value.save_as(download_path)
            suggested = download_info.value.suggested_filename
            check(
                suggested.endswith(".theme.zip") and a_version["version"] in suggested,
                "A下载文件名由版本安全生成",
            )
            exported = download_path.read_bytes()
            check(sha256(exported) == a_version["digest"], "A导出原包摘要与版本记录一致")
            check(
                a_version["digest"] in page_a.locator(".ant-alert-success").inner_text(),
                "A下载完成提示展示原包SHA-256",
            )
            check(
                sha256(exported)
                == docker_sha(
                    "yuanlei-s04-repair", f"/tmp/s04-repair/theme-sources/{a_source['id']}/{a_version['digest']}.zip"
                ),
                "A原包字节与容器存储逐字节一致",
            )
            page_a.screenshot(path=OUT / "a-export-1440.png", full_page=True)
            a_context.close()

            counts_before = {
                "sources": pg("yuanlei_s06_evidence_b", "SELECT count(*) FROM project_theme_sources"),
                "versions": pg("yuanlei_s06_evidence_b", "SELECT count(*) FROM project_theme_versions"),
                "bindings": pg("yuanlei_s06_evidence_b", "SELECT count(*) FROM project_theme_bindings"),
            }
            b1, b2 = B["projects"][0], B["projects"][1]
            b1_before = api(B_API, B["token"], f"/api/projects/{b1['id']}/theme")
            b2_before = api(B_API, B["token"], f"/api/projects/{b2['id']}/theme")
            topic = api(
                B_API,
                B["token"],
                f"/api/projects/{b1['id']}/governance/topics",
                method="POST",
                body={"title": TOPIC_TITLE, "summary": "B自己的业务内容", "source_channel": "project"},
            )
            check(topic["title"] == TOPIC_TITLE, "B真实业务议题已创建")

            b_context, page_b = isolated_session(browser, WEB_B, B)
            page_b.goto(f"{WEB_B}/projects?tab=themes")
            page_b.get_by_text("来源目录", exact=True).wait_for()
            page_b.get_by_role("button", name="导入主题包", exact=True).click()
            import_modal = page_b.locator(".ant-modal").filter(has_text="导入主题包")
            import_modal.wait_for()
            import_modal.locator('input[aria-label="导入主题包ZIP"]').set_input_files(str(download_path))
            import_modal.get_by_text("只读预检", exact=True).wait_for()
            preflight_text = import_modal.inner_text()
            check(
                a_version["version"] in preflight_text and a_version["digest"] in preflight_text,
                "B预检展示版本与原包摘要",
            )
            check("facts" in preflight_text and "chart" in preflight_text, "B预检展示目标项目文件alias要求")
            check("ABI 3" in preflight_text and "format 1" in preflight_text, "B预检展示format与ABI兼容信息")
            after_preflight = {
                "sources": pg("yuanlei_s06_evidence_b", "SELECT count(*) FROM project_theme_sources"),
                "versions": pg("yuanlei_s06_evidence_b", "SELECT count(*) FROM project_theme_versions"),
                "bindings": pg("yuanlei_s06_evidence_b", "SELECT count(*) FROM project_theme_bindings"),
            }
            check(after_preflight == counts_before, "B只读预检不创建来源、版本或绑定")
            (OUT / "b-preflight.txt").write_text(preflight_text)
            page_b.screenshot(path=OUT / "b-preflight-1440.png", full_page=True)
            import_modal.get_by_role("button", name=re.compile(r"取\s*消")).click()
            page_b.get_by_role("button", name="放弃并关闭", exact=True).click()
            import_modal.wait_for(state="hidden")
            after_cancel = {
                "sources": pg("yuanlei_s06_evidence_b", "SELECT count(*) FROM project_theme_sources"),
                "versions": pg("yuanlei_s06_evidence_b", "SELECT count(*) FROM project_theme_versions"),
            }
            check(
                after_cancel["sources"] == counts_before["sources"]
                and after_cancel["versions"] == counts_before["versions"],
                "取消预检不产生来源或候选写入",
            )

            page_b.get_by_role("button", name="导入主题包", exact=True).click()
            import_modal.wait_for()
            import_modal.locator('input[aria-label="导入主题包ZIP"]').set_input_files(str(download_path))
            import_modal.get_by_text("只读预检", exact=True).wait_for()
            before_ids = {source["id"] for source in api(B_API, B["token"], "/api/theme-sources")["sources"]}
            import_modal.get_by_label("导入目标主题名称").fill(IMPORT_NAME)
            import_modal.get_by_role("button", name="确认保存草稿", exact=True).click()
            page_b.get_by_text(re.compile("导入草稿已保存")).wait_for(timeout=30000)
            imported_catalog = api(B_API, B["token"], "/api/theme-sources")
            matches = [
                source for source in imported_catalog["sources"]
                if source["name"] == IMPORT_NAME and source["id"] not in before_ids
            ]
            check(len(matches) == 1, "B本次导入只创建一个准确来源，排除历史同名身份")
            imported = matches[0]
            check(
                imported["candidate_revision"] == 1 and imported["candidate_digest"] == a_version["digest"],
                "B导入定位准确草稿修订与原摘要",
            )
            check(not imported["versions"], "B导入只保存草稿，未自动发布")
            check(
                "3.1.0-r2" in page_b.get_by_label("编辑草稿JSON定义").input_value(),
                "B编辑器显示导入草稿定义",
            )
            page_b.screenshot(path=OUT / "b-imported-draft-1440.png", full_page=True)
            page_b.get_by_role("button", name="导入主题包", exact=True).click()
            import_modal.wait_for()
            check(import_modal.is_visible(), "成功导入后可再次打开导入")
            import_modal.locator(".ant-modal-close").click()
            import_modal.wait_for(state="hidden")

            page_b.get_by_role("button", name="预览已保存草稿", exact=True).click()
            preview_modal = page_b.locator(".ant-modal").filter(has_text="选择预览项目")
            preview_modal.wait_for()
            preview_modal.get_by_label("主题预览项目").click()
            page_b.get_by_text(b1["name"], exact=True).last.click()
            preview_modal.get_by_label("预览文件 facts").fill("/facts.json")
            preview_modal.get_by_label("预览文件 chart").fill("/chart.png")
            preview_modal.get_by_role("button", name="开始只读预览", exact=True).click()
            page_b.wait_for_function("() => location.search.includes('theme_preview_source=')", timeout=30000)
            page_b.locator(".preview-notice").wait_for()
            page_b.wait_for_function(
                "expected => document.querySelector('.project-space')?.dataset.persistedThemeVersion === expected",
                arg=b1_before["binding"]["version_id"],
            )
            project_space = page_b.locator(".project-space")
            check(project_space.get_attribute("data-theme-mode") == "preview", "B草稿预览进入只读模式")
            check(
                project_space.get_attribute("data-persisted-theme-version") == b1_before["binding"]["version_id"],
                "预览不改变B持久主题选择",
            )
            page_b.get_by_role("link", name="项目证据", exact=True).click()
            page_b.get_by_text("B项目真实资料").first.wait_for()
            check(
                page_b.locator(".theme-host img").evaluate("img => img.complete && img.naturalWidth > 0"),
                "B预览读取B自己的PNG资料",
            )
            check("B项目真实资料" in project_space.inner_text(), "B预览读取B自己的JSON资料")
            page_b.screenshot(path=OUT / "b-preview-1440.png", full_page=True)
            page_b.get_by_role("button", name="结束预览", exact=True).click()
            page_b.wait_for_function("() => !location.search.includes('theme_preview_source')")

            page_b.goto(f"{WEB_B}/projects?tab=themes")
            page_b.get_by_text("我的主题", exact=True).click()
            page_b.locator(".source", has_text=IMPORT_NAME).click()
            page_b.get_by_role("button", name="发布新版本", exact=True).click()
            page_b.locator(".ant-popconfirm-buttons button").last.click()
            page_b.get_by_text(re.compile("已发布 " + re.escape(IMPORT_NAME))).wait_for(timeout=30000)
            published_catalog = api(B_API, B["token"], "/api/theme-sources")
            published_source = next(source for source in published_catalog["sources"] if source["id"] == imported["id"])
            b_version = next(version for version in published_source["versions"] if version["version"] == "3.1.0-r2")
            check(b_version["digest"] == a_version["digest"], "B直接发布生成相同原包摘要")
            check(
                pg("yuanlei_s06_evidence_b", "SELECT count(*) FROM project_theme_versions")
                == str(int(counts_before["versions"]) + 1),
                "B发布只新增一条不可变版本",
            )
            page_b.screenshot(path=OUT / "b-published-1440.png", full_page=True)

            published_row = page_b.locator(".version", has_text="3.1.0-r2")
            published_row.get_by_role("button", name="分配到项目", exact=True).click()
            selection_modal = page_b.locator(".ant-modal").filter(has_text="项目主题设置")
            selection_modal.wait_for()
            selection_modal.get_by_label("主题目标项目").click()
            page_b.get_by_text(b1["name"], exact=True).last.click()
            selection_modal.get_by_label("文件绑定 facts").wait_for()
            selection_modal.get_by_label("文件绑定 facts").fill("/facts.json")
            selection_modal.get_by_label("文件绑定 chart").fill("/chart.png")
            page_b.wait_for_function(
                """() => [...document.querySelectorAll('.theme-select button')]
                .some(button => button.textContent.includes('应用主题') && !button.disabled)"""
            )
            selection_modal.get_by_role("button", name="应用主题", exact=True).click()
            page_b.get_by_text(re.compile("选择已保存并核实")).wait_for(timeout=30000)
            b1_after = api(B_API, B["token"], f"/api/projects/{b1['id']}/theme")
            b2_after = api(B_API, B["token"], f"/api/projects/{b2['id']}/theme")
            check(
                b1_after["generation"] == b1_before["generation"] + 1
                and b1_after["binding"]["version_id"] == b_version["id"],
                "B明确分配后推进唯一绑定",
            )
            check(
                b2_after["binding"]["version_id"] == b2_before["binding"]["version_id"]
                and b2_after["generation"] == b2_before["generation"],
                "B对照项目选择未改变",
            )
            check(
                pg("yuanlei_s06_evidence_b", f"SELECT generation FROM project_theme_bindings WHERE project_id='{b1['id']}'")
                == str(b1_after["generation"]),
                "B绑定generation与PG一致",
            )
            page_b.keyboard.press("Escape")

            page_b.goto(f"{WEB_B}/projects/{b1['id']}/dashboard")
            page_b.locator(".project-space").wait_for()
            page_b.wait_for_function(
                "expected => document.querySelector('.project-space')?.dataset.themeVersion === expected",
                arg=b_version["id"],
            )
            check(
                page_b.locator(".project-space").get_attribute("data-theme-version") == b_version["id"],
                "B项目页读取准确已分配版本",
            )
            page_b.get_by_role("link", name="项目证据", exact=True).click()
            page_b.get_by_text("B项目真实资料").first.wait_for()
            page_b.get_by_role("link", name="课题", exact=True).click()
            page_b.get_by_text(TOPIC_TITLE, exact=True).wait_for()
            check(True, "B项目页展示B自己的业务议题")
            page_b.get_by_text(TOPIC_TITLE, exact=True).click()
            page_b.get_by_role("button", name="编辑正文", exact=True).click()
            edit_modal = page_b.locator(".ant-modal").filter(has_text="修改原因")
            edit_modal.get_by_label("课题正文", exact=True).fill("B迁移后真实办理正文")
            edit_modal.get_by_label("课题修改原因", exact=True).fill("S06隔离迁移审查")
            edit_modal.get_by_role("button", name=re.compile(r"保\s*存")).click()
            edit_modal.wait_for(state="hidden")
            page_b.get_by_text("B迁移后真实办理正文", exact=True).first.wait_for()
            saved_topic = api(B_API, B["token"], f"/api/projects/{b1['id']}/governance/topics/{topic['id']}")
            check(saved_topic["summary"] == "B迁移后真实办理正文", "B准确议题办理后HTTP回读持久正文")
            page_b.get_by_role("button", name="返回目录", exact=True).click()
            page_b.get_by_text(TOPIC_TITLE, exact=True).wait_for()
            check(
                page_b.locator(".project-space").get_attribute("data-theme-version") == b_version["id"],
                "办理返回保持B已分配主题",
            )
            page_b.screenshot(path=OUT / "b-applied-1440.png", full_page=True)

            subprocess.run(["docker", "restart", "yuanlei-s06-b"], check=True, capture_output=True)
            wait_health(B_API)
            page_b.reload()
            page_b.locator(".project-space").wait_for()
            page_b.wait_for_function(
                "expected => document.querySelector('.project-space')?.dataset.themeVersion === expected",
                arg=b_version["id"],
            )
            check(
                page_b.locator(".project-space").get_attribute("data-theme-version") == b_version["id"],
                "B重启后准确版本选择保持",
            )
            page_b.get_by_role("link", name="项目证据", exact=True).click()
            page_b.get_by_text("B项目真实资料").first.wait_for()
            check(True, "B重启后业务与资料仍可读取")

            page_b.goto(f"{WEB_B}/projects?tab=themes")
            page_b.get_by_role("button", name="项目主题设置", exact=True).click()
            restore_modal = page_b.locator(".ant-modal").filter(has_text="项目主题设置")
            restore_modal.wait_for()
            restore_modal.get_by_label("主题目标项目").click()
            page_b.get_by_text(b1["name"], exact=True).last.click()
            restore_modal.get_by_label("主题发布版本").click()
            page_b.get_by_text("默认 · 项目管理 · 3.0.0", exact=True).last.click()
            page_b.wait_for_function(
                """() => [...document.querySelectorAll('.theme-select button')]
                .some(button => button.textContent.includes('应用主题') && !button.disabled)"""
            )
            restore_modal.get_by_role("button", name="应用主题", exact=True).click()
            page_b.get_by_text(re.compile("选择已保存并核实")).wait_for(timeout=30000)
            restored = api(B_API, B["token"], f"/api/projects/{b1['id']}/theme")
            check(
                restored["binding"]["version_id"] == B["default_version_id"]
                and restored["generation"] == b1_after["generation"] + 1,
                "B显式切回旧主题并推进generation",
            )
            page_b.keyboard.press("Escape")
            page_b.goto(f"{WEB_B}/projects/{b1['id']}/dashboard")
            page_b.locator(".project-space").wait_for()
            page_b.wait_for_function(
                "expected => document.querySelector('.project-space')?.dataset.themeVersion === expected",
                arg=B["default_version_id"],
            )
            check(
                page_b.locator(".project-space").get_attribute("data-theme-version") == B["default_version_id"],
                "B切回后读取旧主题版本",
            )
            page_b.screenshot(path=OUT / "b-restored-1440.png", full_page=True)
            b_context.close()

            a_binding_after = api(A_API, A["token"], f"/api/projects/{a_project['id']}/theme")
            a_source_after = pg(
                "yuanlei_s04_repair_evidence",
                f"SELECT candidate_digest||'|'||candidate_revision FROM project_theme_sources WHERE id='{a_source['id']}'",
            )
            check(a_source_after == a_source_before, "A导出源候选摘要与修订不变")
            a_after = {
                "sources": pg("yuanlei_s04_repair_evidence", "SELECT count(*) FROM project_theme_sources"),
                "versions": pg("yuanlei_s04_repair_evidence", "SELECT count(*) FROM project_theme_versions"),
                "binding": pg(
                    "yuanlei_s04_repair_evidence",
                    "SELECT version_id||'|'||generation||'|'||files::text FROM project_theme_bindings "
                    f"WHERE project_id='{a_project['id']}'",
                ),
            }
            check(a_after == a_before, "A来源、版本与项目绑定在迁移后不变")
            check(
                a_binding_after["generation"] == a_binding_before["generation"]
                and a_binding_after["package"]["digest"] == a_binding_before["package"]["digest"],
                "A项目当前主题及摘要不变",
            )

            b_export = httpx.get(
                f"{B_API}/api/theme-versions/{b_version['id']}/package",
                params={"project_id": b1["id"]},
                headers={"Authorization": f"Bearer {B['token']}"},
                timeout=30,
            )
            check(b_export.is_success, "B发布版本可再次导出")
            check(sha256(b_export.content) == sha256(exported), "B发布后再导出与A原包字节一致")
            check(
                docker_sha("yuanlei-s06-b", f"/tmp/s06-b/theme-sources/{published_source['id']}/{b_version['digest']}.zip")
                == a_version["digest"],
                "B发布版本文件与A原包摘要一致",
            )
            check(b_export.headers.get("x-theme-sha256") == a_version["digest"], "B导出响应摘要与A原包一致")
            check(not errors, "浏览器无页面脚本错误")
        finally:
            browser.close()

    report = {
        "checks": checks, "requests": requests, "errors": errors,
        "sha256": sha256(exported), "importedSourceId": imported["id"],
    }
    (OUT / "browser-checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"checked": len(checks), "sha256": report["sha256"], "errors": errors}, ensure_ascii=False))


if __name__ == "__main__":
    main()
