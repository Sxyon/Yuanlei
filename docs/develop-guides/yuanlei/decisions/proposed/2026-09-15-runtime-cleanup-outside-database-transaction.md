# Runtime cleanup 外部副作用与数据库事务分离

状态：proposed
类型：architecture
Owner：backend/package/yuxi/services/run_worker.py

## 问题

根 AgentRun 结束后，worker 使用 PostgreSQL advisory transaction lock 和 AgentRun 行锁建立 runtime cleanup fence，然后调用 sandbox provider 删除运行容器。删除包含进程线程调度、provider keyed lock、provisioner HTTP 请求和 Docker 回收，耗时与可用性不受数据库控制。当前实现把这些外部等待放在数据库事务内；一旦 provider 锁或删除请求卡住，同一 Run 的恢复事务会排队，AgentRun lease reconciler 无法完成本轮健康续租，后续任务持续被 `runtime_cleanup_pending` 阻止。

## 提案

`runtime_cleanup_pending` 继续表达根 execution runtime 尚未确认清理完成。清理拆成三个阶段：第一段短事务取得 advisory transaction lock、锁定 Run、确认没有非终态同 scope Run，并解析 uid、runtime scope 和 Workdir；事务提交后，在有界时间内调用 sandbox provider；删除成功后开启第二段短事务，重新取得同一 advisory lock、锁定并复核 Run、同 scope 活跃状态及 Workdir 身份，最后清除 `runtime_cleanup_pending`。

外部删除失败或超时保留 fence，由既有 reconciler 重试。重复删除按 sandbox generation 和 provisioner 的不存在即成功语义收敛；并发清理中，首个成功者清除 fence，其他调用者在最终事务看到 fence 已清除后返回成功。外部调用的线程即使晚于异步等待超时返回，也不持有 PostgreSQL 事务或锁。

Sandbox provider 的 release keyed lock 使用有界等待。等待超过 `SANDBOX_PROVIDER_RELEASE_LOCK_TIMEOUT_SECONDS` 时显式失败；默认 30 秒。worker 对完整外部 release 使用 `SANDBOX_RUNTIME_CLEANUP_TIMEOUT_SECONDS`，默认 155 秒，覆盖默认 30 秒锁等待和 120 秒 provisioner 删除超时。两个值都必须是正整数。

本决定修正 [Agent 并发容量、流式协议与时延观测](../../../decisions/implemented/2026-09-04-agent-concurrency-capacity.md) 中“删除位于 PostgreSQL runtime cleanup fence 内”的实现含义：持久 fence 覆盖删除全过程，数据库事务不覆盖外部删除等待。

## 替代方案

- 继续在事务内等待并只增加 provisioner HTTP 超时：provider keyed lock 和线程调度仍可无限等待，且正常 Docker 回收耗时仍会占用数据库锁。
- 清理前先清除 `runtime_cleanup_pending`：新 Run 可在旧 runtime 尚未删除时创建或复用同 scope sandbox，破坏 generation 与执行树边界。
- 第一版新增 cleanup lease 和独立状态表：当前 fence、advisory lock、Run 行锁与幂等删除足以让重复尝试收敛，新增持久状态没有当前 consumer。
- 超时后强制取消工作线程：Python 无法安全终止已进入同步 provider/HTTP 调用的线程；让其在无数据库锁条件下按 provider 自身超时退出。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| Sandbox 删除等待期间不持有 AgentRun 行锁或 runtime advisory transaction lock | 同 scope 恢复事务排队、reconciler 卡死 | `run_worker._release_runtime_if_idle` | 真实 PostgreSQL integration | 阻塞 provider release 时用 `NOWAIT` 锁同行并取得同 advisory lock | Passed |
| 删除成功并完成最终复核后才清除 cleanup fence | 新旧 runtime 交错 | AgentRun `runtime_cleanup_pending` | 真实 PostgreSQL integration | release 阻塞、失败或超时时 fence 保持 true | Passed |
| Provider release 等待 keyed lock 有上限 | 同进程调用无限等待 | `ProvisionerSandboxProvider.release` | unit | 预先占用 scope lock，release 超时且不调用 delete | Passed |
| 重试可幂等收敛 | 重复 delete、重复清 fence或身份漂移 | worker、provider、provisioner | unit 与 integration | fence 已清、同 scope 新增活跃 Run、Workdir 身份变化 | Not run |

## 风险

异步超时无法终止已经启动的同步线程，超时后的 release 可能继续到 provider 自身超时。它不再占用数据库事务；同 scope provider lock 与 generation 校验限制本地交错。若 provisioner delete 的实际最坏耗时超过 worker 总超时，运维必须同步调整两个超时，保证 worker 总超时大于 provider 锁等待与删除请求超时之和。

本变更只修复已证实的 cleanup 事务和锁等待问题。触发原 AgentRun heartbeat 丢失的上游原因、watchfiles 作为容器 PID 1 时积累僵尸进程，以及 Workspace symlink 删除失败分别保留为独立诊断与后续变更。
