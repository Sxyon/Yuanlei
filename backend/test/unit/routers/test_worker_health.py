"""健康检查装配必须保持轻量并沿用 Worker 心跳协议。"""

import os
import subprocess
import sys


def test_health_settings_import_without_worker_runtime():
    """隔离进程拒绝业务模块导入，恢复旧入口会在正确边界失败。"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib.abc
import sys

class RejectRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'server.worker_main', 'yuxi.services.run_worker'}:
            raise AssertionError('health check imported worker runtime')

sys.meta_path.insert(0, RejectRuntime())
from server.worker_health import WorkerHealthSettings
from yuxi.services.run_queue_service import WORKER_HEALTH_KEY
assert WorkerHealthSettings.health_check_key == WORKER_HEALTH_KEY
assert WorkerHealthSettings.redis_settings.host == 'health-redis'
assert WorkerHealthSettings.redis_settings.database == 3
""",
        ],
        env={**os.environ, "REDIS_URL": "redis://health-redis:6379/3"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
