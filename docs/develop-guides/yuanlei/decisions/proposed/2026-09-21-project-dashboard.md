# 项目自定义 Dashboard（v0）

状态：proposed
类型：feature
Owner：docs/develop-guides/yuanlei/features/project-dashboard.md

## 问题

项目需要由 Agent 创建和维护逐项目不同的 Dashboard。当前 Project Workdir 能保存任意文件，但系统没有受控的项目页面契约、页面 revision、松散项目 JSON、项目级会话与沙盒只读投影，也没有承载不可信 HTML 的运行壳。全局 `/api/dashboard` 与 `/dashboard` 是 superadmin 聚合统计，与项目页面无关。

页面文件和 JSON 文档是两类并发事实：文件系统与 PostgreSQL 不能组成可回滚的同一事务，写入后提交失败必须可观察、可收敛；iframe 是不可信渲染面，必须固定无网络、无同源、无凭据的边界；平台数据只能经权限裁剪的只读投影进入页面。`docs/vibe/` 中的 v0 设计与执行计划被 Git 忽略，不能作为组织记忆；本记录与 [Feature 档案](../../features/project-dashboard.md) 是进入实现前的 tracked 契约。

## 提案

### 1. 项目范围与授权

Dashboard 读、写与 bridge source 只对 `Project.status == "active"` 且 `Project.selection_status == "selectable"` 的当前用户 Project 开放，与项目数字员工、Git 仓库等管理 API 的范围一致。隐式 Project、已删除 Project、其他用户 Project 统一 404，不返回 403 或存在性差异。实现复用 `ProjectRepository.get_for_user` 并显式检查两个状态，或在 repository 增加等价的单项目读方法；不复用其他 service 的私有校验函数。

### 2. 页面资产与单文件入口

页面入口固定为 Project Workdir 内 `dashboard/index.html`，不可由请求传入宿主路径。目录选择可见的 `dashboard/` 而非隐藏目录，因为页面是项目交付物、可以进入项目 Git 版本管理；平台不修改 `.gitignore`。v0 只渲染入口 HTML，CSS 与脚本内联，不引入多文件资源路由、模板系统、静态托管或 CDN。

大小与编码：页面 HTML 的 UTF-8 字节 ≤ 1 MiB，严格 UTF-8 解码；入口路径任一段为符号链接、非普通文件或目录时 fail-closed。读取与写入都通过 `Workdir`、`Workspace` 的 no-follow fd 边界，路径拒绝 `..`、反斜杠和 URL 片段。

原子提交的现有事实：`Workspace.replace_authorized_file` 已经实现 no-follow 的临时文件、`fsync`、`os.rename` 原子替换，并在目标不存在时直接创建；`Workdir.write_file` 是原地截断写入，不具备原子性；原子替换尚未暴露为 `Workdir` 的公开方法。实现必须在真实 Owner 上扩展（`Workdir` 增加复用该原语的原子提交入口），不为形式隔离新建第二套文件层，也不允许 Dashboard writer 使用 `write_file`。

### 3. 页面 revision 的事实 Owner

新增 Yuanlei 表 `project_dashboards`，每个 Project 至多一行，字段：`project_id`（主键，FK 指向上游 `projects.id`，随项目删除级联）、`revision`（bigint，从 1 开始）、`content_sha256`（64 位十六进制）、`content_size`（int）、`updated_by`（用户 uid）、`updated_at`。

PostgreSQL 拥有 revision 比较与冲突结果；Workdir 文件拥有页面字节。读取时按实际文件重算 hash，与元数据比较后返回三种状态：

- `empty`：元数据不存在且文件不存在。
- `ready`：元数据存在且磁盘 hash、大小一致，返回 `revision`、`sha256`、`size`、`updated_at` 与 `html`。
- `repair_required`：文件存在但元数据缺失或 hash 不一致，或元数据存在但文件缺失。该状态返回元数据 revision 与观测到的磁盘 hash，不返回可与 revision 对应的 `html`。

页面读接口为 `GET /api/projects/{project_id}/dashboard`；不存在或不可见项目返回 404，不创建元数据行。

