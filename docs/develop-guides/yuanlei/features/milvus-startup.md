# Milvus 启动等待

状态：implemented
类型：上游缺陷修复
主要 Owner：backend/package/yuxi/knowledge/implementations/milvus.py

## 需求与失败场景

Docker 同时重启服务时，API 可在 Milvus Proxy 就绪前初始化已有知识库并退出；开发热重载父进程继续存活，容器无法依靠 restart policy 恢复。

## 必须保留的业务语义

知识库仍是必需启动组件。连接等待耗尽后保留失败；数据库、鉴权和知识库业务规则保持既有语义。

## 与 Yuxi 的边界

修复上游启动时序缺陷，不新增产品能力或持久化结构。

## 稳定集成点

Compose API 的健康依赖与 MilvusKB 的连接初始化共同拥有启动等待。

## 上游依赖

依赖 Yuxi Compose 和 PyMilvus 连接异常协议。

## 合并判断

保留并迁移启动等待；上游提供等价机制时采用上游实现。

## 替换或删除条件

上游覆盖 Compose 启动和 Docker daemon 恢复已有容器的有限连接等待时删除差异。

## 决策与证据

见[启动等待决策](../decisions/implemented/2026-10-03-milvus-startup.md)；连接回归测试位于 `backend/test/unit/knowledge/test_milvus_connection_startup.py`，真实验证读取 Milvus 协议与 API readiness。
