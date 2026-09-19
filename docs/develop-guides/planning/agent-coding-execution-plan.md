# Agent 编码执行与专属沙盒：合并实施计划

版本：V0.1；状态：草稿；维护方式：随两份提案的评审结论更新，不独立发明需求

关联提案（验收主张的唯一来源，本计划只做阶段映射）：

- [智能体驱动沙盒内 opencode/codex 编码执行](../yuanlei/decisions/proposed/2026-09-18-agent-driven-coding-cli-sessions.md)
- [Agent 专属沙盒与生命周期策略](../yuanlei/decisions/proposed/2026-09-18-agent-dedicated-sandbox-lifecycle.md)

## 为什么合并

两份提案在 7 个面相互影响，分开排期会产生两套 supervisor、两次 yuanlei 版本提升和重复的等待/确认 UX：

1. **runtime scope 语义**：编码会话的绑定与跨 Run 恢复依赖专属沙盒的 scope 泛化（thread → agent_project）。
2. **执行租约**：会话 turn、终端接管与「每沙盒串行」必须是同一套租约，不能各建一套锁。
3. **凭证指纹**：编码凭据解析产出指纹，专属沙盒按指纹变化触发重建；这是同一契约的两个使用点。
4. **worker 监督基础设施**：会话 turn 泵送与沙盒保活/suspend/inventory 对账属于同一类周期任务，统一实现。
5. **yuanlei 迁移版本**：两批表格需要一次协商，否则版本顺延与交叉引用混乱。
6. **运行态 UX**：`sandbox_waiting`、`sandbox_rebuild_required` 同时服务于编码会话面板与普通 Run 的等待提示。
7. **配置与配额**：agent 配置页同时出现 coding 与 sandbox 区块，默认值与上限互相引用。

合并原则：契约先行（M0）、单一依赖序、单一 supervisor、默认行为不变（不配置则完全维持现状）、一次迁移协商。

## 依赖顺序

```text
M0 契约探针与接口冻结
 ├─► M1 凭据与配置基座 ─┐
 └─► M2 沙盒身份与生命周期核心 ─► M3 执行租约与串行 ─► M4 无头编码执行
                                                       └─► M5 持久编码会话
                                                            └─► M6 程序化通道与自主编排
                                                                 └─► M7 终端直连
                                                                      └─► M8 管理面与运维收尾
```

- M1 与 M2 在 M0 之后可并行（触碰文件不重叠：M1 在 config/凭据/前端设置，M2 在 sandbox/provisioner/worker）。
- M4 依赖 M3，而不是反过来；专属沙盒串行语义先成立，编码工具直接落在其上，避免二次改造。
- 每个阶段独立可交付、可回滚；所有新能力默认关闭，未配置专属的 agent 与未启用 coding 的 agent 行为逐阶段保持现状。

## 共享契约（M0 冻结，之后不允许各自解释）

1. **scope 与沙盒 id**：`thread:{uid}:{thread_id}` 或 `agent-project:{uid}:{agent_slug}:{project_id}`，`sandbox_id = sha256(scope_key)[:12]`；Run 的 `runtime_scope_id` 保持不透明字符串，`run_worker` 校验同时接受两种 scope 形态。
2. **执行租约**：字段、获取/心跳/释放/过期语义与 `sandbox_busy` 返回结构；接管前必须校验 generation；等待事件与超时错误结构固定。
3. **凭证/环境指纹**：定义 = 解析后的非密配置 + 密文版本 + 相关沙盒 env 贡献的哈希；由凭据解析输出，沙盒层只存储与比较，不自行计算。
4. **事件命名**：`yuxi.sandbox_waiting`、`yuxi.sandbox_rebuilt`、`yuxi.sandbox_rebuild_required`、`yuxi.coding_session_event`；未知事件记 `warning`，禁止静默丢弃。
5. **迁移版本协调**：一个发布窗口内新增表只升一次 yuanlei 版本；两批表格同期则一次性进 v4，分开则后者顺延并在两份提案中更新交叉引用。business/knowledge 域不动。

## 阶段

### M0 契约探针与接口冻结（状态：已完成）

