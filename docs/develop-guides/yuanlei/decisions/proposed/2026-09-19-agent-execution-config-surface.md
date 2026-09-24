# Agent 执行配置面：sandbox/coding 写入校验、覆盖重置与预热入口

状态：proposed
类型：feature
Owner：backend/package/yuxi/services/agent_config_service.py

事实 Owner 分工：写入校验归 `backend/package/yuxi/services/agent_config_service.py`；覆盖层重置归 `backend/package/yuxi/services/project_agent_service.py`；预热用例与路由归 `backend/package/yuxi/services/sandbox_management_service.py` 与 `backend/server/routers/coding_sandbox_router.py`。执行策略解析与生命周期归 `backend/package/yuxi/agents/backends/sandbox/policy.py` 与 `backend/package/yuxi/services/sandbox_lifecycle_service.py`；编码执行器白名单归 `backend/package/yuxi/coding/credentials.py` 与 `backend/package/yuxi/services/coding_credential_service.py`；Agent 配置读写归 `backend/package/yuxi/repositories/agent_repository.py`；前端表单归 `web/src/components/AgentExecutionConfigForm.vue` 与两个编辑弹窗；管理面板归 `web/src/components/CodingSandboxSettingsCard.vue`。本记录只闭合「配置如何被合法写入、覆盖如何恢复继承、专属沙盒如何预热」这三个面，不改变沙盒生命周期与编码会话语义（见《Agent 专属沙盒与生命周期策略》《智能体驱动沙盒内 opencode/codex 编码执行》）。

## 问题

### 当前事实（代码实证）

- **读取端已按 `config_json.sandbox` / `config_overrides.sandbox` 解析**：`resolve_agent_sandbox_policy` 读 Agent 配置与项目覆盖（`backend/package/yuxi/services/sandbox_lifecycle_service.py:65-79`），`parse_sandbox_policy` 对非法值显式失败（`backend/package/yuxi/agents/backends/sandbox/policy.py:46-70`）；编码白名单由 `CodingCredentialService.resolve_settings` 读 `coding.executors` / `coding.default_executor`（`backend/package/yuxi/services/coding_credential_service.py:220-248`）。
- **写入端不校验这两个段**：`filter_config_by_role`/`filter_declared_config` 只裁剪 `context` 内部字段，顶层 `sandbox`/`coding` 原样透传（`backend/package/yuxi/agents/context.py:99-130`）；`prepare_agent_config_write` 原先只解析 `context` 资源字段（`backend/package/yuxi/services/agent_config_service.py:13-45`）。非法值只在下一轮 Run 解析时爆炸，不在保存时拒绝。
- **项目覆盖无法整段恢复继承**：`reset_fields` 只构造 `{"context": {field: None}}` 再按声明字段清理（`backend/package/yuxi/services/project_agent_service.py:254-260` 原实现），不能移除 `config_overrides` 中的 `sandbox`/`coding` 段。
- **项目覆盖路由不映射 `ValueError`**：`update_project_agent` / `create_project_agent` 直接 await 用例，校验失败会变成 500 而不是 422（`backend/server/routers/project_agent_router.py:61-111` 原实现）；Agent 路由则已有 422 映射。
- **预热入口缺失**：管理面只有 suspend/rebuild（`backend/server/routers/coding_sandbox_router.py:30-59` 原实现），无法在首次运行前创建并验证专属沙盒；且真实 provisioner 要求 `skill-projections/{uid}` 目录存在且无符号链接（`docker/sandbox_provisioner/app.py:1063-1073`），管理面预热必须先物化 Skill 投影（`backend/package/yuxi/agents/skills/service.py:344`），否则 400。
- **前端没有配置入口**：Agent 编辑弹窗保存时只提交 `{context: changedAgentConfig}`（`web/src/components/model-management/AgentEditModal.vue`），项目覆盖表单只渲染 `configurable_items` 的 context 字段（`web/src/components/model-management/ProjectAgentConfigForm.vue`），用户无法给项目智能体开启专属沙盒。
- **合并语义**：`merge_agent_config_json` 顶层 `{**current, **patch}`（`backend/package/yuxi/repositories/agent_repository.py:417-424`），section 值整体替换；项目层与 Agent 层之间按 key 浅合并（`policy.py:38-43`）。

### 现状造成的使用问题

