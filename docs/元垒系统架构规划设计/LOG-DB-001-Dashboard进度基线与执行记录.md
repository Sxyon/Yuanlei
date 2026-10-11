# LOG-DB-001｜Dashboard 进度基线与执行记录

记录日期：2026-10-10。分支：`codex/dashboard`。提交：`3c5ee33c64f82fcb5214f29e7b7198730bdeed55`。本文唯一维护 Dashboard 任务状态与执行事实；需求见 SYS-DB-001，任务范围见 DEV-DB-001。

当前方向与状态见第10节：2026-10-11改为项目主题渐进推进。第1—9节保留此前时点证据和反馈，不继续按其旧DB-D00/T01—13领取。

顺序验收与最新图稿交付见第11节：S01至S07依次验收，S02前期只可准备资料。第10节事实保留，不能据其近端任务表推定阶段并行实施。

## 0. 目录集成时点与状态口径

本文第1节及原测试表是2026-10-10初次重整的时点证据。当前目录已集成，产品基线仍为3c5ee33c；工作树已有管理与文档改动，不能继续称当前工作树干净。此轮没有重跑产品HTTP/PG/worker或远端试验，新增图稿与文档检查单独记录。


## 1. 基线核对

本地已处于目标分支，工作树开始时干净，无需再次切换。最新 merge `3c5ee33c` 将协作 C1 合入 Dashboard；前一 Dashboard 提交为 `72b8d1d8ba015e0d71907449056520f261953a04`，协作提交为 `be41fced4745a6650031f4a2b3bf35f792f0be62`。本轮没有修改仓库产品代码，没有触发远端业务动作。

## 2. 已实现能力与证据范围

| 能力 | 源码/提交确认 | 证据范围与未验 |
| --- | --- | --- |
| 平台与项目稳定导航、管理/静态业务切换 | U5 代码保持，ProjectDashboardView 及布局仍在 | 旧作者有隔离链路回读；本轮未重新走完整真实页面 |
| 准确多结果办理 | U5 工作结果、意见、文件和返回保持 | 原条件/旧结果/409等原证据保留；不证明模板或动态链 |
| 蓝图默认阅读、显式编辑、历史次级 | 72b8d1d8，ProjectInspectionBoardView | 源码已实现；D1 作者报告 DOM/Workdir 主流程回读，剩余详见下一表 |
| 议题筛选列表/详情、当前决定和工作优先 | 同上及 project 子组件 | 源码已实现；旧维护动作扩展、真实身份及使用观察未全闭合 |
| 草稿隔离与恢复 | governanceDrafts/sessionStorage、user store、准确修订 | 本轮相关 unit 45项通过；真实账户/失权仍待页面验证 |
| 共享协作读契约 | collaboration.read/1 Schema、联合样例及原型映射 | 已有唯一 Schema；C1返回partial，生产问题链/宿主联验未完成 |
| 动态定义、Runtime、模板库、多实例 | D0及原型是设计依据 | 无相应完整产品实现，不能登记已交付 |
| 项目 Agent 动态生成和有限维护 | 旧工具仅静态 HTML read/write，运行范围守卫已在 | 新动态工具、验证/启用和自动政策待开发 |

D1原作者主连续任务包括蓝图、议题/批准决定、建议create/link、正式工作及PG/文件回读；本轮读取其记录并检查实现，没有重新产生该真实链路证据。原作者记录540前端全量、末尾相关集合、28 integration、2844后端unit等数量，仅属于原执行范围。

## 3. 关键源码事实与残余

### 蓝图并发保存

`project_blueprint_service.put_project_blueprint_view` 已支持可选 `expected_hash/expected_identity`，并调用 `Workdir.replace_file`，冲突返回409。普通 HTTP `ProjectBlueprintWrite` 只有content，router未传两个预期字段；前端 `putBlueprint` 也只发content。

因此当前普通编辑链没有使用已有条件替换。旧 D1 报告写“没有CAS”不够精确；新任务定位为接通现有 guard 与读取依据，覆盖共享目录/同名替换、冲突保稿，避免再造版本引擎。

### 页面与协作边界

D1改版已进入真实产品，不能沿用旧判断“工作台完全未适配”。但归档/重开等全部旧动作、旧评论deep link、大量记录、完整键盘路径、账户切换/失权等尚未全部用真实页面执行；人类连续使用观察未发生。

协作契约 Schema 的收敛不等于真实 Andon UI。Dashboard 当前消费缺失的问题链必须诚实表示未接入；协作暂停后，将其联合出口移入后继登记，不再阻塞本专项全部产品能力。

## 4. 本轮独立验证

| 检查 | 实际结果 | 证明范围 |
| --- | --- | --- |
| 分支、HEAD、提交差异、关键源码 | 已检查 | 当前合并内容和实现落点 |
| 工程契约检查 | 通过 | 193 decisions、21 yuanlei features等静态检查；此前4处旧措辞已由72b8d1d8修正 |
| 工程检查器unit | 70通过 | 检查器逻辑 |
| 前端5文件相关unit | 45通过，0失败，0跳过；约86.85s | 蓝图编辑、决定历史、建议准入、讨论、草稿规则 |
| 测试环境告警 | Vue Router测试挂载出现无active route record告警 | 未因此失败；实际页面路由/离开保护仍需真实走查 |
| 真实 HTTP/PG/浏览器/用户观察 | 本轮未重新执行 | 原D1作者记录保留，不能称本轮独立已验 |
| 全量前端/后端、lint/build/docs build | 本轮未重复 | 本轮仅新增outputs文档；按改动选择相关检查 |
| 新归档文档链接/编号/范围 | 7份Markdown、全部文件链接、代码围栏与13张任务卡台账映射检查通过 | 只证明文档结构与引用，不证明产品完成 |

