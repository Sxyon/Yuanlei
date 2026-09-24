# 智能体驱动沙盒内 opencode/codex 编码执行

状态：proposed
类型：feature
Owner：backend/package/yuxi/agents/backends/sandbox/provider.py

事实 Owner 分工：本文提案跨越多个 Owner，实现时不得让本文档反向充当运行时事实源。沙盒 env 注入、保活与 runtime 清理归 `backend/package/yuxi/agents/backends/sandbox/`；执行适配与会话状态机落在新增 `backend/package/yuxi/agents/coding/`；终端代理与 WS 通道归 `docker/sandbox_provisioner/app.py`；yuanlei 域迁移归 `backend/package/yuxi/storage/postgres/manager.py` 与 `backend/package/yuxi/storage_migration.py`；凭据加密与 fail-closed 范式复用 `backend/package/yuxi/git/credentials.py`；前端会话与终端组件归 `web/src/components/`。

## 问题

### 当前事实（代码实证）

**沙盒链路已经完整，但只被当作一次性命令执行器使用。**

- 数据面：API/worker 不直连沙盒，只拿 provisioner 返回的带 Bearer 代理 URL（`backend/package/yuxi/agents/backends/sandbox/provider.py:312-320`、`docker/sandbox_provisioner/app.py:2146-2215`）。沙盒容器不接入 `app-network`，不发布端口（`docker-compose.yml:209-269`）。
- 生命周期：按 `(uid, thread)` runtime scope 惰性创建，generation fence 校验，根 Run 终态且 scope 无活跃 Run 时释放（`backend/package/yuxi/agents/backends/sandbox/provider.py:158-269`、`backend/package/yuxi/services/run_worker.py:299-396`）。keepalive 只是访问时 touch，没有后台心跳（`provider.py:119,158-171`），因此空闲沙盒由 provisioner reaper 回收（默认 120 秒，`app.py:1765-1778`）。
- 路径三层：数据库 Project `workdir_path` → runtime `/home/gem/user-data/...` → 宿主持有；可写根只有 user-data，Skills 只读（`backend/package/yuxi/agents/backends/paths.py:10-23`、`backend/package/yuxi/agents/backends/sandbox/backend.py:40-79`）。
- Project 链路：Conversation 不可变绑定 `project_id`，Project 一期一个 `workdir_path`，可重命名、软删除，删除不改 Workdir 字节；Workspace tree 只展示 active selectable Project 子树（ARCHITECTURE.md「智能体运行链路」第 10 条）。编码任务已有 `git_prepare_worktree` 申请任务级 worktree 的现成工具（`backend/package/yuxi/agents/toolkits/git_tools.py:23-66`），但尚无实体把「编码会话」与 Project/worktree 持久绑定。
- 命令执行：`execute` 是一次性同步 `shell.exec_command`，默认 180 秒超时，输出按 256KB 截断，stdout/stderr 不分离，无增量、无 stdin、无进程会话（`backend/package/yuxi/agents/backends/sandbox/backend.py:540-570,198-199`）。
- 镜像原料已就绪（`docker run --entrypoint sh all-in-one-sandbox:1.11.0` 实测）：
  - opencode 1.4.6 预装于 `/usr/local/bin/opencode`，支持 `run --format json -s/--session -c/--continue --attach`、`serve`、`acp`、`session`、`export/import`、`providers`。
  - codex-cli 0.139.0 预装，支持 `exec`（stdin、`resume`、`review`）、`mcp-server`、`app-server`（实验性）、`login`。
  - 镜像入口 `gem.sh:553-640` 会把 `OPENCODE_*` / `CODEX_*` 环境变量渲染进用户 home 的 CLI 配置；`render-opencode-config.sh` 支持 `OPENCODE_JSON` 或 `OPENCODE_API_KEY + OPENCODE_MODEL + OPENCODE_PROVIDER + OPENCODE_BASE_URL`；`render-codex-config.sh` 支持 `CODEX_CONFIG_TOML` 或 `CODEX_API_KEY/ARK_API_KEY/OPENAI_API_KEY + CODEX_MODEL + CODEX_BASE_URL`。
  - 沙盒内 nginx 模板含 `${OPENCODE_PORT}` 端口代理与 WebSocket upgrade 支持（`/opt/gem/nginx.conf`、`gem.sh:835`），但 provisioner 代理剥离 `Upgrade` 等 hop-by-hop 头、methods 不含 WS（`app.py:74,2146-2215`），因此终端通道当前不可达。
  - SDK 暴露但项目未用的能力：shell session（`create_session/view/wait_for_process/write_to_process/kill_process/get_terminal_url/cleanup_session`）、`async_mode`、nodejs/Jupyter/code API（`agent_sandbox` 0.0.30，`backend/uv.lock:24-36`）。
