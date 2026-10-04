# 项目资源的用户操作闭环

状态：proposed
类型：feature
Owner：backend/package/yuxi/services/project_work_service.py
日期：2026-10-04

## 问题

项目设置、Git 审批和占用记录已有实现，但任务列表完成操作遗漏成果提示，任务缺少显式知识库选择，根智能体缺少 Gitea 合并请求的查看及创建工具。已有教程无法从新平台初始化复现任务修改、提交、审批和合并。

## 提案

任务列表与详情都在完成前检查实际 Git 成果，用户明确选择先处理或保留。任务知识库选择存入 yuanlei 域，候选限定项目已关联且当前可访问的知识库；默认不选，有活动任务执行时拒绝变更，运行准备仍按实际权限归一。普通续聊和子运行从持久任务执行会话与父运行关系恢复选择，不依赖新请求来源。项目智能体配置标注关联知识库，保留已有可访问知识库选择。

根智能体仅能查看自己的任务分支合并请求，并向资源目标或持久父任务分支创建请求；提交、推送、实际合并继续走既有审批 Owner。创建请求前重新验证运行 lease，子智能体不能调用管理工具。创建合并请求由 Gitea 保存事实，批准和实际合并由平台 Git 动作记录保存事实。智能体提示只允许通过平台动作申请提交，避免沙盒 shell 提交指令与严格保护相冲突。

实际 Gitea 验证使用新建测试仓库、项目及分支，禁止使用 Yuanlei 源码仓库分支。教程面向首次使用者，按初始化、直接修改、隔离任务、审批合并、恢复与清理组织，每步写明点击入口、输入及可观察结果；配置参考继续拥有部署参数。

## 替代方案

仅保留任务详情提示会让看板绕过完成确认。仅在智能体配置选择知识库不能表达不同任务的需求。让智能体绕过 Git 工具直接操作凭据会破坏严格保护边界。采用现有 Owner 的最小补充，新增任务 JSONB 选择列，需要迁移并重载 worker。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 任务完成前显式决定遗留成果 | 看板直接完成 | ProjectWorkTasksView、成果检查 service | 前端 unit（完成检查失败和明确保留选择） | 检查失败仍要求决定 | Passed |
| 任务选择不授予知识库访问权 | 越权或全部自动注入 | project_work_service、runtime context | PG/HTTP 10 项、续聊与子运行 unit、运行准备 unit | 非关联、不可访问、活动执行拒绝；续聊和跨用户隔离 | Passed |
| 根智能体合法创建和查看合并请求 | 其他任务、任意目标、过期 lease | Git run resource、PR service | PR service unit（合法目标与 lease）；人工界面真实 Gitea | 非父任务目标和失效 lease 拒绝 | Passed |
| 指南能从新仓库复现实际合并 | 文案与 UI 不符 | 产品 UI、Gitea 协议 | 新测试仓库最终分支和文件回读 | 保留未验证范围 | Passed |

## 风险

真实模型、沙盒、ARQ 和 Gitea 依赖需分别观察失败状态。教程中的按钮与期望结果需实际页面核对，未执行场景保留 Not run。

## 验证范围

真实页面与协议验证：新建独立私有测试仓库和项目，根智能体经审批建立新的测试分支与隔离工作树，创建练习文件后停止。人工界面完成精确快照提交、推送、Gitea 合并请求创建和实际合并；从 Gitea 重新读取目标分支文件，内容为 `Yuanlei Git quickstart` 并以换行结尾。数据库中的 commit、push、merge 三个动作均为 succeeded；页面显示已合并、冻结差异和申请至执行成功的时间线，运行结束后的持续占用可见。没有使用 Yuanlei 源码仓库分支进行合并验证。

执行证据：`docker compose exec -T api uv run --no-sync pytest test/integration/api/test_project_settings_api.py -q --tb=short` 10 项通过；相关服务与工具装配 unit 通过。后端完整 unit（`docker compose exec -T api uv run --no-sync pytest test/unit -m "not slow" -q --tb=short`）2787 项通过、63 项跳过；提示与运行清单专项 29 项通过。前端完整 unit（`pnpm --dir web run test:unit`）450 项通过，追加任务知识库保存测试后任务详情专项 12 项通过；`pnpm --dir web run lint:check` 和 `pnpm --dir web run build` 通过。`python3 scripts/verify_engineering_contracts.py` 与 `python3 -m unittest scripts.test_verify_engineering_contracts`（70 项）通过。`pnpm --dir docs run build` 通过。常规 `uv run --group test` 因容器 editable.pth 写权限失败，使用容器已安装测试环境的 `--no-sync` 执行。

教程中直接修改、多个根任务排队释放、子任务独立工作树、转派、崩溃恢复和清理操作，本轮没有逐项进行浏览器端到端演练；这些步骤按当前 Owner 和已有测试核对，仍需按教程在专用测试项目验收。自动审批沿用已有持久记录和保护策略，本轮真实合并使用人工审批，未声称完成自动审批的模型端到端演练。

明确未执行（Not run）：真实看板的任务完成提示、真实模型的任务知识检索，以及新增 `git_list_pull_requests` / `git_create_pull_request` 工具的实际模型调用。真实 Gitea 合并使用人工资源界面，不能替代新增工具的模型端到端验证。
