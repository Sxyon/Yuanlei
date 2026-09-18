"""上游同步报告脚本的事实解析与漂移检查测试。"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.yuanlei_upstream_report import (
    BASELINE_PATH,
    build_report,
    check,
    main,
    parse_name_status,
    render_report,
)


class ParseNameStatusTest(unittest.TestCase):
    def test_parses_modify_add_and_rename(self) -> None:
        text = "M\tbackend/a.py\nA\tdocs/new.md\nR100\told.py\tnew.py\n"
        self.assertEqual(
            parse_name_status(text),
            {
                "backend/a.py": "M",
                "docs/new.md": "A",
                "old.py": "R",
                "new.py": "R",
            },
        )

    def test_ignores_blank_lines(self) -> None:
        self.assertEqual(parse_name_status("\n"), {})


class UpstreamReportRepositoryTest(unittest.TestCase):
    """在临时 Git 仓库上验证报告与漂移检查，不依赖真实上游网络。"""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.upstream = self.root / "upstream"
        self.upstream.mkdir()
        self._git(self.upstream, "init", "-b", "main")
        self._configure(self.upstream)
        (self.upstream / "README.md").write_text("# Yuxi\n", encoding="utf-8")
        (self.upstream / "README.en.md").write_text("# Yuxi EN\n", encoding="utf-8")
        (self.upstream / "shared.py").write_text(
            "# yuanlei coupling\nvalue = 1\n", encoding="utf-8"
        )
        (self.upstream / "upstream_only.py").write_text("x = 1\n", encoding="utf-8")
        self._git(self.upstream, "add", "-A")
        self._git(self.upstream, "commit", "-m", "init")
        self.base_commit = self._head(self.upstream)

        self.fork = self.root / "fork"
        subprocess.run(
            ["git", "clone", str(self.upstream), str(self.fork)],
            check=True,
            capture_output=True,
        )
        self._configure(self.fork)
        (self.fork / "README.yuxi.md").write_bytes(
            (self.upstream / "README.md").read_bytes()
        )
        (self.fork / "README.yuxi.en.md").write_bytes(
            (self.upstream / "README.en.md").read_bytes()
        )
        baseline = {
            "yuanlei_version": "0.1.0",
            "upstream_repository": str(self.upstream),
            "upstream_version": "v0.7.3",
            "upstream_commit": self.base_commit,
            "upstream_commit_date": "2026-09-14",
            "synced_at": "2026-09-18",
        }
        baseline_path = self.fork / BASELINE_PATH
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps(baseline, ensure_ascii=False), encoding="utf-8"
        )
        (self.fork / "README.md").write_text(
            f"# 元垒\n\n基于 Yuxi v0.7.3 @ {self.base_commit[:8]}\n",
            encoding="utf-8",
        )
        (self.fork / "README.en.md").write_text(
            f"# Yuanlei\n\nBased on Yuxi v0.7.3 @ {self.base_commit[:8]}\n",
            encoding="utf-8",
        )
        self._git(self.fork, "add", "-A")
        self._git(self.fork, "commit", "-m", "fork baseline")
        self.ref = "refs/remotes/origin/main"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _git(self, repo: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        return result.stdout

    def _configure(self, repo: Path) -> None:
        self._git(repo, "config", "user.email", "test@example.com")
        self._git(repo, "config", "user.name", "Test")

    def _head(self, repo: Path) -> str:
        return self._git(repo, "rev-parse", "HEAD").strip()

    def _commit_upstream(self, message: str) -> None:
        self._git(self.upstream, "add", "-A")
        self._git(self.upstream, "commit", "-m", message)

    def test_check_passes_on_synced_fork(self) -> None:
        self.assertEqual(check(self.fork, self.ref), [])

    def test_check_detects_mirror_drift(self) -> None:
        (self.fork / "README.yuxi.md").write_text("# tampered\n", encoding="utf-8")
        problems = check(self.fork, self.ref)
        self.assertTrue(any("README.yuxi.md" in problem for problem in problems))

    def test_check_detects_english_readme_baseline_drift(self) -> None:
        (self.fork / "README.en.md").write_text(
            "# Yuanlei EN\n\nYuxi v0.7.2 @ deadbeef\n", encoding="utf-8"
        )
        problems = check(self.fork, self.ref)
        self.assertTrue(any("README.en.md" in problem for problem in problems))

    def test_check_detects_baseline_drift(self) -> None:
        (self.upstream / "upstream_only.py").write_text("x = 2\n", encoding="utf-8")
        self._commit_upstream("upstream moves ahead")
        self._git(self.fork, "fetch", "origin")
        self.assertEqual(check(self.fork, self.ref), [])
        baseline_path = self.fork / BASELINE_PATH
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline["upstream_commit"] = self._head(self.upstream)
        baseline_path.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
        problems = check(self.fork, self.ref)
        self.assertTrue(any("merge-base" in problem for problem in problems))

    def test_report_marks_overlap_and_yuanlei_coupling(self) -> None:
        (self.fork / "shared.py").write_text(
            "# yuanlei coupling\nvalue = 2\n", encoding="utf-8"
        )
        self._git(self.fork, "add", "-A")
        self._git(self.fork, "commit", "-m", "yuanlei changes shared.py")
        (self.upstream / "shared.py").write_text(
            "# yuanlei coupling\nvalue = 3\n", encoding="utf-8"
        )
        (self.upstream / "upstream_only.py").write_text("x = 3\n", encoding="utf-8")
        self._commit_upstream("upstream changes shared.py")
        self._git(self.fork, "fetch", "origin")

        report = build_report(self.fork, self.ref, commit_limit=10)
        self.assertIn("shared.py", report.overlap)
        self.assertIn("shared.py", report.coupled)
        self.assertNotIn("upstream_only.py", report.coupled)
        rendered = render_report(report, commit_limit=10, file_limit=100)
        self.assertIn("## 共同修改", rendered)
        self.assertIn("## 高危：上游触碰的 yuanlei 耦合文件", rendered)

    def test_report_detects_rename_conflict(self) -> None:
        (self.fork / "shared.py").write_text(
            "# yuanlei coupling\nvalue = 8\n", encoding="utf-8"
        )
        self._git(self.fork, "add", "-A")
        self._git(self.fork, "commit", "-m", "yuanlei changes shared.py")
        self._git(self.upstream, "mv", "shared.py", "renamed.py")
        self._commit_upstream("upstream renames shared.py")
        self._git(self.fork, "fetch", "origin")

        report = build_report(self.fork, self.ref, commit_limit=10)
        self.assertIn("shared.py", report.overlap)

    def test_cli_check_exit_codes(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--repo", str(self.fork), "--upstream-ref", self.ref, "--check"])
        self.assertEqual(code, 0)
        self.assertIn("检查通过", output.getvalue())

        (self.fork / "README.yuxi.en.md").write_text("tampered\n", encoding="utf-8")
        with contextlib.redirect_stdout(output):
            code = main(["--repo", str(self.fork), "--upstream-ref", self.ref, "--check"])
        self.assertEqual(code, 1)
        self.assertIn("检查失败", output.getvalue())

    def test_render_report_uses_placeholder_for_empty_lists(self) -> None:
        (self.upstream / "upstream_only.py").write_text("x = 4\n", encoding="utf-8")
        self._commit_upstream("upstream only")
        self._git(self.fork, "fetch", "origin")
        report = build_report(self.fork, self.ref, commit_limit=10)
        rendered = render_report(report, commit_limit=10, file_limit=100)
        self.assertIn("- 无", rendered)
        self.assertIn("元垒决策（0）", rendered)


if __name__ == "__main__":
    unittest.main()
