"""从矩阵原始样本生成不含身份、凭据或正文的同事阅读报告。"""

from collections import defaultdict
from itertools import pairwise

from .matrix import summarize_timings, verified_completed
from .analysis import MissingStageData, summarize_phases


def markdown_table(headers, rows):
    """渲染可复制的简单 Markdown 表格。"""
    return "\n".join("| " + " | ".join(map(str, row)) + " |" for row in [headers, ["---"] * len(headers), *rows])


def worker_cpu(events):
    """进程/事件循环 CPU 以单核为 100%，返回 Worker 均值和单次采样峰值。"""
    samples = defaultdict(list)
    for event in events:
        if event["event"] == "process_sample":
            samples[event["container"]].append(event)
    seconds = cpu = loop_cpu = peak = 0.0
    for rows in samples.values():
        rows.sort(key=lambda row: row["time_ns"])
        for first, last in pairwise(rows):
            duration = (last["time_ns"] - first["time_ns"]) / 1e9
            if duration <= 0:
                continue
            process = last["cpu_seconds"] - first["cpu_seconds"]
            seconds += duration
            cpu += process
            loop_cpu += last["loop_cpu_seconds"] - first["loop_cpu_seconds"]
            peak = max(peak, process / duration * 100)
    if not seconds:
        return [None, None, None]
    return [
        round(cpu / seconds * 100, 1),
        round(loop_cpu / seconds * 100, 1),
        round(peak, 1),
    ]