- 项目代码从未调用 opencode/codex：`models/providers/builtin.py:180-189` 的 opencode 是模型供应商，`.env.template:74` 的 codex 是 Git 分支前缀，均与沙盒 CLI 无关。

**多轮与协作机制已存在，但语义停留在单个 Run 内。**

- SubAgent 四工具（`subagent_start/status/await/cancel`）支持 `thread_id` 续跑、独立持久 Run、父子状态投影（`backend/package/yuxi/agents/middlewares/subagent_task.py:314-335`、`backend/package/yuxi/services/subagent_run_service.py:105-176`）；子 Run 禁止再嵌套（`subagent_run_service.py:122-123`）。
- HITL 审批通过 `HumanInTheLoopMiddleware` 实现，interrupt/resume 新建 resume Run（`backend/package/yuxi/agents/tool_approval.py:22-42`、`backend/server/routers/agent_router.py:345-361`）。
- Run 事件走 Redis Stream + SSE，工具执行有 `tool_audit` 持久审计（`backend/package/yuxi/services/run_queue_service.py:58-73`、`backend/package/yuxi/services/run_worker.py:769-784`、`backend/package/yuxi/services/tool_message_audit_service.py:24-96`）。
- 前端无终端组件、无 xterm 依赖（`web/package.json`），工具结果一次性渲染（`web/src/components/ToolCallingResult/ToolCallRenderer.vue:67-107`）；Channel 只支持纯文本与 `/state`、`/approve`（`backend/server/routers/agent_invocation_channel_router.py:29-33`）。

**配置与密钥体系可用，但对第三方 CLI 缺治理。**

- 用户级 `agent_envs` 在沙盒创建时注入（`provider.py:55-79,203-212`、`app.py:1086-1091`），但明文存 JSONB、GET 原样回显、不热更新（`models_business.py:502-521`、`user_router.py:272-292`、`web/src/components/AgentEnvSettingsCard.vue:25-28`）。
- Git 凭据已有 AES-GCM + AAD 绑定 + write-only API + master key 缺失 fail-closed 的完整范式（`backend/package/yuxi/git/credentials.py:32-75`、`backend/server/routers/git_router.py:33-87`），但 Git token 只留在宿主侧，禁止进沙盒（`docs/agents/sandbox-architecture.md:156`）。
- 使用前没有「所需 key 是否已配置」校验；模型供应商 key 是管理端全局明文（`models_business.py:1091`），不能当用户级第三方 CLI key 使用。

- M0 契约实测（2026-09-18）已完成：版本、env 渲染、`run/exec` 事件样本、原生会话续跑、XDG/CODEX_HOME 持久化、`serve` + 端口代理、terminal-url 均有真实运行证据，详见 [编码 CLI 契约](../../../../agents/coding-cli-contract.md)。

### 上游边界

- 上游现状：Yuxi 沙盒只提供一次性 `execute` 与文件操作，没有 CLI 集成、会话实体和编码凭据；HITL 审批、SubAgent、事件链路与审计均为上游能力。
- 元垒改法：新增 `agents/coding/` 适配层与会话工具、`coding_*` yuanlei 表与编码凭据通道；上游文件只改 `tool_approval.py` 的 `interrupt_on` 一项，沙盒身份/生命周期改动归《Agent 专属沙盒与生命周期策略》。
- 合并注意：上游若升级 deepagents 文件后端、改变 `execute` 签名、重写事件映射或审批中间件，必须同步重验适配器与事件归一化；「密钥不进沙盒明文通道、Git 凭据留在宿主侧」的边界不因上游实现变化而放宽。

### 目标

1. 智能体能在沙盒内驱动 opencode/codex，完成「计划 → 执行 → 检查 → 继续」的多轮编码协作。
2. 密钥与 Git 凭证「使用前配置」：用户级加密存储、管理端兜底、缺配置显式失败，不污染现有沙盒 env 明文通道。
3. 交互可三档递进（无头一次性、程序化会话、终端直连），人可随时查看与接管，agent 始终保有控制权。
4. 把 opencode/codex 建成可被 agent 自主选择的「编码执行器」，纳入现有 Run/事件/审计/审批体系，并为 ACP 统一协议预留适配位。

### 非目标（一期不做）

