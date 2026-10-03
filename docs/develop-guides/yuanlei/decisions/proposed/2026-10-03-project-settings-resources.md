# 项目设置与任务 Git 资源生命周期

状态：proposed
类型：feature
Owner：backend/package/yuxi/services/project_service.py

## 问题

上游 Project 拥有用户与目录绑定，缺少管理属性、描述和知识库关联。元垒现有 Git 按根对话分配 worktree，无法表达任务跨智能体复用、持续目录占用和项目内 review、提交与合并。仅展示设置字段不能证明资源执行语义。

## 提案

项目设置统一呈现属性、名称与描述、资源。业务状态独立于软删除状态，默认计划中；优先级默认无优先级；负责人默认创建者，可指定任意平台成员或项目智能体，但不授予访问权限。日期可空，描述最多 255 字符。知识库单向弱关联，仅列出有读取权限的候选，配置时提供选项而不自动注入运行。

Git 资源对应完整仓库的一个分支，支持同仓库不同分支配置到不同目录。in_place 按任务或对话持续占用真实目录，其他任务 FIFO 等待；worktree 按任务与资源复用，根运行串行。子任务可继承父工作区或从父已提交 HEAD 创建独立工作区。失败保留修改和占用；未提交修改先提交或明确丢弃，才能释放与安全移除。

资源审批模式只授权操作，不自动触发操作。任务分支允许直接提交与推送，合并服从目标分支的保护规则；受保护资源分支的提交、推送、合并要求人工授权，远端保护规则始终生效。受保护资源的 Git 元数据由可信服务管理，智能体通过元垒工具请求提交审批，任务生成分支保留普通 Git 操作；此约束为已确认方案。可信 metadata 位于 API/worker 共享的独立持久目录，不挂载到 Agent 沙盒；用户可写 checkout 的快照由可信 executor 用 no-follow 文件读取构造，审批固定 HEAD 与内容树。已有任务 worktree 继续保留，不能作为受保护资源 HEAD 的权威。项目内支持 diff、commit、推送、Gitea 合并请求及实际合并。任务完成提示未提交、未推送、未合并和未释放成果，由用户选择处理。

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

设置证据：隔离 Compose one-off 挂载当前工作树，执行 `python -m pytest test/integration/api/test_project_settings_api.py test/unit/services/test_storage_migration.py test/unit/services/test_project_settings_service.py test/unit/services/test_project_agent_service.py -q -p no:cacheprovider`，51 passed（8 integration、43 unit）。HTTP 使用真实 ASGI 路由与 PostgreSQL，测试注入用户身份；完整部署认证与 worker 链路尚未覆盖。新 Vue 表单交互测试覆盖异步切换、独立关联保存、日期与负责人校验，项目设置三模块与资源默认授权模式已在真实浏览器查看；任务成果操作和执行链路仍需补齐，提案保持 proposed。

工程信任 verifier、70 个 verifier 单测、前端 lint/build 和文档 build 已执行通过；前端全量 unit 429 passed。后端全量 unit 首次运行 2739 passed、63 skipped、10 failed：迁移 mock 在测试启动后已修正，当前相关重跑通过；技能多进程超时单独重跑通过。挂载仓库根目录后补跑 migration、技能多进程和 config 得到 114 passed、1 failed，失败为未修改的 Compose PostgreSQL 状态路径断言；不宣称全量后端通过。全局删除智能体新增负责人 guard，真实 HTTP 拒绝与持久状态回读单独验证 1 passed。

## 风险

持久占用可能长期阻塞后续任务，必须提供可观察恢复与显式释放。Git 多步副作用需记录意图并回读结果，不能以 HTTP 成功替代最终状态。所有新增结构由 yuanlei schema 版本升级，保持上游 business/knowledge 版本不变。历史 worktree 与已提交分支保留，迁移不得丢弃用户成果。

## 第二阶段已执行证据与剩余范围

资源分支完整检出、可信元数据与内容快照、人工提交/推送/恢复、任务资源占用、工作树继承/隔离、沙盒挂载与 generation 撤销已进入实现。新增持久结构分别由 yuanlei 23、24、25 迁移管理，实际部署已回读 yuanlei 25；business 与 knowledge 版本保持不变。

本地实际执行：

