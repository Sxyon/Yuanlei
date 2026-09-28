# 项目工作任务页面入口

状态：implemented
类型：feature
Owner：web/src/views/ProjectWorkTasksView.vue
关联 Feature：[独立项目工作任务与 Issue](../../features/project-work-tasks.md)

## 问题

项目任务底座已能通过 HTTP 创建和维护任务，但项目工作台没有入口，收件箱只链接到任务详情。用户无法在页面配置项目编号缩写、浏览任务、创建子任务或维护任务下的 Issue。

## 决策

项目工作台增加独立任务列表入口。列表页面读取当前项目缩写、任务与项目数字员工，允许固化缩写、创建普通任务或子任务，并筛选状态。任务详情提供状态、第一负责人、Issue 创建与讨论操作，所有变更以服务端回读结果为准。现有项目工作台中的治理任务仍归审核流程；新页面明确使用独立的 `/work/tasks` 协议。项目缩写新增只读 GET，用同一项目权限边界返回固化值，避免页面尝试覆盖既有缩写。

## 替代方案

- 把新任务混进治理任务列表：两个对象的状态和执行语义不同，混用会把待审核任务误当作长期工作任务。
- 仅保留收件箱详情链接：用户无法发现和创建新任务，也无法先配置项目编号。

## 后果

当前页面能够管理项目任务和 Issue 的基本生命周期。议题缩写自动生成、附件与引用、Agent 执行队列和负责人周期检查仍由[后续提案](../proposed/2026-09-27-agent-workbench-inbox-project-work.md)推进。任务状态由用户显式修改；页面显示“进行中”不证明存在运行中的 AgentRun。

## 验证

- `docker compose exec -T web pnpm run lint:check`：通过。
- `docker compose exec -T web pnpm run build`：通过。
- `docker compose exec -T api pytest test/integration/api/test_project_work_api.py -q --tb=short`：1 passed；覆盖缩写未配置、固化、跨用户及软删除后的读取。
- `docker compose exec -T web node --test test/unit/projectWorkTaskView.test.js test/unit/projectWorkTasksView.test.js`：相关 4 passed；覆盖路由切换、缩写读取和保存竞态、Issue 选择及未提交草稿。最后的控件禁用仅由构建和 lint 验证，未在含数据的浏览器页面验证。
- `docker compose exec -T web pnpm run test:unit`：403 passed、2 failed；失败均在既有 `defaultProjectDashboard.test.js` 的 Pinia 测试夹具，单独复现于前一阶段，与本次页面无关。
- `docker compose exec -T api pytest test/unit -m 'not slow' -q --tb=short`：2721 passed、61 skipped、1 failed；`test_sync_user_accessible_skills_serializes_multiple_processes` 的子进程 20 秒超时，单独复跑仍超时，与项目任务改动无交集。仓库指定的 `uv run --group test` 命令因容器全局 editable `.pth` 无删除权限未启动。
- `docker compose exec -T web pnpm run lint:check`、`docker compose exec -T web pnpm run build`、`cd docs && pnpm run build`、工程信任脚本及其 70 个单测、`git diff --check`：通过。并发执行时一次 Web build 的无关 LESS 文件编译超时，串行复跑通过；容器未安装 Ruff，未执行该 gate。
- 真实浏览器从项目工作台进入任务列表，确认未配置缩写与空列表页面正常渲染；未向用户项目写入测试任务，含数据的详情交互未在浏览器验证。