- 不改普通请求 FIFO、Run 状态模型、Redis/PG 职责划分与沙盒路径三层边界。
- 不在沙盒内注入 Git 凭据；推送仍由宿主侧 `git_push_branch` 执行。
- 不引入 stdio MCP 运行外部 agent（`docs/agents/mcp-integration.md:12` 的禁令保持）。
- 不做 code-server/Jupyter 远程 IDE、不做 claude-code 适配、不做嵌套编码会话。
- 不把 `agent_envs` 升级为通用加密密钥库（只新增编码凭据独立通道）。

## 提案

### 1. 总体架构与所有权

```
Web 终端/会话面板 ──┐
CLI channel ────────┼─► CodingSessionService（状态机、turn、预算）──► CodingSupervisor（worker durable job）
Agent coding_* 工具 ─┘        │                                          │
                              ├─► CodingCredentialService（加密存取、解析、指纹）
                              ├─► CodingExecutorAdapter（opencode / codex / 预留 acp）
                              └─► SandboxProvider（现有，env 注入 + 保活 + fence 扩展）
                                          │
                                          ▼
                              provisioner（现有 HTTP 代理 + 新增 WS 终端代理）
                                          │
                                          ▼
                              AIO Sandbox（opencode 1.4.6 / codex 0.139.0）
```

- `CodingSessionService` 是会话事实 Owner：状态机、turn 序号、预算、与 Run/Project/Workdir 的绑定校验。持久化查询进 `yuxi.repositories`。
- `CodingSupervisor` 是执行 Owner：worker 内 durable job，负责启动/收养 CLI 进程、消费输出、写事件、续租沙盒、收尾。崩溃后按 lease/turn 状态收敛，遵循现有「非终态必须有明确 Owner」不变量。
- `CodingExecutorAdapter` 只拥有「如何调用某个 CLI、如何解析其输出」；不拥有状态与权限。ACP 作为第三个适配器位置预留，一期不实现。
- 前端会话面板与 Run SSE 解耦：会话有自己的 durable 事件流与 SSE，Run SSE 只在工具生命周期事件中携带会话摘要。

### 2. 概念模型

| 概念 | 语义 | 关键不变量 |
|---|---|---|
| CodingExecutor | opencode 或 codex，含版本与能力描述 | 不可用时显式失败，不静默替换 |
| CodingCredential | `(scope=user|global, executor, provider)` 的密钥与配置 | 明文不落库、不回显、不进行日志/事件 |
| CodingSession | 一个持久编码会话，绑定 Project Workdir 与 runtime scope | 会话身份 = uid + project + workdir + executor |
| CodingTurn | 会话内一次「发消息→CLI 执行到停止」 | 同一会话同时最多一个 active turn |
| CodingEvent | 归一化事件（状态/输出/tool_call/file_change/usage/approval） | 递增 seq，PG 持久为事实，Redis 只做在线投递 |

### 3. 凭据与使用前配置

**存储**：新增 yuanlei 表 `coding_credentials`。字段：`id、scope('user'|'global')、uid(global 为空)、executor、provider、base_url、model、api_key_cipher、extra_json、status、version、created_at、updated_at`。加密复用 Git 凭据实现：AES-GCM，AAD 绑定 `purpose='coding_credential'`、scope、uid、id；master key 来自新增 `YUXI_CODING_CREDENTIAL_KEY`（≥32 字符，缺失时 fail-closed 禁用整个编码能力，与 `YUXI_GIT_CREDENTIAL_KEY` 同构但独立，避免不同用途共密钥）。

**接口**：`GET /api/user/coding-credentials` 只返回掩码元数据与 `credential_status`；`PUT` 写入新版本；`DELETE` 销毁密文（保留 tombstone 语义）。管理端 `scope=global` 同构接口。任何响应与日志不出现明文。

**解析与注入**：`CodingCredentialService.resolve(uid, executor)` 返回「用户级 > 管理端全局」的结果与 `credential_fingerprint`（对解析后的非密字段 + 密文版本做哈希）。沙盒创建不直接暴露凭据给通用 `agent_envs` 路径，而是由 provider 新增 `coding_env` 参数合并进 create 请求；映射到镜像原生约定：

