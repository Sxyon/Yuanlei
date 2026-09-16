# Git 工具业务异常收敛为 error ToolMessage

状态：implemented
类型：bug-fix
Owner：backend/package/yuxi/agents/middlewares/git_tool_error.py

## 问题

langgraph 的 ToolNode 默认错误策略（`_default_handle_tool_errors`）只把
`ToolInvocationError`（参数 schema 校验错误）转为 error ToolMessage；工具函数体
抛出的其他异常一律重新抛出并 panic 整个 Run。因此模型给 `git_prepare_worktree`
传了非法 `branch_slug`（如大写的 `PJ1-project-git-extend`）时，
`normalize_branch_slug` 的 422 校验失败不变成模型可见的工具失败，而是直接终结
整个 Run（resume_error），模型没有修正参数重试的机会——可自愈的小错被放大为
Run 死亡。

## 决策

在 chatbot（Root）图中间件链最内层注册 `GitToolErrorMiddleware`
（`awrap_tool_call`），只对 `git_list_project_repositories` /
`git_prepare_worktree` / `git_push_branch` 三个工具捕获两类预期业务异常：

- `HTTPException`：service 层已把全部模型输入校验统一包成 422，恒为模型可修正
  错误，文案沿用 ToolNode 默认的 "Error: … Please fix your mistakes."；
- `PermissionError`：混有模型可修正（alias 失效、误选保护分支、worktree 未就绪）
  与基础设施故障（凭据/审计 Owner 不可用）两类，收敛为中性 "Error: …" 文案，
  不暗示一定是模型输入错误。

`ValueError` 不捕获：service 边界的输入校验均已包成 422，裸 ValueError 只能是
编程错误，必须继续向上传播。`branch_slug` 等校验边界本身不放松、不静默自动
改写：非法值仍然失败，只是失败从"杀死 Run"改为"模型可见"。同时在
`git_prepare_worktree` 的工具描述与 chatbot prompt 中补充 `branch_slug`
（ASCII kebab-case、≤48 字符）与 `branch_kind` 的格式要求，降低模型首次传错的
概率。

## 替代方案

- 校验层自动把输入转成小写/清洗：改变幂等意图匹配的语义，且违反信任边界显式
  失败原则，拒绝。**后记**：2026-09-17 实测本中间件在 resume 恢复中断时未生效，
  `Error during resume: 422` 仍直接终结 Run，且模型反复生成大写 slug；该取舍已由
  [deepseek-git-tool-error 修复](2026-09-17-deepseek-git-tool-error.md) 重开，
  `normalize_branch_slug` 现先 `.lower()` 再校验。
- 工具内捕获后返回 dict 错误载荷：ToolMessage 会是 success 状态，破坏工具审计
  对成功/失败的裁决语义，拒绝。
- 全局放开 ToolNode `handle_tool_errors=True`：langchain `create_agent` 不暴露
  该参数，且会影响全部工具的错误语义，爆炸半径过大，拒绝。
- 同时收敛 `ValueError`：覆盖不到额外模型输入错误（已统一为 422），反而会吞掉
  编程错误，拒绝。

## 后果

- Git 工具的两类业务失败不再终结 Run；模型看到错误 ToolMessage 后自行修正重试
  或向用户报告阻塞，可能多消耗一至两轮模型调用。
- 基础设施类 PermissionError（凭据不可用等）也会被收敛为工具失败，模型可能做
  有限次数的无谓重试后报告阻塞；相比 Run 直接死亡，用户能获得明确的失败说明，
  接受该代价。
- 未知异常（数据库故障、GitExecutionError 等）不在捕获范围，仍然使 Run 失败——
  这是刻意的 fail-closed 取舍，未来如需扩大收敛范围须重开本记录。
- SubAgent 图不注册本中间件：Git 工具在 SubAgent 本就禁用，无影响面。

## 验证

- `test/unit/middlewares/test_git_tool_error_middleware.py`：422 转可修正文案的
  error ToolMessage、PermissionError 转中性文案；负向案例证明 ValueError、未知
  异常（RuntimeError）与审批中断（GraphInterrupt）不被吞、非 Git 工具异常原样
  传播。
- 命令：`docker exec pat-api-1 sh -c 'cd /app && uv run --no-sync --group test pytest test/unit/middlewares/test_git_tool_error_middleware.py -q'`，7 passed；
  `test/unit/middlewares` + project_git 相关 147 passed；`test/unit/agents`
  182 passed。
