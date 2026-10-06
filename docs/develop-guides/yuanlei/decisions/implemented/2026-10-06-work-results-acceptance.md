# 正式工作验收条件与人工结果

状态：implemented
类型：feature
Owner：backend/package/yuxi/services/project_work_result_service.py

## 问题

工作完成状态缺少可追溯的验收依据，人工结果与执行输出混淆，编码和外部委派可能绕过现有智能体完成守卫。读者为工作模块维护者；目标是个人手工结果提交、明确验收及统一完成边界。

## 决策

yuanlei 32→33 增加工作 Markdown 条件与修订号、最小追加式结果。要求（工作描述和验收条件）共用修订号；修改核对修订号，提交固化正文和修订；结果保存摘要、证据、未解决事项、提交人和时间，以及可选同工作执行或委派来源。来源通过组合外键归属，人工提交不创建 Run。

结果待验收、已接受、未接受与工作状态分离。首次验收写入意见、操作者、时间及结果版本，重复相同请求返回原结果，改变已验收记录失败。提交使用工作内唯一请求标识及意图摘要防止重复和异值重放。条件不一致可保留历史验收，但完成仅使用当前条件的已接受结果。旧 done 保留且标明未记录验收依据；done 后条件改变不把旧结果当作满足新条件。

完成涉及 Git 时先取得既有 runtime 锁，再按项目、任务、结果锁和同工作委派行锁提交；普通结果与要求修改按项目优先。回收持有的委派行锁提交后，完成才重新读取活跃事实。完成守卫检查智能体尝试、编码与外部委派真实状态；保留原 Git 成果检查，需关注时要求明确确认保留。结果、接受、完成通知同事务。普通状态修改、看板、工具复用完成守卫。

证据复用当前工作附件、Workdir 文件和 HTTP(S) URL；服务在资源边界检查可访问性并返回不可用原因，URL 只标记引用未读取。提交保存引用与当时可访问状态，读历史时显示当前状态，验收不把可访问等同内容合格。

## 替代方案

不将评论迁移为结果，不推断旧 done 的依据。完整 Context Pack 和 Run 输出反馈分别保留在 P06/P07；通用 Review、团队权限和周期工作定义无本批消费者。

## 后果

后续提交形成新记录，保留旧快照；证据字节仍由现有文件或对象存储拥有，删除证据后历史引用明确不可用。当前条件缺失只提示，人工仍可明确验收简单工作。P03 Codex 成功产物与 Multica 出向待补验收。

## 验证

- `docker compose exec -T api uv run --group test pytest test/integration/api/test_project_work_results_api.py test/integration/services/test_work_result_migration.py test/integration/api/test_project_work_api.py test/integration/services/test_project_work_service.py test/integration/services/test_project_work_execution_service.py -q`：6 passed。真实 PostgreSQL 迁移重入保留旧 done；HTTP 验证人工无 Run、跨工作来源失败、附件越权/删除不可用、并发幂等、异值重放、条件冲突及结果/通知原子性。两种执行入口和本地 coding turn 均阻止活跃时完成；委派显示 failed 但真实 turn 仍 running 的负向 HTTP 复验 1 passed；委派回收 barrier 证明完成等待行锁，回收变活跃后拒绝且无半条结果。
- `docker compose exec -T api uv run --group test pytest test/unit -m "not slow"`：2794 passed、63 skipped、7 subtests passed。跳过项保留原规则。
- `docker compose exec -T web pnpm run lint:check`、`pnpm run test:unit`、`pnpm run build` 全部通过；unit 495 passed。构建保留现有 chunk 大小提醒。Web 相关组件回归 20 passed；实际父模板覆盖刷新/错误时保留结果草稿，迟到响应和切回同工作不能清空新输入，动作变更更新幂等标识。
- 真实浏览器在隔离普通用户和项目中完成：提交→未接受→新提交→接受（工作仍待办）→另一页面修改条件→旧页面冲突并保留草稿→加载最新要求→提交并完成→刷新。非法文件引用失败后输入保留，旧 done 显示历史无验收依据。HTTP 与数据库最终回读工作 done、结果 accepted/accepted/not_accepted、快照修订 2/1/1、操作者和时间完整，该用户 AgentRun=0；运行数据库 yuanlei=33。
- 浅深主题及结果历史截图保存在本地验收附件中。页面 URL 明确显示仅引用未读取。450px 窄屏实际 DOM 为 body=450、main=398、结果面板=350，无横向溢出；截图核对字段与结果卡片可读。恢复原主题、侧栏与设备覆盖。
- `python3 scripts/verify_engineering_contracts.py` 通过；`python3 -m unittest scripts.test_verify_engineering_contracts`：70 passed。
- 本批文档相对链接检查通过；`pnpm --dir docs run build` 通过，保留原有 bundle 大小提醒。隔离验收账号已停用，临时凭证文件清理，旧用户数据未重置。
- 独立 Reviewer Agent 全需求、diff、规范及证据只读复审，修复刷新卸载与请求标识问题后未发现剩余阻断代码问题；Reviewer 未独立执行测试。

P03 真实 Codex 成功产物及 Multica 出向仍待补验收；本批未以人工机制代替其证据。完整 Context Pack 与 Run 自动结果反馈分别保留 P06/P07。
