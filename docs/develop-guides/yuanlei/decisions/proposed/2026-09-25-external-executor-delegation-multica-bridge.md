# Decision：外部执行器委派抽象与 Multica 桥接

状态：proposed
类型：architecture
Owner：backend/package/yuxi/services/coding_execution_service.py
日期：2026-09-25
关联 Feature：[外部执行器委派与 Multica 桥接](../../features/external-executor-delegation.md)

方向评审：2026-09-25 研发评审官结论「事实 Owner 划分基本正确」；按评审意见收窄统一接口、重做 `channel_delegations` 状态分离与投递核对、明确入向游标 Owner 后进入实现。

事实 Owner 分工：本文提案跨越多个 Owner，实现时不得让本文档反向充当运行时事实源。统一委派编排落到新增 `backend/package/yuxi/services/delegation_service.py` 与 `backend/package/yuxi/delegation/`；codex/opencode 的执行与会话事实仍归 `CodingExecutionService` 与 `coding_sessions`；入向治理归一归 `governance_service.py`；委派事实、渠道凭据、同步游标与迁移归 `manager.py`、`storage_migration.py` 与渠道凭据服务；Workdir 物化归 `backend/package/yuxi/workspace/workdir.py`；工具门控归 `agents/toolkits/service.py` 与 `tool_approval.py`。

## 问题

元垒要有「执行与协同」面：把任务委派给外部执行者并回收结果。上游 Yuxi 拥有 Run、Conversation、队列、执行与事件链路；元垒已经具备两段可复用的既有能力，但缺少把它们收敛成一条通道的统一抽象。

入向事实已经存在但只覆盖一部分：`backend/server/routers/agent_invocation_channel_router.py` 把外部纯文本消息信封转换为规范 Run，`RunOrigin` 已承载 `source` / `channel` / `external_id`（`backend/package/yuxi/services/agent_request_service.py`）；治理四表 `governance_topics` / `governance_tasks` / `governance_decisions` / `governance_reports` 已把来源渠道、外部标识与链接归一为 `proposed → 审核 → canonical/rejected` 生命周期，`GOVERNANCE_SOURCE_CHANNELS` 已包含 `multica`（`backend/package/yuxi/storage/postgres/models_business.py`、`backend/package/yuxi/services/governance_service.py`）。

执行事实也已经存在但绑定在一种基底上：`coding_sessions` / `coding_session_turns` / `coding_session_events` 是 opencode/codex 的持久会话事实，`CodingExecutionService` 是执行入口，`CodingExecutorAdapter` 只拥有「如何调用某个 CLI、如何解析输出」，`coding_*` 工具是 Agent 工具面（`backend/package/yuxi/coding/adapters.py`、`backend/package/yuxi/services/coding_execution_service.py`、`backend/package/yuxi/agents/toolkits/buildin/coding_tools.py`）。这套能力的语义、凭据、沙盒和路径边界都限定在项目专属沙盒内，无法直接委派到项目沙盒之外的外部程序。

Multica 目前只是治理域里的一个来源渠道取值，没有消息/任务出向的桥接、没有加密的渠道凭据、没有结果回收路径。由此产生四类失败：委派给外部执行者的任务没有统一入口，codex/opencode 与外部渠道各写一套；外部执行结果无法作为可追溯的 Yuanlei 事实被回收，只能靠人复述；Multica 镜像有机会被当作第二事实源反向写元垒 canonical 状态；缺少 Multica 配置时整条协同能力不可用，元垒议题/任务也被牵连。

## 提案

### 1. 边界与所有权

- 元垒拥有规范化议题/任务的唯一事实源，Multica 是渠道与起草人。Multica 来源只产生 `proposed` 治理行，经人审核才成为 canonical；Multica 永不反向写元垒 canonical 状态。
- 外部执行只产生「委派事实」与「回收结果」，不改变委派来源议题/任务的审核状态，也不复制外部执行状态为 canonical。
- 不为外部执行伪造上游 `agent_runs` 行。上游 Run 的生命周期、lease 与终态由 worker 拥有；外部执行没有 Yuxi 内执行体，强行落 `agent_runs` 会制造第二状态 Owner 与无 Owner 的非终态 Run。委派以独立事实 + 统一读模型满足「结果回读为 Run/Artifact」的语义：结果绑定发起 Run，产物作为 Artifact 物化。