- opencode：`OPENCODE_PROVIDER`、`OPENCODE_MODEL`、`OPENCODE_BASE_URL`、`OPENCODE_API_KEY`、`OPENCODE_PROVIDER_NPM`（Anthropic 端点自动用 `@ai-sdk/anthropic`，其他用 `@ai-sdk/openai-compatible`）；高级用户可提供 `OPENCODE_JSON`。
- codex：`CODEX_MODEL`、`CODEX_BASE_URL`、`CODEX_API_KEY`（或 `OPENAI_API_KEY`），高级用户可提供 `CODEX_CONFIG_TOML`；审批与沙盒策略由平台按会话策略覆盖生成，不允许用户 TOML 放宽平台边界。**codex 0.139 只支持 Responses API**（`wire_api="chat"` 被拒绝，实测），凭据预检必须校验端点提供 `/v1/responses`（OpenAI 官方、DeepSeek 官方、ARK 可用；纯 chat-completions 端点不可用），不满足时返回 `executor_unavailable`，不做静默回退。M0 实测契约见 [编码 CLI 契约](../../../../agents/coding-cli-contract.md)。
- CLI 状态持久化：`CODEX_HOME` 与 opencode 的 XDG 数据目录指向 `agents/coding/<session_id>/cli-state/`（P0 探针确认 opencode 1.4.6 生效变量；不生效则以 `opencode export/import` 作为恢复兜底）。

**使用前预检**：`coding_session_start` 先解析凭据；缺失即结构化失败（`error_code=credential_missing`，附「去设置页配置」指引），不创建沙盒、不启动 CLI。

**env 时效**：容器 env 只在创建时注入。会话启动时比较 `session.credential_fingerprint` 与当前解析结果；不一致且 scope 无其他活跃 Run 时显式重建 runtime（workdir 字节保留，generation 变化记录为事件）；scope 忙时返回 `sandbox_env_stale_busy`，由用户选择等待或取消。

### 4. 执行适配层：三档通道与能力矩阵

统一适配器协议（Python Protocol，新增 `backend/package/yuxi/agents/coding/adapters/`）：

```text
prepare(runtime_env, session, credential) -> env_overrides + cli_state_paths
build_start(session, turn, policy)        -> command / stdin
build_send(session, turn, message)        -> command / stdin
parse_stream(chunks)                      -> NormalizedEvent[]
capabilities()                            -> {plan, steer, resume, approval, terminal, usage}
extract_result(turn)                      -> summary + session_ref + usage
```

| 能力 | 无头一次性（P2） | 程序化会话（P4） | 终端直连（P5） |
|---|---|---|---|
| opencode | `opencode run --format json [-s id\|-c] --agent plan -m provider/model` | `opencode serve`（HTTP+SSE，经 provisioner HTTP 代理）+ `--attach`/SDK | `get_terminal_url` + provisioner WS 代理 + xterm |
| codex | `codex exec --json [resume id]`，计划轮 `-s read-only`、执行轮按策略给 `workspace-write` | 每轮 `codex exec --json/resume` 包在 SDK shell session 中轮询增量；`app-server` 仅 P6 探索 | 同上；codex TUI 交互 |
| 中途 steer | 不支持（turn 原子） | opencode serve 支持；codex 按轮 | 人在终端里直接操作 |
| 命令级审批 | 平台策略预置（workspace-write + 无提权），不支持逐命令询问 | 可把 CLI 审批事件升级到平台审批流 | 原生 TUI 询问 + 平台事件镜像 |

事实纪律：能力差异必须在 `capabilities()` 声明并由工具层显式呈现，不允许「能力不存在但静默降级为成功」。`opencode acp` 在 P6 作为统一协议接入点评估，适配器接口从第一天按「可新增第三个实现」设计。

### 5. Agent 工具面

新增 `backend/package/yuxi/agents/coding/tools.py`，经 `toolkits/registry.py` 的 `@tool(category="coding")` 注册：

| 工具 | 语义 |
|---|---|
| `coding_session_start(executor, task, mode='plan_then_execute', workdir='.', model=None, budget=None)` | 建会话 + 可选 worktree + 首轮；返回 `session_id/turn_id/status/stream_url` |
| `coding_session_send(session_id, message, interrupt=False)` | 下一轮输入（agent 主导多轮） |
| `coding_session_status(session_id)` | 状态、turn 摘要、待审批、usage、最近事件（有界） |
| `coding_session_await(session_id, timeout_seconds=None)` | 等到 turn 终态或 needs-input |
| `coding_session_control(session_id, action)` | `cancel_turn / kill / pause / resume / approve_plan / reject_plan / detach_user` |
| `coding_session_list(project_id=None, status=None)` | 为「自主选择/管理」提供真实清单 |

