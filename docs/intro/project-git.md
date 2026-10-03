# 为 Project 配置 Git 仓库

本教程从一个可访问的 Gitea 仓库开始，为 Yuxi Project 创建 Git connection、绑定仓库，并让根任务在独立分支和 worktree 中开发。完成后，Agent 可以在沙盒内提交本地变更，并通过人工审批把任务分支推送到 Gitea。

## 准备条件

开始前确认以下条件：

- Yuxi 管理员已为 API 和 worker 配置 Git 加密密钥与 Gitea origin allowlist，并重新创建这两个服务。
- Gitea 仓库已有默认分支和至少一个 commit；空仓库不能创建任务 worktree。
- 当前用户拥有一个 active、selectable Project。
- Gitea API Token 具有用户读取权限（`read:user`）和仓库读写权限（`write:repository`），用于验证当前用户、读取仓库元数据和分支保护规则，以及管理仓库 deploy key。
- Gitea SSH endpoint 可从 Yuxi API 和 worker 容器访问。

管理员配置项和容器网络示例见[Project Git 配置与分支参考](../advanced/project-git-reference.md)。

## 1. 准备 Gitea 信任信息

### 本地 Docker Compose 填写样例

此样例适用于 API、worker 与 `gitea` 服务位于同一 Compose 网络的开发环境。即使宿主机将 SSH 映射为 `2223:2222`，表单仍使用容器内端口 `2222`。浏览器通过 `http://localhost:3300` 打开 Gitea，connection 则通过 `http://gitea:3000` 调用 API。

| 表单字段 | 填写样例 | 说明 |
| --- | --- | --- |
| 名称 | `local_gitea` | 自定义连接名称 |
| API Origin | `http://gitea:3000` | 必须在管理员配置的 allowlist 中 |
| SSH Host | `gitea` | API 和 worker 可访问的容器服务名 |
| SSH Port | `2222` | Gitea 容器内 SSH 监听端口 |
| SSH known-host key | 下方命令取得的完整一行 | 包含主机、密钥类型和完整公钥 |
| Gitea API Token | `<新生成的 Gitea Token>` | 填写实际 Token，具有下方列出的权限 |

