# 元垒差异化功能索引

本目录保存元垒相对上游 Yuxi 的当前业务差异。索引只提供导航和状态；每份 Feature 档案解释原始需求、必须保留的业务语义、稳定集成点、上游依赖和退出条件。精确代码事实由源码、测试和 Git diff 拥有，非显然取舍由关联 Decision 拥有。

## 使用规则

- 修改上游已有行为或 Yuanlei 差异前，先读取相关 Feature 与 Decision；缺少对应档案时先补齐。
- Feature 记录稳定语义和集成角色，不逐行复述实现，也不维护可独立漂移的全量文件清单。
- 上游同步时重新评价需求与不变量，明确选择保留并迁移、采用上游替代、缩小差异、需求过期删除或建立新决策。
- 上游完整吸收差异后，在 Feature 中记录取代证据并将相关 Decision 按生命周期归档；历史精确改动继续由 Git 保存。

## 当前功能

- [Project Git 多仓库与任务 worktree](project-git-worktrees.md)：已接入；按根任务显式分配仍有未闭合证据。
- [项目数字员工](project-agents.md)：已实现；拥有项目绑定、配置覆盖和执行范围约束。
- [Git 工具错误与 DeepSeek 兼容](git-tool-compatibility.md)：已实现；收敛可恢复业务错误并稳定 Git 身份字段。
- [个人空间符号链接安全清理](workspace-symlink-cleanup.md)：已实现；只在所有者确认入口 unlink 链接目录项。
- [个人空间附件引用与延迟线程创建](workspace-attachment-references.md)：实现已接入；真实页面与部分 HTTP 证据待补。
- [输入区组合态与发送锁](input-send-lock.md)：已实现；属于局部产品交互差异。
- [Runtime cleanup 事务外执行](runtime-cleanup.md)：提案语义已接入，仍有幂等收敛证据待补。
- [Agent 专属沙盒与编码 CLI 协作](agent-coding-sandbox.md)：实现已接入，提案中的浏览器与真实账号证据待补。
- [项目自定义 Dashboard](project-dashboard.md)：已实现静态 Dashboard v0；含文档与页面 revision、受控 writer、Agent 读写工具和无脚本页面壳。