### 4. 文件与数据库跨边界恢复

Dashboard writer 在单个数据库事务内按以下顺序提交，事务级 advisory lock 按 `project_id` 取得：

1. 收敛：在锁内对账元数据与磁盘 hash。发现 `repair_required` 时先把磁盘当前内容采纳为 `revision + 1`（无元数据时为 1）并更新 `content_sha256`、`content_size`、`updated_at`，使元数据追上文件事实。
2. 比较：请求必须携带 `expected_revision`（首次创建为 0）。收敛后的 revision 与 `expected_revision` 不同时返回 409 与当前 revision，不写文件；若本次已收敛，收敛结果在返回 409 前提交，使修复对后续读取可见。
3. 准备目录：入口父目录不存在时，在同一 Project Workdir 的 no-follow 边界内创建 `dashboard/`；已有对象必须是普通目录，符号链接或同名普通文件失败关闭。
4. 替换：通过 Workdir 级原子提交入口替换入口文件，成功后回读字节、重算 hash 与大小。
5. 推进：更新 `project_dashboards` 为 `revision + 1` 及新 hash、大小、操作者，随后提交事务。

失败语义：

- 步骤 3 或 4 失败：旧页面保持完整，元数据与磁盘仍一致；返回结构化失败。
- 步骤 5 提交失败：新页面字节完整保留在磁盘，元数据停留在旧 revision；客户端收到失败响应。下一次读取返回 `repair_required`，下一次写入在锁内收敛后把磁盘内容采纳为新 revision；持有旧 revision 的编辑者因此得到 409，不会覆盖磁盘内容。
- 修复操作是同一锁下的幂等收敛：重复执行不产生额外 revision。修复由下一次写入自动触发，也允许显式调用；读接口的 `repair_required` 是可观察入口。

该协议确定“文件事实优先、元数据收敛”。写入前记录意图行、写前备份并回滚文件等方案在替代方案中拒绝。

### 5. 松散 JSON 文档与写入协议

新增 Yuanlei 表 `project_documents`：`id`（UUID 主键）、`project_id`（FK 指向 `projects.id`，级联删除）、`key`、`content`（JSONB）、`version`（int，从 1 开始）、`created_by`、`updated_by`、`created_at`、`updated_at`，唯一约束 `(project_id, key)`。

key 只允许小写字母、数字、点、短横线和下划线，首字符为字母或数字，长度 ≤ 120；序列化后 JSON ≤ 256 KiB；`dashboard.` 前缀由平台保留（v0 只定义 `dashboard.config`），其余命名空间留给项目。

写入协议：

| 写入类型 | 客户端前置条件 | 服务端保证 | 冲突结果 |
|---|---|---|---|
| 创建文档 | `expected_version = 0` | 对 `(project_id, key)` 取得事务 advisory lock，仅当不存在时插入 version 1 | 409 与当前 version |
| 替换文档 | `expected_version = n` | 同一事务内 `SELECT ... FOR UPDATE` 行锁，仅当 version 为 n 时更新为 n+1 | 409 与当前 version |
| Agent 读改写 | 先读到 n，再用 n 提交 | 行锁保护单次读改写，乐观 version 防止跨请求旧写入 | 必须重读并显式合并 |

乐观 version 是跨请求的正确性边界；行锁与 advisory lock 只让同一服务调用的创建和读改写串行化，不是长期编辑占用。接口为 `GET/PUT /api/projects/{project_id}/documents/{key}`；v0 不允许 iframe 写入，也不允许用户表单直写。

### 6. iframe、CSP 与 bridge 信任边界

页面壳只通过认证 JSON API 取得 HTML，再用 `srcdoc` 注入 iframe，不把 token、cookie、宿主路径或内部字段写入页面。iframe 属性固定为 `sandbox="allow-scripts"`：不允许 `allow-same-origin`、弹窗、表单提交、下载或顶层导航。