- 交付：`docs/agents/coding-cli-contract.md`（CLI/镜像契约）、`docs/agents/sandbox-lifecycle-contract.md`（生命周期契约）、M0 共享契约记录（并入上述文档或实现说明）；可复跑探针脚本。
- 必须关闭的未知项：
  - CLI：`core` profile 下 opencode server 是否随入口启动；opencode XDG/CODEX_HOME 持久化变量是否生效；`run --format json`、`exec --json` 事件样本；codex 非交互审批语义；plan 能力开关；终端 URL 与沙盒 nginx 端口代理可达性。
  - 生命周期：provisioner 按沙盒 TTL 与 resident 跳过 reaper 的行为；容器跨 provisioner 重启后的 inventory 对账；执行租约在真实 worker 重启下的过期接管。
- 退出证据：文档中每条命令与样本都有真实运行输出；无法成立的项给出降级设计。无生产代码改动。

### M1 凭据与配置基座（M1a/M1b 完成）

- 进度（M1a，2026-09-18）：`coding_credentials` 表随 yuanlei v4→v5 落地（ORM + DDL + 迁移链与真实 PG 幂等测试）；`coding/credentials.py` 提供 AES-GCM（`YUXI_CODING_CREDENTIAL_KEY`、AAD 绑定 scope/uid/executor/provider/id、缺失 fail-closed）、`credential_fingerprint`（非密配置 + 密文版本）、`redact_credential_values`；`CodingCredentialRepository`/`CodingCredentialService`（用户级 > 全局解析、掩码视图、轮换版本自增、删除销毁密文）；用户/管理端 API `/api/user/coding-credentials`、`/api/system/coding-credentials`（write-only + 掩码读，未知 executor 422，缺 master key 503）；`.env.template` 与 compose（dev/prod）注入新密钥。`agents.config_json.sandbox` 与项目覆盖合并已在 M2.4 完成。
- 进度（M1b，2026-09-18）：系统配置新增 `sandbox_dedicated_max_per_user`（默认 3）与 `sandbox_resident_max_per_user`（默认 1），`int` 类型规范化与「常驻 ≤ 专属」保存校验；`ensure_ready` 仅在创建新绑定时强制每用户专属/常驻配额，超限抛 `sandbox_quota_exceeded`，已有绑定不受新增限制；设置页新增「编码执行器凭据」卡（列表掩码、保存 write-only、删除）并注册 tab。
- 证据：coding 13 + router 2 + 配额/生命周期 16 + 配置 11；web `lint:check` 通过、unit 367 passed、build 成功；全量后端单测 2368 passed（仅 3 个既有 xlrd 环境失败）。
- 未验证/待补：设置页凭据卡的真实浏览器截图（当前环境无浏览器工具，仅完成 lint/unit/build）；管理端全局凭据的图形化配置随 M8 管理面板；配额在 Agent 配置保存表单层的提示（当前由创建时结构化失败兜底）。
- 交付：`coding_credentials`（yuanlei）+ AES-GCM 服务 + 用户/管理端 API + 设置页凭据卡；`agents.config_json.sandbox` 与 `project_agents.config_overrides.sandbox` 字段与合并逻辑；系统配额配置项；指纹实现（按 M0 契约）；输出脱敏。
- 退出证据：编码提案矩阵第 1、2 行；沙盒提案矩阵第 9 行；指纹契约单测。
- 迁移：已按顺序推进——专属沙盒表进 v4，编码凭据表进 v5。

### M2 沙盒身份与生命周期核心（进行中）

- 进度：M2.1–M2.5 与 M2.6a 已落地（provisioner 生命周期字段、yuanlei v4 表与迁移、`SandboxScope`、策略/repository/lifecycle service、生命周期 supervisor、清理谓词分派）。M2.6b 运行接线已完成：FIFO 派发创建 Run 时按策略固化 `runtime_scope_id`（`resolve_dispatch_runtime_scope`），resume 继承父 Run 的 runtime scope（与 SubAgent 一致），`_validate_run_workdir_binding` 接受 agent-project scope 并校验 Agent/Project，`_BackendScope`/`ProvisionerSandboxBackend` 按 scope 取连接（专属走 `get_scope`），Run 准备阶段对 dedicated 策略执行 `ensure_ready`（confirm 暂以结构化失败阻断）。证据：affected 全量 1228 passed；M2 实现完成，专属沙盒真实链路（矩阵第 2/3/5 行）的集成验证随 M3/M4 一并补齐。下一阶段 M3 执行租约与串行。
- 交付：scope 泛化与 provider 身份校验；`agent_sandboxes` + `agent_sandbox_events`；provisioner 按沙盒 TTL/resident；`ensure_ready`/`suspend`/自动重建；生命周期 supervisor（保活、空闲 suspend、inventory 对账、孤儿租约清理）；ephemeral 默认路径回归。
- 退出证据：沙盒提案矩阵第 1、2、3、5、8、12 行；第 4 行的 auto 路径。
- 风险护栏：默认路径零行为变化；resident 与 persistent 受配额与面板约束。

