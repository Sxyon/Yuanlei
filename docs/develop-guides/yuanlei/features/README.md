# 元垒差异化功能索引

本索引回答三个问题：哪些行为是元垒的、为什么改、与上游合并时注意什么。权威差异清单由 `scripts/yuanlei_upstream_report.py` 和 `git diff` 生成，本页不枚举文件清单，避免漂移。

## 维护规则

- 新增或改变与上游不同的行为时更新本页，并链接 owning 决策记录；行为等价的局部修复可以豁免，但 PR 要说明原因。
- 上游合并后核对条目：上游完整吸收的差异标注「已回归上游」并移除冲突关注；被取代的条目更新链接。
- 每条写清与上游的语义差异和合并注意项，与上游行为一致的普通功能不收录。

## Project Git 多仓库与任务 worktree

- 类型与状态：feature，代码已接入（选择接口、preflight 与 yuanlei v1→v2 迁移）；对应决策仍在提案状态，验收证据与真实链路测试待补。
- 与上游差异：上游没有 Project 级 Git 仓库绑定、凭据、任务分支或 worktree。元垒新增多仓库绑定、AES-GCM 凭据、Gitea provider、可信 staging fetch/push、根任务 worktree 和始终需要人工审批的 `git_push_branch`。
- 语义 Owner：`backend/package/yuxi/services/project_git_service.py`、`backend/package/yuxi/git/`、`backend/server/routers/git_router.py`。
- 决策记录：[多仓库与根任务 worktree](../decisions/implemented/2026-09-14-project-multi-repository-git-worktrees.md)、[按根任务显式分配 worktree](../decisions/proposed/2026-09-16-on-demand-project-git-worktrees.md)。
- 合并注意：持久化位于 `yuanlei` schema 域；上游改动 project、agent、run manifest、tool approval、sandbox provider 或执行准备入口（`prepare_run_execution`、`AuthorizedWorkdir`）时需要评估；credential、staging、HITL push 和隔离边界不因上游实现变化而放宽。

## 项目数字员工（ProjectAgent）

- 类型与状态：feature，已实现。
- 与上游差异：上游 `agents` 是全局资源，只有 `created_by` 和 `share_config`。元垒新增 `(project_id, agent_slug)` 绑定与项目级配置覆盖，绑定后 Agent 只能在绑定项目内运行，运行边界 fail-closed。
- 语义 Owner：`backend/package/yuxi/services/project_agent_service.py`、`backend/package/yuxi/services/agent_request_service.py`（intake 校验与覆盖读取）、`backend/package/yuxi/repositories/project_agent_repository.py`、`web/src/components/model-management/ProjectAgentManagePanel.vue`。
- 决策记录：[项目数字员工](../decisions/implemented/2026-09-17-project-digital-employees.md)、[上游 2026-09-18 同步迁移](../decisions/implemented/2026-09-18-upstream-23-sync-project-agent-port.md)。
- 合并注意：`project_agents` 表属于 `yuanlei` 域 v3；上游改动 agent 列表、请求接入（`agent_request_service`）、执行准备（`prepare_run_execution`）或 manifest 时，`project_id` 过滤、范围校验与有效配置合并必须保持；上游若引入项目级 Agent 模型，先写决策再取舍。

## Git 工具错误收敛与 DeepSeek 兼容

- 类型与状态：bug-fix，已实现。
- 与上游差异：上游 ToolNode 默认策略会把 Git 工具的业务异常升级为 Run 死亡。元垒新增 `GitToolErrorMiddleware` 把 422 与 PermissionError 收敛为 error ToolMessage，`normalize_branch_slug` 先小写归一，manifest 指纹排除 worktree 运行时派生字段。
- 语义 Owner：`backend/package/yuxi/agents/middlewares/git_tool_error.py`、`backend/package/yuxi/workspace/git_paths.py`。
- 决策记录：[业务异常收敛](../decisions/implemented/2026-09-16-git-tool-business-error-containment.md)、[DeepSeek 分支 slug 与 manifest 指纹](../decisions/implemented/2026-09-17-deepseek-git-tool-error.md)。
- 合并注意：上游修复 ToolNode 错误策略或 manifest 序列化时，先判断元垒中间件是否仍有 consumer；合并 manifest 变更必须保留身份字段与运行时派生字段的区分。

## 个人空间符号链接安全清理

- 类型与状态：bug-fix，已实现。
- 与上游差异：上游递归删除遇到符号链接直接失败。元垒为个人空间所有者确认流程增加 `unlink` 策略，只删除链接目录项，不解析链接目标，Project Workdir 仍使用默认 `reject` 策略。
- 语义 Owner：`backend/package/yuxi/workspace/filesystem.py`、`web/src/utils/workspaceDelete.js`。
- 决策记录：[个人空间安全清理符号链接](../decisions/implemented/2026-09-15-workspace-owner-safe-symlink-cleanup.md)。
- 合并注意：上游修改删除器、workspace API 错误码或前端删除交互时，`409 workspace_contains_symlinks` 契约和 `safe_unlink_symlinks` 参数仅限个人空间入口的边界不得扩散。

