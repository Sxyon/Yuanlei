# Project Git 配置与分支参考

本页集中说明 Project 多仓库功能的启动配置、资源关系、目录与分支规则、状态和权限边界。按界面完成首次配置请先阅读[为 Project 配置 Git 仓库](../intro/project-git.md)。

## 启动配置

Git 能力由 API 和 worker 读取以下环境变量：

| 变量 | 默认值 | 读取者 | 约束与生效时机 |
| --- | --- | --- | --- |
| `YUXI_GIT_CREDENTIAL_KEY` | 空 | API、worker | 32 字节 base64url AES key；为空或无效时 Git API fail-closed，其他 Yuxi 能力仍可启动 |
| `YUXI_GIT_BRANCH_PREFIX` | `codex/` | worker | 必须是安全的 Git ref 前缀并以 `/` 结尾；只影响新派生和校验的任务分支 |
| `YUXI_GIT_ALLOWED_GITEA_ORIGINS` | 开发 Compose 中为 `http://gitea:3000` | API、worker | 逗号分隔的精确 origin；包含 scheme、host 和可选 port，不接受 path、userinfo 或 redirect |

可用下面的命令生成 master key，并把输出写入部署环境文件：

```bash
openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\n'
```

同一套数据库必须长期使用同一个 key。更换或丢失 key 后，已有 Token 和 deploy private key 无法解密。修改配置后重新创建 API 和 worker：

```bash
docker compose up -d --force-recreate api worker
```

这些变量不传给 `sandbox-provisioner` 或动态 Sandbox。Gitea Token 和 deploy private key也不进入 Sandbox environment、UserWorkspace、Agent prompt、Run manifest、日志或 Git remote URL。

## 四类凭据和密钥

| 名称 | 来源与存放位置 | 是否敏感 | 用途 |
| --- | --- | --- | --- |
| Gitea SSH host key | Gitea SSH 服务持有私钥；connection 保存已核验的服务器公钥 `known_hosts` 行 | 公钥不敏感 | worker 校验远端服务器身份，防止连到错误主机 |
| Gitea API Token | 用户在 Gitea 创建；Yuxi 加密保存于 PostgreSQL | 敏感 | 查询仓库元数据、保护规则及管理 deploy key |
| 仓库 deploy keypair | 绑定仓库时由 Yuxi 自动生成；公钥注册到 Gitea，私钥加密保存于 PostgreSQL | 私钥敏感 | 可信 worker 对该仓库执行 fetch 和 push |
| `YUXI_GIT_CREDENTIAL_KEY` | 运维生成并放在 API/worker 环境中 | 高度敏感 | AES-GCM 加密 API Token 和 deploy private key，本身不参与 SSH 认证 |

停用仓库绑定后，远端 deploy key 被撤销，对应私钥密文引用被销毁；保留本地 bare repository、worktree 和远端任务分支。Connection 的 host key 与 deploy key 是两条不同信任链，不能互相替代。

## 开发 Compose 的 Gitea

仓库提供 `git-integration` profile，用于真实 Gitea integration 和本地功能验证：

```bash
docker compose --profile git-integration up -d gitea
```

默认 host HTTP 入口是 `http://127.0.0.1:3300`，host SSH 端口是 `2222`。端口占用时可在启动命令前设置 `YUXI_GITEA_HTTP_PORT` 或 `YUXI_GITEA_SSH_PORT`。

Yuxi API 和 worker 与 Gitea 位于同一 Compose network，因此 connection 使用容器可访问的 endpoint：

| 字段 | 开发值 |
| --- | --- |
| API Origin | `http://gitea:3000` |
| SSH Host | `gitea` |
| SSH Port | `2222` |

host 浏览器端口只用于打开 Gitea 页面，不能替代 API/worker 看到的容器 endpoint。`YUXI_GIT_ALLOWED_GITEA_ORIGINS` 必须包含表中的 API Origin。

开发 profile 的 Gitea 数据保存在 `${YUXI_STATE_DIR}/gitea-git-integration`。它是测试依赖，不随默认 `docker compose up` 启动。

## 资源关系

```mermaid
flowchart LR
    U[User] --> C[GitConnection]
    U --> P[Project]
    C --> R[ProjectGitRepository]
    P --> R
    P --> V[Root Conversation]
    V --> W[ProjectGitWorktree]
    R --> W
    W --> B[task branch]
    W --> D[worktree directory]
```

- `GitConnection` 是用户级 Gitea endpoint 和加密 API Token 记录，只能服务同一用户的 Project。
- `ProjectGitRepository` 是 Project 内仓库绑定，保存 alias、canonical 仓库身份、默认分支、deploy public key 和远端 key ID。
- `ProjectGitWorktree` 由 repository binding 与根 `runtime_scope_id` 唯一确定，保存分支、base/head/last pushed 和清理状态。
- Conversation、AgentRun 和 Project Git 表是任务状态权威；Git commit 保存代码进展。

第一版 provider factory 只接受 `gitea`。`github`、`gitlab` 和未知值会返回 unsupported-provider 错误。

## 仓库目录

Project Workdir 下的稳定布局是：

```text
repos/<repository-directory>/repository.git
repos/<repository-directory>/worktrees/<task-key>
```

`repository-directory` 由规范化 alias 加 repository binding ID 摘要生成。同一用户的多个 Project 可以共享一个 Workdir，这个摘要避免同名 alias 发生目录碰撞。Alias 和 owner/name 不直接拼接为宿主机路径。

