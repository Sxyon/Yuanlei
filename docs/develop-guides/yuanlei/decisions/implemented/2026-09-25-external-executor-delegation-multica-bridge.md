# Decision：外部执行器委派抽象与 Multica 桥接

状态：implemented
类型：architecture
Owner：backend/package/yuxi/services/delegation_service.py
日期：2026-09-25
关联 Feature：[外部执行器委派与 Multica 桥接](../../features/external-executor-delegation.md)

方向评审：2026-09-25 研发评审官结论「事实 Owner 划分基本正确」，并按评审意见收窄统一接口、重做 `channel_delegations` 状态分离与投递核对、明确入向游标 Owner。

事实 Owner 分工：统一委派编排归 `backend/package/yuxi/services/delegation_service.py` 与 `backend/package/yuxi/delegation/`；codex/opencode 的执行与会话事实仍归 `CodingExecutionService` 与 `coding_sessions`；入向治理归一归 `governance_service.py`；委派事实、同步游标与迁移归 `channel_delegation_repository.py`、`manager.py` 与 `storage_migration.py`；Workdir 物化归 `backend/package/yuxi/workspace/workdir.py`；工具门控归 `agents/toolkits/service.py` 与 `agent/buildin/subagent/graph.py`。

## 问题

元垒要有「执行与协同」面：把任务委派给外部执行者并回收结果。上游 Yuxi 拥有 Run、Conversation、队列、执行与事件链路；元垒已具备两段可复用能力（治理域的来源归一化、沙盒内的 codex/opencode 会话），但缺少把它们收敛成一条通道的统一抽象。

入向事实只覆盖一部分：治理四表已把来源渠道、外部标识与链接归一为 `proposed → 审核 → canonical` 生命周期，`GOVERNANCE_SOURCE_CHANNELS` 已包含 `multica`，但没有同步游标与拉取入口。执行事实也已存在但绑定在一种基底上：`CodingExecutorAdapter` 只拥有「如何调用某个 CLI、如何解析输出」，语义、凭据、沙盒与路径边界都限定在项目专属沙盒内，无法直接委派到项目沙盒之外的外部程序。Multica 目前只是治理域里的一个来源渠道取值，没有出向桥接、没有结果回收路径。

由此产生四类失败：委派给外部执行者的任务没有统一入口；外部执行结果无法作为可追溯事实回收；Multica 镜像有机会被当作第二事实源反向写 canonical；缺少 Multica 配置时整条协同能力不可用。

## 决策

### 边界与所有权

- 元垒拥有规范化议题/任务的唯一事实源，Multica 是渠道与起草人。Multica 来源只产生 `proposed` 治理行，经人审核才成为 canonical；没有反向写 canonical 的路径。
- 外部执行只产生「委派事实」与「回收结果」，不改变来源议题/任务的审核状态，也不复制外部执行状态为 canonical。
- 不为外部执行伪造上游 `agent_runs` 行。委派以独立事实 + 统一读模型满足「结果回读为 Run/Artifact」：结果绑定发起 Run，产物作为 Artifact 物化。

### 统一可委派执行者接口

`backend/package/yuxi/delegation/contracts.py` 定义窄接口 `DelegatedExecutor`（Protocol）：`key`、`capabilities()`、`dispatch(request)`、`status(handle)`、`collect(handle)`。值对象为 `DelegationRequest` / `DelegationHandle` / `DelegationResult`。句柄绑定稳定 `operation_id` 与具体 `session_id` / `turn_id`，`external_ref` 指向远端工作项。

MVP 只覆盖委派、查询、回收，不定义 `cancel` / `resume` / `streaming`：沙盒的取消与多轮续接由既有 `coding_*` 承担，Multica 无对应能力。`capabilities()` 只声明有消费者的 `multi_turn` 与 `remote_artifacts`；能力缺失时结构化失败，不静默降级。

### 与既有 coding_* 的关系

