# Project 多仓库与根任务 Git Worktree

状态：implemented
类型：architecture
Owner：backend/package/yuxi/services/project_git_service.py

## 问题

Project 当前只拥有一个 UserWorkspace Workdir，不表达 Git 仓库绑定、远端凭据、任务分支或并发 worktree。让 Agent 自行使用长期 Token 或 SSH 私钥 clone/push，会使凭据进入 Sandbox environment、UserWorkspace、命令输出、模型上下文或日志。多个根任务直接操作同一 checkout 还会共享分支、索引和未提交文件，无法提供稳定的并发开发边界。

Git 托管商 API、Git 本地命令、Run 调度和 Sandbox 生命周期属于不同边界。若由 sandbox-provisioner 查询 Project 或解密凭据，会把运行容器管理与业务授权耦合；若可信 worker 直接在 Agent 可写仓库中携带凭据运行 Git，Agent 可通过 hooks、Git config 或 URL rewrite 影响高权限进程。

## 决策

Project 可以绑定多个 Git 仓库。仓库显示 alias 在同一 Project 内大小写不敏感唯一；服务端生成不可穿越、不可碰撞的 directory name。仓库数据位于 Project Workdir：

- `repos/<directory-name>/repository.git`
- `repos/<directory-name>/worktrees/<task-key>`

`directory-name` 使用规范化 alias 加 repository binding ID 摘要生成；`task-key` 使用 `sha256(uid + runtime_scope_id)` 的稳定摘要生成，不直接使用用户输入或原始线程 ID。

根 Conversation 的 `runtime_scope_id` 是任务身份。Chat、Resume 和其全部 SubAgent 对同一仓库复用一个分支和 worktree；不同根任务得到不同 worktree。分支名称为 `${YUXI_GIT_BRANCH_PREFIX}task-<task-key>`，默认前缀 `codex/`。分支与 commit 保存代码进展，Conversation、AgentRun、ProjectGitRepository 和 ProjectGitWorktree 仍拥有业务状态。

新增小型 `GitHostingProvider`。Provider 只负责仓库元数据、默认分支、分支保护和 deploy key API。第一版只实现 Gitea。Factory 对 `github`、`gitlab` 保留集中 TODO 并抛出 unsupported-provider 错误，不创建空实现。

clone、fetch、worktree、状态读取和 push 由 provider-independent Git executor 执行。远端操作使用 worker 私有临时 staging repo。持有凭据的 Git 进程不在 Agent 可写的 bare repo 或 worktree 中运行；禁用 hooks、全局配置、credential helper、SSH agent 和交互输入，并只使用数据库中的 canonical remote、固定 SSH 参数和连接保存的 known-host key。远端对象完成获取后，再在无凭据环境下导入 UserWorkspace bare repo。

Gitea 使用每仓库独立、可写 deploy key。Gitea API Token 和 deploy private key 由 Git credential owner 使用 AES-256-GCM 加密保存。加密 AAD 绑定 credential ID、uid、用途和 key version。明文不进入 AgentEnv、Sandbox environment、UserWorkspace、模型上下文、日志、HTTP 响应或 Git URL。Git 功能缺少有效 master key 时 fail-closed，Yuxi 非 Git 功能仍可启动。

Agent 在 Sandbox 中通过 execute 使用本地 Git。运行上下文只注入 alias、runtime path、branch、base branch 和状态。Root Agent 获得 `git_push_branch(repository_alias, expected_head_sha)`；SubAgent 不获得 push 工具。Push 无条件进入 HITL，批准后重新验证 Run、uid、Project、repository、runtime scope、worktree、当前分支、clean 状态和 HEAD。远端默认分支、受保护分支、tag、删除和非快进更新均不可通过该工具执行。

仓库 maintenance 使用 PostgreSQL session advisory lock，覆盖共享 bare repo 的 import、worktree add/remove 和 prune。`repository_id + runtime_scope_id` 唯一 worktree 行及可过期 lease 防止重复准备和重复可信写入。不同 runtime scope 的 staging/fetch 可以并行，修改同一 bare repo 的短临界区串行。

