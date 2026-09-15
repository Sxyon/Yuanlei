# Dashboard 会话用量与图表可读性

状态：implemented
类型：bug-fix
Owner：backend/package/yuxi/repositories/dashboard_repository.py

## 问题

会话 active 表示未归档，无法证明 Agent 正在执行。ConversationStats 的 Token 字段未随 Run 用量更新，依赖该字段的审计无法反映实际消耗。工具长名称和饼图标签受半宽布局挤压；文件类型图例与圆环重叠，自动轮播的单类数值也容易被误认为整个圆环的含义。

## 决策

会话列表、筛选和详情将 active 展示为“未归档”。DashboardRepository 从同 conversation_id 的 AgentRun.token_usage 汇总已报告的实测 Token，用 complete 标记识别部分统计；列表先分页，再聚合当前页 Run，详情只聚合对应会话。无 Run 的历史会话保留非零 ConversationStats 汇总，旧汇总的零值无法证明已采集用量，显示未知。

列表与详情共享读取口径：完整统计显示数值，部分统计显示“≥ 已知值”，全部缺失显示“未记录”；真正报告的零仍显示 0。会话统计概览和智能体分组使用同一来源，求和含义为已记录用量。各子会话独立统计，不重复累加父子用量。

ToolStatsComponent 使用全宽名称、次数和占比表，替代重复且受宽度限制的错误饼图；最常用工具按调用量取最高十项。KnowledgeStatsComponent 将圆环与可换行的 DOM 明细分开，圆心固定显示文件总数，明细显示每类数量和比例；非零且不足 0.1% 的比例保留“小于”提示。图表监听容器大小，卸载时释放实例和观察器。

## 替代方案

回填 ConversationStats 增加持久化同步与历史迁移责任；直接读取已有 Run 事实满足审计需求。固定半宽饼图继续限制长名称；完整表格更适合精确比较错误次数。文件类型保留圆环整体比例，同时通过明细表达很小的分类。

## 后果

不改变运行生命周期、用量写入、权限或历史持久数据。没有持久化用量事实的历史运行无法恢复真实账单，部分统计只能表示已记录的下界。列表和详情的 total_tokens 允许 null，token_usage_complete 明确表达数据完整性；会话概览的总量是已记录值之和。

## 验证

- `docker compose exec -T api uv run --no-sync --group test pytest test/unit/services/test_dashboard_service.py -q`：8 项通过。回归测试先复现旧汇总 3500 覆盖 Run 实测 200，再验证多 Run、部分缺失、全部缺失和真实零。
- `docker compose exec -T api timeout 120s uv run --no-sync --group test pytest test/integration/api/test_dashboard_router.py -q -s`：12 项通过；真实 PostgreSQL 写入与 HTTP 回读证明列表和详情在旧汇总冲突时仍返回 Run 总量及完整性。
- `docker compose exec -T api timeout 180s uv run --no-sync --group test pytest test/unit -m 'not slow' -s`：1935 项通过，53 项按既有测试条件跳过；跳过项不计为通过。默认 capture 模式在既有异步清理阶段挂起，关闭 capture 后完成。
- `docker compose exec -T web pnpm run test:unit`：330 项通过；`docker compose exec -T web pnpm run build` 通过。
- `playwright-cli -s=dashboard-fix run-code --filename=web/test/browser/dashboardStats.js`：页面验证覆盖 1440、1024、768、375 宽度、长工具名、八类文件、深色与空数据；图表边界使用显式合成响应，会话状态另由真实接口回读。
- 修改文件 ESLint、Ruff、工程契约及其 62 项单测通过。全量 ESLint 被未修改的 pdfPreviewAssets.test.js 中 Buffer 未声明阻断。标准 uv run 依赖同步因容器安装目录权限失败，测试使用已安装依赖和 --no-sync。