独立部署的 Gitea 使用 API 和 worker 可访问的实际地址，例如 API Origin 为 `https://gitea.example.com`、SSH Host 为 `gitea.example.com`、SSH Port 为 `22`。SSH endpoint 必须与 Gitea 返回的仓库 SSH URL 一致；管理员配置见[Project Git 配置与分支参考](../advanced/project-git-reference.md#开发-compose-的-gitea)。

### 取得完整 SSH known-host key

SSH known-host key 保存 **Gitea SSH 服务器的主机公钥记录**，用于确认远端服务器身份。记录由三部分组成，之间以空格分隔：

```text
主机标识 密钥类型 完整的 Base64 公钥
```

下面是一条完整格式的演示记录，使用虚构公钥，仅用于辨认各部分；实际填写时使用自己 Gitea 的输出：

```text
[gitea]:2222 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAABAgMEBQYHCAkKCwwNDg8QERITFBUWFxgZGhscHR4f
```

| 部分 | 演示值 | 含义 |
| --- | --- | --- |
| 第一部分 | `[gitea]:2222` | 与表单 SSH Host、SSH Port 一致；非 22 端口使用 `[host]:port`，22 端口直接写 host |
| 第二部分 | `ssh-ed25519` | 公钥类型，也可能是 `ssh-rsa`；保留实际输出的类型 |
| 第三部分 | `AAAAC3NzaC1lZDI1NTE5AAAAIAABAgMEBQYHCAkKCwwNDg8QERITFBUWFxgZGhscHR4f` | 完整公钥内容，保留实际输出的全部字符 |

**表单要粘贴整行，三个部分都要保留。** 只粘贴第三部分，或粘贴 `SHA256:…` 指纹，会导致 `ssh_known_host_key 与 SSH endpoint 不匹配`。公钥内容不能截断或用 `...` 代替。

从仓库根目录运行下面的命令，直接在 API 容器中读取候选记录，输出第一列就是 `[gitea]:2222`：

```bash
docker compose exec -T api ssh-keyscan -T 5 -p 2222 -t rsa gitea 2>/dev/null
```

命令选择开发 Gitea 支持的 RSA 主机密钥。复制以 `[gitea]:2222 ssh-rsa` 开头的完整一行。通过 Gitea 主机控制台或管理员公布的信息核对 fingerprint；`ssh-keyscan` 输出本身只代表远端返回的候选公钥。可用下面的命令计算候选公钥的 fingerprint，核对时使用它，表单仍填写完整记录：

```bash
docker compose exec -T api ssh-keyscan -T 5 -p 2222 -t rsa gitea 2>/dev/null | ssh-keygen -lf -
```

如果从宿主机扫描 `127.0.0.1:2223`，输出第一列为 `[127.0.0.1]:2223`。核对公钥后，只把第一列改成 `[gitea]:2222`，保留密钥类型和公钥内容，再填入 connection。

### 创建具有用户读取权限的 Token

在 Gitea **用户设置 → 应用 → 管理访问令牌** 中创建 Token。本地样例可打开 `http://localhost:3300/user/settings/applications`。选择以下权限，再生成并复制 Token：

| 权限类别 | 选择 | Scope | 用途 |
| --- | --- | --- | --- |
| user | 读取 | `read:user` | 创建 connection 时调用 `/api/v1/user` 验证当前用户 |
| repository | 读写 | `write:repository` | 查询仓库、分支保护规则，管理 deploy key 和合并请求 |

**user 读取权限必须勾选。** 只有 repository 权限时，Gitea 的 `/api/v1/user` 会返回 `403 Forbidden`，页面显示 `无法验证 Gitea connection`。此步骤通过 HTTP 验证 Token，修改 SSH 端口无法解决该权限错误。账号本身还需拥有目标仓库的相应权限。

Token 只在 connection 创建或更新时提交一次，页面和 API 响应不会返回原值。

## 2. 创建 Git connection

在 Yuxi 左侧 Project 列表中找到目标 Project，打开更多菜单，选择“项目设置”，进入 **资源 → Git 资源 → Connections** 页签。

填写：

1. 名称：用于识别这套 Gitea 连接。
2. API Origin：必须精确命中管理员配置的 allowlist。
3. SSH Host 和 SSH Port：必须与仓库 canonical SSH URL 一致。
4. SSH known-host key：粘贴已核对 fingerprint 的 Gitea **服务器主机公钥记录**完整行。
5. Gitea API Token：粘贴本次使用的 Token。

点击“创建 connection”。成功后列表显示 connection 名称、provider 和 SSH endpoint，Token 输入框被清空。服务端会先调用 Gitea 验证 Token；验证失败、origin 未允许或 SSH 信任锚格式错误时不会保存 connection。

## 3. 绑定 Project 仓库

切换到 **仓库** 页签，选择刚创建的 connection，并填写：

- **Alias**：Agent 识别仓库的短名称，例如 `api` 或 `web`。同一 Project 内大小写不敏感唯一。
- **Owner**：Gitea 仓库 owner 或组织名。
- **Repository**：Gitea 仓库名，不包含 `.git`。

点击“绑定仓库”。Yuxi 先保存 `provisioning` 状态，再由 worker 创建每仓库独立的可写 deploy key、验证仓库元数据并初始化本地 bare repository。状态变为 `active` 后绑定完成；`provision_failed` 会显示错误摘要和“重试”按钮。

仓库 deploy key 不需要手工创建或粘贴。绑定时，Yuxi 自动生成一对独立的 Ed25519 密钥：公钥通过 Gitea API 写入仓库的 Deploy Keys，私钥由 `YUXI_GIT_CREDENTIAL_KEY` 加密后保存在 PostgreSQL。停用仓库绑定时，worker 撤销 Gitea 中对应的 deploy key，并销毁数据库中的私钥密文引用。

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
| `无法验证 Gitea connection` | 查看 Gitea 日志；`GET /api/v1/user` 返回 `403` 且命中 `tokenRequiresScopes` 时，为 Token 增加 `read:user`；其他情况检查 API origin allowlist、容器网络和 Gitea 状态 |
| `ssh_known_host_key 与 SSH endpoint 不匹配` | 粘贴包含主机、类型、公钥三个部分的完整行；本地 Compose 第一列为 `[gitea]:2222` |
| 仓库 SSH URL endpoint 不匹配 | Gitea 返回的 SSH URL 与 connection host/port 是否一致 |
| 仓库长期 `provisioning` | worker 和 Redis 是否可用；等待 reconciler 重投或点击重试 |
| Run 在 Agent 开始前重试 | Project 中是否存在非 `active` 的未停用仓库，或 worktree 正由其他 worker 准备 |
| push 被拒绝 | 审批状态、完整 HEAD SHA、工作区 clean、分支保护和远端 fast-forward 条件 |

字段、状态、路径和安全边界见[Project Git 配置与分支参考](../advanced/project-git-reference.md)。
