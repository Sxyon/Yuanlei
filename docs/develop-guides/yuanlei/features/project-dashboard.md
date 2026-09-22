# 项目自定义 Dashboard

状态：提案中（阶段 A、B 已实现；只读 bridge、前端页面与 E2E 待收敛）
类型：新增能力
主要 Owner：`docs/develop-guides/yuanlei/decisions/proposed/2026-09-21-project-dashboard.md`（实现 Owner 见该提案；页面资产当前由 `backend/package/yuxi/workspace/workdir.py` 拥有）

## 需求与失败场景

每个 Project 需要由 Agent 生成和维护自己的 Dashboard 页面，把项目已有的智能体、会话、专属沙盒等事实组合成可展示界面。平台提供受控运行壳、只读数据桥和版本化的松散 JSON，项目拥有页面内容与组织方式；平台不预置项目中枢，也不替项目建蓝图、目标、任务、报告等实体。

阶段 A、B 已提供 `project_documents` 的 HTTP 读写、`GET /api/projects/{project_id}/dashboard`、页面 revision/hash 对账、受控原子 writer 与 `dashboard_read`/`dashboard_write` Agent 工具。工具须显式加入 Agent 的已选工具配置；即使被选中，也只允许正在执行、属于当前用户的根 Project Run 使用，且没有浏览器写接口。

它仍不是用户可打开的完整 Dashboard：没有前端路由与 iframe 运行壳、只读 bridge 或首批项目数据投影，也尚未通过真实 Agent 对话 E2E 验证。后续工作不得把迁移、表、service 或工具集成测试当作这些用户能力已经交付的证据。

失败场景：页面文件按 last-write-wins 写入会让并发编辑静默覆盖；文件系统与 PostgreSQL 不能组成可回滚的同一事务，提交失败后旧 revision 可能被当成最新内容；iframe 里的页面若带同源身份或凭据，就能读取其他项目数据或主动访问网络；缺少首批项目数据投影会让项目页长期只显示静态内容。

## 必须保留的业务语义

- 页面入口固定为 Project Workdir 内 `dashboard/index.html`，v0 单文件、内联样式与脚本；Dashboard writer 是唯一承诺并发安全的写入路径，通用文件工具的 last-write-wins 属于可观察的外部变更，不承担并发正确性。
- 页面文件与 JSON 文档各自拥有可观察的单调 revision。基于同一旧 revision 的两个更新至多一个成功，失败方收到最新 revision 和结构化冲突。
- 页面 revision 的元数据 Owner 是 Yuanlei `project_dashboards` 表，页面字节的事实 Owner 是 Workdir 文件。两者不一致时读接口显式暴露待修复状态，不把旧 revision 伪装成最新内容。
- 松散项目 JSON 以 `(project_id, key)` 唯一。创建用事务 advisory lock 防重复，替换用行锁加乐观 `expected_version`；锁只在单次服务调用内有效，不是长期编辑租约。
- Dashboard API 与 bridge source 只读取当前用户 active、selectable 的 Project，并始终在后端按 `project_id`、`uid` 和必要时的 `agent_slug` 过滤；不可见项目统一 404。
- iframe 是无网络、无同源、无凭据的只读运行面。页面只能通过版本化 bridge 请求白名单 source，不能写平台数据；v0 不提供对象详情跳转。
- 首批只读数据覆盖项目摘要、项目数字员工、项目内活动会话、按项目与 Agent 关联的专属沙盒及其受限组合，不新增 Agent、会话或沙盒业务实体。
- Redis 不拥有页面、JSON、版本或锁的最终事实；PostgreSQL 的版本与冲突结果是唯一事实。

## 与 Yuxi 的边界

Yuxi 继续拥有 Project、Conversation、Agent、AgentSandbox 生命周期、Workdir 的 no-follow 文件边界、认证和 AgentRun。元垒新增两个 yuanlei schema 域持久化事实（`project_documents`、`project_dashboards`）、Dashboard 读写用例、项目级会话与沙盒只读投影、bridge 契约和前端 Dashboard 页面壳。上游 business、knowledge schema 不修改。

## 稳定集成点

| 集成角色 | 当前 Owner | Yuanlei 语义 |
|---|---|---|
| Project 可见性 | `ProjectRepository.get_for_user`、`lock_active_selectable_for_user` | 只接受当前用户 active 且 selectable 的 Project；隐式与已删除 Project 不可见 |
| 页面资产 | `yuxi.workspace.Workdir`、`Workspace.replace_authorized_file` | Workdir 内 no-follow 读取与原子替换；Dashboard writer 增加 Workdir 级原子提交入口 |
| 页面 revision | 新增 `project_dashboards` 表与 Dashboard service | 乐观 revision 比较、advisory lock 串行化、hash 不一致时的待修复状态 |
| 松散 JSON | 新增 `project_documents` 表与 repository | `(project_id, key)` 唯一、行锁、单调 version 与结构化 409 |
| 平台事实读投影 | 新增 Dashboard read service | 按 project、uid、agent_slug 过滤，裁剪内部字段，分页与响应上限 |
| iframe 与 bridge | 前端 Dashboard frame | source 身份校验、协议版本、超时与响应上限 |
| Agent 编辑能力 | 显式选中工具的、带 `project_id` 的根 Agent Run | 读取当前 revision 与数据契约；只响应明确的 Dashboard 请求，提交必须携带 `expected_revision` |

## 上游依赖

该能力依赖 Project identity 与选择语义、Conversation 的 `project_id`、`uid`、`agent_id` 事实、Agent 可见性与 slug、AgentSandbox 生命周期与唯一约束、Workdir no-follow 原语、认证依赖和前端 Agent 对话路由。上游改变 Project 可见性、会话模型、沙盒状态机、Workdir 边界或对话创建契约时，必须重新核对 Dashboard 的范围过滤、数据投影和编辑入口。

## 合并判断

- 上游提供项目级页面资产和版本化编辑：比较 revision Owner、并发冲突、跨边界恢复和 iframe 信任边界后再决定采用或缩小差异。
- 上游提供通用 project document 存储：比较 key 约束、锁协议和冲突结果，保留元垒数据迁移路径。
- 上游改进 Workdir 原子写原语：复用新原语并删除元垒重复实现。
- 上游改变项目可见性或引入成员模型：重新评价 Dashboard 的 owner-only 边界和 404 语义。

## 替换或删除条件

上游同时提供项目级页面 revision、跨文件与数据库恢复、权限裁剪的只读 bridge、项目文档版本和同等 iframe 隔离后，可以删除元垒实现，并按 Decision 迁移已有 `project_dashboards`、`project_documents` 数据。业务不再需要项目自定义页面时，需要新 Decision 明确页面与文档数据处置后再删除。

## 决策与证据

- [项目自定义 Dashboard v0](../decisions/proposed/2026-09-21-project-dashboard.md)
- 阶段 0 事实核查结论已写入该提案，可直接核对的 Owner 包括 `backend/package/yuxi/workspace/workdir.py`、`backend/package/yuxi/workspace/filesystem.py`、`backend/package/yuxi/repositories/project_repository.py`、`backend/package/yuxi/storage/postgres/manager.py`、`backend/package/yuxi/storage_migration.py`；相关既有回归在 `backend/test/unit/workspace/test_workdir.py`、`backend/test/unit/workspace/test_filesystem.py`。
- 实现后的证据在同一记录的验收矩阵收敛；阶段 A、B 的已验证项目标为 `Passed`，bridge、数据投影和真实 Agent 对话 E2E 保持 `Not run`。
