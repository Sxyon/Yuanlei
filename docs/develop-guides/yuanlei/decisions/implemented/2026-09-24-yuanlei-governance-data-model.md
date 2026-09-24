# Decision：元垒治理域数据模型（议题/决策/任务/汇报与来源归一化）

状态：implemented
类型：feature
Owner：backend/package/yuxi/services/governance_service.py
日期：2026-09-24
关联 Feature：[项目治理域](../../features/project-governance.md)

## 问题

元垒需要一条把渠道意图收敛为公司级事实的通道。Multica、GitHub、Gitea 与项目内来源各自产生议题/任务，缺少统一结构时会出现三种失败：来源不可追溯，无法判断一条议题来自哪里；同一外部对象重复落库；外部镜像与元垒各写一份状态，形成两个状态 Owner。上游 Yuxi 拥有 Project、AgentRun 与执行链路，但没有议题/任务的规范化事实与审核生命周期。

## 决策

在 `yuanlei` 域新增治理四表，并升 `YUANLEI_SCHEMA_VERSION` 到 10。

- `governance_topics`、`governance_tasks`：携带 `source_channel`、`source_external_id`、`source_url`；外部标识存在时 `(project_id, source_channel, source_external_id)` 唯一。项目内来源不带外部标识与链接，外部渠道必须带非空外部标识。
- 生命周期 `proposed → 审核 → canonical/rejected`。检查约束 `ck_governance_*_review_shape` 要求 `canonical`/`rejected` 必须同时有 `review_owner_uid` 与 `reviewed_at`，`proposed` 两字段为空；`ck_governance_*_source_shape` 约束来源组合。渠道侧创建入口只产生 `proposed`，只有 `review_governance_topic` / `review_governance_task` 写审核结论，未审核直改 canonical 在数据库层被拒绝。
- `governance_decisions`：人拍板结论、理由与被否替代，`status` 为 `proposed`/`implemented`，落 `implemented` 必须记录 `decided_by` 与 `decided_at`。
- `governance_reports`：保存聚合摘要与结构化载荷，引用 `source_run_id` 与 `artifact_path`，不保存 Run 终态。
- 用例层 `backend/package/yuxi/services/governance_service.py` 负责 Project 归属校验、来源归一化、去重、审核边界与项目数字员工绑定校验；持久化在 `backend/package/yuxi/repositories/governance_repository.py`。

## 替代方案

- 把治理对象直接放上游 business 域：拒绝。上游没有对应语义，回写会破坏 fork 边界与上游同步。
- 仓库外镜像（Multica）作为议题/任务事实源：拒绝。会产生第二状态 Owner，使元垒无法成为规范化事实源。
- 只用标签表达来源，不做生命周期：拒绝。来源归一化需要 proposed→审核→落库，标签无法约束 canonical 的唯一 Owner。
- 汇报复用 Run 状态：拒绝。汇报会成为第二 Run 状态源，违反执行终态由上游拥有的不变量。
- 在议题/任务上直接落执行状态字段：拒绝作为本期范围。督查板任务跟踪需要独立设计与迁移，属于后续步骤。

## 后果

- 议题/任务的外部标识唯一性以项目为范围，同一外部对象可在不同项目各自归一，符合项目级事实源语义。
- 审核责任人必填，使 canonical 的写入可问责；外部镜像只能提交 proposed。
- 新增四表通过外键挂接 `projects`、`agents`、`agent_runs`，Project 删除级联清理治理行。
- 任务执行状态、汇报生成与 Dashboard/Taskboard 消费、Multica 桥接仍待后续步骤，本记录不承诺这些能力。
- 上游同步时治理四表属于元垒新增结构，不得随上游覆盖删除。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 多来源议题保留渠道、外部标识与原文链接，可追溯 | 来源丢失或无法区分 | `governance_service.py` + `governance_topics` | `test/integration/services/test_governance_service.py::test_multi_source_topics_round_trip_with_traceable_source` | 项目内来源携带外部标识 | Passed |
| 重复外部标识被拒 | 同一对象重复落库 | `governance_service.py` + 唯一索引 | `test/integration/services/test_governance_service.py::test_duplicate_external_source_is_rejected` | 同 (project, channel, external_id) 二次创建 409 | Passed |
| 无来源或外部渠道缺标识被拒 | 无出处议题被静默接受 | `normalize_governance_source` | `test/unit/services/test_governance_service.py` | `source_channel` 缺失/未知、外部渠道缺标识 422 | Passed |
| 未经审核的 proposed 不得成为 canonical | 外部镜像直写 canonical | `governance_service.py` + 检查约束 | `test/integration/services/test_governance_service.py::test_proposed_requires_review_to_become_canonical` | 直改 canonical 触发 IntegrityError；重复审核 409 | Passed |
| 任务来源归一化并校验指派边界 | 越界指派未绑定数字员工 | `governance_service.py` + `ProjectAgentRepository` | `test/integration/services/test_governance_service.py::test_task_source_normalization_and_assignee_boundary` | 未绑定 slug 404，重复来源 409 | Passed |
| 汇报只引用 Run/artifact 不拥有终态 | 汇报成为第二 Run 状态源 | `governance_reports` | `test/integration/services/test_governance_service.py::test_report_records_artifact_reference_without_owning_run_state` | 汇报载荷无 status 字段 | Passed |
| 幂等迁移与 schema 版本 | 存量库缺少治理四表 | `manager.py` `upgrade_yuanlei_schema_v9_to_v10` | `test/integration/services/test_schema_migration_version.py::test_yuanlei_v9_to_v10_converges_governance_tables_idempotently`；`test/unit/storage/test_postgres_manager_schema.py` | 重放建表不重复；约束与索引真实存在 | Passed |
