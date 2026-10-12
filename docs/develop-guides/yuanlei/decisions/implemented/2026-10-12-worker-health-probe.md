# 健康检查轻量装配与超时回收

状态：implemented
类型：bug-fix
Owner：backend/server/worker_health.py

## 问题

ARQ CLI 通过生产 WorkerSettings 导入完整业务模块。启动恢复时检查超过十秒，Docker 终止外层 shell 后留下 Python 子进程，反复启动检查加剧 CPU 竞争。API 与 Neo4j 的 shell 包装同样可能留下 curl 与 JVM 检查进程。

## 决策

ARQ 使用只承载心跳键和 Redis 配置的检查 Settings，复用队列模块的原始键与基础设施连接配置；运行 Worker 保持既有装配。开发与生产 Compose 使用 exec 直接运行 Python 检查、curl 以及 cypher-shell，curl 增加十秒请求时限，保留 readiness、心跳与真实 Bolt 查询的失败语义。此局部故障修复没有待裁决产品语义或持久化改动，直接记录 implemented。需求与生命周期见[Feature](../../features/worker-health-probe.md)。

开发 Compose 的 Neo4j 检查间隔为六十秒、时限为九十秒：本地高负载下实际查询耗时七十四秒，十秒时限持续误报。生产检查保留既有时间参数。

Milvus 保持原有强依赖：API 在 Compose 中等待其健康，知识库仍作为必需组件初始化。本次修复只调整健康检查装配与进程回收。

## 替代方案

增加 timeout 仍重复加载业务模块，不能解决超时进程残留。仅检查 Redis ping 无法证明 Worker 运行。移除健康检查失去可观察失败。删除开发热重载影响现有开发流程。

## 后果

检查入口与运行入口分别装配，心跳键和 Redis 配置继续由原 Owner 拥有。开发图谱故障检测时间相应延长；检查成功证明近期 ARQ 心跳与 Bolt 查询可用，业务请求正确性仍需真实链路测试。

## 验证

隔离进程测试拒绝 Worker 业务模块导入，并验证共享键与非默认 Redis 数据库。Compose 回归验证两套部署的命令。真实环境验证正常心跳成功、缺失心跳失败、检查超时无残留进程、API readiness 与 Web 代理。真实回读 API、Worker、Neo4j 均为 healthy；前端代理 `/api/system/ready` 返回 ready、degraded=false，初始设置状态为 first_run=false。运行心跳检查返回 0，缺失心跳检查返回 1；进程回读没有累积的超时检查执行者。


- `docker compose exec -T api uv run --no-sync --group test pytest test/unit -m "not slow" --tb=short`：提交前重跑 2875 passed、63 skipped；容器不挂载仓库根目录导致已有 Compose 等测试跳过。
- `python3 -m pytest --noconftest backend/test/unit/config/test_docker_compose_checkpointer.py backend/test/unit/config/test_docker_compose_service_boundaries.py -q --tb=short`：64 passed，补足受影响 Compose 检查；独立健康入口回归也在全量单测中通过。
- `python3 scripts/verify_engineering_contracts.py` 和 `python3 -m unittest scripts.test_verify_engineering_contracts`：通过，后者 71 tests。
- `ruff check`、`ruff format --check`（健康入口和新增回归测试）、文档 `pnpm run build`、`git diff --check`：通过。
- 常规 `docker compose exec -T api uv run --group test pytest test/unit -m "not slow" -q` 因依赖镜像 DNS 查询失败而无法运行；使用已安装依赖的 `--no-sync` 完成测试。真实模型对话、完整业务 E2E 与 Docker daemon 重启场景未运行。
