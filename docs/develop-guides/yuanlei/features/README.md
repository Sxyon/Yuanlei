# 元垒差异化功能索引

本目录保存元垒相对上游 Yuxi 的当前业务差异。索引只提供导航和状态；每份 Feature 档案解释原始需求、必须保留的业务语义、稳定集成点、上游依赖和退出条件。精确代码事实由源码、测试和 Git diff 拥有，非显然取舍由关联 Decision 拥有。

## 使用规则

- 修改上游已有行为或 Yuanlei 差异前，先读取相关 Feature 与 Decision；缺少对应档案时先补齐。
- Feature 记录稳定语义和集成角色，不逐行复述实现，也不维护可独立漂移的全量文件清单。
- 上游同步时重新评价需求与不变量，明确选择保留并迁移、采用上游替代、缩小差异、需求过期删除或建立新决策。
- 上游完整吸收差异后，在 Feature 中记录取代证据并将相关 Decision 按生命周期归档；历史精确改动继续由 Git 保存。

## 当前功能

- [元垒品牌视觉身份](brand-identity.md)：已实现；文档站与 Web favicon 使用元垒专属图形和青蓝色系。
- [LLM 原生图片输入与能力感知](native-llm-image-input.md)：已实现一期；按渠道和协议解析图片能力，保留 MIME 并原生发送，未知/不支持状态显式拒绝。
- [多模态模型能力探查与展示](multimodal-model-capability-discovery.md)：已实现；按已配置渠道目录协议归一显式输入模态声明，并在模型名称旁标注出处与状态。
- [Project Git 多仓库与任务 worktree](project-git-worktrees.md)：已接入；按根任务显式分配仍有未闭合证据。
- [项目数字员工](project-agents.md)：已实现；拥有项目绑定、配置覆盖和执行范围约束。
- [Git 工具错误与 DeepSeek 兼容](git-tool-compatibility.md)：已实现；收敛可恢复业务错误并稳定 Git 身份字段。
- [个人空间符号链接安全清理](workspace-symlink-cleanup.md)：已实现；只在所有者确认入口 unlink 链接目录项。
- [个人空间附件引用与延迟线程创建](workspace-attachment-references.md)：实现已接入；真实页面与部分 HTTP 证据待补。
- [输入区组合态与发送锁](input-send-lock.md)：已实现；属于局部产品交互差异。
- [Runtime cleanup 事务外执行](runtime-cleanup.md)：提案语义已接入，仍有幂等收敛证据待补。
- [Agent 专属沙盒与编码 CLI 协作](agent-coding-sandbox.md)：实现已接入，提案中的浏览器与真实账号证据待补。
- [项目 Dashboard](project-dashboard.md)：已实现统一默认概览与静态自定义页面；治理关系图从议题、决策和任务的已有外键派生。
- [项目治理域数据模型](project-governance.md)：已实现；议题/决策/任务/汇报事实、多渠道来源归一化、持续议题研讨、决策历史与工作建议纳入正式工作。
- [独立项目工作任务与 Issue](project-work-tasks.md)：一期已接入；项目与议题编号、子任务、问题单、第一负责人、追加式评论、议题缩写配置、主要来源决策、工作建议关联与失败后重新执行。
- [用户收件箱](user-inbox.md)：已接入项目任务完成、Run 待答复与任务失败/中断通知、已读与归档；真实页面证据待补。
- [项目蓝图 Workdir 事实源](project-blueprint.md)：已实现；项目蓝图固定在 Workdir `.yuanlei/blueprint/` 目录，可读写、可 diff，Agent 起草、人可编辑，旧文档可整份归档回顾。
- [项目督查板](project-inspection-board.md)：已实现；只读聚合治理事实与 Run 执行事实，跨项目只读展示，单项目工作台提供蓝图编辑、议题讨论与治理审核、工作建议纳入、旧委派历史与汇报查看。
- [外部执行器委派与 Multica 桥接](external-executor-delegation.md)：统一 codex/opencode 与 Multica 的可委派执行者接口；Multica 拉取式入向只产生 proposed，出向按 `operation_id` 标记核对，不成为事实源。
- [Milvus 启动等待](milvus-startup.md)：上游启动缺陷修复；有限等待 Proxy 就绪并保留必需组件失败语义。

- [项目设置与资源管理](project-settings-resources.md)：部分实现；项目设置与弱关联已接入，任务 Git 生命周期待实现。
