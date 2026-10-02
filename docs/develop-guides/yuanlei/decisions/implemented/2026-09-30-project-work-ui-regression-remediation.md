# 项目工作体系界面显示与看板状态回读整改

状态：implemented
类型：bug-fix
Owner：web/src/views/ProjectWorkTasksView.vue
关联 Feature：[独立项目工作任务与 Issue](../../features/project-work-tasks.md)、[用户收件箱](../../features/user-inbox.md)

## 问题

真实浏览器逐页回归项目工作任务、任务详情、数字员工工作台与用户收件箱后，确认以下展示与操作事实问题：

- 看板卡片的“更改任务状态”在更新请求失败时保留用户所选，卡片仍停留在原状态列，页面同时显示错误，界面与 PostgreSQL 事实不一致。
- 数字员工工作台页面标题显示内部 slug（如 `agent-4278a9bf3994`）；任务详情“智能体执行”列表也只显示 agent slug。
- 任务详情“问题单”列表直接展示英文状态 `open`/`resolved`/`closed`，与同页其他中文状态不一致。
- 工作台错误态缺少重试入口，与任务列表、任务详情、收件箱的错误态不一致。

收件箱的未读/已读/归档、标已读、归档与来源跳转在回归中行为正确，本次不需要改动。`user_inbox_items.kind` 的词表由后端 CHECK 约束拥有，覆盖 `task_completed`、`run_question`、`task_failed`、`task_interrupted` 与周期巡检新增的 `task_inspection`；Web 收件箱 `InboxView.vue` 的 `KIND_META` 为每个种类提供中文标签与来源跳转。YL-26 新增 `task_inspection` 时未同步 `KIND_META`，集成 head 的真实页面把该通知渲染为原始英文种类；本记录原先「前端映射与之一致，无缺失种类」的表述错误，该集成回归已在 [收件箱补齐 task_inspection 种类映射](2026-10-02-inbox-task-inspection-kind-mapping.md) 中补齐。

## 决策

看板状态变更 (`ProjectWorkTasksView.changeStatus`) 在成功或失败后一律以服务端读回为准：先发出更新请求，再后台回读任务列表，失败时展示 `actionError` 并让卡片回到 PostgreSQL 事实，不保留乐观选择。回读使用不切换整页 `loading` 的静默模式，避免看板在每次状态变更时整页闪动。

工作台标题使用项目数字员工显示名：加载时并行读取项目归属列表，取匹配 slug 的 `name`；归属列表读取失败时降级为 slug 且不阻断工作台本身。任务详情执行记录通过页面已加载的 `agents` 列表把 slug 映射为名称，缺失时回退 slug。

问题单状态补充中文映射（`待处理`/`已解决`/`已关闭`），未知值原样回退。工作台错误态补充重试按钮。

## 替代方案

- 在后端工作台响应里返回 `agent_name`：需要新增后端字段与集成测试；UI 展示需求用 Web 已有的项目归属列表即可满足，保持改动在 Web 层。
- 用乐观 UI 直接改写卡片状态：执行状态由 PostgreSQL 拥有，更新失败后前端回读服务端事实，不保留乐观值。
- 后台回读也切换整页 `loading`：会让看板在每次状态变更时被整页 spinner 替换，属可见退化；改用静默回读。

## 后果

看板状态更新失败时页面回到服务端事实并同时提示错误，后台回读不引发整页闪动；工作台与任务详情使用可读名称；工作台错误态可重试。未引入新依赖，未改变 API 契约、权限或持久化。

本修复不改动语义 Owner、持久化边界、权限或兼容承诺，属同一变更内即时生效且无待裁决取舍，直接记 `implemented`。

## 验证

- Web unit（`node --test`）本项目相关视图测试 20 项通过，含新增 5 项：看板失败后回读服务端事实（断言读取两次且以第二次服务端状态为准，移除失败后的回读即不通过）、执行记录与问题单可读映射、工作台标题显示名、归属列表读取失败降级、任务设置保存负载。
- `pnpm run lint:check`、`pnpm run build`、`pnpm run test:unit`（424 项）通过。
- 真实浏览器（Chromium，Playwright）回归：工作台标题显示“调研员码农”；任务详情执行记录显示“测试员码农”、问题单显示“待处理”；空项目看板显示空态；注入 500 时任务页显示错误态与重试按钮。浅/深色与窄屏截图见交付 issue。
