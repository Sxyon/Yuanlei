# 项目数字员工

状态：已实现
类型：有意产品差异
主要 Owner：`backend/package/yuxi/services/project_agent_service.py`

## 需求与失败场景

Yuxi Agent 是全局资源，无法表达某个数字员工属于指定 Project、使用项目级配置覆盖并且只能在该 Project 中运行。只在前端过滤会允许 API、恢复、定时任务或其他执行入口绕过项目范围。

## 必须保留的业务语义

- `(project_id, agent_slug)` 绑定拥有项目级配置覆盖。
- 已绑定 Agent 只能在绑定 Project 内运行；没有 Project 或使用其他 Project 时 fail-closed。
- 范围约束同时覆盖请求接入和实际执行边界，不能只依赖前端或列表过滤。
- 项目覆盖进入最终模型、工具审批和执行 Context；resume 继承父 Run 的项目身份。
- 未绑定的全局 Agent 保持 Yuxi 原有可见性和运行语义。

## 与 Yuxi 的边界

Yuxi 继续拥有 Agent 定义、请求队列、AgentRun、执行准备和可见性基础查询。元垒增加 ProjectAgent 绑定、项目级列表过滤、范围校验和有效配置合并。`project_agents` 持久化属于 yuanlei schema 域。

## 稳定集成点

| 集成角色 | 当前 Owner | Yuanlei 语义 |
|---|---|---|
| 绑定与覆盖 | `project_agent_service`、`project_agent_repository` | 拥有项目绑定和有效覆盖 |
| 请求接入 | `agent_request_service` | 新建与幂等重放都校验项目范围并固化有效配置 |
| 执行准备 | `agent_run_manifest_service.prepare_run_execution` | 再次校验范围并把覆盖合入 Context |
| 其他执行入口 | chat、conversation、scheduled、compression 用例 | 不允许绕过同一范围约束 |
| 前端管理 | ProjectAgent 管理组件与 Agent 列表 | 展示和编辑项目数字员工，但不承担最终授权 |

## 上游依赖

该能力依赖 Agent slug、Project identity、Conversation `project_id`、AgentRun input payload、执行准备 Context 和 Agent 配置解析。上游重构请求接入、resume、定时任务、配置合并或 manifest 时必须检查范围校验是否仍覆盖全部入口。

## 合并判断

- 上游重命名或合并入口：把同一业务不变量迁移到新的 intake 与 execution Owner。
- 上游增加项目级 Agent：比较绑定唯一性、配置覆盖、列表可见性、执行 fail-closed 和 resume/定时任务覆盖。
- 上游只实现 UI 分组或列表过滤：继续保留后端范围校验。
- 上游提供等价执行约束但没有历史数据迁移：复用运行能力，保留 yuanlei 迁移兼容直到数据收敛。

## 替换或删除条件

上游 Project Agent 同时覆盖持久绑定、配置覆盖、所有执行入口的 fail-closed 校验、可见性和已有 yuanlei 数据迁移后，可以删除元垒实现。业务不再需要项目专属数字员工时，需要新 Decision 明确数据和兼容后果后删除。

## 决策与证据

- [项目数字员工](../decisions/implemented/2026-09-17-project-digital-employees.md)
- [上游同步与 ProjectAgent 校验迁移](../decisions/implemented/2026-09-18-upstream-23-sync-project-agent-port.md)
- `backend/test/integration/api/test_project_agent_api.py`、请求队列并发测试和相关 service unit 覆盖绑定、覆盖与绕过入口。