- **门控与可见性**：仅根 Agent 可见（与敏感 backend 工具同策略，子 Agent 隐藏）；由 Agent 配置 `coding.enabled`、`coding.executors` 白名单、`coding.default_executor` 控制；工具只有在白名单非空且凭据可解析时进入工具集（沿用 `resolve_configured_runtime_tools` 的白名单模式，`backend/package/yuxi/agents/toolkits/service.py:97-179`）。
- **审批**：`tool_approval.py` 的 `interrupt_on` 增加 `coding_session_start`（默认模式必拦截，审批载荷含：executor、任务、workdir/worktree、预算、首轮计划）；`always_trust` 不拦截。会话内 `send`/`control` 继承已批准会话的策略，不再逐次弹审批；命令级审批仅在 P4/P5 通道出现，映射进现有 HITL 语义。
- **审计**：turn 输入输出、结果与 usage 写 `tool_audit` 同构记录；事件正文写会话事件表；敏感值在写库和发流前按注入明文做值级脱敏。
- **预算**：`max_turns`、`max_wall_clock_seconds`、`max_usage` 由 supervisor 硬执行（超限 kill + `failed(budget_exceeded)`），不靠提示词约束。

### 6. 多轮交互与 agent 控制

**会话状态机**（由 `CodingSessionService` 在行锁事务内迁移，全部持久）：

```text
pending → starting → running(turn) → idle | awaiting_plan_approval | awaiting_user
        | suspended | completed | failed(code) | cancelled
```

**轮次协议**：

1. `start` 默认 `plan_then_execute`：第一轮只允许计划表达（opencode 用只读 agent/plan 能力，codex 用 `read-only` 沙盒策略；P0 探针确定原生开关，不成立则由 agent 先在 Yuxi 侧生成计划交用户审批）。用户批准后进入执行轮。
2. `send` 每次推进一轮；turn 结束产出：摘要、变更文件清单（从 CLI 事件/git diff 双源核对）、usage、原生 session ref。
3. `await` 支持 agent 并行做别的事后回来收割（与 `subagent_await` 同范式），超时返回 `wait_timed_out` 且不改变 turn 状态。
4. `cancel_turn` 通过 SDK session kill 终止进程组，再落 `cancelled`；不假定「进程已死 = 无副作用」，事件中明确提示需核对文件。

**人工接管**：终端面板 attach 时创建短期 ticket，`CodingSessionService` 标记 `attached_by=user`；期间 agent 的 `send/control` 返回 `session_attached_by_user`（busy 语义），用户点击「交还 agent」后恢复。接管与交还都写事件与审计。

**自主选择**：新增内置 Skill `coding-executor`（`tool_dependencies` 指向 `coding_*` 工具），内容包含两个执行器的能力/成本/适用场景与当前可用性；agent 在配置白名单内自主选择，确定性约束只有：白名单、凭据可用性、单会话单 turn、scope 并发上限。不可用即显式错误，不做隐藏路由或静默回退。

### 7. 持久会话与沙盒生命周期

沙盒身份、保活、suspend/rebuild 与执行租约的 Owner 是《Agent 专属沙盒与生命周期策略》（`2026-09-18-agent-dedicated-sandbox-lifecycle.md`），本节只保留编码会话自身的绑定与恢复语义，两者不重复定义事实。

- **绑定**：会话绑定根 Run 的 runtime scope 与 Project `workdir_path`；推荐每会话用现有 `git_prepare_worktree` 建独立 worktree 目录作为会话 workdir，实现任务级隔离与宿主侧推送。
- **生命周期前提**：编码会话建议运行在 `persistent` 或 `resident` 沙盒策略下（该提案的 agent+项目配置）；默认 `ephemeral` 时编码会话启动提示配置专属沙盒，但不强制阻断，按本节恢复语义兜底。会话 turn 的执行竞争使用该提案的统一执行租约（每沙盒串行），终端接管持同一租约。
- **跨 Run 恢复**：`resume` 由该提案的 `ensure_ready` 决策复用或重建 runtime（workdir 字节保留，generation 更新）→ 用原生 session ref 恢复 CLI 会话；原生状态丢失（tmpfs/版本变化）时降级为「新 CLI 会话 + 平台侧上下文摘要」，并在事件中标明 `resume_degraded`，不伪装连续。
- **并发**：同一沙盒允许多会话存在，但通过执行租约串行；每会话单 active turn，scope 级活跃会话上限由该提案的配额配置控制，超出显式拒绝。

### 8. 数据模型（yuanlei 域 v4 → v5）

新增四表（`manager.py` yuanlei 域语句 + `storage_migration.py` 幂等升级链 + `_require_supported_version` 的 `upgrade_from` 扩展）：

