# Decision：项目蓝图重命名与永久删除

状态：implemented
类型：feature
Owner：backend/package/yuxi/services/project_blueprint_service.py
关联 Feature：[项目蓝图 Workdir 事实源](../../features/project-blueprint.md)

## 问题

元垒蓝图只能编辑和归档，名称错误无法纠正，无价值内容只能保留。Yuxi Workdir 已拥有不可覆盖的文件移动与受限文件访问能力。

## 决策

当前蓝图支持重命名，拒绝覆盖同名文件，保留正文与页面未保存编辑，成功后继续选中。归档蓝图保留当时名称。当前与归档蓝图均可确认后永久删除普通文件；弹窗显示名称和无法恢复提示，当前正文有未保存修改时明确提示丢失。

名称范围细化[Workdir 事实源](./2026-09-24-project-blueprint-workdir.md)的命名约定。新建与重命名以中文、英文或数字开头，支持大小写英文、中文、数字和常用标点，禁止内部空白、路径分隔符与英文 `: * ? " < > |`。首尾空白去掉，页面自动补全并隐藏 `.md`；保留 120 字符与 stem UTF-8 194 字节限制。归档按扩展后的名称规则识别与回读。

正文继续由 Workdir 文件拥有；重命名复用不可覆盖原子移动，删除通过 Workspace 的普通文件删除能力拒绝目录、链接与特殊文件。授权复用 active selectable Project 所属用户查询。元垒不新增数据库结构。

删除接口返回 204 空响应。前端公共请求层以状态码识别无正文的成功，JSON 模式返回 `null`，然后页面关闭确认并回读列表；普通 JSON 响应仍严格解析，损坏响应继续显式失败。

当前蓝图管理操作收纳在更多菜单，归档删除位于所选历史预览。表单、提示与危险操作使用现有组件和颜色 token，适配浅色、深色与窄屏。

## 替代方案

- 回收站：增加额外管理位置；用户选择确认后永久删除。
- 归档重命名：改变归档时名称；用户选择归档只读且允许删除。
- 旧页面保存拒绝重建：改变整体保存契约；用户明确接受负责人自行清理。
- 聊天、议题、决策联动修改：扩大业务耦合；用户选择由修改者负责维护，后续智能体自动处理属于独立需求。

## 后果

永久删除无法通过蓝图界面恢复。聊天、议题、决策与旧文件路径引用不自动修改；蓝图负责人负责维护。旧页面整体保存仍可重新生成删除或改名后的旧文件。上游合并保留文件事实源、授权边界与用户确认的职责划分。

## 验证

- 容器内隔离代码副本运行 `python -m pytest --import-mode=importlib test/unit/services/test_project_blueprint_service.py test/unit/routers/test_project_blueprint_router.py test/integration/services/test_project_blueprint_service.py -q`：17 passed。真实 PostgreSQL 隔离 Schema、HTTP 与文件回读覆盖同名不覆盖、正文保留、当前与历史删除、越权、非法名称、目录和链接拒绝，以及旧页面保存重新创建契约。
- `node --test test/unit/blueprintName.test.js test/unit/projectBlueprintEditing.test.js`：5 passed，覆盖名称规则、改名继续选中与草稿保留、同名失败、删除失败保留编辑及删除成功清空并回读列表。
- 隔离示例数据页面挂载实际工作台组件，浏览器验证改名、删除取消、当前与归档删除、空状态、名称错误、浅色/深色和 390px 长名称弹窗，并保存截图；该视觉验证不替代真实后端 HTTP 证据。
- 最终 `python -m pytest test/integration/services/test_project_blueprint_service.py -q`：10 passed，补充文件系统不支持安全重命名时显式拒绝且原文件保留的负向案例。
- 前端 lint 与 build、Python Ruff、工程契约验证与 70 项 verifier unit、VitePress 文档构建通过。全量前端 unit 有两项 Dashboard 测试因 Pinia 初始化失败，未修改 HEAD 的同一测试同样失败；该范围未计为通过。全量后端 unit 为 2721 passed、61 skipped、1 failed；失败为既有 Skill 多进程测试的 20 秒子进程超时，单独复测仍超时，未验证根因。上述全量 gate 未计为通过。
- 浏览器页面使用示例 API，未执行登录、数字员工和 worker 的跨进程 E2E；本功能沿用既有保存、权限与 Workdir 绑定契约。

- 空响应回归由 `web/test/unit/api_boundary.test.js` 调用真实蓝图 API 封装和公共请求层，覆盖当前与归档删除的 204 + JSON 响应头，及普通 JSON 成功和损坏 JSON 拒绝；恢复无条件 JSON 解析时复现 `Unexpected end of JSON input`。
