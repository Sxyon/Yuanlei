# Agent 专属沙盒与生命周期策略

状态：proposed
类型：feature
Owner：backend/package/yuxi/agents/backends/sandbox/provider.py

事实 Owner 分工：沙盒身份、租约与生命周期记录归 `backend/package/yuxi/agents/backends/sandbox/`（本提案首要 Owner）；provisioner 的按沙盒回收策略与数据面归 `docker/sandbox_provisioner/app.py`；生命周期持久记录进 yuanlei 域，归 `backend/package/yuxi/storage/postgres/manager.py` 与 `backend/package/yuxi/storage_migration.py`；保活/收敛 worker 任务归 `backend/package/yuxi/services/`；配置入口复用 `backend/package/yuxi/storage/postgres/models_business.py` 的 `agents.config_json` 与 `project_agents.config_overrides`；管理面板归 `web/src/components/`。编码会话的多轮执行语义见《智能体驱动沙盒内 opencode/codex 编码执行》，本提案接管其中沙盒生命周期部分。

## 问题

### 当前事实（代码实证）

- **身份**：沙盒按 `sandbox_id = sha256("{uid}:{thread_id}")[:12]` 确定性派生，provider 缓存键为 `uid::thread`，连接自带 `workdir_path`（`backend/package/yuxi/agents/backends/sandbox/provider.py:25-34,82-90`）。
- **workdir 身份不变量**：get/release 都要求请求的 `workdir_path` 与连接/记录完全一致，否则 `SandboxIdentityMismatchError`（`provider.py:158-201,229-269`）。这是「一个容器服务一个 Project Workdir」的硬约束。
- **惰性创建与终态释放**：首次沙盒操作创建；根 Run 终态且同 scope 无活跃 Run 时删除 runtime，保留 Workdir 字节（`backend/package/yuxi/services/run_worker.py:299-396`）。
- **回收是全局策略**：provisioner 的 `SandboxIdleReaper` 只读全局 `SANDBOX_IDLE_TIMEOUT_SECONDS`（代码默认 600，compose 为 120），`CreateSandboxRequest` 不接受按沙盒 TTL，也没有 resident 概念（`docker/sandbox_provisioner/app.py:1768-1778,323-329`）。
- **保活只有访问时 touch**：`_should_touch` 基于本进程上次访问时间，没有后台心跳循环（`provider.py:95-171`）；API/worker 重启后未访问的沙盒只能靠 reaper 回收或下次 discover。
- **无持久所有权记录**：沙盒存在性只存在于 provisioner（Docker 容器/记录）和 provider 进程内缓存；没有数据库实体记录「哪个 agent、哪个项目、什么策略、期望状态」，因此无法做跨进程收敛、suspend/resume、配额与审计。
- **配置机制已具备**：`agents.config_json` 是 agent 级 JSONB，`project_agents.config_overrides` 是项目级覆盖层，manifest 加载时合并（`models_business.py:560,623`、`backend/package/yuxi/services/agent_run_manifest_service.py:167-174`）；无需新配置表。

### 现状造成的使用问题

- 每次 Run 都可能冷启动新容器（线程级作用域），环境准备、依赖安装、服务预热重复发生。
- 同一 agent 在多个会话/项目中的执行环境互不复用，长期协作（编码、数据管道）缺少稳定工作台。
- 环境变量与凭据只在创建时注入，轮换后无法自动生效；也没有「重建」这一显式语义。
- 活跃的沙盒可能被全局 reaper 误杀（全局 TTL 不感知业务意图），而希望常驻的沙盒无法表达。
- 同一 agent 的多个会话并发时，共享 `user-data` 的进程态没有串行约束，结果不可预测。

### 上游边界

- 上游现状：沙盒身份为线程级确定性 id、回收为全局 idle TTL、根 Run 终态释放、没有持久所有权记录与执行租约（证据见「当前事实」）。
- 元垒改法：新增 scope 形态与 `agent_sandboxes`/`agent_sandbox_events`（yuanlei 域），provisioner 创建请求新增可选策略字段，`run_worker` 清理谓词按 scope 分派；未配置专属的路径保持上游行为。
- 合并注意：上游若修改 `provider.py`、`run_worker` 清理、provisioner 创建/回收协议或 Project/Workdir resolver，必须在同一改动中保持 scope 三元校验、generation fence、默认 ephemeral 行为与「删除不改 Workdir 字节」不变量；yuanlei 迁移必须在 business 域收敛之后执行。