- `coding_credentials(id, scope, uid, executor, provider, base_url, model, api_key_cipher, extra_json, status, version, created_at, updated_at)`；唯一约束 `(scope, uid, executor, provider)`。
- `coding_sessions(id, uid, project_id, conversation_id, parent_run_id, runtime_scope_id, executor, mode, status, title, workdir_path, worktree_ref, sandbox_id, sandbox_generation, credential_fingerprint, cli_session_ref, policy_json, budget_json, usage_json, last_activity_at, suspended_at, terminal_at, error_code, error_message, created_at, updated_at)`。
- `coding_session_turns(id, session_id, seq, request_text, status, result_summary, usage_json, started_at, ended_at, error_code, error_message)`；唯一 `(session_id, seq)`。
- `coding_session_events(id, session_id, turn_id, seq, kind, payload_json, created_at)`；唯一 `(session_id, seq)`，按保留策略裁剪（终态 + N 天或每会话上限）。

约束与顺序：FK 指向 business 域 `users`、`projects`（yuanlei 迁移在 business 收敛之后执行，遵循 `docs/develop-guides/yuanlei/README.md` 的归属规则）；`YUANLEI_SCHEMA_VERSION` 3→4；不动 business/knowledge 域版本。

### 9. 事件、审计与前端投影

归一化事件 `kind`：`session_status`、`turn_started`、`turn_finished`、`output_delta`、`tool_call`、`file_change`、`plan`、`approval_request`、`usage`、`warning`、`error`。

- **持久路径（事实）**：事件写 `coding_session_events`；turn 终态与结果写 `coding_session_turns`；会话状态写 `coding_sessions`。
- **在线路径（投递）**：Redis Stream `coding:events:{session_id}`，与 Run Stream 同构 envelope 与 seq；断线用 `after_seq` 重放。
- **SSE**：`GET /api/coding/sessions/{id}/events`（独立于 Run SSE），前端会话面板订阅；agent 工具生命周期内，Run SSE 通过 `custom` 事件携带 `yuxi.coding_session_event` 摘要（沿用 `run_worker.py:769-784` 的映射位）。
- **前端**：新增 `CodingSessionCard`（状态、turn 时间线、文件变更、usage、审批按钮）与 `CodingTerminalPanel`（P5，xterm.js）；`ToolCallRenderer.vue` 注册表增加 `coding_*` 渲染项；工具审计与调试面板沿用现有读接口。新增依赖仅 `@xterm/xterm` 及其 fit addon，不引入其他终端运行时。

### 10. API 面

- 用户凭据：`GET/PUT/DELETE /api/user/coding-credentials`（write-only 值，掩码读）。
- 会话管理：`GET/POST /api/coding/sessions`、`GET /api/coding/sessions/{id}`、`GET .../events`（SSE）、`POST .../input`、`POST .../control`、`GET .../terminal-ticket`。
- 终端：`GET /api/coding/sessions/{id}/terminal?ticket=...`（WebSocket）。provisioner 新增 WS 代理：仅对升级请求开放，校验 Bearer 后按 sandbox_id 转发到沙盒 nginx 的 `${OPENCODE_PORT}`/终端路径；ticket 由服务端签发、单会话单次、短 TTL，浏览器不携带 provisioner token。若 P5 发现 WS 代理安全/稳定性不达标，终端回退为「程序化事件只读 + 输入走 HTTP」，不阻塞主线。
- 管理端：全局凭据 CRUD、会话审计读接口（按 uid 过滤，权限与现有调试面板同级）。

### 11. 安全与失败语义

- 凭据：AES-GCM + AAD + fail-closed；响应/日志/事件/审计值级脱敏（注入时持有明文，可对输出做精确替换与 canary 测试）。
- 边界：编码会话 workdir 只能落在 Project Workdir 内（复用 no-follow 校验）；终端 cwd 固定 workdir；沙盒虚拟路径规则不新增第四条路径。
- Git：沙盒不注入 token；会话结束后由 agent 走现有 `git_push_branch`（宿主侧执行）推送 worktree 分支。
- 命令行不携带密钥：密钥只经 env 注入，禁止拼进 argv（argv 会进审计）。
- 失败语义：turn 崩溃/lease 过期 → 状态收敛 `failed`，CLI 残留进程由 supervisor 收养或 kill；外部副作用按 at-least-once 提示核对；未知 CLI 事件不静默丢弃，记录 `warning` 事件；版本与适配器声明不符（例如 CLI 升级改变 JSON schema）时显式降级/禁用该执行器。

### 12. 分阶段实施计划

