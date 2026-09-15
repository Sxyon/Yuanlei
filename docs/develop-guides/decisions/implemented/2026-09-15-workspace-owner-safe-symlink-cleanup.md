# 个人空间安全清理符号链接

状态：implemented
类型：bug-fix
Owner：backend/package/yuxi/workspace/filesystem.py

## 问题

个人空间是用户全部 Project Workdir 的持久文件边界。当前递归删除只接受真实目录和普通文件，遇到任何符号链接都会失败。Agent 通过 Git clone 得到包含受版本控制 symlink 的仓库后，用户即使从个人空间操作也无法删除该目录。统一放开路径跟随会让链接目标越过 UserWorkspace，因此删除能力必须区分链接目录项与链接指向的对象。

## 决策

Workspace 删除器保留默认 `reject` 策略，并增加只供个人空间所有者确认流程使用的 `unlink` 策略。两种策略都通过目录文件描述符、`follow_symlinks=False` 和 `O_NOFOLLOW` 固定父路径。`unlink` 策略遇到 symlink 时只对当前父目录中的链接目录项执行 `unlink`，不读取、解析、打开或递归进入链接目标。

个人空间普通删除先使用 `reject`。遇到 symlink 时 API 返回固定、脱敏的 `409 workspace_contains_symlinks`；前端说明只删除链接本身且目标不受影响，经二次确认后以 `safe_unlink_symlinks=true` 重试。该参数不进入 Project Workdir 文件接口或 Agent 工具。用户现有登录身份已经拥有个人空间权限，流程不要求重新输入密码。

安全清理不改变 Workspace 根目录、父路径 symlink、路径穿越和跨 uid 限制。只有待删除树内部或最终目标本身的 symlink 可以被 unlink；任何位于目标路径父链中的 symlink 仍在打开目录时失败。

## 替代方案

- 输入密码后允许跟随 symlink：重新认证不能改变文件系统路径的安全性，链接目标仍可能越过 UserWorkspace。
- 所有删除入口默认 unlink symlink：Project Workdir 和其他调用方会在没有明确产品交互的情况下改变行为。
- 让用户进入 Sandbox 执行 `rm -rf`：把持久文件管理责任交给 Agent 命令，缺少个人空间 API 的授权、错误语义和可审计入口。
- 复制或修改 Git 仓库以移除 symlink 后再删除：破坏用户数据且无法处理任意嵌套链接。

## 后果

个人空间安全清理仍是不可恢复的数据删除。它只收窄 symlink 处理方式，不新增恢复站、批量事务或 Project Git 生命周期绕过。

单个目录的递归删除不是文件系统事务。普通删除可能先删除目录内按遍历顺序出现的普通条目，随后才因 symlink 返回冲突；用户取消第二次确认时，已完成的删除不会回滚。批量删除也可能在冲突前完成前序项目。前端重试只包含冲突项及尚未处理的后续项目，并在操作后刷新个人空间视图。

## 验证

- `docker compose exec -T api python -m pytest test/unit/workspace/test_filesystem.py test/unit/workspace/test_workdir.py test/unit/services/test_workspace_service.py -q`：44 passed。覆盖外部链接目标保持不变、父路径 symlink 拒绝、结构化冲突和 Project Workdir 默认拒绝。
- `cd web && node --test test/unit/api_boundary.test.js test/unit/workspace_action_semantics.test.js test/unit/workspace_delete.test.js`：20 passed。行为测试覆盖固定冲突码、确认前无安全请求、确认后安全参数、取消不重试和其他 409 不触发确认。
- Ruff 与 ESLint 目标文件检查通过；文档构建与 Web 生产构建通过；`python3 scripts/verify_engineering_contracts.py`、`python3 -m unittest scripts.test_verify_engineering_contracts` 和 `git diff --check` 通过。
- 后端完整非 slow unit 当前为 3 failed、2082 passed、56 skipped，失败集中在 Project Git API Token 错误映射和既有 business schema 版本断言；Web 完整 unit 当前为 16 failed、147 passed，失败集中在缺失的既有模块、Run 事件断言、消息分组和流式时序。这些失败不涉及本决策修改的文件，相关目标测试均通过。
- 用户在真实个人空间完成含 symlink 的 Git clone 目录删除，确认操作成功。
- 真实自动化 HTTP integration 因环境未配置 `TEST_USERNAME` 与 `TEST_PASSWORD` 跳过；FastAPI 测试客户端未形成该项证据。
