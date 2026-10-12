"""仅装配 ARQ 心跳检查，避免加载业务执行模块。"""

from yuxi.services.run_queue_service import WORKER_HEALTH_KEY
from yuxi.storage.redis import get_arq_redis_settings


class WorkerHealthSettings:
    """复用运行 Worker 的心跳键和 Redis 连接配置。"""

    health_check_key = WORKER_HEALTH_KEY
    redis_settings = get_arq_redis_settings()
