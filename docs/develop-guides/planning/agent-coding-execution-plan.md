# Agent 编码执行与专属沙盒：合并实施计划

版本：V0.1；状态：草稿；维护方式：随两份提案的评审结论更新，不独立发明需求

关联提案（验收主张的唯一来源，本计划只做阶段映射）：

- [智能体驱动沙盒内 opencode/codex 编码执行](../yuanlei/decisions/proposed/2026-09-18-agent-driven-coding-cli-sessions.md)
- [Agent 专属沙盒与生命周期策略](../yuanlei/decisions/proposed/2026-09-18-agent-dedicated-sandbox-lifecycle.md)

## 为什么合并

两份提案在 7 个面相互影响，分开排期会产生两套 supervisor、两次 yuanlei 版本提升和重复的等待/确认 UX：

1. **runtime scope 语义**：编码会话的绑定与跨 Run 恢复依赖专属沙盒的 scope 泛化（thread → agent_project）。
2. **执行租约**：会话 turn、终端接管与「每沙盒串行」必须是同一套租约，不能各建一套锁。
3. **凭证指纹**：编码凭据解析产出指纹，专属沙盒按指纹变化触发重建；这是同一契约的两个使用点。
4. **worker 监督基础设施**：会话 turn 泵送与沙盒保活/suspend/inventory 对账属于同一类周期任务，统一实现。
5. **yuanlei 迁移版本**：两批表格需要一次协商，否则版本顺延与交叉引用混乱。
6. **运行态 UX**：`sandbox_waiting`、`sandbox_rebuild_required` 同时服务于编码会话面板与普通 Run 的等待提示。
7. **配置与配额**：agent 配置页同时出现 coding 与 sandbox 区块，默认值与上限互相引用。

合并原则：契约先行（M0）、单一依赖序、单一 supervisor、默认行为不变（不配置则完全维持现状）、一次迁移协商。

## 依赖顺序

```text
M0 契约探针与接口冻结
 ├─► M1 凭据与配置基座 ─┐
 └─► M2 沙盒身份与生命周期核心 ─► M3 执行租约与串行 ─► M4 无头编码执行
                                                       └─► M5 持久编码会话
                                                            └─► M6 程序化通道与自主编排
                                                                 └─► M7 终端直连
                                                                      └─► M8 管理面与运维收尾
```

- M1 与 M2 在 M0 之后可并行（触碰文件不重叠：M1 在 config/凭据/前端设置，M2 在 sandbox/provisioner/worker）。
- M4 依赖 M3，而不是反过来；专属沙盒串行语义先成立，编码工具直接落在其上，避免二次改造。
- 每个阶段独立可交付、可回滚；所有新能力默认关闭，未配置专属的 agent 与未启用 coding 的 agent 行为逐阶段保持现状。

## 共享契约（M0 冻结，之后不允许各自解释）

1. **scope 与沙盒 id**：`thread:{uid}:{thread_id}` 或 `agent-project:{uid}:{agent_slug}:{project_id}`，`sandbox_id = sha256(scope_key)[:12]`；Run 的 `runtime_scope_id` 保持不透明字符串，`run_worker` 校验同时接受两种 scope 形态。
2. **执行租约**：字段、获取/心跳/释放/过期语义与 `sandbox_busy` 返回结构；接管前必须校验 generation；等待事件与超时错误结构固定。
3. **凭证/环境指纹**：定义 = 解析后的非密配置 + 密文版本 + 相关沙盒 env 贡献的哈希；由凭据解析输出，沙盒层只存储与比较，不自行计算。
4. **事件命名**：`yuxi.sandbox_waiting`、`yuxi.sandbox_rebuilt`、`yuxi.sandbox_rebuild_required`、`yuxi.coding_session_event`；未知事件记 `warning`，禁止静默丢弃。
5. **迁移版本协调**：一个发布窗口内新增表只升一次 yuanlei 版本；两批表格同期则一次性进 v4，分开则后者顺延并在两份提案中更新交叉引用。business/knowledge 域不动。

## 阶段

### M0 契约探针与接口冻结（状态：已完成）

- 交付：`docs/agents/coding-cli-contract.md`（CLI/镜像契约）、`docs/agents/sandbox-lifecycle-contract.md`（生命周期契约）、M0 共享契约记录（并入上述文档或实现说明）；可复跑探针脚本。
- 必须关闭的未知项：
  - CLI：`core` profile 下 opencode server 是否随入口启动；opencode XDG/CODEX_HOME 持久化变量是否生效；`run --format json`、`exec --json` 事件样本；codex 非交互审批语义；plan 能力开关；终端 URL 与沙盒 nginx 端口代理可达性。
  - 生命周期：provisioner 按沙盒 TTL 与 resident 跳过 reaper 的行为；容器跨 provisioner 重启后的 inventory 对账；执行租约在真实 worker 重启下的过期接管。
- 退出证据：文档中每条命令与样本都有真实运行输出；无法成立的项给出降级设计。无生产代码改动。

### M1 凭据与配置基座

- 交付：`coding_credentials`（yuanlei）+ AES-GCM 服务 + 用户/管理端 API + 设置页凭据卡；`agents.config_json.sandbox` 与 `project_agents.config_overrides.sandbox` 字段与合并逻辑；系统配额配置项；指纹实现（按 M0 契约）；输出脱敏。
- 退出证据：编码提案矩阵第 1、2 行；沙盒提案矩阵第 9 行；指纹契约单测。
- 迁移：若与 M2 同窗口，两批表一次进 v4；否则本阶段先升一次版本。

### M2 沙盒身份与生命周期核心（进行中）

