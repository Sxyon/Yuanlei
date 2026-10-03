# Milvus 连接有限启动等待

状态：implemented
类型：bug-fix
Owner：backend/package/yuxi/knowledge/implementations/milvus.py

## 问题

上游连接初始化只尝试一次。Docker 同时重启时，Milvus Proxy 尚未就绪导致 API 必需知识库组件失败，开发热重载父进程仍存活。

## 决策

Compose API 声明 Milvus 健康依赖。连接初始化对 MilvusException 最多尝试六次，每次连接超时十秒，间隔五秒；等待耗尽继续显式失败，不改变 readiness 或知识库必需性。此局部修复没有持久化变更与待裁决产品语义，直接记录 implemented。需求与退出条件见[Feature](../../features/milvus-startup.md)。

## 替代方案

只添加 Compose 依赖无法覆盖 Docker daemon 同时恢复已有容器。关闭知识库必需性会把服务未就绪伪装为成功。删除开发热重载会破坏开发体验。无限重试会隐藏永久故障。

## 后果

连接故障增加有限次数的初始化等待，每次向 SDK 指定十秒连接超时；实际耗时受 SDK 内部连接阶段影响。非 Milvus 异常立即传播。上游同步时采用等价机制，避免叠加重试。

## 验证

单测覆盖暂时不可用后成功、持续不可用耗尽失败、其他异常立即失败；Compose 测试验证 API 健康依赖。真实环境验证 Milvus 协议连接、API readiness 和 Web 代理。`docker compose exec -T api uv run --no-sync --group test pytest test/unit -m "not slow" -q`：2732 passed、63 skipped（容器未挂载仓库根目录等既有 skip）；本机 Compose 边界测试 50 passed，相关知识库测试 8 passed。工程信任检查及其 70 个单测、文档构建、Ruff 与补丁检查通过。`docker compose restart milvus api` 后回读 readiness 为 ready、degraded=false，Milvus 协议版本 2.5.6 且集合查询成功。默认 `uv run --group test` 因运行身份不能修改镜像系统依赖而失败，测试使用已安装依赖的 `--no-sync`；未覆盖真实模型对话。
