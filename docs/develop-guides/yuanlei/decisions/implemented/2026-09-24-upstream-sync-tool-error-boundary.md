# 上游工具异常隔离与元垒 Git 错误边界

状态：implemented
类型：architecture
Owner：backend/package/yuxi/agents/middlewares/tool_error_guard.py

## 问题

截至 `dee83624` 的上游版本引入 `ToolErrorGuardMiddleware`，在 Chatbot 与 SubAgent 最外层把普通工具异常转换成模型可见的错误 ToolMessage。元垒的 Git 工具此前只收敛已知业务错误；未知异常与系统故障必须使 Run 显式失败。若直接采用上游的全工具兜底，Git 专用中间件放行的异常会在外层被吞掉，失去 fail-closed 语义。此次同步还共同修改了 Agent 装配、API 错误展示、模型管理页和沙盒 provisioner。

## 决策

- 接受上游的普通工具异常隔离、模型重试失败保真、SSE 终态游标修复、知识库入库重试、图谱与 URL 抓取修复、单沙盒资源限制和 UI 更新。
- `ToolErrorGuardMiddleware` 对三个元垒 Git runtime 工具放行未知异常；内层 `GitToolErrorMiddleware` 继续把 HTTP 与权限业务异常转换成 ToolMessage。其他工具沿用上游隔离行为，取消和 Graph interrupt 继续向上传播。
- API 错误展示同时保留元垒编码凭据 503 的受控字符串明细，并采用上游 `code/message` 结构化业务错误；项目智能体标签与元垒 README 品牌内容保留。
- 上游没有改动元垒独有的 yuanlei schema 与迁移链。`business` 和 `knowledge` 域按上游版本接收；本次不推进 `YUANLEI_SCHEMA_VERSION`。
- 上游 SSRF 防护的多公网地址回退同时处理 `httpcore.ConnectError` 与 `ConnectTimeout`；默认 backend 抛出的这两类异常不继承 `OSError`，仅捕获后者会使首个地址失败时提前终止。

## 替代方案

- 直接保留上游所有工具的异常兜底：拒绝。Git 系统故障会被包装成可重试业务错误，违反现有权限和审计失败边界。
- 取消上游兜底并保留原工具异常行为：拒绝。普通工具的可恢复失败会继续中断整个 AgentRun，丢失上游修复。
- 对所有工具重建异常白名单：拒绝。没有当前业务需求支撑额外策略层，并增加维护面。

## 后果

Git 专用异常策略依赖工具名白名单和中间件顺序。新增 Git runtime 工具时需要同步扩展白名单与负向测试；上游若提供同等 per-tool 策略，可迁移后删除此特例。上游资源限制同时作用于元垒专属 Sandbox，保留 scope、generation、Workdir 与凭据边界。

## 验证

- `backend/test/unit/middlewares/test_tool_error_guard.py` 覆盖 Git 未知异常穿过同步与异步包装；原有 `test_git_tool_error_middleware.py` 覆盖业务异常收敛。
- `backend/test/unit/knowledge/test_url_fetcher.py` 覆盖 httpcore 建连失败后只回退到事先校验的公网地址。
- `python3 scripts/yuanlei_upstream_report.py --check` 校验基线、README 和镜像；工程契约、后端、Web 与文档检查以本次合并的实际执行结果为准。
