# 服务端口

下面列出开发 Compose 发布到宿主机的端口。生产 Compose 默认只发布 Web 入口，其余服务通过 Compose 内网访问。

## 开发环境端口

| 端口 | 服务 | 用途 |
| --- | --- | --- |
| 5173 | Web | 开发 Web 界面 |
| 5050 | API | API 和 Swagger 文档 |
| 8002 | `sandbox-provisioner` | 本机排查 provisioner；只绑定 `127.0.0.1` |
| 7474 / 7687 | Neo4j | HTTP 管理界面 / Bolt |
| 9000 / 9001 | MinIO | 对象 API / 管理控制台 |
| 19530 / 9091 | Milvus | gRPC / 健康检查 |
| 5432 | PostgreSQL | 本机数据库维护 |
| 6379 | Redis | 本机缓存和队列维护 |

通过 `all` profile 启动的可选 OCR 服务：

| 端口 | 服务 | 用途 |
| --- | --- | --- |
| 30001 | `mineru-api` | MinerU `/file_parse` 接口 |
| 8080 | `paddlex` | PP-Structure-V3 接口 |

etcd 只在 Compose 网络内供 Milvus 使用，没有发布到宿主机。MinerU 镜像内部使用推理运行时，但 Compose 没有单独发布 vLLM 服务端口。

## 常用入口

开发环境：

- Web：<http://localhost:5173>
- API 文档：<http://localhost:5050/docs>
- API 存活检查：<http://localhost:5050/api/system/health>
- API 就绪检查：<http://localhost:5050/api/system/ready>
- Neo4j：<http://localhost:7474>
- 沙盒 provisioner：<http://localhost:8002/health>

`/api/system/health` 只表示 API 进程存活；`/api/system/ready` 还会检查启动完成、PostgreSQL、Redis 和 worker 健康租约；provisioner 的 `/health` 表示自身进程、backend 和沙盒跟踪状态。三类接口都不能单独证明知识库、模型或 Agent 业务链路正确。

## 安全边界

不要把 PostgreSQL、Redis、MinIO、Neo4j、Milvus 或 provisioner 的管理端口暴露到公网。生产入口、TLS、CORS 和密钥要求见[生产部署](./deployment.md)。
