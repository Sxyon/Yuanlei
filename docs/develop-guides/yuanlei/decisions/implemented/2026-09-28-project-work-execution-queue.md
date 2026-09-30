# 项目任务执行队列

状态：implemented
类型：feature
Owner：backend/package/yuxi/services/project_work_execution_service.py
关联 Feature：[独立项目工作任务与 Issue](../../features/project-work-tasks.md)

## 问题

任务状态和聊天 Request FIFO 均无法表示一个项目任务交给多个智能体依次执行，也无法独立呈现智能体待接受、排队、当前和最近工作。进程在分配与投递之间退出时，工作不能丢失。

## 决策

在 yuanlei schema v15 增加任务执行尝试。一次分配先持久化为待接受；用户从智能体工作台接受后进入该智能体 FIFO，派发前允许撤回。数据库部分唯一索引约束同一任务只有一个活跃尝试、同一智能体只有一个执行中尝试。认领等待被撤回事务锁住的队头，不能跳过后派发后续任务。派发认领先提交，再以稳定 request ID 调用现有 `submit_agent_request`；worker 周期重试失联认领，并以同一次 Run 或其 resume 链的终态回写尝试。收敛时核对 Run 的用户、Agent、Thread、来源、外部执行 ID 与初始 request 祖先。完成输出只从对应 Run 的 assistant Message 追加到任务评论，Run ID 唯一索引使重试不重复；缺失对应输出时显示失败。任务完成或智能体解绑时检查活跃尝试。

## 替代方案

- 将任务状态改成 Run 状态：任务可能经历多次执行，状态不能拥有一次 Run 的并发和恢复语义。
- 每个智能体独立建一个 ARQ 队列：需要第二套投递 Owner，且与现有 Request/Run 生命周期竞争。
- 只从 Run 反推工作台：无法表示尚未接受和排队的分配，也无法在投递前持久恢复。

## 后果

任务执行队列复用现有 Run 生命周期及租约；一个 Agent 的项目任务在已中断等待答复时继续占用执行槽。自动接受与默认模型由[任务队列配置决策](2026-09-28-project-agent-work-queue-config.md)拥有。第一负责人周期检查、附件/引用和议题缩写自动固化也未由本决策覆盖。

## 验证

- `backend/test/integration/services/test_schema_migration_version.py`：v14→v15 重复升级、活跃任务和 Agent 唯一约束。
- `backend/test/integration/api/test_project_work_api.py`：真实 HTTP 分配、跨用户拒绝、工作台及任务完成 guard。
- `backend/test/integration/services/test_project_work_execution_service.py`：隔离 PostgreSQL 验证接受、撤回、并发队头锁与 FIFO 认领、终态评论幂等、被拒 Request 释放执行槽及错误 Run 绑定拒绝。
- `backend/test/e2e/test_deterministic_agent_path_e2e.py::test_project_work_assignment_reaches_worker_result_and_task_comment`：使用确定性模型回放，经真实 HTTP、worker、Request/Run 与 PostgreSQL 回读验证手动及自动接受的完成路径、限流失败路径、人工审批中断与恢复链；完成评论绑定最终 Run，失败不生成完成评论，恢复前的 Run 不生成评论。本地四个场景全部通过（`4 passed`）；失联投递恢复仍需独立 E2E 证据。
