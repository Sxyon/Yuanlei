# 元垒上游治理与同步流程

状态：implemented
类型：process
Owner：docs/develop-guides/yuanlei/README.md

## 问题

元垒长期作为 Yuxi 的 fork 存在，但仓库没有把两者关系写成可执行的工程事实：README 与文档站沿用上游品牌；上游 README 没有稳定镜像；元垒决策与上游决策混在 `docs/develop-guides/decisions/`；`yuanlei` schema 域的解耦规则只出现在个别决策里；上游同步没有报告、分类和取舍记录，冲突处理依赖临场判断。Agent 在读取文档时无法稳定区分某个功能由元垒引入还是来自上游，也无法判断改动上游实现的原因。

## 决策

- 双轨版本：元垒使用独立版本号（初始 `0.1.0`），上游能力用 Yuxi 版本和 commit 表达。`docs/develop-guides/yuanlei/baseline.json` 是同步基线的单一事实源；`README.md` 与 `README.en.md` 展示的版本与 commit 必须与它一致。
- README 体系：`README.md`、`README.en.md` 展示元垒特性与上游基线；`README.yuxi.md`、`README.yuxi.en.md` 是上游 README 的逐字镜像，对应 `baseline.json` 的 `upstream_commit`，每次上游同步后刷新。
- 治理目录：`docs/develop-guides/yuanlei/` 拥有 fork 关系、改动归属规则、上游同步流程、差异化功能索引和元垒决策；上游决策仍归 `docs/develop-guides/decisions/`。
- 决策归属：8 份由元垒创建的决策记录从上游目录迁入 `yuanlei/decisions/`，交叉链接修正；`decisions/README.md` 增加指向元垒目录的指针。
- 解耦规则：改变上游行为前先查元垒决策；涉及数据库修改必须走 `yuanlei` schema 域，升级 `YUANLEI_SCHEMA_VERSION`、挂接幂等升级链并补真实 PostgreSQL 迁移测试，不推进上游 `business`、`knowledge` 域版本。规则写入根 `AGENTS.md`、`docs/AGENTS.md` 和 `ARCHITECTURE.md`。
- 合并流程：`upstream-sync.md` 定义四阶段（差异报告、冲突评估、取舍决策、合并落地）与 R1~R5 冲突分类；`scripts/yuanlei_upstream_report.py` 生成两侧 commit、文件、重叠、yuanlei 耦合与镜像漂移报告，`--check` 校验基线与镜像。
- Gate：`verify_engineering_contracts.py` 扩展为双 decision 根校验（上游四 lifecycle，元垒 implemented/proposed），`trust.yml` 接入报告脚本测试。

## 替代方案

- 手工维护元垒差异文件清单：拒绝。文件清单必然漂移，差异事实由 Git 和报告脚本拥有。
- 元垒决策继续留在上游目录并用文件名前缀区分：拒绝。目录归属不清晰，Agent 仍需猜测；迁移一次即可消除歧义。
- 只写文档，不做报告脚本：拒绝。四阶段流程的第一步没有可执行报告时无法稳定执行，镜像和基线漂移无人发现。
- CI 自动 merge 上游：拒绝。冲突取舍需要决策记录和人工判断，自动合并会把语义冲突伪装成文本合并成功。
- 用 rebase 保持线性历史：拒绝。已共享的 fork 历史会被重写，同步回滚和审计都更困难。

## 后果

- 每次上游同步先产出报告；R4/R5 冲突在合并前必须形成元垒决策，强制留下“为什么改 Yuxi”的记录。
- `README.yuxi*.md` 与 `baseline.json` 必须在同一变更中更新，否则 `--check` 失败；上游每前进一个 commit，报告都会显示领先距离。
- 对上游文件引入少量长期 diff：`docs/develop-guides/decisions/README.md` 两行指针、`documentation-guidelines.md` 一行目录职责、`trust.yml` 一个步骤、`verify_engineering_contracts.py` 的双根校验、根 `AGENTS.md`、`docs/AGENTS.md` 和 `ARCHITECTURE.md` 的治理段落。上游同步时按 R1/R3 处理这些文件的冲突。
- 元垒决策从此受 gate 校验；`yuanlei/decisions/` 只要求 implemented 与 proposed 两个 lifecycle 目录，rejected/archived 出现时同样校验。
- 报告脚本只读取 Git 事实，不替 Agent 做取舍；判断责任仍在决策记录和 Reviewer。

## 验证

- `python3 scripts/verify_engineering_contracts.py`：通过，输出 `107 decisions / 5 workflows / 4 agents files / 166 docs / 28 routers / 258 web sources`。
- `python3 -m unittest scripts.test_verify_engineering_contracts`：64 tests OK，新增元垒决策根校验与缺失 lifecycle 目录负向用例。
- `python3 -m unittest scripts.test_yuanlei_upstream_report`：10 tests OK，临时 Git 仓库覆盖镜像漂移、中英 README 基线漂移、重命名冲突检测、重叠与 yuanlei 耦合分类。
- `python3 scripts/yuanlei_upstream_report.py --check`：检查通过（exit 0），镜像逐字一致。
- `cd docs && pnpm run build`：build complete，含新治理页面与迁移后链接。
- `git diff --check`：通过。