Repository provisioning、停用和本地清理以 PostgreSQL 状态作为持久意图。事务提交后才发布 ARQ job；发布失败由 worker reconciler 扫描未完成状态重新投递。外部成功但数据库提交失败时，重试通过确定性 deploy-key title、公钥 fingerprint、remote branch SHA 和本地路径回读收敛。

删除 Conversation 不自动删除 worktree。停用仓库或删除 Project 会先阻止新 preflight/push，并异步撤销 deploy key和销毁当前数据库凭据引用，但保留本地 bare repo/worktree。用户通过显式清理操作删除 worktree；只有 worktree clean 且 HEAD 已推送时允许清理。远端 branch 不由第一版自动删除。

## 替代方案

- 把 SSH private key写入 Sandbox environment 或普通文件挂载：拒绝。Agent 的 execute 可以读取、打印或传出凭据。
- 让可信 worker 在 Agent 可写仓库中直接携带凭据执行 push：拒绝。仓库 hooks 和本地 Git config 会进入高权限执行路径。
- 每个 Agent 单独创建 branch/worktree：拒绝。Root Agent 与 SubAgent 属于同一根任务，需要共享代码状态。
- 为 Git 基础操作新增 Skill：拒绝。模型已经具备 Git 基础知识；只需注入项目路径、分支和权限契约。
- 把 Git 配置和密钥交给 sandbox-provisioner：拒绝。Provisioner 继续只拥有 runtime、挂载和网络。
- 第一版同时实现 GitHub/GitLab：拒绝。当前 consumer 只有 Gitea，实现空 provider 会增加不可验证表面。
- Conversation 删除时自动清理 worktree：拒绝。未推送进展可能丢失，清理必须是显式且可验证的操作。

## 验证

- `test_project_git_core.py` 覆盖 AES-GCM AAD、缺失 key、provider fail-closed、安全路径与分支前缀、公开序列化脱敏，以及 Gitea 通配保护规则。
- `test_git_executor.py` 覆盖恶意 pre-push hook、`core.sshCommand`、credential helper、URL rewrite 和 fsmonitor 不进入可信远端操作。
- `test_project_git_service.py` 覆盖清理意图先提交、dirty worktree 拒绝、ready worktree直接复用，以及 provision generation 变化后的 deploy key 自撤销。
- `test_schema_migration_version.py` 在真实 PostgreSQL 中验证 v2 到 v3、alias 大小写唯一与跨用户复合外键。
- `test_gitea_git_integration.py` 在真实 Gitea HTTP/SSH 中验证 deploy key、fetch、worktree、commit、push、通配保护规则、撤权及撤权后拒绝访问。
- Agent prompt、manifest、工具装配、SubAgent 过滤和审批单元测试验证 Git 快照不含 secret，且 `git_push_branch` 不受 `always_trust` 豁免。
- 工程 gate、后端相关单元测试、Web lint/unit/build 和文档构建通过。完整证据与尚未覆盖的真实浏览器/API→ARQ→Sandbox→HITL 组合链路记录在交付说明中。

## 后果

当前 Sandbox 挂载同一用户的整个 UserWorkspace。Worktree 提供任务级 Git 索引、分支和目录隔离，但不是同一 uid 下对恶意 Agent 的强文件安全边界；Agent 仍可能读取或修改其他 Project、bare repo 和 worktree。可信 push 必须忽略这些目录中的 remote、hooks 和 credential 配置，并从数据库与私有 staging repo 重建远端操作。

Project 允许多个业务 Project 共享同一个 Workdir。目录名必须包含 repository binding ID，不能只使用 alias，否则两个 Project 的同名 alias 会在同一 POSIX 目录碰撞。

数据库、远端 Gitea 和 POSIX 文件系统无法形成单一事务。所有操作必须先持久化意图、提交、再发布；恢复依据必须来自远端 key/branch 和真实文件回读，不能依据日志或 ARQ 成功状态。
