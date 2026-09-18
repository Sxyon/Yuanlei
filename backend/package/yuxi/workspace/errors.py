"""Workspace 文件边界的中立异常。"""


class FileTransferLimitError(ValueError):
    """受信任文件传输超过调用方声明的字节上限。"""


class WorkspaceContainsSymlinkError(PermissionError):
    """删除目标包含只能由个人空间确认流程清理的符号链接。"""
