# Git 工具错误与 DeepSeek 兼容

状态：已实现
类型：上游缺陷修复与模型兼容
主要 Owner：`backend/package/yuxi/agents/middlewares/git_tool_error.py`

## 需求与失败场景

Git 工具的可恢复业务错误会被默认 ToolNode 策略升级为整个 Run 失败；DeepSeek 可能生成包含大写字符的分支 slug；manifest 把 worktree 运行时派生字段纳入身份指纹后，同一授权身份会因路径变化产生漂移。

## 必须保留的业务语义

- 可恢复的 Git 业务错误以结构化 ToolMessage 返回模型，不杀死整个 Run。
- 权限、未知异常和系统错误保持 fail-closed，不被通用捕获伪装为业务失败。
- 分支 slug 在校验前做确定性小写归一，非法字符和边界继续拒绝。
- manifest 指纹只包含稳定身份字段，运行时派生路径不改变同一授权事实。

## 与 Yuxi 的边界

Yuxi 拥有 ToolNode、middleware 装配和 manifest 主契约。元垒只收敛 Git 工具的已知业务异常，并修正分支 slug 与 Git 身份字段；其他工具和异常沿用上游行为。

## 稳定集成点

| 集成角色 | 当前 Owner | Yuanlei 语义 |
|---|---|---|
| Git 工具错误转换 | `GitToolErrorMiddleware` | 只处理约定的 422 与 PermissionError |
| Middleware 装配 | chatbot/subagent graph | 确保 Git 工具经过收敛层 |
| 分支名称 | `workspace.git_paths` | 先归一再执行安全校验 |
| manifest | `agent_run_manifest_service` | 稳定身份与运行时派生字段分离 |

## 上游依赖

该修复依赖 deepagents ToolNode 异常传播、middleware 生命周期、Git 工具错误类型和 manifest fingerprint 结构。依赖升级或上游修复这些行为时需要重新运行负向案例。

## 合并判断

- 上游提供等价 per-tool error policy：删除重复 middleware，保留异常白名单和 fail-closed 测试。
- 上游改变 ToolMessage 错误协议：迁移结构化业务错误，不扩大捕获范围。
- 模型或上游已稳定 slug：可以删除归一补丁，但必须保留非法 ref 负向测试。
- manifest 上游引入正式身份模型：映射稳定 Git 身份并删除重复字段。

## 替换或删除条件

真实 provider 与确定性测试证明上游已等价处理业务错误、slug 和 manifest 身份后，可以分别删除对应补丁。三个修复具有独立退出条件，不因其中一个被覆盖而整体删除。

## 决策与证据

- [Git 工具业务异常收敛](../decisions/implemented/2026-09-16-git-tool-business-error-containment.md)
- [DeepSeek Git 工具错误](../decisions/implemented/2026-09-17-deepseek-git-tool-error.md)
- `backend/test/unit/middlewares/test_git_tool_error_middleware.py`、Git path/ref 测试和 manifest service 测试拥有正向与负向证据。
