# 上游 Yuxi 同步流程

本流程把上游 `xerrors/Yuxi` 的变更合并进元垒，按「差异报告 → 冲突评估 → 取舍决策 → 合并落地」四阶段执行。每次同步都产出可复查的报告、决策链接和验证结果。

## 坐标与前置

- 上游 remote 为 `upstream`，只使用 `refs/remotes/upstream/main`。本地存在同名分支 `upstream/main` 时 Git 命令会产生歧义警告，不要依赖它（建议删除：`git branch -D upstream/main`）。
- 同步前更新远端跟踪引用：`git fetch upstream`。基线为 `git merge-base HEAD refs/remotes/upstream/main`，与 `baseline.json` 的 `upstream_commit` 一致。
- 工作区干净，在专用分支上同步：`git switch -c sync/yuxi-YYYYMMDD`。

## 阶段 1 差异报告

```bash
python3 scripts/yuanlei_upstream_report.py --fetch --output tmp/upstream-report.md
```

报告必须包含：上游与元垒各自的领先/落后 commit、两侧文件清单、共同修改文件、决策记录变化、README 镜像与基线一致性。共同修改只表示候选影响面；是否影响元垒语义由相关 Feature、Decision、源码 Owner 和测试共同判断。差异事实由 Git 生成，不手工维护第二份文件清单。

## 阶段 2 冲突评估

先阅读上游 commit 与改动符号，再对照全部 Feature 的「稳定集成点」和「上游依赖」筛查影响。上游单侧修改也可能改变元垒依赖的入口、数据或行为，不能因为 Git 没有共同修改就直接判定安全。确认受影响的 Feature 后，再按语义关系分类：

| 类别 | 情形 | 默认处理 |
|---|---|---|
| R1 | 只有上游修改，且确认不影响任何元垒 Feature | 直接接受上游版本 |
| R2 | 只有元垒修改或元垒独有文件 | 保留元垒版本，再按 Feature 验证业务语义 |
| R3 | 同文件不同区域 | 接受自动合并，人工核对语义与测试 |
| R4 | 同一行为双方都改 | 查元垒决策；默认保留元垒语义并吸收上游修复，必要时更新决策 |
| R5 | schema、迁移顺序或持久化 Owner 交叉 | 停下写决策；禁止静默改动上游域版本或迁移顺序 |

R4、R5 以及影响运行语义的 R3 必须在合并提交前形成取舍决策，记录到 [decisions/](decisions/README.md)。

对每个受影响的元垒 Feature，先读取对应[差异化功能档案](features/README.md)，重建原始需求、业务不变量、上游依赖和退出条件，再选择一种结果：

- 保留业务语义，并把实现迁移到上游的新结构；
- 上游已经等价覆盖，采用上游实现并删除元垒差异；
- 上游部分覆盖，采用公共能力并缩小元垒差异；
- 原始需求已经失效，删除过期行为；
- 两侧业务目标产生新的非显然取舍，新增或更新 Decision。

文本冲突、`ours/theirs`、旧代码归属和测试变绿都不能单独决定结果。无法重建理由且改动影响行为、数据、安全或兼容时，停止合并并请求确认。

## 阶段 3 取舍决策

- 新建或更新 `decisions/implemented/YYYY-MM-DD-topic.md`，进行中的提案写入 `decisions/proposed/`，遵守[工程决策记录](../decisions/README.md)的格式。
- 决策写明上游当前实现、元垒差异与原因、被拒绝的替代方案、合并后的边界和验证证据。
- 同步更新受影响 Feature 的当前边界、集成点、上游依赖、退出条件和证据；索引只更新状态与导航。
- 上游完整吸收元垒差异时，把功能条目标注为「已回归上游」，删除不再需要的兼容代码，并在决策中记录取代关系。

## 阶段 4 合并落地

```bash
git merge refs/remotes/upstream/main
```

- 按取舍决策解决冲突；重大修改可以先形成独立 commit，再完成 merge commit。
- 更新 `baseline.json`（上游 commit、版本、日期）、`README.yuxi.md`、`README.yuxi.en.md` 和 README 展示的基线。
- 运行最小验证：`python3 scripts/verify_engineering_contracts.py`、`python3 -m unittest scripts.test_verify_engineering_contracts scripts.test_yuanlei_upstream_report`、`git diff --check`；按改动面执行[测试规范](../testing-guidelines.md)要求的最低证据，涉及持久化、Run 或权限时扩大到真实 PostgreSQL、HTTP、worker 或浏览器语义。
- 提交信息列出：上游基线、吸收的上游变更、保留的元垒差异、新增决策链接、验证命令与结果。
- `python3 scripts/yuanlei_upstream_report.py --check` 无漂移后才能合并到主干。

## 回滚

合并未推送前用 `git merge --abort` 或 `git reset --hard` 回到同步前 commit。已推送的 merge commit 用 `git revert -m 1 <merge>` 撤销，随后重新评估上游差异；已共享历史不强制改写。

## 镜像与基线检查

```bash
python3 scripts/yuanlei_upstream_report.py --check
```

检查项：`README.yuxi.md` 与 `baseline.json:upstream_commit` 处上游 `README.md` 字节一致；`README.yuxi.en.md` 与上游 `README.en.md` 字节一致；`baseline.json:upstream_commit` 等于当前 merge-base；`README.md` 和 `README.en.md` 展示的 Yuxi 版本与 commit 与 `baseline.json` 一致。任一不一致退出码为 1。
