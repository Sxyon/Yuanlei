# 项目自定义 Dashboard

状态：已实现（静态 Dashboard v0）
类型：新增能力
主要 Owner：[项目自定义 Dashboard v0 Decision](../decisions/implemented/2026-09-21-project-dashboard.md)

## 需求与失败场景

每个 Project 可以由带项目上下文的 Agent 创建和维护一个项目页面。第一版交付的是可进入、可安全渲染的静态 HTML/CSS Dashboard，不是智能体管理工作台，也不提供在页面中新增智能体、跳转对象或编辑项目资料的能力。

页面以 `dashboard/index.html` 保存到 Project Workdir，数据库只保存 revision、hash 与大小元数据。页面或命名 JSON 的并发更新不能静默覆盖；文件系统与数据库提交失配必须显式显示待修复状态。Agent 只能在所属用户、正在运行的根 Project Run 中调用专用读写工具，浏览器没有写接口。

先前拟议的 iframe bridge 与项目事实投影未进入第一版：不可信页面一旦能够执行脚本，就不能同时被视为隔离页面并获授私有项目数据。第一版因此不执行脚本、没有 bridge、没有 `/sources` 接口，也不会把 JSON 文档自动注入页面。

## 必须保留的业务语义

- 页面入口固定为 Project Workdir 的 `dashboard/index.html`；第一版仅允许静态 HTML/CSS，writer 拒绝 `<script`、`meta` 和非页内锚点的 `href`。
- 页面内容放在受控文档壳的 body 中，以无 token、无同源、无脚本权限的 iframe 渲染；固定 head CSP 禁止网络、表单、frame、object 与 base，内联 CSS 和 data URL 图片/字体可用。
- 页面与命名 JSON 各自有单调 revision。对同一旧 revision 的两个更新最多一个成功，失败方得到结构化冲突和当前 revision。
- 页面字节的事实 Owner 是 Workdir，页面 revision 的事实 Owner 是 yuanlei `project_dashboards`。二者 hash 不一致时读取为 `repair_required`，不返回可能过期的页面。可读但违反静态策略的旧页不被采纳，只允许持有当前 revision 的安全写入覆盖修复；不可信路径、坏编码和超限仍拒绝覆盖。
- 命名 JSON 的事实 Owner 是 yuanlei `project_documents`，以 `(project_id, key)` 唯一；它供受控 HTTP API 与未来能力使用，不向 iframe 暴露。
- Dashboard 的读接口和 Agent 工具只对当前用户 active、selectable 的 Project 开放；不可见项目返回 404。
- Redis 不拥有页面、JSON、版本或锁的最终事实。

## 与 Yuxi 的边界

Yuxi 继续拥有 Project、认证、Conversation、AgentRun 以及 Workdir 的 no-follow 文件边界。元垒在 yuanlei schema 新增 `project_documents`、`project_dashboards`，并新增 Dashboard 读写用例、原子 Workdir writer、Agent 工具和前端静态页面壳；不修改上游 business 或 knowledge schema。

## 稳定集成点

| 集成角色 | 当前 Owner | 元垒语义 |
|---|---|---|
| Project 可见性 | `ProjectRepository.get_active_selectable_for_user` | 当前用户 active、selectable Project，否则 404 |
| 页面资产 | `yuxi.workspace.Workdir`、`Workspace.replace_authorized_file` | no-follow 原子替换与回读校验 |
| 页面 revision | `project_dashboards` 与 Dashboard service | advisory lock、乐观 revision、hash 对账与 repair |
| 命名 JSON | `project_documents` 与 document service | key 唯一、行锁、单调 version 与 409 |
| Agent 编辑 | 根 Project Run 的 `dashboard_read`/`dashboard_write` | 从 Run→Conversation→Project 重建授权并核验当前 worker lease，只写静态页面 |
| 浏览器展示 | `ProjectDashboardView`、`dashboardFrame` | 无脚本 sandbox 与无网络 CSP，不提供 bridge |

## 上游依赖

依赖 Project 可见性、AgentRun/Conversation 项目关联、Workdir no-follow 原语、认证和前端项目对话路由。

## 合并判断

上游若提供项目页面 revision 与同等文件恢复语义，比较其并发冲突、恢复与授权边界后采用或缩小此差异；不得以脚本 bridge 取代静态隔离。

## 替换或删除条件

上游提供等价的项目页面 revision、Workdir 恢复与无脚本预览时可删除重复实现。项目工作台取代展示入口时，仍保留页面与 JSON 数据迁移路径，并以新的 Decision 定义工作台权限与设置语义。

下一版“项目工作台”若需要项目目标、智能体列表、详情跳转、创建智能体或 Dashboard 设置，必须新建 Decision：明确受信任 UI Owner、每个写操作的授权/审计/冲突契约，以及 JSON 如何被读取和编辑。不得重新向任意 Agent 生成 HTML 页面授予项目数据 bridge。

## 决策与证据

- [项目自定义 Dashboard v0](../decisions/implemented/2026-09-21-project-dashboard.md)
- 实现 Owner：`backend/package/yuxi/services/project_dashboard_service.py`
- 代码与测试是当前实现事实；Decision 的验证记录保留实际证据与已知环境限制。
