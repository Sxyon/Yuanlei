#!/usr/bin/env python3
"""生成元垒与上游 Yuxi 的差异报告，并检查基线与 README 镜像漂移。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

UPSTREAM_REMOTE = "upstream"
UPSTREAM_REF = "refs/remotes/upstream/main"
BASELINE_PATH = Path("docs/develop-guides/yuanlei/baseline.json")
UPSTREAM_DECISIONS_PREFIX = "docs/develop-guides/decisions/"
YUANLEI_DECISIONS_PREFIX = "docs/develop-guides/yuanlei/decisions/"
MIRRORS = (
    ("README.yuxi.md", "README.md"),
    ("README.yuxi.en.md", "README.en.md"),
)


class ReportError(RuntimeError):
    """无法读取真实的 Git 或基线事实。"""


def _run(repo: Path, *args: str, binary: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=not binary,
    )


def git(repo: Path, *args: str) -> str:
    result = _run(repo, *args)
    if result.returncode != 0:
        raise ReportError(result.stderr.strip() or f"git {' '.join(args)} 失败")
    return result.stdout


def try_git(repo: Path, *args: str) -> str | None:
    result = _run(repo, *args)
    if result.returncode != 0:
        return None
    return result.stdout


def git_bytes(repo: Path, *args: str) -> bytes:
    result = _run(repo, *args, binary=True)
    if result.returncode != 0:
        raise ReportError(result.stderr.decode().strip() or f"git {' '.join(args)} 失败")
    return result.stdout


def parse_name_status(text: str) -> dict[str, str]:
    """把 `git diff --name-status` 输出解析为 路径 -> 状态码；重命名同时记录两侧路径。"""

    changes: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0][0]
        if status in {"R", "C"} and len(parts) >= 3:
            changes.setdefault(parts[1], status)
            changes[parts[2]] = status
        elif len(parts) >= 2:
            changes[parts[1]] = status
    return changes


def resolve_merge_base(repo: Path, upstream_ref: str) -> str:
    return git(repo, "merge-base", "HEAD", upstream_ref).strip()


def ahead_count(repo: Path, base: str, ref: str) -> int:
    return len(git(repo, "rev-list", f"{base}..{ref}").splitlines())


def commits_between(repo: Path, base: str, ref: str, limit: int) -> list[str]:
    lines = git(repo, "log", "--oneline", "--no-decorate", f"{base}..{ref}").splitlines()
    return lines[:limit]


def changed_files(repo: Path, base: str, ref: str) -> dict[str, str]:
    return parse_name_status(git(repo, "diff", "--name-status", base, ref))


def load_baseline(repo: Path) -> dict:
    path = repo / BASELINE_PATH
    if not path.is_file():
        raise ReportError(f"缺少同步基线：{BASELINE_PATH}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReportError(f"{BASELINE_PATH} 不是合法 JSON：{exc}") from exc


def mirror_problems(repo: Path, baseline: dict) -> list[str]:
    """检查 README 镜像是否与基线 commit 处上游原文逐字一致。"""

    problems: list[str] = []
    commit = baseline.get("upstream_commit", "")
    if not commit:
        return ["baseline.json 缺少 upstream_commit"]
    for mirror, upstream_path in MIRRORS:
        mirror_path = repo / mirror
        if not mirror_path.is_file():
            problems.append(f"{mirror} 缺失")
            continue
        expected = git_bytes(repo, "show", f"{commit}:{upstream_path}")
        if mirror_path.read_bytes() != expected:
            problems.append(f"{mirror} 与上游 {commit}:{upstream_path} 不一致")
    return problems


def baseline_problems(repo: Path, upstream_ref: str, baseline: dict) -> list[str]:
    problems: list[str] = []
    base = resolve_merge_base(repo, upstream_ref)
    if baseline.get("upstream_commit") != base:
        problems.append(
            f"baseline.json upstream_commit={baseline.get('upstream_commit')} "
            f"与 merge-base={base} 不一致"
        )
    version = baseline.get("upstream_version", "")
    short = str(baseline.get("upstream_commit", ""))[:8]
    for readme_name in ("README.md", "README.en.md"):
        readme_path = repo / readme_name
        if not readme_path.is_file():
            problems.append(f"{readme_name} 缺失")
            continue
        readme = readme_path.read_text(encoding="utf-8")
        if version and f"Yuxi {version}" not in readme:
            problems.append(f"{readme_name} 未展示上游版本 Yuxi {version}")
        if short and short not in readme:
            problems.append(f"{readme_name} 未展示上游 commit {short}")
    return problems


@dataclass
class SyncReport:
    upstream_ref: str
    upstream_head: str
    base: str
    ours_ahead: int
    upstream_ahead: int
    ours_commits: list[str] = field(default_factory=list)
    upstream_commits: list[str] = field(default_factory=list)
    ours_files: dict[str, str] = field(default_factory=dict)
    upstream_files: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def overlap(self) -> list[str]:
        return sorted(set(self.ours_files) & set(self.upstream_files))

    @property
    def upstream_decision_files(self) -> list[str]:
        return sorted(p for p in self.upstream_files if p.startswith(UPSTREAM_DECISIONS_PREFIX))

    @property
    def yuanlei_decision_files(self) -> list[str]:
        return sorted(p for p in self.ours_files if p.startswith(YUANLEI_DECISIONS_PREFIX))


def build_report(repo: Path, upstream_ref: str, commit_limit: int) -> SyncReport:
    baseline = load_baseline(repo)
    base = resolve_merge_base(repo, upstream_ref)
    report = SyncReport(
        upstream_ref=upstream_ref,
        upstream_head=git(repo, "rev-parse", upstream_ref).strip(),
        base=base,
        ours_ahead=ahead_count(repo, base, "HEAD"),
        upstream_ahead=ahead_count(repo, base, upstream_ref),
        ours_commits=commits_between(repo, base, "HEAD", commit_limit),
        upstream_commits=commits_between(repo, base, upstream_ref, commit_limit),
        ours_files=changed_files(repo, base, "HEAD"),
        upstream_files=changed_files(repo, base, upstream_ref),
        problems=mirror_problems(repo, baseline) + baseline_problems(repo, upstream_ref, baseline),
    )
    return report


def _render_files(files: dict[str, str], limit: int) -> list[str]:
    lines: list[str] = []
    for path, status in sorted(files.items()):
        lines.append(f"- `{status}` {path}")
        if len(lines) >= limit:
            remaining = len(files) - limit
            if remaining > 0:
                lines.append(f"- 其余 {remaining} 个文件省略")
            break
    return lines or ["- 无"]


def _bullet_lines(items: list[str], limit: int | None = None) -> list[str]:
    shown = items if limit is None else items[:limit]
    return [f"- {item}" for item in shown] or ["- 无"]


def render_report(report: SyncReport, commit_limit: int, file_limit: int) -> str:
    lines = [
        "# 元垒上游差异报告",
        "",
        f"- 上游引用：`{report.upstream_ref}` (`{report.upstream_head[:8]}`)",
        f"- 同步基线（merge-base）：`{report.base[:8]}`",
        f"- 元垒领先：{report.ours_ahead} 个 commit",
        f"- 上游领先：{report.upstream_ahead} 个 commit",
        "",
        f"## 上游领先 commit（{report.upstream_ahead}，最多展示 {commit_limit}）",
        "",
        *_bullet_lines(report.upstream_commits, commit_limit),
        "",
        f"## 元垒领先 commit（{report.ours_ahead}，最多展示 {commit_limit}）",
        "",
        *_bullet_lines(report.ours_commits, commit_limit),
        "",
        "## 上游变更文件",
        "",
        *_render_files(report.upstream_files, file_limit),
        "",
        "## 元垒变更文件",
        "",
        *_render_files(report.ours_files, file_limit),
        "",
        f"## 共同修改（R3/R4 冲突候选，{len(report.overlap)} 个）",
        "",
        *_bullet_lines(report.overlap),
        "",
        "## 决策记录变化",
        "",
        f"上游决策（{len(report.upstream_decision_files)}）：",
        "",
        *_bullet_lines(report.upstream_decision_files),
        "",
        f"元垒决策（{len(report.yuanlei_decision_files)}）：",
        "",
        *_bullet_lines(report.yuanlei_decision_files),
        "",
        "## 镜像与基线检查",
        "",
        *([f"- 漂移：{problem}" for problem in report.problems] or ["- 一致"]),
        "",
    ]
    return "\n".join(lines)


def check(repo: Path, upstream_ref: str) -> list[str]:
    baseline = load_baseline(repo)
    return mirror_problems(repo, baseline) + baseline_problems(repo, upstream_ref, baseline)


def _ambiguous_branch(repo: Path) -> bool:
    return try_git(repo, "show-ref", "--verify", "--quiet", "refs/heads/upstream/main") is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=None, help="仓库根目录，默认当前仓库")
    parser.add_argument("--upstream-ref", default=UPSTREAM_REF, help="上游引用")
    parser.add_argument("--remote", default=UPSTREAM_REMOTE, help="--fetch 使用的远端名")
    parser.add_argument("--fetch", action="store_true", help="先运行 git fetch 远端")
    parser.add_argument("--output", type=Path, default=None, help="报告输出文件")
    parser.add_argument("--check", action="store_true", help="只检查镜像与基线漂移")
    parser.add_argument("--commit-limit", type=int, default=40, help="最多展示的 commit 数")
    parser.add_argument("--file-limit", type=int, default=200, help="最多展示的文件数")
    args = parser.parse_args(argv)

    if args.repo is not None:
        repo = args.repo.resolve()
    else:
        root = try_git(Path.cwd(), "rev-parse", "--show-toplevel")
        if root is None:
            print("不在 Git 仓库中", file=sys.stderr)
            return 2
        repo = Path(root.strip())

    try:
        if args.fetch:
            result = _run(repo, "fetch", args.remote)
            if result.returncode != 0:
                raise ReportError(result.stderr.strip() or f"git fetch {args.remote} 失败")
        if try_git(repo, "rev-parse", "--verify", "--quiet", args.upstream_ref) is None:
            raise ReportError(
                f"缺少上游引用 {args.upstream_ref}；先运行 git fetch {UPSTREAM_REMOTE}"
            )
        if _ambiguous_branch(repo):
            print(
                "警告：本地存在同名分支 upstream/main，git 命令会产生歧义；建议 git branch -D upstream/main",
                file=sys.stderr,
            )
        if args.check:
            problems = check(repo, args.upstream_ref)
            for problem in problems:
                print(f"漂移：{problem}")
            print("检查通过" if not problems else f"检查失败：{len(problems)} 项漂移")
            return 1 if problems else 0
        report = build_report(repo, args.upstream_ref, args.commit_limit)
        rendered = render_report(report, args.commit_limit, args.file_limit)
    except ReportError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"报告已写入 {args.output}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
