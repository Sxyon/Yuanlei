"""S06跨实例迁移的独立HTTP、PG、ZIP与Workdir对账及负向证据。"""

import hashlib
import io
import json
import os
import subprocess
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).parents[3]
OUT = Path(os.environ["THEME_EVIDENCE_OUTPUT"])
A_API = os.environ.get("THEME_EVIDENCE_A_API", "http://127.0.0.1:15064")
B_API = os.environ.get("THEME_EVIDENCE_B_API", "http://127.0.0.1:15065")
A = json.loads(Path(os.environ["THEME_EVIDENCE_A_SESSION"]).read_text())
B = json.loads(Path(os.environ["THEME_EVIDENCE_B_SESSION"]).read_text())
OUT.mkdir(parents=True, exist_ok=True)


def sha(raw):
    """统一字节摘要。"""
    return hashlib.sha256(raw).hexdigest()


def request(base, token, method, route, **kwargs):
    """返回真实HTTP状态与可公开JSON，负例不抛异常。"""
    response = httpx.request(
        method, base + route, headers={"Authorization": f"Bearer {token}"}, timeout=60, **kwargs
    )
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else None
    return response, body


def pg(db, sql):
    """独立PostgreSQL回读。"""
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "postgres", "-d", db, "-tAc", sql],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def docker_sha(container, file):
    """独立读取容器内文件摘要。"""
    result = subprocess.run(
        ["docker", "exec", container, "sha256sum", file], check=True, capture_output=True, text=True
    )
    return result.stdout.split()[0]


def rewrite(raw, member, update):
    """只改声明成员生成合法变体包，用于冲突与兼容负例。"""
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item)
            if item.filename == member:
                data = json.dumps(update(json.loads(data)), ensure_ascii=False).encode()
            target.writestr(item, data)
    return output.getvalue()


def negative(name, response, body, expected_status, expected_code):
    """记录负例，并断言失败原因来自目标校验而非偶然错误。"""
    code = body.get("detail", {}).get("code") if isinstance(body, dict) else None
    assert response.status_code == expected_status, (name, response.status_code, response.text[:300])
    assert code == expected_code, (name, code, response.text[:300])
    return {"case": name, "status": response.status_code, "code": code, "passed": True}


A_CATALOG = request(A_API, A["token"], "GET", "/api/theme-sources")[1]["sources"]
A_SOURCE = next(source for source in A_CATALOG if source["name"] == "S05-R2证据 · 调研 · 阅读工作室")
A_VERSION = next(version for version in A_SOURCE["versions"] if version["version"] == "3.1.0-r2")
A_PROJECT = A["projects"][0]
A_BINDING = request(A_API, A["token"], "GET", f"/api/projects/{A_PROJECT['id']}/theme")[1]

B_CATALOG = request(B_API, B["token"], "GET", "/api/theme-sources")[1]["sources"]
B_SOURCE = next(source for source in B_CATALOG if source["name"] == "B迁移草稿-UI")
B_VERSION = next(version for version in B_SOURCE["versions"] if version["version"] == "3.1.0-r2")
B1, B2 = B["projects"]
B1_BINDING = request(B_API, B["token"], "GET", f"/api/projects/{B1['id']}/theme")[1]
B2_BINDING = request(B_API, B["token"], "GET", f"/api/projects/{B2['id']}/theme")[1]

export = httpx.get(
    f"{A_API}/api/theme-versions/{A_VERSION['id']}/package",
    headers={"Authorization": f"Bearer {A['token']}"},
    timeout=30,
)
assert export.is_success
ORIGINAL = export.content
DIGEST = sha(ORIGINAL)
assert DIGEST == A_VERSION["digest"] == B_VERSION["digest"]

