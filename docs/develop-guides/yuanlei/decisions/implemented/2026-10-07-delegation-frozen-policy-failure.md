# 沙盒策略拒绝的委派终态

状态：implemented
类型：bug-fix
Owner：backend/package/yuxi/services/delegation_service.py

## 问题

P10 真实委派在共享 ephemeral 策略下被 `sandbox_policy_unsupported` 拒绝。投递意图已经提交，错误释放租约后仍为 pending。适配器预检读取当前项目覆盖配置，CodingExecutionService 环境准备却依据 `_coding_effective_snapshot` 标记使用已冻结配置。当前覆盖改成 dedicated 时预检通过，准备仍以共享策略拒绝；异常退化为通用投递失败，后台持续重试，完成守卫将 pending 视为活跃。该策略拒绝发生在创建执行会话之前，没有需要恢复的外部执行句柄。

## 决策

沙盒适配器预检与 CodingExecutionService 共享冻结配置标记语义，有标记时不重读项目覆盖，创建编码会话时同样保留已冻结的 coding/sandbox 配置。在回滚后重新锁定记录并核对原 owner 与 pending 状态，避免覆盖其他收敛者已派发的句柄。首次派发及后台恢复遇到 `sandbox_policy_unsupported` 时收敛到已有 failed 终态，保留原输入、操作标识和准确错误码，清除租约。其他错误维持既有重投语义。修正配置后用户从正式工作发起新委派。

## 替代方案

重读新配置后重试会改变已有冻结运行配置的约定；忽略所有 pending 错误会放过外部副作用不明的投递；批量删除历史委派会丢失因果证据。仅在完成守卫忽略该错误不能结束后台重投。

## 验证

真实 PostgreSQL 隔离 Schema 回归通过真实适配器覆盖首次拒绝和恢复拒绝，使用冻结共享策略与当前专属策略证明一致判定；并覆盖回滚后新收敛者取得 Owner 或提交句柄的并发情况，失败记录不再活跃且再次收敛不重投。成功投递的会话持久化保留冻结专属策略和执行器，当前共享策略不覆盖它。普通暂时失败仍保留 pending。真实项目原失败意图经 Owner 收敛，成功结果在原完成守卫下可以接受并完成。

## 后果

仅明确发生在创建执行句柄前的策略拒绝属于该终态分支，网络失败与未知外部副作用继续重试；不增加 Schema 或业务状态。
