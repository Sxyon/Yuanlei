# Project Git 资源目录初始化守卫的终态判定

状态：implemented
类型：bug-fix
Owner：backend/package/yuxi/repositories/project_git_repository.py

## 问题

资源目录初始化守卫在用户仍有非终态 Run 时拒绝初始化，并撤销该用户的 Git 运行时。守卫使用的排除集合只列出 completed、failed、cancelled，漏掉 interrupted。系统的终态定义 `AGENT_RUN_TERMINAL_STATUSES` 包含 interrupted；恢复中断运行会创建新的 resume Run，被恢复的旧 Run 永远停留在 interrupted。一条历史中断运行因此让守卫恒为真，用户在同一工作区继续绑定或初始化资源目录时持续得到 409。

守卫拒绝进入 Provision worker 的兜底 `except` 后，所有异常被统一映射为 `git_provision_failed` 与固定文案 `Git repository operation failed`，真实原因不出现在 API 响应、数据库和前端，只能从 Redis 结果键或日志读取。

## 决策

守卫复用 `AGENT_RUN_TERMINAL_STATUSES` 判定非终态，不再手写状态列表。interrupted 与 completed、failed、cancelled 一样不阻塞资源目录初始化；随后执行的 `revoke_user_git_runtimes` 撤销该用户所有 Git 运行时，resume 为新 Run 建立新运行时，因此不破坏待审批运行的恢复。

Provision 失败记录区分守卫拒绝与其它失败：守卫拒绝写入 `git_provision_blocked` 与守卫自身的受控文案；其它异常继续写入 `git_provision_failed` 与通用文案。失败记录只接受调用方给定的受控文案，避免把远端响应、凭据或路径写入用户可见错误。

## 替代方案

只补一个字符串字面量会再次与终态定义漂移。守卫继续把 interrupted 视为活动会让任何历史中断运行永久阻塞资源目录。把任意异常文本透传到 `last_error_message` 会破坏失败记录不含 secret 的边界，因此只透传守卫自身受控文案。

## 后果

历史中断运行不再阻塞绑定与初始化；真正的 pending、running、cancel_requested 仍被拒绝。守卫拒绝在数据库与前端显示可定位原因。守卫语义绑定共享终态常量，新增终态只需更新常量。

## 验证

`test/integration/services/test_project_git_occupancy.py::test_user_has_nonterminal_runs_excludes_terminal_interrupted_run` 在真实 PostgreSQL 上断言 interrupted 不属非终态、running 仍属非终态。`test/integration/api/test_project_git_resource_api.py::test_interrupted_terminal_run_does_not_block_directory_guard` 与 `test_running_run_still_blocks_directory_guard` 通过真实 HTTP、PostgreSQL 与本地 Git 证明行为。`test/unit/services/test_project_git_service.py::test_provision_surfaces_controlled_directory_busy_reason` 证明守卫拒绝记录受控文案。移除本修复后前两项按原缺陷失败（分别得到 `assert True is False` 与 409），恢复后通过。
