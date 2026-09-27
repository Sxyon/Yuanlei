# 用户收件箱的持久通知

状态：implemented
类型：feature
Owner：backend/package/yuxi/repositories/user_inbox_repository.py
关联 Feature：[用户收件箱](../../features/user-inbox.md)

## 问题

用户离开对话或项目页面后，任务完成和等待答复的中断缺少统一、持久的待处理入口。只依赖 Redis 事件或前端在线状态会漏掉离线期间的变化。

## 决策

在 yuanlei schema v14 保存按用户隔离的通知；任务首次进入 `done` 时通知创建者，顶层 AgentRun 因提问或审批进入 `interrupted` 时通知 Run 所属用户。通知与来源状态在同一 PostgreSQL 事务内写入，并以接收者、类型、来源 ID 唯一约束去重。已读和归档分别保存时间，归档不会修改来源任务或 Run。收件箱通过权限受控 HTTP 查询，提供未读、已读与归档分类；基于通知 ID 的游标分页避免分类成员变化时跳过旧通知，页面可进入任务详情或原始对话。

## 替代方案

- 从任务和 Run 状态临时汇总：不能记录用户已读或归档，也无法可靠区分旧中断与本次待答复事件。
- 在 Redis Stream 中保存通知：事件可能过期，无法成为离线用户的持久收件箱。
- 由前端看到终态后写通知：离线时漏记，重连时重复写入。

## 后果

通知保存来源摘要快照，来源删除或权限变化后页面会通过原始接口显示不可访问；收件箱不会赋予对原始任务或 Run 的额外权限。当前任务完成指工作任务状态由非 `done` 进入 `done`，不声称智能体执行已结束。重新打开再完成同一任务不会产生第二条通知。一般 Run 完成、失败和取消尚未进入收件箱；接入任务执行后再定义执行完成与任务完成的关系。

## 验证

- v13→v14 隔离 PostgreSQL 迁移可重入，旧通知保留；`test_schema_migration_version.py -k v13_to_v14`。
- 真实 HTTP 创建任务并改为完成后，回读 PostgreSQL 通知，验证跨用户修改 404、已读与归档分类及分类变化后的游标翻页；`test_project_work_api.py`。
- 真实 PostgreSQL 的 Run 中断与消息同事务提交后回读通知；`test_agent_run_lease.py -k interrupt_message_and_run_terminal_commit_together`。
- 后端非慢速 unit 2722 passed、61 skipped；`uv run --group test` 因容器 editable 文件权限错误未启动，直接调用容器内 pytest 通过。Web lint 与 build 通过；收件箱分类和任务详情切换竞态 unit 通过。全量 Web unit 在既有 `defaultProjectDashboard.test.js` 两项缺少 active Pinia 的失败处结束，独立重跑仍失败。浏览器已核对收件箱空状态及任务详情 404 状态，含通知列表的真实页面仍未核对。
- `test_deterministic_agent_path_e2e.py -k resume_with_offloaded_tool_result_publishes_stream_owned_audit` 已尝试；缺少 E2E_USERNAME/E2E_PASSWORD 或 TEST_USERNAME/TEST_PASSWORD 而 skip，未形成 worker E2E 证据。
