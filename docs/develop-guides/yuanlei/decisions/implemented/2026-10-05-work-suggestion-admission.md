# 工作建议纳入正式工作与执行归属

状态：implemented
类型：feature
Owner：backend/package/yuxi/services/governance_service.py

## 问题

治理任务只审核来源，却能直接委派执行，正式工作另有执行入口。个人需要一次纳入产生可追踪的正式工作，并保留旧执行。目标是同项目映射、原子审核/创建或关联、幂等与真实执行归属；不建设团队权限、周期工作定义、完整 Context Pack 或结果验收，不推断旧执行归属。

## 决策

复用治理任务承载工作建议。yuanlei v30→v31 新增建议唯一、同项目组合外键的映射，一项工作可关联多个建议。项目行锁先于建议及来源、工作锁。同建议重试返回已有映射，不同目标返回冲突。纳入服务拥有一次提交，工作创建过程拆出不提交写入供独立创建复用。关联已有工作不改其主要来源、编号或状态。

正式工作接入现有本地编码与外部委派服务，委派保存工作归属和当次来源定位。建议新建委派入口拒绝并指向正式工作。Agent 工具从当次正式工作执行定位或明确工作选择确定归属；旧委派的查询、租约恢复、回收保持原路径，旧行关联为空。

## 替代方案

串联两个会提交的服务无法保证回滚，拒绝。批量生成旧工作或迁移旧 Run 会伪造历史，拒绝。删除现有编码执行能力会破坏真实消费者，先最小接入正式工作。建议映射不表示成果验收，外部状态不改变工作业务状态。

## 后果

正式工作继续可以独立创建。关联建议不改变当前工作主要来源；历史 coding 会话、旧委派和 Run 继续按原 Owner 读取与收敛。只在 yuanlei 域增加 v31，不改变 business/knowledge 版本。个人使用，不增加组织审批或团队权限。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
| --- | --- | --- | --- | --- | --- |
| 同建议只纳入一次且同项目 | 并发重复或跨项目 | 纳入 service/repository/schema | PostgreSQL 与 HTTP | 重试不同目标及组合外键拒绝 | Passed |
| 审核创建映射原子提交 | 半条审核或孤立工作 | 纳入 service | 失败注入及数据库回读 | 映射失败全部回滚 | Passed |
| 纳入沿用来源与编号 | 无效来源或缺编号被绕过 | work service | HTTP 及页面 | 归档、无效决策、未复核拒绝 | Passed |
| 新执行归属工作且旧执行保留 | 工具或接口旁路 | delegation service/tool/router | HTTP、worker、数据库 | 建议新建入口拒绝，旧回收可用 | Passed |
| 页面可恢复且跳转正确 | 丢输入或重复创建 | Web 工作建议 | unit、lint/build 与浏览器 | 失败保留输入、已纳入链接 | Passed |

## 验证

- 基线 `develop-v0.0.1` / `dfddcd2c37884c4e7b99a574807a014eded89397`，人工暂存的 P02 核对文档保留。本地升级后数据库回读 business=7、knowledge=2、yuanlei=31；六条既有委派保持空工作与空来源。隔离 PostgreSQL 的 v30→v31 重入测试保留旧输入、不生成映射，重入保留明确关联。
- `docker compose exec api uv run --group test pytest test/integration/api/test_work_suggestion_admission_api.py -q`：5 通过。真实 HTTP 与数据库回读覆盖并发/重复纳入、多个建议关联同工作、跨项目拒绝与组合外键、不同目标冲突、拒绝记录、历史 canonical 补充关联保留原审核责任人/时间/说明、映射失败整体回滚、草案与归档来源拒绝、需复核确认、编号缺失及补齐，以及建议新建委派和无工作通用委派拒绝。
- `docker compose exec api uv run --group test pytest test/integration/api/test_work_suggestion_admission_api.py test/integration/api/test_work_decision_source_api.py test/integration/services/test_delegation_service.py test/integration/services/test_governance_service.py -q`：新增历史 canonical 用例前的最终集合 40 通过；随后纳入文件 5 通过，合计 41 项不同用例通过。委派服务真实 PostgreSQL 集合覆盖工具沿用当次决策修订、当前来源为空仍保留旧执行依据、无归属新建拒绝、旧无归属委派回收、迁移重入与项目优先锁。锁负控在工具等待项目锁时以 NOWAIT 获取 Run 行；旧 Run 优先顺序会在同一断言上失败。执行器协议使用确定性 stub，不冒充外部服务验收。
- 使用隔离测试账号和仓库确定性回放服务，`python -m pytest test/e2e/test_deterministic_agent_path_e2e.py -k test_project_work_assignment_reaches_worker_result_and_task_comment -q -rs`：4 通过。真实建议纳入 HTTP、正式工作分配、API/worker、Request、Run、评论与数据库回读覆盖手动和自动接受完成、失败、中断恢复；改变当前工作来源后当次请求仍保留原决策修订。临时回放服务已关闭，E2E 账号已停用，历史保留。
- `docker compose exec api uv run --group test pytest test/unit -m "not slow"`：2787 通过、63 跳过。Schema 精确外键集合显式补入四项新增约束；相关 Schema 单测 31 通过。`python3 -m unittest scripts.test_verify_engineering_contracts`：70 通过。
- 真实页面验证缺项目编号时保留输入、同弹窗补编号后新建跳转、关联已有工作保留原主要来源、需复核未确认拒绝和确认后纳入、已纳入链接、工作详情建议反向定位、刷新回读；450px 控件换行及浅深主题截图保存在会话产物。主题、尺寸与侧栏已恢复。

- `pnpm --dir web run test:unit`：477 通过；最后将投递/回收状态与执行终态分开展示后，两个新面板相关 unit 5 通过。Web lint、build 与 docs build 通过，工程信任检查和 `git diff --check` 通过。
- 全包 `ruff check package` 仍有 19 项既有问题，逐项核对失败源行均存在于基线 HEAD，本次新增行没有失败；`ruff format package --check` 仍受既有格式差异阻断。未为 P03 顺手格式化无关模块。

## 消费者与未验证范围

工作台的新建议入口改为纳入；正式工作保留原智能体队列并接入原 coding/外部委派服务。通用 HTTP 要求正式工作，工具以当次正式工作或明确选择确定归属。渠道同步仍只产生 proposed 建议；通知消费现有正式工作执行结果，不新增建议执行入口。Dashboard 与督查板使用待处理工作建议及纳入映射，旧图和历史来源继续读取。

真实 Multica 出向没有可用配置，本次不声称外部服务验收。实际 Codex 页面委派已持久化正式工作与版本；首次 worker 被开发环境自动重载中断，随后自然收敛为 coding_worker_lost，真实 HTTP 回收后数据库为 reclaimed/failed，记录保留。稳定环境复验因验收账号缺 Codex 授权返回 401，数据库失败终态与页面失败结果回收通过，工作仍保持待办且来源版本为 2。成功完成和文件产物未通过，不以投递或失败回收替代成功验收。临时 UI 账号已停用，测试项目和执行历史保留，测试口令文件已移除。未批量取消旧 Run、迁移旧成果或标记结果已验收。团队权限、周期 Work Definition、完整 Context Pack 与结果验收平台留后续阶段。
