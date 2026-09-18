# Project Git Worktree 按根任务显式分配

状态：proposed
类型：architecture
Owner：backend/package/yuxi/services/project_git_service.py

## 问题

Project 可以绑定多个 Git 仓库，但当前 Run preflight 会为根任务自动准备全部未停用仓库。未使用的仓库因此产生远端 fetch、分支和 worktree 副作用；任一未使用仓库处于 provisioning 或失败状态也会阻塞任务。当前仓库绑定只保存远端默认分支，不能表达仓库用途、允许的任务基线或用户与 Root Agent 对当前任务的选择意图。

## 提案

Project 仓库绑定只定义可用仓库及其用途、默认任务基线和精确允许基线列表。根 Conversation 通过 `ProjectGitWorktree` 持久化零个或多个仓库 allocation；没有 allocation 的仓库不进入 Run preflight。该表继续以 repository binding 与根 `runtime_scope_id` 唯一，同时拥有 allocation 意图、服务端生成的任务分支、准备状态、lease 和清理生命周期。

用户通过 Conversation 接口预选仓库，下一次 Run 只准备 `requested` allocation。Root Agent 可以列出 Project 仓库，并通过始终需要人工批准的工具动态申请和同步准备 worktree。Root 与 SubAgent 共享同一根 scope 的已分配路径；SubAgent 不获得 list、prepare 或 push 管理工具。

任务分支由服务端使用受限 kind、ASCII kebab-case slug 和稳定 task key 生成。base branch 必须精确命中仓库 allowlist，base SHA 在首次准备时冻结。`prepare_failed` 只由显式重试恢复；未选择仓库的状态不影响 Run。removed allocation 可以创建新的 generation；请求幂等只覆盖当前 generation。

可信 Project Git service 和 Git executor 继续独占 fetch、worktree add/remove/prune、base SHA 冻结与 push。Agent prompt 只说明已授权环境和协作约束，不构成同 uid 恶意 Agent 的文件隔离边界。Run manifest 只记录 Run 开始时的稳定 ready 快照，动态 prepare 不改写既有 fingerprint。

Project Git 当前由 `yuanlei` schema 域拥有。本变更把该域从 v1 升级到 v2，幂等回填既有 binding 与 worktree，不修改 business schema 版本，不删除已有分支、worktree 或代码。

本记录部分取代[Project 多仓库与根任务 Git Worktree](../implemented/2026-09-14-project-multi-repository-git-worktrees.md)中“每个根任务自动准备全部仓库”和固定 `task-<task-key>` 分支命名；其 credential、staging、maintenance lock、HITL push、显式清理及隔离边界继续有效。

## 替代方案

- 保留全部仓库自动准备：拒绝。仓库绑定不是任务使用声明，未使用仓库不应产生副作用或阻塞 Run。
- 新增独立 allocation 表：拒绝。现有 worktree 行已经由 repository 与根 scope 唯一确定，拆表会增加事务和恢复表面。
- 根据 execute 命令推断仓库：拒绝。shell 文本不是稳定授权边界，也无法可靠表达 base 和分支意图。
- 新增 Git Skill：拒绝。Skill 不能拥有凭据、授权、lease 或外部副作用。
- 用 Prompt 强制只读或隔离：拒绝。当前 Sandbox 挂载同一用户的整个 UserWorkspace，无法形成该安全承诺。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 未选择仓库的 Conversation 运行时不创建 worktree，也不 fetch | preflight 仍遍历 Project binding | Project Git service、worktree repository | 相关 unit + PostgreSQL integration + assembled-path E2E | Project 绑定三个仓库但零 allocation，记录任何 worktree/fetch 即失败 | Not run |
| 只准备显式选择且授权的仓库 | 跨 Project/scope 选择或未选择仓库产生副作用 | Conversation API、Project Git service、数据库约束 | 真实 HTTP integration + Gitea E2E | 伪造 scope、跨用户 alias、未选择失败仓库 | Not run |
| base、任务分支和 generation 稳定且可恢复 | base 漂移、非法 ref、旧请求复活已替换意图 | worktree 数据约束、Git path/ref helper、executor | unit + PostgreSQL integration + Gitea E2E | 非 allowlist base、非法 slug、远端同名冲突、removed 后旧 request replay | Not run |
| 动态 prepare 与 push 仅 Root Agent 经审批执行 | always_trust 绕过、SubAgent 直接调用、只按 Prompt 授权 | tool approval、tool filtering、Project Git service | Agent unit + assembled-path E2E | SubAgent 显式工具调用、旧 Run 或停用 binding | Not run |
| v1 数据无损升级为 yuanlei v2 | 既有 worktree 被重建或 migration 不可重放 | storage migrator、PostgreSQL schema | 真实 PostgreSQL migration integration | v1 数据重复升级后字段、分支、状态或路径变化 | Not run |

## 风险

- PostgreSQL、Gitea 和 POSIX 文件系统仍无法形成单一事务；恢复必须回读远端 ref、bare repo、worktree metadata 和数据库 lease。
- 八位 task key 分支后缀存在碰撞可能；准备阶段必须拒绝不属于当前 allocation 历史的同名远端分支。
- 动态 prepare 发生在 Run manifest 固化后；当前 Run 依赖 Tool result，下一次 Run 才把该仓库纳入 manifest。
- 当前 Sandbox 不隔离同 uid 的其他 worktree；可信 push 必须继续忽略 Agent 可控 remote、hook 和 Git config。
