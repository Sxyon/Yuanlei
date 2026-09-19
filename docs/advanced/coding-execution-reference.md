# 编码执行配置参考

本页汇总编码执行（opencode / codex）的全部可配置项、接口与错误语义。操作步骤见[编码执行配置指南](./coding-execution-setup.md)，内部原理见[编码执行机制](../mechanisms/coding-execution.md)。

## 环境变量

全部由 Docker Compose 注入；修改后需重建对应容器：`docker compose up -d --force-recreate api worker`（provisioner 变量换成 `sandbox-provisioner`）。

| 变量 | 服务 | 默认 | 说明 |
| --- | --- | --- | --- |
| `YUXI_CODING_CREDENTIAL_KEY` | api、worker | 无（必填） | 编码凭据 AES-GCM 主密钥。32 字节 base64url；生成：`bash scripts/init.sh --ensure-coding-secret` |
| `SANDBOX_PROVIDER` | api、worker | `provisioner` | 沙盒承载方式；编码执行要求 provisioner 路径 |
| `SANDBOX_PROVISIONER_URL` | api、worker | `http://sandbox-provisioner:8002` | provisioner 地址 |
| `SANDBOX_PROVISIONER_TOKEN` | api、worker、provisioner | 无（必填） | provisioner 管理接口令牌 |
| `SANDBOX_PROVISIONER_BACKEND` | provisioner | `docker` | `docker` / `kubernetes` / `memory`（仅测试） |
| `SANDBOX_IDLE_TIMEOUT_SECONDS` | provisioner | 120（代码默认 600） | 全局空闲回收阈值；专属沙盒按创建时策略覆盖 |
| `SANDBOX_IDLE_CHECK_INTERVAL_SECONDS` | provisioner | 10 | 空闲巡检周期 |
| `SANDBOX_KEEPALIVE_INTERVAL_SECONDS` | provisioner | 30 | 保活周期 |
| `SANDBOX_EXEC_TIMEOUT_SECONDS` | api、worker | 180 | 沙盒内命令执行超时 |
| `SANDBOX_MAX_OUTPUT_BYTES` | api、worker | 262144 | 单次输出上限 |
| `SANDBOX_VIRTUAL_PATH_PREFIX` | api、worker | `/home/gem/user-data` | 沙盒虚拟路径前缀（与宿主/对象路径不可混用） |
| `SANDBOX_PROVIDER_RELEASE_LOCK_TIMEOUT_SECONDS` | api、worker | 30 | 释放作用域的锁等待 |
| `SANDBOX_PROVISIONER_DELETE_TIMEOUT_SECONDS` / `SANDBOX_RUNTIME_CLEANUP_TIMEOUT_SECONDS` | api、worker | 120 / 155 | 删除与清理超时 |

`.env.template` 是唯一清单来源；新增变量先加模板并同步 compose 注入。

## 系统配置（管理员可运行时修改）

设置 → 系统配置，持久化在 `config_options`，保存后立即生效（创建新沙盒时读取）。

| 配置键 | 默认 | 说明 |
| --- | --- | --- |
| `sandbox_dedicated_max_per_user` | 3 | 每用户专属沙盒上限（按记录数） |
| `sandbox_resident_max_per_user` | 1 | 每用户 resident 沙盒上限，保存时校验不得超过专属上限 |

## Agent / 项目配置键

写在 Agent 的 `config_json`；项目数字员工的 `config_overrides` 可按 key 浅合并覆盖。字段校验在保存边界执行，非法值返回 422。

```jsonc
{
  "sandbox": {
    "mode": "shared | dedicated",                  // 默认 shared；dedicated 才启用专属沙盒
    "lifecycle": "ephemeral | persistent | resident", // shared 下强制 ephemeral
    "resume_policy": "auto | confirm",             // 默认 auto
    "idle_suspend_seconds": 900                    // 可空；resident 固定不回收
  },
  "coding": {
    "executors": ["opencode", "codex"],            // 合法执行器白名单
    "default_executor": "opencode"                 // 必须属于白名单，否则解析为 null
  }
}
```

项目覆盖语义：

- 只提交被修改的段（`sandbox` / `coding` 整段替换，其它键继承）。
- `reset_fields: ["sandbox" | "coding"]` 移除对应覆盖段，回退 Agent 基础配置；不影响 `context` 字段重置。
- 保存 Agent/项目配置的接口分别为 `PUT /api/agent/{slug}` 与 `PUT /api/projects/{project_id}/agents/{agent_slug}`。

## HTTP 接口