- `docker compose exec api uv run --no-sync pytest test/unit -m 'not slow' -q --tb=short`：2766 passed、63 skipped。规定的 `uv run --group test` 因容器内 editable.pth 更新权限失败；已安装依赖下执行上述测试，不能称依赖同步通过。
- `test/integration/services/test_project_git_occupancy.py`：真实 PostgreSQL 3 passed，覆盖持久 FIFO、隔离分配不参与共享目录队列、共享子任务历史禁止改工作区模式。
- `test/integration/api/test_project_git_resource_api.py`：真实 HTTP ASGI、PostgreSQL 与本地 Git 5 passed，覆盖快照变化拒绝提交、越权拒绝、失败检出内容恢复、实际远端推送回读、拒绝覆盖远端进展。认证身份由测试依赖注入；Git 远端是本地 bare 仓库，不替代 Gitea 集成证据。
- `test/e2e/test_project_git_mount_boundary_e2e.py`：真实 Docker 1 passed，覆盖挂载只读/可写结果、跨挂载硬链接拒绝、旧 generation 撤销与旧请求拒绝。尚不替代完整 worker/FIFO/取消恢复 E2E。
- 前端此前全量 unit 433 passed；新增 `gitResourcePanel.test.js` 的 5 项交互测试通过，覆盖轮询保留草稿/审查状态、过期项目响应、精确提交/推送确认与实际合并状态投影。前端 lint 与 build 已通过；当前增量仍需最终 gate。
- 工程契约 verifier 通过，verifier 单测 70 passed。服务中的宿主路径解析已移到 workspace Owner。

Gitea 合并前回读当前目标分支 HEAD，源 HEAD 交由 Gitea `head_commit_id` 再校验。Gitea 合并接口没有目标 HEAD 的原子 CAS 参数：合并前检查不能承诺阻止外部写入者在检查和合并之间更新目标，必须保留这一实际限制，不能把页面确认描述为原子锁定两个分支。

尚未完成：任务工作树完整人工成果操作、智能体模式对应的受保护操作审批与自动授权链路、任务完成成果提示、任务知识库选项、真实 Gitea 创建/状态/合并集成证据、完整 worker 恢复 E2E、最终独立全量审查。上述未完成项不应因已有字段、按钮、unit 或 HTTP 200 视为交付。


## 仓库绑定的候选读取

用户配置 Gitea 连接后需要用下拉选择仓库与分支，避免重复输入仓库归属、名称与默认分支。候选由当前用户拥有的 active 连接读取 Token 可访问的远端仓库，选择仓库后自动填写归属、名称、资源名称、默认目录及默认分支；资源名称和目录保留编辑能力。同一仓库多分支仍需选择不同项目目录。Token 仅在服务端解密，候选不授予新的 Gitea 权限，也不代替绑定时的 canonical 仓库校验。连接或项目切换后，迟到响应不能恢复旧候选或旧表单归属。失败显示可重试错误，不能把旧候选作为新连接的列表。

验证：`test/integration/api/test_git_discovery_api.py` 真实 PostgreSQL 与 HTTP ASGI 4 passed，覆盖候选协议、跨用户连接拒绝、停用连接拒绝及远端错误脱敏。远端响应在该 integration 中替换；实际开发环境 Gitea 仓库列表另经真实页面读取。前端 `gitResourcePanel.test.js` 8 passed，包含自动填写、跨连接/项目迟到响应拒绝、分支读取失败禁止绑定；Gitea 候选分页及非法响应 unit 2 passed。


## 中间状态提交边界

中间提交保存当前实现及已有证据，提案保持 proposed。人工清理只移除 Git 审查范围中的文件，保留 ignored 内容；`test_discard_preserves_ignored_files_added_after_review` 验证审查后新增忽略文件不会被删除。资源准备先取得用户 advisory lock，锁定绑定、占用再锁定工作树；真实 PostgreSQL `pg_locks` 阻塞 oracle 验证准备不能在释放侧持有用户与占用锁时提前锁住工作树。上述文件/API 联合测试 13 passed，新增锁顺序 integration 1 passed。

全量 backend unit 执行 `docker compose exec api uv run --no-sync pytest test/unit -m 'not slow' -q --tb=short`：2772 passed、63 skipped；执行期间的后续锁顺序修改以相关 service unit 重跑补充验证。独立 Reviewer 完成完整中间 diff 审查，修复清理范围、锁顺序、页面授权承诺三项问题后复核通过；批准只覆盖中间状态。自动授权选项在界面禁用并标为开发中，智能体审批与完整任务成果处理不作当前交付承诺。