### 2. 统一可委派执行者接口

新增 `backend/package/yuxi/delegation/`，定义窄接口 `DelegatedExecutor`（Python Protocol）：

```text
key -> str
capabilities() -> {multi_turn, remote_artifacts}
dispatch(request) -> handle        # 先持久化投递意图，再创建外部/沙盒执行，写入委派事实
status(handle) -> state            # 返回本地状态与远端投影，不拥有外部终态
collect(handle) -> result          # 归一化摘要、产物引用、用量、错误
```

- `DelegationRequest`：`project_id`、`task`、`context_refs`（来源议题/任务）、`budget`、`initiator_run_id`。
- `DelegationHandle`：`operation_id`、`executor_key`、`session_id`（可空）、`turn_id`（可空）、`external_ref`（可空）。句柄绑定具体委派操作；沙盒场景的 `session_id` / `turn_id` 指向被委派的会话与那一轮 turn，`operation_id` 是元垒侧稳定操作标识。
- `DelegationResult`：`summary`、`artifacts`（Workdir 相对路径与/或外部 URL）、`usage`、`error_code`。
- `DelegationService` 拥有适配器注册、按适配器解析凭据、委派事实的持久化、单活跃尝试与收集租约、产物物化与统一读模型。

MVP 接口只覆盖委派、查询、回收三件事，不定义 `cancel`、`resume`、`streaming`。这些能力当前没有共同消费者：沙盒的取消与多轮续接由既有 `coding_*` 工具承担，Multica 没有对应能力，统一接口不提前承诺。`capabilities()` 只声明有消费者的两项：`multi_turn`（是否存在稳定的多轮续接入口）与 `remote_artifacts`（产物是否只以远端 URL 暴露）；能力缺失时结构化失败，不静默降级。`DelegationService` 只做编排，不重实现任何执行基底。

### 3. 与既有 coding_* 的关系

- 沿用，不替换、不收窄。`CodingExecutorAdapter` 继续是沙盒内 CLI 的协议适配；`CodingSessionService` 与 `coding_sessions` 继续是 codex/opencode 的会话与执行事实 Owner。
- 新增 `SandboxCodingExecutor`（executor key 为 `opencode` / `codex`）作为 `DelegatedExecutor` 实现，内部复用 `CodingExecutionService` 与 coding session 仓储。`dispatch` 等价于 `create_session` 后 `queue_turn`；返回句柄携带该 `session_id` 与该轮 `turn_id`；`status` / `collect` 读取这一轮 turn 与其结果，不读相邻 turn。
- `coding_*` 工具保留，继续提供 start/send/await/status/cancel 的轮次控制。同一会话的后续轮次继续走 `coding_*`，统一接口不提供 `resume`。两者指向同一会话事实，是同一执行的两个入口。
- Multica 没有沙盒内 CLI 的续接入口，`capabilities.multi_turn` 为 false，返回的句柄只有 `operation_id` 与 `external_ref`。

### 4. 持久化与回收路径

- codex/opencode：不新增平行会话表，`coding_sessions` 保持唯一执行事实；`DelegationService` 从会话仓储装配统一视图。
- Multica 等外部渠道：新增 yuanlei 表 `channel_delegations`，字段：
  - `id`（主键）、`operation_id`（唯一，元垒侧稳定操作标识，由发起方生成）
  - `project_id`、`initiator_run_id`（FK `agent_runs`，只引用发起 Run）
  - `executor_key`
  - `external_ref`、`external_url`（远端标识与链接，投递确认前为空）
  - `dispatch_state`（本地投递/回收状态，Owner 为 `DelegationService`）：`pending` / `dispatched` / `collecting` / `reclaimed` / `failed`；`attempts`
  - `remote_status`（远端执行状态的只读投影）、`remote_status_synced_at`（投影时间）
  - `result_summary`、`result_json`、`artifact_path`
  - `owner_token`、`lease_expires_at`、`error_code`、`last_error_at`、时间戳
  - 唯一约束 `operation_id`；索引 `(dispatch_state, lease_expires_at)` 与 `project_id`
