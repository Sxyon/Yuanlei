# 外部执行器委派与 Multica 桥接

状态：已实现（MVP：委派/查询/回收 + Multica 拉取式入向与标记核对出向）
类型：新增业务能力
主要 Owner：backend/package/yuxi/services/delegation_service.py

## 需求与失败场景

元垒要把「把任务委派给外部执行者并回收结果」收敛成统一抽象，并把 Multica 接成其中一种渠道。codex/opencode 编码协作与 Multica 套同一「可委派执行者」接口；Multica 可作为来源渠道与执行渠道，双向交互但不成为元垒事实源；无 Multica 时元垒议题/任务仍独立工作。

失败场景：委派入口分叉，codex/opencode 与外部渠道各写一套执行事实；外部执行结果无法作为可追溯的 Yuanlei 事实回收，只能靠人复述；Multica 镜像被当作第二状态 Owner 反向写元垒 canonical 状态；缺少 Multica 配置时整条协同能力不可用并牵连元垒议题/任务；远端文本结果越界写入 Project Workdir 之外的路径。

## 必须保留的业务语义

- 元垒拥有规范化议题/任务的唯一事实源；Multica 只产生 `proposed` 治理行，经人审核才成为 canonical，且无反向写 canonical 的路径。
- 外部执行只产生委派事实与回收结果，不改变来源议题/任务的审核状态，不复制外部执行终态为 canonical。
- 不为外部执行伪造上游 `agent_runs` 行；委派结果只绑定发起 Run，产物作为 Artifact 物化。
- 每个委派操作有稳定 `operation_id` 与唯一 `channel_delegations` 行；投递意图先持久化再调用远端，同一操作不产生第二个远端工作项（远端已创建但响应丢失时经标记核对采纳）。
- 本地投递/回收状态（`dispatch_state`）与远端执行状态投影（`remote_status`）分离：本地状态只由 `DelegationService` 写，远端状态是只读投影，不反向写元垒状态。
- 统一委派接口与既有 `coding_*` 是同一执行事实的两个入口：`coding_sessions` 仍是 codex/opencode 的会话与执行事实 Owner，不新增平行会话表；句柄绑定具体 `session_id` / `turn_id`，只回收被委派的那一轮，续轮走 `coding_*`。
- 能力差异由 `capabilities()` 显式声明，MVP 只声明有消费者的 `multi_turn` 与 `remote_artifacts`；不可用即结构化失败，不静默降级或替换基底。
- 非终态委派必须有显式 owner 与 lease，崩溃后可观察收敛；结果不得从相邻 Run 或会话猜测。
- 入向游标、去重与失败重试由确定性同步服务与 `channel_sync_cursors` 行持有，不依赖 Agent 自行决定同步。请求固定 `sort=updated_at&direction=desc`（服务端忽略 `updated_after`，不作为增量依据），游标是稳定组合键 `(updated_at, id)`：两个字段归一为固定 UTC 微秒格式后 JSON 编码，历史裸 `updated_at` 值按 `(updated_at, "")` 兼容读取，解析失败即 fail-closed。客户端按组合键过滤，`updated_at < 游标` 即停止翻页；同一 `updated_at` 的边界秒内项全部纳入并靠 `source_external_id` 去重（服务端并列次序不可依赖，按 id 严格过滤会漏掉同一 `updated_at` 下更小的 id）。分页按远端 `offset`/`limit` 有界进行，只有整个结果集取回后才推进游标；触顶 `MULTICA_SYNC_MAX_PAGES` 或中途异常时保持原游标并显式告警/报错，绝不把游标推进到未确认取回的页（不静默跳过）。该取舍的已知后果：待取回项 ≥ `MULTICA_SYNC_MAX_PAGES * limit`（默认 500）且每页始终满页时，游标不推进、每轮重复处理同一批（返回并持久化错误；静态列表不会跳过未取回项，但无法前进），需调大页上限/`limit` 或缩小项目积压才能前进；边界秒内项每轮重扫并产生一次 409 跳过。
- 渠道凭据 fail-closed、明文不进 DB/API/日志/事件；Multica MVP 用实例级全局环境变量（`YUANLEI_MULTICA_BASE_URL` / `YUANLEI_MULTICA_TOKEN` / `YUANLEI_MULTICA_WORKSPACE_ID` 必填，`YUANLEI_MULTICA_PROJECT_ID` 可选），升级到按 Project 的凭据（依据 `channel_delegations.project_id` 与 `channel_sync_cursors(channel, project_id)`，非按用户）属后续决策；远端结果写入 Workdir 由 `Workdir` 安全写入 Owner 执行，路径按现有边界校验。
- 入向同步完成时核对游标的当前 owner 与租约；失去租约的旧执行者不能覆盖新游标。Multica 列表未提供快照游标，远端在 `offset` 翻页期间删除或重排工作项仍有遗漏风险；关键历史导入需另行核对来源总量与外部标识。
- 无 Multica 凭据时 Multica 适配器不注册，治理、Channel、Run 与 coding 路径独立可用。
- 单项目的人用 HTTP 本地入口从已审核且已指派项目数字员工的任务发起。服务端重验项目数字员工的当前可见与管理权限，并按用户、项目、Agent 绑定与 Workdir 派生专属沙盒范围，通用 HTTP 委派入口不接受无范围的 codex/opencode 请求。委派请求快照保留来源任务 ID，读视图可关联同一任务的多次尝试。既有 Agent Run 内工具仍可按其运行授权范围执行独立编码委派。
- 本地编码会话/turn 与委派句柄同事务提交后再发布队列；编码 pending turn 的既有恢复流程处理提交后投递失败。首次沙盒创建前刷新用户 Skill 投影，避免缺目录导致 provisioner 拒绝。