- 进度：M2.1–M2.5 与 M2.6a 已落地（provisioner 生命周期字段、yuanlei v4 表与迁移、`SandboxScope`、策略/repository/lifecycle service、生命周期 supervisor、清理谓词分派）。M2.6b 运行接线已完成：FIFO 派发创建 Run 时按策略固化 `runtime_scope_id`（`resolve_dispatch_runtime_scope`），resume 继承父 Run 的 runtime scope（与 SubAgent 一致），`_validate_run_workdir_binding` 接受 agent-project scope 并校验 Agent/Project，`_BackendScope`/`ProvisionerSandboxBackend` 按 scope 取连接（专属走 `get_scope`），Run 准备阶段对 dedicated 策略执行 `ensure_ready`（confirm 暂以结构化失败阻断）。证据：affected 全量 1228 passed；M2 实现完成，专属沙盒真实链路（矩阵第 2/3/5 行）的集成验证随 M3/M4 一并补齐。下一阶段 M3 执行租约与串行。
- 交付：scope 泛化与 provider 身份校验；`agent_sandboxes` + `agent_sandbox_events`；provisioner 按沙盒 TTL/resident；`ensure_ready`/`suspend`/自动重建；生命周期 supervisor（保活、空闲 suspend、inventory 对账、孤儿租约清理）；ephemeral 默认路径回归。
- 退出证据：沙盒提案矩阵第 1、2、3、5、8、12 行；第 4 行的 auto 路径。
- 风险护栏：默认路径零行为变化；resident 与 persistent 受配额与面板约束。

### M3 执行租约与串行

- 交付：租约字段与获取/心跳/释放服务；等待事件与超时；generation fencing 与过期收敛；Run、编码 turn、终端三类持有者的接入点（后两者在 M5/M7 使用）。
- 退出证据：沙盒提案矩阵第 6、7 行。

### M4 无头编码执行（opencode + codex）

- 交付：适配器协议与两个实现；`coding_*` 工具；计划审批 interrupt；turn 状态与审计；最小会话卡片；在共享与专属 scope 都可运行。
- 退出证据：编码提案矩阵第 1、3、5、7、10 行；第 8 行的首层脱敏。
- 依赖：M1（凭据与指纹）、M3（专属 scope 下的串行）。

### M5 持久编码会话

- 交付：`coding_sessions/turns/events`；会话 supervisor（与 M2 同一 worker 基础设施）；跨 Run 恢复与 `resume_degraded`；`resume_policy=confirm` 重建确认路径；预算硬执行。
- 退出证据：编码提案矩阵第 4、6、8 行；沙盒提案矩阵第 4 行的 confirm 路径。

### M6 程序化通道与自主编排

- 交付：opencode serve SSE；codex 逐轮 JSON 流（shell session 增量读取）；mid-turn steer；审批升级；executor registry 与 `coding-executor` Skill；完整会话面板。
- 退出证据：编码提案矩阵第 10（steer/未知事件）、14 行；P4 交付清单对应的真实链路 E2E。

### M7 终端直连

- 交付：provisioner WS 代理与 ticket；xterm 面板；接管/交还（持执行租约）；Channel 流式输出。
- 退出证据：编码提案矩阵第 9、13 行；按 web 约定完成真实页面验证（浅/深色、loading、empty、error）。

### M8 管理面与运维收尾

- 交付：沙盒管理面板与事件时间线（手动 suspend/重建/解除专属）；配额与用量展示；metrics；策略切换后的遗留 scope 清理；ACP spike 结论。
- 退出证据：沙盒提案矩阵第 10、11 行；ACP spike 产出接入/放弃结论并回写对应提案。

## 证据与门禁

- 每个阶段的验收主张以两份提案的验收矩阵为准，本计划不复制、不新增主张；矩阵中的 `当前结果` 在实现阶段逐行更新。
- 最低证据按根 `AGENTS.md` 证据表：纯逻辑 unit；API/权限/持久化真实 HTTP integration；Run/沙盒/恢复 E2E；前端 lint + unit + build + 页面验证。
- 每个阶段结束前必须证明「未配置专属、未启用 coding 的默认路径行为不变」，防止能力回退。
- 提交前按仓库门禁执行工程信任检查、根级测试与 web 检查（见根 `AGENTS.md` 与 `docs/develop-guides/testing-guidelines.md`）。

## M0 结果（已完成，2026-09-18）

- 出证文档：[编码 CLI 契约](../../agents/coding-cli-contract.md)、[沙盒生命周期契约](../../agents/sandbox-lifecycle-contract.md)；可复跑脚本 `scripts/probes/coding_cli_probe.sh`、`scripts/probes/sandbox_lifecycle_probe.sh`。
- 已关闭的未知项：
  - opencode 原生会话续跑（`-s`）与 XDG 状态持久化成立；`plan` agent 原生存在；`run --format json` 事件含 tokens/cost/sessionID。
  - codex 原生会话（`CODEX_HOME` + `exec resume`）成立；**codex 0.139 只支持 Responses API**，SiliconFlow 不可用、DeepSeek 官方与 OpenAI/ARK 可用 → 凭据预检必须校验端点能力。
  - `core` profile 不自启 opencode server，程序化通道需显式启动 `serve` 并经 nginx 端口代理（`x-aio-proxy-port`）访问，provisioner HTTP 代理可直接承载。
  - provisioner 闲置回收为全局 TTL；`GET discover/touch/proxy` 会计入活动，supervisor 对账必须用 list；容器跨 provisioner 重启存活；generation fence 删除 409 语义可用。
  - 共享契约（scope、租约、指纹、事件命名、迁移版本）已按上文冻结。
- 仍未关闭、转入实现阶段验证：K8s 后端与 quiesce、reaper 与长命令竞争、租约过期接管的双写防护（M3 负向测试）、终端 WS 代理可达性（M7，不达标降级为程序化只读 + HTTP 输入）。
