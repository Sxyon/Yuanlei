# 议题纳入、研讨进度与修订历史

状态：implemented
类型：feature
Owner：backend/package/yuxi/services/governance_service.py

## 问题

一次性纳入审核锁死正文与讨论，无法在同一议题维护实践反馈。纳入资格、研讨进度与实际目标结果需要各自表达。架构依据为[系统规划](../../../../元垒系统架构规划设计/元垒系统架构规划设计.md)与[第一批范围](../../../../元垒系统架构规划设计/议题规划吸收评估与下一次开发任务.md)。

## 决策

既有 status 列仅拥有纳入事实，公开契约命名为 admission_status；增加 open/decided/closed 进度。选择已拍板关联决策后显式确认 decided，不由新建决策自动驱动。纳入审核不形成决策。修改、讨论不改变结论；拒绝后显式重新提交。重开保存 continue/pause_recommended 提示，所有任务与运行保持独立。

议题专用修订保存完整标题正文；评论绑定修订号；专用历史节点按议题递增序号分页倒序读取。所有议题写操作共享行锁，正文保存要求预期修订号。归档后只读，恢复后可维护。无决策、两类工作或执行依据引用时允许软删除；新增引用也持有议题行锁，避免删除竞态。决策记录引用当时议题修订，历史旧决策版本未知。

v27→v28 保留纳入事实，既有议题全部开放，建立带迁移标识的基线；旧评论版本未知，不还原未记录正文。不建设结果确认、回复处置、通用事件、团队权限或运行控制。

## 替代方案

单一状态机混淆纳入与结果，拒绝。永久删除会销毁历史，拒绝。新增决策自动改变进度会在重开后产生意外转换，采用用户确认的显式操作。通用事件平台缺少当前消费者，使用议题局部表。

用户界面使用“删除”和“研讨中”，逻辑删除及 `open` 留在内部契约。状态转换、组合及实际影响由[议题状态与历史](../../../../mechanisms/topic-lifecycle.md)说明。

## 后果

所有新增持久结构属于 yuanlei 域，域版本为 28。旧 status 列保留纳入含义，议题接口和新工作选择器使用 admission_status 与 progress；治理任务与决策的既有状态保持其原有语义。归档对象可定位但恢复后才能维护，软删除对象退出读取及选择器；来源标识仍保留，渠道重导入不会复活对象。真实历史未保存的正文不可恢复，迁移评论与旧决策的修订均为未知。

第一批不建设实际目标达成、回复与采纳、决策替代撤销、团队授权、周期工作或通用事件平台。上游同步保留独立纳入、持续研讨、依据快照及引用保护边界，允许迁移实现位置。真实页面的视觉与交互验收仍未完成。

## 验证

- 用户文案与状态机制说明复验：相关 Web 单测 9 passed，lint、Web build、文档 build、工程 gate 和 70 项 gate 单测通过。真实页面验收限制仍保留。

- 相关五组 integration 测试：20 passed；补充关联决策暂停提示后 HTTP 与督查服务复验：5 passed。真实 PostgreSQL 服务及 HTTP 测试验证持续研讨、拒绝后修订与重新提交、显式确认决策、软删除和归档恢复。双会话并发保存只有一个版本成功；引用提交与删除竞争时拒绝删除。关联治理任务、正式工作、执行尝试、Run 与运行输入逐项回读保持原值。
- v27 旧列结构与未版本化旧库两种入口完成真实迁移和重入，旧进度开放、迁移基线有标识、旧评论版本未知。运行环境由 storage-migrator 升级后回读 business=7、knowledge=2、yuanlei=28；上游域版本不变。
- 前端延迟响应测试验证旧分页不污染刷新首屏，旧议题发布响应不清空新议题草稿；归档读取失败明确提示且不阻断蓝图。
- `docker compose exec -T -u root api uv run --group test pytest test/unit -m 'not slow' -q`：2787 passed、63 skipped。首次执行有 6 个迁移测试替身缺少新增步骤，修复后通过；另一个 Skills 子进程测试首次超时，单独复跑和全量复跑通过，记录该环境敏感性。
- `docker compose exec -T web pnpm run lint:check`、`docker compose exec -T web pnpm run build`：通过。首次 build 发现时间格式函数错误导入，修复后通过。`docker compose exec -T web pnpm run test:unit`：460 passed。首次全量测试有一个蓝图测试未模拟新增读取，补齐替身及读取失败边界后全量通过。
- `python3 scripts/verify_engineering_contracts.py`：通过；`python3 -m unittest scripts.test_verify_engineering_contracts`：70 tests OK；`pnpm --dir docs run build`：通过。决策记录收敛后复查通过。
- 相关源码 Ruff 通过；manager 的完整 Ruff 仍报告原有三个 E501（Git 占用索引、Git 审批配置、工作引用索引长字符串），本变更不修改这些无关行。容器依赖同步以默认用户执行时出现目录权限错误，测试以 root 运行或使用已配置依赖的 `--no-sync`；pytest cache 权限警告不计为通过证据。
- 独立 Reviewer 首轮提出两个前端异步隔离 P2，均修复并以延迟响应测试验证；复核未发现阻断问题。真实浏览器页面、主题、响应式与截图：Not run，当前工具没有可用浏览器，创建 iab 也返回 unavailable。构建与组件测试不替代该项验收。
