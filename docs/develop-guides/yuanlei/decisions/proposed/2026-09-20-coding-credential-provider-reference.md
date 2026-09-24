# 编码凭据引用模型供应商（共用密钥 / 单独密钥）

状态：proposed
类型：feature
Owner：backend/package/yuxi/services/coding_credential_service.py

事实 Owner 分工：凭据加密、指纹与 env 映射归 `backend/package/yuxi/coding/credentials.py`；持久化与解析归 `backend/package/yuxi/services/coding_credential_service.py` 与 `backend/package/yuxi/repositories/coding_credential_repository.py`；引用目标的事实源是上游 `model_providers` 表，读取入口归 `backend/package/yuxi/models/providers/service.py`（`get_model_provider_by_id` / `resolve_api_key`），本提案不改其结构；HTTP 表面归 `backend/server/routers/coding_credential_router.py`；前端表单归 `web/src/components/CodingCredentialSettingsCard.vue`。沙盒重建由既有指纹机制触发（`backend/package/yuxi/services/sandbox_lifecycle_service.py:213-232`）。

## 问题

### 当前事实（代码实证）

- 编码凭据按 `(scope, uid, executor, provider)` 加密存储，`provider` 只是 CLI 环境变量里的自由文本标识；解析顺序 user > global，同层取 `list_active` 返回的第一条（按 executor/provider 字典序，`coding_credential_repository.py:31-40`、`coding_credential_service.py:169-205`）。
- 模型供应商（上游 `model_providers`）已有管理员配置的 `provider_id`、`base_url`、`api_key`（直配优先）/`api_key_env`、`enabled_models`（`{id,type,display_name}`）与 `is_enabled`；`resolve_api_key` 定义密钥解析优先级（`models/providers/service.py:217-223`）。该表按 fork 规则不可加列。
- 供应商 CRUD 与列表是 admin-only，且列表响应目前直接带明文 `api_key`（`model_provider_router.py:71-76`），不能作为普通用户的凭据来源接口。
- 用户现在必须把 key 从供应商页面复制到编码凭据卡；同一渠道多 key 只能靠建多个供应商条目，普通用户还没有供应商条目创建权限。

### 现状造成的使用问题

- 复制粘贴易错，且换渠道/换 key 后编码凭据不会自动跟随，产生"以为改了其实没改"的漂移。
- 同一 key 想在编码场景分账（外部供应商按 key 看额度）只能复制密钥，无法单一来源。
- 同一执行器可能存在多条凭据，实际生效项不可解释（字典序）。

### 上游边界

- 上游现状：没有"编码凭据引用模型供应商"的概念；供应商表结构、CRUD 与密钥存储方式不变。
- 元垒改法：编凭据行新增 `source`（manual/model_provider）、`model_provider_id`、`key_mode`（inherit/custom，仅引用模式）；引用解析复用 `resolve_api_key` 与 `enabled_models`，只读上游事实；新增用户可见的掩码供应商选择器端点；解析改为"同层取最新"，写入收敛为"每 scope 每 executor 一条"。
- 合并注意：上游若修改 `model_providers` 读取方式、`resolve_api_key` 语义或 `coding_credentials` 既有约束，必须保留引用解析的 fail-closed 分类与指纹输入（`key_hash` + 解析后的实际值）。

### 目标

1. 三种模式：手动（现状保留）/ 引用·共用密钥（密钥随供应商）/ 引用·单独密钥（渠道跟随供应商，密钥只存本表）。
2. 换 key、改 base_url、换模型后编码凭据自动跟随；指纹变化触发沙盒下次创建/重建。
3. 引用不可用时（供应商被删/停用、缺 key、模型未启用）不阻断供应商运维，只在凭据读取时标记状态、在编码工具调用时返回结构化原因。
4. 每 scope 每执行器只保留最新一条生效记录；存量多行迁移收敛为最近更新的一条。

### 非目标

- 不做"跟随 Agent 当前模型渠道"的动态解析（`source` 预留扩展位）。
- 不改上游 `model_providers` 表/接口；不做供应商面板引用计数、删除/停用阻断、审批与白名单。
- 不给普通用户暴露任何明文 key；选择器端点只返回掩码信息。
- 不变更手动模式已有指纹算法（避免升级即重建存量沙盒）。

## 提案

### 1. 数据与写入

- `coding_credentials` 增 `source`（默认 `manual`）、`model_provider_id`、`key_mode`（`inherit`/`custom`；manual 行为空）；yuanlei v6→v7。
- 写入规则：manual 要求 `provider` 与 `api_key`；引用要求 `model_provider_id` 且模型属于该供应商 `enabled_models`（type=chat）；`inherit` 不允许携带 key，`custom` 必须携带；引用行的 `provider` 列存 `provider_id`，`base_url` 不落库（解析时取供应商或模型覆盖）。
- 写入后停用同 scope 同 executor 的其他 active 行（软删，清空密文），实现"一条最新"。

### 2. 解析与可用性

