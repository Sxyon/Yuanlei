"""报告的 Worker 分组和 CPU 口径由独立数值验证。"""

import unittest
from unittest.mock import patch

from test.performance.matrix import summarize_timings
from test.performance.report import markdown_table, render_report, worker_cpu


class ReportTest(unittest.TestCase):
    """不把多个进程的 CPU 相加后冒充单 Worker 使用率。"""

    def group(self, concurrency, workers=1):
        """构造独立可手算的成功样本。"""
        return {
            "workers": workers,
            "concurrency": concurrency,
            "planned_requests": 2,
            "events": [],
            "successful_rps": 1,
            "requests": [
                {
                    "success": True,
                    **{metric: value for metric in summarize_timings([])},
                    "db": {"status": "completed", "attempts": 1, "bound_output": True},
                }
                for value in (10, 20)
            ],
        }

    def test_partial_observation_displays_effective_count_and_error(self):
        group = self.group(1)
        group["requests"][1].pop("api_to_model_ms")
        for row in group["requests"]:
            row.pop("client_total_ms")
        group["observation_error"] = "RuntimeError"
        output = render_report({"groups": [group]})
        self.assertIn("10 / 10 (n=1)", output)
        self.assertIn("不完整；RuntimeError", output)
        self.assertIn("None / None (n=0)", output)

    def test_extra_failed_request_cannot_be_hidden_by_planned_successes(self):
        """完成计划数量仍不能掩盖额外失败或超出预算的样本。"""
        group = self.group(1)
        group["requests"].append({**group["requests"][0], "success": False})
        output = render_report({"groups": [group]})
        self.assertIn("3/2", output)
        self.assertIn("不完整", output)

    def test_reversed_groups_cannot_reverse_ten_to_twenty_delta(self):
        with patch(
            "test.performance.report.summarize_phases",
            side_effect=lambda group: {
                "phase": {
                    "mean": group["concurrency"],
                    "p50": group["concurrency"],
                    "p95": 99,
                }
            },
        ):
            output = render_report({"groups": [self.group(20), self.group(10)]})
        self.assertIn("| phase | 10 | 20 | 10 | 10 / 99 | 20 / 99 |", output)
        with self.assertRaisesRegex(ValueError, "重复"):
            render_report({"groups": [self.group(10), self.group(10)]})

    def test_cpu_uses_container_identity_and_sample_intervals(self):
        events = []
        for container, cpu, loop in (("worker-1", 0.5, 0.4), ("worker-2", 0.9, 0.6)):
            for second in (0, 1, 2):
                events.append(
                    {
                        "event": "process_sample",
                        "container": container,
                        "time_ns": second * 1_000_000_000,
                        "cpu_seconds": second * cpu,
                        "loop_cpu_seconds": second * loop,
                    }
                )
        self.assertEqual(worker_cpu(list(reversed(events))), [70.0, 50.0, 90.0])
        self.assertEqual(worker_cpu([]), [None, None, None])

    def test_table_keeps_both_workers_and_both_percentiles(self):
        output = markdown_table(["Worker", "并发", "P50/P95"], [[1, 20, "10 / 40"], [4, 20, "5 / 20"]])
        self.assertIn("| 1 | 20 | 10 / 40 |", output)
        self.assertIn("| 4 | 20 | 5 / 20 |", output)
