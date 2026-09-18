# 上游 2026-09-18 同步与 ProjectAgent 校验迁移

状态：proposed
类型：architecture
Owner：docs/develop-guides/yuanlei/README.md

## 问题

上游 23 个 commit 重构了 Agent 请求接入与运行上下文准备（`a7f10198` 等），删除 `backend/package/yuxi/services/run_submission_service.py` 并新增 `agent_request_service.py`。元垒的项目数字员工提交边界校验和项目覆盖读取落在被删除或被重构的文件中，直接接受上游会丢失"绑定 Agent 只能在绑定项目内运行"的 fail-closed 语义。同步还涉及 `agent_repository.py`、`agent_router.py`、`chat_service.py`、`agent_run_manifest_service.py`、`scheduled_agent_service.py`、`context_compression_service.py`、`run_worker.py` 与工程契约脚本的双侧修改。

## 提案

- 接受上游请求接入重构：删除 `run_submission_service.py`，请求校验与持久化归属 `agent_request_service.submit_agent_request`。
- ProjectAgent 范围校验保留双侧：intake 在 `get_visible_by_slug` 后调用 `ensure_agent_project_scope`，执行侧继续在 `agent_run_manifest_service` 与 `chat_service` 校验并使用项目有效配置。
- 元垒项目覆盖读取（`model_spec`、`tool_approval_mode`）跟随上游新的运行上下文装配路径迁移。
- 冲突文件按「上游结构 + 元垒语义」合并；`verify_engineering_contracts.py` 同时保留上游 Windows `as_posix` 路径修复与元垒双 decision 根校验。
- 上游 schema 版本无变化（business 7 / knowledge 2），`models_business.py` 保留 `project_agents` 表与上游 MCP 远程化修改，`yuanlei` 域版本不动。

## 替代方案

- 只保留 intake 校验：拒绝。执行入口不限于 Web Chat，resume、定时任务与主动上下文压缩都可能到达执行边界，单点校验会留下绕过路径。
- 保留 `run_submission_service.py` 兼容层：拒绝。会形成第二个请求接入 Owner，与上游重构后的单一入口冲突。
- 把项目范围校验放进 repository 查询：拒绝。repository 只拥有可见性查询，绑定语义与有效配置合并属于 service 用例。
- 暂缓同步直到元垒功能冻结：拒绝。基线会继续漂移，冲突面随上游重构扩大。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 绑定 Agent 在非绑定项目被拒，解绑恢复全局 | 范围语义丢失 | `agent_request_service`、`project_agent_service` | 真实 HTTP integration `test_project_agent_api.py` | 非绑定项目提交返回 200 | Not run |
| 项目覆盖进入运行上下文与 manifest | 覆盖被上游重构吞掉 | `agent_run_manifest_service`、`chat_service` | unit + integration | 项目模型与审批模式未生效 | Not run |
| 执行边界仍 fail-closed | 直达执行路径绕过 intake | `agent_run_manifest_service` | unit | 绕过 intake 的执行被接受 | Not run |
| 上游 23 个 commit 行为保留 | 上游修复被合并回退 | 上游语义 Owner | 后端 unit 全量 + web unit | R1 文件出现回退 diff | Not run |
| 相对上游 23 个 commit 的合并与基线同步 | 报告显示漂移或未同步 | `baseline.json` | `python3 scripts/yuanlei_upstream_report.py --check` | 镜像或基线不一致 | Not run |

## 风险

- 上游请求接入重构后，项目覆盖的读取点可能分布在 Web、外部入口、resume 与定时任务多条路径，漏一处会产生模型或审批配置不一致。
- 冲突解决可能覆盖上游修复；以合并后的上游测试为 oracle，不用元垒旧测试替代。
- 真实 PostgreSQL integration 与 Gitea 链路依赖本机环境；未执行前不宣称通过。