- 先持久化投递意图：`dispatch` 先在独立事务写入 `operation_id` + `dispatch_state='pending'` 并提交，再调用执行器。进程崩溃后，`pending` / 超租约的 `dispatched` 行由确定性 worker 收敛，不丢投递意图。
- 本地状态与远端投影分离：`dispatch_state` 只由 `DelegationService` 写；`remote_status` 是远端执行的只读投影，远端状态变化不改写 `dispatch_state`，也不复制为 canonical。统一读模型同时呈现两者，由消费方区分。
- 结果归属：回收结果只绑定 `initiator_run_id`，不产生新的 `agent_runs` 行，不声称远端执行对应某个元垒 Run。
- Workdir 物化：远端文本结果写入 Project Workdir 下 `.yuanlei/delegations/<operation_id>/result.md`，经 `backend/package/yuxi/workspace/workdir.py` 的 `Workdir.replace_file` / `write_file`，由 `workspace/filesystem.py` 的 `_require_within` 校验路径边界。`artifact_service.py` 继续是下载/保存读取用例，不在此新增物化写用例；外部文件只存 URL 引用。
- 入向游标：新增 yuanlei 表 `channel_sync_cursors`，按渠道记录同步进度（`channel`、`project_id`、`cursor_value`、`last_synced_at`、`owner_token`、`lease_expires_at`、`last_error`），Owner 为确定性同步服务（见第 5 节）。
- 迁移仅进 `yuanlei` 域，幂等升级链挂接并升 `YUANLEI_SCHEMA_VERSION`，不触碰上游 `business` / `knowledge` 域。

### 5. Multica 桥接

#### Multica 契约（2026-09-25 核实）

依据 `multica` CLI 帮助与 `multica-platform` skill reference（`references/issues.md`）：

- 创建：`multica issue create` 对应 `POST /api/issues`，必填标题，返回 `id`（UUID）与 `identifier`。服务端没有调用方提供的幂等键，也没有按外部引用 upsert 的入口；`--allow-duplicate` 只关闭服务端的重复告警，不提供幂等保证。
- 查询：`multica issue get <id>`（`GET /api/issues/<id>`）；`issue list` 支持 project / status / metadata / property 过滤与 offset/limit 分页；`issue search <query>` 匹配标题、描述与评论正文。
- 元数据 KV：`issue metadata set/get/list/delete` 维护每 issue 的 KV，`issue list --metadata key=value` 可按它过滤；写入是创建后的独立调用，与创建不原子。
- 状态：`backlog` / `todo` / `in_progress` / `in_review` / `blocked` / `done` / `cancelled`，附带 `status_category` 生命周期分类。
- 重复标记：`GET /api/issues/<id>/duplicates` 返回双向重复关系。

结论：Multica 不提供幂等创建，元垒侧必须自己保证「同一操作不产生第二个远端工作项」，用稳定 `operation_id` 与核对来实现。

#### 入向（Multica → 元垒）

- 新增确定性同步服务 `ChannelSyncService.pull_multica`，把 Multica 议题归一为 `proposed` 治理行：`source_channel="multica"`、`source_external_id` 用 Multica `identifier`、`source_url` 用 issue 链接，调用既有 `create_governance_topic` / `create_governance_task`；重复由既有 partial unique `(project_id, source_channel, source_external_id)` 拒绝（409 `duplicate_source`）。入向不提供写 canonical/rejected 的路径。
- 游标、去重与失败重试由 `ChannelSyncService` 与 `channel_sync_cursors` 行持有：服务在租约内读取游标、分页拉取、按外部标识去重、成功后推进游标并记录 `last_error`，构成可重放的确定性用例，不依赖 Agent 的临时判断。
- 驱动方式：注册为 worker 周期任务（与 `run_worker.py` 的 `_reconcile_agent_run_leases_forever` 同一周期收敛循环，启动时也执行一次），并提供显式同步入口由人触发。不新增公网 webhook，不引入新调度服务。

#### 出向（元垒 → Multica）