## 与 Yuxi 的边界

上游 Yuxi 拥有 Run、Conversation、队列、执行、事件链路与用户自建定时任务；元垒不在这些域新增语义。元垒新增的是委派编排用例、统一执行器接口与适配器、Multica 拉取式入向归一与出向桥接、渠道加密凭据、只读委派读模型与 Agent 工具面，以及 yuanlei 域的 `channel_delegations`、`channel_sync_cursors` 表与幂等迁移。上游文件只做最小 diff，执行基底能力（沙盒会话、Channel 入口、治理事实、Workdir 安全写入）复用既有实现。

## 稳定集成点

| 集成角色 | 当前 Owner | Yuanlei 语义 |
|---|---|---|
| 统一委派接口与编排 | `backend/package/yuxi/services/delegation_service.py`、`backend/package/yuxi/delegation/` | 适配器注册、委派事实、收集租约、统一读模型 |
| 沙盒 CLI 适配 | `CodingExecutionService`、`coding_sessions` 仓储 | `SandboxCodingExecutor` 复用会话事实，句柄绑定 `session_id` / `turn_id`，不新增平行表 |
| Multica 适配与凭据 | 新增 Multica 适配器；MVP 凭据为实例级全局 env（`YUANLEI_MULTICA_BASE_URL` / `YUANLEI_MULTICA_TOKEN` / `YUANLEI_MULTICA_WORKSPACE_ID` / 可选 `YUANLEI_MULTICA_PROJECT_ID`） | 入向拉取归一；出向按 `operation_id` 创建/轮询/回收，投递意图先持久化；无凭据或缺 workspace 作用域时适配器不注册 |
| 入向归一与审核 | `backend/package/yuxi/services/governance_service.py` + 治理四表 | 只产生 `proposed`，导入入口无 canonical 写路径，复用外部标识唯一约束 |
| 入向同步游标 | 新增 `ChannelSyncService` + `channel_sync_cursors`（yuanlei 域） | 游标、去重与失败重试的确定性 Owner，worker 周期驱动 |
| 委派事实 | 新增 `channel_delegations`（yuanlei 域） | 稳定 `operation_id`、投递/回收本地状态与远端只读投影分离 |
| 结果产物 | `backend/package/yuxi/workspace/workdir.py` | Workdir 边界内物化，经 `_require_within` 校验 |
| 工具门控 | `backend/package/yuxi/agents/buildin/subagent/graph.py`（`_SUBAGENT_DISABLED_TOOLS`）、`backend/package/yuxi/agents/toolkits/buildin/delegation_tools.py`（`is_subagent_runtime` 检查）、`backend/package/yuxi/agents/toolkits/buildin/project_run_scope.py`（`resolve_project_run_scope`） | 子智能体工具面隐藏并在调用期结构化拒绝；根 AgentRun 按 Project 授权范围校验 |

