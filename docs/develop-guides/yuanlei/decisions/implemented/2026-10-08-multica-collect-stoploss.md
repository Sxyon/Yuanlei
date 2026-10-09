# Multica 不可信回收的独立止损

状态：implemented
类型：bug-fix
Owner：backend/package/yuxi/delegation/multica.py

## 问题

元垒的 Multica Adapter 仅取得 issue 投影，却用 description 生成成功交付；未完成工作项也进入 reclaimed，文本物化到 Workdir，done 可导入待验收结果。上游 Run/Workdir 不拥有 Multica 交付来源，修复位于元垒外部执行器差异。本记录部分取代[桥接决策](2026-09-25-external-executor-delegation-multica-bridge.md)的 Multica 回收约定，保留其委派、查询与入向同步决定。

## 决策

在真实 collect 入口拒绝非 done 状态，以结构化未就绪错误返回；done 仍缺准确尝试及正式输出来源，以结果未核实错误返回。description、标题和工作项 URL 只作定位/状态资料，不能生成 DelegationResult。复用 DelegationService 的 owned collecting 异常释放事务，恢复 dispatched 并清除 owner/lease；保留 status、其他执行器以及已 reclaimed 的幂等读取。

直接 Adapter、默认注册的 HTTP/Service 入口均执行同一拒绝边界。DelegationService、Result Owner 与 Workdir 保留当前事务及幂等语义；Schema、远端协议、Andon、配置和历史数据保持当前边界。

## 替代方案

仅拒绝非终态仍允许 done 描述冒充输出；仅隐藏按钮可绕过；立即增加远端 Run/结果协议依赖未证明的服务能力。采用 collect 边界拒绝能独立阻止新增不可信结果，保留查询与未来恢复接口。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
| --- | --- | --- | --- | --- | --- |
| 描述不能回收为输出 | Adapter 返回描述型成功 | MulticaExecutor.collect | `test_multica_executor.py`、`test_multica_rejection_releases_owned_lease_without_result_or_file` | 恢复描述型返回后拒绝及无结果断言失败 | Passed |
| owned 拒绝保留处理能力 | 提前 reclaimed 或遗留租约 | DelegationService.collect | `test_multica_rejection_releases_owned_lease_without_result_or_file`、`test_multica_collect_http_rejects_projection_and_releases_lease` | 非终态/未核实两次拒绝仍 dispatched | Passed |
| 迟到拒绝不释放新租约 | 旧 owner 覆盖新 owner | collect 异常分支 | `test_multica_late_rejection_preserves_new_collecting_owner` | 接管期间旧拒绝不能清空新 token/lease | Passed |
| 其他执行器及缓存结果不变 | 可信回收/幂等被扩大拒绝 | Service、Result Owner | `test_collection_owner_and_automatic_result_are_preserved`、`test_multica_reclaimed_history_remains_idempotent` | 旧 reclaimed Multica 原样读取 | Passed |

直接入口的七种状态负控、缺句柄拒绝，以及真实 PG 新事务回读、临时 Workdir 字节回读和双事务接管测试构成独立 oracle。旧实现上运行直接入口测试出现七项未拒绝失败，PG 的非终态/未知/done 三项同样出现未拒绝失败；新边界使它们拒绝。真实平台网络由内存远端投影替代，HTTP 使用 ASGI 传输，Adapter/Service/注册、PostgreSQL 和文件边界保留真实实现。

| 命令 / 核对 | 结果 |
| --- | --- |
| `docker compose exec -T api uv run --group test pytest test/unit/delegation test/integration/services/test_delegation_service.py test/integration/api/test_delegation_router.py test/integration/api/test_project_work_results_api.py -q -p no:cacheprovider` | Passed：61 项；含真实 PG/Workdir、HTTP 拒绝、其他执行器与结果唯一性。增强后的历史 accepted 夹具另由下行核对 |
| `docker compose exec -T api uv run --group test pytest test/integration/services/test_delegation_service.py -k multica_reclaimed_history -q -p no:cacheprovider` | Passed：1 项，accepted 的版本/审阅/来源与文件保留 |
| `docker compose exec -T api uv run ruff check --no-cache package/yuxi/delegation/multica.py test/unit/delegation/test_multica_executor.py test/integration/api/test_delegation_router.py` | Passed；相同三文件 `ruff format --no-cache ... --check` 通过 |
| `docker compose exec -T api uv run ruff check --no-cache test/integration/services/test_delegation_service.py --output-format json` | 未通过：30 处既有测试代码问题均位于新增块之前；新增块无问题，保持旧代码范围 |
| `python3 scripts/verify_engineering_contracts.py` | 未通过：既有 ef65969 深度评估四处措辞，本记录与本轮文档无错误 |
| `python3 -m unittest scripts.test_verify_engineering_contracts` | Passed：70 项 |
| `docker compose exec -T api uv run --group test pytest test/unit -m 'not slow' -p no:cacheprovider` | Passed：2815 passed、63 skipped、7 subtests passed、9 warnings，360.57 秒；63 项因容器未挂载仓库根目录而跳过，不计作已验证 |
| 独立 Review | 全新 Reviewer 审查完整需求、diff、源码、规范与测试；无遗留功能/边界/复杂度问题，另独立执行 Multica unit 14 项通过。未访问远端或凭据 |
| `docker compose exec -T api uv run --group test pytest test/unit/config -q -rs -p no:cacheprovider` | Passed：32 passed、63 skipped；核对全部跳过原因为未挂载仓库根目录 |
| `cd docs && pnpm run build` | Passed：33.39 秒，有 bundle 大小警告；仅证明文档构建 |
| 本任务相对链接 / 空白 | Passed；全工作树 `git diff --check` 被用户既有模型文件尾随空白阻塞，保持该文件 |

真实 Multica 派发、权限、取消、准确远端输出与原运行恢复均为 Not run，后续具体试验卡另行验证。worker/真实外部 CLI E2E 未执行：止损发生在回收入口，最低直接证据由真实 PostgreSQL、HTTP 与 Workdir 回读提供，执行器真正运行/远端可信交付继续属于独立试验。

## 后果

现有 Multica 成功回收暂时全部关闭，即使 issue 标 done。恢复条件是 Adapter 能提供当前绑定尝试的可信终态和正式输出，并以来源错配/非终态负向证据证明；更换摘要文本不能满足。历史错误 reclaimed 保持原样，逐对象纠正须另行授权。
