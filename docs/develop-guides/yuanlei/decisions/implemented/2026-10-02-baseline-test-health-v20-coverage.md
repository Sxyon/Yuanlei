# 基线测试健康：收件箱时间戳默认值对齐与 v19→v20 迁移集成覆盖

状态：implemented
类型：testing
Owner：backend/package/yuxi/storage/postgres/models_business.py
关联 Feature：[用户收件箱](../../features/user-inbox.md)、[项目任务附件与周期巡检](../../features/project-work-tasks.md)

## 问题

`create_all` 建出的运行库与迁移 SQL 对元垒域时间戳列的默认值不一致。`USER_INBOX_SCHEMA_STATEMENTS` 与 v19→v20 迁移语句给这些列带 `DEFAULT NOW()`，而 ORM 模型只有 Python 侧 `default`、没有 `server_default`；测试夹具用原始 SQL 插入通知且不带 `created_at` 时命中 NOT NULL，`test/integration/api/test_project_work_api.py` 整体失败。同一分歧也存在于 `project_git_repositories.allowed_base_branches`（ORM 无 `server_default`，迁移带 `DEFAULT '[]'::jsonb`）。

集成 head 的 `YUANLEI_SCHEMA_VERSION` 为 20，测试中残留三处 `YUANLEI_SCHEMA_VERSION == 12` 恒假断言。其中 `test_yuanlei_v9_to_v10_converges_governance_tables_idempotently` 在断言之前就因 `DROP TABLE governance_*` 未加 CASCADE 而失败（`governance_topic_comments`、`project_work_tasks` 等后续表持有指向治理表的外键），断言实际不可达。v19→v20 迁移（任务文件附件、第一负责人周期巡检、巡检通知词表）此前只有 unit mock 调用链，缺真实 PostgreSQL 集成覆盖。

## 决策

`UserInboxItem.created_at` 与迁移对齐：加 `server_default=func.now()`，与 `manager.py` 中 `USER_INBOX_SCHEMA_STATEMENTS` 的 `DEFAULT NOW()` 语义一致；ORM 仍保留 Python 侧 `default=utc_now_naive`。迁移 SQL 已拥有该默认值，不新增迁移。本决定的语义分工：ORM 列定义由 `models_business.py` 拥有，迁移 DDL 事实由 `manager.py` 拥有，回归夹具由对应 integration 测试拥有。

删除三处恒假 `==12` 断言。v9→v10 的 `DROP TABLE governance_*` 加 CASCADE；治理四表的精确集断言放宽为包含（v10 之后新增的 `governance_topic_comments` 等表在隔离 schema 中共存）。

新增 `test_yuanlei_v19_to_v20_adds_attachments_and_inspection_idempotently`：在隔离 schema 中从当前形态降级到 v19（删附件/巡检表与巡检列、收窄 `ck_user_inbox_items_kind`），验证迁移前拒写 `task_inspection`，迁移后建表建列、巡检词表可写、重复迁移幂等，并保留既有任务与通知。

`project_git_repositories.allowed_base_branches` 与既有 lease/durable/scheduled/git/provisioner 基线失败不在本决定内，按跟踪项处理。

## 替代方案

- 只在夹具补 `created_at`：掩盖 ORM 与迁移的默认值分歧，其他 `create_all` 路径仍会复发。
- 断言当前常量 20：把用例与易变常量耦合，且与该用例主题（v8→v9、v9→v10）无关；删除更直接。
- v19→v20 仅保留 unit mock：无法证明真实 PostgreSQL 上的约束收敛、数据保留与迁移前拒写。
- 顺带修 `allowed_base_branches` 的同类分歧：超出本子问题「确认并跟踪」的范围，留给专门的收口改动。

## 后果

`create_all` 与迁移对 `user_inbox_items.created_at` 的默认值一致，原始 SQL 夹具在不显式写时间戳时按库时钟补齐。该对齐只作用于此后由 `create_all` 新建的表；已存在的运行库列默认值由迁移 DDL 拥有，不会因 ORM 改动回填，复用的旧测试卷仍可能在原始插入时失败。三处恒假断言移除，v9→v10、v10→v11 与 dashboard 用例恢复真实断言路径。未改动三功能业务不变量、API 契约、权限或持久化结构，未新增抽象或依赖。

## 验证

- 真实 PostgreSQL（隔离 schema；另建 migrated 库 `yl33_verify` 并用本分支代码起 API）：
  - `test_yuanlei_v19_to_v20_adds_attachments_and_inspection_idempotently` 通过。
  - `test_yuanlei_v9_to_v10_converges_governance_tables_idempotently`、`test_yuanlei_v10_to_v11_converges_channel_delegation_tables_idempotently`、`test_project_dashboard_service.py::test_yuanlei_v8_to_v9_converges_dashboard_tables_idempotently` 通过。
  - `test/integration/api/test_project_work_api.py` 通过（夹具原始插入 51 条不带 `created_at` 的通知）。
- `python3 scripts/verify_engineering_contracts.py`、`python3 -m unittest scripts.test_verify_engineering_contracts` 通过。
- 未覆盖：`test/integration/services` 中 lease/durable/scheduled/git/provisioner 与 `allowed_base_branches` 原始插入的基线失败与三功能无关，实际清单与命令见交付 issue。`docs/develop-guides/yuanlei/features/project-governance.md` 中 `YUANLEI_SCHEMA_VERSION = 12` 的过时描述同属跟踪项，不在本变更修正。
- `ruff check package` / `ruff format package --check` 在基线即存在失败（如 `models_business.py:952` E501），非本变更引入，本次未扩大处理。