### M3 执行租约与串行（实现完成，集成验证待补）

- 进度：`SandboxLeaseService` 已落地（acquire 独立事务轮询等待、heartbeat fencing、仅持有者可 release、`reconcile_expired` 过期收敛与事件）；Run 接线完成——专属 Run 在执行前获取租约（busy 落 `sandbox_busy` 终态）、RunContext heartbeat 同步续租（失去沙盒租约触发 lease_lost/取消，终态后静默退出）、终态事件前释放租约；supervisor tick 增加过期租约回收计数。事件写入 `agent_sandbox_events`（lease_acquired/lease_waiting/lease_released/lease_expired）。
- 证据：lease/supervisor/run_worker 66 passed；affected 全量 1236 passed。
- 待补：真实两 Run 争抢的集成用例（矩阵第 6 行）、旧 owner 接管后写入被拒的负向验证（矩阵第 7 行，provider generation fencing 已有单测）、`yuxi.sandbox_waiting` 的 Run SSE 投影（M4/M5 随工具与会话事件一起接）。
- 交付：租约字段与获取/心跳/释放服务；等待事件与超时；generation fencing 与过期收敛；Run、编码 turn、终端三类持有者的接入点（后两者在 M5/M7 使用）。
- 退出证据：沙盒提案矩阵第 6、7 行。

### M4 无头编码执行：适配器与执行环境（完成；工具面调整到 M5）

- 进度（2026-09-18）：`coding/adapters.py` 提供 `OpenCodeAdapter`（`run --format json [--agent plan] [-m] [-s]`，step_start/text/tool/step_finish/error→归一事件）与 `CodexAdapter`（`exec [resume] --json --skip-git-repo-check -s read-only|workspace-write`，thread.started/item.completed/turn.completed/turn.failed→归一事件），未知事件记 `warning` 不丢帧；`coding_executor_environment` 按 M0 契约映射 `OPENCODE_*`/`CODEX_*`；`CodingCredentialService.build_coding_environment` 按 Agent `coding.executors` 白名单解析凭据并聚合指纹；`provider.get_scope(env_overrides=...)` 在创建时合并 user env；`ensure_ready` 透传 env/指纹，指纹从无到有时触发重建；Run 准备阶段对 dedicated 沙盒构建 coding env 并注入。
- 调整说明：会话化 `coding_*` 工具、计划审批、turn 持久状态与最小会话卡片需要 M5 的 `coding_sessions/turns/events` 实体；先做工具会在 M5 二次改写，因此工具面随 M5 一起落地。
- 退出证据：编码提案矩阵第 1、3 行以单测覆盖（凭据缺失/环境映射/指纹触发重建）；第 5、7、10 行随 M5 工具与事件一起验证。
- 依赖：M1（凭据与指纹）、M3（专属 scope 下的串行）。

### M5 持久编码会话（M5a/M5b-1 完成，M5b-2 待做）

