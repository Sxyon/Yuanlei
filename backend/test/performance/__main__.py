"""性能评测统一入口；从仓库根目录运行 python -m backend.test.performance。"""

import argparse
import asyncio
from pathlib import Path

from . import analysis, load, matrix, report


def build_parser() -> argparse.ArgumentParser:
    """统一注册采样与离线报告命令。"""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    matrix.add_arguments(commands.add_parser("matrix", help="不同用户、固定 Thread 的闭环并发矩阵"))
    load.add_arguments(commands.add_parser("load", help="通用 Agent 对话与沙盒容量压测"))
    report_parser = commands.add_parser("report", help="从已有样本一次生成阶段统计和 Markdown 报告")
    report_parser.add_argument("path", type=Path, help="已有 matrix.json 路径")
    report_parser.add_argument("--refresh", action="store_true", help="显式从仍在运行的实验容器补齐探针")
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行一个子命令；离线报告默认不访问服务或模型。"""
    args = build_parser().parse_args(argv)
    if args.command == "load":
        return load.main(args)
    if args.command == "matrix":
        asyncio.run(matrix.main(args))
        return 0
    data = analysis.main(args.path, args.refresh)
    output = args.path.with_name("report.md")
    output.write_text(report.render_report(data))
    print(f"已生成 {output} 和 {args.path.with_name('stages.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