- 沿用，不替换、不收窄。`CodingExecutorAdapter` 仍是沙盒内 CLI 的协议适配；`CodingSessionService` 与 `coding_sessions` 仍是 codex/opencode 的会话与执行事实 Owner。
- `SandboxCodingExecutor`（key 为 `opencode` / `codex`）实现 `DelegatedExecutor`：`dispatch` 等价于 `create_session` 后 `queue_turn`，句柄携带该 `session_id` 与该轮 `turn_id`；`status` / `collect` 只读这一轮，不读相邻 turn。不新增平行会话表。
- Multica 没有沙盒内续接入口，`multi_turn` 为 false，句柄只有 `operation_id` 与 `external_ref`。

### 持久化与回收路径

- codex/opencode 复用 `coding_sessions`；`DelegationService` 从会话仓储装配统一视图，不落平行会话表。
- 新增 yuanlei 表 `channel_delegations`（迁移升 `YUANLEI_SCHEMA_VERSION` 到 11）：`operation_id` 唯一、`project_id`、`initiator_run_id`（只引用发起 Run）、`executor_key`、`task` 与 `request_json`（投递意图快照）、`session_id` / `turn_id` / `external_ref` / `external_url`、本地 `dispatch_state`（`pending` / `dispatched` / `collecting` / `reclaimed` / `failed`）、`attempts`、远端只读 `remote_status` 与 `remote_status_synced_at`、`result_summary` / `result_json` / `artifact_path`、`owner_token` / `lease_expires_at`、`error_code` / `last_error_at`。
- 先持久化投递意图：`dispatch` 先在独立事务写入 `pending` 行并提交，再调用执行器；进程崩溃后 `pending` / 超租约行由确定性 worker 收敛。
- 本地状态与远端投影分离：`dispatch_state` 只由 `DelegationService` 写；`remote_status` 是远端执行的只读投影，不改写本地状态，也不复制为 canonical。
- 结果只绑定 `initiator_run_id`，不产生新的 `agent_runs`。
- Workdir 物化：远端文本结果写入 Project Workdir 下 `.yuanlei/delegations/<operation_id>/result.md`，经 `Workdir.create_directory` / `replace_file` 与 `_require_within` 校验边界；`artifact_service.py` 不新增物化写用例，外部文件只存 URL 引用。
- 新增 `channel_sync_cursors`，按（`channel`, `project_id`）记录同步进度、`owner_token` 与租约；迁移仅进 `yuanlei` 域，幂等升级链挂接，不触碰上游 `business` / `knowledge` 域。

### Multica 桥接

