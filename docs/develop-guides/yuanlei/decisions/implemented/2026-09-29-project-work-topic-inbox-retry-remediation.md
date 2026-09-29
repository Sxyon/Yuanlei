# 项目任务议题缩写全链路、执行通知与重新执行

状态：implemented
类型：feature
Owner：backend/package/yuxi/services/project_work_execution_service.py
关联 Feature：[独立项目工作任务与 Issue](../../features/project-work-tasks.md)、[用户收件箱](../../features/user-inbox.md)

## 问题

后端已支持议题缩写与 `topic_id`，但 Web 没有 `configureTopicCode`/议题列表调用，新建任务页面无法选择议题，任务编号恒为 `{项目}-GEN-{序号}`，`configure_topic_code` 也缺少真实 HTTP 覆盖。用户收件箱只允许 `task_completed` 与 `run_question`，执行失败与中断恢复没有用户可见通知。任务详情与工作台只显示失败文案，既不能一键重新委派，也不展示失败尝试与具名 Run 的绑定。

## 决策

议题维度在 Web 补齐：新增只读 `GET /projects/{id}/work/topics` 返回议题及已固化缩写，`ProjectWorkTasksView` 读取它提供议题选择与议题编号配置入口，创建任务时传 `topic_id`；编号仍由后端在项目缩写行锁内分配，`GEN` 继续保留给无议题任务。议题缩写冲突与缺失返回可展示的业务错误码。

收件箱 `user_inbox_items.kind` 扩展 `task_failed` 与 `task_interrupted`，以幂等 `DROP/ADD` 迁移收敛 CHECK 并升 `YUANLEI_SCHEMA_VERSION` 到 19，保留既有通知行。执行尝试进入失败或中断状态时，在 owning transaction 内调用 `UserInboxRepository.add_once` 写入通知，`source_id` 使用任务 ID，同一任务同一类通知只写一次；收件箱 UI 按种类展示并跳转到对应任务。

任务详情与数字员工工作台展示失败尝试的 Run 标识与错误，并为失败或已取消的尝试提供显式“重新执行”。重新执行复用 `POST .../executions` 创建新的执行意图，产生新的请求与 Run，旧尝试与旧 Run 保留可追踪；不自动重跑同一命令。

## 替代方案

- 让收件箱直接保存执行尝试 ID 作为来源：跳转需要任务 ID，而通知表没有该列；改用任务 ID 作为 `source_id`，与 `task_completed` 一致，并接受同一任务同类通知只提醒一次。
- 为重新执行增加专用后端端点：`assign_task` 在无活跃尝试时已能创建新执行意图，专用端点只重复校验，不增加业务语义。
- 用乐观 UI 直接改写失败尝试状态：执行状态由 PostgreSQL 与 Run 生命周期拥有，前端只回读。

## 后果

存量 v18 库升级后既有通知保留，新词表可写；旧任务编号和 `topic_id` 语义不变。失败与中断通知对同一任务同类只出现一次，更细的多次失败仍可在任务详情按尝试追踪。重新执行不改变任务的“第一负责人”，只新增执行尝试。

## 验证

- 真实 PostgreSQL 迁移测试 `test_yuanlei_v18_to_v19_extends_inbox_kinds_idempotently` 验证旧词表拒绝新种类、升级后可写且重复升级保留通知。
- 真实 PostgreSQL service 集成测试验证议题列表与缩写的项目归属，以及失败、中断通知的幂等写入。
- 真实 HTTP 集成测试 `test_project_work_http_lifecycle_and_cross_project_guards` 验证议题列表、缩写固化、`topic_code_required` 与按议题编号；本工作树环境下该文件未对运行中容器执行，命令与未验证范围以交付记录为准。
- Web unit 覆盖议题选择与缩写保存、失败尝试重新执行、收件箱失败/中断跳转；lint、unit、build 通过。