前端命令：`docker compose exec -T web node --test --test-concurrency=1 test/unit/governanceDrafts.test.js test/unit/projectBlueprintEditing.test.js test/unit/decisionHistoryPanel.test.js test/unit/workSuggestionsPanel.test.js test/unit/topicFollowup.test.js`。

## 5. 历史任务台账｜2026-10-10口径，已停止领取

| 新任务 | 当前状态 | 已有增量 | 还需达到的出口 |
| --- | --- | --- | --- |
| DB-D00 设计审阅 | 审阅准备中；SYS-DB-002仅示范 | 已有分区草图、候选关系图及阅读计划 | 整体/模块、真实映射、关键状态和明确确认范围 |
| DB-T01 治理收尾 | 代码已实现待验（新增保存guard接线待执行） | D1阅读、筛选、层级、草稿 | 蓝图接线负控、旧动作/深链、真实身份、连续使用 |
| DB-T02 工作列表与概览 | 待执行 | U5准确结果与入口保留 | 列表注意事项、投影、过滤及概览统一 |
| DB-T03 收件箱 | 待执行 | 现有通知/对象入口 | 项目身份/需处理/交付/通知分层和返回 |
| DB-T04 Agent日常办理 | 待执行 | 既有队列/运行/配置 | 接收/异常/交付分层及准确路径 |
| DB-T05 定义与草稿 | 待执行 | D0规则/样例可吸收 | 持久模型、API和真实项目管理 |
| DB-T06 真实渲染取数 | 待执行 | 可信组件基础可复用 | 真实定义Runtime和源查询 |
| DB-T07 启用导航 | 待执行 | U5静态返回可参考 | 动态生命周期、首页、返回闭环 |
| DB-T08 业务数据 | 待执行 | 有界数据设计 | 候选/验证/采纳/经营一屏 |
| DB-T09 库与多实例 | 待执行 | 模板样例 | 实际库/派生/升级/提取/保护 |
| DB-T10 Agent生成（a页面/b数据） | 两子批待执行 | 静态工具及root范围守卫 | 真实动态工具/模型/worker链 |
| DB-T11 有限自动维护 | 待执行 | 政策设计 | 范围授权、真实自动生效及负控 |
| DB-T12 兼容与故障 | 待执行（可分项补证） | U5/D1局部证据 | 静态/身份/失权/资源/恢复完整残余 |
| DB-T13 连续使用收尾 | 待执行 | 历史合成任务 | 本人使用观察与完整独立专项出口 |

本表不计算百分比。旧D1已经实现的代码复用，未验部分继续收尾；其余待执行也可能已有零散基础，领取时先检查实际源。

## 6. 本次规划变更记录

| 调整 | 原因 | 影响 |
| --- | --- | --- |
| SYS/DEV/LOG分离、统一前缀编号 | 原主文混合设计/包/进度 | 旧主文保留历史，新进度仅此表 |
| 日常治理作为首包，复用D1 | 主流程真实使用仍未全闭合 | 不重做已完成界面，先补具体残余 |
| 动态首屏先用现有结果源 | 避免基础运行时等待业务数据和外部问题链 | 先交付观察，业务数据后续具名包 |
| 分析默认可选 | 普通经营图不必因缺AI分析无法启用 | 必需槽由模板具体定义，缺数规则保留 |
| 页面回退与数据修订独立 | 防止用户误解回退会撤销业务事实 | UI/说明/负控明确分开 |
| Andon联合验收转后继 | 用户明确全面暂停协作 | Dashboard可独立收尾；总体原目标仍未交付 |
| 蓝图guard接线 | 已有底层条件替换未用于普通编辑 | 最小接口/前端增量及真实文件负控 |

以上是规划调整，产品是否落地仍由后续执行记录证明。下一轮先按DB-D00交设计审阅包；本目录未定位DB-T01蓝图guard独立实施的原用户授权，暂保留读码与设计准备，不据此启动实现。

本节保留原时点安排，2026-10-11新的领取范围由第10节替代。

## 7. 后续执行记录模板

每包在本文件追加，状态表同步更新，不另造每轮主规划：

- 日期、任务号/子批、分支及开始/结束commit。
- 实际交付的使用结果、相关Owner、修改范围。
- 按需接口/模型确定细节及来源链接；影响SYS时写明修订。
- 实际命令、结果、数据/文件/DOM回读、截图和Review范围。
- 失败、未验、环境限制、用户反馈及下一次具体动作。
- 是否满足完整出口；尚缺什么；临时对象或配置残留及处理结果。

## 8. 依据入口