counts = {
    "A": {
        "sources": pg("yuanlei_s04_repair_evidence", "SELECT count(*) FROM project_theme_sources"),
        "versions": pg("yuanlei_s04_repair_evidence", "SELECT count(*) FROM project_theme_versions"),
        "bindings": pg("yuanlei_s04_repair_evidence", "SELECT count(*) FROM project_theme_bindings"),
    },
    "B": {
        "sources": pg("yuanlei_s06_evidence_b", "SELECT count(*) FROM project_theme_sources"),
        "versions": pg("yuanlei_s06_evidence_b", "SELECT count(*) FROM project_theme_versions"),
        "bindings": pg("yuanlei_s06_evidence_b", "SELECT count(*) FROM project_theme_bindings"),
    },
}
rows = {
    "A_version": pg(
        "yuanlei_s04_repair_evidence",
        f"SELECT version||'|'||digest||'|'||size||'|'||candidate_revision FROM project_theme_versions WHERE id='{A_VERSION['id']}'",
    ),
    "A_binding": pg(
        "yuanlei_s04_repair_evidence",
        f"SELECT version_id||'|'||generation||'|'||files::text FROM project_theme_bindings WHERE project_id='{A_PROJECT['id']}'",
    ),
    "B_source": pg(
        "yuanlei_s06_evidence_b",
        f"SELECT candidate_digest||'|'||candidate_revision||'|'||kind FROM project_theme_sources WHERE id='{B_SOURCE['id']}'",
    ),
    "B_version": pg(
        "yuanlei_s06_evidence_b",
        f"SELECT version||'|'||digest||'|'||size||'|'||candidate_revision FROM project_theme_versions WHERE id='{B_VERSION['id']}'",
    ),
    "B_binding": pg(
        "yuanlei_s06_evidence_b",
        f"SELECT version_id||'|'||generation||'|'||files::text FROM project_theme_bindings WHERE project_id='{B1['id']}'",
    ),
    "B_control_binding": pg(
        "yuanlei_s06_evidence_b",
        f"SELECT version_id||'|'||generation||'|'||files::text FROM project_theme_bindings WHERE project_id='{B2['id']}'",
    ),
}
files = {
    "A_store": docker_sha(
        "yuanlei-s04-repair", f"/tmp/s04-repair/theme-sources/{A_SOURCE['id']}/{A_VERSION['digest']}.zip"
    ),
    "B_store": docker_sha(
        "yuanlei-s06-b", f"/tmp/s06-b/theme-sources/{B_SOURCE['id']}/{B_VERSION['digest']}.zip"
    ),
}
assert files["A_store"] == files["B_store"] == DIGEST
# Workdir路径由真实用户目录生成；容器内读取实际文件摘要。
workdir = subprocess.run(
    [
        "docker",
        "exec",
        "yuanlei-s06-b",
        "sh",
        "-c",
        f"sha256sum /tmp/s06-b/user-data/shared/{B['uid']}/workspace/{B1['workdir']}/facts.json "
        f"/tmp/s06-b/user-data/shared/{B['uid']}/workspace/{B1['workdir']}/chart.png",
    ],
    check=True,
    capture_output=True,
    text=True,
).stdout.splitlines()
files["B_workdir_facts"], files["B_workdir_chart"] = (line.split()[0] for line in workdir)
preview_facts = request(
    B_API,
    B["token"],
    "POST",
    f"/api/projects/{B1['id']}/theme/preview-file",
    json={
        "source_id": B_SOURCE["id"],
        "revision": B_SOURCE["candidate_revision"],
        "expected_generation": B1_BINDING["generation"],
        "files": {"facts": "/facts.json", "chart": "/chart.png"},
        "alias": "facts",
    },
)[0]
preview_chart = request(
    B_API,
    B["token"],
    "POST",
    f"/api/projects/{B1['id']}/theme/preview-file",
    json={
        "source_id": B_SOURCE["id"],
        "revision": B_SOURCE["candidate_revision"],
        "expected_generation": B1_BINDING["generation"],
        "files": {"facts": "/facts.json", "chart": "/chart.png"},
        "alias": "chart",
    },
)[0]
assert preview_facts.content == b'{"origin": "B", "samples": 99, "note": "B\xe9\xa1\xb9\xe7\x9b\xae\xe7\x9c\x9f\xe5\xae\x9e\xe8\xb5\x84\xe6\x96\x99"}'
assert sha(preview_facts.content) == files["B_workdir_facts"]
assert sha(preview_chart.content) == files["B_workdir_chart"]