### 目标

1. 为 agent 配置专属沙盒：`(uid, agent_slug, project_id)` 唯一容器，跨会话复用，保留 workdir 身份不变量。
2. 生命周期可配：`ephemeral`（默认，现状）、`persistent`（闲置 suspend、下次使用重建）、`resident`（常驻，不自动回收），并可单独配置重建前是否需确认。
3. 同一沙盒执行串行：跨会话/跨 Run 通过执行租约排队，不发生并发命令执行。
4. 生命周期可观测、可管理：状态、generation、最后活动、租约归属、手动回收/重建、审计。
5. 与编码会话提案无缝衔接：opencode/codex 会话的保活、suspend、重建由本提案统一提供。

### 非目标

- 不改变 ephemeral 的默认行为（不配置专属时与现状完全一致）。
- 不做「每用户所有项目共用一个容器」的跨项目共享（进程态与 cwd 串扰）。
- 不删除、不修改 Workdir 持久字节（`删除不改 Workdir 字节` 是现有不变量，管理面同样遵守）。
- 不做容器预热池、不跨用户共享容器、不改变 `(user, agent, thread)` 的普通请求 FIFO。
- 不引入 Redis 作为租约事实源（Redis 只做唤醒投递，最终状态在 PostgreSQL）。

## 提案

### 1. 身份与作用域

新增作用域概念 `SandboxScope`：

- `thread`：现状，`scope_key = f"thread:{uid}:{thread_id}"`，`sandbox_id = sha256(scope_key)[:12]`，用于未开启专属的 agent。
- `agent_project`：`scope_key = f"agent-project:{uid}:{agent_slug}:{project_id}"`，`sandbox_id = sha256(scope_key)[:12]`，用于开启专属的 agent；一个容器只服务一个 Project Workdir，`workdir_path` 校验保持现有一致性语义。

Run 的 `runtime_scope_id` 按 agent 策略解析为对应 scope：专属时为 `agent:<agent_slug>:project:<project_id>`，否则保持会话线程。子 Agent 继承根 Run 的 scope（现状不变）。同一线程切换 agent 时，不同 agent 可分别命中各自 scope。

### 2. 生命周期模型

两个正交字段，落在 agent 配置 `config_json.sandbox`，项目级 `config_overrides.sandbox` 可覆盖：

```text
sandbox: {
  mode:            "shared" | "dedicated"     # 默认 shared
  lifecycle:       "ephemeral" | "persistent" | "resident"   # dedicated 时生效；shared 强制 ephemeral
  resume_policy:   "auto" | "confirm"          # persistent/resident 的 suspend 后重建方式
  idle_suspend_seconds: 1800                   # persistent 的空闲阈值，系统配置给默认与上下限
}
```

| 组合 | 语义 |
|---|---|
| shared + ephemeral（默认） | 完全保留现状：线程级容器，Run 终态释放 |
| dedicated + ephemeral | 专属身份容器；同 agent+project 的并行 Run 共享；无活跃 Run 后释放（适合并发会话热共享） |
| dedicated + persistent + auto | 保活；空闲超阈值后 suspend（删容器保记录）；下次使用自动重建 |
| dedicated + persistent + confirm | 同上，但重建前进入 `sandbox_rebuild_required` 中断，用户确认后重建并继续 |
| dedicated + resident | 不自动 suspend（provisioner 侧 TTL=never，supervisor 不做空闲回收）；仅手动/配额约束 |

状态机（`agent_sandboxes.status`）：`active → reaping → suspended → (rebuild) → active`，异常落 `error`。所有迁移在 PostgreSQL 行锁内完成，事件进 `agent_sandbox_events`。

### 3. 执行串行（执行租约）

- `agent_sandboxes` 持租约字段：`lease_owner_kind('run'|'coding_session'|'terminal')`、`lease_owner_id`、`lease_expires_at`、`lease_heartbeat_at`（默认 TTL 120s、心跳 30s，与 Run lease 同构）。
- 获取：事务内 `SELECT ... FOR UPDATE` 校验；被他人持有且未过期时返回 `sandbox_busy(owner, expires_at)`，调用方进入等待（事件 `yuxi.sandbox_waiting`），到 `sandbox_wait_timeout_seconds`（默认 600）仍不可得则显式失败，不排队堆积、不静默降级。
- 释放：Run 终态、coding session turn 结束、终端交还时释放；失联由过期收敛（复用现有 reconciliation 范式）。
- fencing：每次沙盒操作前校验记录 generation 与容器 generation 一致（provider 现有 touch-then-verify 语义），suspend/rebuild 后旧租约持有者的写入被拒绝。
- 公平性为 best-effort 轮询等待，不承诺严格 FIFO；普通请求 FIFO 仍在 `(user, agent, thread)` 层不变。

