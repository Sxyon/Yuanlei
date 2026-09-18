# 项目数字员工（ProjectAgent）

状态：implemented
类型：feature
Owner：backend/package/yuxi/services/project_agent_service.py

事实分工：绑定与覆盖持久化归 `backend/package/yuxi/repositories/project_agent_repository.py`，提交边界校验归 `backend/package/yuxi/services/run_submission_service.py` 与 `backend/package/yuxi/services/conversation_service.py`，执行边界校验与有效配置归 `backend/package/yuxi/services/agent_run_manifest_service.py` 与 `backend/package/yuxi/services/chat_service.py`，Python 持久化模型归 `backend/package/yuxi/storage/postgres/models_business.py`，yuanlei 域 Schema 归 `backend/package/yuxi/storage/postgres/manager.py` 与 `backend/package/yuxi/storage_migration.py`，HTTP 表面归 `backend/server/routers/project_agent_router.py`，前端管理面归 `web/src/components/model-management/ProjectAgentManagePanel.vue`。

## 问题

- 上游 `agents` 表是全局资源：只有 `created_by` + `share_config` 表达归属，没有项目边界。`Conversation` 绑定 `(uid, agent_slug, project_id)`，但提交与执行边界都不校验"这个智能体是否属于这个项目"。
- 产品需要"项目数字员工"：只在所属项目内工作、参数可按项目覆盖，并在同一条归属记录上承载后续的独立记忆、常驻沙盒、Taskboard 与 Workflow 成员。
- 本仓库是上游 fork，新增持久化内容必须落在 `yuanlei` schema 域，避免与上游 business 域版本漂移。

## 决策

- 新增 yuanlei 域表 `project_agents`：`(project_id, agent_slug)` 唯一绑定 + `config_overrides` 项目覆盖层；绑定行是未来项目级状态的挂载点。`YUANLEI_SCHEMA_VERSION` 从 2 升到 3，幂等 DDL 收敛。
- 语义：Agent 一旦存在绑定，就只能在绑定项目内的会话运行；没有任何绑定的 Agent 完全维持现有全局行为。绑定即项目范围，运行边界 fail-closed。
- 有效配置 = Agent 基础 `config_json.context` 与绑定 `config_overrides.context` 合并，再走 `normalize_agent_context_config` 做角色与资源授权归一，并进入 Run manifest 的 `normalized_context`；项目覆盖与基础配置一样受 `BaseContext.auth` 约束。
- 授权在提交边界（`submit_run_command`、`create_thread_view`、`prepare_agent_run_creation_scope`、`_resolve_agent_runtime`、定时任务校验、主动上下文压缩）与执行边界（`build_run_manifest_result`）双重校验，无绑定智能体直接通过。
- Run 创建时的 `model_spec` 与 `tool_approval_mode` 快照同样读取项目覆盖（`load_agent_run_context` 接受 `project_override`），避免 manifest 记录项目模型而执行使用基础/系统模型的分叉；项目内同一 Agent 的绑定变更用 Agent 级 advisory lock 串行化。
- 管理 API：`/api/projects/{project_id}/agents`（列表、创建并绑定、绑定已有、更新覆盖、解绑）；`PUT` 提交增量覆盖与 `reset_fields` 恢复继承；智能体列表新增可选 `project_id` 参数：无参数只返回无绑定 Agent，带参数返回该项目绑定 + 无绑定 Agent。`GET /api/agent/{slug}?project_id=` 返回项目覆盖后的 `effective_context`。
- 前端：聊天页按所选项目过滤智能体，打开已绑定线程时以项目有效配置渲染输入区；`AgentManageView` 新增「项目智能体」tab 完成创建、绑定、覆盖编辑、恢复继承与解绑。
- 「新建项目智能体」与「编辑项目智能体」弹窗都与智能体弹窗共用同一视觉结构（自定义标题栏、头像/名称/标识/后端、描述、分段侧栏），编辑弹窗在基本信息中展示「项目归属」；运行配置以基础与覆盖的合并值回填，保存时只把变更字段写成覆盖、恢复继承的字段走 `reset_fields` 删除旧覆盖。
- 「项目智能体」面板默认展示全部项目的数字员工并带项目标签；新建/绑定在未选择项目时提示并抖动项目选择器，不进入弹窗；聊天选择器为项目数字员工显示「项目」徽标（列表与详情接口在项目上下文下返回 `is_project_agent`）。
- 支持从全局或其他项目的可见智能体复制参数/描述/图标到新建草稿（`web/src/utils/projectAgentCopy.js`），复制只改前端状态，创建必须由用户点击「创建」触发。
- 项目软删除在同一事务中删除绑定、不删除 Agent，也不修改 Workdir 字节；解绑并显式请求删除时，仅当智能体不再绑定其他项目才删除。

## 替代方案

