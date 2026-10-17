"""S06重启回读：重启B后读取健康、就绪、A/B绑定与跨实例token。"""

import json
import os
import subprocess
import time
from pathlib import Path

import httpx

OUT = Path(os.environ["THEME_EVIDENCE_OUTPUT"])
A_API = os.environ.get("THEME_EVIDENCE_A_API", "http://127.0.0.1:15064")
B_API = os.environ.get("THEME_EVIDENCE_B_API", "http://127.0.0.1:15065")
B_CONTAINER = os.environ.get("THEME_EVIDENCE_B_CONTAINER", "yuanlei-s06-b")
A = json.loads(Path(os.environ["THEME_EVIDENCE_A_SESSION"]).read_text())
B = json.loads(Path(os.environ["THEME_EVIDENCE_B_SESSION"]).read_text())


def binding(base, token, project_id):
    """读取准确绑定；故障也保留公开状态。"""
    response = httpx.get(
        f"{base}/api/projects/{project_id}/theme",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    body = response.json() if response.is_success else None
    return {
        "status": response.status_code,
        "generation": body.get("generation") if body else None,
        "version": body.get("binding", {}).get("version_id") if body and body.get("binding") else None,
    }


def main():
    """不修改主题数据，只重启证据服务并回读真实结果。"""
    subprocess.run(["docker", "restart", B_CONTAINER], check=True, capture_output=True)
    for _ in range(90):
        try:
            if httpx.get(f"{B_API}/api/system/health", timeout=2).is_success:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    else:
        raise AssertionError("B重启后未恢复health")
    ready = httpx.get(f"{B_API}/api/system/ready", timeout=30)
    b1, b2 = B["projects"][0], B["projects"][1]
    report = {
        "generatedBy": "backend/test/e2e/project_theme_migration_restart.py",
        "restart": "done",
        "health": httpx.get(f"{B_API}/api/system/health", timeout=30).json(),
        "ready": {
            "httpStatus": ready.status_code,
            "body": ready.json(),
            "note": "A/B沿用既有project_theme_app证据入口，运行真实routers、认证、PG、migrator与主题文件域，但不执行server.main完整lifespan；startup not_complete不代表主题链路不可用，本证据以真实API成功、绑定回读和文件hash闭合。",
        },
        "B1": binding(B_API, B["token"], b1["id"]),
        "B2": binding(B_API, B["token"], b2["id"]),
        "A": binding(A_API, A["token"], A["projects"][0]["id"]),
        "crossTokens": {
            "AonB": httpx.get(
                f"{B_API}/api/theme-sources", headers={"Authorization": f"Bearer {A['token']}"}, timeout=30
            ).status_code,
            "BonA": httpx.get(
                f"{A_API}/api/theme-sources", headers={"Authorization": f"Bearer {B['token']}"}, timeout=30
            ).status_code,
        },
    }
    (OUT / "restart-ready.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"health": report["health"].get("status"), "ready": ready.status_code, "B1": report["B1"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
