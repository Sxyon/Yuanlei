# 用户收件箱

状态：已接入任务完成、Run 待答复与项目任务失败/中断通知；含通知列表的真实页面与 worker E2E 证据待补
类型：有意产品差异
主要 Owner：`backend/package/yuxi/repositories/user_inbox_repository.py`

## 需求与失败场景

用户需要在同一入口处理离线期间完成的项目任务和智能体等待答复的中断，并把通知分为未读、已读与归档。依赖 Run SSE 或在线页面会漏记离线变化；只展示来源当前状态无法保存阅读与归档选择。

## 必须保留的业务语义

- 通知、已读与归档由 PostgreSQL 持久化；接收者只能读写自己的通知。来源详情仍经过原任务或 Run 的权限检查。
- 项目工作任务首次进入 `done` 通知创建者；顶层 AgentRun 因提问或审批中断通知其用户。通知与来源状态同事务提交，重复状态转换不新增通知。
- 项目任务执行尝试进入失败或中断时通知尝试所属用户，种类为 `task_failed` 与 `task_interrupted`，来源取任务 ID。同一任务同一类通知只写一次；失败或中断通知与执行状态同事务提交。收件箱按种类区分展示，任务类通知跳转到对应任务页面，Run 待答复仍进入原执行会话。
- 已读和归档相互独立；归档不代表任务完成、问题已回答或审批已通过。答复仍使用原 Run resume 链路。

## 与 Yuxi 的边界

AgentRun 继续拥有运行状态、输出、interrupt checkpoint 和 resume；收件箱只记录用户可处理的通知。项目任务属于 yuanlei 独立工作对象。通知表属于 yuanlei 域，通知种类词表在 schema v14 建立、v18→v19 扩展失败与中断种类。

## 稳定集成点

`user_inbox_repository.py` 拥有接收者查询和写入去重，Run 终态和项目任务状态事务调用它；`user_inbox_router.py` 提供当前用户 HTTP 入口，Web 收件箱展示与操作通知。

## 上游依赖

依赖 AgentRun 终态在 repository 中统一收敛，以及项目工作任务的状态服务。若上游调整 Run 终态入口，需要保留中断通知与来源状态同事务的语义。

## 合并判断

上游若有同等持久收件箱，应核对离线可靠性、来源归属、提问/审批中断识别、已读归档和用户权限后再替换。

## 替换或删除条件

上游能力覆盖业务不变量并提供通知数据迁移后可采用上游结构；如果用户不再需要收件箱，须先处理存量通知及来源入口。

## 决策与证据

- [持久通知决定](../decisions/implemented/2026-09-27-user-inbox.md)
- [议题缩写全链路、执行通知与重新执行](../decisions/implemented/2026-09-29-project-work-topic-inbox-retry-remediation.md)
- [项目任务重执行集成覆盖与收件箱通知幂等写入](../decisions/implemented/2026-10-02-project-work-reexecution-test-and-inbox-idempotency.md)
- [整体后续提案](../decisions/proposed/2026-09-27-agent-workbench-inbox-project-work.md)
- 真实 PostgreSQL 与 HTTP：`backend/test/integration/services/test_schema_migration_version.py`、`test_agent_run_lease.py`、`backend/test/integration/api/test_project_work_api.py`。