negatives = []
# 跨实例会话与目标来源授权。
cross_a = request(B_API, A["token"], "GET", "/api/theme-sources")[0]
assert cross_a.status_code == 401
negatives.append({"case": "A token on B", "status": 401, "code": None, "passed": True})
cross_b = request(A_API, B["token"], "GET", "/api/theme-sources")[0]
assert cross_b.status_code == 401
negatives.append({"case": "B token on A", "status": 401, "code": None, "passed": True})
foreign_source = request(
    B_API, B["token"], "POST", "/api/theme-imports", params={"digest": DIGEST, "source_id": A_SOURCE["id"], "expected_revision": 0}, content=ORIGINAL
)
negatives.append(negative("foreign source", foreign_source[0], foreign_source[1], 404, "source_denied"))
foreign_project = request(B_API, B["token"], "GET", f"/api/projects/{A_PROJECT['id']}/theme")
negatives.append(negative("foreign project", foreign_project[0], foreign_project[1], 404, "project_denied"))

# ZIP边界、兼容声明与预检摘要复核。
invalid = request(B_API, B["token"], "POST", "/api/theme-imports/preflight", content=b"not-a-zip")
negatives.append(negative("invalid zip", invalid[0], invalid[1], 422, "invalid_zip"))
unsupported = rewrite(ORIGINAL, "manifest.json", lambda value: {**value, "componentAbi": 4})
unsupported_result = request(
    B_API, B["token"], "POST", "/api/theme-imports/preflight", content=unsupported
)
negatives.append(negative("unsupported ABI", unsupported_result[0], unsupported_result[1], 422, "package_contract"))
variant = rewrite(ORIGINAL, "theme.json", lambda value: {**value, "name": "B同版本异字节"})
fingerprint = request(
    B_API, B["token"], "POST", "/api/theme-imports", params={"digest": DIGEST, "name": "指纹不符"}, content=variant
)
negatives.append(negative("preflight digest mismatch", fingerprint[0], fingerprint[1], 409, "preflight_changed"))
builtin = next(source for source in B_CATALOG if source["kind"] == "builtin" and source["status"] == "active")
readonly = request(
    B_API,
    B["token"],
    "POST",
    "/api/theme-imports",
    params={"digest": DIGEST, "source_id": builtin["id"], "expected_revision": 0},
    content=ORIGINAL,
)
negatives.append(negative("builtin target", readonly[0], readonly[1], 403, "builtin_readonly"))

# 既有草稿revision并发；版本冲突；同字节复用不新增版本。
stale = request(
    B_API,
    B["token"],
    "POST",
    "/api/theme-imports",
    params={"digest": DIGEST, "source_id": B_SOURCE["id"], "expected_revision": 0},
    content=ORIGINAL,
)
negatives.append(negative("stale candidate revision", stale[0], stale[1], 409, "candidate_conflict"))
conflict = request(
    B_API,
    B["token"],
    "POST",
    "/api/theme-imports",
    params={"digest": sha(variant), "source_id": B_SOURCE["id"], "expected_revision": 1},
    content=variant,
)
assert conflict[0].status_code == 200, conflict[0].text
assert conflict[1]["version_state"] == "same_version_different_bytes"
conflict_publish = request(
    B_API, B["token"], "POST", f"/api/theme-sources/{B_SOURCE['id']}/publish", json={"expected_revision": 2}
)
negatives.append(negative("same version different bytes", conflict_publish[0], conflict_publish[1], 409, "version_conflict"))
same = request(
    B_API,
    B["token"],
    "POST",
    "/api/theme-imports",
    params={"digest": DIGEST, "source_id": B_SOURCE["id"], "expected_revision": 2},
    content=ORIGINAL,
)
assert same[0].status_code == 200, same[0].text
assert same[1]["version_state"] == "published_same_bytes" and same[1]["reusable_version_id"] == B_VERSION["id"]
reuse = request(
    B_API, B["token"], "POST", f"/api/theme-sources/{B_SOURCE['id']}/publish", json={"expected_revision": 3}
)
assert reuse[0].status_code == 200 and reuse[1]["id"] == B_VERSION["id"]
assert pg("yuanlei_s06_evidence_b", f"SELECT count(*) FROM project_theme_versions WHERE source_id='{B_SOURCE['id']}'") == "1"

