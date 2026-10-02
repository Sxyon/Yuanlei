# 项目任务重执行集成覆盖与收件箱通知追加

状态：implemented
类型：feature
Owner：backend/package/yuxi/repositories/user_inbox_repository.py
关联 Feature：[独立项目工作任务与 Issue](../../features/project-work-tasks.md)、[用户收件箱](../../features/user-inbox.md)

## 问题

YL-25 的 P0 整改合入后，独立审查（YL-29）提出三条非阻塞收口项。重新执行只有代码路径审查，缺少「失败或已取消尝试显式重新执行会创建新执行意图、旧尝试与旧 Run 保留」的真实 HTTP 与 PostgreSQL 专门用例。失败与中断通知以任务 ID 为 `source_id`，同一来源只写一次，再次失败时收件箱没有任何变化。通知写入先 SELECT 再 INSERT，在并发窗口内会以 `IntegrityError` 使事务失败重试。

产品确认（2026-10-02）：按来源去重的维度没有问题；问题是再次发生变动时用户必须能感知到。同一来源共用一条通知，通知内部保留同一 `source_id` 的发生过程。

## 决策

补一条真实 HTTP + PostgreSQL 专门集成用例，直接访问运行中的 API 并回读数据库：先让一个执行尝试失败并绑定旧 Run，再通过 `POST /projects/{id}/work/tasks/{task_id}/executions` 重新执行，断言新尝试的 `id`、`request_id`、`thread_id` 都与旧尝试不同，旧失败的 `status`、`error_message`、`request_id` 与旧 Run 保留；随后撤回该活跃尝试并再次重新执行，重复同一断言，覆盖已取消分支。

`UserInboxRepository.add_once` 改为 `record_occurrence`，语义从「幂等写入一次」变为「记录一次来源发生」。写入仍以 `(uid, kind, source_id)` 唯一键共用一行：首次写入 `INSERT ... ON CONFLICT DO NOTHING RETURNING`，`occurrences` 初始化为本次 `{at, summary}`；命中唯一键时在同一行锁下追加本次发生，`title` 与 `summary` 更新为最新一次，`read_at` 与 `archived_at` 清空回到未读未归档，`created_at` 前移到本次发生时间，使通知重新排到列表顶部并让接收者感知到变化。

`user_inbox_items` 新增 `occurrences JSONB NOT NULL DEFAULT '[]'`，yuanlei schema 升到 v21，迁移语句幂等，存量行以空数组补齐。`storage_migration` 为 v20 存量库新增一条只执行 v20→v21 的分支，避免跳过整个升级链。收件箱 HTTP 响应项新增 `occurrences`，Web 收件箱在发生过程多于一条时按时间列出。

## 替代方案

- 以 `execution_id` 或 Run ID 作为通知 `source_id`：每次失败尝试各自成行，无法在同一通知内看到同一来源的历史发生过程，与「同一来源共用一条通知」的产品确认不符。
- 保留 `add_once` 只回读既有行：再次发生不追加、不重置已读，用户看不到变化，正是产品指出的问题。
- 新增 `last_occurred_at` 列再排序：需要新建列、索引并调整分页游标；直接前移 `created_at` 复用现有排序，以最小改动满足「让接收者感知到变化」。
- 为重新执行新增专用端点：`assign_task` 在没有活跃尝试时已能创建新执行意图，专用端点只重复校验，不增加业务语义。

## 后果

同一任务同一类通知保持单行，但每次发生都会追加时间与摘要、刷新标题摘要并要求重新阅读，收件箱上表现为该来源重新变为未读并置顶。唯一约束 `uq_user_inbox_items_source` 仍是复用行的依据，并发写入在行锁上串行，不再抛 `IntegrityError`。`occurrences` 随发生次数增长，当前发生频率低，未设上限。重新执行的请求、线程与旧尝试保留由专门用例锁定；新 Run 的实际产生与 worker 收敛仍由 E2E 覆盖。

## 验证

- 实执行命令：容器内 `pytest test/integration/services/test_user_inbox_repository.py -q`，真实 PostgreSQL，`2 passed`；覆盖同一来源追加发生过程、不同 `kind`/`source_id` 各自成行、再次发生回到未读与取消归档、以及首个事务未提交时第二个写入等待行锁后追加。
- 实执行命令：容器内 `pytest test/integration/services/test_schema_migration_version.py -k v20_to_v21 -q`，`1 passed`；存量 v20 行迁移后保留且 `occurrences` 补齐为空数组，迁移可重复执行。
- 实执行命令：容器内 `pytest test/unit/services/test_storage_migration.py -q`，`19 passed`；v1..v5 升级链包含 v20→v21，新增 v20 存量库只执行 v20→v21 的用例。
- 实执行命令：容器内 `pytest test/unit -m "not slow" -q`，`2639 passed, 61 skipped`；仅 `test_context_backend_construction_does_not_sync_skill_projection` 因临时容器 skill 目录不可写失败，属运行环境所致，与本变更无关。
- 实执行命令：容器内 `pytest test/integration/api/test_project_work_api.py -k reexecution -q`，`1 passed`。同文件既有 `test_project_work_http_lifecycle_and_cross_project_guards` 因基线夹具缺 `created_at` 默认值失败，属 YL-33 跟踪的既有缺陷，与本用例无关。
- `python3 scripts/verify_engineering_contracts.py` 与 `python3 -m unittest scripts.test_verify_engineering_contracts` 通过；`ruff check` 对修改文件通过；`git diff --check` 干净。
- 未验证范围：文档站 `pnpm run build` 未运行（工作树无 docs `node_modules`）；worker 级 E2E（失败或中断再次发生追加通知、重新执行绑定新 Run 的真实 worker 消费）需要确定性 replay 服务与 worker，本环境未运行，由既有 E2E 归属跟踪。
