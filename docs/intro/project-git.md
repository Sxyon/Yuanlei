# 为 Project 配置 Git 仓库

本教程从一个可访问的 Gitea 仓库开始，为 Yuxi Project 创建 Git connection、绑定仓库，并让根任务在独立分支和 worktree 中开发。完成后，Agent 可以在沙盒内提交本地变更，并通过人工审批把任务分支推送到 Gitea。

## 准备条件

开始前确认以下条件：

- Yuxi 管理员已为 API 和 worker 配置 Git 加密密钥与 Gitea origin allowlist，并重新创建这两个服务。
- Gitea 仓库已有默认分支和至少一个 commit；空仓库不能创建任务 worktree。
- 当前用户拥有一个 active、selectable Project。
- Gitea API Token 可以读取仓库元数据和分支保护规则，并管理仓库 deploy key。
- Gitea SSH endpoint 可从 Yuxi API 和 worker 容器访问。

管理员配置项和容器网络示例见[Project Git 配置与分支参考](../advanced/project-git-reference.md)。

## 1. 准备 Gitea 信任信息

记录 Gitea 的三个地址字段：

| 字段 | 示例 | 用途 |
| --- | --- | --- |
| API Origin | `https://gitea.example.com` | API 和 worker 调用 Gitea REST API |
| SSH Host | `gitea.example.com` | worker 执行 fetch 和 push |
| SSH Port | `22` | 与 Gitea 返回的 canonical SSH URL 一致 |

从可信管理通道取得 SSH host public key，并核对管理员公布的 fingerprint。连接表单需要 OpenSSH `known_hosts` 格式，例如：

```text
gitea.example.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA...
```

非 22 端口的第一列使用 `[host]:port`。Yuxi 不自动接受首次出现的 host key；host、port 或 key 不匹配时 connection 创建或 Git 操作会失败。

在 Gitea 的用户设置中创建 API Token。Token 只在 connection 创建或更新时提交一次，页面和 API 响应不会返回原值。

## 2. 创建 Git connection

在 Yuxi 左侧 Project 列表中找到目标 Project，打开更多菜单，选择“Git 仓库”，再进入 **Connections** 页签。

填写：

1. 名称：用于识别这套 Gitea 连接。
2. API Origin：必须精确命中管理员配置的 allowlist。
3. SSH Host 和 SSH Port：必须与仓库 canonical SSH URL 一致。
4. SSH known-host key：粘贴已核对 fingerprint 的完整行。
5. Gitea API Token：粘贴本次使用的 Token。

点击“创建 connection”。成功后列表显示 connection 名称、provider 和 SSH endpoint，Token 输入框被清空。服务端会先调用 Gitea 验证 Token；验证失败、origin 未允许或 SSH 信任锚格式错误时不会保存 connection。

## 3. 绑定 Project 仓库

切换到 **仓库** 页签，选择刚创建的 connection，并填写：

- **Alias**：Agent 识别仓库的短名称，例如 `api` 或 `web`。同一 Project 内大小写不敏感唯一。
- **Owner**：Gitea 仓库 owner 或组织名。
- **Repository**：Gitea 仓库名，不包含 `.git`。

点击“绑定仓库”。Yuxi 先保存 `provisioning` 状态，再由 worker 创建每仓库独立的可写 deploy key、验证仓库元数据并初始化本地 bare repository。状态变为 `active` 后绑定完成；`provision_failed` 会显示错误摘要和“重试”按钮。

一个 Project 可以重复此步骤绑定多个仓库。Alias 只负责显示和工具查找，磁盘目录由服务端根据 alias 和 binding ID 派生。

## 4. 运行根任务

在这个 Project 中新建或继续一个根 Conversation，然后运行 Agent。worker 在构造 Agent 前为每个 active 仓库准备任务分支和 worktree。**Worktrees** 页签会出现对应记录。

每个根任务在每个仓库中获得：

```text
分支：codex/task-<task-key>
目录：repos/<repository-directory>/worktrees/<task-key>
```

Root Agent 与它启动的 SubAgent 使用同一组目录和分支。另一个根 Conversation 使用不同的 `task-key`，因此拥有独立 worktree，可以并行修改同一仓库。

Agent 提示词会列出 alias、沙盒路径、任务分支和基础分支。Agent 使用沙盒 `execute` 执行普通本地 Git 命令，例如：

```bash
cd /home/gem/user-data/<project-workdir>/repos/<repository-directory>/worktrees/<task-key>
git status
git diff
git add <files>
git commit -m "描述本次变更"
```

无需为这些基础命令安装 Git Skill。Agent 不能读取 deploy private key，也不通过自己的 `git push` 获得远端权限。

## 5. 审批并推送任务分支

Root Agent 完成本地 commit 后读取当前完整 SHA，并调用：

```text
git_push_branch(repository_alias="api", expected_head_sha="<40 位 commit SHA>")
```

这个工具总是要求人工审批。批准后，可信 service 重新检查 Run、Project、仓库绑定、任务 scope、当前分支、clean 状态和 HEAD，再读取 Gitea 分支保护规则并执行 fast-forward push。审批后如果 HEAD 或工作区发生变化，push 会被拒绝，需要 Agent 用新的 SHA 重新发起。

SubAgent 不拥有 push 工具。它可以在共享 worktree 中修改和 commit，最终由 Root Agent 发起审批。

## 6. 停用或清理

仓库页签中的“停用”会立即禁止新的 preflight 和 push，并异步撤销 Gitea deploy key。bare repository、worktree 和远端任务分支会保留。

Worktrees 页签中的“安全清理”只接受同时满足以下条件的记录：

- 该根任务没有非终态 AgentRun；
- working tree clean；
- 当前 HEAD 已成功推送。

清理完成后，本地 worktree 被移除，远端任务分支保留。同一 Conversation 后续恢复时，系统从本地 bare repository 中保留的任务分支重建 worktree。

## 常见失败

| 表现 | 检查项 |
| --- | --- |
| `git_not_configured` | API 和 worker 是否都有稳定的 `YUXI_GIT_CREDENTIAL_KEY` |
| connection 无法验证 | API origin allowlist、Token 权限、容器网络和 Gitea 状态 |
| SSH endpoint 不匹配 | Gitea 返回的 SSH URL、connection host/port 与 known-host 第一列 |
| 仓库长期 `provisioning` | worker 和 Redis 是否可用；等待 reconciler 重投或点击重试 |
| Run 在 Agent 开始前重试 | Project 中是否存在非 `active` 的未停用仓库，或 worktree 正由其他 worker 准备 |
| push 被拒绝 | 审批状态、完整 HEAD SHA、工作区 clean、分支保护和远端 fast-forward 条件 |

字段、状态、路径和安全边界见[Project Git 配置与分支参考](../advanced/project-git-reference.md)。
