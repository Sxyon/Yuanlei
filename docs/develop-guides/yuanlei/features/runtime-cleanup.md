# Runtime cleanup 事务外执行

状态：提案语义已接入，部分证据待收敛
类型：上游生命周期缺陷修复
主要 Owner：`backend/package/yuxi/services/run_worker.py`

## 需求与失败场景

根 AgentRun 终止后，worker 在 PostgreSQL transaction lock 和 Run 行锁内等待 Sandbox 删除。provider 锁、HTTP 和 Docker 回收耗时不受数据库控制，阻塞会拖住恢复事务与 lease reconciler，并让后续任务持续停留在 `runtime_cleanup_pending`。

## 必须保留的业务语义

- 持久 cleanup fence 覆盖外部删除全过程，数据库事务不覆盖外部等待。
- 删除成功并在最终短事务重新校验身份和活跃 Run 后才清除 fence。
- 删除失败或超时保留 fence，reconciler 可以重试。
- provider keyed lock 和完整 release 都有显式上限。
- 重复清理按 runtime scope、generation 和不存在即成功语义幂等收敛。

## 与 Yuxi 的边界

Yuxi 继续拥有 AgentRun 终态、lease、恢复和 Sandbox provider 生命周期。元垒调整 cleanup fence 的事务时序与超时，不新增第二套 Run 状态模型。

## 稳定集成点

| 集成角色 | 当前 Owner | Yuanlei 语义 |
|---|---|---|
| cleanup fence | `run_worker._release_runtime_if_idle` | 短事务预检、事务外删除、短事务复核 |
| provider release | Sandbox provider | scope lock 有界等待并校验 generation |
| 恢复 | AgentRun reconciler | fence 保留时可重复发布清理 |
| 配置 | `.env.template`、Compose | worker 总超时覆盖锁等待和 provider 删除上限 |

## 上游依赖

该能力依赖 AgentRun lease、runtime scope、cleanup fence、provider release 和 provisioner 删除协议。上游改变 Run 恢复或 Sandbox 生命周期时，需要验证数据库锁不再覆盖外部副作用。

## 合并判断

- 上游采用同类事务外清理：复用上游实现并保留 fence、身份复核和超时负向案例。
- 上游引入 cleanup lease 或 durable task：比较 ownership、重试和新旧 runtime 交错后决定是否取代当前 fence。
- 上游仅增加 HTTP 超时：继续保留数据库事务分离和 provider lock 上限。

## 替换或删除条件

上游机制能够证明外部删除不持有数据库锁、失败保持可恢复意图、并发重复清理幂等且新 runtime 不与旧 runtime 交错时，可以删除元垒补丁。Sandbox provider 被整体替换时，需要在新 Owner 上重新证明相同不变量。

## 决策与证据

- [Runtime cleanup 外部副作用与数据库事务分离](../decisions/proposed/2026-09-15-runtime-cleanup-outside-database-transaction.md)
- `backend/test/unit/services/test_run_worker.py`、Sandbox provider unit 和真实 PostgreSQL integration 覆盖锁与 fence；幂等重试的未运行项以 Decision 当前结果为准。
