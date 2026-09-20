# Project Git 多仓库与任务 worktree

状态：部分实现，部分提案待验收
类型：新增业务能力
主要 Owner：`backend/package/yuxi/services/project_git_service.py`

## 需求与失败场景

Project 需要绑定多个远端仓库，并让同一根任务的 Root Agent 与 SubAgent 共享分支和 worktree。长期 Token、SSH 私钥和可信 push 不能进入 Agent 可读取的 Sandbox、UserWorkspace、模型上下文或日志。多个任务直接操作同一 checkout 会共享索引、分支和未提交文件；自动准备全部绑定仓库还会让未使用仓库产生副作用或阻塞 Run。

## 必须保留的业务语义

- Git 凭据只在可信服务端边界解密和使用，不进入 Agent 可见环境。
- 同一根任务共享一个仓库分支和 worktree，不同根任务使用不同 worktree。
- 只有显式分配的仓库进入 Run preflight；未选择仓库不 fetch、不创建 worktree，也不阻塞运行。
- push 始终需要人工批准，并在批准后重新校验用户、Project、Run、仓库、scope、分支、clean 状态和 HEAD。
- 数据库保存持久意图；远端 Git 和文件系统副作用通过幂等回读收敛。

## 与 Yuxi 的边界

上游 Yuxi 拥有 Project、Conversation、AgentRun、Sandbox 和审批主链路。元垒增加仓库绑定、加密凭据、Gitea provider、可信 staging、任务 worktree、运行时 Git 身份快照与审批 push。Yuxi 普通非 Git 能力在 Git 配置缺失时继续工作，实际使用 Git 能力时 fail-closed。

## 稳定集成点

| 集成角色 | 当前 Owner | Yuanlei 语义 |
|---|---|---|
| 仓库、凭据和 worktree 用例 | `yuxi.services.project_git_service`、`yuxi.repositories.project_git_repository` | 拥有授权、状态、lease、preflight 和恢复 |
| 可信 Git 与托管商边界 | `yuxi.git` | 忽略 Agent 可控 hook/config/remote，并通过私有 staging 使用凭据 |
| Run 执行准备 | `yuxi.services.run_worker`、`agent_run_manifest_service` | 只注入已授权仓库的稳定身份快照 |
| Agent 工具与审批 | `yuxi.agents.toolkits.git_tools`、tool approval | Root 可申请准备和 push，SubAgent 不拥有管理能力 |
| 持久化 | yuanlei schema migration | Git 表和版本不推进上游 business 域 |

## 上游依赖

该能力依赖 Project/Conversation 的稳定身份、根 `runtime_scope_id`、Run manifest、Sandbox Workdir 映射、tool approval 和 worker 的执行准备时序。上游修改这些 Owner 时需要重新核对分配、身份快照、凭据边界与恢复语义。

## 合并判断

- 上游只重构 Run 或 Sandbox：迁移集成点，保留凭据不可见、任务级 worktree 和 HITL push 不变量。
- 上游提供仓库绑定或 worktree：优先复用公共能力，逐项比较多仓库、根任务共享、可信凭据和恢复语义后缩小元垒实现。
- 上游只提供普通 Git 工具：继续保留元垒可信远端操作和审批边界。
- 上游改变 manifest：保留稳定身份字段，运行时派生路径不进入长期指纹。

## 替换或删除条件

上游能力同时覆盖项目仓库绑定、任务级显式分配、凭据隔离、可信远端操作、人工批准 push、lease/recovery 和 yuanlei 数据迁移兼容时，可以删除对应元垒实现。单独提供 clone、shell Git 或 prompt 约束不满足替换条件。

## 决策与证据

- [Project 多仓库与根任务 Git Worktree](../decisions/implemented/2026-09-14-project-multi-repository-git-worktrees.md)
- [按根任务显式分配 worktree](../decisions/proposed/2026-09-16-on-demand-project-git-worktrees.md)
- `backend/test/unit/services/test_project_git_service.py`、`test_git_executor.py`、真实 PostgreSQL migration 和 `test_gitea_git_integration.py` 拥有主要证据；显式分配提案中的 assembled-path 证据仍以 Decision 当前结果为准。