- 契约（2026-09-25 核实 `multica` CLI 与平台 reference；2026-09-26 对真实实例探测）：创建 `POST /api/issues` 没有调用方幂等键、没有按外部引用 upsert；查询有 `issue get` / `list` / `search`；状态枚举 `backlog` / `todo` / `in_progress` / `in_review` / `blocked` / `done` / `cancelled`。issues 端点强制 workspace 作用域，缺失即 400 `{"error":"workspace_id or workspace_slug is required"}`，`project_id` 不能替代；GET 的列出/查询/详情入口以查询参数附带 `workspace_id`，真实实例复验通过（选 `id` 而非 `slug`：稳定且与既有 `project_id` 同为 id，避免引入可变键；两键不并存）。`POST /api/issues` 的作用域位置不成立：真实实例上请求体带 `workspace_id` 仍返回同一 400，出向创建因此保持 fail-closed（结构化 `multica_request_failed`，不创建任何工作项），未改用 `workspace_slug` 或把作用域移到查询参数，待决策。列表端点实测接受 `sort=updated_at&direction=desc`（`sort` 不在 CLI 文档枚举内，依据真实实例探测采用），并实测静默忽略 `updated_after`、默认按可变 `position` 排序（`updated_at` 非单调），故增量不能依赖服务端 `updated_after` 与默认次序。幂等只能由元垒侧 `operation_id` + 标记核对实现。
- 出向：`MulticaExecutor.dispatch` 先在描述内嵌稳定标记 `Yuanlei-Delegation-Operation: <operation_id>`，重投时先按标记 `search` 精确核对，命中则采纳已有工作项（写回 `external_ref`），未命中才创建，保证同一操作不产生第二个远端工作项。`status` / `collect` 轮询读取远端并将状态写入 `remote_status` 投影，不修改远端状态、不回写 canonical。
- 入向：`ChannelSyncService.pull_multica` 在游标租约内按 `sort=updated_at&direction=desc` 分页拉取 Multica 议题，归一为 `proposed` 治理行（`source_channel="multica"`、外部标识、原文链接），重复由既有 partial unique 拒绝（409 跳过），成功后推进游标。游标是稳定组合键 `(updated_at, id)`：两个字段归一为固定 UTC 微秒格式后 JSON 编码，`updated_at` 先于 `id` 比较；历史裸 `updated_at` 值按 `(updated_at, "")` 兼容读取，解析失败即 fail-closed（保持原值、记 error、不发请求）。增量由客户端按组合键过滤：`updated_at < 游标` 即停止翻页；`updated_at == 游标` 的边界秒内项全部纳入并靠 `source_external_id` 去重——服务端并列次序不可依赖，若按 id 严格过滤会漏掉同一 `updated_at` 下更小的 id。只有整个结果集取回后才推进游标；触顶 `MULTICA_SYNC_MAX_PAGES` 或中途异常时保持原游标并显式告警，不静默跳过未取回项。导入入口只调用治理创建用例，不暴露审核或状态写入参数，不开公网 webhook。
- 驱动：`reconcile_channel_sync` 与 `reconcile_delegations` 注册进 worker 周期收敛循环并启动时执行一次；另提供显式 HTTP 同步入口，不依赖 Agent 自行决定同步。
- 凭据：MVP 通过实例级全局环境配置（`YUANLEI_MULTICA_BASE_URL` / `YUANLEI_MULTICA_TOKEN` / `YUANLEI_MULTICA_WORKSPACE_ID` 必填，`YUANLEI_MULTICA_PROJECT_ID` 可选，端点、认证头与 workspace 作用域收敛在 `HttpMulticaClient`）装配；任一必填缺失时 `build_multica_client_from_env` 不装配、`MulticaExecutor` 不注册，向 `multica` 委派返回结构化 `executor_unavailable`，渠道同步与游标入口返回结构化 `channel_unavailable`，且不发任何外部请求，元垒其余能力独立可用。粒度升级到按 Project 的凭据（依据 `channel_delegations.project_id` 与 `channel_sync_cursors(channel, project_id)`，非按用户）与 DB 级加密渠道凭据表留待后续 decision，不在本 MVP 引入。

### 入口

- HTTP：`backend/server/routers/delegation_router.py`（委派创建/列表/查询/回收 + 显式 Multica 同步与游标读取）。
- Agent 工具：`delegation_tools.py` 的 `delegation_dispatch` / `delegation_status` / `delegation_collect` / `delegation_list`，只在根 AgentRun 的 Project 范围内可用，子智能体禁用。

### 传输与失败语义

MVP 入向与出向都用轮询，复用既有 worker 收敛循环与显式入口，不引入新调度服务。入向按（project, channel, external_id）去重；出向按稳定 `operation_id` 以「持久化意图 + 描述标记 + search 核对」实现 search-before-create。投递失败保持 `pending` 可重试并记录 `error_code`；远端已创建但响应丢失由核对采纳；未知外部事件记录 warning，不静默丢弃。

## 替代方案

- 让 Multica 镜像成为议题/任务事实源或反向写 canonical：拒绝，会产生第二状态 Owner。
- 为每个外部执行伪造 `agent_runs`：拒绝，会产生无 Owner 的非终态 Run。
- 只做一个大而全接口把 Multica 塞进沙盒 CLI 适配层：拒绝，基底、产物与凭据类型不同，会形成泄漏抽象。
- 在统一接口引入 `cancel` / `resume` / `streaming`：拒绝，当前没有共同消费者。
- 出向用 `(project_id, executor_key, initiator_run_id, task)` 做幂等键：拒绝，同 Run 两次合法同文任务会被合并且无法处理响应丢失。
- 入向直接暴露公网 webhook：MVP 拒绝，新增未认证写入面且难以 fail-closed；拉取式同步先满足验收。
- MVP 引入 DB 级加密渠道凭据表：拒绝，当前无第二个渠道消费者，先用环境配置并经 `build_multica_client_from_env` fail-closed。

