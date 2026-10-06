# 独立项目工作任务与 Issue

状态：任务底座、页面管理、智能体执行队列、网页引用、文件附件、议题缩写配置、第一负责人周期巡检与失败后重新执行已接入
类型：有意产品差异
主要 Owner：`backend/package/yuxi/services/project_work_service.py`

## 需求与失败场景

项目需要长期工作对象与任务下的问题单，支持子任务、第一负责人和按议题归档的稳定编号。现有 `governance_tasks` 只负责来源审核，`AgentRunRequest` 只负责一次请求排队；把执行过程放进任一状态模型都会混淆审核、排队和长期责任。用户需要以后由不同智能体依次执行同一任务，并从评论区核对结论与产物。

## 必须保留的业务语义

- 工作任务在 `yuanlei` 域独立持久化，与治理任务、Durable Task 和 AgentRunRequest 分离。当前任务状态为 `todo`、`in_progress`、`blocked`、`done`、`cancelled`，不表达 Run 终态。
- 项目缩写全局唯一，议题缩写在所属项目唯一。两种缩写首次配置后固化；项目内行锁串行分配序号，历史编号不随标题或配置变化。`GEN` 保留给无议题任务，不能配置为议题缩写。当前 API 要求在建任务前配置项目缩写；关联议题时要求先配置议题缩写。任务页面通过只读议题列表读取议题与已固化缩写，提供议题缩写配置入口并允许建任务时选择议题。
- 子任务、Issue、评论与任务均通过后端 service 和 repository 检查当前用户的 active selectable Project 归属。组合外键阻止跨项目议题缩写、任务议题和父任务关联。Issue 必须在当前任务下。任务和 Issue 评论仅追加，保存作者 UID、显示名快照与时间。
- 第一负责人可设置或转移到项目已绑定数字员工，也可为空；解绑或直接删除仍负责任务的数字员工会被拒绝，须先转移或清空责任。这个字段不等同于当前执行者。周期巡检默认关闭，开启前须先设置第一负责人与巡检周期，清空负责人会同时关闭巡检。worker 启动与每轮收敛认领到期任务，在行锁内推进下次运行时刻并登记一次巡检运行；重复 tick 因计划已推进且 `(task_id, occurrence_key)` 唯一而不重复产出，崩溃遗留的待处理运行由恢复流程重新收敛。巡检只读任务事实并按第一负责人署名追加评论和收件箱通知，不改变任务状态、不创建 `AgentRun`；`in_progress` 在无待接受、排队或运行中执行尝试时记为异常，`blocked` 与已过计划结束日期分别记为异常，只在结论相对上一次完成结论变化时提醒一次。
- 计划开始和结束日期可为空；两者都有值时结束日期不得早于开始日期。计划日期属于任务事实，与 AgentRun 的开始、结束时间分开。任务看板、列表和按月甘特图读取同一项目任务 API；看板状态修改及甘特图计划修改由后端保存后回读。
- 执行尝试与任务状态分离。任务可依次交给不同智能体，但同一任务只能有一个待接受、排队或执行中的尝试；同一智能体只能有一个派发、执行或等待答复中的尝试。待接受任务不进入执行队列，接受后按创建时间 FIFO 派发。中断保留执行槽位直到原 Run 的恢复链结束。
- 待接受或仍在队列中的分配可撤回并释放任务槽位；派发开始后须由对应 Run 的生命周期结束。终态评论仅引用本次执行初始 Request 所产生的 Run 或其合法恢复后代；完成但无对应输出时执行尝试显式失败。
- 任务详情与数字员工工作台展示每次尝试的状态、关联 Run 与错误。失败或已取消的尝试提供“重新执行”，它在无活跃尝试时创建新的执行意图，产生新的 Request 与 Run，旧尝试与旧 Run 保留；不自动重跑同一命令，也不改写任务的第一负责人。
- 项目数字员工绑定拥有独立的任务自动接受开关与默认工作模型。关闭自动接受是默认值；开启后新分配在同一事务进入队列。手动接受和自动接受均在接受事务中固化当前可用聊天模型，后续配置变化不改写旧尝试。模型留空时先继承项目有效 Agent 模型，再继承系统默认模型。
- 任务网页引用独立保存标题、HTTP(S) URL、添加人和时间；当前项目用户可添加与移除。服务器不抓取目标网页，网页引用不承载文件字节。
- 文件附件以 yuanlei 域元数据引用既有对象存储内容：保存项目、任务、文件名、内容类型、大小与对象名，内容写入 `documents` bucket。当前项目用户可上传、下载与删除；文件名去目录化，扩展名须在允许清单内，大小上限 5 MB，均在真实 HTTP 边界校验。权限在 repository 可见性查询处 fail-closed，跨项目与外部用户不可读。删除先提交元数据再尽力删除对象，上传写库失败回滚元数据并清理对象。

- 正式工作可选关联同项目已批准主要来源决策及批准修订号，议题和决策均可为空。同时给议题时与决策来源一致；归档议题拒绝新引用。需复核补充要求个人明确确认；已替代或撤销只显示历史和提示，不自动停工或重定向。来源调整保留编号，原来源校验拒绝竞争覆盖。
- 分配时固化当次议题和决策修订定位，Request 与 Run 读取该尝试定位；工作当前来源修改不改变旧 prompt、尝试或请求输入。当前引用与历史执行定位均参与删除保护，项目锁先于议题、决策与工作对象。v29→v30 的旧工作和尝试保持空关联，不推断历史。