- 用户已能在管理面板看到专属沙盒列表，却找不到开启专属的入口；直接调用 API 写入非法值时错误延迟到运行期。
- 项目覆盖一旦写入 `sandbox`/`coding` 就无法恢复继承，只能再次写入一组「与基础相同」的冗余覆盖。
- 首次使用专属沙盒的用户可能因 Skill 投影目录缺失而创建失败（run 路径由 graph 构建时的 `sync_agent_context_skills` 兜底，管理面预热路径没有兜底）。

### 上游边界

- 上游现状：`agents.config_json` 顶层未声明的键可被任意写入且不校验；`project_agents.config_overrides` 的 reset 只覆盖 context；HTTP 管理面没有 sandbox 预热概念。
- 元垒改法：在共享写入入口 `prepare_agent_config_write` 对 `sandbox`/`coding` 做边界校验；`reset_fields` 将 `sandbox`/`coding` 视为整段可重置字段；新增 `provision` 用例与路由，并在管理用例内先物化 Skill 投影；前端新增「沙盒与编码」表单与预热/恢复继承入口。
- 合并注意：上游若重写 `prepare_agent_config_write`、`merge_agent_config_json`、项目覆盖 reset 或 `coding_sandbox_router`，必须保留 `sandbox`/`coding` 的校验失败 422、section 级 reset 与预热前置 Skill 投影；新增字段语义仍由 `policy.py` / `credentials.py` 单一解释。

### 目标

1. 写入 `sandbox`/`coding` 时非法值在保存边界以 422 拒绝，合法值原样持久；Agent 创建/更新与项目覆盖创建/更新共用同一校验。
2. 项目覆盖的 `reset_fields: ["sandbox"|"coding"]` 移除对应覆盖段，运行解析回退到 Agent 基础层；不影响 context 字段重置。
3. 管理面可预热专属沙盒（创建或复用 runtime），复用生命周期状态机与配额，失败返回 422/502 结构化错误。
4. Agent 编辑与项目覆盖均有「沙盒与编码」表单：回显生效值、只提交变化段、支持恢复继承、项目上下文提供预热按钮；沙盒面板为已有记录提供预热入口。

### 非目标

- 不改变 `parse_sandbox_policy` / `resolve_settings` 的解析语义与默认值（shared/ephemeral）。
- 不引入新的配置表或新的配置键；沿用 `config_json` / `config_overrides`。
- 不做字段级（如 `sandbox.lifecycle` 单独）写入校验以外的深合并；section 整体替换语义保持不变。
- 不改变预热之外的沙盒生命周期动作与编码会话执行语义。

## 提案

### 1. 写入校验

在 `prepare_agent_config_write` 中新增 `validate_agent_execution_config`：`sandbox` 必须是对象并交给 `parse_sandbox_policy`；`coding.executors` 必须是合法执行器列表，`coding.default_executor` 必须是合法执行器或 null（允许项目覆盖单独声明默认执行器、白名单继承）。校验失败抛 `ValueError`，两个 HTTP 入口都映射 422。

### 2. 覆盖层整段重置

`update_project_agent_view` 的 `reset_fields` 将 `sandbox`/`coding` 解释为 section 字段：从合并结果中 `pop` 对应段；其余字段维持原有 context 声明字段清理逻辑。

### 3. 预热用例与路由

`SandboxManagementService.provision`：解析项目 Workdir、策略与编码环境（先 `refresh_user_skill_projection_async(uid)`），调用 `SandboxLifecycleService.ensure_ready`（复用配额与 generation 语义），提交后返回带 generation 的视图；`POST /api/coding/sandboxes/{agent_slug}/{project_id}/provision`。`rebuild` 抽取同一 `_dedicated_environment`/`_finalize_ensure`，消除重复实现。

### 4. 前端配置面

新增 `web/src/utils/agentExecutionConfig.js`（规范化/差异/克隆）与 `web/src/components/AgentExecutionConfigForm.vue`（沙盒模式/生命周期/恢复策略/空闲回收/执行器白名单/默认执行器，可选预热按钮）；Agent 编辑弹窗新增「沙盒与编码」tab，项目覆盖弹窗新增同名 section（含「恢复继承」与「立即预热」，预热前先落盘改动）；沙盒面板对每条记录提供「预热」按钮；API 客户端新增 `codingSandboxApi.provision`。

## 替代方案

