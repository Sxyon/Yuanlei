# 项目治理域：议题/决策/任务/汇报与来源归一化

状态：已实现
类型：feature
主要 Owner：backend/package/yuxi/services/governance_service.py

## 需求与失败场景

元垒是公司层面的核心统筹点，拥有规范化议题与任务的唯一事实源。Multica、GitHub、Gitea 与项目内渠道只能产生 proposed 议题/任务，经人审核 → 排版归一 → 落库元垒后才成为 canonical；外部镜像不得反向写元垒状态。项目内 proposed 议题可在审核前编辑，并以按时间追加的 Markdown 回复展开讨论；审核后议题与讨论串只读。汇报由上游定时任务产出 artifact，元垒只保存结构化引用。

失败场景：多来源议题无法区分或丢失出处；同一外部标识重复落库形成重复议题；无来源或外部渠道缺标识的输入被静默接受；proposed 未经审核直接成为 canonical，使渠道镜像与元垒出现两个状态 Owner。

## 必须保留的业务语义

- 议题与任务携带来源渠道、外部标识与原文链接，来源可追溯。
- 外部标识存在时，`(project_id, source_channel, source_external_id)` 唯一，重复落库被拒。
- 项目内来源不携带外部标识与链接；外部渠道必须携带非空外部标识。
- 生命周期为 `proposed → 审核 → canonical/rejected`，审核必须记录审核责任人与审核时间。
- 议题正文复用 `summary` 的 Markdown 文本；议题仍为 proposed 时可编辑并追加讨论回复。每条回复保存正文、发帖时作者名、作者 uid 与时间，内容不可覆盖；审核和议题编辑/回复通过同一议题行锁串行化。canonical/rejected 后只能读取正文和讨论历史。
- 只有审核动作写入 `canonical`/`rejected`；渠道侧创建入口不提供写 canonical 的能力，未经审核直改 canonical 由数据库检查约束拒绝。
- 决策由人拍板，记录结论、理由与被否替代；汇报引用产出 Run 与 artifact 路径，不复制 Run 终态。
- Dashboard 从议题、决策、任务的现有外键生成关系图；图节点只选择与查看事实，写操作跳转项目工作台，不保存图形副本。

## 与 Yuxi 的边界

上游 Yuxi 拥有 Project、AgentRun、队列、执行与用户自建定时任务；元垒治理域不在这些域新增语义。元垒在 `yuanlei` 域新增治理四表与议题讨论回复表，并升 `YUANLEI_SCHEMA_VERSION`，通过外键引用上游 `projects(id)`、`agents(slug)`、`agent_runs(id)`，不修改上游 business/knowledge 表结构。任务执行状态与汇报生成流程属于督查板，本档案还覆盖议题讨论与来源归一化。

## 稳定集成点

- 表结构：治理四表与 `governance_topic_comments`，由 `backend/package/yuxi/storage/postgres/manager.py` 的迁移语句与 ORM 模型共同拥有。
- 用例：`backend/package/yuxi/services/governance_service.py` 拥有创建、编辑、讨论、审核与读取流程；来源归一化由 `normalize_governance_source` 与 `normalize_title` 承担。
- 持久化：`backend/package/yuxi/repositories/governance_repository.py` 按 Project 读写治理事实，提交点由用例决定。
- 迁移：议题讨论在 `upgrade_yuanlei_schema_v11_to_v12` 幂等建表，当前 `YUANLEI_SCHEMA_VERSION = 12`。

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
- Decision：[项目议题讨论、决策入口与关系图](../decisions/implemented/2026-09-27-project-governance-discussion-and-graph.md)。
- 用例与来源归一化实现：`backend/package/yuxi/services/governance_service.py`。
- 真实 PostgreSQL 行为证据：`backend/test/integration/services/test_governance_service.py`、`backend/test/integration/services/test_schema_migration_version.py`。
- 纯逻辑与 schema 单测：`backend/test/unit/services/test_governance_service.py`、`backend/test/unit/storage/test_postgres_manager_schema.py`。