### 4. 保活、回收与重建

- **provisioner 扩展**：`CreateSandboxRequest` 增加 `lifecycle` 与 `idle_timeout_seconds`（`None`=全局默认，`0`=永不回收）；`SandboxResponse`/inventory 回传策略字段；`SandboxIdleReaper` 按记录策略判定，`resident` 直接跳过（`app.py:1757-1869`）。兼容：旧客户端不带字段时行为与现在完全一致。
- **worker 收敛任务**：新增 `SandboxLifecycleSupervisor`（ARQ 周期任务/durable job，复用现有 lease 与恢复范式）：
  1. 对 `active` 且有租约或近期活动的记录执行 `touch`（编码会话跨 turn 的保活归属此任务，不再由会话自己实现）；
  2. 对 `persistent` 且空闲超过 `idle_suspend_seconds` 的记录主动 suspend（释放容器、记 `suspended`）；
  3. 用 provisioner `GET /api/sandboxes` 权威 inventory 对账：容器已消失 → 记录 `suspended`；记录 `active` 但容器缺失 → 保持 `suspended` 等待下次使用重建；
  4. 释放孤儿执行租约。
- **回收兜底**：`persistent` 的 provisioner 侧 TTL 设为 `idle_suspend_seconds + 余量`，即使 supervisor 停摆也不会无限泄漏；`resident` 依赖配额与面板。
- **重建**：使用前 `ensure_ready(scope)`：
  - 记录 `active` 且 generation 匹配、凭证指纹一致 → 直接复用；
  - `suspended` 或指纹不一致 → `resume_policy=auto` 时重建（重新解析凭据注入 env、generation 更新、事件 `yuxi.sandbox_rebuilt`）；`confirm` 时先产生 `sandbox_rebuild_required` 中断，用户确认后重建；
  - 容器存在但 generation 不匹配（例如被 reaper 回收后重建过）→ 按 suspend 语义处理，不静默接管旧容器。
- **凭证指纹**：`agent_sandboxes.credential_fingerprint` 保存最近一次注入解析结果的哈希；凭据轮换、`agent_envs` 变更、镜像/策略变更都使指纹变化并在下次使用触发重建。

### 5. 配置、权限与配额

- 配置入口：agent 配置页新增「沙盒」区块（mode/lifecycle/resume_policy/idle 时长）；项目 agent 配置页提供覆盖；运行时由 manifest 合并后传入 provider。
- 权限：agent 所有者/有编辑权限者可开启专属；管理员通过系统配置设上限与默认值（`sandbox.dedicated.max_per_user`、`sandbox.resident.max_per_user`、默认 idle 阈值与上下限、等待超时）。超限在保存配置与创建容器两处都显式拒绝。
- 共享 agent（share_config）的专属沙盒仍按使用者的 uid 隔离，不跨用户复用。

### 6. 数据模型（yuanlei 域）

- `agent_sandboxes`：`id、uid、agent_slug、project_id、scope_key(unique)、sandbox_id(unique)、generation、mode、lifecycle、resume_policy、status、idle_timeout_seconds、credential_fingerprint、lease_owner_kind、lease_owner_id、lease_expires_at、lease_heartbeat_at、last_activity_at、last_keepalive_at、suspended_at、error_code、error_message、created_at、updated_at`；唯一约束 `(uid, agent_slug, project_id)`。
- `agent_sandbox_events`：`id、sandbox_id、kind(created|keepalive|suspend|rebuilt|rebuilt_confirmed|released|manual_suspend|manual_rebuild|error)、actor_kind、actor_id、payload_json、created_at`；有界保留，供管理面板时间线与审计。
- 版本：与《智能体驱动沙盒内 opencode/codex 编码执行》同期落地时共用一次 yuanlei 升级（新增表一起进 v4）；分开落地则按落地顺序递增，后者顺延。迁移幂等、FK 指向 business 域 users/projects、在 business 收敛之后执行。

### 7. provider 与 worker 改动

