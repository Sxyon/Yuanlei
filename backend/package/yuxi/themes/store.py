"""独立服务文件域的fd-relative、no-follow和原子无覆盖包存储。"""

import hashlib
import os
import re
import uuid
from pathlib import Path

from yuxi.themes.packages import MAX_ARCHIVE_BYTES, ThemeError
from yuxi.utils.paths import open_directory_fd, open_regular_file_fd


class ThemeStore:
    """按来源身份隔离候选快照与不可变ZIP，Agent不持有该域。"""

    def __init__(self, root: Path | None = None):
        """绑定独立服务根，拒绝依赖进程工作目录的相对配置。"""
        self.root = root or Path(os.environ.get("YUXI_THEME_SOURCES_DIR", "/app/theme-sources"))
        if not self.root.is_absolute():
            raise ThemeError("storage_configuration", "主题文件域必须配置绝对服务路径", 503)

    def source_fd(self, source_id: str, *, create: bool = False) -> int:
        """仅以服务UUID打开来源目录，逐段拒绝符号链接。"""
        try:
            valid = str(uuid.UUID(source_id)) == source_id
        except ValueError:
            valid = False
        if not valid:
            raise ThemeError("source_identity", "来源持久身份不合法", 409)
        root_fd = open_directory_fd(Path(self.root.anchor), tuple(self.root.parts[1:]), create=create)
        try:
            if create and os.geteuid() == 0:
                os.fchown(root_fd, 1000, 1000)
                os.fchmod(root_fd, 0o700)
            fd = open_directory_fd(root_fd, (source_id,), create=create)
            if create and os.geteuid() == 0:
                os.fchown(fd, 1000, 1000)
            return fd
        finally:
            os.close(root_fd)

    def read(self, source_id: str, digest: str) -> bytes:
        """回读同来源包字节并核对完整摘要，损坏显式失败。"""
        self.check_digest(digest)
        try:
            fd = self.source_fd(source_id)
            try:
                with open_regular_file_fd(fd, (f"{digest}.zip",)) as (file_fd, metadata):
                    if metadata.st_size > MAX_ARCHIVE_BYTES:
                        raise ThemeError("package_corrupt", "已保存主题包大小不合法", 409)
                    raw = bytearray()
                    while chunk := os.read(file_fd, 64 * 1024):
                        raw.extend(chunk)
                        if len(raw) > MAX_ARCHIVE_BYTES:
                            raise ThemeError("package_corrupt", "已保存主题包超过容量", 409)
            finally:
                os.close(fd)
        except FileNotFoundError as exc:
            raise ThemeError("package_missing", "该版本主题文件缺失；原项目选择保留", 409) from exc
        except (PermissionError, OSError) as exc:
            raise ThemeError("package_unreadable", "主题文件无法安全读取；请维护对账", 409) from exc
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ThemeError("package_corrupt", "主题包摘要不匹配；原项目选择保留", 409)
        return bytes(raw)

    def put(self, source_id: str, raw: bytes, digest: str) -> None:
        """完整fsync后原子链接，无覆盖发布；PG失败只留完整孤儿。"""
        self.check_digest(digest)
        if len(raw) > MAX_ARCHIVE_BYTES or hashlib.sha256(raw).hexdigest() != digest:
            raise ThemeError("package_digest", "写入包与摘要不一致")
        fd = self.source_fd(source_id, create=True)
        temporary = f".pending-{uuid.uuid4()}"
        file_fd = None
        try:
            file_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            view = memoryview(raw)
            while view:
                view = view[os.write(file_fd, view) :]
            os.fchmod(file_fd, 0o444)
            if os.geteuid() == 0:
                os.fchown(file_fd, 1000, 1000)
            os.fsync(file_fd)
            os.close(file_fd)
            file_fd = None
            try:
                os.link(temporary, f"{digest}.zip", src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            except FileExistsError:
                self.read(source_id, digest)
            os.unlink(temporary, dir_fd=fd)
            os.fsync(fd)
        finally:
            if file_fd is not None:
                os.close(file_fd)
            try:
                os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass
            os.close(fd)

    @staticmethod
    def check_digest(digest: str) -> None:
        """存储键只接受完整SHA-256。"""
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ThemeError("package_digest", "包摘要不合法")
