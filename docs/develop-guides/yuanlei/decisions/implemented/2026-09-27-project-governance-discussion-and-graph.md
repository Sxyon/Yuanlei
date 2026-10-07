# 项目议题讨论、决策入口与关系图

状态：implemented
类型：feature
Owner：backend/package/yuxi/services/governance_service.py
日期：2026-09-27
关联 Feature：[项目治理域数据模型](../../features/project-governance.md)、[项目 Dashboard](../../features/project-dashboard.md)、[项目蓝图 Workdir 事实源](../../features/project-blueprint.md)

当前统计与正式工作/结果关系图由[正式工作与业务结果概览](2026-10-07-formal-work-overview.md)部分取代；本文保留其余工具、授权与历史决定。

## 问题

项目议题需要承载背景、方案和讨论，短文本列表无法支持长文编辑，也没有审核前修改提议的流程。议题、决策和任务的外键已表达业务关系，但 Dashboard 的列表不能呈现关系走向。蓝图文件名不接受中文。

## 决策

议题审核后只读与正序讨论的决定由[议题纳入、研讨进度与修订历史](2026-10-05-topic-lifecycle-revisions.md)取代；本记录的正文、图关系和蓝图命名取舍仍保留。

议题正文继续使用 governance_topics.summary，按 Markdown 内容呈现；新建、修改和讨论回复单篇最多 100,000 字符。只有仍为 proposed 的议题允许修改标题/正文或追加回复，审核后正文和讨论历史可读但只读。审核、修改与新增回复锁定同一议题行，审核与写入按事务先后闭合状态竞态。回复按时间顺序追加保存，记录正文、发帖时作者名快照、作者 uid 和创建时间；回复不依赖用户外键，保留历史作者显示名。

项目工作台为议题提供独立长文编辑区、Markdown 预览和论坛式讨论串。审核操作位于议题正文与讨论之后。每条议题可直接预填新决策，决策表单支持结论与理由长文；任务可直接关联议题。已有决策继续在工作台显示。

Dashboard 从现有议题、决策、任务记录及其外键派生 SVG 关系图。节点键盘可达，可选择后查看 Markdown 详情，并链接到对应的工作台记录。每类绘制最近 10 条；Dashboard 不复制或持久化关系。蓝图名称支持中文及 Unicode 字母/数字，英文大小写保持小写；保留单层 .md 名称、120 字符和 194 UTF-8 字节 stem 上限，确保归档文件名不超过 255 字节。

议题回复表属于 yuanlei schema，版本从 11 升至 12。v11 到 v12 迁移只增建评论表和索引；存量议题无需回填。

## 替代方案

- 将回复拼入议题正文：丢失作者、时间和独立帖子边界，不能保留讨论历史。
- 在 Dashboard 另存图节点或边：复制外键关系，产生与治理事实漂移的第二个 Owner。
- 引入图表依赖：当前三列 SVG 能表达已有的一到多关系与点击详情，不需要增加运行依赖。
- 取消蓝图文件名边界：会扩大路径风险，也无法保证归档名称满足文件系统分量限制。

## 后果

议题正文、审核状态、决策和任务关系仍由治理数据模型拥有；Workdir 仍拥有蓝图正文。讨论回复只允许追加；用户修改名后历史回复保留发帖时显示名。已有 Dashboard 节点超过绘制上限时，工作台仍可查看全部记录。schema v11 的部署在 API 与 worker 启动前需要由 storage-migrator 升级到 v12。

## 验证

- python3 -m py_compile 检查受影响的 Python 源文件：通过。
- docker compose exec -T web pnpm run lint:check：通过。
- docker compose exec -T web pnpm run build：通过；构建报告已有大型 bundle 提示。
- docker compose run --rm storage-migrator：通过；PostgreSQL 回读 yuanlei=12 且 governance_topic_comments 存在。
- API 重启后日志显示 startup complete。
- 独立源码复审指出并修复：旧蓝图名称 oracle 拒绝中文、切换项目残留草稿、默认 Dashboard 缺少决策摘要，以及 SVG 图片角色遮蔽节点语义。
- docker compose exec api uv run ruff check ...：未运行成功；uv 因无权改写容器全局 editable 安装文件退出。
- Python / Web 测试未运行。
- 议题编辑/回帖与审核共享行锁；未运行真实 PostgreSQL 并发竞态测试，最终状态交错尚无自动化证据。
- 认证浏览器页面未完成核对；本地 In-App Browser 被重定向至登录页，没有有效登录态。
