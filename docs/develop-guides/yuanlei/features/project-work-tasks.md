# 独立项目工作任务与 Issue

状态：任务底座、页面管理、智能体执行队列与网页引用已接入；文件附件和自动巡检尚未实现
类型：有意产品差异
主要 Owner：`backend/package/yuxi/services/project_work_service.py`

## 需求与失败场景

项目需要长期工作对象与任务下的问题单，支持子任务、第一负责人和按议题归档的稳定编号。现有 `governance_tasks` 只负责来源审核，`AgentRunRequest` 只负责一次请求排队；把执行过程放进任一状态模型都会混淆审核、排队和长期责任。用户需要以后由不同智能体依次执行同一任务，并从评论区核对结论与产物。

## 必须保留的业务语义

- 工作任务在 `yuanlei` 域独立持久化，与治理任务、Durable Task 和 AgentRunRequest 分离。当前任务状态为 `todo`、`in_progress`、`blocked`、`done`、`cancelled`，不表达 Run 终态。
- 项目缩写全局唯一，议题缩写在所属项目唯一。两种缩写首次配置后固化；项目内行锁串行分配序号，历史编号不随标题或配置变化。`GEN` 保留给无议题任务，不能配置为议题缩写。当前 API 要求在建任务前配置项目缩写；关联议题时要求先配置议题缩写。
- 子任务、Issue、评论与任务均通过后端 service 和 repository 检查当前用户的 active selectable Project 归属。组合外键阻止跨项目议题缩写、任务议题和父任务关联。Issue 必须在当前任务下。任务和 Issue 评论仅追加，保存作者 UID、显示名快照与时间。
- 第一负责人当前可设置或转移到项目已绑定数字员工，也可为空；解绑或直接删除仍负责任务的数字员工会被拒绝，须先转移或清空责任。这个字段不等同于当前执行者。周期核查尚未接入，界面和外部消费者不能将设置负责人解释为已经启用自动巡检。
- 执行尝试与任务状态分离。任务可依次交给不同智能体，但同一任务只能有一个待接受、排队或执行中的尝试；同一智能体只能有一个派发、执行或等待答复中的尝试。待接受任务不进入执行队列，接受后按创建时间 FIFO 派发。中断保留执行槽位直到原 Run 的恢复链结束。
- 待接受或仍在队列中的分配可撤回并释放任务槽位；派发开始后须由对应 Run 的生命周期结束。终态评论仅引用本次执行初始 Request 所产生的 Run 或其合法恢复后代；完成但无对应输出时执行尝试显式失败。
- 项目数字员工绑定拥有独立的任务自动接受开关与默认工作模型。关闭自动接受是默认值；开启后新分配在同一事务进入队列。手动接受和自动接受均在接受事务中固化当前可用聊天模型，后续配置变化不改写旧尝试。模型留空时先继承项目有效 Agent 模型，再继承系统默认模型。
- 任务网页引用独立保存标题、HTTP(S) URL、添加人和时间；当前项目用户可添加与移除。服务器不抓取目标网页。文件附件仍未实现，不能把网页引用当作文件副本。

## 与 Yuxi 的边界

上游继续拥有 Project、Agent、Conversation、AgentRun、聊天 FIFO 和 Durable Task。工作任务不改变其表或状态机；任务与 Issue 表、编号配置和评论表由 yuanlei schema v13 拥有。既有治理任务和来源审核流程不迁移、不改变。

## 稳定集成点

- `project_work_service.py` 负责权限、编号分配、父子关系、负责人绑定与评论边界。
- `project_work_repository.py` 负责 PostgreSQL 读写；`project_work_router.py` 提供 `/projects/{id}/work/*`。
- `project_work_execution_service.py` 与 repository 拥有分配、接受、队列认领和 Run 结果收敛；Run 仍由上游 Request/Run 链路执行。
- `storage/postgres/models_business.py` 与 `manager.py` 拥有表结构和 yuanlei 域幂等迁移。
- 项目任务接收配置属于 yuanlei schema v15→v16 的 `project_agents` 绑定列；工作台读写入口属于 `project_work_execution_router.py`。

## 上游依赖

依赖 `projects`、`governance_topics` 与项目数字员工绑定；项目软删除后读写被拒，历史行保留。将来的执行尝试会引用上游 AgentRun，但 Run 状态仍由上游拥有。

## 合并判断

上游若新增项目级任务，应比较稳定编号、任务下独立 Issue、第一负责人、项目范围权限与跨智能体顺序执行。只提供聊天队列或运行记录并不等价。

## 替换或删除条件

上游任务能力覆盖业务不变量并提供既有 yuanlei 数据迁移后，可采用上游结构。需求过期或对象关系改变时，需要新 Decision 说明数据和消费侧后果。

## 决策与证据

- [项目工作任务第一阶段](../decisions/implemented/2026-09-27-project-work-task-foundation.md)
- [项目工作任务页面入口](../decisions/implemented/2026-09-28-project-work-task-interface.md)
- [项目任务执行队列](../decisions/implemented/2026-09-28-project-work-execution-queue.md)
- [项目数字员工任务队列配置](../decisions/implemented/2026-09-28-project-agent-work-queue-config.md)
- [项目任务网页引用](../decisions/implemented/2026-09-28-project-work-web-references.md)
- [后续工作提案](../decisions/proposed/2026-09-27-agent-workbench-inbox-project-work.md)
- 真实 PostgreSQL：`backend/test/integration/services/test_project_work_service.py` 与 `test_schema_migration_version.py`。
- 真实 HTTP：`backend/test/integration/api/test_project_work_api.py`。
