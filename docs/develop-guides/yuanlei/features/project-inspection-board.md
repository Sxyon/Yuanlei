# 项目督查板：只读聚合、汇报与 Taskboard 展示

状态：已实现
类型：feature
主要 Owner：backend/package/yuxi/services/inspection_board_service.py
展示 Owner：web/src/views/InspectionBoardView.vue、web/src/views/ProjectInspectionBoardView.vue、web/src/components/inspection/GovernanceBoardPanel.vue

## 需求与失败场景

元垒需要一个督查与汇报面：由上游用户自建定时任务驱动项目数字员工，只读汇聚 Run、任务、产物与失败，产出周期汇报，并在 Dashboard/Taskboard 呈现跨项目的 open 议题、阻塞项与待决策队列，且可由汇报打开新议题。汇报的载体是定时任务产出的 artifact，元垒只保存结构化引用。跨项目页面只读呈现督查板；单项目页面把只读督查面板嵌入可操作工作台，并支持议题长文讨论、审核前修改和只读历史。

失败场景：为展示另建镜像表导致议题/任务状态与来源漂移；汇报复制或回写 Run 终态，使执行面出现第二个状态 Owner；跨项目待决策队列只能单项目查看；展示面缺失或前端自行解析 Run/治理状态导致展示与唯一事实源分叉；子智能体或越权运行读写项目督查事实。

## 必须保留的业务语义

- 议题/任务/决策状态只有唯一事实源：治理四表；督查板读视图直接读来源，不建立可独立漂移的镜像。
- 执行事实归属上游 `agent_runs` 与 `conversations`；督查板只读，不终结、不改写 Run 状态。
- 汇报写入 `governance_reports`，只引用 `source_run_id` 与 `artifact_path`，不保存 Run 终态。
- `open` 指仍在 `proposed` 的议题/任务/决策；`blockers` 指 `failed`/`interrupted` 的 Run。
- Agent 工具只在带 Project 的运行中重建授权并校验当前 worker lease；子智能体拒绝。
- 跨项目视图只覆盖当前用户 active、selectable 的 Project。
- 督查面板只消费 board 读视图：跨项目入口消费 `GET /governance/board`，单项目工作台消费 `GET /projects/{id}/governance/board`；治理与执行操作由单项目工作台通过各自 API 完成，后端拥有最终状态。Dashboard 的关系图直接派生议题、决策和任务外键，节点选中后展示详情并跳转到工作台对应记录。
- 展示面读取授权由后端执行：读接口要求登录用户，单项目 board 对不可见项目 404；前端路由守卫只提供体验约束。

## 与 Yuxi 的边界

上游 Yuxi 拥有 Project、Conversation、AgentRun、队列、执行与用户自建定时任务；督查板不在这些域新增语义，也不新建调度器或角色抽象。元垒的督查读模型不新增表；单项目工作台复用治理写接口、蓝图 Workdir 与委派事实。

## 稳定集成点

- 读模型：`backend/package/yuxi/services/inspection_board_service.py` 的 `get_project_inspection_board` 与 `get_user_inspection_board`。
- 持久化读查询：`backend/package/yuxi/repositories/inspection_board_repository.py` 按 Project 读取最近 Run、阻塞 Run 与状态计数。
- Agent 工具：`backend/package/yuxi/agents/toolkits/buildin/governance_tools.py` 的 `governance_board_read` / `governance_report_write` / `governance_topic_open`；运行范围解析复用 `backend/package/yuxi/agents/toolkits/buildin/project_run_scope.py`。
- HTTP 接口：`backend/server/routers/governance_router.py` 的 `/projects/{id}/governance/*` 与 `/governance/board`。
- 展示面：`web/src/views/InspectionBoardView.vue`（跨项目 `/inspection`）与 `web/src/views/ProjectInspectionBoardView.vue`（单项目工作台 `/projects/:project_id/inspection`）共用只读 `web/src/components/inspection/GovernanceBoardPanel.vue`；API 适配在 `web/src/apis/governance_board_api.js`，展示适配与状态文案在 `web/src/utils/governanceBoard.js`。
- 治理事实 Owner：`governance_service.py` 与治理四表；汇报写入复用 `create_governance_report`。

## 上游依赖

- `projects`：督查板只覆盖当前用户 active、selectable 的 Project。
- `conversations.project_id`：Run 经 Conversation 归属 Project，跨项目聚合按此过滤。
- `agent_runs`：只读最近 Run、阻塞 Run 与状态计数；终态由上游维护。
- `agents(slug)`：任务指派的项目数字员工沿用既有绑定校验。

## 合并判断

上游若提供等价的 Run/任务聚合读模型或 Taskboard 消费面，按业务语义重新取舍：仅当上游事实 Owner 更权威、且能表达 proposed→审核→canonical 与来源归一化时，才采用上游实现并缩小本差异。`open`/`blockers` 的定义与「汇报只引用不拥有 Run」是元垒产品主张，缺失对应上游语义前保留。

## 替换或删除条件

当上游拥有等价的督查聚合读模型，并能保证读视图不成为第二状态 Owner、汇报不复制 Run 终态时，可删除本读模型、Agent 工具与只读展示面。删除前需要新的 Decision 说明 Dashboard/Taskboard 消费侧的替换路径与既有汇报记录的处理。

## 决策与证据

- Decision：[元垒督查板](../decisions/implemented/2026-09-25-yuanlei-inspection-board.md)。
- Decision：[项目议题讨论、决策入口与关系图](../decisions/implemented/2026-09-27-project-governance-discussion-and-graph.md)。
- 读模型与持久化：`backend/package/yuxi/services/inspection_board_service.py`、`backend/package/yuxi/repositories/inspection_board_repository.py`。
- Agent 工具与授权：`backend/package/yuxi/agents/toolkits/buildin/governance_tools.py`、`project_run_scope.py`。
- 真实 PostgreSQL 行为证据：`backend/test/integration/services/test_inspection_board_service.py`。
- Agent 工具单测：`backend/test/unit/toolkits/test_governance_tools.py`。
- HTTP 适配：`backend/server/routers/governance_router.py`。
- 展示面单测：`web/test/unit/governanceBoard.test.js`（API 端点、文案回退与「只消费读视图字段」源码 guard）。
- 展示面渲染证据：`web/test/unit/governanceBoard.test.js` 的督查面板源码 guard、文案/配色查表单测与 `vite build`；2026-09-26 真实浏览器核对单项目工作台蓝图、任务委派和汇报，关联 [单项目本地闭环决策](../decisions/implemented/2026-09-26-single-project-local-loop.md)。