## 后果

- Multica HTTP 契约的认证头、分页与元数据形状未对照真实实例固化，传输细节收敛在 `HttpMulticaClient`；核实前不把细节散落到编排层。契约测试覆盖适配器与假客户端，真实实例连通性未验证。
- search-before-create 存在核对窗口：`issue search` 可能命中同名字段，标记包含唯一 `operation_id` 且只采纳精确匹配；租约保证同委派单写者。
- 收敛重投 `pending` 时，沙盒场景在「会话已提交、本地行未更新」的窄窗口内可能重复建会话；Multica 场景由标记核对避免重复工作项。
- 外部执行副作用不可回滚；委派描述写一次，结果与副作用在终端事件中显式提示核对。
- 渠道 token 仍属敏感值：只经环境注入，明文不进 DB/API/日志/事件；响应与日志不落未脱敏凭据。
- 入向积压边界：当某 Project 待取回项 ≥ `MULTICA_SYNC_MAX_PAGES * limit`（默认 10×50=500）且每页始终满页时，永远见不到短页 → `consumed` 恒为 false → 游标不推进，每轮重复处理同一批（有告警、不丢数据、不静默，但无法前进）。这是「触顶保原游标」取舍的已知后果：需提高页上限、调大 `limit` 或缩小 Project 积压才能前进，不能靠重放自愈。
- 游标边界秒：远端 `updated_at` 为秒级，同一秒内多个议题的并列次序由服务端可变 `position` 决定，元垒不能依赖。组合游标只按时间戳分界，边界秒内项目每轮重扫并由 `source_external_id` 去重；代价是每次同步对边界秒内已导入项产生一次 409 跳过，换来同一 `updated_at` 下更小 id 的新项不被漏掉。

## 验证

实际执行（容器内以本 worktree 代码 + 运行中 PostgreSQL）：

- `pytest test/integration/services/test_delegation_service.py` → 11 passed（统一接口委派与未注册执行器结构化失败、operation_id search-before-create 采纳响应丢失、本地状态与远端投影分离、Workdir 物化边界、崩溃收敛、入向只产生 proposed 与游标去重、待取回项超过 limit 时有界分页取回、整页重复仍推进游标、触顶分页上限保持原游标、同一 `updated_at` 下不同 id 的边界不丢项且不重复落库、畸形 `cursor_value` fail-closed 保原游标且不发请求）。
- `pytest test/integration/api/test_delegation_router.py` → 3 passed（未认证 401 由 `get_required_user` 拒绝、未知或不可见 Project 404、无 Multica 凭据 503 `channel_unavailable`）。
- `pytest test/unit/delegation` → 12 passed（含按 workspace 作用域装配的 fail-closed、四个 issues 出入口附带 `workspace_id` 且列表固定 `updated_at` 倒序、子智能体委派工具 fail-closed）；`pytest test/unit/storage test/unit/services/test_storage_migration.py` → 通过（含 v10→v11 幂等与升级顺序）。
- `pytest test/unit/services/test_run_worker.py` → 通过（`_worker_startup` 断言 `reconcile_delegations()` 与 `reconcile_channel_sync()` 各执行一次；移除调用时该用例失败）。
- `pytest test/integration/services/test_schema_migration_version.py` → 除两个与本变更无关的既有失败（`test_business_v2_converges_project_git_schema`、`test_project_git_schema_enforces_alias_and_user_boundaries`，在未改动的基线 checkout 上同样失败）外通过，含新增的 v10→v11 真实 PostgreSQL 收敛用例。
- `ruff check` / `ruff format --check` 通过。
- 真实 Multica 实例探测：YL-17（2026-09-26）确认 workspace 必填、`updated_after` 被静默忽略、默认按 `position` 排序、`sort=updated_at&direction=desc` 被接受；以本 worktree 的 `HttpMulticaClient` 对真实实例复验：无 workspace 的 `GET /api/issues` 返回 400 `{"error":"workspace_id or workspace_slug is required"}`，带 workspace 的列表返回 200 且 `updated_at` 严格倒序，`get_issue` / `search_issues` 均成功。出向 `create_issue` 对真实实例发一次受控写：`POST /api/issues` 请求体含 `workspace_id` 仍返回 400 同一错误，未创建工作项，桥接以结构化 `multica_request_failed` fail-closed；未改用 `workspace_slug` 或查询参数，待决策。unit 仅断言其 json 载荷含 `workspace_id`，不足以证明服务端接受该形状。

