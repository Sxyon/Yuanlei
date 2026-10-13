"""不可信主题ZIP与资源的有界解析，不将成员展开到文件系统。"""

import hashlib
import io
import json
import stat
import struct
import zlib
import zipfile
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from yuxi.services.project_theme_contract import ThemePackage

MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_EXPANDED_BYTES = 32 * 1024 * 1024
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_MEMBERS = 128
MAX_PAGES = 32
MAX_BLOCKS_PER_PAGE = 64
MAX_IMAGE_PIXELS = 16_000_000
MAX_ALIASES = 64
MAX_ALIAS_LENGTH = 160


class ThemeError(Exception):
    """主题边界可公开的错误码与原因。"""

    def __init__(self, code: str, message: str, status: int = 422):
        """绑定当前用例的持久化或错误上下文。"""
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


@dataclass(frozen=True)
class ParsedPackage:
    """经校验的定义、原ZIP身份与声明资源字节。"""

    definition: ThemePackage
    digest: str
    size: int
    assets: dict[str, bytes]


def parse_json(raw: bytes):
    """JSON键必须唯一，避免维护、校验与宿主解释不同。"""

    def unique(pairs):
        """在每一层拒绝重复键。"""
        value = {}
        for key, item in pairs:
            if key in value:
                raise ThemeError("duplicate_json_key", "JSON存在重复字段")
            value[key] = item
        return value

    def reject_constant(_):
        """JSON不接受非有限数值。"""
        raise ThemeError("invalid_json", "JSON不接受非有限数值")

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ThemeError("invalid_json", "JSON编码、结构或深度不受支持") from exc


def validate_resource(raw: bytes, media: str) -> int:
    """核对实际资料类型与有界解码，复用于项目文件绑定。"""
    if len(raw) > MAX_MEMBER_BYTES:
        raise ThemeError("member_limit", "单个资料超过8 MiB", 413)
    if media == "application/json":
        parse_json(raw)
        return 0
    if media != "image/png":
        raise ThemeError("resource_type", "资料类型不受支持")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != "PNG":
                raise ThemeError("resource_type", "声明PNG的资料实际不是PNG")
            if image.width * image.height > MAX_IMAGE_PIXELS or image.n_frames != 1:
                raise ThemeError("image_limit", "PNG像素超过1600万或包含动画", 413)
            pixels = image.width * image.height
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
        return pixels
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ThemeError("invalid_png", "PNG内容损坏或无法安全解码") from exc


def member_chunks(raw: bytes, archive, member):
    """按压缩流实际输出读取，拒绝中心目录伪报长度隐藏展开量。"""
    # stdlib open核对本地名称及成员重叠；其read会按声明长度截断，因此不消费其正文。
    with archive.open(member):
        pass
    offset = member.header_offset
    if offset < 0 or offset + 30 > len(raw):
        raise ThemeError("invalid_zip", "ZIP成员头损坏")
    header = struct.unpack_from("<4sHHHHHIIIHH", raw, offset)
    if header[0] != b"PK\x03\x04" or header[2] != member.flag_bits or header[3] != member.compress_type:
        raise ThemeError("invalid_zip", "ZIP本地头与目录声明不一致")
    start = offset + 30 + header[9] + header[10]
    end = start + member.compress_size
    if start > len(raw) or end > len(raw):
        raise ThemeError("invalid_zip", "ZIP压缩内容不完整")
    payload = memoryview(raw)[start:end]
    size, crc = 0, 0
    inflater = zlib.decompressobj(-15) if member.compress_type == zipfile.ZIP_DEFLATED else None
    for position in range(0, len(payload), 64 * 1024):
        data = payload[position : position + 64 * 1024]
        while len(data):
            output = inflater.decompress(data, 64 * 1024) if inflater else bytes(data)
            data = inflater.unconsumed_tail if inflater else b""
            if output:
                size += len(output)
                crc = zlib.crc32(output, crc)
                yield output
    if inflater:
        while not inflater.eof:
            output = inflater.decompress(b"", 64 * 1024)
            if not output:
                raise ThemeError("invalid_zip", "ZIP压缩流未正常结束")
            size += len(output)
            crc = zlib.crc32(output, crc)
            yield output
        if inflater.unused_data:
            raise ThemeError("invalid_zip", "ZIP压缩流包含额外数据")
    if size != member.file_size or crc != member.CRC:
        raise ThemeError("member_integrity", "ZIP实际长度或CRC与声明不一致")


