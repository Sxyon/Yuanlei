# 编码执行配置指南（opencode / codex）

本指南面向运维与管理员，讲清从零开启 Agent 编码执行需要配置的四层：加密密钥 → 模型供应商 → Agent 沙盒与执行器 → 编码凭据，并给出验证与排障方法。机制原理见[编码执行机制](../mechanisms/coding-execution.md)，完整字段与接口见[编码执行配置参考](./coding-execution-reference.md)。

## 前置条件

- 已按[初始化脚本](https://github.com/xerrors/Yuxi/blob/main/scripts/init.sh)完成 `.env` 初始化，并成功执行过 `docker compose up -d --build`。
- 沙盒 provisioner 可用：`docker compose ps sandbox-provisioner` 为 running，`GET /health` 返回 200。
- 当前部署的 yuanlei schema 版本为 7（服务启动时自动校验；升级执行 `docker compose run --rm storage-migrator`）。

## 1. 配置编码凭据加密密钥（必做）

编码密钥只加密存储在 `coding_credentials`，不参与登录与 API Key 签发，需要单独一把 32 字节密钥：

```bash
# 方式一：自动生成并写入 .env（幂等，已有合法密钥时跳过）
bash scripts/init.sh --ensure-coding-secret

# 方式二：手动生成后填入 .env
openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\n'
# 然后设置 YUXI_CODING_CREDENTIAL_KEY=<上面的值>
```

写入后重建 api 与 worker 容器。**只执行 `docker compose restart` 不会刷新容器环境变量**（容器仍是配置前创建的那个），必须 `--force-recreate`：

```bash
docker compose up -d --force-recreate api worker
```

验证：

```bash
docker compose exec api sh -lc 'printenv YUXI_CODING_CREDENTIAL_KEY | wc -c'   # 输出应为 44（43 字符 + 换行）
```

未配置或密钥无效时，保存编码凭据会返回 **503**，前端会直接显示“请在 .env 设置 YUXI_CODING_CREDENTIAL_KEY …”。生产环境需要在 `.env.prod` 配置同一变量。

## 2. 配置模型供应商（管理员）

进入 **智能体管理 → 模型供应商**（或 设置 → 基本设置中的模型配置入口）：

1. 新建或编辑供应商，填写 `base_url` 与 API Key（`api_key` 直配优先，或填 `api_key_env` 指向环境变量）。
2. 在供应商的模型列表中启用至少一个 `type=chat` 的模型——编码凭据的引用模式只能从这里选择模型。
3. 保持 `is_enabled=true`。停用不会阻止保存引用，但编码凭据会立即标记为“供应商已停用”，运行时报结构化错误。

两条注意事项：

- **codex 需要 Responses API**：供应商端点必须支持 Responses 协议；`opencode` 使用 OpenAI 兼容端点。当前供应商配置没有协议标记，界面只做提示，真实可用性由运行结果证明。
- **同渠道多 key**：上游 `model_providers` 表一个条目一把 key。需要按 key 分账时可建多个条目（如 `sf-main`、`sf-budget`）；个人用户也可以不改供应商，直接在编码凭据使用“引用·单独密钥”。

## 3. 给 Agent 开启专属沙盒与编码执行器

编码执行要求 Agent 使用**专属沙盒**（thread 级共享沙盒不具备跨会话工作台语义）：

**智能体管理 → 智能体 → 编辑智能体 → 沙盒与编码**：

| 字段 | 建议值 | 说明 |
| --- | --- | --- |
| 沙盒模式 | 专属 | 按 `(用户, Agent, 项目)` 复用 runtime |
| 生命周期 | persistent（或 resident） | persistent 空闲回收后可恢复；resident 不自动回收（占用常驻配额） |
| 恢复策略 | auto | 回收后下次使用自动重建 |
| 空闲回收秒数 | 留空或 900 | resident 固定不回收；0 表示显式不回收 |
| 执行器白名单 | `opencode`、`codex` 按需 | 只有白名单内的执行器允许被编码工具选择 |
| 默认执行器 | 白名单内的一个 | 编码工具未显式指定时使用 |

保存后在项目上下文发起一次对话，运行期会按策略创建专属沙盒。执行 scope 为 `agent-project:{uid}:{slug}:{project_id}`，存放在 yuanlei 的 `agent_run_scopes` 映射并作为沙盒作用域；`agent_runs.runtime_scope_id` 保持会话线程 id（上游约束）。

## 4. 配置编码凭据（每个用户）

**设置 → 编码凭据**，为每个执行器配置一条（同一执行器只保留最新一条）：

| 模式 | 渠道/模型来源 | 密钥来源 | 适用场景 |
| --- | --- | --- | --- |
| 手动配置 | 手填 | 手填，加密存本表 | 私有端点、非标准模型 |
| 引用·共用密钥 | 跟随模型供应商 | 跟随供应商（供应商轮换后自动生效） | 复用平台已配置的渠道 |
| 引用·单独密钥 | 跟随模型供应商 | 单独填写，加密存本表 | 同一渠道按 key 分账 |

引用模式从下拉选择“供应商 + chat 模型”；密钥字段只在手动/单独密钥模式出现。列表会实时自检并显示状态：

- **可用**：供应商存在且启用、密钥可解析、模型仍在启用列表。
- **供应商已停用 / 已删除 / 缺少密钥 / 模型未启用**：保存时供应商被停用、或之后被管理员改动。此时不阻断其他功能，但编码工具调用会返回带原因的不可用错误。

引用是活引用：供应商换 key、改 `base_url`、移除模型后，编码凭据无需回改；指纹变化会在下次创建/重建沙盒时自动生效。管理员全局凭据（`/api/system/coding-credentials`）支持同样的三种模式。

## 5. 项目级覆盖（可选）

**智能体管理 → 项目智能体 → 编辑项目配置 → 沙盒与编码**：

- 覆盖只影响该项目内的运行，按 key 与 Agent 层浅合并（只提交被改动的段）。
- “恢复继承”会移除整个沙盒段或编码段的项目覆盖，回退到 Agent 基础配置。
- “立即预热”会先落盘当前改动，再按策略创建或复用专属沙盒，适合首次运行前验证环境；共享模式或未选供应商时按钮不可用/会提示。

## 6. 首次运行验证

1. 在上述面板点击“立即预热”，或在 **设置 → 专属沙盒** 对已有记录点击“预热”；列表应出现 `status=active` 的记录。
2. 在项目会话中让 Agent 调用 `coding_session_start`（`plan_first=true` 先跑只读计划轮）。
3. 需要交互时，从编码会话打开终端（`terminal-ticket` + WebSocket 中继）。
4. Workdir 文件不会因回收/重建而丢失；回收只释放 runtime。

## 7. 在会话里查看与直达沙盒

使用专属沙盒的项目会话，聊天头部会出现「沙盒」入口（`ConversationSandboxChip`）：

- 状态：运行中 / 已回收（下次自动恢复）/ 未创建（打开终端或首次使用自动预热）；
- 面板显示作用域、生命周期与最后活动；
- 「打开沙盒终端」会确保 runtime 就绪（按当前策略与凭据）并直接打开 Web 终端，**不要求先有编码会话**——Agent 没调用 `coding_*` 工具时也能进去看/操作 opencode 与 Workdir。

对应接口：

- `GET /api/coding/threads/{thread_id}/sandbox`：会话视角的沙盒摘要（非专属返回 `enabled=false`）；
- `POST /api/coding/threads/{thread_id}/terminal`：预热并签发终端门票（复用同一沙盒会话，不重复创建）。

## 8. 排障

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 保存凭据 503 | 密钥未配置/非法 | 按第 1 步生成并重建 api、worker |
| 已写入密钥但仍 503 | 容器是配置前创建的，`restart` 不刷新环境变量 | `docker compose up -d --force-recreate api worker`，再用 `printenv YUXI_CODING_CREDENTIAL_KEY` 核对长度为 43 |
| 列表“供应商已停用/已删除” | 引用目标被改动 | 在编码凭据切换到可用供应商，或恢复供应商 |
| 列表“模型未启用” | 供应商侧移除了该模型 | 重新选择模型，或让管理员启用 |
| “编码执行器不可用：引用的模型供应商未配置 API Key” | 供应商既无直配 key 也无可用环境变量 | 供应商页补 key，或编码凭据改用“单独密钥” |
| 工具报 `sandbox policy is not dedicated` | Agent 未开启专属沙盒 | 第 3 步改为专属并保存 |
| 工具报 `sandbox_quota_exceeded` | 超出每用户专属/常驻配额 | 系统设置调整配额或回收旧沙盒 |
| codex 运行即失败 | 端点不支持 Responses API | 更换供应商或改用 opencode |
| 预热 400/502 | provisioner 或 Workdir 异常 | `docker compose logs sandbox-provisioner api`，核对项目 Workdir |

## 相关文档

- [编码执行配置参考](./coding-execution-reference.md)：环境变量、配置键、API 与错误码速查
- [编码执行机制](../mechanisms/coding-execution.md)：凭据、指纹、沙盒与会话内部原理
- [编码 CLI 契约](../agents/coding-cli-contract.md)、[沙盒生命周期契约](../agents/sandbox-lifecycle-contract.md)
- [编码执行决策记录](../develop-guides/yuanlei/decisions/proposed/2026-09-20-coding-credential-provider-reference.md)