- `resolve`：user > global；同层按 `updated_at/created_at` 取最新；manual 走原逻辑。
- 引用：`get_model_provider_by_id` → 不存在 `provider_missing`、`is_enabled=false` `provider_disabled`、`resolve_api_key` 为空 `provider_key_missing`、模型不在 `enabled_models` `model_not_enabled`；全部结构化失败（`CodingCredentialUnavailableError`）。
- 指纹：manual 不变；引用把解析后的 `provider_id/base_url/model`、密钥短哈希（`sha256(key)[:16]`，只参与哈希）与行版本纳入 `credential_fingerprint`。
- `list_masked` 每次读取实时自检，返回 `availability`（active/unavailable）、`unavailable_reason`、`provider_display_name`；不落状态字段。

### 3. 运行时与 UI

- `build_coding_environment` 返回 `env/fingerprint/unavailable/missing`：不可用不阻塞沙盒创建，但编码工具在选中该执行器时抛出带原因的不可用错误。
- 新增 `GET /api/user/coding-credentials/model-providers` 掩码选择器（enabled 与 disabled 都返回、只含 chat 模型、无 key）。
- 凭据卡三模式表单：引用模式选供应商与模型、密钥输入仅 manual/custom；列表展示模式、来源、可用性徽标与原因。

## 替代方案

- **纯前端预填**：key 仍需粘贴且普通用户拿不到 key，漂移问题未解；拒绝。
- **把编码 key 写回 `model_providers`**：违反 fork 规则且把编码密钥混入上游表；拒绝。
- **引用模式也复制密文到本表**：破坏"单一来源、自动跟随"，key 轮换仍要双改；拒绝。
- **引用不可用时阻断供应商删除/停用**：与"运维自由、自检兜底"的产品决策冲突；拒绝。
- **同执行器保留多条并显式优先级**：当前 UI/解析都没有优先级概念，一条最新更可解释；拒绝。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| manual 模式行为与指纹与现状一致 | 升级导致存量沙盒重建或写入回归 | `coding_credential_service.py` | `pytest test/unit/coding/test_coding_credentials.py`、`test/unit/routers/test_coding_credential_router.py` | 现有单测不改断言仍通过；manual 指纹不含 key_hash | Passed |
| 引用·共用密钥使用供应商 key/base_url/model，且随供应商变化 | 复制密钥或漂移 | 同上 + `models/providers/service.py` | 新单测：inherit 解析、改供应商 key 后指纹变化、改展示名不变化 | 供应商缺 key / 停用 / 删除 / 模型移除 → 结构化 unavailable | Passed |
| 引用·单独密钥渠道跟随、密钥只存本表 | 密钥写回上游或渠道漂移 | 同上 | 新单测：custom 解密与指纹、AAD 绑定 provider_id | inherit 携带 key 或 custom 缺 key → 写入 422 | Passed |
| 每 scope 每 executor 仅一条最新生效；存量多行收敛 | 旧配置继续生效或迁移失败 | repository + 迁移 | 单测：写入后旧行停用；`pytest test/unit/services/test_storage_migration.py`、`test/integration/services/test_schema_migration_version.py` | 迁移二次执行幂等；deleted 行清空密文 | Passed |
| 读取自检与运行时不可用原因一致 | 静默跳过或泛化报错 | `coding_credential_service.py` + `coding_tools.py` | 单测：list_masked 状态；工具调用抛 `credential_unavailable` 原因 | 供应商停用后列表标记且工具报原因，不阻塞沙盒创建 | Passed |
| 选择器端点无密钥泄漏且普通用户可用 | 越权或泄漏明文 | router | 单测 + 真实 HTTP：响应不含 `api_key`/密文；匿名 401 | 非管理员可读；disabled 供应商带标记返回 | Passed |
| 初始化与失败提示：缺密钥可一键生成，启动/前端提示可执行 | 克隆后仍 503 或只提示查看容器 | `scripts/init.sh` / `init.ps1`、compose 注入、`web/src/apis/base.js` | `python3 -m unittest scripts.test_init_coding_secret`（2 用例）；`pnpm run test:unit` 中 `api_boundary` 新增 2 用例；`bash scripts/init.sh --validate-security-env` | 非法 hex 被替换；非白名单 503 不泄漏明细；compose 缺值 fail-fast | Passed |

## 风险

- **生效项变化**：迁移把同执行器多行收敛为最新，原本按字典序生效的用户会切换配置；已在提案确认并写入迁移说明。
- **共享密钥成本**：任意用户可引用管理员配置的供应商 key 跑编码；依赖既有 `max_turns` 预算与后续异常 dashboard，白名单/审批留作扩展位。
- **codex 端点能力**：供应商配置无 Responses 协议标记，引用 codex 时 UI 仅提示、运行失败可见；不自动过滤。
- **上游同步冲突**：新增列都在 yuanlei 域；对上游读取只做只读调用，合并时保持 `resolve_api_key`/`enabled_models` 语义。
