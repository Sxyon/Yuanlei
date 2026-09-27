# 项目蓝图 Workdir 事实源

状态：已实现
类型：新增能力
主要 Owner：`backend/package/yuxi/services/project_blueprint_service.py`

## 需求与失败场景

参谋板负责把模糊意图收敛为有理由、可演进、可 diff 的方案。项目蓝图承载产品规划、设计、工程与交互方案，需要随项目发展持续修订，并同时被项目数字员工起草、被人审阅编辑。元垒把蓝图固定在 Project Workdir 的 `.yuanlei/blueprint/` 目录，用 Markdown 文件承载内容，数据库不保存蓝图正文。旧蓝图按整份文档归档，供项目工作台只读翻阅。

失败场景：蓝图正文存进数据库后与 Workdir 出现两份内容，Agent 写入文件、页面写入数据库，双方都自称事实源；文档名携带路径分隔符或 `..` 时写到 Workdir 之外；非所属用户或不可见项目读取、改写他人蓝图；蓝图目录被同名普通文件占用时静默覆盖或写入失败但不报告。

## 必须保留的业务语义

- 蓝图文档是 Project Workdir 下的 `.yuanlei/blueprint/` 目录内的单层 Markdown 文件；文档名支持中文、英文小写和数字，可在后续字符中使用点、下划线或短横线。名称不超过 120 个字符；为使归档文件仍满足常见文件系统单个分量 255 字节限制，去除 `.md` 后 UTF-8 不超过 194 字节。英文名称保持小写。
- 蓝图正文的事实 Owner 是文件本身。读取接口每次回读文件；直接改写磁盘文件会改变后续读取结果。数据库没有蓝图行，直接改库不改变蓝图内容。
- 写入按需幂等创建 `.yuanlei` 与 `blueprint`；任一层被普通文件或符号链接占用时以结构化 409 显式失败，不写入蓝图文件。
- 只有当前用户 active、selectable 的 Project 可以读取与写入蓝图；其他用户、隐式或已删除项目统一返回 404。
- 正文按 UTF-8 编码，单文档上限 256 KiB；超限与非 UTF-8 内容以结构化错误拒绝。
- 文档以原子替换写入，同一路径的并发写遵循真实 POSIX 结果；目录内容天然可进 Git、可 diff。
- 新建文档独占同名文件，不覆盖已有正文；归档把整份当前文档移入同一 Workdir 的 `archive/` 子目录，当前列表只含未归档文档，归档可按原名与时间回读。归档不逐次保存编辑版本。
- 项目数字员工的运行时 Workdir 指向所属 Project 的同一目录，蓝图路径在其工作范围之内。

## 与 Yuxi 的边界

Yuxi 继续拥有 Project、Conversation、AgentRun、Workdir 的 no-follow 文件边界与 Agent 文件工具。元垒新增蓝图用例与只读/写入 HTTP 端点，并在 Agent 文件系统提示中声明 `.yuanlei/blueprint/` 约定；元垒不新增数据库表，不修改上游 business 或 knowledge schema。

## 稳定集成点

| 集成角色 | 当前 Owner | 元垒语义 |
|---|---|---|
| Project 可见性 | `ProjectRepository.get_active_selectable_for_user` | 当前用户 active、selectable Project，否则 404 |
| Workdir 打开 | `Workdir.open_existing`、`ensure_bound_user_workdir` | managed 先物化，linked 需已存在，不可用返回 409 |
| 文件读写 | `Workspace` 文件 capability | no-follow 目录边界、有界读取、独占创建、原子替换与不可覆盖的同 Workdir 归档 |
| HTTP 入口 | `server/routers/project_blueprint_router.py` | 蓝图创建、读写和归档的授权入口；非法输入 422 |
| Agent 起草 | `yuxi.agents.buildin.chatbot.prompt.build_prompt_with_context` | 文件系统提示声明蓝图固定目录 |

## 上游依赖

依赖 Project 归属查询、Workdir no-follow 原语、用户认证依赖与 Agent 运行时 Workdir 绑定。蓝图用例复用上游既有的文件 capability，不引入新的沙盒或存储后端。

## 合并判断

上游若提供等价的“项目级可演进方案文档 + 人机共同编辑”事实源，比较其存储边界、路径隔离与并发语义后采用或缩小此差异。蓝图落在 Workdir 并归属 Project，是元垒“可演进文档进 Workdir、结构化事实进 DB”的产品主张；上游缺失对应语义前保留本实现。

## 替换或删除条件

当上游拥有等价的项目级方案文档事实源，且能保证路径隔离、原子写入与 Workdir 归属时，可删除本用例与端点。删除前需要新的 Decision 说明既有蓝图文档的迁移路径与 Dashboard/Taskboard 消费侧的替换方案。

## 决策与证据

- Decision：[项目蓝图 Workdir 事实源](../decisions/implemented/2026-09-24-project-blueprint-workdir.md)。
- Decision：[项目蓝图新建与整份归档](../decisions/implemented/2026-09-27-project-blueprint-archive.md)。
- Decision：[项目议题讨论、决策入口与关系图](../decisions/implemented/2026-09-27-project-governance-discussion-and-graph.md)。
- 用例实现：`backend/package/yuxi/services/project_blueprint_service.py`。
- HTTP 入口：`backend/server/routers/project_blueprint_router.py`。
- 真实 PostgreSQL 与真实文件系统证据：`backend/test/integration/services/test_project_blueprint_service.py`。
- 纯逻辑与路由契约单测：`backend/test/unit/services/test_project_blueprint_service.py`、`backend/test/unit/routers/test_project_blueprint_router.py`。