CSP 以 `<meta http-equiv="Content-Security-Policy">` 注入 srcdoc 文档头，v0 固定为 `default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; media-src 'none'; object-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'`。页面不能主动访问网络；外部图片或资源需要单独的代理与许可策略，不在 v0。

bridge 协议名 `yuxi.project-dashboard.bridge`，版本 1，消息形态：iframe 请求 `{bridge, version, kind: "request", id, source, params}`；父窗口响应 `{bridge, version, kind: "response", id, ok, data | error}`。父窗口只处理 `event.source === iframe.contentWindow` 的消息（sandbox 无同源时 origin 为 opaque，source 身份是唯一可靠校验），并校验协议、版本、request id 唯一性、source 白名单和 params schema。限制：请求 ≤ 8 KiB、响应 ≤ 512 KiB、单请求超时 10 秒、会话分页 ≤ 50、offset ≤ 10000，未知字段与超限请求结构化失败。

v0 bridge 只读取数据，不承诺对象详情跳转。Dashboard 已能呈现项目智能体、会话与沙盒摘要；把 iframe 发出的标识映射为项目内详情路由，需要再定义目标可见性验证和目标页面契约，单独延后。

### 7. 首批只读 source

| source | 参数 | 返回字段 | 事实 Owner |
|---|---|---|---|
| `project.summary` | 无 | `id`、`name`、`status` | `ProjectRepository.get_for_user` |
| `project.agents` | 无 | `slug`、`name`、`description`、`updated_at` | 项目智能体绑定与 Agent，新裁剪投影 |
| `project.conversations` | `agent_slug?`、`limit`、`offset` | `thread_id`、`title`、`status`、`agent_slug`、`created_at`、`updated_at` | Conversation 的 `project_id`、`uid`、`agent_id`，新增按项目查询 |
| `project.sandboxes` | `agent_slug?` | `agent_slug`、`lifecycle`、`status`、`resume_policy`、`last_activity_at`、`suspended_at`、`updated_at`、`error_code` | `AgentSandbox` 唯一约束，新增按项目查询 |
| `project.agent_overview` | `agent_slug`（必填）、`limit`、`offset` | `{agent, sandbox, conversations}`，三者都必须同 project、同 uid、同 agent_slug | 上述三个 Owner 的读投影 |
| `project.data` | `key`（必填） | `key`、`content`、`version`、`updated_at` | `project_documents` |

投影规则：`project.agents` 不得复用管理视图的原始序列化，只返回表中声明的字段；不返回数值 id、`backend_id`、图像 URL、`config_json`、`config_overrides`、`effective_context`、`configurable_items` 及其 options、`share_config`、`created_by`、`updated_by`。`project.sandboxes` 必须去掉 `sandbox_id`、`scope_key`、`credential_fingerprint`、`lease_owner_kind`、`lease_owner_id`、`generation`、`error_message`；任何 source 不返回 Workdir 路径、uid 列表、token 或异常堆栈。会话只返回 `status == "active"`，按 `updated_at` 倒序。

bridge 不接受 `project_id` 参数：项目由页面壳路由固定，父窗口只按该固定项目调用后端投影；iframe 的 `agent_slug` 等参数在投影内部仍与 `project_id`、`uid` 联合过滤，跨项目或不匹配的对象返回空集而不是相邻对象。

### 8. Agent 编辑能力与入口

Dashboard writer 是平台提供的专用工具（服务能力），不是通用文件写工具。它提供读取当前页面、revision、hash 和可用 source 数据契约的读取动作，以及必须携带 `expected_revision` 的提交动作；提交内部执行第 4 节的锁定、比较、原子替换和回读。它是 v0 唯一承诺并发安全的 Dashboard 写入路径；通用文件工具或用户在 Workdir 中的直接修改视为外部变更，读取会以 hash 对账暴露 `repair_required`，不会被错误标记为正常 revision。

