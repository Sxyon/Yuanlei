# 项目任务重执行集成覆盖与收件箱通知幂等写入

状态：implemented
类型：testing
Owner：backend/package/yuxi/repositories/user_inbox_repository.py
关联 Feature：[独立项目工作任务与 Issue](../../features/project-work-tasks.md)、[用户收件箱](../../features/user-inbox.md)

## 问题

YL-25 的 P0 整改合入后，独立审查（YL-29）提出三条非阻塞收口项。重新执行只有代码路径审查，缺少「失败或已取消尝试显式重新执行会创建新执行意图、旧尝试与旧 Run 保留」的真实 HTTP 与 PostgreSQL 专门用例。失败与中断通知是否应为每次失败尝试重复提醒，`source_id` 的去重维度未与产品确认。通知幂等写入先 SELECT 再 INSERT，没有使用唯一键的 `ON CONFLICT`，在并发窗口内会以 `IntegrityError` 使事务失败重试。

## 决策

补一条真实 HTTP + PostgreSQL 专门集成用例，直接访问运行中的 API 并回读数据库：先让一个执行尝试失败并绑定旧 Run，再通过 `POST /projects/{id}/work/tasks/{task_id}/executions` 重新执行，断言新尝试的 `id`、`request_id`、`thread_id` 都与旧尝试不同，旧失败的 `status`、`error_message`、`request_id` 与旧 Run 保留；随后撤回该活跃尝试并再次重新执行，重复同一断言，覆盖已取消分支。

`UserInboxRepository.add_once` 改为 `INSERT ... ON CONFLICT (uid, kind, source_id) DO NOTHING RETURNING`，命中唯一键时回读既有行返回。唯一约束 `uq_user_inbox_items_source` 拥有幂等事实，写入语义与仓库既有 `ON CONFLICT` 幂等写法一致，不再依赖调用方的执行行锁。

失败与中断通知的 `source_id` 维持任务 ID：同一任务同一类通知只写一次，与 `task_completed` 的来源语义一致，也是当前需求「同一来源仅一次」的字面实现。是否为每次失败尝试重复提醒属于产品取舍，作为待确认问题保留，未确认前不改写来源语义。

## 替代方案

- 以 `execution_id` 或 Run ID 作为通知 `source_id`：每次失败尝试都会提醒，但收件箱跳转需要任务 ID，且与既有任务类通知来源不一致；若产品确认需要按尝试提醒，再单独立项并补充导航列。
- 保留 SELECT-then-INSERT：功能等价，但并发窗口内依赖执行行锁串行化，冲突时以 `IntegrityError` 事务失败重试；使用唯一键 `ON CONFLICT` 更直接。
- 为重新执行新增专用端点：`assign_task` 在没有活跃尝试时已能创建新执行意图，专用端点只重复校验，不增加业务语义。

## 后果

通知幂等由数据库唯一约束保证，重复写入返回既有行且不再抛 `IntegrityError`，用户可见行为不变。重新执行的请求、线程与旧尝试保留由专门用例锁定；新 Run 的实际产生与 worker 收敛仍由 E2E 覆盖。`source_id` 去重维度仍为任务级，产品确认若改为尝试级会产生更多通知行，需要相应迁移判断。

## 验证

- 实执行命令：容器内 `pytest test/integration/api/test_project_work_api.py -k reexecution -q`，对新分支 API（真实 HTTP）与真实 PostgreSQL，`1 passed`。同文件既有 `test_project_work_http_lifecycle_and_cross_project_guards` 因基线夹具缺 `created_at` 默认值失败，属 YL-33 跟踪的既有缺陷，与本用例无关。
- 实执行命令：容器内 `pytest test/integration/services/test_user_inbox_repository.py test/integration/services/test_project_work_service.py test/integration/services/test_project_work_execution_service.py -q`，`3 passed`。其中执行队列用例覆盖失败、中断通知多次收敛后计数为 1。
- 实执行命令：容器内 `pytest test/unit -m "not slow" -q`，`2725 passed, 61 skipped`，另有 1 项 `test_context_backend_construction_does_not_sync_skill_projection` 因临时运行目录只读失败，设可写 skill 目录后单独通过，与本变更无关。
- `python3 scripts/verify_engineering_contracts.py` 通过；`ruff check` 对修改后的 `user_inbox_repository.py` 通过。
- 未验证范围：文档站 `pnpm run build` 未运行（工作树无 docs `node_modules`）；worker 级 E2E（失败或中断各产生一次通知、重新执行绑定新 Run 的真实 worker 消费）需要确定性 replay 服务与 worker，本环境未运行，由既有 E2E 归属跟踪。
