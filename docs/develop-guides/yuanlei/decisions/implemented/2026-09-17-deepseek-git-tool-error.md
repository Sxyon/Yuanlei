# DeepSeek 分支 slug 校验与 manifest 指纹稳定性修复

状态：implemented
类型：bug-fix
Owner：backend/package/yuxi/workspace/git_paths.py

## 问题

真实测试中 deepseek-v4-pro 在两个环节反复失败：

1. **branch_slug 大写导致 Run 失败**：模型生成 `PJ1-project-git-extend` 之类含大写字母
   的 slug，`normalize_branch_slug` 的严格 kebab-case 校验抛 `ValueError` → service 层
   包成 422。先前
   [GitToolErrorMiddleware](../implemented/2026-09-16-git-tool-business-error-containment.md)
   已把 422 收敛为 error ToolMessage，但实测在 resume 恢复中断时该中间件未生效，错误以
   `Error during resume: 422: branch_slug must be ASCII kebab-case` 直接终结 Run，模型
   没有修正机会。
2. **模型旁路查询仓库**：resume run 固化 manifest 时 `git_repositories` 为空（worktree
   分配尚未落库），模型失去 Git 工作区上下文，退而用 `execute` 直接 `git log`/`git
   branch` 操作 bare 仓库（`repos/*/repository.git`）查询 gitea 分支，绕过 Git 工具管理
   方式。
3. **manifest 指纹漂移**：`build_manifest_payload` 把 `path`/`branch`/`base_sha` 等
   worktree 运行时派生字段纳入 write-once manifest 指纹；worktree 准备过程中
   `base_sha` 从 None 落到真实 SHA，重试时指纹不一致，`_require_persisted_manifest_match`
   误判"运行资产已在重试前变化"而拒绝执行。

## 决策

- `normalize_branch_slug` 对输入先 `.lower()` 再校验：大写字母静默归一为小写，只有空串、
  连字符重复（`a--b`）、首尾连字符、超长（>48）等无法安全归一化的输入才抛 `ValueError`。
  分支 slug 仅是分支名的可读后缀，大小写无语义差异，且最终仍经
  `git check-ref-format --branch` 二次校验；`derive_repository_directory` 已有 `.lower()`
  先例。
- manifest 的 `git_repositories` 只固化身份字段（`alias`/`repository_id`/`purpose`/
  `task_purpose`/`base_branch`/`selection_source`），排除 `path`/`branch`/`base_sha`。其中
  `base_sha` 虽是一次 allocation 冻结的精确基线提交，但在 worktree 首次准备过程中会从
  `None` 落到真实 SHA（`_prepare_repository_worktree`），而 resume run 固化 manifest 时
  worktree 往往尚未 ready，此时 base_sha 仍是 None，重试后变为真实值导致 write-once 指纹
  漂移；故连同 `path`/`branch` 一并排除，使指纹在准备进度中保持稳定。
- chatbot prompt 的 `project_git_enabled` 分支补充硬约束：严禁用 `execute` 读取 bare 仓库、
  调用 gitea/远程 API 或执行 `git branch`/`git log` 旁路查询，仓库与分支的查看/申请/推送
  只能通过三个 Git 工具完成。

## 替代方案

- 保持严格拒绝、仅靠 prompt 强化格式要求：LLM 已实测不遵守（仍生成大写），不可靠，拒绝。
- 修复 GitToolErrorMiddleware 使其覆盖 resume 恢复路径：根因在 langgraph 内部 ToolNode 的
  resume 执行链，难以静态定位且治标不治本（模型仍会反复生成大写、反复重试），暂不采用，
  作为后续可选加固。
- 让 manifest 指纹忽略整个 `git_repositories`：会削弱"重试必须复用相同仓库选择"的
  write-once 语义，拒绝；仅排除运行时派生字段、保留身份字段。

## 后果

- 模型生成的含大写 slug 会被静默归一为小写分支名，消除 422 导致的 Run 死亡；`PJ1` 与
  `pj1` 现在视为同一分支意图，这是更合理的大小写不敏感幂等语义。
- manifest 指纹不再随 worktree 准备进度漂移，resume 重试可正确复用已固化清单。
- prompt 约束降低模型旁路操作 bare 仓库的概率，但仍是软约束，不能替代工具层的授权边界
  （授权边界仍由服务层 `_require_authorized_root_run` 等 fail-closed 保证）。

## 验证

- `test/unit/services/test_project_git_core.py`：`test_branch_slug_normalizes_uppercase_to_kebab_case`
  证明 `PJ1-project-git-extend` → `pj1-project-git-extend`；`test_branch_slug_rejects_unfixable_input`
  证明空串/`a--b`/首尾连字符/超长仍被拒绝。
- `test/unit/services/test_agent_run_manifest_service.py`：
  `test_git_runtime_derived_fields_do_not_shift_manifest_fingerprint` 证明 base_sha/path/branch
  变化不改变指纹；`test_git_snapshot_is_explicit_and_excludes_remote_credentials` 补充断言
  path/branch/base_sha 不进入 manifest 序列化。
- 命令（容器内）：`python -m pytest test/unit/services/test_project_git_core.py -q` 47 passed；
  `python -m pytest test/unit/services/test_agent_run_manifest_service.py -q` 13 passed；
  `python -m pytest test/unit/middlewares/test_git_tool_error_middleware.py test/unit/services/test_project_git_service.py -q` 16 passed；
  `python -m pytest test/unit/services/test_run_worker.py -q -k manifest` 2 passed。
- 工程契约：`python scripts/verify_engineering_contracts.py` 通过；
  `python -m unittest scripts.test_verify_engineering_contracts` 62 passed。
