# LOG-DB-001｜主题阶段状态与证据

状态：2026-10-18按用户要求阶段暂停，开发成果保留；最终验收未完成。整理前代码快照为`63dc5af7442812a928ed0af0c4795a2a8acc3621`。需求见[SYS](SYS-DB-001-Dashboard系统需求与架构设计.md)，维护和补验见[DEV](DEV-DB-002-项目主题实施指南.md)。本页以阶段摘要替代逐轮执行日志。

## 用户方向与确认范围

| 日期 | 原用户依据与适用范围 |
| --- | --- |
| 2026-10-11 | S01项目入口已获验收，评价“基本能用，审美较差”；完整属性创建、图标上传及全局大小写不敏感且首次设定后不可变slug已确认 |
| 2026-10-12 | “采纳方案”：Vue可信组件＋受控JSON资源包、独立主题文件域、PG来源／版本／绑定、双数据与原包迁移路线；S03六页原型的页面组织和关键交互获确认 |
| 2026-10-13—14 | 项目维度全部界面通过主题管理，旧页面结构允许重构。原文“批准此次设计稿，纳入系统设计规划中，弹窗样式依旧未做任何样式审核”：对象为DB-P07 R3及同栏工具、共享点击区、蓝图历史返回等补充，准确字节见[设计确认回执](图解/21-full-project-theme-20261013/design-approval.json) |
| 2026-10-15—16 | 批准双入口切换与恢复、三套主题整改及主题管理整理；后续制作反馈直接修正。2026-10-16明确开发先交人工路径，意见修完并验收后才跑全量，关系未变无需重画图 |
| 2026-10-17 | 用户报告M1／S05-R2完成，要求S06闭合主题后试运行；此报告作为接续依据，前段人工及全量证据不据此补记 |
| 2026-10-18 | 独立审查并修复S06，之后授权一次本地commit保存工作；快照授权不代表产品验收或正式试运行批准。当前用户要求主题暂告一段落、全面吸收精简目录，作为暂停与整理依据 |

以上是确认范围摘要；原消息摘录和阶段上下文可从整理前Git提交的本文件第13—61节追溯。测试通过、Reviewer意见、原型操作和用户沉默不扩张确认范围。

## 已接入的能力与证据

下表是历史验证索引，本次整理只读核对，未重跑产品链路。当前精确代码与协议由源码拥有，历史回执只证明其版本和环境。

| 能力 | 实际结果与直接材料 | 证明范围 |
| --- | --- | --- |
| S01项目管理 | 项目入口、完整属性原子创建、图标与锁定slug、列表／卡片／搜索；历史HTTP／PG／MinIO及浏览器验证 | S01获用户验收；[页面回读](图解/11-s01-entry-20261011/product-browser/checks.json)、[持久化回读](图解/11-s01-entry-20261011/product-browser/persistence.json)；精确命令在整理前LOG15—16 |
| S02路线与S03运行时 | 同一受控协议承载不同组织；当前设计与技术取舍已进入[Feature](../develop-guides/yuanlei/features/project-themes.md)和Decision | 研究／合成原型与实际产品分开；原S03固定样例不是日常入口 |
| S04存储 | 受保护不可变ZIP、来源候选／版本、PG唯一Project绑定及联合备份恢复 | [存储回执](图解/17-s04-implementation-20261013/recovery-receipt.json)及[存储决策](../develop-guides/yuanlei/decisions/implemented/2026-10-13-project-theme-storage.md) |
| S05原业务与文件 | 实际业务分页、准确对象与冻结依据、JSON／PNG、原宿主办理与返回 | [HTTP／PG／文件回读](图解/18-s05-implementation-20261013/pg-http-file-receipt.json)、[浏览器回执](图解/18-s05-implementation-20261013/browser-receipt.json)；旧六页组织不作为当前全项目覆盖依据 |
| 全项目重整 | 九类能力及详情／编辑进入同一项目壳，旧URL解析到新能力，既有包／绑定与数据保留 | [整体实施证据摘要](图解/22-s05r-system-review-20261014/review.md)；设计落实与最终用户验收分别判断 |
| S04-R切换与恢复 | 平台完整管理分配、项目快捷选择、同源预检、统一宿主失效、草稿保护、故障恢复 | [切换证据](图解/26-s04-r-evidence-20261016/README.md)，实际HTTP／PG及隔离浏览器；未逐字段穷举 |
| 三套主题与M1 | 默认／精简／调研、ABI3有限呈现与隐藏导航、真实只读预览、制作模式及副本恢复 | [制作证据](图解/31-theme-authoring-m1-20261016/README.md)及[预览HTTP／PG](图解/29-theme-preview-parity-20261016/http-pg.json)／[DOM](图解/29-theme-preview-parity-20261016/browser.json)；用户2026-10-17报告完成，独立人工验收及全量不补记 |
| S05-R2消费 | 有限词汇进入真实办理，项目级JSON／PNG及准确混合预览，业务与文件映射身份保持 | [消费证据](图解/32-theme-consumption-r2-20261017/README.md)；代表场景通过，后续人工／全量未补记 |
| S06迁移与审查修复 | 原ZIP导出、只读预检、目标草稿、真实预览／发布／分配，连续导入与候选恢复修正 | [迁移与独立审查证据](图解/33-theme-migration-20261017/README.md)；正式部署边界见下节 |