- `provider.py`：`_sandbox_key/sandbox_id` 泛化为 scope 派生；`SandboxConnection` 增加 `scope_kind/agent_slug/project_id`；`get` 增加专属路径的 agent/project 校验（严格于线程路径）；新增 `suspend(scope)`、`ensure_ready(scope)`、`get_lease/acquire/release` 服务入口。
- `run_worker._release_runtime_if_idle`：按 scope 类型分派——`thread` scope 保持现状；专属 scope 且 `lifecycle=ephemeral` 时在无活跃 Run 且无租约后释放；`persistent/resident` 不释放，交 supervisor。同一 advisory lock 与 `runtime_cleanup_pending` fence 保持。
- Run 阶段：等待租约、等待重建确认通过 `custom` 事件与 interrupt 表达（`yuxi.sandbox_waiting`、`sandbox_rebuild_required`），前端展示为运行阶段的显式等待，不断言成功。
- coding session 与终端接管：通过同一租约服务竞争；会话的 suspend 不再自行保活，`resume_degraded` 语义保留（原生 CLI 状态丢失时显式标记）。

### 8. 前端与管理面

- Agent 配置表单与项目覆盖表单：沙盒区块（含当前配额使用、预计资源影响提示）。
- 沙盒管理面板（新页面或 agent 管理页标签）：列表字段（agent、项目、状态、generation、最后活动、租约归属、策略）、操作（手动 suspend、立即重建、解除专属并回收）、事件时间线；所有手动操作走权限校验与审计。
- 运行态提示：等待沙盒、等待重建确认、已重建（含 generation 与耗时）；断线恢复沿用 Run SSE 的终态补偿语义。
- 明确不提供「清除工作区」操作：Workdir 字节归 Project/Workspace 所有，沙盒管理不触碰。

### 9. 与编码会话提案的关系

《智能体驱动沙盒内 opencode/codex 编码执行》中的沙盒保活、清理 fence、suspend/resume 归属本提案；编码提案保留会话自身的绑定、turn 协议、预算与 `resume_degraded` 判定。默认建议：编码会话在 `persistent` 或 `resident` 策略下运行；若 agent 仍是默认 `ephemeral`，编码会话启动时提示配置专属沙盒，但不强制阻断（按该提案的 suspend 语义兜底）。两提案的合并实施顺序与共享契约见 [Agent 编码执行与专属沙盒：合并实施计划](../../../planning/agent-coding-execution-plan.md)。

### 10. 失败与安全语义

- 崩溃与失联：租约过期可被接管；接管前必须校验 generation，避免双执行旧容器。
- 双写防护：suspend/rebuild 在行锁内完成并递增 fencing 事实（generation 更新），运行中的持有者下一次操作即失败并可恢复。
- 越权：scope 解析与容器使用都校验 `uid`、`agent_slug`、`project_id` 三元一致；跨用户/跨 agent/跨项目请求显式 404/403 语义，不做只读降级。
- 成本：resident 与 persistent 受配额、面板与事件监控约束；reaper 兜底策略保证 supervisor 停摆不无限泄漏容器。
- 兼容：未配置专属的 agent 走原线程逻辑；策略从专属切回共享时，遗留专属容器由 supervisor 在下一次收敛中释放（记录保留终态供审计）。

## 替代方案