- [当前D1实施记录](<归档/2026-10-10-重整前/第一阶段专项/D1治理工作台分批实施与验收-2026-10-10.md>)
- [原D0设计与验收卡](<归档/2026-10-10-重整前/第一阶段专项/Dashboard-D0设计基线与D1-D6验收卡-2026-10-09.md>)
- [工作台实现](https://github.com/Sxyon/Yuanlei/blob/3c5ee33c64f82fcb5214f29e7b7198730bdeed55/web/src/views/ProjectInspectionBoardView.vue)
- [普通蓝图HTTP边界](https://github.com/Sxyon/Yuanlei/blob/3c5ee33c64f82fcb5214f29e7b7198730bdeed55/backend/server/routers/project_blueprint_router.py)
- [蓝图文件用例](https://github.com/Sxyon/Yuanlei/blob/3c5ee33c64f82fcb5214f29e7b7198730bdeed55/backend/package/yuxi/services/project_blueprint_service.py)
- [当前系统架构与阶段边界](SYS-PL-001-系统架构与阶段边界.md)

## 9. 2026-10-11｜DB-D00审阅准备

用户要求推进整体设计审阅并提供阅读计划。基于a40df11adc7a15d7004494d0928071ae2d8d3217文档集，新增[DEV-MG-002阅读指南](DEV-MG-002-DB-D00设计审阅阅读计划.md)，入口和站点导航同步引用。按整体/日常页面、动态大屏、开发覆盖三轮安排；每步列具体章节、重点、推荐/代价和判断出口。

本轮读取当前SYS/DEV/LOG及既有Archify图稿说明，未重新核产品源码或运行产品链路，未重绘图稿。完整外壳、其他日常页面、动态管理连续稿、Agent维护状态及真实映射仍需设计执行者补齐。现有议题稿继续为示范，阅读指南未新增用户设计确认，不将DB-D00登记完成，未开启T01—13实施，协作/Andon继续暂停。

检查：工程契约通过；检查器unit 71项通过；文档构建通过（最终22.59s）；指南12条文件、图稿及章节引用按实际构建标题ID核对通过；差异空白检查通过。独立Reviewer核对需求、全文及关联Owner，无实质问题。产品链路未运行，文档检查不证明设计已确认或产品已验收。

## 10. 2026-10-11｜项目主题与渐进推进重新定向

### 用户依据与范围

本会话用户明确指出整体预规划脱离真实实现，提出项目一级导航、列表/主题管理、多页面项目主题、技术货比三家、两主题前端样板、真实存储加载、两类数据、迁移及最后强化默认主题的方向。日常采用进度/问题/计划，选型采用现状/问题/方案/建议/请示。这是方向与推进机制依据，不把尚未产出的页面稿或技术选型登记为批准。

原依据：Codex会话01a10a44-9fa2-7bc1-861c-25f1e5dcf89a，2026-10-11用户消息，以“只按照建议计划阅读了开头一点点”开头。关键原文：“应该定好方向，渐进式发展，关键节点评审和细化后续发展”“由表及里，先从界面上调整”“以上目标达到后我再敲定细化页面的内容和方式”。DEV表中的用户编号对应该消息：1项目一级入口；2列表/主题二级入口；3搜索/新增/视图切换；4新建字段；5卡片/列表；6Vue加载/存储/双数据通信；7至少三家实际采用者；8默认/调研前端主题；9文件存储/加载/切换；10系统对象与项目文件协议；11导入导出；12最后强化默认主题。这些编号只用于定位原消息，不建立长期需求ID体系。

### 当前台账

| 阶段 | 状态 | 实际交付 / 下一出口 |
| --- | --- | --- |
| DB-D00 | 改为逐段评审；旧整体预批准停止 | 当前仅细化S01/S02，不登记完整主题方案已确认 |
| DB-S01 | R1设计稿已交审阅；产品未实施/未验收 | P1—P4原型、字段缺口及候选增量见第12节；等待具体范围确认 |
| DB-S02 | 初步现状阅读及外部入口定位；正式调研/试验待执行 | 三类真实案例、源码/示例、Vue接入试验、推荐与请示 |
| DB-S03 | 远端结果已记录，待S02证据细化 | 默认/调研两主题前端样板 |
| DB-S04 | 远端结果已记录，待前段细化 | 独立文件包、项目选择、安全加载、切换及恢复 |
| DB-S05 | 远端结果已记录，待前段细化 | 系统数据与项目指定文件两维度协议 |
| DB-S06 | 远端结果已记录，待前段细化 | 两环境导入导出与重新绑定 |
| DB-S07 | 远端结果已记录，待基架验证细化 | 默认主题日常信息架构与交互强化 |

### 现状证据与本轮调整

产品代码HEAD仍为a40df11adc7a15d7004494d0928071ae2d8d3217文档提交。本轮阅读AppLayout/mainList与router，未见项目管理一级页，已有项目准确路由保留。ProjectDashboardView业务页使用iframe srcdoc和空sandbox；dashboardFrame禁止脚本与网络。project_dashboard_service的现有入口是Workdir内/dashboard/index.html并对账修订/hash。以上是源码阅读，未执行真实页面/HTTP/文件试验。

ProjectCreate目前接request_id/name/workdir，ProjectUpdate接name；ProjectSettingsUpdate已有描述、类型、分类、标签和弱负责人等。新增表单的icon/slug需另沿模型与接口核实，不声称现有请求支持。现有Workdir创建不能在新增项目稿中隐去。

访问官方Grafana app插件、Appsmith Custom Widget与JupyterLab扩展/MIME资料，仅用于定位真实路线调查入口。没有完成相关源码核验、截图、部署或候选小试，技术未定案。受控定义/可信Vue由原推荐降为候选；文件目录、存储绑定及协议待真实试验选择。

重写当前SYS/DEV/阅读入口，前版三个文件按原字节保存至[快照](归档/2026-10-11-渐进推进前/README.md)并记录SHA256。原DB-G02/03为历史候选，DB-G05/议题稿作S07参考。新增DB-G08管理流程及阶段中断规则。本轮不改产品业务代码、不派发协作任务、不提交或重置工作树。

任务开始存在其他会话的storage_migration、对应unit及C1 Decision未提交修改，另有上一轮阅读指南暂存内容；本轮保持其修改与暂存状态，文档增量留工作树，不能将整棵工作树差异都算本轮交付。

### 检查与剩余

工程契约检查通过（196 decisions、356 docs）；检查器unit 71项通过；最终文档构建通过（17.24s）；当前六份Owner文档42条本地文件/图稿引用无缺失；3份原始快照SHA256一致；diff空白检查通过。独立Review指出原用户来源定位不足，补会话/消息/原文与编号映射后复核通过。初次归档的Markdown相对链接被构建拒绝，改为保留原字节的文本附件及明确入口，未扩展ignoreDeadLinks。

DB-G08四次finalize均在validate阶段失败：初次返回路由约束，后续桌面可读宽度，再两次28px连线边界。按技能两次集中修复及一次证据重试限额停止，候选与最终失败回执留08-progressive；暂无可交付HTML，未执行浏览器或目视检查。文字规划可用，图解仍是残余。正式技术调研、页面稿、产品代码及产品链路均未执行，本轮不登记其完成。

## 11. 2026-10-11｜S01—S07顺序验收图

### 用户依据与范围

同一会话01a10a44-9fa2-7bc1-861c-25f1e5dcf89a，用户本轮回复“1. 可以 2. 对 3. 对”，对应上一回复的前端先行、项目主题多页面/业务别名、多格式先调研三项原则。继而明确要求：“重新画任务推进图，我要按照我的推进顺序验收，图中同步展示S01-07对应关系”。记录为方向认可与顺序验收要求，不等同尚未生成页面稿或具体技术选型获批。

当前顺序为S01项目入口→S02技术选型→S03默认/调研前端样板→S04独立存储/加载/切换→S05两维度数据→S06导入导出→S07默认主题强化。分别对应原要求1—5、6—7、8、9、10、11、12。S01先交编号稿、在确认范围内落地并验收，随后正式进入S02；资料准备不代表阶段开工或验收。各阶段产品状态保持第10节所列未实现/待展开事实。

### 图稿与入口

<a href="图解/10-stage-relations-20261011/stage-acceptance.html" target="_blank" rel="noopener">DB-G09阶段任务与验收关系</a>采用Archify architecture模式，展示每段任务、验收点、绿色通过路径和红色未通过重审路径。原要求编号直接放入节点副标题，详细验收内容保存在探索卡片。图表达推进关系与阶段出口，未锁定远期技术；受影响前段重审仍按DEV执行。原生成文件未经手改。

09-stage-acceptance-20261011保存被拒绝的workflow试稿：端点约束、左至右mainPath限制、纵向viewport和折行路线交叉使其未通过完整门禁，不作为交付。10-stage-relations保存独立的阶段关系图及自身candidate、HTML、finalize/浏览器回执。旧G08失败残余留历史，不与新图校验身份混用。

目录README、图解入口、DEV任务、推进机制及当前审阅入口已统一顺序验收，不继续保留S01/S02并行实施表述。本轮只改图稿与对应管理文档，未改产品业务代码、未提交、未恢复协作/Andon；工作树已有暂存及其他会话改动保持不动。

### 检查与实际范围

Archify最终finalize的validate、deliver、check、browser-check全部通过，diagnostics为零。最终HTML SHA256为`b796f3755f2365e02fd6a414789dd0ed470bb0e5cee64ca81f7b208c8acbc6c9`；回执保存在图稿目录`review-3/`。针对这一HTML另做`visual-check-final/`四种尺寸/主题截图，自动浏览器检查通过；实际目视核对2048×1320浅色和1440×900深色首屏，原要求副标题可见、推进及返回线路无重叠。截图只覆盖当前视口，不宣称一张图目视覆盖完整长页面；七段语义、编号与路径另外对照candidate和全文复核。

工程契约检查通过（196 decisions、356 docs），检查器unit 71项通过，差异空白检查通过。独立Reviewer复核七段映射、顺序、未通过返回、用户批准边界、入口和本节记录，无剩余交付阻塞。上述只证明本次图稿与管理文档检查，不证明S01—S07产品实现或验收完成。

文档构建通过；仅保留构建工具既有的大包体积提示。最终补充记录后再次执行差异空白检查通过。

### 归档与提交范围

按用户本轮“归档，提交commit，我要新开会话执行”的要求，将当前项目主题渐进规划、三份旧方案原字节快照、S01—S07顺序验收图与工具证据一起保存到Git；新会话直接按DEV第3节领取S01，不另建任务描述文件。图解08/09保留失败身份，10内旧字节回执和截图仅供追溯，当前可交付HTML以review-3与visual-check-final指纹为准。

本次提交排除其他会话已暂存的storage_migration、对应unit和C1准确交付Decision，保留其暂存内容。提交不包含产品实现，不登记S01完成，不恢复协作专项。后端规定命令尝试后因容器无法写`/app/uv.lock`退出；改用`uv run --frozen --no-sync --group test pytest test/unit -m "not slow"`复用现有容器依赖验证，结果在执行结束后记录。

提交前最终检查：工程契约通过，检查器71项通过，文档构建通过（19.41s）。后端现有依赖环境复跑退出0，2859 passed、63 skipped、7 subtests passed、11 warnings（173.93s）；63项跳过不计作通过，未据其证明产品链路。容器锁文件写入失败和pytest缓存目录写入警告保留为环境限制。独立提交Reviewer核对完整授权文档范围、归档指纹与S01领取条件；归档索引多余空行已修正，授权范围HEAD差异及暂存空白检查通过。

## 12. 2026-10-11｜DB-S01入口设计审阅 R1

### 进度与确认依据

用户本轮明确要求推进“DB-S01：项目管理入口设计、实施与验收”，先读规范与当前SYS/DEV/LOG及DB-G09，调查真实代码后交P1—P4完整编号稿、隔离原型、模块理念与取舍，自行完成视觉/浏览器/窄屏检查；原文“首次交付停在设计审阅”“我确认具体范围后，再完成该范围内的产品实施”。本节记录为设计工作授权，R1尚待用户范围确认，原型操作与独立Review不算产品授权。S01产品未实施/未验收，S02未进入，协作接入与Andon继续暂停。

起点HEAD为`a8e567dc2e20b32ae47f6d376db1e65d91014eb9`，开始时`git status --short`为空；本轮不reset、stash或提交。实际新增仅设计HTML、Archify候选与回执、合成页面截图、提案和现有管理文档增量，产品web/backend源码未改。

R1由[SYS第8节](SYS-DB-001-Dashboard系统需求与架构设计.md#_8-db-s01-项目入口设计审阅-r1)拥有完整页面全景、模块解释与替代比较，DEV补确认后的步骤与出口。P1新增项目一级入口/二级tab；P2默认卡片及六列表格、有界列宽、搜索和空错；P3基本身份/Workdir/用途与折叠管理属性；P4公共/专属主题位置与准确返回。待判断四组页面范围及完整原子创建、可选slug与icon枚举增量。

### 技术调查与真实缺口

沿AppLayout/router→projects store/project_api→project_router→project_service/settings service→ProjectRepository/ProjectSettingsRepository与Project/ProjectSettings模型读取；参考AgentManageView、AgentManagePanel、PageHeader及ProjectSettingsModal。现有项目内概览/工作台/工作/智能体/资料路径可复用，尚无独立项目一级管理页面。WorkspacePathPicker已有目录选择与新建文件夹，ProjectSelectionSection已有历史目录路径，均可复用。

create schema声明mode默认managed，但手动创建用例仅接linked已有非根目录；不将schema默认误报为可用创建模式。列表已有类型/分类/标签摘要，描述、work_status、负责人和icon/slug缺列表输出；完整settings可读写已有属性，名称重命名与软删除已有，编辑Workdir换绑不支持。模型无Project icon/slug，Agent.slug不可当项目字段。提出在yuanlei域补身份展示属性与唯一约束、扩当前创建用例同事务存属性、列表批量摘要的最小候选；尚未实施或运行数据库迁移。

### 检查、问题与下一步

隔离原型采用手工HTML与现有样式token，所有对象为合成，仅内存变更，无产品HTTP请求；真实产品确认后仍复用Vue/Ant Design Vue。Chrome/Playwright浏览器检查读取DOM和请求，覆盖创建/编辑表单校验、搜索、空错、48项数据、列宽、准确项目返回、浅深色及390px窄屏；最终结果与HTML指纹见`图解/11-s01-entry-20261011/browser/checks.json`。截图见同目录，目视结果与最终检查在本节补记。

DB-G10入口关系使用Archify architecture，最终回执为`nav-final/`；初次误用sequence专属return枚举被schema拒绝，改用合法dashed。第一次同目录交付碰到另图目录锁而浏览器检查失败，改为串行后完整finalize通过。DB-G11保存与回读使用sequence，第一稿桌面文字缩放失败、第二稿纵向画布过高、第三稿legend余量不足；收紧布局后最终`save-final-3/`完整finalize通过。旧失败回执保留工具证据，只有最终指纹与回执属于交付。两图均为设计提案，不作为现有产品链路证据。

尚缺用户确认、真实字段实施与PG/HTTP回读及产品验收；本轮不能宣布S01完成。下一轮按明确P号/字段反馈修改稿或实施已批准范围，独立Review后逐项登记S01验收，再正式进入S02。

最终设计检查：`verify-prototype.cjs`通过33项DOM/浏览器断言，零页面脚本错误、零产品API请求；其中新增日期编辑回填、平台主题入口不沿用最近项目、图解索引合法main内三入口。复跑方式为先在原型目录运行本地HTTP服务4317，再用已配置Playwright的Node运行该脚本；依赖来自已有本地运行环境，未安装新依赖。HTML SHA256为`11a80610b8c98493909c8af853e28fbf928d06664f4b596db1aa6e270f74bf1c`，精确值以checks.json直接计算结果为准，截图全部为合成数据。目视检查最终浅色卡片/表格/P3/P4、深色卡片及390px列表/P3/P4；窄屏审阅条改为普通底部区域避免遮挡，平台菜单可打开，表单内部滚动可到达目录与管理属性。Archify两图各四尺寸/主题自动捕获通过，并实际目视1440×900浅色入口关系和保存序列，节点、关系标签与返回线无重叠；截图回执仍保留visualReview=pending，目视结论由本LOG记录，不改工具回执。

独立Reviewer不继承开发上下文，读取原需求、规范、完整diff、源码与图稿，提出图解索引HTML、编辑日期丢失、平台主题上下文污染三项阻塞；修复后复核通过，无剩余实质阻塞。SYS已明确未保存提醒、真实读取/提交错误、智能体负责人及失效关联仅为待实施产品目标，原型未演示。设计Review通过只代表可交用户审阅，未取得用户产品范围确认。

工程契约检查通过（197 decisions、357 docs）；检查器unit 71项通过；文档build通过（19.61s），保留工具既有大包提示；四份管理Owner的52条相对文件/图稿引用无缺失；diff空白检查通过。初次工程契约因证据结果列混写说明被拒绝，已改为规定结果词并通过。未运行后端unit、真实HTTP/PG或产品E2E：本轮只交设计，没有产品代码变更、迁移或commit，不用文档与原型检查替代产品验收。最终补记后的文档build通过（17.59s），diff空白检查通过。


## 13. 2026-10-11｜S01身份字段授权与隔离实施

用户明确要求“icon／slug 后端同步开发实现”“icon要和智能体一样支持项目图标上传”“slug要支持大写字母，最少1位，唯一标识后端需校验全局唯一性”“slug设定后不允许修改”。针对大小写唯一范围，用户答复“不区分大小写：保留输入大小写，A 与 a 冲突（推荐）”。这只授予身份字段实施，不扩大为P1—P4全部获批；协作/Andon暂停、S02未进入。

代码位于附加的s01-project-identity隔离工作树，基线仍为a8e567d；主工作区的R1设计及其他会话改动保留，日常Compose数据库不升级。ProjectSettings增加icon／slug，yuanlei schema37→38；全局lower(slug)唯一索引、格式约束和不可变触发器；真实创建同事务绑定身份属性，幂等重试检查新增字段。上传复用现有user接口与MinIO公共图像机制，不添加主题框架或修改议题/决定状态机。

首次相关测试55项中53通过，2项因新增icon／slug响应而失败，明确更新预期后重跑并补并发、跨账号、软删除、DB替代写入、迁移及真实对象回读。前端直接调用本地eslint通过，build通过（5.30秒，既有大包提示）；pnpm exec因共享node_modules隔离安全检查拒绝，未删除主工作区依赖，改用同版本CLI直接调用。后续证据在本节追加；当前不宣布字段或S01整体验收通过。


### 13.1 最终证据与本轮出口

已确认icon／slug字段已在隔离工作树完成创建、编辑、列表摘要、真实持久化回读和上传等待处理。S01完整入口、完整属性创建及主题占位页面尚待范围确认，不能以字段出口代替S01总体验收；S02未进入。代码未提交、未部署，日常Compose数据库维持版本37，隔离测试执行版本38迁移。主工作区已有暂存设计资料保持原暂存状态；本轮只核对原指纹后同步R2原型HTML，其余代码和R2文档保留在附加工作树。

实际执行：

- 容器yuanlei-api:0.7.3加载隔离package／server／test／docker源码，复用开发服务网络；`python -m pytest test/unit -m "not slow" -q -p no:cacheprovider --tb=short`：2874通过、63跳过、10条工具既有warning，302.41秒。初轮16失败：15为旧迁移夹具缺v38方法，1为容器技能投影路径权限；补31—37迁移链和失败不记版本测试，为测试容器提供临时可写skill-projections后全量通过。不改日常路径或迁移生产数据。
- `python -m pytest test/unit/services/test_project_service.py test/unit/services/test_project_settings_service.py test/integration/api/test_project_settings_api.py -q -p no:cacheprovider`：72通过（63.43秒）。补旧客户端省略身份字段的回归后单独重跑`python -m pytest test/integration/api/test_project_settings_api.py -q -p no:cacheprovider`：17通过（82.81秒）。真实PostgreSQL并发只产生一个项目；跨账号A/a冲突、软删除占用、数据库UPDATE改值／改大小写／清空均拒绝；旧行迁移保留、重复迁移、同request_id重试和列表回读通过；真实MinIO字节回读通过，伪图片拒绝。
- web内`node --test test/unit/projectIdentityFields.test.js test/unit/projectSettingsForm.test.js test/unit/projectSettingsApi.test.js`：11通过。直接eslint检查受影响源码和测试通过；Vite build通过（5.30秒）。测试同时验证新建上传等待期间不提交、结束后提交icon／slug并选择服务端ID，设置上传等待锁、迟到响应、失败与格式／5MB拒绝。临时移除保存锁后负向测试在接口调用数1≠0失败，恢复源码后通过。
- `python3 scripts/verify_engineering_contracts.py`通过；`python3 -m unittest scripts.test_verify_engineering_contracts`71通过；docs内`node node_modules/vitepress/bin/vitepress.js build`通过（26.37秒，最终补记后再验）；22处DB管理文档相对文件引用无缺失，`git diff --check`通过。Ruff相关service／router／测试通过，manager保留已有E501不做无关格式化。

浏览器使用真实ProjectSettingsModal和Ant Design Vue，通过隔离测试身份调用原路由；图标上传时保存禁用、完成后提示仍需保存，保存后刷新显示真实图片且loaded=true；BrowserA原大小写保留并readonly。窄屏实测innerWidth／scrollWidth均354，身份字段单列，无横向溢出；截图及观察在[身份字段浏览器证据](图解/11-s01-entry-20261011/identity-browser/checks.json)。R2原型支持上传本地预览与单字符A、编辑锁定；仅内存演示，R1旧33项回执继续标历史，不套用新指纹。

独立Reviewer不继承开发上下文，核对授权范围、完整diff和规范；修复了原负向测试不能检出缺陷的问题，独立重跑相关测试并核对mutation失败，最终无新增功能阻塞。Reviewer报告不替代以上运行结果。临时QA页面、测试图片对象、独立数据库schema已清理；用户原浏览器设计tab保留，协作接入与Andon继续暂停。


### 13.2 错误展示收尾与最终回归

最后检查发现字符串HTTP detail会被既有通用API层泛化，改用现有业务`code/message`契约表达slug格式、全局冲突和不可修改；创建提示读取message，避免把对象传给toast。增加create API请求字段与冲突文案透传断言，独立Reviewer核对这次修正并重跑11项前端测试通过。首次补断言误加到既有蓝图冲突测试，已撤回该错误断言并限定在项目身份冲突用例；最终相关后端72项全部通过（42.25秒），前端11项通过，lint通过，build通过（8.95秒，既有大包提示）。全量unit2874通过发生在此错误展示调整之前，最终相关回归证明本次契约修正；不将此前全量执行误记为最终新契约下重跑。

最终原型HTML SHA-256以[verification.json](图解/11-s01-entry-20261011/identity-browser/verification.json)为准；设计tab回到初始全景，R2上传按钮本地PNG预览实际loaded=true。身份字段实施与检查出口通过，S01总体验收仍未通过，P1—P4其余范围继续审阅。

最终补记后的文档build通过（19.44秒）；24处DB管理文档相对文件引用无缺失，diff空白检查通过。临时运行凭据文件已删除。

## 14. P1—P4确认与本地开发纠正（2026-10-11）

用户原反馈：“p1-p4基本没有问题”，“排版和计划我都认可，无需为了使落地和原型一直而投入”，“项目的workdir的选定和操作方式要沿用现有的组件和方式”；要求“P1-P4吸收我的意见之后提交一次commit，保证开发前所有内容git归档记录就可以继续了”。对应R1完整布局与R2身份字段规则。确认全部P1—P4，并明确二级导航复用智能体页面、正式产品去掉原型说明区、平台现有风格和组件优先。完整创建属性及批量列表摘要按原推荐范围实施。

用户同时明确：“我要求工作推进在我的本地工作空间，不要用worktree”。前轮icon／slug代码与验证确实只在隔离工作树完成，尚未提交，也未迁入本地主checkout；前轮报告没有充分说明这个落点。保留第13节作为隔离验证历史，停止工作树开发，在当前本地分支归档设计后迁入代码并复核。此前字段测试通过不能宣称当前本地产品已交付。

当前阶段：设计确认、归档与本地实施准备；S01整体未验收，S02不进入，协作接入与Andon保持暂停。本轮不需要新的范围确认。归档检查及commit随后记录实际结果。

设计归档检查：工程契约197 decisions／21 features／357 docs通过，checker单元71项通过；`cd docs && pnpm run build`通过（35.59s），42条相关相对链接存在，`git diff --check`通过。全新Reviewer对确认依据、设计约束和隔离证据边界审查通过。受引用identity-browser证据纳入归档，构建产物排除。规定`docker compose exec api uv run --group test pytest test/unit -m "not slow"`因容器`/app/uv.lock`写权限失败；用`--no-sync`复用现有依赖的全量单元正在运行，结果后续登记，不作为设计产品通过依据。此提交只归档文档与原型，产品代码未纳入。

## 15. S01本地完整实施与验收（2026-10-11）

进度：设计及批准记录先提交为`3a0ff83a`（docs(dashboard): 归档 S01 项目入口设计及确认范围）。随后将字段代码逐文件核对迁入当前本地`codex/dashboard`，全部产品开发和日常Compose验证均在此checkout；不继续使用工作树。正式页面采用平台PageHeader、Ant Design Vue、既有样式与WorkspacePathPicker，移除原型说明区，完整实现批准P1—P4。

技术：`project_service`拥有原子完整创建及有效意图幂等，`project_settings_service`拥有验证与设置，repository批量读取摘要及弱负责人名称。icon／slug只增至yuanlei.project_settings，版本37→38，business7／knowledge2保持。数据库lower(slug)唯一索引、格式CHECK与不可变trigger覆盖并发、替代写入和软删除占用。UUID路由、原Workdir边界、权限及管理状态语义保持；新建失败保留草稿和目录。共用新建组件覆盖新旧两个入口；编辑沿用已有设置组件，Workdir／账号只读。

实际执行与证据：

- `docker compose run --rm --no-deps storage-migrator`在本地执行成功；另进程PG回读business7／knowledge2／yuanlei38。规定`uv run --group test`因`/app/uv.lock`权限拒绝；改用现有容器已安装依赖`uv run --no-sync --group test pytest test/unit -m "not slow" -q -p no:cacheprovider --tb=short`最终完整unit：2874通过、63跳过、10条既有warning，380.90s。先前设计归档时运行的2859项仅记基线，不冒充最终代码。
- `docker compose exec -T api uv run --no-sync --group test pytest test/integration/api/test_project_settings_api.py -q -p no:cacheprovider --tb=short`：23通过，131.55s。真实PG／HTTP覆盖完整属性回读、字段失败无Project残留、全字段意图重试及省略非默认值拒绝、默认空属性等价重试、失效负责人、跨账号／并发大小写冲突、软删除占用、直接DB不可改／清空、迁移重入、MinIO字节与非法图片、根目录／穿越／文件／符号链接／缺失目录。前轮相关111项（88 unit＋23 integration）也通过，但最终23项含幂等补强后重跑。
- `docker compose exec -T web pnpm run test:unit`：546项首次544通过、2失败，721.33s。失败分别是旧API精确expected未含已批准icon／slug null、旧Workdir guard仍在抽取前组件找Picker；显式更新expected及证明旧入口消费共用组件后检查真实Picker，相关`node --test --test-concurrency=1 test/unit/api_boundary.test.js test/unit/workspace_action_semantics.test.js`21项通过，46.70s。没有宣称修訂后全量一次全绿。其余相关12项通过（20.40s）；最终标签逐实例id修正后，identity／settings两文件10项再次通过（17.64s）。
- `docker compose exec -T web pnpm run lint:check`通过；最终`pnpm run build`通过（15.82s），既有大包提示保留。相关Python Ruff使用`--no-cache`避开既有缓存目录权限，通过。工程契约197 decisions／21 features／357 docs／40 routers通过，checker单元71通过；最终文档build与相对链接检查、diff空白结果随本节收尾登记。

真实浏览器在原生日常前端，通过正常认证的本轮合成账户创建长标题项目，上传PNG，slug单字符大写Q，选既有Workdir组件创建的s01-entry目录，设置阶段交付／产品／验收标签／暂停／本人责任归属；随后编辑描述。独立进程读PG及正常HTTP GET验证字段，读取MinIO对象逐字节匹配。导航、错误恢复及实际宽度见[结构化检查](图解/11-s01-entry-20261011/product-browser/checks.json)、[持久化回读](图解/11-s01-entry-20261011/product-browser/persistence.json)。暂时阻断GET用于错误检查，未改产品API；深色与viewport随后恢复。日期反转等通过集成验证，本次浏览器未操作日期保存，不冒充视觉动作。

| S01出口 | 结果与直接证据 |
| --- | --- |
| P1 一级／二级入口及准确返回 | Passed；原生DOM及真实UUID导航，cards-final／themes截图 |
| P2 搜索／新增／卡片列表／列宽／长标题／空加载错 | Passed；DOM、列宽320→321及重置、empty／list／first-load-error／refresh-error截图 |
| P3 全字段真实创建编辑／icon／slug／Workdir归属 | Passed；23集成、PG／HTTP／对象回读，create／narrow-edit截图 |
| P4 主题管理位置、来源状态与返回 | Passed；公共与专属未接入明确、动作禁用，themes截图 |
| 视觉、窄屏及独立Review | Passed；浅深色、实际341px无页面横溢；全新Reviewer先发现有效默认意图缺口，修复并补双向负例后通过，测试oracle更新经独立核对 |

问题：无阻塞性剩余项。原有仓库大包及第三方warning保留，容器lock／cache权限导致标准依赖同步命令不可用，已如实记录替代命令；既有worker不健康不是本阶段执行入口依赖，未扩大修改。主题运行时仍明确未接入，属于后续阶段范围。真实合成账号、项目、settings、部门、其Workdir及2个上传对象已按自身命名范围删除并回读验证，用户数据未改；[清理回执](图解/11-s01-entry-20261011/product-browser/cleanup.json)。临时凭据不进入Git。

计划：S01验收通过；S02具备进入前提但本轮未开始，随后按DEV第4节调查与小试，不沿旧T任务领取。协作接入与Andon继续暂停。产品提交记录以本节所在commit为准。

最终收尾：docs build通过（18.73s），53条相关相对文件引用无缺失，`git diff --check`通过。迁移夹具既有7处E501不做无关重排；Ruff最终检查repository／两service／router／HTTP测试与两个service unit文件通过。Decision迁implemented后补齐规范要求的“决策／后果／验证”标题；工程gate再次核对。全新Reviewer最终核对useId标签修正及完整diff，无实质剩余问题；两次测试预期调整保留拒绝后果。临时验收凭据清理完成。