def render_report(data):
    """主表及阶段、体验、CPU 副表使用相同请求集合，不相加分位数。"""
    groups = sorted(data["groups"], key=lambda group: (group["workers"], group["concurrency"]))
    keys = [(group["workers"], group["concurrency"]) for group in groups]
    if len(keys) != len(set(keys)):
        raise ValueError("重复 Worker/并发组，不能隐式合并独立实验")
    main, stages, experience, resources = [], [], [], []
    detailed = {}
    for group in groups:
        rows = group["requests"]
        timings = summarize_timings(rows)

        def pair(metric, values=timings):
            """明确显示缺失值，不把缺失样本作为零延迟。"""
            value = values[metric]
            return f"{value['p50']} / {value['p95']} (n={value['n']})"

        identity = [group["workers"], group["concurrency"]]
        verified = sum(verified_completed(row) for row in rows)
        complete = (
            verified == len(rows) == group["planned_requests"]
            and all(metric["n"] == len(rows) for metric in timings.values())
            and not group.get("missing")
            and not group.get("observation_error")
        )
        main.append(
            [
                *identity,
                f"{len(rows)}/{group['planned_requests']}",
                verified,
                pair("api_to_model_ms"),
                "完整" if complete else f"不完整；{group.get('observation_error', '时点或结果缺失')}",
            ]
        )
        stages.append(
            [
                *identity,
                *(
                    pair(metric)
                    for metric in (
                        "api_to_created_ms",
                        "created_to_started_ms",
                        "started_to_prepared_ms",
                        "prepared_to_model_ms",
                    )
                ),
            ]
        )
        experience.append(
            [
                *identity,
                pair("model_to_first_output_ms"),
                pair("api_to_finished_ms"),
                pair("client_total_ms"),
                round(group["successful_rps"], 2),
            ]
        )
        resources.append(
            [
                *identity,
                *worker_cpu(group.get("events", [])),
                round(
                    max(
                        (e["ms"] for e in group.get("events", []) if e["event"] == "loop_lag"),
                        default=0,
                    ),
                    1,
                ),
            ]
        )
        if complete and group["workers"] == 1 and group["concurrency"] in {10, 20}:
            try:
                detailed[group["concurrency"]] = summarize_phases(group)
            except MissingStageData as exc:
                group["phase_error"] = str(exc)

    rounds = "；".join(
        f"Worker {group['workers']} / 并发 {group['concurrency']}：{group.get('rounds_per_thread', '未记录')} 轮"
        for group in groups
    )
    sections = [
        "# Alpha 连续并发报告",
        (
            "不同普通用户、每通道固定 Thread、上一轮完成并回读结果后立即补位；提示词为 `say hi`。"
            f"各组计划每通道轮数：{rounds}。无额外预热、输出长度限制或沙盒监测。"
            "下表数值为毫秒，单元格为 P50 / P95（nearest-rank）。"
        ),
        "## 主表：API 接入到首次模型 HTTP 提交",
        (
            "起点为 ASGI 收到 POST、鉴权及正文解析之前；终点为 HTTPX.send 入口，尚未等待供应商首 token。"
            "终点不代表网卡发包时间。样本包含各 Worker 冷启动；不将 Run 创建当作起点。"
        ),
        markdown_table(
            [
                "Worker",
                "并发",
                "实际/计划请求",
                "数据库验证完成",
                "接入→模型提交",
                "观测状态",
            ],
            main,
        ),
        "## 副表：接入和 Worker 准备",
        "各阶段独立计算分位数，不能把各列 P95 相加。领取列从 Run 创建计到数据库 started 时点。",
        markdown_table(
            [
                "Worker",
                "并发",
                "接入→Run 创建",
                "创建→started",
                "started→prepared",
                "prepared→模型提交",
            ],
            stages,
        ),
        "## 副表：供应商等待和完整对话",
        "模型提交→首输出还包含网络和 Worker 接收处理，不能全部归因于供应商。",
        markdown_table(
            [
                "Worker",
                "并发",
                "模型提交→首输出",
                "接入→数据库完成",
                "客户端完整结果",
                "成功请求/秒",
            ],
            experience,
        ),
        "## 副表：Worker CPU 与事件循环",
        (
            "CPU 以单核为 100%，均值按各 Worker 的采样时长加权；峰值是单 Worker 约 1 秒区间值。"
            "循环迟到仅记录超过 30 ms 的样本，0 表示未记录超过阈值的迟到。没有采样 API 或数据库 CPU。"
        ),
        markdown_table(
            [
                "Worker",
                "并发",
                "进程 CPU 均值%",
                "循环线程 CPU 均值%",
                "进程 CPU 峰值%",
                "循环迟到最大 ms",
            ],
            resources,
        ),
    ]
    if len(detailed) == 2:
        first, last = detailed[10], detailed[20]
        sections.extend(
            [
                "## 单 Worker 的 10→20 增量定位",
                "均值用于加总解释；P50/P95 用于观察分布。阶段边界来自轻量语义探针。",
                markdown_table(
                    [
                        "阶段",
                        "10 并发均值",
                        "20 并发均值",
                        "均值增量",
                        "10 并发 P50/P95",
                        "20 并发 P50/P95",
                    ],
                    [
                        [
                            name,
                            values["mean"],
                            last[name]["mean"],
                            round(last[name]["mean"] - values["mean"], 2),
                            f"{values['p50']} / {values['p95']}",
                            f"{last[name]['p50']} / {last[name]['p95']}",
                        ]
                        for name, values in first.items()
                    ],
                ),
            ]
        )
    sections.extend(
        [
            "## 解读边界",
            (
                "同一 Thread 的历史长度随实际完成轮数增长，组间比较须同时考虑轮数差异。"
                "外部模型响应速度影响闭环请求重叠程度，主指标不含本次首 token 等待仍不等于完全隔离外部影响。"
                "表内为单次实验，不代表置信区间；短对照实验和正式矩阵的样本数不同，不能直接宣称前后百分比。"
            ),
        ]
    )
    for group in groups:
        if group.get("phase_error"):
            sections.append(
                f"Worker {group['workers']} / 并发 {group['concurrency']} 阶段统计不可用：{group['phase_error']}。"
                "该组保留全部请求和主指标有效计数，不用零填充缺失阶段。"
            )
    return "\n\n".join(sections) + "\n"