| 方法与路径 | 权限 | 说明 |
| --- | --- | --- |
| `GET /api/user/coding-credentials` | 登录用户 | 掩码列表 + 自检（`availability`、`unavailable_reason`、`provider_display_name`） |
| `PUT /api/user/coding-credentials` | 登录用户 | 写入凭据；`source=manual/model_provider`，引用模式含 `model_provider_id`、`key_mode=inherit/custom`、`model` |
| `DELETE /api/user/coding-credentials?executor=&provider=` | 登录用户 | 删除；同执行器只保留一条 active |
| `GET /api/user/coding-credentials/model-providers` | 登录用户 | 供应商选择器：`provider_id`、名称、base_url、`is_enabled`、`credential_status`、chat 模型；**不含密钥** |
| `GET/PUT/DELETE /api/system/coding-credentials` | 管理员 | 全局凭据，语义同上 |
| `GET /api/coding/sandboxes` | 登录用户 | 专属沙盒列表与配额用量 |
| `GET /api/coding/threads/{thread_id}/sandbox` | 会话所有者 | 会话视角沙盒状态（非专属 `enabled=false`） |
| `POST /api/coding/threads/{thread_id}/terminal` | 会话所有者 | 预热并签发终端门票，可直接打开沙盒终端 |
| `POST /api/coding/sandboxes/{agent_slug}/{project_id}/provision` | 项目所有者 | 预热：创建或复用 runtime（先物化 Skill 投影） |
| `POST /api/coding/sandboxes/{agent_slug}/{project_id}/suspend` | 项目所有者 | 手动回收 runtime，保留 Workdir 字节 |
| `POST /api/coding/sandboxes/{agent_slug}/{project_id}/rebuild` | 项目所有者 | 强制回收后重建 |
| `POST /api/coding/sessions/{id}/terminal-ticket` + `WS /api/coding/sessions/{id}/terminal` | 会话所有者 | 终端门票与 WebSocket 中继 |

## 凭据模式与解析优先级

| 模式 | `source` | `key_mode` | 渠道来源 | 密钥来源 |
| --- | --- | --- | --- | --- |
| 手动 | `manual` | 空 | 行内 `provider`/`base_url` | 行内密文 |
| 引用·共用密钥 | `model_provider` | `inherit` | 供应商 | 供应商 `resolve_api_key`（直配 key 优先，其次 `api_key_env`） |
| 引用·单独密钥 | `model_provider` | `custom` | 供应商 | 行内密文（AAD 绑定 supplier id） |

解析顺序：**用户级 > 全局**；同层多条 active 时取最近更新的一条（写入路径保证一条）。指纹输入为解析后的 `provider_id/base_url/model` + 密钥短哈希 + 行版本，供应商换 key → 沙盒下次创建/重建自动生效。

## 错误码

| 错误 | 触发 | 表现 |
| --- | --- | --- |
| `credential_missing` | 执行器未配置任何凭据 | 工具返回 `coding_credential_missing: {executor}` |
| `credential_unavailable` | 引用不可用 | 带 `reason`：`provider_missing` / `provider_disabled` / `provider_key_missing` / `model_not_enabled` / `credential_key_missing` |
| `sandbox_quota_exceeded` | 创建新沙盒超配额 | 结构化错误，含 `limit_key/limit/current` |
| `sandbox_rebuild_required` | `resume_policy=confirm` 且处于 suspended | 需显式重建 |
| 503 + `YUXI_CODING_CREDENTIAL_KEY` 提示 | 密钥缺失/非法 | 保存凭据时直接展示配置指引 |
| 422 | 非法 `sandbox`/`coding` 值、引用未知模型、inherit 携带 key 等 | 保存边界拒绝，不落库 |

## 沙盒内 CLI 环境变量（M0 契约）

| 执行器 | 变量 |
| --- | --- |
| opencode | `OPENCODE_PROVIDER`、`OPENCODE_API_KEY`、`OPENCODE_PROVIDER_NPM`（默认 `@ai-sdk/openai-compatible`）、`OPENCODE_BASE_URL`、`OPENCODE_MODEL` |
| codex | `CODEX_API_KEY`、`CODEX_BASE_URL`、`CODEX_MODEL`、`CODEX_CONFIG_TOML`（可选） |

## 数据与迁移

| 结构 | 归属 | 引入版本 |
| --- | --- | --- |
| `coding_credentials`（含 `source`/`model_provider_id`/`key_mode`） | yuanlei schema | v5；引用列 v7 |
| `agent_sandboxes` / `agent_sandbox_events` | yuanlei schema | v4 |
| `coding_sessions` / `coding_session_turns` / `coding_session_events` | yuanlei schema | v6 |
| `agent_run_scopes`（Run → 专属 scope 映射） | yuanlei schema | v8 |

升级与校验命令：

```bash
docker compose run --rm storage-migrator     # 幂等；v6→v7 收敛同执行器多行，v7→v8 建 agent_run_scopes 映射
docker compose exec api python -c "import asyncio; from yuxi.storage.postgres.manager import pg_manager; asyncio.run(pg_manager.require_current_schema())"
```

## 常用命令

```bash
bash scripts/init.sh --ensure-coding-secret     # 生成/补全编码密钥（幂等）
bash scripts/init.sh --validate-security-env    # 校验 JWT / API Key / 沙盒 / 编码四把密钥
docker compose up -d --force-recreate api worker  # 环境变量生效
docker compose exec api python -m pytest test/unit/coding test/unit/routers/test_coding_credential_router.py
docker compose exec api python -m pytest test/integration/api/test_coding_credential_reference_api.py
```
