# 项目工作任务第一阶段

状态：implemented
类型：feature
Owner：backend/package/yuxi/services/project_work_service.py
关联 Feature：[独立项目工作任务与 Issue](../../features/project-work-tasks.md)

## 问题

Yuxi 的 AgentRunRequest 是一次聊天请求，元垒既有 `governance_tasks` 是来源审核对象。两者都无法保存项目长期任务、父子任务、任务下独立问题单、第一负责人和稳定编号。把工作状态塞进任一现有对象会使审核、执行和长期责任混用。

## 决策

在 yuanlei 域新增项目工作任务、任务下 Issue、项目及议题编号配置和追加式评论表，schema 版本从 12 升至 13。当前阶段只建立工作对象和 HTTP 操作，不触发 AgentRun，也不改变治理任务。项目缩写全局唯一，议题缩写在所属项目唯一；首次配置后固化。任务创建在项目缩写行锁内分配递增项目序号，编号为 `项目缩写-议题缩写-六位序号`；无议题时使用 `GEN`，议题不可配置该缩写。Issue 在任务行锁下分配序号，展示编号为 `任务编号-I序号`。对象归属、父子范围和第一负责人项目绑定由后端校验；每条评论保存作者显示名快照。

Service 与 repository 都限定当前用户的 active selectable Project；议题缩写、任务议题和父任务使用组合外键保证同项目。第一负责人必须是项目数字员工；解绑和直接删除 Agent 都检查其是否仍负责任务，存在则返回 409。自动生成缺失议题缩写、执行队列、附件引用、用户收件箱和第一负责人周期检查由[后续提案](../proposed/2026-09-27-agent-workbench-inbox-project-work.md)推进。现阶段关联议题但尚无缩写时，建任务返回 409；不生成临时编号。

## 替代方案

- 扩展 `governance_tasks`：其 `proposed/canonical/rejected` 和来源审核约束不能同时充当工作进度。
- 用 AgentRunRequest 作任务：请求只代表一次输入和线程 FIFO，无法承载跨执行者长期状态。
- 直接从标题生成缩写：中文及重复标题不能保证稳定与唯一，且会在未核验模型输出前固化不可靠编号。

## 后果

两种任务对象暂时并存，调用方必须选择 `/governance/tasks` 的审核语义或 `/work/tasks` 的工作语义。存量治理任务不自动迁移。项目缩写配置后不可改，避免历史编号出现歧义。当前接口可用来建立和记录任务，但 `in_progress` 由有权用户显式修改，并不证明存在运行中的 AgentRun。新增部署须先运行 storage-migrator 升级 yuanlei v12→v13，再启动 API 与 worker。

## 验证

- `docker compose exec -T api pytest test/integration/services/test_project_work_service.py test/integration/services/test_schema_migration_version.py -k 'project_work or v12_to_v13' -q`：2 passed；并发编号、直接仓储越权、跨项目父任务/议题的数据库拒绝、负责人解绑拒绝、跨任务 Issue、迁移重入及旧议题数据保留已核对。迁移测试从当前模型建表后删除 v13 新表与索引模拟存量 v12，尚未从真实 v12 发布快照还原。
- `docker compose run --rm storage-migrator`：退出码 0；随后 PostgreSQL schema 版本回读为 yuanlei=13。
- `docker compose exec -T api pytest test/integration/api/test_project_work_api.py -q -rs`：重启 API/worker 后 1 passed；HTTP 回读 Issue 评论，跨项目与其他用户访问 404，项目软删除后 404，无身份 401，删除仍负责任务的 Agent 返回 409。
- `docker compose exec -T api pytest test/unit -m 'not slow' -q --tb=short`：2722 passed、61 skipped；`uv run --group test` 因容器全局 editable 文件权限错误未启动，直接调用容器内 pytest 得到上述结果。最后修改的 Agent 删除路径另以 72 个相关 unit 与真实 HTTP 负向案例验证。
- `python3 scripts/verify_engineering_contracts.py`、`python3 -m unittest scripts.test_verify_engineering_contracts`、`cd docs && pnpm run build`、相关 Ruff check/format、`git diff --check`：通过。
- 三轮独立 Reviewer 发现仓储裸 ID 访问、跨项目持久关系、负责人解绑/直接删除残留、无目标评论查询泄露及 `GEN` 议题缩写歧义；均已在边界修复并增加负向案例。
- 首次 HTTP 测试因 API 在 schema 仍为 v12 时启动失败而超时；迁移后重启并重新执行通过。该失败不计作产品验证结果。