## 个人空间附件引用与延迟线程创建

- 类型与状态：bug-fix / feature，实现完成，真实页面与部分 HTTP 主链路证据待补。
- 与上游差异：上游附件选择器创建线程即落库、浏览 Project Workdir。元垒把浏览源改为用户个人空间、首次发送前只保留前端缓存、发送时才物化引用，后端引用契约新增 `source: workspace` 且在个人空间边界内校验。
- 语义 Owner：`web/src/components/AgentChatComponent.vue`、`web/src/components/ProjectFilePickerModal.vue`、`backend/package/yuxi/services/attachment_service.py`。
- 决策记录：[附件选择延迟线程创建](../decisions/proposed/2026-09-17-attachment-picker-workspace-browse-deferred-thread.md)。
- 合并注意：上游改动附件上传、引用校验或 `chat_router` 时，`source` 默认值与 `workdir` 兼容路径必须保留；未完成证据补齐前不得把该提案改写为已实现。

## 输入区交互与发送锁

- 类型与状态：feature，已实现。
- 与上游差异：元垒新增输入法组合态回车不触发发送、手动发送锁和发送锁按钮位置调整。
- 语义 Owner：`web/src/utils/sendLock.js`、`web/src/components/AgentInputArea.vue`、`web/src/components/MessageInputComponent.vue`。
- 决策记录：局部交互修复，无独立决策记录。
- 合并注意：上游重写输入组件时应保留组合态与发送锁行为；纯前端交互冲突优先采用上游结构并迁移元垒行为。

## Runtime cleanup 事务外执行

- 类型与状态：architecture，实现待收口。
- 与上游差异：上游在 PostgreSQL runtime cleanup fence 事务内等待 sandbox 删除。元垒改为短事务预检、事务外删除、短事务复核并清除 fence，provider release 锁与整体清理都有显式超时。
- 语义 Owner：`backend/package/yuxi/services/run_worker.py`、`backend/package/yuxi/agents/backends/sandbox/provider.py`。
- 决策记录：[Runtime cleanup 与数据库事务分离](../decisions/proposed/2026-09-15-runtime-cleanup-outside-database-transaction.md)。
- 合并注意：上游修改 Run 恢复、lease、provider release 或沙盒生命周期时，数据库事务不得重新覆盖外部删除等待；新的超时配置必须与 `.env.template` 和 Compose 保持同源。

## Agent 专属沙盒、编码 CLI 协作与执行租约

- 类型与状态：feature，提案（proposed），实现进行中；M0 契约探针、专属沙盒（M2）、执行租约（M3）、凭据基座（M1）、适配器与凭据注入（M4）、会话实体与状态机（M5a）均已落地；`coding_*` 工具、会话 supervisor 与前端会话面板（M5b）待做。
- 与上游差异：上游沙盒是线程级身份、全局 idle TTL、根 Run 终态释放且只有一次性 `execute`；没有 `(uid, agent, project)` 专属沙盒、生命周期策略、执行租约、编码凭据通道与 opencode/codex 会话工具。
- 语义 Owner：`backend/package/yuxi/agents/backends/sandbox/provider.py`（身份、生命周期与租约）、`docker/sandbox_provisioner/app.py`（按沙盒策略回收与终端代理）、新增 `backend/package/yuxi/agents/coding/`（适配器与会话工具）、`backend/package/yuxi/storage/postgres/manager.py`（yuanlei 域表）。
- 决策记录：[Agent 专属沙盒与生命周期策略](../decisions/proposed/2026-09-18-agent-dedicated-sandbox-lifecycle.md)、[智能体驱动沙盒内 opencode/codex 编码执行](../decisions/proposed/2026-09-18-agent-driven-coding-cli-sessions.md)；实施顺序与共享契约见 [合并实施计划](../../planning/agent-coding-execution-plan.md)。
- 实测契约：[编码 CLI 契约](../../../agents/coding-cli-contract.md)、[沙盒生命周期契约](../../../agents/sandbox-lifecycle-contract.md)；`scripts/probes/` 下有两个可复跑探针脚本。
- 合并注意：上游修改 sandbox provider、run_worker 清理、provisioner 创建/回收协议、tool approval、事件映射或 deepagents 文件后端时，scope 三元校验、generation fence、默认 ephemeral 行为、密钥不进沙盒明文通道与「删除不改 Workdir 字节」不得放宽；yuanlei 迁移必须晚于 business 域收敛。
