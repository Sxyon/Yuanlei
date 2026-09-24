# 元垒差异语义追溯与上游合并纪律

状态：implemented
类型：process
Owner：AGENTS.md

## 问题

元垒已经记录 fork 基线、差异化功能索引、决策目录和上游同步流程，但根级开发指令没有要求 Agent 在修改上游 Owner 或解决同步冲突前重建元垒差异的业务理由、必须保留的语义和退出条件。原功能索引以简短摘要和文件路径为主，不能稳定回答某段差异为何存在、哪些只是可替换的实现、上游提供等价能力后能否缩小或删除。后续 vibe coding 可能只按文本冲突、历史代码或测试结果处理合并，使临时补丁永久化，或静默丢失元垒业务语义。

## 决策

- 根 `AGENTS.md` 强制 Agent 先分类差异来源，读取相关 Feature 与 Decision，区分业务不变量和当前实现，并在上游同步时明确选择保留迁移、上游替代、缩小差异或删除。无法重建且影响行为、数据、安全或兼容时停止并请求确认。
- `ARCHITECTURE.md` 定义元垒是 Yuxi 上的业务语义扩展：允许在真实 Yuxi Owner 中直接实现，不为形式隔离引入抽象；源码和数据拥有运行事实，Feature 拥有业务理由、集成关系和退出条件，Decision 拥有非显然取舍。
- `docs/develop-guides/yuanlei/features/README.md` 只保存导航和状态。每项现有差异使用独立 Feature 档案记录需求与失败场景、业务不变量、与 Yuxi 的边界、稳定集成点、上游依赖、合并判断、替换或删除条件、决策与证据。
- 上游同步报告只提供 Git commit、两侧文件和共同修改等可重建事实，不再用文件内的 `yuanlei` 字面量推断完整耦合关系。同步流程要求从 Feature 业务语义评价共同修改候选。
- 工程契约检查验证 Feature 的必需元数据、章节、索引覆盖、有效 Decision 链接和可定位证据入口；它不判断业务结论，也不维护 claim ID 或逐文件差异清单。

## 替代方案

- 只更新 Yuanlei 专题文档：拒绝。普通开发任务可能不主动读取专题页，根级 Agent 约束和架构不变量仍然缺失。
- 把 Yuanlei 代码迁入独立目录或插件层：拒绝。目录隔离不回答业务理由，会为当前需求引入没有证据支持的抽象和迁移成本。
- 只依赖 Git 历史和 commit message：拒绝。历史能定位修改，不能稳定表达当前仍有效的业务不变量、上游依赖和删除条件。
- 建立逐文件中央差异清单或 claim ID：拒绝。它会复制 Git、源码和测试事实并形成第二真相；Feature 只记录稳定集成点及其业务角色。

## 后果

- 修改 Yuanlei 差异和同步上游都从业务需求与不变量出发，历史实现可以被等价上游能力替换、缩小或删除。
- Yuanlei 可以继续直接修改 Yuxi 的真实 Owner；代码解耦只在重复规则、绕过风险或持续同步成本提供当前证据时进行。
- 现有八类 Yuanlei 差异各有独立 Feature 档案。档案需要随业务语义、集成角色、上游依赖或退出条件变化更新，精确 diff 继续由 Git 拥有。
- Feature 结构 gate 只证明材料存在、索引接线与引用可解析，Reviewer 仍负责判断需求、不变量和合并结论是否正确。
- 差异报告移除字面量耦合列表；既有共同修改列表继续提供完整的文本候选面。

## 验证

- `python3 scripts/verify_engineering_contracts.py`：通过，124 decisions、8 yuanlei features、5 workflows、4 agents files、197 docs、31 routers、267 web sources。
- `python3 -m unittest scripts.test_verify_engineering_contracts scripts.test_yuanlei_upstream_report`：80 tests OK；负向用例覆盖缺少业务不变量、缺少替换或删除条件、Feature 未进入索引、Decision 链接缺失、Decision 索引冒充记录、证据链接失效，以及无 `yuanlei` 标记的共同修改仍被报告。
- `git diff --check`：通过。
- `cd docs && pnpm run build`：已执行，当前起点分支的 `develop-guides/planning/agent-coding-execution-plan.md` 存在三个既有断链而失败；错误清单不包含本变更新增 Feature 或链接。该既有规划文档不在本变更范围内。
- `docker compose exec -T api uv run --no-sync --group test pytest test/unit -m "not slow" -q`：已执行，2430 passed、57 skipped、32 failed；失败集中在当前起点分支未修改的 sandbox scope、XLS parser 依赖、AgentRun fake DB 和 run worker 用例，本变更未修改 `backend/`。