证据矩阵（结果口径）：

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 同一接口可委派 codex/opencode 与 Multica，结果回读为统一委派视图 | 两套入口或结果结构分叉 | `DelegationService` + `DelegatedExecutor` | `test_delegation_service.py::test_dispatch_persists_intent_unified_view_and_executor_unavailable` | 未注册执行器显式 `executor_unavailable` | Passed |
| 沙盒委派句柄绑定具体 `session_id` / `turn_id`，`collect` 只回收该轮 | 回收相邻轮次或平行会话表 | `SandboxCodingExecutor` | `test_sandbox_executor.py`（status/collect 只读被委派 turn） | 未终结 turn 拒绝；缺失 turn 返回 None | Passed |
| `coding_*` 工具在新增委派入口后不回归 | 收窄原多轮/取消能力 | `coding_*` 工具 + coding session 仓储 | 既有 coding 工具与沙盒测试未改动并回归通过 | 委派入口不移除或替换原工具 | Passed |
| Multica 导入入口只产生 `proposed`，无 canonical 写路径 | 镜像直写 canonical 或重复落库 | `governance_service.py` + `ChannelSyncService` | `test_delegation_service.py::test_multica_inbound_sync_only_proposed_and_deduped_by_cursor` | 导入服务不暴露审核/状态写入参数 | Passed |
| 同一 `operation_id` 重复投递不产生第二个远端工作项（含响应丢失核对） | 重复创建或永久卡在未知态 | `DelegationService` + `MulticaExecutor` | `test_multica_search_before_create_adopts_lost_response`、`test_multica_executor.py` | 标记不匹配时不静默采纳 | Passed |
| 本地 `dispatch_state` 与远端 `remote_status` 投影分离 | 远端状态改写本地状态或成为第二事实源 | `DelegationService` + `channel_delegations` | `test_local_state_and_remote_projection_stay_separate` | 远端状态变化不写 `dispatch_state`，不新增 `agent_runs` | Passed |
| 委派结果只引用发起 Run，产物物化在 Workdir 边界内 | 伪造新 Run 或越界写文件 | `DelegationService` + `Workdir` | `test_collect_materializes_inside_workdir_boundary` | 越界路径被 `_require_within` 拒绝 | Passed |
| 入向游标、去重与重试由确定性同步服务持有，游标落在稳定组合键且不静默跳过未取回项 | 依赖 Agent 自行决定同步/重复导入/满页推进游标跳过/同一 `updated_at` 边界项被跳过/畸形游标被静默读作空 | `ChannelSyncService` + `channel_sync_cursors` | `test_multica_inbound_sync_pages_past_limit_without_cursor_skip`、`test_multica_inbound_sync_full_duplicate_page_advances_cursor`、`test_multica_inbound_sync_holds_cursor_when_page_cap_hit`、`test_multica_inbound_sync_same_updated_at_boundary_not_lost`、`test_multica_inbound_sync_fails_closed_on_malformed_cursor`；`reconcile_channel_sync` 注册进 worker | 待取回项超过 limit 时不被游标跳过；整页重复仍推进游标；触顶分页上限保原游标不静默跳过；同一 `updated_at` 下更小 id 的新项仍取回；畸形 `cursor_value` 时 fail-closed、保原游标、不发外部请求（移除解析守卫时该用例失败）；租约被占时拒绝 | Passed |
| issues 的 GET 出入口强制 workspace 作用域，列表固定 `updated_at` 倒序且不依赖被忽略的 `updated_after` | 缺失作用域 400 / 依赖可变排序导致增量不可靠 | `HttpMulticaClient` + `build_multica_client_from_env` | `test_multica_executor.py::test_http_client_scopes_every_issue_request_by_workspace` | 缺 workspace 键时不装配客户端、不发请求 | Passed |
| 出向 `create_issue` 的 workspace 作用域被真实服务端接受 | 作用域位置错误导致出向不可用或静默错建 | `HttpMulticaClient.create_issue` | 2026-09-26 真实实例受控写：`POST /api/issues` 请求体带 `workspace_id` → 400 `{"error":"workspace_id or workspace_slug is required"}`，未创建工作项 | 失败即结构化 `multica_request_failed`、不静默兼容；未改用 `workspace_slug` | Failed (fail-closed) |
| 缺失 Multica 凭据或 workspace 作用域时适配器禁用且元垒其余能力独立可用 | 整链不可用或缺配置伪装成功 | `build_multica_client_from_env` + 适配器注册表 + `delegation_router.py` | `test_multica_executor.py::test_build_multica_client_from_env_fails_closed_without_credentials`、`test_delegation_router.py::test_multica_channel_routes_fail_closed_without_credentials` | 无凭据或缺 workspace 时不注册、不发外部请求，渠道入口 503 `channel_unavailable` | Passed |
| 非终态委派有 owner/lease，崩溃后可观察收敛，且 worker 启动即收敛一次 | 委派永久 running 或停机期间委派/渠道失联不可恢复 | `DelegationService` + `reconcile_delegations` + `_worker_startup` | `test_converge_resets_interrupted_collecting_row`、`test_run_worker.py::test_worker_startup_ensures_builtin_mcp_servers_and_runs_convergence` | 超租约行复位且释放 owner；移除启动调用该用例失败 | Passed |
| 委派 HTTP 入口最终授权在 `get_required_user`，Project 可见性在 repository 查询执行 | 未认证放行或跨用户读取他人 Project 委派 | `delegation_router.py` + `ProjectRepository.get_active_selectable_for_user` | `test_delegation_router.py::test_delegation_routes_require_authentication`、`test_delegation_routes_reject_unknown_or_invisible_project` | 未认证 401；未知或不可见 Project 404 | Passed |
| 子智能体不能委派外部执行器（工具面隐藏 + 调用期 fail-closed） | 子智能体绕过 Project 授权发起委派 | `subagent/graph.py` + `delegation_tools.py` + `resolve_project_run_scope` | `test_delegation_tools_guard.py::test_subagent_delegation_operation_fails_closed_without_db_or_external` | 结构化拒绝且不访问 DB、不调用执行器 | Passed |
| yuanlei 迁移幂等且不触碰上游域 | 重复执行报错或越域 | `storage_migration.py` + `manager.py` | `test_yuanlei_v10_to_v11_converges_channel_delegation_tables_idempotently` | 重放建表不重复；business/knowledge 版本不变 | Passed |
| 真实 Multica 实例的 workspace 作用域、读取/认证头连通 | 契约未固化导致线上失败 | `HttpMulticaClient` | 对本 worktree 客户端真实实例只读复验：无 workspace 400，带 workspace 列表 200 且倒序，`get_issue` / `search_issues` 200 | 出向 `create_issue` 未创建真实工作项 | Passed（读取）/ Not run（写出） |
| 沙盒委派在真实专属沙盒内执行并回收 | 依赖外部沙盒环境 | `SandboxCodingExecutor` | 未在真实沙盒执行整轮 | — | Not run |
