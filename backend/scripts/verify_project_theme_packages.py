"""检查受信任样例ZIP与展开定义／资源同字节，不充当生产ZIP parser。"""

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from yuxi.services.project_theme_contract import ThemePackage


def verify(folder: Path) -> list[dict]:
    """样例通过正式模型，归档成员与工作文件保持一致。"""
    results = []
    for archive in sorted(folder.glob("*.theme.zip")):
        unpacked = folder / archive.name.removesuffix(".theme.zip")
        with ZipFile(archive) as package:
            model = ThemePackage.model_validate(
                {"manifest": json.loads(package.read("manifest.json")), "theme": json.loads(package.read("theme.json"))}
            )
            expected = {"manifest.json", "theme.json", *[a.path for a in model.manifest.assets.values()]}
            assert set(package.namelist()) == expected
            for name in expected:
                assert package.read(name) == (unpacked / name).read_bytes(), name
            for asset in model.manifest.assets.values():
                assert hashlib.sha256(package.read(asset.path)).hexdigest() == asset.sha256
        results.append(
            {
                "theme": model.theme.id,
                "pages": len(model.theme.pages),
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            }
        )
    assert results, "未找到主题包样例"
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    print(json.dumps(verify(parser.parse_args().folder), ensure_ascii=False))
