# Agent 编码协作核心链路收敛

状态：proposed
类型：feature
Owner：backend/package/yuxi/services/coding_execution_service.py

## 问题

项目已经接入专属 Sandbox、编码凭据、opencode/codex adapter、持久编码会话、Agent 工具和人工终端，但这些组成部分尚未由项目对话中的真实 AgentRun 端到端证明。工具创建的编码会话没有稳定写入创建它的 Conversation 与 AgentRun；异步 worker 不能据此恢复同一项目配置和脱敏上下文；数据库提交与 ARQ 投递之间以及 running turn 失联后缺少恢复闭环。现有阶段计划同时追踪平台外围能力与核心链路，不能作为完成依据。

第一阶段产品目标是 Agent 在项目对话中选择 opencode 或 codex，连续完成两个 turn，并把真实文件写入该 Project Workdir。第一阶段要求 `persistent` 或 `resident` 项目专属 Sandbox，支持轮次级多轮与取消，不承诺单个 turn 内实时 steer。人工终端用于观察和排障，不与 Agent 形成并发双向输入协议。

## 提案

编码工具从当前 AgentRun 取得 Conversation、Project、Agent 和生效项目配置。新建编码会话写入 `conversation_id` 与 `parent_run_id`，后续 turn 验证会话仍属于同一用户、Project 和 runtime scope。同步工具和异步 worker 复用同一配置解析、凭据解析与 `SandboxLifecycleService.ensure_ready` 路径，任何入口不得旁路创建项目专属 Sandbox。

异步 turn 以 PostgreSQL 状态为投递意图。提交 pending turn 后投递 ARQ；投递失败保持可恢复事实。worker 对 running turn 使用有期限的执行 ownership，并在执行期间续租；周期恢复任务补投 pending turn并收敛失联 running turn。重复投递只有当前 owner 可以产生终态。

CLI 事件在写入 PostgreSQL 前按本次解析出的凭据值递归脱敏。事件、摘要、SSE 与错误使用同一脱敏边界；异步执行不得以空 secret 集合绕过该边界。当前凭据仍通过 Sandbox 进程环境注入，网络隔离、短期凭据和更细审批后续迭代。

旧 M0–M10 计划保留为历史实施记录。当前完成由本记录的两条真实 E2E 和负向恢复案例决定，不由模块存在、HTTP 200、工具注册或日志关键词决定。

## 替代方案

- 继续按 M11 扩展管理面、ACP 或 mid-turn steer：拒绝。现有核心用户路径尚未形成独立 oracle。
- 第一阶段同时支持共享 Sandbox：拒绝。共享进程态、凭据生命周期和跨 Run ownership 会扩大验收面；普通 Agent 的上游 ephemeral 行为保持不变。
- 只保留同步 turn：暂不采用。异步接口已经公开并拥有持久数据，必须恢复或明确移除，不能保留不可收敛的 running 状态。
- 把 Redis job 当作最终事实：拒绝。Redis 负责投递，PostgreSQL 拥有 turn 与执行 ownership。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 项目对话创建的编码会话绑定同一 Conversation、AgentRun、Project 与 runtime scope | 会话无法追溯或串到相邻 Run | coding tools + session repository | 真实 HTTP/worker E2E 后回读 PostgreSQL | 以另一 Conversation 或 scope 继续必须失败 | Passed |
| opencode 在同一会话完成两个 turn 并产生指定 Workdir 文件 | 工具存在但真实 CLI、续轮或文件落盘失败 | coding execution service + Project Workdir | 专用 Agent E2E，回读两个 turn、逐 turn CLI session ref 与文件内容 | 第二轮只引用上一轮文件，不重述文件名 | Passed |
| codex 在同一会话完成两个 turn 并产生指定 Workdir 文件 | provider 协议、resume 或配置解析失败 | coding execution service + Project Workdir | 与 opencode 相同的独立 E2E | 第二轮只引用上一轮文件，不重述文件名 | Passed |
| 同一会话不接受并发第二轮 | 重复 turn 或覆盖 active turn | coding session state machine | 并发发送集成测试 | 返回 busy 且不产生额外 turn | Not run |
| 不可用 codex 凭据不创建 turn | 不可执行请求留下幽灵 turn | credential service + coding tools | 凭据不可用集成测试 | 显式失败并回读无新增 turn | Not run |
| 同步、异步、预热和重建使用同一项目配置与 Sandbox 创建入口 | 项目覆盖丢失或创建无凭据容器 | credential service + sandbox lifecycle service | 集成测试检查项目覆盖及 provisioner 最终环境 | 旁路创建项目专属 Sandbox 被拒 | Not run |
| pending 投递失败可补投，失联 running turn 有可观察结局 | turn 永久 pending/running | coding turn recovery publisher | 真实 PostgreSQL、Redis 与 worker 集成 | 在 commit 后和执行中分别终止 worker | Not run |
| 持久事件、摘要、SSE 与日志不包含凭据 canary | 原始 CLI 事件先于脱敏落库 | coding execution service | 注入 canary 后回读 PostgreSQL 与事件流 | 编码及嵌套 payload 中的 canary 命中即失败 | Not run |
| 未启用编码协作的普通 Agent 保持上游线程级 ephemeral 行为 | 新能力改变默认 Run/Sandbox 行为 | sandbox provider + run worker | 默认 Agent E2E | 断言无专属 Sandbox 记录 | Not run |

已通过的双执行器 E2E 同时回读了会话归属、两个独立 completed turn、每个 turn 一致且非空的 CLI session ref 和最终文件内容；跨 Conversation、Project、runtime scope 与 Workdir 的续轮由 unit 负向案例覆盖。同步真实路径和冻结项目生效配置的异步快照 unit 已通过，但“同步、异步、预热和重建”这一完整主张尚无异步真实 provider E2E，因此保持 `Not run`。pending 补投、turn owner 租约/心跳、终态 fencing、活跃 owner 免误杀、准备失败立即收敛及嵌套事件脱敏已有 unit 证据；表中要求的真实 kill-worker integration、SSE 和日志 canary 尚未执行，完整主张保持 `Not run`。

## 风险

- opencode/codex E2E 依赖真实外部模型能力并产生费用；测试使用专用凭据、最小任务和可清理 Project。
- CLI 进程具有文件副作用，worker 在不确定是否仍运行时不能直接并发重试；ownership 过期后的恢复策略必须先确认旧进程结局。
- 当前异步恢复会补投 `pending`，并以 turn 级沙盒租约、heartbeat 与终态 fencing 保护 `running`；超过命令超时缓冲窗口且没有活跃 owner 的 turn 收敛为失败。尚未执行真实 kill-worker 集成，因此不能宣称可安全自动接管执行中的 CLI。
- 当前凭据存在于 Sandbox 进程环境，适用于可信开发部署；对不可信多租户开放前需要网络与凭据边界加固。