v0 不新建“dashboard 编辑模式”或草稿 query。`dashboard_read`、`dashboard_write` 是需显式加入 Agent 已选工具配置的内建工具；writer 只在已有 `project_id`、正在执行的根 Agent Run 中可用。工具从 Run、Conversation、Project 的当前数据库关联重建 uid 与 Project 授权，不信任运行时的单独字段，并在描述中限定为用户明确请求创建或修改 Dashboard 时使用。Dashboard 页面的“生成/编辑”入口只打开现有 Project 对话，让用户给出具体目标。这条路径复用现有项目上下文，不把未实现的页面意图、自动提示词或长时编辑状态塞进路由。

冲突处理：`409` 返回当前 revision；Agent 重新读取页面与 JSON、显式合并用户请求后再提交，不自动重试旧内容。页面壳不提供自动刷新、模板或草稿参数。

编辑入口沿用现有前端契约：`router.push({ name: "AgentComp", query: { project_id } })`，需要指定项目数字员工时可带 `agent_id`（slug）。现有 `AgentView` 只消费 `agent_id` 与 `project_id` 两个 query，`project_id` 仅是新建线程时的 create-only 上下文，没有 `draft`、`prompt` 等草稿 query，也不存在项目详情路由；v0 不为 Dashboard 新增草稿或自动发送参数，入口不伪造未实现的上下文注入。入口路径、当前 revision 与数据契约由 writer 工具的读取动作提供给 Agent，用户目标由其在项目对话中的指令表达。

### 9. Schema 迁移与命名

两个新表进入 `backend/package/yuxi/storage/postgres/manager.py` 的 yuanlei 域定义，`YUANLEI_SCHEMA_VERSION` 从 8 升到 9，并在 `backend/package/yuxi/storage_migration.py` 挂接从当前版本起的幂等升级链；yuanlei 收敛继续排在 business schema 之后。上游 business、knowledge 域版本不推进。验收要求新库、从 8 升级的库都能获得表，且重复执行升级无副作用，使用真实 PostgreSQL 迁移测试。

命名避免与现有全局统计模块冲突：路由挂在 `/api/projects/{project_id}/dashboard`、`/api/projects/{project_id}/documents` 下；新增模块使用 `project_dashboard_service`、`project_document_repository` 等前缀，不复用或改名现有 `dashboard_router`、`dashboard_service`、`dashboard_repository`。

### 10. Redis 与延后项

v0 不引入 Redis 缓存、Redis 锁或 WebSocket 刷新，Dashboard 正确性测试不依赖 Redis。Redis 的启用前提是实测读取压力证明需要缓存；即使启用，PostgreSQL 的文档 version、页面 revision 与冲突结果仍是唯一事实。长时编辑 lease、多文件资源、模板与版本回滚、跨项目比较与共享成员同样延后；需要时建立新的 Decision。

### 阶段 0 事实核查结论（只读，已完成）

