# Decision：项目蓝图 Workdir 事实源

状态：implemented
类型：feature
Owner：backend/package/yuxi/services/project_blueprint_service.py
日期：2026-09-24
关联 Feature：[项目蓝图 Workdir 事实源](../../features/project-blueprint.md)

## 问题

参谋板需要一条把模糊意图收敛为可演进方案的通道。项目蓝图覆盖产品规划、设计、工程与交互方案，需要随项目发展持续修订，并由项目数字员工起草、由人审阅编辑。上游 Yuxi 拥有 Project 与 Workdir 文件 capability，但没有“项目级方案文档”的事实源。

把蓝图正文放进数据库会与 Workdir 形成两份内容：Agent 通过文件工具写入文件，页面或接口写入数据库，双方都自称事实源并可能静默漂移。把蓝图直接放进 Workdir 根目录，会与用户已有目录冲突；文档名携带路径分隔符或 `..` 时，写入还可能越出 Workdir 边界。

## 决策

在 Project Workdir 的固定目录 `.yuanlei/blueprint/` 承载蓝图文档，新增用例与 HTTP 端点，不新增数据库表。

- 文档是固定目录内的单层 `.md` 文件，名称在进入文件系统前校验。名称范围、长度限制与管理操作由[项目蓝图重命名与永久删除](./2026-10-04-blueprint-rename-delete.md)细化。
- 蓝图正文的事实 Owner 是文件。读取每次回读文件；写入以原子替换落盘。数据库没有蓝图行，直接改库不影响蓝图内容。
- 写入按需幂等创建 `.yuanlei` 与 `blueprint`；任一层被普通文件或符号链接占用时以结构化 409 fail-closed。
- 用例在 `backend/package/yuxi/services/project_blueprint_service.py`；路由在 `backend/server/routers/project_blueprint_router.py`，暴露 `GET /api/projects/{id}/blueprint`、`GET/PUT /api/projects/{id}/blueprint/{name}`。
- 鉴权复用 Project 归属查询：仅当前用户 active、selectable 的 Project 可读可写，其他情况 404。
- Agent 侧在 `build_prompt_with_context` 的文件系统提示中声明 `.yuanlei/blueprint/` 为蓝图固定目录，项目数字员工用既有文件工具起草，人通过 HTTP 端点编辑。
- 决策的 proposed → implemented 生命周期继续由治理域 `governance_decisions` 拥有；蓝图记录方案内容，决策记录结论与理由，两者的关联通过议题/决策标题与正文引用表达，不在蓝图文件上复制决策状态。

## 替代方案

- 蓝图正文进数据库：拒绝。会产生第二份内容与静默漂移，且数据库无法原生表达可 diff 的演进。
- 蓝图放在 Workdir 根目录的 `blueprint/`：拒绝。linked 模式下可能命中用户已有同名目录，读取到无关文件。
- 为蓝图增加数据库 revision 与 hash 对账：拒绝作为本期范围。蓝图正文本身可进 Git，revision 对账留给确实需要并发写控制的场景；引入会新增第二状态 Owner。
- 为 Agent 新增专用蓝图读写工具：拒绝作为本期范围。项目数字员工已有受 Workdir 约束的文件工具，提示中声明固定目录为零新增抽象的等价路径。
- 由前端直接读写文件系统：拒绝。前端守卫不是授权边界，读写必须经后端 Project 归属校验。

## 后果

- 蓝图与 Workdir 同生命周期，可进 Git、可 diff、可被 Agent 与人共同编辑；不存在数据库正文副本。
- 蓝图目录是元垒在文件系统上的命名空间约定，与元垒持久化结构进独立域的原则一致，降低与用户内容冲突的风险。
- 本记录不承诺蓝图的版本对账、并发冲突解决与前端展示入口；这些能力需要时另行决策。
- 上游同步时，本用例与端点为元垒新增面，不随上游覆盖删除；`build_prompt_with_context` 的提示行是元垒对上游文件的最小差异，冲突时按业务语义保留。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 蓝图正文事实 Owner 是 Workdir 文件 | 数据库与文件两份内容 | `project_blueprint_service.py` + `Workspace` | `test/integration/services/test_project_blueprint_service.py::test_blueprint_round_trip_is_filesystem_owned` | 直接改写磁盘文件后读取回读新内容 | Passed |
| 文档名越界被拒 | 写到 Workdir 之外 | `validate_blueprint_name` | `test/unit/services/test_project_blueprint_service.py` | `../escape.md`、`sub/escape.md`、内部空白与非 `.md` 名 422 且不落盘 | Passed |
| 目录被非目录占用 fail-closed | 静默覆盖或未报告失败 | `_ensure_blueprint_directory` | `test/integration/services/test_project_blueprint_service.py::test_blueprint_conflicts_when_directory_is_file` | `.yuanlei` 为普通文件时 409 | Passed |
| 仅所属用户可见项目可读写 | 越权读改他人蓝图 | `_require_project` | `test/integration/services/test_project_blueprint_service.py::test_blueprint_requires_owned_selectable_project` | 其他用户、隐式与已删除 Project 404 | Passed |
| HTTP 契约与非法输入处理 | 非法 payload 或名称进入用例 | `project_blueprint_router.py` | `test/unit/routers/test_project_blueprint_router.py` | 未知字段 422，ValueError 映射 422，缺失 404 | Passed |
| 项目数字员工获知蓝图固定目录 | Agent 无固定起草位置 | `build_prompt_with_context` | `test/unit/agents/test_chatbot_prompt.py` | 缺少 Workdir 路径时显式失败 | Passed |
