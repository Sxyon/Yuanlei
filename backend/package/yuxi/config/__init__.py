import os
import tempfile
from pathlib import Path


def get_int_env(name: str, default: int, *, minimum: int = 1) -> int:
    """读取有下界的整数环境变量，配置非法时显式失败。"""
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw_value!r}") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be >= {minimum}, got {value}")
    return value


def get_legacy_storage_dir() -> Path:
    """读取仅供一次性迁移使用的历史广域存储目录。"""
    return Path(os.getenv("YUXI_LEGACY_STORAGE_DIR", "legacy-saves"))


def get_runtime_dir() -> Path:
    """读取可丢弃日志与缓存使用的当前进程运行目录。"""
    configured = os.getenv("YUXI_RUNTIME_DIR")
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / f"yuxi-runtime-{os.getpid()}"


def get_skill_data_dir() -> Path:
    """读取共享与个人 Skill 持久源目录。"""
    configured = os.getenv("YUXI_SKILL_DATA_DIR")
    return Path(configured) if configured else Path("skill-sources")


def get_skill_projection_dir() -> Path:
    """读取用户授权 Skill 只读投影目录。"""
    configured = os.getenv("YUXI_SKILL_PROJECTION_DIR")
    return Path(configured) if configured else Path("skill-projections")


def get_user_data_dir() -> Path:
    """读取用户级实时文件持久目录。"""
    return Path(os.getenv("YUXI_USER_DATA_DIR", "user-data"))


def __getattr__(name: str):
    """按需加载用户配置，避免轻量路径配置触发业务模型导入。"""
    if name in {"UserConfig", "UserConfigSchema"}:
        from .user import UserConfig, UserConfigSchema

        return {"UserConfig": UserConfig, "UserConfigSchema": UserConfigSchema}[name]
    raise AttributeError(name)


__all__ = [
    "UserConfig",
    "UserConfigSchema",
    "get_int_env",
    "get_runtime_dir",
    "get_legacy_storage_dir",
    "get_skill_data_dir",
    "get_skill_projection_dir",
    "get_user_data_dir",
]