| 核查 | 已定位 Owner | 核实结论 |
|---|---|---|
| Project 可见性 | `ProjectRepository.get_for_user`、`lock_active_selectable_for_user`、`Project.status`/`selection_status` | `get_for_user` 只按 id 与 uid 过滤、不过滤状态；status 为 `active/deleted` 字符串枚举，selection_status 为 `implicit/selectable`；项目数字员工与 Git 管理 API 一致要求 active + selectable，不可见统一 404；无成员表、无管理员跨用户读取。Dashboard 采用同一范围，语义不变 |
| Project Workdir | `yuxi.workspace.Workdir`、`Workspace`、`Workspace.replace_authorized_file` | no-follow 通过 fd 相对打开实现（`O_NOFOLLOW`、`follow_symlinks=False`），符号链接映射为 `PermissionError`；`replace_authorized_file` 已实现临时文件 + `fsync` + rename 的原子替换，目标不存在时可直接创建；`Workdir.write_file` 非原子且未暴露原子替换。设计假设“可原子替换”成立，但需要 Workdir 级入口，属于本提案新增的最小改动 |
| 项目数字员工 | `project_agent_service.list_project_agents_view` | 该视图是管理范围，返回 `config_json`、`config_overrides`、`effective_context`、资源 options、`share_config`、uids 等内部字段。设计假设“可裁剪出稳定字段”成立，但不能原样复用，需要独立公开投影 |
| 会话关系 | `Conversation` 模型、`ConversationRepository` | `agent_id` 实际保存 Agent slug 且无外键；`project_id` 单列已有索引，但没有组合索引，也没有按 `project_id` 过滤的 repository 方法。分页、状态过滤和项目过滤需要在新增查询中组合 |
| 专属沙盒 | `AgentSandbox` 模型、`AgentSandboxRepository` | 唯一约束 `(uid, agent_slug, project_id)` 保证每项目每 Agent 一行；状态实际写入 `active`、`suspended`（`reaping`、`error` 只有注释与读取分支）；现有读视图包含 `sandbox_id`、`scope_key`、`credential_fingerprint`、lease 字段，必须裁剪；没有按项目或 Agent 的列表方法 |
| 前端导航与项目对话 | `AgentView`、`web/src/router/index.js`、`agent_api`、`AppLayout.vue` | 只有 `agent_id`、`project_id` 两个 query 被消费，`project_id` 是新建线程的 create-only 上下文；`draft`、`prompt`、`agent_slug` 等 query 不存在；没有项目详情路由。编辑入口必须使用现有契约，不能假设草稿 query |
| iframe 预览 | `AgentFilePreview`、`MarkdownPreview` | 现有不可信 HTML 预览使用 `sandbox="allow-scripts"`，无 `allow-same-origin`；只有 iframe 到父窗口的高度上报，且只校验 `event.source === iframe.contentWindow`；主应用没有 CSP 中间件、没有 X-Frame-Options；没有父窗口到 iframe 的 bridge，也没有 srcdoc 资源改写或后端 HTML 直出接口。Dashboard 需要新增双向 bridge，CSP 只能注入 srcdoc 文档头 |

与设计假设不一致的点已在本节和下表中显式收敛：原子替换需要 Workdir 级入口；两类读视图需要重新裁剪；项目级会话与沙盒查询需要新增；入口不能携带草稿或目标 prompt；CSP 需自建注入点。

## 替代方案

