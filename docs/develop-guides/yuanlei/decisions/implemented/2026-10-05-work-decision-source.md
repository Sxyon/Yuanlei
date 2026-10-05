# 正式工作来源与执行依据定位

状态：implemented
类型：feature
Owner：backend/package/yuxi/services/project_work_service.py

## 问题

正式工作缺少主要来源决策，无法说明当前依据与某次执行实际使用的版本；改变当前来源可能使旧执行失去可追溯定位。

## 决策

正式工作保存可选来源决策及批准修订号，议题仍可独立关联。新增来源只接受同项目已批准决策，同时给议题时必须一致；关联议题归档后拒绝新增引用。需复核补充要求明确确认。来源变更不重编号，通过独立来源接口核对原来源避免竞争覆盖。项目行锁优先于议题、决策和工作行锁。分配时保存本次议题及来源决策修订定位，派发使用尝试的定位作为请求元数据；当前来源变化不改旧 prompt、Request 或 Run。旧工作和尝试保持空定位，不推断。

## 替代方案

只保存决策 ID 会失去版本依据，拒绝。每次派发重读任务来源会让排队尝试被静默改写，拒绝。完整 Context Pack、验收字段、结果验收和建议纳入留后续批次。

## 后果

yuanlei v29→v30 增加可空来源字段及同项目和修订外键；新引用与执行定位参与删除保护。来源状态变化只提示个人重新核对，保留历史正文和链接，不自动暂停、迁移或替换。编号仍使用建工作时的议题缩写或 GEN。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
| --- | --- | --- | --- | --- | --- |
| 工作可独立创建或关联正式依据 | 强制来源、跨项目或不一致关系 | work service/repository/model | 真实 HTTP 与 PostgreSQL | 外项目、草案、归档议题及不一致关系拒绝 | Passed |
| 引用和删除竞争安全 | 删除后新增引用、历史来源失联 | governance/work repositories | 并发 HTTP 与持久回读 | 删除成功则引用失败，历史尝试阻止删议题 | Passed |
| 来源改变不覆盖旧执行定位和输入 | 派发时偷换当前来源 | execution service/repository | 真实 HTTP、worker E2E、数据库 | 来源改变后原尝试和请求仍引用旧版本 | Passed |
| 状态与来源在页面可理解 | 失效来源未知或需复核被推荐 | Web work views | 页面、单测、lint/build | 历史来源可读、复核提示与确认 | Passed |

## 验证

- 本地 HEAD 为 b459d823，三份人工暂存规划文件保留。`docker compose exec api uv run python -m yuxi.storage_migration` 完成 v29→v30，数据库回读 business=7、knowledge=2、yuanlei=30；原正式工作仍为空来源。
- `docker compose exec api uv run --group test pytest test/integration/api/test_work_decision_source_api.py -q`：3 通过。真实 HTTP 与 PostgreSQL 验证独立创建、跨项目和不一致来源拒绝、草案及撤销来源拒绝、需复核确认、保留撤销决策原文、归档限制、旧尝试不可被当前来源修改覆盖、新尝试采用新来源、编号不变、来源冲突、历史引用保护及引用/删除竞争。锁顺序测试由独立连接占用项目行并回读等待后验证议题 NOWAIT 可锁，防止编号配置先占议题形成反向等待。
- `docker compose exec api uv run --group test pytest test/integration/api/test_work_decision_source_api.py test/integration/api/test_project_work_api.py test/integration/services/test_project_work_service.py test/integration/services/test_project_work_execution_service.py -q`：新增锁顺序用例前的 6 项通过；新增用例及更完整历史断言由上一命令复验。相关旧 HTTP、执行服务和迁移 unit 集合另有 22 项通过。
- `docker compose exec api uv run --group test pytest test/integration/services/test_schema_migration_version.py::test_yuanlei_v29_to_v30_preserves_empty_sources_and_constraints -q`：1 通过。隔离 v29 结构升级保留旧编号/输入与空定位；重入保留明确关联，数据库拒绝跨项目、不存在修订及不完整定位。
- 临时隔离测试账号、环境变量注入口令和本地确定性回放服务下，`python -m pytest test/e2e/test_deterministic_agent_path_e2e.py -k test_project_work_assignment_reaches_worker_result_and_task_comment -q -rs`：4 通过。真实 API、worker、Request、Run 与数据库覆盖手动/自动接受、失败和中断恢复；分配后清空工作当前来源，各次执行和初始请求、Run 保留原决策/修订。无测试账号的首次命令为 4 skip，不作为通过证据。临时回放进程已停止，临时账号已停用，测试历史保留。
- `docker compose exec api uv run --group test pytest test/unit -m "not slow" -q`：2787 通过、63 跳过；既有 pytest 缓存权限警告不影响结果。随后锁顺序与可读错误修正以真实 HTTP 定向集合复验。
- Web `pnpm run lint:check`、`pnpm run build` 通过，`pnpm run test:unit`：472 全部通过。新增预填与复核确认传参、冲突选择保留及候选失效/需复核展示测试通过；相关旧交互仍通过。最终主题链接修正后，相关五个测试文件 31 项通过，lint/build 再次通过。
- 浏览器从议题进入表单正确预填议题且不强制决策，未配置议题编号时明确提示；从已批准决策进入工作表单，正确预填并创建工作；详情展示批准原文及版本。选择需复核补充但不确认时拒绝且保留选择；确认后保存，编号与待办状态不变。浅深主题、450px 详情及编辑表单检查通过，来源分区 scrollWidth 等于 clientWidth；420px 仍受既有全局最小宽度限制，不宣称适配。截图 `source-work.jpg`、`review-required.jpg`、`source-reviewed.jpg`、`source-dark.jpg`、`source-narrow.png` 为本地产物，不提交用户数据。页面最终事实再次从 PostgreSQL 读取。
- 工程信任 gate、70 项 gate 单测与 `git diff --check` 通过。独立 Reviewer 初审发现编号配置锁顺序例外，已修复并增加真实并发回归；最终复审发现新增链接暗色可读性问题，已复用主题色并更新真实截图，复审确认无剩余阻断问题；文档构建通过。

P03、完整 Context Pack、验收字段、结果验收和团队权限未实施。来源定位是执行追溯入口，完整业务文本装配留 P06。