- `agents` 表增加 `project_id` 列：破坏上游 slug 全局唯一与 share_config 语义，merge 成本高。拒绝。
- 只用 share_config 实现私有：无法表达项目归属，也没有承载未来项目级状态的实体。拒绝。
- 绑定只作展示、不限制运行范围：无法保证数字员工不在项目外工作。拒绝。
- 为每个项目复制一份独立 agent 定义表：与现有运行时、管理、manifest 链路重复。拒绝。

## 后果

- 上游 merge 冲突面集中在 `agent_repository.py`、`agent_router.py`、`chat_service.py`、`run_submission_service.py`、`conversation_service.py`、`agent_run_service.py`、`agent_run_manifest_service.py`、`scheduled_agent_service.py`、`manager.py`、`storage_migration.py` 的各一处小改；新增文件独立。
- 项目软删除仅解绑后，owner 的私有智能体回到个人全局列表（仅本人可见），不会泄漏给其他用户；该行为已写入 `test_project_agent_lifecycle_keeps_agent_out_of_global_lists`。
- 覆盖参数没有独立的作用域校验层：管理员字段仍按 `filter_config_by_role` 静默裁剪，普通用户不能借项目覆盖提升管理员参数。
- 后端支持同一 Agent 绑定多个项目（解绑删除前检查剩余绑定），但本期前端绑定入口只列出未绑定 Agent，跨项目复用同一 Agent 尚无 UI 入口。
- 本期顺手修正了 fork 基线中与 yuanlei 版本策略冲突的过期断言（`test_schema_migration_version.py` 的 `BUSINESS_SCHEMA_VERSION == 8` 改为 7，business 域仍归上游），并把运行时版本测试补齐为 business/knowledge/yuanlei 三段；这两处不是本 feature 的功能改动，记录在此避免误读。
- 未来扩展落在 `project_agents` 行上（记忆命名空间、沙盒保留策略、Taskboard、Workflow），本期不预建投机字段。

## 验证

| 验收主张 | 直接证据 | 结果 |
|---|---|---|
| 创建 / 覆盖 / reset_fields / 项目删除解绑 / 列表边界 | `docker compose exec -T -e TEST_USERNAME=... api uv run --no-sync --group test pytest test/integration/api/test_project_agent_api.py -q`（4 passed） | Passed |
| 绑定智能体在非绑定项目、隐式项目被拒，解绑恢复全局 | 同上（403/200 负向与正向断言） | Passed |
| 主动上下文压缩不能绕过项目范围 | 同上 `test_bound_agent_rejects_context_compression_outside_project`（403） | Passed |
| 非项目成员不可见、不可管理、不可运行 | 同上 `test_project_agent_management_is_private_to_project_owner` | Passed |
| 项目覆盖合并与运行范围守卫 | `pytest test/unit/services/test_project_agent_service.py -q`（4 passed） | Passed |
| 执行边界带范围校验并使用有效配置 | `pytest test/unit/services/test_agent_run_manifest_service.py -q`（新增用例） | Passed |
| Run 创建使用项目 model/approval 覆盖 | `test_load_agent_run_context_merges_project_override`；接入 `intake_request` 与 `create_agent_run_view` | Passed |
| yuanlei v2 → v3 幂等收敛与绑定边界 | `pytest test/integration/services/test_schema_migration_version.py -q`（新增 2 用例通过；该文件预存在的 2 个 PJ1 基线失败见未验证范围） | Passed |
| 前端请求携带项目上下文、选中使用有效配置、覆盖更新载荷、表单事件接线、复制草稿不入库、项目徽标 | `pnpm run test:unit`（349 passed，含 `test/unit/projectAgentScope.test.js`） | Passed |
| 项目上下文列表/详情返回 `is_project_agent` 标记 | `test_project_agent_api.py`（4 passed，含项目列表与详情断言） | Passed |
| 前端 lint 与构建 | `pnpm run lint:check`、`pnpm run build` | Passed |
| 真实页面截图/录屏（浅/深色、loading/empty/error） | `n -s=<session> run-code --filename=web/test/browser/projectAgentManagePanel.js`（需补写脚本） | Not run |

未验证范围与原因：

- 本环境没有 `n`（playwright-cli）与 `TEST_USERNAME/TEST_PASSWORD`，无法执行真实浏览器截图；integration 用例通过临时本地测试账号运行，命令与结果已记录在 PR 证据。页面验证脚本需按 `web/test/browser/` 既有模式补充后执行。
- 该文件在本次改动前就有 2 个 PJ1 半合并基线失败（`test_business_v2_converges_project_git_schema`、`test_project_git_schema_enforces_alias_and_user_boundaries`）与 1 个技能并发 flake（`test_sync_user_accessible_skills_serializes_multiple_processes` 子进程超时），均与本决策无关，未在本期修复。