- 继续使用 `Workdir.write_file` 的 last-write-wins：拒绝。无 revision、非原子，无法满足并发冲突和失败恢复。
- 页面 HTML 只存 PostgreSQL：拒绝。页面是项目交付物，应可见于 Workdir 并可进入项目 Git；大文本进入业务表也会扩大数据库负担。v0 保持文件为字节事实、数据库为 revision 索引。
- 只靠文件 hash 或 mtime 作为 revision：拒绝。无法给出稳定的 `expected_revision` 链，也无法区分“新版本”和“外部改写”。
- 用带响应头 CSP 的 HTTP 页面端点替代 srcdoc：拒绝。前端认证使用请求头而不是 cookie，iframe 导航无法携带 token；把 token 放进 URL 违反“不向 iframe 暴露凭据”。srcdoc 加 meta CSP 是当前认证模型下可验证的边界。
- 用 DOMPurify 清洗 Dashboard HTML：拒绝。Dashboard 的脚本与样式是产品输出，清洗会破坏功能；隔离由 sandbox、CSP、无凭据和无网络保证。
- 写入前记录意图行或写前备份并回滚文件：拒绝。会引入额外状态机或不可靠的文件回滚；“磁盘 hash 必须等于元数据 hash，修复以磁盘为准”已经给出确定、可观察的收敛规则。
- Redis 缓存或分布式锁：延后。没有读取压力证据，且不改变 PostgreSQL 的事实 Owner。
- 长时编辑 lease：延后。v0 的并发正确性由乐观 revision 保证；需要“某人正在编辑”或跨分钟独占时再新增带 owner、到期和恢复语义的显式 lease。
- 预置模板、多文件静态站点、CDN 或可视化编排器：延后。没有已验证的真实使用需求，且会扩大信任边界。
- 继续把 `docs/vibe/` 草稿当作实施依据：拒绝。草稿被 Git 忽略，不是组织记忆。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 不同 Project 展示各自页面，跨项目访问返回 404 | 串项目内容或通过参数放宽范围 | ProjectRepository + Dashboard service | `test/integration/api/test_project_dashboard_api.py::test_project_dashboard_pages_are_project_scoped`、`::test_project_dashboard_read_reports_empty_ready_and_repair` | 以 A 项目路由读 B 页面返回 404 | Passed |
| 旧 revision 不能覆盖新页面 | 两个编辑者互相覆盖 | Dashboard writer + `project_dashboards` | `test_project_dashboard_service.py::test_write_page_creates_revision_and_requires_expected_revision`、`::test_concurrent_writes_on_same_revision_keep_single_winner` | 失败响应后回读磁盘仍是成功者版本，元数据 revision 与磁盘一致 | Passed |
| 文件写后数据库提交失败的恢复 | 元数据与磁盘永久不一致或旧 revision 冒充最新 | Dashboard writer + 读接口 | `test_project_dashboard_service.py::test_write_commit_failure_keeps_repair_state_and_next_write_converges` | 读取返回 `repair_required`；下一次写入收敛为新 revision 且不损坏页面 | Passed |
| JSON 同版本并发写入不静默丢写 | 后写覆盖先写 | `project_documents` repository | `test/integration/services/test_project_document_service.py::test_document_versions_conflict_with_current_version`、`test/integration/api/test_project_document_api.py::test_project_document_versions_and_scope` | 一个成功一个 409，409 携带当前 version | Passed |
| 并发创建同一 key 只产生一行 | 两条 version 1 | `project_documents` repository | `test/integration/services/test_project_document_service.py::test_concurrent_create_keeps_single_version_one_row` | 唯一约束与 advisory lock 生效，只有一行 version 1 | Passed |
| 跨用户与不可见项目统一 404 | 存在性泄漏或越权读取 | Dashboard service | 已证文档读写（`test_project_document_service.py`、`test_project_document_api.py`）、页面 HTTP 跨用户 404（`test_project_dashboard_api.py`）与隐式 Project 的工具拒绝（`test_project_dashboard_tool.py`）；bridge source 在阶段 C 补齐 | 其他用户、隐式项目、已删除项目均返回 404 或结构化拒绝，且不创建数据 | Passed |
| 路径逃逸、符号链接、非 UTF-8、超限内容 fail-closed | 逃出 Workdir 或写出非法页面 | `Workdir`、Dashboard writer | 已证：key 校验 unit 与 HTTP 422、页面读的符号链接与非 UTF-8/超限（`test_page_read_back_rejects_unusable_page_bytes`）、writer 对符号链接及非 UTF-8/超限既有入口的拒绝（`test_write_rejects_symlinked_entry_without_touching_target`、`test_write_rejects_unusable_entry_without_overwriting_it`）；`..`、反斜杠由既有 `Workdir` 边界测试拥有 | 非法 key、符号链接、非 UTF-8、超限分别被拒绝；写入失败不损坏页面 | Passed |
| bridge 伪造消息、未知 source、超限请求被拒绝 | 第三方脚本或相邻 frame 借用 bridge | 前端 Dashboard frame | 前端 unit + 浏览器 E2E：伪造 `event.source`、未知 source、超大 params | 不发起后端查询，返回结构化错误 | Not run |
| CSP 阻止页面网络外联 | 页面外带数据或加载外部资源 | 前端 Dashboard frame 与注入的 CSP | 浏览器 E2E：页面发起 fetch、img 外链、WebSocket | 请求未发出，控制台出现 CSP 违规 | Not run |
| 首批数据按 project、uid、agent_slug 正确关联 | 跨项目或跨 Agent 串数据 | Dashboard read service | 新增 HTTP integration：`project.agents`、`project.conversations`、`project.sandboxes`、`project.agent_overview` 回读 | 传入其他项目的 agent_slug 返回空集，不返回相邻对象 | Not run |
| 页面投影不泄漏内部字段 | 凭据、路径、资源引用或 uid 进入 iframe | Dashboard read service | 新增 integration：对投影做字段白名单断言 | 出现 `config_json`、`effective_context`、`sandbox_id`、`credential_fingerprint`、`workdir_path` 即失败 | Not run |
| Agent 生成或编辑页面并回报 revision | Agent 绕过 writer 或写入不推进 revision | Dashboard writer 工具 | 已证工具路径：`test_project_dashboard_tool.py`（Run→Project 解析、writer 复用、隐式项目拒绝）与工具 unit 的子智能体拒绝；真实项目对话生成页面的 E2E 在阶段 D | 过期 revision 提交返回 409，页面字节保持新版本 | Not run |
| Dashboard 写能力只在带 Project 的 Agent Run 中生效，且无公开浏览器写接口 | 任意调用方写页面或绕过 revision | Dashboard writer 工具 + 路由范围 | `test/integration/services/test_project_dashboard_tool.py`、`test/unit/toolkits/test_dashboard_tools.py`；`/api/projects/{project_id}/dashboard` 只注册 GET | 非 project run、子智能体、隐式或不可见 Project 均被拒绝，HTTP 无写路由 | Passed |
| 外部直接改写页面被识别为待修复 | 通用工具改文件后元数据静默过期 | 读接口 hash 对账 | `test_project_dashboard_service.py::test_page_read_back_reports_empty_ready_and_repair_states` | 返回 `repair_required`，不返回与旧 revision 对应的内容 | Passed |
| 新库与从版本 8 升级的库都获得表且升级幂等 | 升级链缺失或重复执行失败 | `manager.py` + `storage_migration.py` | `test_project_dashboard_service.py::test_yuanlei_v8_to_v9_converges_dashboard_tables_idempotently`、`test/unit/services/test_storage_migration.py` 的升级链用例、真实库已记录 `yuanlei=9` | 重复升级无副作用，唯一与检查约束生效，已有数据不丢失 | Passed |