- 进度（M5a，2026-09-18）：`coding_sessions/coding_session_turns/coding_session_events` 三表随 yuanlei v5→v6 落地（ORM + DDL + 迁移链 + 真实 PG 幂等测试）；`CodingSessionRepository`（会话/turn/事件，seq 会话内递增、after_seq 回放）；`CodingSessionService` 显式状态机与 create/start_turn/finish_turn/record_events。
- 进度（M5b-1，2026-09-18）：`CodingExecutionService` 在专属 scope 内跑 headless turn（ensure_ready + 凭据 env/指纹 → 适配器命令 → `execute` → 归一事件持久化 → turn/会话终态，输出按注入密钥值级脱敏）；六个 `coding_*` 工具（start/send/status/await/control/list）经 `toolkits/registry` 注册（category=coding），由 Agent 配置 `coding.executors` 白名单门控（manifest 注入 `context.coding_executors`，未声明则工具不可见）；默认审批模式对 `coding_session_start` 走任务级计划审批；子智能体禁用全部 coding 工具。共享 scope 显式拒绝（`coding_scope_unsupported`）。
- 进度（M5b-2a，2026-09-18）：CLI 原生状态持久化到 Workdir（opencode `XDG_DATA_HOME/XDG_CACHE_HOME`、codex `CODEX_HOME` 并在 prelude 复制非密 config.toml），沙盒重建后原生会话可续；`resume_degraded` 在状态缺失时显式清空 session ref 并记录事件；`max_turns` 预算硬执行（超限会话落 `failed/budget_exceeded`）；前端新增 `CodingSessionTool` 会话卡片并注册 6 个 `coding_*` 渲染与图标/名称映射。
- 进度（M5b-2b，2026-09-18）：coding 工具通过 `get_stream_writer` 投影 `yuxi.coding_session_event`（含 session/turn/executor/state/usage/resume_degraded，Run SSE 以 custom 事件下发）；真实沙盒冒烟通过——经真实 provisioner 建立 agent-project scope 沙盒（注入 `OPENCODE_*`），`opencode run --format json` 返回 PONG，适配器解析出 `session_ref/output_delta/usage`，退出码 0，随后按 scope 释放并清理探针资源。
- 进度（M6a，2026-09-18）：只读会话 API 落地——`GET /api/coding/sessions`（按用户/Conversation 列表）与 `GET /api/coding/sessions/{id}?after_seq=&event_limit=`（详情 + turn 时间线 + 增量事件回放，越权 404）；内置 `coding-executor` Skill（工具依赖 + 执行器选择与分轮推进流程）随内置 Skills 同步发布。
- 进度（M6b-1，2026-09-18）：执行器设置落地——`resolve_settings` 合并 Agent `coding` 与项目覆盖，支持 `default_executor`（不在白名单自动回落 None）；`coding_session_start` 的 executor 可选，缺省用项目默认，不可用即显式失败；前端新增 `coding_session_api` 并在会话工具卡内按需拉取 turn 列表（消费 M6a 只读 API）。程序化通道预验证：真实沙盒内 `opencode serve` 经 provisioner 代理（`x-aio-proxy-port`）返回 200，SSE `/event` 流式可达（首事件 `server.connected`）。
- 进度（M6b-2a，2026-09-18）：新增 `GET /api/coding/sessions/{id}/events/stream` SSE 尾随流（轮询持久事件、keep-alive、终态且追平后 `coding_end` 收尾，支持 `after_seq` 断线续读；生成器支持注入 session factory 便于测试）；前端会话卡在非终态时按 2s 轮询刷新 turn 列表（终态/卸载停止）。
- 进度（M6b-3，2026-09-18）：异步 turn 与 supervisor 落地——`coding_session_start/send` 新增 `wait=false`：准备环境后创建 `pending` turn 入队并立即返回（要求 persistent/resident 专属沙盒，否则显式失败）；worker 新增 ARQ 任务 `process_coding_turn`（幂等跳过已终态/缺失 turn，执行前检查 Redis 取消信号，执行后若收到取消则 turn/会话落 `cancelled`）；`coding_session_await(session_id, timeout_seconds)` 轮询至最新 turn 终态或 `wait_timed_out`；`coding_session_control(cancel)` 对 running 会话发布 `coding:cancel:{session_id}` 信号；执行尾部抽取为共用 `_execute_turn_tail`（同步/异步同一路径）。设计约束已落实：异步 turn 不重复申请沙盒执行租约（串行由同 scope 的 Run 租约 + 单 active turn 保证），避免 await 与 supervisor 的租约死锁；mid-turn 进程级 kill 与 steer 仍待 SDK shell session 支持。
- 进度（M6b-4，2026-09-18）：进程级取消落地——`CodingExecutionService.terminate_cli_processes` 在专属沙盒内 `pkill` 活跃 opencode/codex 进程（前提是单 active turn，由会话状态保证）；`coding_session_control(cancel)` 对 running 会话发布信号并立即终止进程，阻塞中的 `execute` 随即返回非零退出，执行尾部依据取消信号把 turn/会话收敛为 `cancelled`。
- 待做（M6b 剩余）：mid-turn steer（需要 opencode `serve` 会话输入或 SDK shell session `write_to_process` 的协议接入，M6b-1 已证明 SSE 通道可达）、真实链路 E2E（专用 agent + 凭据，含 async 与 cancel）。完成后进入 M7 终端直连。
- 证据：M5a 会话服务 4 用例 + 迁移/模型测试；M5b-1 执行服务 6 用例；全量单测 2396 passed（仅 3 个既有 xlrd 环境失败）。
- 交付：`coding_sessions/turns/events`；会话 supervisor（与 M2 同一 worker 基础设施）；跨 Run 恢复与 `resume_degraded`；`resume_policy=confirm` 重建确认路径；预算硬执行。
- 退出证据：编码提案矩阵第 4、6、8 行；沙盒提案矩阵第 4 行的 confirm 路径。

