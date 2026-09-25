# Decision：元垒督查板（秘书数字员工、只读聚合与汇报）

状态：implemented
类型：feature
Owner：backend/package/yuxi/services/inspection_board_service.py
日期：2026-09-25
关联 Feature：[项目督查板](../../features/project-inspection-board.md)

## 问题

督查与汇报需要一条「定时任务驱动项目数字员工，只读汇聚执行面事实并产出汇报，在 Dashboard/Taskboard 展示」的通道。Step 1 已有治理四表，Step 2 已有蓝图与决策生命周期，但缺少三样东西：把治理事实与上游 Run 事实聚合成一个读视图的用例；让项目数字员工只读汇总并写入汇报、打开议题的 Agent 工具；以及把事实暴露给 Dashboard/Taskboard 的读接口。若为展示另建镜像表、或让汇报复制/回写 Run 终态，就会出现第二个状态 Owner 与镜像漂移。上游 Yuxi 拥有 AgentRun、队列与用户自建定时任务，但没有任何督查聚合读模型。

## 决策

新增督查板只读聚合，不新增表、不升 schema。

- 读模型 `backend/package/yuxi/services/inspection_board_service.py`：直接读治理四表与上游 `agent_runs`，不建镜像表、不写 Run。`open` 指仍在 `proposed` 的议题/任务/决策，`blockers` 指 `failed`/`interrupted` 的 Run。
- 持久化读查询 `backend/package/yuxi/repositories/inspection_board_repository.py`：按 Project（经 `conversations.project_id` 归属）读取最近 Run、阻塞 Run 与状态计数。
- Agent 工具 `backend/package/yuxi/agents/toolkits/buildin/governance_tools.py`：`governance_board_read`（只读聚合）、`governance_report_write`（写 `governance_reports`，`source_run_id` 绑定当前 Run，`artifact_path` 引用产物）、`governance_topic_open`（写 proposed 项目内议题）。工具在带 Project 的运行中经 `resolve_project_run_scope` 重建 Run→Conversation→Project 授权并校验 lease，子智能体拒绝。
- HTTP 接口 `backend/server/routers/governance_router.py`：`GET /projects/{id}/governance/board`、`GET /governance/board`（跨项目）、`POST /projects/{id}/governance/topics`、`.../topics/{topic_id}/review`、`.../tasks/{task_id}/review`、`.../reports`。
- 秘书数字员工复用现有 ProjectAgent，不引入角色抽象；定时触发链路是上游 `ScheduledAgentJob`，本步不新建调度器。
- 无 schema 迁移，`YUANLEI_SCHEMA_VERSION` 保持 10。

## 替代方案

- 为督查板建镜像/缓存表：拒绝。会产生第二状态 Owner 与漂移，违反唯一事实源。
- 让秘书工具或汇报直接改 Run 状态：拒绝。执行终态由上游拥有，汇报只引用产出 Run。
- 在 Agent 工具内重复实现聚合查询：拒绝。读模型归 service，持久化查询归 repository。
- 新建「秘书/参谋/执行」角色抽象：拒绝。沿用 2026-09-24 六项决策，ProjectAgent 已能表达。
- 前端自行读取 Run 明细并判断状态：拒绝。前端只消费 board 读视图，避免状态判断分叉。

## 后果

- Dashboard/Taskboard 的议题/任务状态直接来自治理四表与 `agent_runs`，无镜像漂移。
- 汇报写入永不触碰 `agent_runs`，生产 Run 的终态由上游链路维护。
- 跨项目 `blockers` 计数来自状态计数；`blocked_runs` 明细按项目有界（各取最近 10 条），最近 Run 明细各取 20 条。
- 治理 Agent 工具默认对所有项目数字员工按工具配置可见，子智能体禁用。
- 前端 Vue Taskboard 页面不在本记录范围；本步交付其数据面（board 接口）。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 督查板展示的议题/任务/决策与执行事实与唯一事实源逐项一致 | Dashboard 读视图与来源漂移 | `inspection_board_service.py` | `test/integration/services/test_inspection_board_service.py::test_project_board_reads_governance_and_run_facts_from_source` | 逐项等于 `list_governance_*` 与 Run 事实；pending 只含 proposed | Passed |
| 跨项目 open 议题、待决策队列与阻塞项可汇总 | 议题队列只能单项目查看 | `get_user_inspection_board` | `test/integration/services/test_inspection_board_service.py::test_cross_project_board_aggregates_pending_and_blockers` | summary 对两个 selectable Project 汇总 | Passed |
| 汇报只引用产出 Run，不终结或改写 Run 终态 | 汇报成为第二 Run 状态源 | `governance_reports` + `create_governance_report` | `test/integration/services/test_inspection_board_service.py::test_report_write_references_run_without_changing_run_status` | 写汇报后回读 Run 仍为 `running` | Passed |
| 不可见/未知 Project 不泄漏事实 | 跨用户读取他人督查板 | Project 可见性查询 | `test/integration/services/test_inspection_board_service.py::test_board_rejects_invisible_or_unknown_project` | 未知 Project 404 | Passed |
| 治理 Agent 工具注册、元数据与越权收敛 | runtime 泄漏进 schema 或子智能体调用 | `governance_tools.py` + `resolve_project_run_scope` | `test/unit/toolkits/test_governance_tools.py` | 子智能体返回 `invalid_request` | Passed |
