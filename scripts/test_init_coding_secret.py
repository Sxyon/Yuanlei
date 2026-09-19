"""初始化脚本编码密钥生成/校验的回归测试。"""

from __future__ import annotations

import base64
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "init.sh"


def _run_ensure(workdir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(workdir / "init.sh"), "--ensure-coding-secret"],
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
    )


def _coding_key(workdir: Path) -> str:
    match = re.search(r"^YUXI_CODING_CREDENTIAL_KEY=(.*)$", (workdir / ".env").read_text(), re.M)
    assert match is not None
    return match.group(1).strip()


def _decoded_length(value: str) -> int:
    return len(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))


class InitCodingSecretTests(unittest.TestCase):
    """缺少/非法密钥时生成 32 字节 base64url；已有合法值保持不变。"""

    def setUp(self) -> None:
        if shutil.which("bash") is None or shutil.which("openssl") is None:
            self.skipTest("需要 bash 与 openssl")
        self._tmp = tempfile.TemporaryDirectory()
        self.workdir = Path(self._tmp.name)
        shutil.copy(SCRIPT, self.workdir / "init.sh")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_missing_key_is_generated_and_idempotent(self) -> None:
        (self.workdir / ".env").write_text("JWT_SECRET_KEY=placeholder\nYUXI_CODING_CREDENTIAL_KEY=\n")

        first = _run_ensure(self.workdir)
        self.assertEqual(first.returncode, 0, first.stderr)
        generated = _coding_key(self.workdir)
        self.assertEqual(_decoded_length(generated), 32)

        second = _run_ensure(self.workdir)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(_coding_key(self.workdir), generated)
        self.assertNotIn("generating", second.stdout)

    def test_invalid_hex_key_is_replaced(self) -> None:
        hex_value = "ab" * 32
        (self.workdir / ".env").write_text(f"YUXI_CODING_CREDENTIAL_KEY={hex_value}\n")

        result = _run_ensure(self.workdir)

        self.assertEqual(result.returncode, 0, result.stderr)
        replaced = _coding_key(self.workdir)
        self.assertNotEqual(replaced, hex_value)
        self.assertEqual(_decoded_length(replaced), 32)


if __name__ == "__main__":
    unittest.main()