### M6 程序化通道与自主编排

- 交付：opencode serve SSE；codex 逐轮 JSON 流（shell session 增量读取）；mid-turn steer；审批升级；executor registry 与 `coding-executor` Skill；完整会话面板。
- 退出证据：编码提案矩阵第 10（steer/未知事件）、14 行；P4 交付清单对应的真实链路 E2E。

### M7 终端直连（完成）

- 进度（2026-09-18）：provisioner 新增 WebSocket 代理 `/api/sandboxes/{id}/proxy/ws`（Bearer 鉴权、剥离自身 Authorization 后转发到沙盒 `/v1/shell/ws`、双向中继与 websockets 12–15 头部兼容）；API 新增 `POST /api/coding/sessions/{id}/terminal-ticket`（HMAC 短 TTL 门票，绑定 uid+session）与 `WS /api/coding/sessions/{id}/terminal?ticket=`（校验门票与归属，非专属 scope 拒绝，中继到 provisioner，并写 `terminal_attached/detached` 事件与 `policy_json.terminal_attached`）；前端新增 `CodingTerminalModal`（xterm 动态加载避免 SSR 测试破坏）与会话卡「打开终端」入口，vite `/api` 代理开启 `ws: true`。
- 证据：真实链路——经 provisioner WS 代理连接沙盒终端，收到 `restore_output/terminal_restored/output` 帧并验证 `{type:'input'}` 生效（`echo PROBE_OK` 回显）；门票单测（签名/绑定/过期/篡改/缺密钥）与 provisioner WS 鉴权 4401 用例；全量后端 2414 passed、web lint/unit/build 通过。
- 未验证：浏览器内真实页面截图（当前环境无浏览器工具）；终端接管期间 agent 工具 busy 语义尚未强制（`terminal_attached` 已可读，busy 拒绝留待后续小项）。

### M8 管理面与运维收尾

- 交付：沙盒管理面板与事件时间线（手动 suspend/重建/解除专属）；配额与用量展示；metrics；策略切换后的遗留 scope 清理；ACP spike 结论。
- 退出证据：沙盒提案矩阵第 10、11 行；ACP spike 产出接入/放弃结论并回写对应提案。

## 证据与门禁

- 每个阶段的验收主张以两份提案的验收矩阵为准，本计划不复制、不新增主张；矩阵中的 `当前结果` 在实现阶段逐行更新。
- 最低证据按根 `AGENTS.md` 证据表：纯逻辑 unit；API/权限/持久化真实 HTTP integration；Run/沙盒/恢复 E2E；前端 lint + unit + build + 页面验证。
- 每个阶段结束前必须证明「未配置专属、未启用 coding 的默认路径行为不变」，防止能力回退。
- 提交前按仓库门禁执行工程信任检查、根级测试与 web 检查（见根 `AGENTS.md` 与 `docs/develop-guides/testing-guidelines.md`）。

## M0 结果（已完成，2026-09-18）

- 出证文档：[编码 CLI 契约](../../agents/coding-cli-contract.md)、[沙盒生命周期契约](../../agents/sandbox-lifecycle-contract.md)；可复跑脚本 `scripts/probes/coding_cli_probe.sh`、`scripts/probes/sandbox_lifecycle_probe.sh`。
- 已关闭的未知项：
  - opencode 原生会话续跑（`-s`）与 XDG 状态持久化成立；`plan` agent 原生存在；`run --format json` 事件含 tokens/cost/sessionID。
  - codex 原生会话（`CODEX_HOME` + `exec resume`）成立；**codex 0.139 只支持 Responses API**，SiliconFlow 不可用、DeepSeek 官方与 OpenAI/ARK 可用 → 凭据预检必须校验端点能力。
  - `core` profile 不自启 opencode server，程序化通道需显式启动 `serve` 并经 nginx 端口代理（`x-aio-proxy-port`）访问，provisioner HTTP 代理可直接承载。
  - provisioner 闲置回收为全局 TTL；`GET discover/touch/proxy` 会计入活动，supervisor 对账必须用 list；容器跨 provisioner 重启存活；generation fence 删除 409 语义可用。
  - 共享契约（scope、租约、指纹、事件命名、迁移版本）已按上文冻结。
- 仍未关闭、转入实现阶段验证：K8s 后端与 quiesce、reaper 与长命令竞争、租约过期接管的双写防护（M3 负向测试）、终端 WS 代理可达性（M7，不达标降级为程序化只读 + HTTP 输入）。
