# 项目治理域：议题/决策/任务/汇报与来源归一化

状态：已实现
类型：feature
主要 Owner：backend/package/yuxi/services/governance_service.py

## 需求与失败场景

元垒是公司层面的核心统筹点，拥有规范化议题与任务的唯一事实源。Multica、GitHub、Gitea 与项目内渠道只能产生 proposed 议题/任务，经人审核 → 排版归一 → 落库元垒后才成为 canonical；外部镜像不得反向写元垒状态。议题在纳入通过或拒绝后持续维护，纳入与研讨进度分别保存；正文修订与研讨、重议、纠偏讨论形成倒序时间线。归档可恢复，无业务引用议题允许软删除。汇报由上游定时任务产出 artifact，元垒只保存结构化引用。

失败场景：多来源议题无法区分或丢失出处；同一外部标识重复落库形成重复议题；无来源或外部渠道缺标识的输入被静默接受；proposed 未经审核直接成为 canonical，使渠道镜像与元垒出现两个状态 Owner。

## 必须保留的业务语义

- 议题与任务携带来源渠道、外部标识与原文链接，来源可追溯。
- 外部标识存在时，`(project_id, source_channel, source_external_id)` 唯一，重复落库被拒。
- 项目内来源不携带外部标识与链接；外部渠道必须携带非空外部标识。
- 纳入资格为 `proposed → 审核 → canonical/rejected`，拒绝后修改不自动提交，显式重新提交回到 proposed；审核记录保留在历史节点。接口使用 admission_status 表达纳入，进度独立为 open/decided/closed。
- 议题正文使用 `summary` 的 Markdown 文本；未归档或删除时持续可修改与讨论。每次修订保存标题正文、原因、作者与时间；保存要求预期修订号，过期版本拒绝覆盖。讨论绑定当时修订，保存意图类型及作者名快照；旧评论版本未知。创建、修订、讨论和生命周期节点在同一议题行锁与事务内保存，按序号稳定倒序分页。
- 已纳入、开放的议题由用户选择当前已批准的关联决策后显式确认 decided；关闭填写原因，重开回到 open 并选择继续执行或建议暂停。重议和纠偏评论不自动重开。正文修订不覆盖正式决策；新决策引用当时议题修订，旧决策版本未知。重开提示不暂停任务或 Run，不撤销决策。
- 归档议题退出默认列表、督查汇总、图和新工作选择器，详情仍可读取，恢复后可维护。无关联决策、正式工作或治理任务及其执行依据时软删除；有引用拒绝删除并提供归档。来源唯一标识继续保留，防止外部重新导入。
- 只有审核动作写入 `canonical`/`rejected`；渠道侧创建入口不提供写 canonical 的能力，未经审核直改 canonical 由数据库检查约束拒绝。
- 决策新增为草案，显式批准才形成正式依据；草案保存携带预期版本，有引用拒绝删除。批准原文保留，不改变业务含义的文字勘误追加字段、新旧片段、原因与用户声明。数值、范围、条件变化通过新决策表达。
- 形成方式与效力独立：补充及整条替代有同项目单一目标，可跨议题。补充批准保留原决策有效；整条替代批准同事务使原决策被替代。撤销保留历史，不复活旧依据，不联动任务或执行记录。原依据变化的补充提示需复核。决策局部快照和倒序事件保存责任人、时间、原因及版本，关联议题节点在同一事务保存。
- 汇报引用产出 Run 与 artifact 路径，不复制 Run 终态。
- Dashboard 从议题、决策、任务的现有外键生成关系图；图节点只选择与查看事实，写操作跳转项目工作台，不保存图形副本。

## 与 Yuxi 的边界

上游 Yuxi 拥有 Project、AgentRun、队列、执行与用户自建定时任务；元垒治理域不在这些域新增语义。元垒在 `yuanlei` 域维护治理四表、议题讨论、修订和历史节点，并升 `YUANLEI_SCHEMA_VERSION`，通过外键引用上游 `projects(id)`、`agents(slug)`、`agent_runs(id)`，不修改上游 business/knowledge 表结构。任务执行状态与汇报生成流程属于督查板，本档案覆盖议题持续研讨、修订与来源归一化，实际目标达成、回复与采纳处置另批实施。

## 稳定集成点

- 表结构：治理对象与议题评论、修订和历史节点，由 `backend/package/yuxi/storage/postgres/manager.py` 的迁移语句与 ORM 模型共同拥有。
- 用例：`backend/package/yuxi/services/governance_service.py` 拥有创建、编辑、讨论、审核与读取流程；来源归一化由 `normalize_governance_source` 与 `normalize_title` 承担。
- 持久化：`backend/package/yuxi/repositories/governance_repository.py` 按 Project 读写治理事实，提交点由用例决定。
- 迁移：v28→v29 映射旧 proposed/implemented 为草案/已批准，保留拍板责任人与时间；当前正文建立一次迁移基线，过往修订与旧议题依据版本照实未知。v27→v28 拆分进度、建立当前内容迁移基线，并导入可证明的创建、审核和评论节点；旧进度保持开放，不推断决策形成或目标达成。

## 上游依赖

- `projects(id)`：治理对象按 Project 归属，Project 删除级联删除治理行。
- `agents(slug)`：任务指派的项目数字员工，未绑定项目的 slug 在用例层拒绝。
- `agent_runs(id)`：汇报只引用产出 Run，Run 删除时置空，不承载其状态。
- 归一路径复用上游 Project 归属查询与元垒 ProjectAgent 绑定查询。

## 合并判断

上游新增议题/任务或 Dashboard 能力时，按业务语义重新取舍：仅当上游提供等价且更权威的事实 Owner 时，才采用上游实现并缩小本差异；来源归一化与 proposed→审核→canonical 生命周期是元垒产品主张，缺失对应上游语义前保留。上游同步不得直接删除治理四表或其检查约束。

## 替换或删除条件

当上游拥有等价的议题/任务事实源，且能表达来源渠道、外部标识与审核责任人，并保证外部镜像不反向写时，治理四表可被上游结构替换。删除前需要新的 Decision 说明数据迁移与 Dashboard/督查板消费侧的替换路径。

## 决策与证据

- Decision：[元垒治理域数据模型](../decisions/implemented/2026-09-24-yuanlei-governance-data-model.md)。
- Decision：[议题纳入、研讨进度与修订历史](../decisions/implemented/2026-10-05-topic-lifecycle-revisions.md)。
- Decision：[项目议题讨论、决策入口与关系图](../decisions/implemented/2026-09-27-project-governance-discussion-and-graph.md)。
- 用例与来源归一化实现：`backend/package/yuxi/services/governance_service.py`。
- 真实 PostgreSQL 行为证据：`backend/test/integration/services/test_governance_service.py`、`backend/test/integration/services/test_schema_migration_version.py`。
- 纯逻辑与 schema 单测：`backend/test/unit/services/test_governance_service.py`、`backend/test/unit/storage/test_postgres_manager_schema.py`。

- P01 Decision：[决策批准、关系与局部历史](../decisions/implemented/2026-10-05-decision-approval-history.md)。真实 HTTP 负向、并发与 PostgreSQL 回读由 `backend/test/integration/api/test_decision_lifecycle_api.py` 覆盖，隔离旧结构迁移与重入由治理服务 integration 覆盖。