## 上游依赖

依赖 Run 与 `RunOrigin` 的 `source`/`channel`/`external_id` 语义、Channel 消息入口、治理四表与审核边界、`coding_sessions` 会话事实、Sandbox provider 与执行租约、`Workdir` 路径边界、渠道凭据加密范式、工具审批与 Skills 依赖门控、worker 周期收敛循环。上游修改这些 Owner 时必须重验委派绑定、投递意图持久化、只读投影、路径边界与「不反向写 canonical」语义。

## 合并判断

- 上游提供通用外部执行/委派抽象：比较事实 Owner、恢复与回收语义后，优先采用可证明等价的上游部分并缩小本差异。
- 上游提供 Multica 或同类渠道桥接：比较 proposed 生命周期、反向写边界与凭据边界，等价时替换本实现。
- 上游改变 Run/Channel/治理/Workdir 任一 Owner：迁移适配层，不放宽「外部不成为事实源」「不伪造 agent_runs」「投递意图先持久化」「Workdir 边界」四条不变量。

## 替换或删除条件

当上游拥有等价的外部执行器委派接口与渠道桥接，并能表达 proposed→审核→canonical、外部不反向写、投递意图持久化与核对、结果绑定发起 Run 与 Workdir 边界产物时，可删除本实现。删除前需要新的 Decision 说明 `channel_delegations`、`channel_sync_cursors` 既有数据的迁移与消费侧替换路径。

## 决策与证据

- Decision：[外部执行器委派抽象与 Multica 桥接](../decisions/implemented/2026-09-25-external-executor-delegation-multica-bridge.md)。
- 既有可复用事实：[Agent 专属沙盒与编码 CLI 协作](agent-coding-sandbox.md)、[项目治理域数据模型](project-governance.md)。
- Multica 创建/查询/幂等契约依据 `multica` CLI 帮助与 `multica-platform` skill reference 核实，workspace 必填、`updated_after` 被忽略与列表排序行为由 2026-09-26 真实实例只读探测确认；同日两次受控写实测确认 `POST /api/issues` 的 workspace 作用域在查询参数（请求体带 `workspace_id` 返回 400，查询参数带返回 2xx 并真实建单），`create_issue` 据此把作用域经查询参数附带、请求体只放内容字段。结论写在 Decision 的 Multica 桥接一节。
- 代码 Owner：`backend/package/yuxi/delegation/`（接口与适配器）、`backend/package/yuxi/services/delegation_service.py`、`backend/package/yuxi/services/channel_sync_service.py`、`backend/package/yuxi/repositories/channel_delegation_repository.py`、`backend/server/routers/delegation_router.py`、`backend/package/yuxi/agents/toolkits/buildin/delegation_tools.py`。
- 单项目本地闭环与真实 Codex/Workdir 证据见 [决策记录](../decisions/implemented/2026-09-26-single-project-local-loop.md)。
- 验收证据以关联 Decision 的六列矩阵为准；真实 Multica 实例的只读读取已复验，出向 `create_issue` 的 workspace 作用域经查询参数被真实服务端接受（受控写建单后回收），以 unit 断言 create 请求体不含 `workspace_id` 守住该形状；修正后客户端对真实实例的真实写未复测。单项目专属沙盒的真实 Codex 完成、结果回收和 Workdir 产物回读见 [单项目本地闭环决策](../decisions/implemented/2026-09-26-single-project-local-loop.md)。
