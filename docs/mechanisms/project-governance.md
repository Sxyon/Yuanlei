# 项目治理、委派与督查如何协作

本页面向需要理解项目功能边界的管理员和开发者，解释蓝图、议题、任务、委派、汇报及展示页面各自保存什么。日常操作从[项目工作台使用指南](../intro/project-workbench.md)开始。

## 模块与事实归属

| 模块 | 当前事实源 | 用户看到的结果 |
| --- | --- | --- |
| 项目蓝图 | Project Workdir 中的 `.yuanlei/blueprint/` Markdown 文件 | 工作台编辑、归档和历史蓝图阅读 |
| 议题、决策、任务、汇报 | PostgreSQL 的 `yuanlei` 治理域 | 项目工作台的审核、关联和记录 |
| 项目数字员工 | 项目与 Agent 的持久绑定及项目级配置覆盖 | 项目内可选执行者与专属运行范围 |
| 编码会话与委派 | 编码会话事实和委派记录分别保存 | Codex/OpenCode 执行状态、回收结果与产物 |
| Agent Run | 上游 PostgreSQL 请求、Run 和消息 | 执行动态、失败和中断状态 |
| 督查板与默认概览 | 从治理事实、Run 和蓝图读取的视图 | 跨项目待处理汇总、单项目概览与关系图 |
| 自定义 Dashboard | 项目静态页面文件及其 revision | 隔离展示的 HTML/CSS 页面 |

蓝图正文不写入治理表；督查板不复制 Run 终态。项目关系图从议题、决策和任务之间的既有关联生成。汇报可以保存产出 Run 和文件产物的引用，周期运行由用户配置的 Agent 定时任务驱动。

## 从提议到执行

项目内及外部渠道产生的议题、任务先以 `proposed` 保存。议题审核决定是否纳入项目，研讨进度独立记录；未归档议题在纳入、拒绝或关闭后仍可修订和讨论。决策由人记录结论、理由及关联议题。议题各维度的状态、转换及历史规则见[议题状态与历史](./topic-lifecycle.md)。任务仍按其自身审核与执行规则处理。

任务通过审核且指派给该项目数字员工后，单项目工作台可发起 Codex 或 OpenCode 本地委派。委派有独立状态和结果；编码会话保留本轮执行事实，结果产物写入项目 Workdir。委派结果不会自动审核议题、改写任务状态或伪造 Agent Run。Multica 在配置后提供外部来源和执行渠道：入向先形成待审核提议，出向通过稳定操作标识核对远端工作；缺少渠道配置时本地治理与编码委派仍可用。

## 权限、失败与恢复

项目蓝图、治理接口和督查读视图只覆盖当前用户可见的有效项目。项目数字员工的项目范围在请求接入与实际执行处再次检查；前端筛选不是授权边界。蓝图读写经过 Workdir 的文件边界校验，路径或目录结构异常会显式失败。委派的投递意图先持久化，执行和回收由各自的 owner 与租约收敛；远端状态仅作为投影展示。

项目自定义 Dashboard 是静态页面，使用隔离 iframe 展示，不能直接读写项目治理数据。页面完整性异常时，界面提示修复并展示默认概览。督查板读取已存事实；失败或中断的 Run 作为阻塞项展示，不由展示层终结。

## 源码定位与验证

- [项目治理 Feature](../develop-guides/yuanlei/features/project-governance.md)说明审核语义；执行 Owner 位于仓库中的 `backend/package/yuxi/services/governance_service.py` 与治理 repository，真实 PostgreSQL 验证位于 `backend/test/integration/services/test_governance_service.py`。
- [项目蓝图 Feature](../develop-guides/yuanlei/features/project-blueprint.md)说明 Workdir 文件边界；执行 Owner 是 `project_blueprint_service.py`，真实文件系统验证见同目录的 `test_project_blueprint_service.py`。
- [外部委派 Feature](../develop-guides/yuanlei/features/external-executor-delegation.md)说明本地与 Multica 的状态边界；执行 Owner 是 `delegation_service.py` 和编码会话服务。
- [项目督查板 Feature](../develop-guides/yuanlei/features/project-inspection-board.md)说明读视图与汇报引用；读视图 Owner 是 `inspection_board_service.py`，真实数据库验证见同目录的 `test_inspection_board_service.py`。
- [项目 Dashboard Feature](../develop-guides/yuanlei/features/project-dashboard.md)说明默认概览与静态页面隔离；页面入口是 `web/src/views/ProjectDashboardView.vue` 与 `web/src/views/ProjectInspectionBoardView.vue`。

上述链接解释元垒相对 Yuxi 的差异与取舍；仓库内源码和测试拥有当前运行事实。
