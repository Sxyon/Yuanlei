# 项目任务文件附件与第一负责人周期巡检

状态：implemented
类型：feature
Owner：backend/package/yuxi/services/project_work_service.py
关联 Feature：[独立项目工作任务与 Issue](../../features/project-work-tasks.md)、[用户收件箱](../../features/user-inbox.md)

## 问题

原始需求要求任务具备「附件」，并要求第一负责人「定时检查任务状态」。当时的项目任务只有网页引用（`project_work_references`），没有文件附件表、上传下载入口和对象存储边界；`primary_owner_agent_slug` 只有字段与转移，没有持久调度、周期核查、重复 tick 防护和 worker 崩溃恢复，界面和外部消费者不能把设置负责人解释为已启用自动巡检。

## 决策

任务文件附件使用 yuanlei 域元数据 + 既有对象存储内容。新增 `project_work_attachments` 保存项目、任务、文件名、内容类型、大小与对象名，内容写入现有 `documents` bucket，对象名按 `project_work/{project_id}/{task_id}/{attachment_id}/{file_name}` 组织。上传、下载、删除由 `project_work_router` 暴露，权限在 `ProjectWorkRepository` 的 active selectable Project 可见性查询处 fail-closed；文件名去目录化，扩展名在允许清单内，大小上限 5 MB 在真实 HTTP 边界校验。删除先提交元数据再尽力删除对象，上传写库失败回滚元数据并清理对象。

第一负责人周期巡检使用持久运行事实与 worker 收敛。`project_work_tasks` 增加 `inspection_enabled`、`inspection_interval_minutes`、`inspection_next_run_at`，`project_work_inspection_runs` 以 `(task_id, occurrence_key)` 唯一约束表达一次到期检查，`occurrence_key` 取计划到期时刻。worker 启动与每轮收敛调用 `recover_stale_inspections` 和 `run_project_work_inspection_tick`：认领到期任务时对任务行 `FOR UPDATE SKIP LOCKED`，在同一事务内推进 `next_run_at` 并登记 claimed 运行，事务提交后再在独立事务内执行核查并落库结论；重复 tick 因计划已推进且 occurrence 唯一而不重复产出；崩溃遗留的 claimed 运行由恢复流程重新收敛。

核查只读任务事实，不把任务状态当作 Run。`in_progress` 在没有待接受、排队或运行中执行尝试时记为异常；`blocked` 与已过计划结束日期分别记为异常。异常结论与上一次完成结论不同时，以第一负责人显示名追加任务评论并写一条 `task_inspection` 收件箱通知（`source_id` 取该次运行 ID，幂等），巡检本身不创建 `AgentRun`。

新增持久化进入 `yuanlei` schema 并升 `YUANLEI_SCHEMA_VERSION` 到 20；`user_inbox_items.kind` 词表以幂等 `DROP/ADD` 收敛加入 `task_inspection`。

## 替代方案

- 把附件写入任务所属的数字员工沙盒目录：沙盒是执行期临时工作区、会随运行回收，不满足任务长期产物的持久与用户下载边界；对象存储已经是仓库文档内容的 Owner，直接复用。
- 复用 `project_work_references`：引用只保存 HTTP(S) URL 且服务器不抓取目标内容，不能承载文件字节、大小和内容类型校验。
- 为巡检引入独立调度框架或 cron 表：现有 worker 收敛循环已经承担 lease、恢复与幂等语义，新增框架会引入第二套调度真相。
- 用 `in_progress` 直接表示“任务正在被 Agent 执行”：任务状态和 Run 终态是不同状态模型，巡检改为查询 `project_work_executions` / `AgentRun` 事实判断是否有活跃尝试。

## 后果

存量 v19 库升级后既有数据保留，新增表与列可写；附件对象与元数据分离，元数据删除后对象仍可能短暂存在（删除失败只记录不回滚）。巡检对同一异常只在结论变化时提醒一次，异常持续期间不重复打扰；恢复的巡检按运行 ID 幂等，不会重复产出评论或通知。巡检不改变任务状态、不创建 Run，也不改写第一负责人。

## 验证

- 真实 HTTP + PostgreSQL：`backend/test/integration/api/test_project_work_attachments_api.py` 覆盖上传、下载回读、删除、非法类型、超大文件、跨项目与外部用户越权，并回读 `project_work_attachments` 行。
- 真实 PostgreSQL：`backend/test/integration/services/test_project_work_inspection_service.py` 覆盖重复 tick 幂等、worker 崩溃遗留 claimed 运行恢复、结论变化才产出、只写评论与收件箱而不创建 `project_work_executions`/`agent_runs`。
- Web unit：`web/test/unit/projectWorkTaskView.test.js` 覆盖附件上传成功后回读与失败错误展示、巡检配置保存与失败错误展示；`lint:check` 通过。
- 迁移单元：`backend/test/unit/services/test_storage_migration.py` 与 `test_run_worker.py` 显式更新为 v19→v20 升级链与 worker 启动收敛顺序。
