"""拥有 Yuxi 的 ARQ 领取适配，执行与恢复协议仍由 ARQ 管理。"""

from arq.worker import Worker, get_kwargs


class YuxiWorker(Worker):
    """跳过本进程仍在执行的候选，减少补位请求之前的重复 Redis 往返。"""

    async def start_jobs(self, job_ids: list[bytes]) -> None:
        """已结束 Task 必须重新参与领取，以保留 ARQ retry 与完成清理语义。"""
        candidates = []
        for job_id in job_ids:
            task = self.tasks.get(job_id.decode())
            if task is None or task.done():
                candidates.append(job_id)
        await super().start_jobs(candidates)


def run_worker(settings: type) -> None:
    """让正式入口和诊断入口复用同一 Worker 与既有生命周期。"""
    YuxiWorker(**get_kwargs(settings)).run()
