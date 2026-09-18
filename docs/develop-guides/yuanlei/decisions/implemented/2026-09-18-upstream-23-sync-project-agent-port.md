# 上游 2026-09-18 同步与 ProjectAgent 校验迁移

状态：implemented
类型：architecture
Owner：backend/package/yuxi/services/agent_request_service.py

## 问题

上游 23 个 commit 重构了 Agent 请求接入与运行上下文准备（`a7f10198` 等），删除 `backend/package/yuxi/services/run_submission_service.py` 并新增 `agent_request_service.py`。元垒的项目数字员工提交边界校验和项目覆盖读取落在被删除或被重构的文件中，直接接受上游会丢失"绑定 Agent 只能在绑定项目内运行"的 fail-closed 语义。同步还涉及 `agent_repository.py`、`agent_router.py`、`chat_service.py`、`agent_run_manifest_service.py`、`scheduled_agent_service.py`、`context_compression_service.py`、`run_worker.py` 与工程契约脚本的双侧修改。上游同时移除了 `agent_manager`、改用 `get_agent_backend`，并把内置角色落库重构为 `AgentPreset`，元垒新文件必须跟随。

## 决策

- 接受上游请求接入重构：删除 `run_submission_service.py`，请求校验与持久化归 `agent_request_service.submit_agent_request`。ProjectAgent 范围校验保留双侧：intake 在重放与新建两条路径调用 `ensure_agent_project_scope`，执行侧在 `agent_run_manifest_service.prepare_run_execution` 与 `chat_service._resolve_agent_runtime` 校验。
- 项目覆盖读取迁移到上游新路径：`agent_request_service._persist_request` 在 `resolve_agent_run_config` 前加载 `load_project_agent_override`；`prepare_run_execution` 在 `context.update_config` 前合并覆盖；`context_compression_service` 同样合并；resume 继续继承父 Run 的 `input_payload`。
- 上游执行准备入口 `prepare_run_execution` 接收 `git_repositories` 与 `project_git_enabled`，写入 Context 并进入 manifest；`run_worker` 统一通过 `prepare_and_record_run_execution` 固化清单与指纹，删除元垒旧入口 `build_run_manifest_result`。
- 冲突文件按「上游结构 + 元垒语义」合并；`verify_engineering_contracts.py` 同时保留上游 `as_posix` 路径修复与元垒双 decision 根校验。
- 上游 MCP 远程化、`AgentPreset` 内置角色、子智能体独立观察、审批中断骨架恢复、`.xls` 解析等 R1 变更全部接受。
- 顺手修正 HTTP 层 `api_token` 的长度上界（`str`，1~4096），与 service 既有校验一致，使分支上既有红色测试恢复为真；service 校验保留为纵深防御。

## 替代方案

- 只保留 intake 校验：拒绝。执行入口不限于 Web Chat，resume、定时任务与主动上下文压缩都可能到达执行边界，单点校验会留下绕过路径。
- 保留 `run_submission_service.py` 兼容层：拒绝。会形成第二个请求接入 Owner，与上游重构后的单一入口冲突。
- 保留 `build_run_manifest_result` 作为元垒入口：拒绝。上游 `PreparedRunExecution` 同时拥有 Context 与 manifest，双入口会造成两套执行准备语义。
- 把项目范围校验放进 repository 查询：拒绝。repository 只拥有可见性查询，绑定语义与有效配置合并属于 service 用例。
- 暂缓同步直到元垒功能冻结：拒绝。基线会继续漂移，冲突面随上游重构扩大。

## 后果

- ProjectAgent 语义落在新入口的 intake 与既有执行边界；上游后续修改请求接入、执行准备或 manifest 时以本记录和[功能索引](../../features/README.md)为准。
- manifest schema 版本保持 3：合并上游 v2 演进与元垒 `git_repositories` 身份快照。
- 上游单测需要适配元垒 scope 与项目覆盖：`test_agent_request_service`、`test_chat_service_sync`、`test_agent_run_manifest_service`、`test_context_compression_service`、`test_agent_run_service` 已更新，并在请求队列测试中新增项目覆盖断言。
- 基线更新到 `5a1bdc3c`；合并完成时上游跟踪引用已前进到 `1946c3d7`，下一次同步报告会显示该差异。
- `test_schema_migration_version.py` 的 2 个 PJ1 基线失败与技能并发 flake 不是本次合并引入，保持既有未验证状态。
- HTTP 层拒绝超长 Token 后，非法请求不再进入 service；响应与日志仍只包含固定脱敏文案。

## 验证

- 后端全量 unit：`docker compose exec -T api uv run --no-sync --group test pytest test/unit -m "not slow" -q`：2293 passed、57 skipped。环境缺少新增依赖 `xlrd`，通过 `uv run --with "xlrd>=2.0.1"` 覆盖提供；这是环境补齐，不是测试豁免。
- PostgreSQL integration：`test_schema_migration_version.py` 10 passed、2 个既有 PJ1 失败；`test_agent_request_queue_concurrency.py` 与 `test_project_agent_api.py` 8 passed、4 skipped（缺 `TEST_USERNAME`/`TEST_PASSWORD`）。
- Web：`pnpm run lint:check`、`pnpm run test:unit`（367 passed）、`pnpm run build` 全部通过。
- Ruff（pinned 0.16.4）：`ruff check package`、`ruff format package --check`、`ruff check --select I package` 全部通过。
