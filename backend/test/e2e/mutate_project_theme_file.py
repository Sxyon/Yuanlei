"""S05隔离环境的合成文件变更与故障注入，禁止用于日常数据库。"""

import base64
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from yuxi.workspace.paths import user_workspace_dir


def main():
    """在服务实际POSIX挂载内修改同一合成文件，回执不携身份凭据。"""
    if urlsplit(os.environ["POSTGRES_URL"]).path != "/yuanlei_s05_evidence":
        raise RuntimeError("文件故障注入只允许S05隔离数据库")
    session = json.loads((Path(os.environ["YUXI_USER_DATA_DIR"]) / ".s05-session.json").read_text())
    project = session["projects"][0]
    target = user_workspace_dir(project["uid"]) / project["workdir_path"] / "survey.json"
    action = sys.argv[1]
    if action not in {"write", "missing", "symlink"}:
        raise ValueError("未知故障动作")
    if target.exists() or target.is_symlink():
        target.unlink()
    if action == "write":
        target.write_bytes(base64.b64decode(sys.argv[2], validate=True))
    elif action == "symlink":
        target.symlink_to("not-present.json")
    print(json.dumps({"action": action, "symlink": target.is_symlink()}))


if __name__ == "__main__":
    main()
