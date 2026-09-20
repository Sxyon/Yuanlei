# Agent 专属沙盒与编码 CLI 协作

状态：实现已接入，提案证据待补齐
类型：新增业务能力
主要 Owner：`backend/package/yuxi/agents/backends/sandbox/provider.py`

## 需求与失败场景

线程级临时 Sandbox 和一次性 execute 无法支持数字员工跨对话复用受控开发环境，也不能表达 `(uid, agent, project)` 身份、生命周期策略、执行租约、终端会话与 opencode/codex 协作。直接把长期编码凭据注入 Sandbox 会暴露密钥并绕过服务端授权。

## 必须保留的业务语义

- 默认 Yuxi Agent 继续使用 ephemeral 行为；只有显式策略启用专属 Sandbox。
- 专属 Sandbox 以 uid、Agent、Project 和 generation 形成稳定身份，任何替代入口都不能绕过 scope 校验。
- 执行租约与生命周期状态有唯一 Owner，过期执行不能静默接管新 generation。
- 编码凭据通过可信服务端引用和临时交换使用，不以明文进入模型、日志、持久工作区或普通环境变量。
- Sandbox 删除和回收不修改持久 Workdir 字节。

## 与 Yuxi 的边界

Yuxi 继续拥有 Run、Workdir、Sandbox provider 和工具审批。元垒增加 Agent/Project 级 Sandbox 身份、策略、租约、终端代理、编码 CLI adapter 与持久会话事实；相关新增表属于 yuanlei schema 域。

## 稳定集成点

| 集成角色 | 当前 Owner | Yuanlei 语义 |
|---|---|---|
| 身份、策略与租约 | Sandbox provider、sandbox lifecycle service | 校验 scope、generation 和默认 ephemeral |
| 创建、回收与终端 | `docker/sandbox_provisioner/app.py` | 按策略回收并代理受控终端 |
| 编码会话 | `yuxi.agents.coding` | 适配 CLI、事件和会话工具 |
| 凭据 | coding credential service | 服务端引用、短期交换和脱敏 |
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
- [编码 CLI 契约](../../../agents/coding-cli-contract.md)与[沙盒生命周期契约](../../../agents/sandbox-lifecycle-contract.md)
- `backend/test/unit/services/test_sandbox_lifecycle_service.py` 与 integration、E2E 、`scripts/probes/` 拥有当前证据；依赖真实浏览器和账号的项目保持关联 Decision 中的 `Not run`。