def parse_package(raw: bytes) -> ParsedPackage:
    """限制压缩与实际展开量，闭合成员、定义、资源及指纹。"""
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise ThemeError("archive_limit", "压缩包超过8 MiB", 413)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) > MAX_MEMBERS:
                raise ThemeError("member_count", "包成员超过128项", 413)
            names, contents, expanded = set(), {}, 0
            for member in members:
                name = member.orig_filename
                if (
                    name != member.filename
                    or "\x00" in name
                    or "\\" in name
                    or ":" in name
                    or any(part in ("", ".", "..") for part in name.split("/"))
                    or name.startswith("/")
                ):
                    raise ThemeError("member_path", "ZIP成员路径不合法")
                if name in names:
                    raise ThemeError("duplicate_member", "ZIP成员重复")
                names.add(name)
                mode = member.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG) or member.is_dir():
                    raise ThemeError("member_type", "ZIP只接受普通文件，拒绝符号链接及目录")
                if member.flag_bits & 1 or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ThemeError("compression_type", "不支持加密或该ZIP压缩方式")
                if member.file_size > MAX_MEMBER_BYTES:
                    raise ThemeError("member_limit", "单个包成员超过8 MiB", 413)
                if expanded + member.file_size > MAX_EXPANDED_BYTES:
                    raise ThemeError("expanded_limit", "展开内容超过32 MiB", 413)
                chunks, size = [], 0
                for chunk in member_chunks(raw, archive, member):
                    size += len(chunk)
                    expanded += len(chunk)
                    if size > MAX_MEMBER_BYTES:
                        raise ThemeError("member_limit", "实际成员展开超过8 MiB", 413)
                    if expanded > MAX_EXPANDED_BYTES:
                        raise ThemeError("expanded_limit", "实际展开内容超过32 MiB", 413)
                    chunks.append(chunk)
                contents[name] = b"".join(chunks)
            if not {"manifest.json", "theme.json"}.issubset(names):
                raise ThemeError("required_member", "包缺少manifest.json或theme.json")
            try:
                definition = ThemePackage.model_validate(
                    {
                        "manifest": parse_json(contents["manifest.json"]),
                        "theme": parse_json(contents["theme.json"]),
                    }
                )
            except ValidationError as exc:
                error = exc.errors(include_input=False)[0]
                location = ".".join(str(part) for part in error["loc"])
                raise ThemeError("package_contract", f"定义不符合契约：{location}（{error['type']}）") from exc
            if len(definition.theme.pages) > MAX_PAGES or any(
                len(page.blocks) > MAX_BLOCKS_PER_PAGE for page in definition.theme.pages
            ):
                raise ThemeError("layout_limit", "主题超过32页或每页64块", 413)
            expected = {"manifest.json", "theme.json", *[a.path for a in definition.manifest.assets.values()]}
            if names != expected:
                raise ThemeError("undeclared_member", "ZIP包含未声明成员")
            aliases = [*definition.manifest.files, *definition.manifest.assets]
            if len(aliases) > MAX_ALIASES:
                raise ThemeError("alias_limit", "文件及资源声明合计超过64项", 413)
            if any(len(alias) > MAX_ALIAS_LENGTH or "\x00" in alias for alias in aliases):
                raise ThemeError("alias_identity", "逻辑alias超过160字符或包含数据库不支持的NUL")
            assets, image_pixels = {}, 0
            for alias, asset in definition.manifest.assets.items():
                content = contents[asset.path]
                if hashlib.sha256(content).hexdigest() != asset.sha256:
                    raise ThemeError("asset_digest", f"资源指纹不匹配：{alias}")
                image_pixels += validate_resource(content, asset.mediaType)
                if image_pixels > MAX_IMAGE_PIXELS:
                    raise ThemeError("image_total_limit", "包内PNG解码像素合计超过1600万", 413)
                assets[alias] = content
            return ParsedPackage(definition, hashlib.sha256(raw).hexdigest(), len(raw), assets)
    except (
        zipfile.BadZipFile,
        EOFError,
        NotImplementedError,
        RuntimeError,
        ValueError,
        zlib.error,
        struct.error,
    ) as exc:
        raise ThemeError("invalid_zip", "ZIP损坏、CRC错误或无法解析") from exc
