"""生产ZIP与独立文件域的真实字节边界验例。"""

import hashlib
import io
import json
import os
import stat
import zipfile
from pathlib import Path

import pytest

from yuxi.themes.packages import (
    MAX_ARCHIVE_BYTES,
    MAX_MEMBER_BYTES,
    MAX_MEMBERS,
    MAX_PAGES,
    ThemeError,
    parse_package,
    validate_resource,
)
from yuxi.themes.store import ThemeStore

BUILTIN = Path(__file__).parents[2] / "package/yuxi/themes/builtin"


def members(name="default"):
    """独立读取已审阅S03包成员。"""
    with zipfile.ZipFile(BUILTIN / f"{name}.theme.zip") as archive:
        return [(info.filename, archive.read(info)) for info in archive.infolist()]


def pack(items):
    """负向样本不使用生产打包或解析实现。"""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in items:
            archive.writestr(name, raw)
    return output.getvalue()


def rejected(raw, code):
    """只接受guard的正确错误码。"""
    with pytest.raises(ThemeError) as error:
        parse_package(raw)
    assert error.value.code == code


def test_original_packages_keep_bytes_and_assets():
    for name in ["default", "research"]:
        raw = (BUILTIN / f"{name}.theme.zip").read_bytes()
        parsed = parse_package(raw)
        assert parsed.digest == hashlib.sha256(raw).hexdigest()
        assert len(parsed.definition.theme.pages) == 3
        for alias, content in parsed.assets.items():
            assert hashlib.sha256(content).hexdigest() == parsed.definition.manifest.assets[alias].sha256


@pytest.mark.parametrize("name", ["../escape", "/absolute", "assets/../evil", "assets\\evil", "assets//evil", "a:evil"])
def test_member_path_rejected(name):
    rejected(pack([*members(), (name, b"{}")]), "member_path")


def test_duplicate_and_symlink_members():
    rejected(pack([*members(), members()[0]]), "duplicate_member")
    link = zipfile.ZipInfo("assets/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    rejected(pack([*members(), (link, b"../outside")]), "member_type")


def test_undeclared_member_and_resource_digest():
    rejected(pack([*members(), ("assets/unlisted.json", b"{}")]), "undeclared_member")
    items = members("research")
    rejected(pack([(name, b"bad" if name.endswith(".png") else raw) for name, raw in items]), "asset_digest")


def test_json_duplicate_keys_nonfinite_and_wrong_png():
    rejected(
        pack(
            [
                (name, b'{"formatVersion":1,"formatVersion":1}' if name == "manifest.json" else raw)
                for name, raw in members()
            ]
        ),
        "duplicate_json_key",
    )
    for raw in [b'{"x":NaN}', b'{"x":Infinity}']:
        with pytest.raises(ThemeError, match="非有限"):
            validate_resource(raw, "application/json")
    with pytest.raises(ThemeError) as error:
        validate_resource(b"not a png", "image/png")
    assert error.value.code == "invalid_png"


def test_compressed_expanded_and_member_capacity_have_different_reasons():
    rejected(b"x" * (MAX_ARCHIVE_BYTES + 1), "archive_limit")
    rejected(pack([*members(), ("assets/big.json", b"x" * (MAX_MEMBER_BYTES + 1))]), "member_limit")
    raw = pack([*members(), *[(f"assets/{i}.json", b"x" * MAX_MEMBER_BYTES) for i in range(5)]])
    assert len(raw) < MAX_ARCHIVE_BYTES
    rejected(raw, "expanded_limit")
    rejected(pack([(f"assets/{i}", b"x") for i in range(MAX_MEMBERS + 1)]), "member_count")


def test_page_budget_and_unsupported_compression():
    items = dict(members())
    definition = json.loads(items["theme.json"])
    base = definition["pages"][0]
    definition["pages"] = [{**base, "id": f"p-{i}"} for i in range(MAX_PAGES + 1)]
    for page in definition["pages"]:
        page["blocks"] = [{k: v for k, v in page["blocks"][0].items() if k != "action"}]
    items["theme.json"] = json.dumps(definition).encode()
    rejected(pack(list(items.items())), "layout_limit")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_BZIP2) as archive:
        for name, raw in members():
            archive.writestr(name, raw)
    rejected(output.getvalue(), "compression_type")


def test_store_no_clobber_corruption_symlink_and_restart(tmp_path):
    source = "de18671d-3ef8-41b7-a65d-3a0c9de41951"
    raw = (BUILTIN / "default.theme.zip").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    store = ThemeStore(tmp_path / "themes")
    store.put(source, raw, digest)
    store.put(source, raw, digest)
    assert ThemeStore(tmp_path / "themes").read(source, digest) == raw
    target = tmp_path / "themes" / source / f"{digest}.zip"
    assert target.stat().st_mode & 0o222 == 0
    os.chmod(target, 0o600)
    target.write_bytes(b"tampered")
    with pytest.raises(ThemeError) as error:
        store.put(source, raw, digest)
    assert error.value.code == "package_corrupt"
    target.unlink()
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(ThemeError) as error:
        store.read(source, digest)
    assert error.value.code == "package_unreadable"