- **维持运行期校验**：实现成本最低，但非法值在保存时不报错、在下次 Run 才爆炸，且用户无法从 UI 发现错误；拒绝。
- **字段级深合并与逐键校验**：允许项目覆盖只改 `sandbox.lifecycle` 而不动其余键，但会改变现有 section 整体替换语义，并引入「删除键 vs 置空」的新歧义；当前浅合并已足够表达配置，拒绝。
- **只在前端限制取值**：后端仍接受任意值，绕过 UI 的写入（脚本、API 客户端）不受保护；违反「后端最终执行授权/校验」的既有边界，拒绝。
- **用 `null` 覆盖代替移除 section**：解析端需要新增「null 等于继承」语义，且会与「显式 shared」混淆；`reset_fields` 移除整段与 context 字段恢复继承语义一致，采纳。
- **预热复用 `rebuild`（先回收再创建）**：会无条件中断运行中的 runtime，违背预热「验证环境、不影响现状」的意图；改为 `provision` 走 `ensure_ready` 的复用语义，`rebuild` 保留强制回收语义。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 非法 `sandbox`/`coding` 在保存边界被拒且不落库（Agent 与项目覆盖一致） | 校验缺失或仅运行期失败 | `agent_config_service.py` + 两个路由 | `pytest test/unit/services/test_agent_config_service.py`；`pytest test/integration/api/test_project_agent_api.py::test_execution_config_validation_and_section_reset`（422 后 GET 断言无覆盖） | 未知 executor、非对象 section、负数 idle、`mode=bogus` 均 422；创建路径同样拒绝 | Passed |
| `reset_fields: ["sandbox","coding"]` 移除整段覆盖并保留 context 覆盖 | 重置误删 context 或无法回退 | `project_agent_service.py` | `pytest test/unit/services/test_project_agent_service.py`；同一 integration 用例 | 重置后 `config_overrides["context"]["system_prompt"]` 仍在；仅重置 context 字段不影响 section | Passed |
| 预热真实创建 runtime、复用已有 runtime、共享策略被拒 | 预热绕过配额/策略或重复建容器 | `sandbox_management_service.py` | `pytest test/unit/services/test_sandbox_management_service.py`；`pytest test/integration/api/test_coding_sandbox_api.py`（真实 provisioner：provision→suspend→provision） | 非专属策略 422、他人项目拒绝、重复预热仅一次 create | Passed |
| 预热前物化 Skill 投影，避免 provisioner 400 | 首个专属沙盒因目录缺失失败 | `sandbox_management_service.py` + `skills/service.py` | 同上单测（断言 refresh 调用）与真实 provisioner 集成 | 缺失投影目录时 provisioner 返回 400 的链路已在修复前复现 | Passed |
| 前端可配置并回显、只提交变化段、覆盖可恢复继承 | 表单丢字段或覆盖无法回退 | `AgentExecutionConfigForm.vue` + 两个弹窗 | `pnpm run lint:check`、`test:unit`（372 passed，含 5 个新用例）、`build`；`web/test/browser/agentExecutionConfig.js` 真实页面断言 | 清空执行器/默认值后保存只发送变化的 section；无变化时不发送 | Passed |
| 预热按钮只对专属模式可用且先保存再预热 | 未保存即预热命中旧策略或共享模式报 502 | `ProjectAgentEditModal.vue` + `CodingSandboxSettingsCard.vue` | 浏览器脚本断言按钮存在与可用；API 集成覆盖 422 语义 | 共享模式按钮禁用；保存失败中止预热 | Passed |

## 风险

- **上游同步冲突**：改动集中在 `agent_config_service.py`、`project_agent_service.py`、`coding_sandbox_router.py` 与项目覆盖路由；均保持最小 diff，语义仍由 `policy.py`/`credentials.py` 单一解释。
- **校验边界变化**：此前可写入的未知值（如 `coding.executors` 含未知名）现在 422；对存量脏数据仅在读取时继续按既有容错（过滤/回落 None），不做迁移。
- **预热副作用**：预热会真实创建容器并占用专属配额；管理面按现有配额与事件记录约束，Workdir 字节不受影响。
- **浏览器验证依赖本机环境**：`web/test/browser/agentExecutionConfig.js` 需要已登录的 playwright-cli 会话与一次性 fixture，未纳入 CI；真实页面截图仅作为本地证据。
