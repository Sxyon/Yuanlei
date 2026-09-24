# 编码执行机制（opencode / codex）

## 一句话理解

Agent 把「在专属沙盒里连续跑 opencode / codex」当作一个能力层：模型渠道与密钥是一条独立的**执行配置**，与聊天模型解耦；沙盒是**按用户+Agent+项目**复用的工作台，恢复与重建由指纹驱动；Agent 通过 `coding_*` 工具与终端使用它。

英文/实现命名约定：编码执行 = coding execution；执行器 = executor（`opencode` / `codex`）；专属沙盒 = dedicated sandbox；本轮 = turn。

## 关键组成

| 组成 | 事实 Owner | 职责 |
| --- | --- | --- |
| 凭据存储与加密 | `backend/package/yuxi/coding/credentials.py` | AES-GCM + AAD 绑定 `(scope, uid, executor, provider)`；密钥短哈希参与指纹 |
| 凭据用例与自检 | `backend/package/yuxi/services/coding_credential_service.py` | 三模式写入、解析优先级、可用性分类、供应商选择器 |
| 供应商事实 | 上游 `model_providers` | `provider_id` / `base_url` / `api_key` / `api_key_env` / `enabled_models`；本仓库只读，不改表结构 |
| 沙盒身份与生命周期 | `backend/package/yuxi/agents/backends/sandbox/`、`services/sandbox_lifecycle_service.py` | scope 派生、ensure_ready/suspend、配额、事件 |
| 执行租约 | 沙盒生命周期同域 | 同一沙盒串行执行；`run/coding_session/terminal` 为租约持有者 |
| 会话语义 | `services/coding_session_service.py`、`services/coding_execution_service.py` | session/turn 状态机、异步 turn、取消、预算 |
| 工具与终端 | `agents/toolkits/buildin/coding_tools.py`、`CodingTerminalModal` + WS 中继 | `coding_*` 工具、终端门票与字节流 |

## 凭据的两个维度

执行配置拆成两个可独立选择的问题：

1. **渠道从哪来**：手填，或引用模型供应商（`base_url` 与模型由供应商决定，支持模型级 `base_url_override`）。
2. **密钥从哪来**：手填密文、共用供应商密钥（`inherit`）、单独密钥（`custom`，只存本表）。

由此得到三种模式（手动 / 引用·共用密钥 / 引用·单独密钥）。引用是**活引用**：解析发生在每次沙盒准备时，供应商改 key、换端点、移除模型都无需回改编码凭据。

### 解析与优先级

```text
用户级凭据  >  管理端全局凭据
同层多条    →  取最近更新的一条（写入路径保证每执行器仅一条）
引用不可用  →  结构化失败（不静默跳过）
```

模型必须在供应商 `enabled_models` 中且 `type=chat`；`inherit` 不允许携带 key，`custom` 必须携带。写入边界同时校验模式组合与引用目标，非法值 422 且不落库。

## 指纹与自动重建

沙盒记录保存 `credential_fingerprint`。引用模式的指纹包含：解析后的 `provider_id`、`base_url`、`model`、**密钥短哈希**（`sha256(key)[:16]`，只参与哈希，不落库）与行版本。因此：

- 供应商换 key / 换端点 / 换模型 → 指纹变化 → 下次 `ensure_ready` 自动重建 runtime；
- 只改展示名等无关字段 → 指纹不变 → 不重建；
- 手动模式指纹算法保持原样，升级不会触发存量沙盒重建。

## 沙盒作用域与生命周期

- 编码执行要求 `sandbox.mode=dedicated`；作用域键 `agent-project:{uid}:{agent_slug}:{project_id}`，一个 runtime 只服务一个项目 Workdir。
- Run 行本身遵守上游不变量（`runtime_scope_id = conversation_thread_id`），专属执行 scope 由 yuanlei 表 `agent_run_scopes` 映射并在派发时绑定；resume / subagent 继承父 Run 的映射。
- `lifecycle=ephemeral|persistent|resident` 与 `resume_policy=auto|confirm` 决定回收与恢复；`resident` 跳过自动回收并占用常驻配额。
- 回收/重建**不删除 Workdir 字节**；重建必须赢过 generation 校验，旧 runtime 的写入会被拒绝。
- 首次创建 runtime 前会物化用户 Skill 投影（provisioner 校验目录存在且无符号链接）；配额在创建新绑定时强制（`sandbox_dedicated_max_per_user` / `sandbox_resident_max_per_user`）。

各阶段状态、事件与失败语义详见[沙盒生命周期契约](../agents/sandbox-lifecycle-contract.md)与[沙盒与文件系统机制](./sandbox.md)。

## 执行流（一次编码工具调用）

```text
coding_session_start
  → 读取 Agent/项目 coding 配置（executors/default_executor）
  → 校验选中执行器：已配置？引用可用？（不可用直接返回 reason）
  → 构建沙盒 env（OPENCODE_* / CODEX_*）与聚合指纹
  → ensure_ready：复用 / 恢复 / 按需重建 runtime
  → 获取执行租约，写入 turn 并执行 CLI
  → turn 终态回写会话与事件；SSE 投影 yuxi.coding_session_event
```

异步模式先入队 pending turn 并投递 worker，`coding_session_await` 收割结果；取消为进程级（`pkill` 活跃 CLI），随后收敛为 `cancelled`。终端通过短 TTL 门票 + WebSocket 中继接入同一沙盒。

## 自检、失败语义与默认路径

- 凭据列表实时自检并返回 `availability` 与 `provider_missing / provider_disabled / provider_key_missing / model_not_enabled / credential_key_missing`；不落状态字段，避免过期假象。
- 供应商停用/删除**不阻断**供应商运维，也不级联删除引用；编码工具在真正使用时返回带原因的错误。
- 未配置专属沙盒、未声明 `coding.executors`、未配置凭据的路径与上游行为一致：不创建专属记录、不注入编码 env、`coding_*` 工具返回未启用。

## 源码定位与验证

- [凭据服务](https://github.com/xerrors/Yuxi/blob/main/backend/package/yuxi/services/coding_credential_service.py) / [加密与指纹](https://github.com/xerrors/Yuxi/blob/main/backend/package/yuxi/coding/credentials.py)
- [沙盒生命周期](https://github.com/xerrors/Yuxi/blob/main/backend/package/yuxi/services/sandbox_lifecycle_service.py) / [provider](https://github.com/xerrors/Yuxi/blob/main/backend/package/yuxi/agents/backends/sandbox/provider.py)
- [编码执行服务](https://github.com/xerrors/Yuxi/blob/main/backend/package/yuxi/services/coding_execution_service.py) / [工具面](https://github.com/xerrors/Yuxi/blob/main/backend/package/yuxi/agents/toolkits/buildin/coding_tools.py)
- 单测：`backend/test/unit/coding/`；真实 HTTP：`backend/test/integration/api/test_coding_credential_reference_api.py`、`test_coding_sandbox_api.py`
- 契约与决策：[编码 CLI 契约](../agents/coding-cli-contract.md)、[编码凭据引用决策](../develop-guides/yuanlei/decisions/proposed/2026-09-20-coding-credential-provider-reference.md)、[实施计划](../develop-guides/planning/agent-coding-execution-plan.md)

**不要**：把密钥写回 `model_providers`（上游域）；用展示名而非 `provider_id` 判等；在引用解析失败时静默跳过；删除 Workdir 字节来「重建」。