已批准设计保留<a href="图解/21-full-project-theme-20261013/review.html" target="_blank" rel="noopener">完整原型</a>与确认回执。截图和原型用于表达或观察具体状态，产品结果以相同版本的持久数据、文件和协议回读判定。

## S06最新相关检查

审查起点`858f91d5`，产品首版`fabc09f0`。四类导入问题已修复：成功后连续导入按钮复位；新建／既有目标切换后按最终模式核实；核实与定位保持准确摘要／修订；既有候选已提交但回读失败时保留“已保存待核实”入口。提交后另窗口替换候选会返回`import_result_changed`，避免混用字节。

| 实际命令或材料 | 历史结果与观察 |
| --- | --- |
| `cd web && node --test test/unit/projectThemeDraft.test.js` | 最终13通过，包含先在旧实现失败的连续导入、最终模式及候选竞争负例 |
| `cd web && node --test --test-concurrency=1 test/unit/projectThemePreview.test.js test/unit/projectThemeSwitch.test.js test/unit/projectThemeSamples.test.js` | 18通过，原SSR告警保留；真实正文另有浏览器读取 |
| `docker compose exec -T api pytest test/unit/test_project_theme_packages.py test/unit/test_project_theme_contract.py -q -o cache_dir=/tmp/pytest-s06-review` | 48通过，覆盖ZIP展开、路径、资源、媒体与契约预算 |
| `docker compose exec -T api pytest test/integration/api/test_project_themes_api.py -k 'existing_import_committed or another_windows_candidate or import_rejections' -q -o cache_dir=/tmp/pytest-s06-review-final` | 最终3通过／28未选择；真实PG候选竞争与写后回读，Docker控制面故障后的同选择器重试 |
| 其他主题HTTP相关选择器 | 首轮6通过／23未选，恢复集合4通过／26未选；每轮范围与命令可追溯整理前LOG61，不相加宣称全部测试通过 |
| Web lint、build及工程契约 | 当轮通过，脚本unit71通过；文档构建通过。标准uv命令因容器lock写入权限未完成，HTTP使用已安装pytest；未放宽权限 |
| [导入恢复6项](图解/33-theme-migration-20261017/review-20261018/import-review.json) | 真实提交后丢响应、准确新增来源、候选revision及零发布／绑定不变，由DOM／HTTP／PG核实 |
| [重启后独立读取与切回](图解/33-theme-migration-20261017/review-20261018/restart-browser-review.json)及[原包再导出](图解/33-theme-migration-20261017/review-20261018/reexport-review.json) | B资料可读，显式切回推进generation，页面／HTTP／PG一致，A及B2保持；B再导出与A原ZIP逐字节一致 |

迁移主脚本曾因重复同名数据定位及重启等待超时而失败；后续准确来源定位、独立浏览器恢复和原包回读补验各段。主脚本保持失败记录，分段结果不改写为一次整链通过。原记录的已修复权限／超时噪声从当前页省略，相关限制已归入DEV与证据摘要。

## 待验与恢复入口

| 状态 | 恢复后需要的结果 |
| --- | --- |
| 正式部署证据未完成 | 现有A／B证据app省略正式startup，两库无`yuxi_schema_migrations`，`/ready`均503。使用正式migrator和应用入口证明schema及就绪，再核两环境迁移和重启 |
| 人工验收未完成 | 先交DEV中的正常入口、变动和可观察结果，修正具体反馈，记录明确验收与代码／主题版本 |
| 验收后全量未执行 | 按用户当轮执行者约定运行前后端相关全量，记录实际结果；保持CI及guard |
| 体验矩阵未完成 | S06新增弹窗与恢复态主要为1440浅色；暗色、窄屏、跨浏览器及完整错误组合尚未补验 |
| 生产及外部链路未验证 | 生产备份恢复、付费模型、组织协作和第三方平台不在本轮证据范围；协作／Andon继续暂停 |

上述内容作为暂停交接保留，当前不执行。正式A／B证据不能靠补写schema版本或放宽ready替代。恢复后按实际差额补验，普通体验改进依反馈安排；数据、授权、绑定和核心办理问题须明确闭合。

后续若获准进入试运行，固定已验收代码／主题版本，记录场景、问题与恢复动作。当前“阶段暂停”仅停止专项推进，不补记最终完成或试运行批准。
