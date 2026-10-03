# 项目设置与任务 Git 资源生命周期

状态：proposed
类型：feature
Owner：backend/package/yuxi/services/project_service.py

## 问题

上游 Project 拥有用户与目录绑定，缺少管理属性、描述和知识库关联。元垒现有 Git 按根对话分配 worktree，无法表达任务跨智能体复用、持续目录占用和项目内 review、提交与合并。仅展示设置字段不能证明资源执行语义。

## 提案

项目设置统一呈现属性、名称与描述、资源。业务状态独立于软删除状态，默认计划中；优先级默认无优先级；负责人默认创建者，可指定任意平台成员或项目智能体，但不授予访问权限。日期可空，描述最多 255 字符。知识库单向弱关联，仅列出有读取权限的候选，配置时提供选项而不自动注入运行。

Git 资源对应完整仓库的一个分支，支持同仓库不同分支配置到不同目录。in_place 按任务或对话持续占用真实目录，其他任务 FIFO 等待；worktree 按任务与资源复用，根运行串行。子任务可继承父工作区或从父已提交 HEAD 创建独立工作区。失败保留修改和占用；未提交修改先提交或明确丢弃，才能释放与安全移除。

资源审批模式只授权操作，不自动触发操作。任务分支允许直接提交与推送，合并服从目标分支的保护规则；受保护资源分支的提交、推送、合并要求人工授权，远端保护规则始终生效。受保护资源的 Git 元数据由可信服务管理，智能体通过元垒工具请求提交审批，任务生成分支保留普通 Git 操作；此约束为已确认方案，尚未实现。项目内支持 diff、commit、推送、Gitea 合并请求及实际合并。任务完成提示未提交、未推送、未合并和未释放成果，由用户选择处理。

## 替代方案

仅增加表单不能满足真实执行与恢复。按每次 Run 新建 worktree 会割裂多轮任务。以负责人授予权限超出已确认范围。自动在任务完成时提交、推送或合并会把授权模式误作执行策略。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 设置默认值和更新可持久回读，权限不变 | 混用项目软删除状态或负责人授权 | project service/repository、yuanlei migration | `test_project_settings_api.py` 真实 PostgreSQL 与 HTTP ASGI integration | 越权、非法日期、描述超长、非项目智能体 | Passed |
| 知识库关联不授予读取权限 | 关联列表泄露不可见知识库 | permission 与关联 repository | `test_project_settings_api.py` 关联与权限撤销 integration | 撤销读取权限后不能读取 | Passed |
| 资源完整检出所选分支并正确隔离 | 分支错误、目录重叠、共享索引 | Git executor、资源 repository | 真实 Git 与 worker E2E | 同目录并发、错误分支、路径逃逸 | Not run |
| 任务持续占用与崩溃恢复可观察 | Run 结束过早释放、失败丢失修改 | 请求队列、Git ownership | FIFO 与恢复 E2E | 未提交释放、失联 owner | Not run |
| 提交和合并审批在副作用边界生效 | shell 或替代调用绕过保护 | Git executor、approval、Gitea provider | HTTP、Git、Gitea integration/E2E | 未批准受保护操作、HEAD 变化 | Not run |
| 用户可以查看与处理成果 | 只有字段或按钮，无真实操作 | 设置与 Git review UI | lint、unit、build、真实页面 | 失败、空、加载、冲突与清理状态 | Not run |

设置证据：隔离 Compose one-off 挂载当前工作树，执行 `python -m pytest test/integration/api/test_project_settings_api.py test/unit/services/test_storage_migration.py test/unit/services/test_project_settings_service.py test/unit/services/test_project_agent_service.py -q -p no:cacheprovider`，51 passed（8 integration、43 unit）。HTTP 使用真实 ASGI 路由与 PostgreSQL，测试注入用户身份；完整部署认证与 worker 链路尚未覆盖。新 Vue 表单交互测试覆盖异步切换、独立关联保存、日期与负责人校验，真实浏览器截图因工具没有可用浏览器尚未完成。Git 生命周期与任务级资源执行尚未实现，提案保持 proposed。

工程信任 verifier、70 个 verifier 单测、前端 lint/build 和文档 build 已执行通过；前端全量 unit 429 passed。后端全量 unit 首次运行 2739 passed、63 skipped、10 failed：迁移 mock 在测试启动后已修正，当前相关重跑通过；技能多进程超时单独重跑通过。挂载仓库根目录后补跑 migration、技能多进程和 config 得到 114 passed、1 failed，失败为未修改的 Compose PostgreSQL 状态路径断言；不宣称全量后端通过。全局删除智能体新增负责人 guard，真实 HTTP 拒绝与持久状态回读单独验证 1 passed。

## 风险

持久占用可能长期阻塞后续任务，必须提供可观察恢复与显式释放。Git 多步副作用需记录意图并回读结果，不能以 HTTP 成功替代最终状态。所有新增结构由 yuanlei schema 版本升级，保持上游 business/knowledge 版本不变。历史 worktree 与已提交分支保留，迁移不得丢弃用户成果。