本提案与《Agent 专属沙盒与生命周期策略》共用一份合并实施计划（契约先行、单一依赖序、默认行为不变）：[Agent 编码执行与专属沙盒：合并实施计划](../../../planning/agent-coding-execution-plan.md)。本记录不维护第二份阶段表；验收主张仍以本文与沙盒提案的验收矩阵为唯一来源。

### 13. 与现有机制的关系

- 复用：Run/lease/事件/SSE/审批/SubAgent 范式、`git_prepare_worktree`、沙盒 provider 与 provisioner、Skills 依赖门控、audit 与调试读接口。
- 最小侵入：本提案只改一个上游文件——`tool_approval.py` 增加 `coding_session_start` 的 `interrupt_on` 项；`run_worker.py` 的清理判定改动归《Agent 专属沙盒与生命周期策略》，其余全部落在 `agents/coding/`、yuanlei 域与前端新组件。
- 不变式保留：PostgreSQL 事实优先、Redis 只做投递、终态清理与 Workdir 保留、密钥不进沙盒明文通道、路径三层、Sandbox runtime 由 scope 唯一拥有。

## 替代方案

1. **只包装现有 `execute`（`opencode run` / `codex exec` 一次性字符串）**：成本最低，但无流式、无多轮、无原生 session，agent 无法控制进行中的执行；仅作为 P2 的起点被本提案吸收，不作为终态。
2. **用 `codex mcp-server` 把 codex 接成 Yuxi 远程 MCP 工具**：被 `docs/agents/mcp-integration.md:12` 的 stdio 禁令排除；且 MCP 无会话生命周期与租约语义，只有 codex 可覆盖。
3. **在宿主机部署独立 coding-agent 服务，不放进用户沙盒**：破坏既有「每用户 Workdir + 沙盒隔离」信任边界，需要新的隔离与配额体系；沙盒已是现成边界。
4. **只做 `opencode acp` 统一协议，codex 等 ACP 支持**：codex 0.139.0 无 ACP；单协议方案会阻塞双执行器目标。ACP 保留为适配器第三实现。
5. **把密钥继续放在 `agent_envs` 明文通道**：无加密、GET 回显、无使用前校验；与「用户级加密 + 管理端兜底」的验收目标冲突。
6. **会话不持久，Run 终态即销毁沙盒**：无法满足跨 Run 多轮协作；仅作为会话 `suspended` 后的回收路径存在。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 未配置/坏配置凭据时启动会话显式失败，不创建沙盒、不静默回退 | 以空 env 启动 CLI 并把认证失败伪装成运行成功 | `CodingCredentialService` + `coding_session_start` | `docker compose exec api uv run --group test pytest test/integration/coding/test_coding_credentials.py` | 删除凭据/写入坏 key 后重跑，断言 `credential_missing`/`credential_invalid` 且无 sandbox create 调用 | Not run |
| 用户级密钥加密落库，全部读接口与日志不回显明文；master key 缺失 fail-closed | 明文进 DB/API/日志/事件 | 凭据 repository + AES-GCM 服务 | 同上 + `pytest test/unit/coding/test_credential_cipher.py` | 直读 PG 断言无明文；移除 `YUXI_CODING_CREDENTIAL_KEY` 后接口返回禁用错误而非空值 | Not run |
| 沙盒创建时按镜像原生约定注入 opencode/codex 配置并能通过认证 | env 合并优先级错误导致用户被全局覆盖或反了 | sandbox provider `coding_env` 合并 | E2E：`test_deterministic_coding_path_e2e.py` 中两个执行器各跑一轮真实任务 | 注入错误 key 时必须看到认证失败事件，而非模糊超时 | Not run |
| 同一会话多轮 `send/await` 可用，并发 turn 显式 busy | 双驱动写坏同一 CLI 会话 | `CodingSessionService` 状态机 | `pytest test/integration/coding/test_session_turns.py` | 并发 `send` 第二次返回 `turn_busy`，不产生第二个 turn 记录 | Not run |
| `cancel_turn` 终止 CLI 进程组并正确落终态 | 只改数据库状态、进程继续写文件 | `CodingSupervisor` | E2E + `沙盒内 pgrep` 断言 | 取消后断言进程不存在、turn=`cancelled`、事件含副作用核对提示 | Not run |
| 跨 Run 恢复：会话 suspend 后 resume 保留 workdir 字节并恢复或显式降级 | 声称恢复但上下文丢失无标记 | 会话服务 + provider | `pytest test/integration/coding/test_session_resume.py` | 手动 kill sandbox 后 resume；断言 generation 变化、workdir 字节一致；原生状态缺失时事件含 `resume_degraded` | Not run |
| 默认审批模式 start 需计划审批，reject 不启动执行轮 | 审批被绕过或拒绝后仍执行 | `tool_approval.py` + HITL 链路 | E2E：审批弹窗 approve/reject 两条路径 | reject 后断言无执行轮 turn、CLI 未启动 | Not run |
| 事件流不携带密钥明文（值级脱敏 + canary） | canary 泄漏到 PG/Redis/SSE/日志 | 脱敏中间件 + 会话事件服务 | E2E 注入 canary key 后 `grep` 各存储与事件流 | canary 命中即失败；大小写/编码变体同样覆盖 | Not run |
| 终端接管期间 agent 工具返回 busy，交还后恢复 | 双源同时输入 | 终端服务 + 会话状态机 | P5 浏览器 E2E + `pytest test/integration/coding/test_terminal_ticket.py` | 接管中 `coding_session_send` 返回 `session_attached_by_user`；过期 ticket 被拒 | Not run |
| 沙盒保活与清理 fence：活跃会话不被 reaper 回收，会话终止后 runtime 收敛 | 长驻容器泄漏或 Run 清理误删活跃会话沙盒 | `provider` + `_release_runtime_if_idle` 扩展 | `pytest test/integration/coding/test_runtime_lifecycle.py` | 无会话时保持现有清理行为；会话活跃时清理请求返回不释放 | Not run |
| CLI 事件归一化稳定，未知事件不静默丢弃 | CLI 升级后事件丢失无告警 | 适配器 `parse_stream` | 录制 fixtures 的合同测试 `pytest test/unit/coding/test_adapter_events.py` | 注入未知 kind 断言产生 `warning` 事件而非丢弃 | Not run |
| yuanlei v4→v5 迁移幂等且不触碰 business/knowledge 域 | 迁移重复执行报错或越域 | `storage_migration.py` + `manager.py` | `pytest test/integration/services/test_schema_migration_version.py` | 连续两次迁移；断言 business/knowledge 版本与表结构不变 | Not run |
| 越权隔离：他人会话/终端/凭据不可读 | 跨 uid 读取或接管 | 路由层 + repository 可见性 | `pytest test/integration/coding/test_coding_authz.py` | 跨 uid 请求返回 404/403，且无侧信道差异 | Not run |
| 自主选择：不可用执行器显式失败，无隐藏回退 | 静默换执行器导致用户失去控制 | `coding_*` 工具 + allowlist | 单测 + E2E | 只有 opencode 有凭据时以 codex 启动必须失败并提示 | Not run |

