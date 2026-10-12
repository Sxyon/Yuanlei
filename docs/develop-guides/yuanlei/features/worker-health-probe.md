# Worker 健康检查轻量装配

状态：implemented
类型：上游缺陷修复
主要 Owner：backend/server/worker_health.py

## 需求与失败场景

本地环境恢复后无法启动；ARQ 健康检查导入完整 Worker 业务模块，超过 Docker 检查时限，外层 shell 被终止后 Python 子进程残留，重复检查消耗 CPU 并拖慢 API 与其他依赖启动。

## 必须保留的业务语义

健康检查继续读取运行 Worker 写入的 ARQ 心跳键，复用 Redis 连接配置。缺失或过期心跳必须失败；Redis 可连接本身不能证明 Worker 健康。Compose 以 exec 启动检查进程，使 Docker 超时终止直接作用于检查执行者。API 检查继续访问 readiness，使用 exec 与十秒 curl 请求时限；Neo4j 仍通过真实 Bolt 查询证明可用，也使用 exec 终止检查执行者。

## 与 Yuxi 的边界

修复上游检查装配与进程回收缺陷，不新增持久化或产品语义。

## 稳定集成点

Compose 检查入口、ARQ 心跳键与 Redis 连接配置。

本地开发图谱检查允许 JVM 启动与查询在九十秒内完成，间隔六十秒；生产保留原有时间参数。

## 上游依赖

依赖 ARQ 心跳协议、Yuxi 队列心跳键与 Redis 配置、Docker 健康检查进程终止语义。上游提供等价轻量检查与进程回收后采用上游实现并删除此差异。

## 合并判断

保留并迁移检查语义，上游实现等价能力后采用上游替代。

## 替换或删除条件

上游健康检查不加载业务模块且正确回收超时执行者后删除差异。

## 决策与证据

见[健康检查决策](../decisions/implemented/2026-10-12-worker-health-probe.md)。隔离进程测试禁止加载 Worker 业务模块；真实验证读取 ARQ 心跳、健康检查退出码及 Compose 状态。

直接回归入口：`backend/test/unit/routers/test_worker_health.py`。