- 工作建议可新建或关联同项目正式工作，一项建议最多一个映射，一项工作可以承接多个建议。相同纳入重试返回已有映射，变更目标或模式返回冲突；审核、编号、创建和映射由一个事务提交。关联已有工作保留标题、负责人、状态、编号与主要来源，详情保留各建议来源链接。旧已审核建议可补充关联，旧执行不推断归属。
- 新编码与外部委派从正式工作发起，保存工作和当次来源修订。工作当前来源变化不改旧委派输入，委派终态不自动改工作状态或标记成果验收。

- 工作要求保存 Markdown 验收条件与修订号；人工结果追加保存摘要、证据、未解决事项和提交时条件快照，不生成 AgentRun。结果验收与工作完成分开，已处置结果不覆盖；完成只采用当前修订的已接受结果，条件变化不改旧快照。旧 done 不推断历史验收依据。
- 所有完成入口在后端检查智能体尝试、编码及外部委派活跃事实，证据可访问性与 Git 成果处理保留原边界；结果、完成与通知同事务，幂等请求与跨工作来源由数据库约束保护。URL 只作引用，不能宣称已读取验证。

## 与 Yuxi 的边界

上游继续拥有 Project、Agent、Conversation、AgentRun、聊天 FIFO 和 Durable Task。工作任务不改变其表或状态机；任务与 Issue 表、编号配置和评论表由 yuanlei schema v13 拥有。治理任务作为工作建议，经纳入接口在一个事务中审核并创建或关联正式工作；旧行不批量迁移。

## 稳定集成点

- `project_work_service.py` 负责权限、编号分配、父子关系、负责人绑定与评论边界。
- `project_work_repository.py` 负责 PostgreSQL 读写；`project_work_router.py` 提供 `/projects/{id}/work/*`。
- `project_work_execution_service.py` 与 repository 拥有分配、接受、队列认领和 Run 结果收敛；Run 仍由上游 Request/Run 链路执行。
- `storage/postgres/models_business.py` 与 `manager.py` 拥有表结构和 yuanlei 域幂等迁移。
- 项目任务接收配置属于 yuanlei schema v15→v16 的 `project_agents` 绑定列；工作台读写入口属于 `project_work_execution_router.py`。
- 议题列表与缩写入口属于 `project_work_service.list_topics` 与 `/projects/{id}/work/topics*`；收件箱词表扩展属于 yuanlei schema v18→v19。
- 任务文件附件元数据、附件 HTTP 入口与对象存储读写属于 `project_work_attachments`、`project_work_service` 与 `/projects/{id}/work/tasks/{id}/attachments*`；`project_work_inspection_service`、`ProjectWorkInspectionRepository` 与 worker 收敛循环拥有周期巡检的认领、核查、产出与恢复。两者属于 yuanlei schema v19→v20。

## 上游依赖

依赖 `projects`、`governance_topics` 与项目数字员工绑定；项目软删除后读写被拒，历史行保留。将来的执行尝试会引用上游 AgentRun，但 Run 状态仍由上游拥有。

## 合并判断

上游若新增项目级任务，应比较稳定编号、任务下独立 Issue、第一负责人、项目范围权限与跨智能体顺序执行。只提供聊天队列或运行记录并不等价。

## 替换或删除条件

上游任务能力覆盖业务不变量并提供既有 yuanlei 数据迁移后，可采用上游结构。需求过期或对象关系改变时，需要新 Decision 说明数据和消费侧后果。

## 决策与证据

- [正式工作验收条件与人工结果](../decisions/implemented/2026-10-06-work-results-acceptance.md)

- [工作建议纳入正式工作与执行归属](../decisions/implemented/2026-10-05-work-suggestion-admission.md)

- [正式工作来源与执行依据定位](../decisions/implemented/2026-10-05-work-decision-source.md)
- [项目工作任务第一阶段](../decisions/implemented/2026-09-27-project-work-task-foundation.md)
- [项目工作任务页面入口](../decisions/implemented/2026-09-28-project-work-task-interface.md)
- [项目任务执行队列](../decisions/implemented/2026-09-28-project-work-execution-queue.md)
- [项目数字员工任务队列配置](../decisions/implemented/2026-09-28-project-agent-work-queue-config.md)
- [项目任务网页引用](../decisions/implemented/2026-09-28-project-work-web-references.md)
- [任务管理视图与委派反馈](../decisions/implemented/2026-09-28-project-task-management-views.md)
- [议题缩写全链路、执行通知与重新执行](../decisions/implemented/2026-09-29-project-work-topic-inbox-retry-remediation.md)
- [项目任务文件附件与第一负责人周期巡检](../decisions/implemented/2026-09-30-project-work-attachments-and-inspection.md)
- [项目任务重执行集成覆盖与收件箱通知幂等写入](../decisions/implemented/2026-10-02-project-work-reexecution-test-and-inbox-idempotency.md)
- [后续工作提案](../decisions/proposed/2026-09-27-agent-workbench-inbox-project-work.md)
- 真实 PostgreSQL：`backend/test/integration/services/test_project_work_service.py` 与 `test_schema_migration_version.py`。
- 真实 PostgreSQL 附件边界：`backend/test/integration/api/test_project_work_attachments_api.py` 覆盖上传、下载回读、删除、非法类型、超大文件、跨项目与外部用户越权。
- 真实 PostgreSQL 周期巡检：`backend/test/integration/services/test_project_work_inspection_service.py` 覆盖重复 tick 幂等、worker 崩溃恢复与只在结论变化时产出。
- 真实 HTTP：`backend/test/integration/api/test_project_work_api.py`。
- Web unit：`web/test/unit/projectWorkTaskView.test.js` 覆盖附件上传回读与巡检配置保存的错误展示。
- 真实 worker E2E：`backend/test/e2e/test_deterministic_agent_path_e2e.py::test_project_work_assignment_reaches_worker_result_and_task_comment`；手动/自动接受完成、限流失败和中断恢复四个确定性回放场景均回读执行尝试、Run 与评论归属。