阶段 A 与阶段 B 已实现并取得上述证据：`project_documents`、`project_dashboards` 两类 yuanlei 事实与迁移链 8→9；文档 repository、advisory lock/行锁协议与 HTTP 读写接口；Workdir 原子替换入口与 `dashboard/` 目录安全创建；Dashboard writer 的收敛、`expected_revision` 比较、原子替换、回读与提交失败后的 repair 收敛；页面 GET 路由；带 Project 运行中可用的 Dashboard 读写 Agent 工具（子智能体禁用，重新授权，无浏览器写接口）。前端 Dashboard 页面、iframe bridge、项目数据投影与真实 Agent 对话 E2E 仍属阶段 C、D；证据不足的条目保持 `Not run`，不因代码存在或 HTTP 200 改为通过。

## 风险

- iframe 隔离依赖浏览器 sandbox 与 srcdoc 头部 meta CSP 的实际行为，主应用没有全局 CSP；必须用真实浏览器的负向外联测试证明，不能以代码存在或静态检查代替。
- 页面 HTML 经认证 JSON 接口进入父窗口再注入 iframe，大小上限 1 MiB 与响应上限 512 KiB 限制内存与传输压力，但大页面的编辑体验需要真实页面验证。
- 跨边界恢复采用“文件事实优先”，提交失败但已落盘的编辑会被后续修复采纳；相关编辑者必须依据 409 重新读取并合并，UI 需要展示 `repair_required` 而不是静默重试。
- 单文件入口限制页面组织方式；真实需求出现多文件资源时必须先建立受控资源路由与新的信任边界，再扩展。
- `project_dashboards` 与 `project_documents` 位于 yuanlei schema，依赖 business schema 先收敛；升级链必须幂等，并在现有部署上验证不丢失数据。
- 会话与沙盒按项目查询没有组合索引，v0 数据量下可接受；出现读取压力时先补索引或再评估 Redis，不改变事实 Owner。
- 只有 Project owner 可见、可编辑，没有成员共享模型；多用户协作需要新的 Decision 和权限设计。
- 事实核查为只读源码结论，尚未运行真实迁移与浏览器；实现必须按验收矩阵补齐真实 PostgreSQL、真实 HTTP 与浏览器证据后才能移入 implemented。
