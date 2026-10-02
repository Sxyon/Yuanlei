# 收件箱补齐 task_inspection 种类映射

状态：implemented
类型：bug-fix
Owner：web/src/views/InboxView.vue
关联 Feature：[用户收件箱](../../features/user-inbox.md)

## 问题

YL-26 的第一负责人周期巡检新增 `user_inbox_items.kind='task_inspection'`，通知来源 `source_id` 取巡检运行 ID。集成 head 的 `web/src/views/InboxView.vue` 中 `KIND_META` 只有 `task_completed`、`task_failed`、`task_interrupted`、`run_question` 四种，未知种类由回退分支原样显示英文 kind，真实收件箱页面把该通知渲染为 `task_inspection`。YL-27 决策中「词表与前端映射一致、无缺失种类」的表述与集成 head 事实不符。

## 决策

`KIND_META` 增加 `task_inspection`：中文标签「任务巡检」、动作「查看任务」、跳转目标 `project_tasks`。`openItem` 对 `project_tasks` 分支跳转到对应项目的任务列表 `/projects/{project_id}/work/tasks`。巡检通知的 `source_id` 是巡检运行 ID 而不是任务 ID，无法用既有 `task` 目标直接进入任务详情；项目任务详情页展示该任务的巡检记录，从任务列表进入即可。

## 替代方案

- 把巡检通知 `source_id` 改为任务 ID：会改变 `(uid, kind, source_id)` 的运行级幂等，同一任务后续巡检不再产生提醒。
- 复用 `task` 目标拼任务详情 URL：会把巡检运行 ID 当作任务 ID，生成不存在的任务路径。
- 等待后端提供巡检运行详情路由：当前没有该事实 Owner，超出本次修复范围。

## 后果

未知 kind 的回退分支保留，后续新增种类若不同步 `KIND_META` 仍会显示英文。unit 断言锁定 `task_inspection` 的中文标签与跳转，防止再次静默丢种类。未改变持久化、API 契约或权限。

## 验证

- Web unit：`web/test/unit/inboxView.test.js` 覆盖 `task_inspection` 的中文标签、跳转到 `/projects/p1/work/tasks` 与标已读（`node --test --test-concurrency=1 test/unit/inboxView.test.js`，3 项通过）。
- Web gate：`lint:check`、`test:unit`（427 项）、`build` 通过。
- 真实页面：本地环境缺少 `.env` 与服务，收件箱页面复核 `Not run`；`task_inspection` 通知在真实收件箱显示为「任务巡检」并跳转项目任务列表待独立验证补齐。
