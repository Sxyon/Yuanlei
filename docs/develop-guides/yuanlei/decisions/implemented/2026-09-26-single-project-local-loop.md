# Decision：单项目本地治理与执行闭环

状态：implemented
类型：feature
Owner：backend/package/yuxi/services/delegation_service.py
日期：2026-09-26
关联 Feature：[项目治理域数据模型](../../features/project-governance.md)、[项目蓝图](../../features/project-blueprint.md)、[外部执行器委派](../../features/external-executor-delegation.md)

## 问题

上游 Yuxi 提供 Project、项目数字员工、定时任务与编码沙盒。元垒的治理四表、蓝图和委派接口已有独立实现，但单项目页面只能查看督查板；人无法在同一流程中编辑蓝图、审核任务、发起本地执行并回读结果。通用 HTTP 委派缺少沙盒运行范围，本地编码执行直接失败。真实单项目完整协作尚未有端到端证据。

## 决策

单项目页面承载蓝图编辑、议题审核、决策记录、任务审核、本地 codex/opencode 委派、结果回收和督查读视图。治理写入继续使用治理四表；蓝图继续由 Project Workdir 拥有；编码执行继续由 `coding_sessions` 和 worker 拥有。项目任务入口要求 canonical 状态、项目数字员工绑定和当前可见/管理权限，服务端从登录用户、Project 与绑定 Agent 派生沙盒范围。委派读模型携带来源任务 ID，保存在不可由客户端直接写入的投递意图快照中。沙盒 turn 与委派句柄同事务提交后再投递队列；pending turn 的已有 reconciliation 负责提交后投递失败的恢复。定时汇报沿用现有计划任务与治理报告工具，不新建调度器。

## 替代方案

- 为项目工作台另建状态表：增加可漂移事实，现有治理四表与编码会话已拥有所需状态。
- 由浏览器传沙盒 uid、scope 与 Workdir 路径：这些是授权与隔离边界，必须由服务端派生。
- 为秘书和参谋新增固定角色：现有项目数字员工与工具配置可承担该工作。

## 后果

项目任务可关联多次委派尝试；每次委派保留独立 operation ID 和 turn ID。项目任务的审核状态不被执行结果反向改写。任务关联目前在委派请求快照中，删除任务时历史委派保留任务 ID，读取端应允许任务详情不存在。人从 HTTP 发起的本地委派需从已审核项目任务入口进入；既有 Agent 运行内 `delegation_dispatch` 工具仍可在 Run 授权范围中执行独立编码委派，其任务不归治理表。真实 Codex 已在试点项目完成一次只读任务；其他凭据及自动 cron 时间触发尚未验证。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 未审核任务不能委派，已审核任务能保留来源 ID | 绕过人审与来源丢失 | `DelegationService.dispatch_project_task` | `test/integration/services/test_delegation_service.py` | proposed 任务返回 409；绑定后撤销可见或管理权限时拒绝且不创建委派 | Passed |
| 本地 Codex turn 可完成并回收同一 turn 结果 | 相邻 turn 猜测结果或无法回收 | `DelegationService` / `SandboxCodingExecutor` | 真实项目 Codex turn `e917d62a-8c92-4081-8d65-c0d733d44984` 完成，委派 `4fb3c89ea3fe422ab1bbb7fabd0d336a` 回收并回读 Workdir 产物 | 首次缺技能投影失败，修复后 pending 委派恢复；提交后队列发布失败尚未注入 | Passed |
| 页面可编辑蓝图与操作治理、委派 | 仅展示不可使用 | `ProjectInspectionBoardView.vue` | web lint、396 unit、build；真实浏览器 DOM 与截图 | 未审核任务 409，通用本地入口 422，项目不可见 404 | Passed |
| 单项目计划任务手动触发可产出并展示汇报 | Run 完成但无报告行 | 既有 ScheduledAgentJob 与治理报告工具 | 试点计划任务手动触发，AgentRun `65daf9e9-3652-436e-bf85-5516a7d5b509` completed，汇报行 `bcf5661f-72b3-4574-ab1a-25ec3796cf14` 回读并在页面显示 | 自动 cron 时间触发尚未验证，试点任务保持 disabled | Passed |
