# Decision：外部执行器委派抽象与 Multica 桥接

状态：proposed
类型：architecture
Owner：backend/package/yuxi/services/coding_execution_service.py
日期：2026-09-25
关联 Feature：[外部执行器委派与 Multica 桥接](../../features/external-executor-delegation.md)

事实 Owner 分工：本文提案跨越多个 Owner，实现时不得让本文档反向充当运行时事实源。统一委派编排落到新增 `backend/package/yuxi/services/delegation_service.py` 与 `backend/package/yuxi/delegation/`；codex/opencode 的执行与会话事实仍归 `CodingExecutionService` 与 `coding_sessions`；入向治理归一归 `governance_service.py`；委派事实、渠道凭据与迁移归 `manager.py`、`storage_migration.py` 与渠道凭据服务；产物边界归 `artifact_service.py`；工具门控归 `agents/toolkits/service.py` 与 `tool_approval.py`。

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
capabilities() -> {cancel, resume, multi_turn, streaming, remote_artifacts}
dispatch(request) -> handle        # 创建外部/沙盒执行，写入委派事实
status(handle) -> state            # 返回投影状态，不拥有外部终态
collect(handle) -> result          # 归一化摘要、产物引用、用量、错误
cancel(handle) -> None             # 仅当 capabilities.cancel
```

- `DelegationRequest`：`project_id`、`task`、`context_refs`（来源议题/任务）、`budget`、`initiator_run_id`。
- `DelegationHandle`：`delegation_id`、`executor_key`、`external_ref`。
- `DelegationResult`：`summary`、`artifacts`（Workdir 相对路径与/或外部 URL）、`usage`、`error_code`。
- `DelegationService` 拥有适配器注册、按适配器解析凭据、委派事实的持久化、单活跃尝试与收集租约、产物物化与统一读模型。

能力差异必须在 `capabilities()` 声明并由工具层显式呈现；能力不存在时结构化失败，不静默降级。`DelegationService` 只做编排，不重实现任何执行基底。

### 3. 与既有 coding_* 的关系

- 沿用，不替换、不收窄。`CodingExecutorAdapter` 继续是沙盒内 CLI 的协议适配；`CodingSessionService` 与 `coding_sessions` 继续是 codex/opencode 的会话与执行事实 Owner。
- 新增 `SandboxCodingExecutor`（executor key 为 `opencode` / `codex`）作为 `DelegatedExecutor` 实现，内部复用 `CodingExecutionService` 与 coding session 仓储；`dispatch` 等价于启动会话，`status` / `collect` 读会话 turn 与事件。
- `coding_*` 工具保留，继续提供 start/send/await/status/cancel 的轮次控制；统一委派工具覆盖「一次委派 + 等待/收割 + 回收」。两者指向同一会话事实，是同一执行的两个入口。
- Multica 无法提供沙盒内 CLI 的多轮与实时事件，`capabilities.multi_turn` 为 false，以委派级 await/collect 代替。

### 4. 持久化与回收路径

- codex/opencode：不新增平行会话表，`coding_sessions` 保持唯一执行事实；`DelegationService` 从会话仓储装配统一视图。
- Multica 等外部渠道：新增 yuanlei 表 `channel_delegations`，字段包含 `id`、`project_id`、`initiator_run_id`、`executor_key`、`external_ref`、`external_url`、`status`（显式标注为投影）、`result_summary`、`result_json`、`artifact_path`、`owner_token` / `lease_expires_at`、`error_code`、时间戳。`status` 是外部状态的只读投影，外部系统是对应执行的事实 Owner。
- 统一回收：`DelegationService.collect` 返回同一 `DelegationResult`；远端文本结果按边界写入 Project Workdir 下 `.yuanlei/delegations/<id>/result.md`，经既有 `artifact_service` 的授权路径与大小限制暴露，外部文件只存 URL 引用。
- 非终态委派必须有显式 owner 与 lease，并可在崩溃后收敛；回收不得改写来源议题/任务审核状态，也不得从相邻 Run/会话猜测结果。
- 迁移仅进 `yuanlei` 域，幂等升级链挂接并升 `YUANLEI_SCHEMA_VERSION`，不触碰上游 `business` / `knowledge` 域。

### 5. Multica 桥接

- 入向（Multica → 元垒）：新增 Multica 适配器把外部议题/消息归一为 `proposed` 治理行（`source_channel="multica"` + 非空 `source_external_id` + 原文 `source_url`），幂等由既有的 `(project_id, source_channel, source_external_id)` 唯一约束保证；需要触发元垒 Agent 时走既有 Channel 消息入口。入向不提供写 canonical/rejected 的路径。MVP 采用拉取式同步（由用户自建定时任务或显式同步命令驱动），不新增公网 webhook 入口。
- 出向（元垒 → Multica）：`MulticaExecutor` 实现 `DelegatedExecutor`，`dispatch` 创建 Multica 侧工作项（一次性写入任务描述），`status` / `collect` 轮询读取结果；`cancel` 尽力而为并由 `capabilities.cancel` 声明。任务描述写一次，之后只读。
- 凭据与端点：新增渠道级加密凭据（base_url + token 密文），复用 coding/git 凭据的 AES-GCM + AAD + fail-closed 范式与独立 master key，明文不进 DB/API/日志/事件。凭据缺失时 Multica 适配器不注册，工具返回结构化 `channel_unavailable`。
- 无 Multica 时元垒独立可用：适配器注册表按可用凭据装配，治理、Channel、Run、coding 路径不依赖 Multica 存在。

### 6. 传输与失败语义

- 传输：MVP 入向与出向都用轮询，复用既有用户自建定时任务与 worker/ARQ 投递，不引入新调度服务；webhook 作为后续可选项，需要时另开 decision。
- 失败：委派创建失败保持可重试事实；外部不可达返回结构化错误并保持委派非终态或显式失败；未知外部事件不静默丢弃，记录 warning；取消不假定「外部已停止」，事件中提示核对副作用。
- 幂等：入向按外部标识去重；出向 `dispatch` 以 `(project_id, executor_key, initiator_run_id, task)` 的请求标识保证不重复创建外部工作项。

## 替代方案

- 让 Multica 镜像成为议题/任务事实源，或允许其反向写 canonical：拒绝。会产生第二状态 Owner，破坏元垒规范化事实源。
- 为每个外部执行伪造 `agent_runs` 行：拒绝。上游 Run 生命周期与 lease 由 worker 拥有，外部执行没有对应执行体会产生无 Owner 的非终态 Run。
- 只做一个大而全的执行器接口，把 Multica 塞进沙盒 CLI 适配层：拒绝。两者基底、产物位置与凭据类型不同，会形成泄漏抽象并让沙盒边界屈从远端语义。
- 新增独立委派调度服务/队列：拒绝。既有用户自建定时任务 + worker + 委派事实已足够，独立服务会复制 Owner 与恢复逻辑。
- 入向直接暴露公网 webhook：MVP 拒绝。新增未认证写入面且难以 fail-closed；拉取式同步先满足验收。
- 在 `governance_tasks` 上直接落执行状态：拒绝。与治理域「任务不含执行状态」的已确认决定冲突。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 同一接口可委派 codex/opencode 与 Multica，结果回读为统一委派视图 | 两套入口或结果结构分叉 | `DelegationService` + `DelegatedExecutor` | 真实 HTTP/worker 集成：分别委派三执行器并回读统一 view | 未注册执行器显式 `executor_unavailable`，不静默换基底 | Not run |
| codex/opencode 经委派入口仍写入同一 `coding_sessions` 事实，原 `coding_*` 工具不回归 | 平行会话表或收窄原能力 | `SandboxCodingExecutor` + `CodingExecutionService` | coding E2E 复用 + 委派入口集成测试 | 委派产生的会话有独立事实且可从原工具续轮 | Not run |
| Multica 入向只产生 `proposed`，重复外部标识被拒 | 镜像直写 canonical 或重复落库 | `governance_service.py` + 唯一索引 | 真实 PostgreSQL：导入后回读状态与来源；重复导入 409 | 直接写 canonical/rejected 被检查约束拒绝 | Not run |
| Multica 无反向写元垒 canonical 状态的路径 | 出现第二状态 Owner | 路由 + 用例 + 检查约束 | 源码 guard + 负向集成：外部状态变化后 canonical 不变 | 以外部状态调用审核入口被拒 | Not run |
| 缺失 Multica 凭据时适配器禁用且元垒其余能力独立可用 | 整链不可用或缺配置伪装成功 | 渠道凭据服务 + 适配器注册表 | 删除凭据后重跑治理/Channel/coding 集成，断言 `channel_unavailable` | 无凭据时不得注册 multica 或发出外部请求 | Not run |
| 委派结果绑定发起 Run 与 Project，产物物化在 Workdir 边界内 | 从相邻 Run 猜结果或越界写文件 | `DelegationService` + `artifact_service` | 集成测试注入 `..`/绝对路径与跨 Project 结果 | 越界路径与跨 Run 结果被拒 | Not run |
| 非终态委派有 owner/lease，崩溃后可观察收敛 | 委派永久 running 或静默接管 | `DelegationService` + `channel_delegations` | 真实 PostgreSQL/worker：kill 回收后重跑收敛 | 过期 owner 不得写终态 | Not run |
| yuanlei 迁移幂等且不触碰上游域 | 重复执行报错或越域 | `storage_migration.py` + `manager.py` | 迁移集成测试连跑两次 | 重放建表不重复；business/knowledge 版本不变 | Not run |

## 风险

- **Multica API 契约未在仓库内固化**：出向创建/读取工作项的端点、认证头与状态枚举需要对照 Multica 实际 API 验证；无法验证前不进入实现。缓解：先把传输与解析收敛在适配器内并补契约测试，端点以配置表达。
- **基底差异导致抽象泄漏**：沙盒 CLI 与远端渠道的能力、产物、取消语义不同。缓解：能力在 `capabilities()` 显式声明，差异由工具层呈现，不承诺统一多轮与实时事件。
- **外部执行副作用不可回滚**：远端已执行的任务无法撤销。缓解：委派描述写一次、取消只作尽力而为、结果与副作用在终端事件中显式提示核对。
- **凭据与越权**：渠道 token 属敏感值。缓解：独立 master key、AES-GCM + AAD、fail-closed、响应/日志/事件脱敏与 canary 负向测试；远端结果写入 Workdir 前按现有路径边界校验。
- **重复回收与并发**：轮询可能重复处理同一外部结果。缓解：委派级 lease 与幂等回收，终态只由当前 owner 写。
- **范围蔓延**：本次只做「委派 + 回收 + Multica 桥接」最小闭环，不做通用工作流编排、不做多外部渠道矩阵、不做 webhook。