# 资料未绑定、错类型、缺失与旧generation。
base_preview = {
    "source_id": B_SOURCE["id"],
    "revision": 3,
    "expected_generation": B1_BINDING["generation"],
    "files": {"facts": "/facts.json", "chart": "/chart.png"},
    "alias": "facts",
}
for name, body, status, code in [
    ("unbound alias", {**base_preview, "files": {}}, 409, "file_unbound"),
    ("wrong JSON media", {**base_preview, "files": {"facts": "/chart.png"}}, 422, "invalid_json"),
    ("wrong PNG media", {**base_preview, "alias": "chart", "files": {"chart": "/facts.json"}}, 422, "invalid_png"),
    ("missing file", {**base_preview, "files": {"facts": "/missing.json"}}, 404, "file_missing"),
    ("old generation", {**base_preview, "expected_generation": 999}, 409, "binding_conflict"),
]:
    response = request(B_API, B["token"], "POST", f"/api/projects/{B1['id']}/theme/preview-file", json=body)
    negatives.append(negative(name, response[0], response[1], status, code))

# 写后核实：候选、不可变版本、绑定、存储与再导出。
post = {
    "source": pg(
        "yuanlei_s06_evidence_b",
        f"SELECT candidate_digest||'|'||candidate_revision FROM project_theme_sources WHERE id='{B_SOURCE['id']}'",
    ),
    "version": pg(
        "yuanlei_s06_evidence_b",
        f"SELECT digest||'|'||size FROM project_theme_versions WHERE id='{B_VERSION['id']}'",
    ),
    "binding": pg(
        "yuanlei_s06_evidence_b",
        f"SELECT version_id||'|'||generation||'|'||files::text FROM project_theme_bindings WHERE project_id='{B1['id']}'",
    ),
    "B1_http": B1_BINDING["binding"],
}
assert post["source"] == f"{DIGEST}|3"
assert post["version"] == f"{DIGEST}|{len(ORIGINAL)}"
assert post["B1_http"]["version_id"] == post["binding"].split("|")[0]
re_export = httpx.get(
    f"{B_API}/api/theme-versions/{B_VERSION['id']}/package",
    params={"project_id": B1["id"]},
    headers={"Authorization": f"Bearer {B['token']}"},
    timeout=30,
)
assert re_export.content == ORIGINAL and re_export.headers["x-theme-sha256"] == DIGEST

assert A_BINDING["generation"] == int(rows["A_binding"].split("|")[1])
assert B2_BINDING["binding"]["version_id"] == rows["B_control_binding"].split("|")[0]
report = {
    "instances": {
        "A": {"api": A_API, "db": "yuanlei_s04_repair_evidence", "source": A_SOURCE["id"], "version": A_VERSION["id"]},
        "B": {"api": B_API, "db": "yuanlei_s06_evidence_b", "source": B_SOURCE["id"], "version": B_VERSION["id"]},
    },
    "original": {"digest": DIGEST, "size": len(ORIGINAL)},
    "counts": counts,
    "pgRows": rows,
    "files": files,
    "preview": {
        "facts_sha256": sha(preview_facts.content),
        "facts_origin": json.loads(preview_facts.content)["origin"],
        "chart_sha256": sha(preview_chart.content),
    },
    "negative": negatives,
    "writeAfterVerify": {
        "candidate": post["source"],
        "version": post["version"],
        "bindingGeneration": B1_BINDING["generation"],
        "exportDigest": re_export.headers["x-theme-sha256"],
    },
}
(OUT / "http-pg-files.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps({"negatives": len(negatives), "digest": DIGEST, "B1_generation": B1_BINDING["generation"]}, ensure_ascii=False))