`task-key` 是 `sha256(uid + runtime_scope_id)` 的稳定截断摘要。原始用户输入、Conversation ID 和 uid 不直接出现在目录名中。宿主机解析会拒绝 `repos` 路径中的符号链接穿越。

动态 Sandbox 仍挂载当前用户的整个 UserWorkspace。worktree 隔离 Git 分支、索引和任务目录，不提供同 uid 恶意 Agent 之间的强文件隔离。

## 分支分配

默认分支格式是：

```text
codex/task-<task-key>
```

`runtime_scope_id` 来自根 Conversation：

- Root Agent、Resume 和全部 SubAgent 复用同一个分支/worktree。
- 不同根 Conversation 获得不同分支/worktree。
- Project 新增 active 仓库后，下一次 Run 为当前根任务补建该仓库的 worktree。
- Run、Sandbox 或 Conversation 进入终态不会自动删除 worktree。

每次 Run 在 Agent 构图前从数据库重建仓库快照。已有 ready worktree 会校验确定性 identity、实际路径和当前分支后直接复用；缺失或失败的 worktree 才重新取得 lease 并准备。

## 仓库状态

| 状态 | 含义 | 后续动作 |
| --- | --- | --- |
| `provisioning` | 已保存绑定意图，worker 正在创建/认领 deploy key 和 bare repo | 等待 worker 或 reconciler |
| `active` | 可参与 Run preflight 和 push | 正常使用 |
| `provision_failed` | provision 失败，错误不包含 secret | 修正依赖后点击重试 |
| `deleting` | 已禁止新 preflight/push，正在撤销 key | 等待 worker |
| `delete_failed` | 撤权失败 | 恢复 Gitea/API Token 后重试 |
| `disabled` | 远端 key 已撤销，私钥密文已销毁 | 本地代码仍保留 |

Project 中存在未停用且非 `active` 的绑定时，Run 在 Agent 执行前重试，不向 Agent 提供部分仓库集合。

## Worktree 状态

| 状态 | 含义 |
| --- | --- |
| `preparing` | worker 持有可过期 lease，正在 fetch/import/add |
| `ready` | identity、分支和路径已回读，可交给 Agent |
| `prepare_failed` | 准备失败，下一次 Run 可重新准备 |
| `cleanup_pending` | 安全条件通过，已提交异步清理意图 |
| `cleanup_failed` | 文件系统或 Git 清理失败，可重试 |
| `removed` | 本地 worktree 已移除；远端分支保留 |

repository maintenance advisory lock 只串行化同一 bare repo 的 import、worktree add/remove 和 prune。repository operation session advisory lock 跨事务串行化同一 binding 的 provision 与撤权，进程退出时由 PostgreSQL 自动释放，避免 deploy key 创建和停用交错后遗留权限。不同仓库以及不修改共享 bare repo 的远端 staging fetch 可以并发。

## Agent 与可信 Git 操作

Agent 只通过 Sandbox `execute` 操作本地 worktree：`status`、`diff`、`add`、`commit` 等命令使用模型已有的 Git 能力，不需要额外 Skill。

远端 clone/fetch/push 在 API/worker 私有临时 staging repo 中执行。可信进程从数据库读取 canonical remote 和加密凭据，禁用 hooks、credential helper、SSH agent、交互输入、代理继承和 Agent 可写 Git config。

Root Agent 可以调用：

```text
git_push_branch(repository_alias, expected_head_sha)
```

工具无条件进入 HITL，即使 Agent 配置为 `always_trust`。SubAgent 不装配该工具。批准后 service 只允许数据库分配的任务分支、clean worktree、精确 HEAD、非保护分支和 fast-forward 更新；不接受 default branch、tag、delete、任意 refspec或 force push。

## API 参考

用户级 connection：

- `GET /api/git/connections`
- `POST /api/git/connections`
- `PUT /api/git/connections/{connection_id}/credential`
- `DELETE /api/git/connections/{connection_id}`

Project 资源：

- `GET|POST /api/projects/{project_id}/repositories`
- `POST /api/projects/{project_id}/repositories/{repository_id}/retry`
- `DELETE /api/projects/{project_id}/repositories/{repository_id}`
- `GET /api/projects/{project_id}/git-worktrees`
- `DELETE /api/projects/{project_id}/git-worktrees/{worktree_id}`

Token 是 write-only 字段。创建 binding、停用和清理返回 `202`；PostgreSQL 状态是持久事实，Redis/ARQ 只负责投递。发布失败时 reconciler 会扫描未完成状态并重新投递。

## 撤权与恢复

停用仓库或删除 Project 会先在数据库中写入 `deleting` 并阻止新操作，再撤销远端 deploy key。若 provision job 已创建 key 但发现 operation generation 已变化，该旧 job 会自行撤销刚创建的 key；delete job也会按确定性 title 与 public-key fingerprint 查找并撤销没有写回 ID 的 key。

远端 key 已存在、远端 branch 已等于 expected SHA 或本地路径已缺失时，重试通过回读收敛。只有 Gitea 撤权成功或确认 key 不存在后，服务才销毁本地 deploy private credential。

数据库、Gitea 和 POSIX 文件系统不共享事务。排障时以数据库状态、Gitea deploy key/branch 和真实 worktree 路径回读为准，不能仅依据 HTTP 200、日志或 ARQ job 结束状态。
