# 元垒差异语义追溯与上游合并纪律

状态：proposed
类型：process
Owner：AGENTS.md

## 问题

现有 fork 治理能定位元垒与 Yuxi 的 Git 差异，但不能稳定回答一项差异为何存在、必须保留什么业务语义、依赖哪些上游集成点、何时可替换或删除。后续 vibe coding 和上游同步容易以文本冲突或历史实现代替业务判断，也可能为形式解耦引入无当前消费者的工程表面。

## 提案

- 在根 `AGENTS.md` 和 `ARCHITECTURE.md` 明文规定：元垒可以在 Yuxi 真实 Owner 中直接扩展，代码位置不决定差异归属，抽象必须有当前证据。
- 每项长期元垒差异建立独立 Feature 档案，记录需求、失败场景、业务不变量、Yuxi 边界、稳定集成点、上游依赖、合并判断和退出条件。
- Feature 必须链接有效的元垒 Decision 与仓库内可定位证据；结构和引用由工程契约 gate 校验，业务充分性由 Reviewer 判断。
- 上游同步先按 Feature 的集成点与依赖筛查影响，再选择保留并迁移、上游替代、缩小差异或删除过期行为。

## 替代方案

- 把元垒代码全部迁入独立目录或插件层：拒绝。不能回答差异的业务理由，且增加迁移与抽象成本。
- 只依赖 Git 历史和 commit message：拒绝。它们无法稳定表达当前仍有效的业务不变量和退出条件。
- 建立逐文件中央差异清单：拒绝。该清单会复制 Git 与源码事实，形成第二真相。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 根指令与架构文档明确要求先重建差异的业务语义 | 合并时丢失或永久保留无理由差异 | `AGENTS.md`、`ARCHITECTURE.md` | 独立 Reviewer 逐条对照用户需求检查文档约束 | 移除业务不变量、退出条件或禁止形式解耦时 Reviewer 拒绝 | Not run |
| 每项长期差异都有 Feature、Decision 和证据 | 文档仅有概要或失效链接 | `docs/develop-guides/yuanlei/features/` | `python3 -m unittest scripts.test_verify_engineering_contracts` | 删除必需章节、Decision 或证据入口时测试失败 | Not run |
| 上游同步文档要求以 Feature 影响与业务语义选择策略 | 只按共同修改或文本标记处理 | `docs/develop-guides/yuanlei/upstream-sync.md` | 独立 Reviewer 语义审查；`python3 -m unittest scripts.test_yuanlei_upstream_report` 只验证 Git 候选面 | 移除 Feature 影响筛查时 Reviewer 拒绝；无 `yuanlei` 字面标记的共同修改仍必须报告 | Not run |

上表为 proposal commit 的初始证据状态，实现、命令执行与独立审查尚未发生。

## 风险

- Feature 档案可能变成第二份实现清单；因此只记录稳定业务语义与集成角色，精确 diff 仍由 Git 拥有。
- 结构 gate 可能促生空洞文案；因此 gate 只保证材料与引用存在，语义质量继续由独立 Reviewer 负责。
- 既有差异的证据完整度不一；缺失的真实测试必须标记 `Not run`，禁止用推测冒充验证。