def test_store_source_directory_symlink(tmp_path):
    source = "de18671d-3ef8-41b7-a65d-3a0c9de41951"
    root = tmp_path / "themes"
    root.mkdir()
    (tmp_path / "outside").mkdir()
    (root / source).symlink_to(tmp_path / "outside", target_is_directory=True)
    raw = (BUILTIN / "default.theme.zip").read_bytes()
    with pytest.raises(OSError):
        ThemeStore(root).put(source, raw, hashlib.sha256(raw).hexdigest())
    assert not list((tmp_path / "outside").iterdir())


def test_alias_block_and_image_budgets():
    """各布局与解码预算分别在正确原因上拒绝。"""
    from PIL import Image
    from yuxi.themes.packages import MAX_ALIASES, MAX_BLOCKS_PER_PAGE

    items = dict(members())
    manifest = json.loads(items["manifest.json"])
    manifest["files"] = {f"file{i}": "application/json" for i in range(MAX_ALIASES + 1)}
    items["manifest.json"] = json.dumps(manifest).encode()
    rejected(pack(list(items.items())), "alias_limit")
    items = dict(members())
    theme = json.loads(items["theme.json"])
    base = theme["pages"][0]["blocks"][0]
    theme["pages"][0]["blocks"] = [
        {**{k: v for k, v in base.items() if k != "action"}, "id": f"block{i}"} for i in range(MAX_BLOCKS_PER_PAGE + 1)
    ]
    items["theme.json"] = json.dumps(theme).encode()
    rejected(pack(list(items.items())), "layout_limit")
    image = io.BytesIO()
    Image.new("RGB", (4000, 4001)).save(image, format="PNG")
    with pytest.raises(ThemeError) as error:
        validate_resource(image.getvalue(), "image/png")
    assert error.value.code == "image_limit"
    image = io.BytesIO()
    Image.new("RGB", (3000, 3000)).save(image, format="PNG")
    content = image.getvalue()
    items = dict(members())
    manifest = json.loads(items["manifest.json"])
    manifest["assets"] = {
        f"img{i}": {
            "path": f"assets/img{i}.png",
            "mediaType": "image/png",
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for i in range(2)
    }
    items["manifest.json"] = json.dumps(manifest).encode()
    items.update({f"assets/img{i}.png": content for i in range(2)})
    rejected(pack(list(items.items())), "image_total_limit")


def test_false_declared_length_cannot_hide_zip_expansion():
    """独立修改ZIP头，证明stdlib截断不能替代真实展开限额。"""
    import struct
    import zlib

    items = dict(members())
    manifest = json.loads(items["manifest.json"])
    manifest["assets"] = {
        "hidden": {
            "path": "assets/hidden.json",
            "mediaType": "application/json",
            "sha256": hashlib.sha256(b"{}").hexdigest(),
        }
    }
    items["manifest.json"] = json.dumps(manifest).encode()
    items["assets/hidden.json"] = b"{}" + b"x" * (MAX_MEMBER_BYTES + 1)
    raw = bytearray(pack(list(items.items())))
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        offset = archive.getinfo("assets/hidden.json").header_offset
    central = raw.rfind(b"PK\x01\x02")
    for location, value in [
        (offset + 14, zlib.crc32(b"{}")),
        (offset + 22, 2),
        (central + 16, zlib.crc32(b"{}")),
        (central + 24, 2),
    ]:
        struct.pack_into("<I", raw, location, value)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.read("assets/hidden.json") == b"{}"
    assert len(raw) < MAX_ARCHIVE_BYTES
    rejected(bytes(raw), "member_limit")


def test_alias_identity_capacity_and_nul_rejection():
    for alias in ["x" * 161, "bad\x00alias"]:
        items = dict(members())
        manifest = json.loads(items["manifest.json"])
        manifest["files"] = {alias: "application/json"}
        items["manifest.json"] = json.dumps(manifest).encode()
        rejected(pack(list(items.items())), "alias_identity")


def test_storage_root_and_source_identity_fail_closed(tmp_path):
    """相对根和非UUID身份在文件副作用前拒绝。"""
    with pytest.raises(ThemeError) as error:
        ThemeStore(Path("relative/theme-root"))
    assert error.value.code == "storage_configuration"
    store = ThemeStore(tmp_path / "themes")
    with pytest.raises(ThemeError) as error:
        store.source_fd("../outside", create=True)
    assert error.value.code == "source_identity"
    assert not store.root.exists()