1. **只做应用侧 keepalive，不改 provisioner**：全局 reaper 无法表达 resident 与按沙盒阈值，进程重启/收敛缺口无法闭合；本提案选择小步扩展 provisioner（自有代码），并保留旧请求兼容。
2. **用 Redis 租约代替 PostgreSQL 行级租约**：违反「Redis 不拥有最终业务状态」不变量，崩溃后 ownership 无法权威收敛。
3. **每 (uid, agent) 一个容器跨项目共享**：会放宽 workdir 身份不变量并共享进程态/cwd，跨项目串扰不可接受。
4. **每 Run 预热容器池**：资源浪费，且 workdir 与 agent 身份组合爆炸；不采用。
5. **维持纯 ephemeral**：无法支撑长期协作与跨 Run 会话，重复冷启动成本不可控。
6. **由 coding session 自己持有一个专用容器**：把生命周期塞进业务会话，导致非编码场景无法复用；生命周期应是沙盒层的一等能力。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 未配置专属时行为与现状一致（线程 scope、终态释放、无记录写入） | 默认路径被悄悄改变 | `provider.py` + `run_worker.py` | 回归：现有 `pytest test/unit/backends/test_sandbox_backends.py` 与 `test/integration/.../test_project_workdir_provisioner.py` | 默认 agent 运行后断言无 `agent_sandboxes` 记录、容器按原语义释放 | Not run |
| 专属沙盒按 `(uid, agent, project)` 唯一并在跨会话间复用 | 重复建容器或串到别的项目 | scope 派生 + repository | `pytest test/integration/sandbox_lifecycle/test_dedicated_scope.py` | 跨项目请求必须 `SandboxIdentityMismatchError`/404，不得复用容器 | Not run |
| `persistent` 空闲 suspend、使用前自动重建，Workdir 字节保留 | 声称保留但丢文件，或无法重建 | supervisor + provider | 集成：置短阈值等待 suspend → 再次使用断言 generation 变化、文件哈希不变、事件齐全 | 重建失败必须 `error` 可见，不得伪装成功 | Not run |
| `resume_policy=confirm` 未确认前不重建、不执行 | 确认流程被绕过 | interrupt 链路 | E2E：拒绝/超时/确认三条路径 | 拒绝后断言无新容器、无 turn 执行 | Not run |
| `resident` 不被 reaper 或 supervisor 自动回收 | 常驻容器被误杀 | provisioner reaper + supervisor | integration：真实 provisioner 运行超阈值后 `GET /api/sandboxes` 仍在 | 手动 suspend 后记录为 `suspended` 且容器删除 | Not run |
| 执行租约串行：并发 Run 不并行执行命令 | 双执行写坏工作区 | 租约服务 | 集成：两个 Run 争抢，断言一个等待一个执行、等待事件与超时错误可见 | 超时返回 `sandbox_busy`，不得静默并行 | Not run |
| 崩溃/失联后租约过期可收敛，旧 generation 写入被拒 | 僵尸持有者继续写入 | reconciliation + fencing | 集成：杀掉持有者，断言租约到期接管；旧容器操作被拒 | 接管后旧 owner 操作必须失败而非双写 | Not run |
| 凭证/环境指纹变化触发重建 | 旧 env 容器继续使用过期密钥 | `ensure_ready` + 指纹 | 集成：改 `agent_envs` 后下次使用断言重建与事件 | 指纹相同必须复用，不产生无谓重建 | Not run |
| 配额上限在配置保存与容器创建两处生效 | 绕过上限创建 resident | 配置服务 + 创建路径 | 单测 + 集成 | 超限返回结构化错误，不先创建后回滚 | Not run |
| 管理面手动 suspend/重建/解除专属均审计且不动 Workdir 字节 | 手动操作损坏用户数据 | 路由 + 事件表 | 集成 + 浏览器验证 | 操作后断言 Workdir 哈希不变、无删除接口 | Not run |
| 跨用户/跨 agent/跨项目越权访问被拒绝 | 通过 scope 猜测访问他人容器 | 路由 + provider 校验 | `pytest test/integration/sandbox_lifecycle/test_sandbox_authz.py` | 跨 uid 请求 404/403，无侧信道差异 | Not run |
| yuanlei 迁移幂等且不触碰 business/knowledge 域 | 重复迁移失败或越域改表 | `manager.py` + `storage_migration.py` | `pytest test/integration/services/test_schema_migration_version.py` | 连续两次迁移；断言上游域版本与表结构不变 | Not run |

## 风险

- **上游同步冲突**：改动集中在 provider、run_worker 清理谓词与 provisioner，均需最小 diff；逻辑放元垒模块，yuanlei 域版本纪律与上游同步流程照常执行。
- **provisioner 策略扩展的兼容性**：新增字段必须可选且默认等价现状；`resident` 跳过 reaper 需要 inventory/`/health` 可观测，避免「看不见的常驻容器」。
- **supervisor 单点与重启语义**：reaper 内存种子、容器跨 provisioner 重启存活、worker 多实例并发收敛都需要真实环境验证（列入 P0 探针）；租约与 fence 是防双写的最后屏障。
- **串行等待长尾**：同一沙盒被长任务占用会阻塞其他会话；通过等待事件、超时与面板可见性管理预期，必要时提供手动取消租约持有者。
- **常驻成本**：resident 无自动回收，依赖配额、面板与事件告警；默认策略保持 ephemeral，避免隐性资源增长。
- **迁移协调**：与编码会话提案共用 yuanlei 版本时需一次落地；若分开落地，后落者顺延版本并在两文档交叉链接更新。
- **策略切换遗留**：从专属切回共享或调整项目绑定后，旧容器释放依赖 supervisor 收敛，需要覆盖测试避免孤儿容器长期占用。
