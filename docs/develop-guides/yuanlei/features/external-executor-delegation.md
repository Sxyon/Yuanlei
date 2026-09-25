# 外部执行器委派与 Multica 桥接

状态：提案，未实现
类型：新增业务能力
主要 Owner：backend/package/yuxi/services/delegation_service.py

## 需求与失败场景

元垒要把「把任务委派给外部执行者并回收结果」收敛成统一抽象，并把 Multica 接成其中一种渠道。codex/opencode 编码协作与 Multica 套同一「可委派执行者」接口；Multica 可作为来源渠道与执行渠道，双向交互但不成为元垒事实源；无 Multica 时元垒议题/任务仍独立工作。

失败场景：委派入口分叉，codex/opencode 与外部渠道各写一套执行事实；外部执行结果无法作为可追溯的 Yuanlei 事实回收，只能靠人复述；Multica 镜像被当作第二状态 Owner 反向写元垒 canonical 状态；缺少 Multica 配置时整条协同能力不可用并牵连元垒议题/任务；远端文本结果越界写入 Project Workdir 之外的路径。

## 必须保留的业务语义

- 元垒拥有规范化议题/任务的唯一事实源；Multica 只产生 `proposed` 治理行，经人审核才成为 canonical，且无反向写 canonical 的路径。
- 外部执行只产生委派事实与回收结果，不改变来源议题/任务的审核状态，不复制外部执行终态为 canonical。
- 不为外部执行伪造上游 `agent_runs` 行；委派结果绑定发起 Run，产物作为 Artifact 物化并通过既有 artifact 管线暴露。
- 统一委派接口与既有 `coding_*` 是同一执行事实的两个入口：`coding_sessions` 仍是 codex/opencode 的会话与执行事实 Owner，不新增平行会话表。
- 能力差异由 `capabilities()` 显式声明，不可用即结构化失败，不静默降级或替换基底。
- 非终态委派必须有显式 owner 与 lease，崩溃后可观察收敛；结果不得从相邻 Run 或会话猜测。
- 渠道凭据加密、fail-closed、明文不进 DB/API/日志/事件；远端结果写入 Workdir 前按现有路径边界校验。
- 无 Multica 凭据时 Multica 适配器不注册，治理、Channel、Run 与 coding 路径独立可用。

## 与 Yuxi 的边界

上游 Yuxi 拥有 Run、Conversation、队列、执行、事件链路与用户自建定时任务；元垒不在这些域新增语义。元垒新增的是委派编排用例、统一执行器接口与适配器、Multica 拉取式入向归一与出向桥接、渠道加密凭据、只读委派读模型与 Agent 工具面，以及 yuanlei 域的 `channel_delegations` 表与幂等迁移。上游文件只做最小 diff，执行基底能力（沙盒会话、Channel 入口、治理事实）复用既有实现。

## 稳定集成点

| 集成角色 | 当前 Owner | Yuanlei 语义 |
|---|---|---|
| 统一委派接口与编排 | `backend/package/yuxi/services/delegation_service.py`、`backend/package/yuxi/delegation/` | 适配器注册、委派事实、收集租约、统一读模型 |
| 沙盒 CLI 适配 | `CodingExecutionService`、`coding_sessions` 仓储 | `SandboxCodingExecutor` 复用会话事实，不新增平行表 |
| Multica 适配 | 新增 Multica 适配器与渠道凭据服务 | 拉取式入向归一为 proposed；出向创建/轮询/回收 |
| 入向归一与审核 | `backend/package/yuxi/services/governance_service.py` + 治理四表 | 只产生 `proposed`，复用外部标识唯一约束 |
| 委派事实 | 新增 `channel_delegations`（yuanlei 域） | 外部渠道委派记录与只读状态投影 |
| 结果产物 | `backend/package/yuxi/services/artifact_service.py` | Workdir 边界内物化，经既有授权路径暴露 |
| 工具门控 | `backend/package/yuxi/agents/toolkits/service.py`、`tool_approval.py` | 仅根 Agent 可见，审批与白名单沿用 coding 模式 |

## 上游依赖

依赖 Run 与 `RunOrigin` 的 `source`/`channel`/`external_id` 语义、Channel 消息入口、治理四表与审核边界、`coding_sessions` 会话事实、Sandbox provider 与执行租约、artifact 授权路径、工具审批与 Skills 依赖门控、用户自建定时任务。上游修改这些 Owner 时必须重验委派绑定、只读投影、路径边界与「不反向写 canonical」语义。

## 合并判断

- 上游提供通用外部执行/委派抽象：比较事实 Owner、恢复与回收语义后，优先采用可证明等价的上游部分并缩小本差异。
- 上游提供 Multica 或同类渠道桥接：比较 proposed 生命周期、反向写边界与凭据边界，等价时替换本实现。
- 上游改变 Run/Channel/治理/artifact 任一 Owner：迁移适配层，不放宽「外部不成为事实源」「不伪造 agent_runs」「Workdir 边界」三条不变量。

## 替换或删除条件

当上游拥有等价的外部执行器委派接口与渠道桥接，并能表达 proposed→审核→canonical、外部不反向写、结果绑定发起 Run 与 Workdir 边界产物时，可删除本实现。删除前需要新的 Decision 说明 `channel_delegations` 既有数据的迁移与消费侧替换路径。

## 决策与证据

- Decision：[外部执行器委派抽象与 Multica 桥接](../decisions/proposed/2026-09-25-external-executor-delegation-multica-bridge.md)。
- 既有可复用事实：[Agent 专属沙盒与编码 CLI 协作](agent-coding-sandbox.md)、[项目治理域数据模型](project-governance.md)。
- 未实现，验收证据以关联 Decision 的六列矩阵为准；当前结果全部为 `Not run`。