## 风险

- **镜像外部依赖**：opencode/codex 与渲染脚本由外部 AIO 镜像提供；M0 已实测版本、事件 schema、XDG/CODEX_HOME 持久化与 profile 行为（见 [编码 CLI 契约](../../../../agents/coding-cli-contract.md)），但版本升级仍可能改变 JSON 事件 schema。缓解：adapter 合同测试 + 版本探测 + 显式降级；必要时用 `SANDBOX_IMAGE` 构建自持镜像。
- **codex 的 Responses API 依赖**：0.139 只接受 `wire_api="responses"`，chat-completions 端点不可用；可用性取决于用户/管理端配置的端点能力。缓解：凭据预检校验能力并显式 `executor_unavailable`；失败不静默切换到 opencode。
- **上游同步冲突**：清理 fence 与审批接线会改动两个上游文件。缓解：只做最小 diff，逻辑放元垒模块；yuanlei 域版本纪律与上游同步四阶段流程。
- **密钥暴露面**：CLI 可能把 key 打进输出/错误。缓解：只经 env 注入、值级脱敏、canary 负向测试、审计写库前统一过滤。
- **长驻资源与成本**：跨 Run 会话会长期占用沙盒与模型 token。缓解：空闲 suspend、预算硬杀、每 scope 会话上限、用量事件与看板。
- **at-least-once 副作用**：turn 崩溃时文件系统可能已被 CLI 修改。缓解：worktree 隔离、状态机显式、终态事件给出核对指引、取消/失败不静默接续。
- **WS 代理安全面**：终端通道新增升级路径。缓解：单会话单次 ticket、短 TTL、仅终端路径升级、越权与重放负向测试；不达标则回退 HTTP 方案。
- **codex app-server 实验性**：不进一期依赖，只作 P6 探索；P4 的 codex 通道基于稳定的 `exec --json`。
- **并发语义复杂**：多会话共享一个 scope 沙盒可能互相影响进程资源。缓解：会话级 worktree、单 active turn、scope 上限、事件化审计。
