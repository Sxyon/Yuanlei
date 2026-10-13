"""用真实样例及接近容量边界的有效包测定解析成本。"""

import hashlib
import io
import json
import resource
import time
import zipfile
from pathlib import Path

from yuxi.themes.packages import MAX_ARCHIVE_BYTES, MAX_MEMBER_BYTES, ThemeError, parse_package


def measure(raw, name):
    """读取实际定义及资源，并记录压缩量、展开量和耗时。"""
    start = time.perf_counter()
    parsed = parse_package(raw)
    elapsed = time.perf_counter() - start
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        expanded = sum(member.file_size for member in archive.infolist())
    return {
        "name": name,
        "compressed_bytes": len(raw),
        "expanded_bytes": expanded,
        "assets": len(parsed.assets),
        "pages": len(parsed.definition.theme.pages),
        "seconds": round(elapsed, 4),
        "digest": hashlib.sha256(raw).hexdigest(),
    }


def main():
    """测量结果用于配额依据，失败不生成成功记录。"""
    root = Path(__file__).parents[1] / "package/yuxi/themes/builtin"
    results = [measure((root / f"{name}.theme.zip").read_bytes(), name) for name in ("default", "research")]
    with zipfile.ZipFile(root / "default.theme.zip") as archive:
        manifest = json.loads(archive.read("manifest.json"))
        theme = json.loads(archive.read("theme.json"))
    content = json.dumps({"boundary": "x" * (MAX_MEMBER_BYTES - 2048)}).encode()
    manifest["assets"] = {
        f"part{i}": {
            "path": f"assets/part{i}.json",
            "mediaType": "application/json",
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for i in range(4)
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("theme.json", json.dumps(theme))
        for i in range(4):
            archive.writestr(f"assets/part{i}.json", content)
    results.append(measure(output.getvalue(), "four-near-8MiB-json-assets"))
    reasons = {}
    try:
        parse_package(b"x" * (MAX_ARCHIVE_BYTES + 1))
    except ThemeError as exc:
        reasons["raw"] = exc.code
    with zipfile.ZipFile(output, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("assets/overflow.json", content)
    try:
        parse_package(output.getvalue())
    except ThemeError as exc:
        reasons["expanded"] = exc.code
    assert reasons == {"raw": "archive_limit", "expanded": "expanded_limit"}
    print(
        json.dumps(
            {
                "accepted": results,
                "rejection_reasons": reasons,
                "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
