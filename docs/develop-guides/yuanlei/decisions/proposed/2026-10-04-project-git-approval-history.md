# 项目 Git 审批记录与占用队列

状态：proposed
类型：feature
Owner：backend/package/yuxi/services/project_git_action_service.py

## 问题

项目 Git 操作需要在自动授权与严格保护之间形成可追溯的批准依据。用户需要从项目资源看到申请者、关联任务及运行、源与目标分支、内容快照、批准者或规则、执行结果和时间线，以及当前目录占用者和 FIFO 排队顺序。授权模式仅决定批准方式，任务完成不自动触发 Git 操作。

目标是接入真实智能体工具、人工批准入口和执行边界，先持久化批准记录再产生 Git 副作用。非目标是新增项目共享权限、用模型评审替代授权规则、审计全部任意 shell 命令或改变上游 Request/Run/Task 状态模型。普通任务分支 Git 命令仍保留，平台审批历史覆盖平台提供的成果操作；已提交内容以 Git 对象为事实。

## 提案

新增 yuanlei 域审批记录，冻结申请身份、分支、HEAD/tree、策略与内容差异。受保护资源目标或 Gitea 保护分支等待人工批准；服务端可按自动授权规则批准当前任务分支、合法父任务目标及未保护的自动授权资源目标。智能体不能把人工批准身份写入请求，也不能选择不属于任务的资源或兄弟任务目标。自动批准记录规则依据；它表示授权通过，不冒充模型代码审查。

智能体操作通过既有 Durable Task 执行，复用持久投递、lease/heartbeat、成功与失败收敛。审批与 Task 投递意图同事务提交，ARQ 在提交后发布。外部副作用仍可能在崩溃前发生，失败记录提示核对实际 Git 状态，不自动重新执行或强制覆盖。人工直接操作保留现有交互并记录明确确认与结果。既有 Git push 工具转到同一批准边界，避免旧入口绕过记录。

## 替代方案

只写普通日志，不能冻结申请快照与批准事实；为每个 Git 操作新增独立 worker 状态机则重复现有 Durable Task 生命周期。当前采用独立审批事实加既有执行 Owner，允许分别追溯批准与执行。

占用与队列从持久占用、实际目录竞争关系和根执行树派生；按资源显示使用模式、占用任务/对话、当前运行及后续等待序列，不把普通聊天 Request FIFO 当作工作空间占用队列。

## 验收标准

服务、repository 与 executor 拥有授权和副作用；审批记录和 Durable Task 拥有持久事实；Vue 项目资源页拥有历史与占用投影。最低证据是实际 PostgreSQL 迁移、HTTP 审批与越权/过期快照/受保护目标负向案例、worker 结果和 Git 文件/远端引用回读，以及真实页面验证。Gitea 目标 HEAD 不支持原子 CAS，合并前检查继续明确保留此限制。

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 平台批准历史冻结身份与内容，自动和人工批准可追溯 | 批准记录与真实提交不同 | project_git_action service/repository、Task handler | test_project_git_resource_api.py 实际 HTTP、PG、Task attempt、Git 引用回读 | 越权、重复决定、批准后内容变化 | Passed |
| 项目占用和 FIFO 次序反映持久分配 | 队列次序与真实目录竞争不符 | project_git_execution_service、occupancy repository | 实际 PG/HTTP 占用投影与 test_project_git_occupancy.py | worktree 不加入共享目录队列 | Passed |
| 审批时间线与占用界面可查看 | 旧响应覆盖新项目，失败不可见 | ProjectGitActivityPanel.vue | 前端 unit、lint、build、真实浏览器 | 项目切换、迟到轮询、读取失败 | Passed |

完整真实 ARQ、AgentRun lease 丢失恢复、Gitea 创建及合并端到端证据尚未执行，不以 Task handler 的 integration 替代。

## 风险

批准后 HEAD、内容或策略变化必须拒绝执行。持久占用和失败意图需要用户核对真实 Git 状态并显式处理；审批授权不能冒充代码质量审核。

## 已执行证据与边界

`docker compose run --rm storage-migrator` 完成 yuanlei 26 迁移，既有 business/knowledge 版本不变。`test_project_git_resource_api.py` 与 `test_project_git_occupancy.py` 实际 PostgreSQL、HTTP ASGI 与本地 Git integration 16 passed；审批四组合覆盖 worktree/in_place、人工/自动批准、真实提交和本地 bare 远端推送回读、冻结差异、重复决定与请求、批准后内容变化拒绝，以及 FIFO 投影。增加运行身份与 lease 在策略读取期间失效的负向案例后，审批四组合重跑 4 passed，保证未产生新批准或未改变 Git 引用。PR 源 HEAD 改变且已被合并的协议负向案例由模拟 provider 返回，实际 Task/审批终态回读为 failed；它不替代真实 Gitea 合并证据。

后端全量 unit：`uv run --no-sync pytest test/unit -m 'not slow' -q --tb=short`，2778 passed、63 skipped。规定的 `uv run --group test` 因容器 editable.pth 更新权限失败；已安装依赖下的测试通过，不宣称依赖同步成功。前端全量 unit 448 passed；相关交互 12 passed，覆盖人工决定回读、队列次序、迟到轮询拒绝与读取失败。前端 lint/build、工程契约 verifier、verifier unit 70 项、文档构建及 diff whitespace 检查通过。开发环境实际项目资源页面验证历史和占用标签及空状态；非空时间线由 Vue 交互单测覆盖，真实浏览器中的非空记录与人工决定仍 Not run。当前无活动 AgentRun 时重载 worker，实际 readiness 回读 ready。

独立 Reviewer 不继承开发上下文审查完整 staged、unstaged 与新增文件，确认审批执行路径、推送冻结差异、已合并源 SHA 校验及副作用前 lease 回读问题闭合。完整 ARQ/AgentRun 恢复与真实 Gitea 创建及合并 E2E 保持 Not run。
