# 个人空间符号链接安全清理

状态：已实现
类型：有意产品差异
主要 Owner：`backend/package/yuxi/workspace/filesystem.py`

## 需求与失败场景

Git 仓库可能包含受版本控制的符号链接。Yuxi 递归删除遇到任何 symlink 都失败，使用户无法从个人空间删除这类目录；直接跟随链接会越过 UserWorkspace 边界并删除外部目标。

## 必须保留的业务语义

- 默认删除继续拒绝 symlink。
- 只有个人空间所有者在收到结构化冲突并确认后才能启用安全清理。
- 安全清理只 unlink 链接目录项，不读取、打开、跟随或递归进入链接目标。
- 目标父链中的 symlink、路径穿越、Workspace 根和跨 uid 操作继续拒绝。
- Project Workdir 与 Agent 工具不获得该确认参数。

## 与 Yuxi 的边界

Yuxi filesystem 原语继续拥有 no-follow 路径安全。元垒增加一个严格收窄的 `unlink` 策略、稳定的 `409 workspace_contains_symlinks` 协议和所有者确认交互，不改变其他删除入口。

## 稳定集成点

| 集成角色 | 当前 Owner | Yuanlei 语义 |
|---|---|---|
| 文件原语 | `workspace.filesystem` | fd-relative、no-follow unlink 链接目录项 |
| 用例与 API | `workspace_service`、`workspace_router` | 默认拒绝，确认后显式重试 |
| 前端交互 | `web/src/utils/workspaceDelete.js` | 解释链接目标不受影响并只重试冲突项 |

## 上游依赖

该能力依赖 UserWorkspace 授权、filesystem no-follow 原语、删除 API 的结构化错误和前端批量删除状态。上游修改任一入口时必须确认参数没有扩散到 Project Workdir 或 Agent 执行边界。

## 合并判断

- 上游提供安全 unlink：比较父链校验、外部目标不变、所有者确认和入口范围后采用公共实现。
- 上游只允许跟随链接或使用普通 `rm -rf`：继续保留元垒边界。
- 上游改变错误协议：迁移确认流程，保持默认拒绝和显式重试。

## 替换或删除条件

上游删除能力同时满足 fd-relative/no-follow、只 unlink 目录项、所有者确认和入口限制时可以删除元垒实现。产品取消个人空间清理能力时可以删除 UI 和策略，但默认拒绝安全边界继续保留。

## 决策与证据

- [个人空间安全清理符号链接](../decisions/implemented/2026-09-15-workspace-owner-safe-symlink-cleanup.md)
- `backend/test/unit/workspace/test_filesystem.py` 和 workdir/service unit、Web 删除语义测试验证外部目标不变、父链拒绝与确认重试。
