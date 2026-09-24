# Agent 专属沙盒与编码 CLI 协作

状态：核心双执行器 E2E 与异步 turn ownership 已实现；崩溃恢复真实集成与安全加固待迭代
类型：新增业务能力
主要 Owner：`backend/package/yuxi/agents/backends/sandbox/provider.py`

## 需求与失败场景

线程级临时 Sandbox 和一次性 execute 无法支持数字员工跨对话复用受控开发环境，也不能表达 `(uid, agent, project)` 身份、生命周期策略、执行租约、终端会话与 opencode/codex 协作。第一阶段以可信开发部署中的项目专属 Sandbox 跑通 Agent 驱动的轮次级多轮协作为目标；共享 Sandbox、单轮执行中的实时 steer 和更强凭据交换不属于当前承诺。

## 必须保留的业务语义

- 默认 Yuxi Agent 继续使用 ephemeral 行为；只有显式策略启用专属 Sandbox。
- 专属 Sandbox 以 uid、Agent、Project 和 generation 形成稳定身份，任何替代入口都不能绕过 scope 校验。
- 执行租约与生命周期状态有唯一 Owner，过期执行不能静默接管新 generation。
- 编码凭据由服务端解析并在 Sandbox 创建时通过进程环境注入 CLI；明文不得进入模型上下文、API 回显、事件、日志或持久 Workdir。短期凭据交换属于后续加固方向。
- Sandbox 删除和回收不修改持久 Workdir 字节。
- 编码会话绑定创建它的 Conversation 与 AgentRun；结果、事件和错误不得从相邻 Run 或会话猜测。
- 第一阶段编码协作只运行在 `persistent` 或 `resident` 项目专属 Sandbox；普通 Agent 未启用该能力时继续使用上游线程级 ephemeral 行为。
- Agent 通过 start、send、await、status 和 cancel 完成轮次级多轮协作。单个 turn 运行中的实时 steer 未实现，不构成当前能力。

## 与 Yuxi 的边界

Yuxi 继续拥有 Run、Workdir、Sandbox provider 和工具审批。元垒增加 Agent/Project 级 Sandbox 身份、策略、租约、终端代理、编码 CLI adapter 与持久会话事实；相关新增表属于 yuanlei schema 域。

## 稳定集成点

| 集成角色 | 当前 Owner | Yuanlei 语义 |
|---|---|---|
| 身份、策略与租约 | Sandbox provider、sandbox lifecycle service | 校验 scope、generation 和默认 ephemeral |
| 创建、回收与终端 | `docker/sandbox_provisioner/app.py` | 按策略回收并代理受控终端 |
| 编码会话 | `yuxi.coding` 与 coding services | 适配 CLI、事件和会话工具 |
| 凭据 | coding credential service | 服务端引用、环境注入和持久事件脱敏 |
| 持久化 | yuanlei schema migration | 专属 Sandbox、租约和会话事实 |

## 上游依赖

该能力依赖 Workdir identity、Run execution tree、Sandbox provider/provisioner 协议、tool approval、事件流和 deepagents 文件后端。上游修改这些 Owner 时必须验证 scope、generation、默认 ephemeral、密钥边界和 Workdir 保留语义。

## 合并判断

- 上游引入持久 Sandbox：比较身份维度、generation、回收、租约和 Workdir 后复用公共生命周期。
- 上游提供终端或编码 Agent：比较凭据、审批、事件和会话恢复，优先采用可证明等价的上游部分。
- 上游只改变 provider API：迁移适配层，不能放宽 scope 或密钥边界。
- 上游更换文件后端：重新证明删除 Sandbox 不删除持久 Workdir。

## 替换或删除条件

上游完整覆盖专属身份、生命周期、租约、终端、编码会话、凭据引用和持久文件边界后，可以分阶段删除元垒实现。产品取消专属 Sandbox 时仍需迁移或终结持久会话与租约，不能只移除 UI。

## 决策与证据

- [Agent 专属沙盒与生命周期策略](../decisions/proposed/2026-09-18-agent-dedicated-sandbox-lifecycle.md)
- [Agent 驱动编码 CLI 会话](../decisions/proposed/2026-09-18-agent-driven-coding-cli-sessions.md)
- [Agent 编码协作核心链路收敛](../decisions/proposed/2026-09-20-agent-coding-core-convergence.md)
- [编码 CLI 契约](../../../agents/coding-cli-contract.md)与[沙盒生命周期契约](../../../agents/sandbox-lifecycle-contract.md)
- `backend/test/e2e/test_agent_coding_collaboration_e2e.py` 已证明真实 OpenCode/Codex 两轮协作、会话归属和 Project Workdir 文件结果；unit、其他 integration/E2E 与 `scripts/probes/` 拥有其余当前证据。未验证范围以关联 Decision 的结果列为准。