- `MulticaExecutor` 实现 `DelegatedExecutor`。`dispatch`：先写 `channel_delegations` 的 `pending` 意图并提交，再创建 Multica issue，描述内嵌稳定标记 `Yuanlei-Delegation-Operation: <operation_id>`，成功后记录 `external_ref=identifier`、`external_url`，置 `dispatch_state='dispatched'`。
- 远端创建成功但响应丢失：重试时先 `issue search <operation_id>` 核对标记。命中则采纳已有 issue（写回 `external_ref`），不再创建；未命中才创建。租约保证同一委派同一时刻只有一个投递写者。
- `status` / `collect` 轮询读取远端 issue 与结果，写入 `remote_status` 投影与 `result_*`；结果落 Workdir 由第 4 节的 Workdir Owner 执行。
- 任务描述写一次，之后只读；不修改 Multica 侧状态，也不把 Multica 侧状态回写元垒 canonical。

#### 凭据与降级

- 新增渠道级加密凭据（base_url + token 密文），复用 coding/git 凭据的 AES-GCM + AAD + fail-closed 范式与独立 master key，明文不进 DB/API/日志/事件。
- 无 Multica 凭据时 `MulticaExecutor` 不注册，工具返回结构化 `channel_unavailable`；治理、Channel、Run、coding 路径不依赖 Multica 存在，元垒独立可用。
- Multica 的实际 HTTP 认证头与分页细节未在本仓库固化，实现时对照真实实例核实并收敛在适配器内，端点以配置表达；核实前不把传输细节散落到编排层。

### 6. 传输与失败语义

- 传输：MVP 入向与出向都用轮询，复用既有 worker 收敛循环与显式入口，不引入新调度服务；webhook 作为后续可选项，需要时另开 decision。
- 幂等：入向按 `(project_id, source_channel, source_external_id)` 去重；出向按稳定 `operation_id`，以「持久化意图 + 描述标记 + search 核对」实现 search-before-create，同一操作不产生第二个远端工作项。
- 失败：投递意图保持 `pending` 可重试；远端不可达返回结构化错误并保持委派非终态或显式 `failed`；远端已创建但响应丢失由核对采纳；未知外部事件记录 warning，不静默丢弃。

## 替代方案

