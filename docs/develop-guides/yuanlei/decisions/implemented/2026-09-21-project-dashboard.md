# Decision：项目自定义 Dashboard v0

状态：implemented
类型：feature
Owner：backend/package/yuxi/services/project_dashboard_service.py
日期：2026-09-21
关联 Feature：[项目自定义 Dashboard](../../features/project-dashboard.md)

## 问题

Project 需要可由 Agent 维护、用户可从项目导航进入的页面，页面产物也应留在 Project Workdir。原始设想让任意 Agent 生成的 HTML 在 iframe 内执行脚本，再通过父窗口 bridge 读取项目智能体、会话、沙盒和命名 JSON。

该设想不能构成可证明的隔离边界：iframe 的 `WindowProxy` 会跨导航复用，脚本一旦获得项目数据即可导航或外传。消息端口只能缩小某个回复竞争窗口，不能把不可信可执行页面变成可安全获授私有数据的主体。

## 决策

第一版交付静态 HTML/CSS Dashboard，入口固定为 Project Workdir 的 `dashboard/index.html`。专用 writer 限制页面为 UTF-8、最大 1 MiB、含 `<html` 或 `<!doctype html`，并拒绝 `<script`、`meta` 和非页内锚点的 `href`。前端将页面放入受控 `srcdoc` 文档壳的 body，固定 head CSP 限制网络；iframe 使用空 `sandbox` 和 `no-referrer` 渲染，不存在 bridge、页面数据读写接口或浏览器写接口。

页面 bytes 由 Workdir 拥有，revision/hash 由 yuanlei `project_dashboards` 拥有。写入以项目 advisory lock 对账外部改写、比较 `expected_revision`，再经 no-follow 临时文件、fsync、rename 原子替换并回读。普通可读的外部改写先采纳为一个 revision 后返回冲突；可读但违反静态策略的旧页面只会显示 `repair_required`，不会被渲染或采纳，且仅持有当前 revision 的安全写入可以覆盖修复。符号链接、坏编码和超限入口仍 fail-closed。

`dashboard_read` 和 `dashboard_write` 只在正在执行的根 Project Run 中可用，沿 Run→Conversation→Project 重新授权，并锁定 Run、核验运行时 worker 与当前未过期 lease；子智能体、无项目上下文、失去 lease 的 worker 和不可见 Project 都被拒绝。命名 JSON 继续由 `project_documents` 的受控 API 保存，不向 iframe 暴露。

## 替代方案

- **任意 Dashboard 脚本加私有 bridge：拒绝。** 脚本持有私有数据后无法证明其不可外传；导航后的 WindowProxy 复用是直接反例。
- **执行脚本但不提供私有数据：拒绝作为 v0 范围。** 没有当前消费者，却增加页面行为与浏览器验证面。
- **DOM 清洗后提供 bridge：拒绝。** 清洗无法稳定覆盖所有可执行语义，且会形成不稳定的受限语言。
- **直接做项目工作台：延后。** 智能体列表、创建和详情跳转需要独立的受信任 UI、授权、审计和冲突契约。
- **只把 HTML 放 PostgreSQL：拒绝。** 页面是项目交付物，应保留在 Workdir 并可被项目 Git 看见；数据库只保存并发与对账元数据。

## 后果

用户可以查看 Agent 生成的说明、进度、卡片、表格、内联样式和 data URI 图像，但不能期待页面列出现有智能体、读取项目目标、跳转对象详情或新增智能体。命名 JSON 已有版本化存储边界，供后续受信任工作台使用；它不是 Dashboard 页面数据接口。

未来项目工作台必须新建 Decision，明确项目目标等 JSON 的 schema 与编辑入口、智能体列表的可见性查询、创建智能体的后端授权和审计，以及页面与工作台之间的边界。

## 验证

- `docker compose exec api python -m pytest test/unit/services/test_project_dashboard_service.py test/unit/toolkits/test_dashboard_tools.py -q`：17 passed。
- `docker compose exec api python -m pytest test/integration/services/test_project_dashboard_service.py -q`：12 passed；其中自动跳转和外链旧页均进入修复态，旧 revision 得到 409，当前 revision 的安全写入恢复为 ready。
- Dashboard HTTP/API 与 Agent 工具 integration：8 passed；覆盖跨用户、empty/ready/repair、无项目上下文、子智能体、worker owner 不匹配和过期 lease 拒绝。
- 前端相关 unit、全量 lint、生产构建通过；真实已登录浏览器验证项目 `Yuanlei` 的 revision 4：页面在空 sandbox、`no-referrer` iframe 和固定 head CSP 内渲染，控制台无警告/错误，编辑入口带项目上下文跳转。含恶意资源的自动浏览器用例已写入 `web/test/browser/projectDashboardStaticFrame.js`，本机无 `playwright-cli`、前端依赖也未安装 Playwright，故该自动用例未执行；CSP 伪造 head 的负向结构由 unit 覆盖。
- 真实根 Project Agent Run 通过 `dashboard_read`/`dashboard_write` 将修复后的静态页面提交为 revision 4；重新读取得到 `ready`、hash `65d09eb10c90…`、12596 bytes。
- 工程契约检查与 70 个契约单测通过；完整后端 unit 为 2502 passed、57 skipped，3 个 `.xls` 解析用例因容器缺少 `xlrd` 失败；另一个多进程 skills 锁用例在全量运行时超时，单独重跑通过。上述均非 Dashboard 用例。
