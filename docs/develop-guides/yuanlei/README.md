# 元垒与上游 Yuxi

元垒（Yuanlei）是本仓库的产品名，代码基线来自开源项目 [Yuxi](https://github.com/xerrors/Yuxi)。元垒在上游能力之上做个性化改造，并持续合并上游的新功能与修复。本目录拥有两者的关系定义、改动归属规则、差异化功能索引、元垒决策记录和上游同步流程。

## 版本与同步基线

- 元垒使用独立版本号（当前 `0.1.0`），上游能力用 Yuxi 版本和 commit 表达。双轨信息以 `baseline.json` 为单一事实源，`README.md` 和 `README.en.md` 展示的基线必须与它一致。
- 元垒版本号只记录在 `baseline.json` 和 README，上游 `backend/pyproject.toml`、`web/package.json` 的版本仍由上游拥有。`upstream_version` 是基线 commit 最近的 release tag，可以和精确 commit 不同（例如基线位于 `v0.7.3` 之后的 commit）。
- `README.yuxi.md` 和 `README.yuxi.en.md` 是上游 README 的逐字镜像，内容对应 `baseline.json` 中的 `upstream_commit`。每次同步上游后刷新镜像。
- `scripts/yuanlei_upstream_report.py` 生成两侧差异报告，`--check` 模式检测镜像与基线漂移。

## 改动归属规则

- 上游文件保持最小 diff。元垒可以在真实 Yuxi Owner 中直接实现业务差异；只在功能必需处修改，不顺手重构、格式化或重命名，也不为形式隔离引入没有当前 consumer 的抽象、插件或兼容层。
- 涉及数据库修改时必须走 `yuanlei` schema 版本：新增表、列或数据收敛写入 `backend/package/yuxi/storage/postgres/manager.py` 的 yuanlei 域定义，升级 `YUANLEI_SCHEMA_VERSION`，在 `backend/package/yuxi/storage_migration.py` 挂接幂等升级链，并补真实 PostgreSQL 迁移测试。上游 `business`、`knowledge` 域版本归上游所有，元垒不推进。
- yuanlei 域的收敛顺序依赖上游域：`project_agents` 等表的外键指向上游 `users`、`projects`、`agents`，因此 yuanlei 迁移必须在 business schema 收敛之后执行。
- 改变上游已有行为或与上游可能冲突前，先查 [features/](features/README.md) 与 [decisions/](decisions/README.md)。Feature 拥有原始需求、业务不变量、集成点、上游依赖和退出条件；没有记录时先补齐。非显然取舍在同一变更中新增或更新元垒 Decision。
- 上游新增能力与元垒功能重叠时，按 [upstream-sync.md](upstream-sync.md) 的 R1~R5 分类取舍，不静默覆盖任一方的语义。

## 目录

- [upstream-sync.md](upstream-sync.md)：四阶段同步流程、冲突分类、报告模板与合并后检查清单。
- [features/README.md](features/README.md)：元垒差异 Feature 导航；每项档案说明需求、不变量、Yuxi 集成点、上游依赖、合并判断和退出条件。
- [decisions/README.md](decisions/README.md)：元垒决策记录，生命周期与格式沿用[工程决策记录](../decisions/README.md)；上游决策仍在 `docs/develop-guides/decisions/`。
- `baseline.json`：元垒版本与上游同步基线。