- 让 Multica 镜像成为议题/任务事实源，或允许其反向写 canonical：拒绝。会产生第二状态 Owner，破坏元垒规范化事实源。
- 为每个外部执行伪造 `agent_runs` 行：拒绝。上游 Run 生命周期与 lease 由 worker 拥有，外部执行没有对应执行体会产生无 Owner 的非终态 Run。
- 只做一个大而全的执行器接口，把 Multica 塞进沙盒 CLI 适配层：拒绝。两者基底、产物位置与凭据类型不同，会形成泄漏抽象并让沙盒边界屈从远端语义。
- 在统一接口引入 `cancel` / `resume` / `streaming`：拒绝。当前没有共同消费者，沙盒的取消与多轮续接已由 `coding_*` 覆盖，Multica 无对应能力。
- 出向用 `(project_id, executor_key, initiator_run_id, task)` 做幂等键：拒绝。同一 Run 的两次合法同文任务会被合并，且无法处理「远端创建成功但响应丢失」。
- 新增独立委派调度服务/队列：拒绝。既有 worker 收敛循环 + 委派事实已足够，独立服务会复制 Owner 与恢复逻辑。
- 入向直接暴露公网 webhook：MVP 拒绝。新增未认证写入面且难以 fail-closed；拉取式同步先满足验收。
- 在 `governance_tasks` 上直接落执行状态：拒绝。与治理域「任务不含执行状态」的已确认决定冲突。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 同一接口可委派 codex/opencode 与 Multica，结果回读为统一委派视图 | 两套入口或结果结构分叉 | `DelegationService` + `DelegatedExecutor` | 真实 HTTP/worker 集成：分别委派三执行器并回读统一 view | 未注册执行器显式 `executor_unavailable`，不静默换基底 | Not run |
| 沙盒委派句柄绑定具体 `session_id` / `turn_id`，`collect` 只回收该轮 | 回收相邻轮次或平行会话表 | `SandboxCodingExecutor` + `CodingExecutionService` | coding E2E 复用 + 委派入口集成测试 | 委派句柄指向的 turn 与回收结果不一致时结构性失败 | Not run |
| `coding_*` 工具在新增委派入口后不回归 | 收窄原多轮/取消能力 | `coding_*` 工具 + coding session 仓储 | 既有 coding 测试回归 | 委派入口不得移除或替换原工具 | Not run |
| Multica 导入入口只产生 `proposed`，无 canonical 写路径 | 镜像直写 canonical 或重复落库 | `governance_service.py` + 导入适配器 | 真实 PostgreSQL：经导入入口创建后回读状态为 `proposed`；重复导入 409 | 在导入入口调用治理用例无法写出 canonical/rejected；导入服务不暴露审核/状态写入参数 | Not run |
| 同一 `operation_id` 重复投递不产生第二个远端工作项（含创建响应丢失核对） | 重复创建或永久卡在未知态 | `DelegationService` + `channel_delegations` + `MulticaExecutor` | 集成测试用假 Multica：首次创建后模拟响应丢失，重试经标记核对采纳同一 `external_ref` | 无标记 / 标记不匹配时不得静默采纳；租约外不得投递 | Not run |
| 本地 `dispatch_state` 与远端 `remote_status` 投影分离 | 远端状态改写本地状态或成为第二事实源 | `DelegationService` + `channel_delegations` | 集成测试：只改远端结果，断言 `dispatch_state` 与治理 canonical 不变 | 远端状态变化不得写 `dispatch_state` 或 canonical | Not run |
| 委派结果只引用发起 Run，产物物化在 Workdir 边界内 | 伪造新 Run 或越界写文件 | `DelegationService` + `Workdir`（`workspace/workdir.py`） | 集成测试注入 `..`/绝对路径与跨 Project 结果，回读 `initiator_run_id` | 越界路径与跨 Run 结果被 `_require_within` 拒绝；不新增 `agent_runs` | Not run |
| 入向游标、去重与重试由确定性同步服务持有 | 依赖 Agent 自行决定同步或重复导入 | `ChannelSyncService` + `channel_sync_cursors` | 真实 PostgreSQL/worker：崩溃后重跑从游标继续，不重复导入 | 游标陈旧或租约被占时不得推进，失败记录 `last_error` | Not run |
| 缺失 Multica 凭据时适配器禁用且元垒其余能力独立可用 | 整链不可用或缺配置伪装成功 | 渠道凭据服务 + 适配器注册表 | 删除凭据后重跑治理/Channel/coding 集成，断言 `channel_unavailable` | 无凭据时不得注册 multica 或发出外部请求 | Not run |
| 非终态委派有 owner/lease，崩溃后可观察收敛 | 委派永久 running 或静默接管 | `DelegationService` + `channel_delegations` | 真实 PostgreSQL/worker：kill 回收后重跑收敛 | 过期 owner 不得写终态 | Not run |
| yuanlei 迁移幂等且不触碰上游域 | 重复执行报错或越域 | `storage_migration.py` + `manager.py` | 迁移集成测试连跑两次 | 重放建表不重复；business/knowledge 版本不变 | Not run |

## 风险

- **Multica HTTP 契约未完全固化**：CLI 与服务端路径已核实，但认证头、分页与元数据读写的确切线上形状需对照真实实例。缓解：把传输与解析收敛在适配器内并补契约测试，端点以配置表达，实现前核实；无幂等键依赖 `operation_id` 标记核对。
- **search-before-create 核对窗口**：`issue search` 可能命中同名字段。缓解：标记包含唯一 `operation_id`，只采纳精确匹配；租约保证单写者。
- **基底差异导致抽象泄漏**：沙盒 CLI 与远端渠道的能力、产物、取消语义不同。缓解：能力在 `capabilities()` 显式声明，差异由工具层呈现，不承诺统一多轮与实时事件。
- **外部执行副作用不可回滚**：远端已执行的任务无法撤销。缓解：委派描述写一次、结果与副作用在终端事件中显式提示核对。
- **凭据与越权**：渠道 token 属敏感值。缓解：独立 master key、AES-GCM + AAD、fail-closed、响应/日志/事件脱敏与 canary 负向测试；远端结果写入 Workdir 前按现有路径边界校验。
- **重复回收与并发**：轮询可能重复处理同一外部结果。缓解：委派级 lease 与幂等回收，终态只由当前 owner 写。
- **范围蔓延**：本次只做「委派 + 回收 + Multica 桥接」最小闭环，不做通用工作流编排、不做多外部渠道矩阵、不做 webhook。
