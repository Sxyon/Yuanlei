# DEV-DB-002｜项目主题实施指南

版本：1.2，2026-10-12。读者：后续开发者、设计者和独立Reviewer。类型：已采纳方案的实施参考。需求与架构由[SYS-DB-001](SYS-DB-001-Dashboard系统需求与架构设计.md)拥有，阶段领取由[DEV-DB-001](DEV-DB-001-Dashboard开发任务与实施约束.md)拥有，用户确认及实际完成状态由[LOG最新记录](LOG-DB-001-Dashboard进度基线与执行记录.md)拥有。本指南拥有工作包、契约落点与验证步骤，不维护第二套进度台账。

## 1. 使用方法与确认范围

用户于2026-10-12明确“采纳方案”，采纳对象为S02 R3完整技术路线及其支持边界；同一消息授权编写后续执行指南并归档调研。指南编写轮只交文档与归档。当前S03任务与确认范围见SYS第10节和LOG最新节。技术采纳、试验自测通过、用户实验阶段验收和产品实现分别记录；该消息没有另行表述实验阶段验收结果，不据此新增“全部产品能力已通过”结论。

每次领取：先读目录README、SYS-DB-001第9节、DEV-DB-001与本指南对应阶段；用git log/status及符号搜索核实最新实现，记录真实HEAD/工作树；按前段产品出口和用户当轮任务范围开工。2026-10-12编写本指南时HEAD为592b6e510bc5049c9dbe24c75199c7b9dae10fb9，S02历史试验HEAD为d2bf7134，不可拿任一固定旧提交判断未来当前实现。已采纳技术路线不重复审批；具体页面整体/模块设计按DEV-MG-001审阅。

| 阶段 | 本段产出 | 本段输入 | 本段完成后交给下一段 |
| --- | --- | --- | --- |
| S03 | 两主题六页、契约模型、固定组件、模拟数据适配与返回 | 已采纳Vue/受控包路线、已有平台UI/业务入口 | 正式组件词汇、包样例、逻辑数据/文件需求、页面与错误验例 |
| S04 | 候选/版本/发布、真实文件域、PG绑定、维护界面 | S03正式契约及包样例 | 持久版本/选择、窄资源绑定校验、可用加载DTO与故障恢复证据 |
| S05 | 原业务数据、Project授权的指定文件、真实宿主办理 | S04版本/绑定，当前原业务API/Workdir | 真实授权/分页/内容/返回证据与迁移需求清单 |
| S06 | 导出/导入预览、目标重绑定、两元垒环境验证 | S04原字节包，S05真实数据/文件协议 | 格式/ABI兼容与迁移证据、明确未携带内容 |
| S07 | 默认主题日常治理体验强化 | 已运行基架与当前真实使用反馈 | 信息层级/连续办理体验及残余，不新增业务状态机 |

研究代码、lab表、合成HTTP身份、研究限额和实验CSS只属于[归档](归档/2026-10-12-DB-S02技术调研/README.md)。后续工作不复制实验宿主为产品，不引入FormKit/TinyEngine/amis作为主运行时，不复活旧T01—13或重做已验收S01；协作接入与Andon继续暂停。

## 2. 固定技术边界与改动落点

<a href="图解/13-theme-execution-20261012/theme-execution.html" target="_blank" rel="noopener">DB-G13｜已采纳执行结构</a>表示目标分工，S03独立合成预览已形成；生产存储与真实业务接线尚未交付。M1外壳与M5原业务能力已有实现；M2/M3/M4/M6/M7的主题适配和M8项目资源入口按下表逐段补齐。

| 模块 | 复用Owner及职责 | 计划新增及落段 |
| --- | --- | --- |
| M1 外壳/返回 | web/src/router/index.js、ProjectDashboardView.vue拥有当前项目与路由；PageHeader、平台明暗样式拥有外观 | S03先用独立预览入口承载ThemeHost，S04/S05接现有项目概览；内部page ID不注册任意新平台路由；保留可信项目入口 |
| M2 契约/校验 | 当前Pydantic/FastAPI依赖；现有静态HTML服务策略 | S03新增纯模型yuxi.services.project_theme_contract；S04 API复用同模型，生成JSON Schema给维护工具 |
| M3 页面组件 | Vue/Ant Design Vue、DefaultProjectDashboard、MarkdownPreview与dashboardFrame等 | S03新增web/src/components/project/themes/下的ThemeHost、有限注册表及必要业务包装；主题包不提供SFC/JS |
| M4 数据适配 | governance_board_api、project_work_api与现有项目API | S03提供明确标模拟的适配器；S05同输入契约换真实调用，每种逻辑binding映射固定API |
| M5 办理 | ProjectInspectionBoardView、ProjectWorkTaskView及原governance/project_work服务 | S03模拟准确入口；S05进入真实对象及原写API，主题不重写权限/状态/审计 |
| M6 包/维护 | 现有文件访问原语及服务用例分层 | S04新增project_theme_service、受保护文件存储模块、project_theme_repository；API用project_theme_router薄适配 |
| M7 Project选择 | ProjectRepository的可见性查询/行锁、PostgreSQL yuanlei域及storage_migration | S04新增来源/版本/Project绑定实体和正式migrator增量；未来版本号以当时真实Owner为准 |
| M8 指定文件 | Workdir.open_existing/read_file及Workspace全路径no-follow | S04校验绑定；S05新增Project主题资源读取用例与薄路由，复用Workdir，不创建thread |

表中新增名称是实施位置建议，不表示文件已经存在。开始修改前用rg定位当前符号：ProjectRepository.get_active_selectable_for_user／lock_active_selectable_for_user、治理查询、正式工作查询、Workdir.read_file与resolve_project_run_scope。HTTP入口在backend/server/routers，服务在backend/package/yuxi/services，SQL查询在repositories，不能把用例写进路由。

公共内置包随平台只读发布；个人公共库属于当前维护者；项目专属来源只可在该Project选择，若需复用先经有权维护者显式复制/提升为个人公共来源并记录来源。受保护theme-sources服务文件域不挂Agent、不放进Project可写Workdir。平台当前个人/Project权限复用，组织协作授权不在本轮范围。

## 3. S03先形成、S04—S06沿用的契约

### 3.1 包与定义

首批ZIP固定含manifest.json、theme.json及manifest声明的assets。formatVersion与componentAbi均从1起；生产格式字段采用formatVersion，研究脚本的format字段不作为兼容输入。纯Pydantic模型是权威，未知字段/组件/表达式/资源明确拒绝；前端只接受平台校验的DTO和可信注册名。没有产品消费者需要时不增加兼容旧实验字段的分支。

manifest只声明逻辑文件与包内资源；source是作者声明，认证来源引用由加载DTO另行提供。下例为真实契约可接受的单页说明样例，完整六页以packages内两份样例为准。

```json
{
  "formatVersion": 1,
  "componentAbi": 1,
  "theme": "theme.json",
  "files": {},
  "assets": {},
  "source": "作者声明，不能作为授权依据"
}
```

```json
{
  "id": "example",
  "version": "1.0.0",
  "name": "课题阅读样例",
  "topicLabel": "课题",
  "pages": [
    {
      "id": "context",
      "title": "课题脉络",
      "description": "从同一议题对象阅读问题",
      "layout": "reading",
      "blocks": [
        {
          "id": "topics",
          "type": "records",
          "title": "课题目录",
          "region": "aside",
          "variant": "selector",
          "binding": {
            "kind": "business",
            "resource": "topics",
            "scope": "project"
          }
        },
        {
          "id": "question",
          "type": "topic",
          "title": "研究问题",
          "region": "main",
          "binding": {
            "kind": "business",
            "resource": "selectedTopic"
          }
        }
      ]
    }
  ]
}
```

纯契约Owner是 `backend/package/yuxi/services/project_theme_contract.py`，`export_project_theme_schemas.py` 输出同源Schema，前端 `contract.schemas.json` 直接消费。定义用有限组件type、页layout、block region与受控variant；records区分topics／decisions／workTasks，summary只接project，topic／discussion只接当前选择。文件引用用 `{kind: file或asset, alias}`；PNG必须有alt，资源声明包含相对成员、MIME与SHA-256。HTML／Markdown文件块在出现当前consumer时按可信组件发布扩充，S03不为凑六类能力实现它们。

开发保护阈值可以先沿S02有界输入做验证，但不能把2MiB/12成员/8页/12块写成已经测得的产品容量。S04用六页正式包及边界样本测默认阈值，将压缩大小、展开总量、成员量、单文件/页/块限制集中在真实parser契约Owner；每个阈值有正确原因负例。常规配额测定不重开技术路线，也不建设没有consumer的后台配置机制。

### 3.2 数据、事件与返回

宿主适配输入只含逻辑binding、当前Project、当前选择对象及原API分页参数。主题不提供用户ID、请求URL、SQL、凭据或业务批准状态。系统数据保持原DTO语义，组件包装负责可读字段/状态标签；资源响应提供MIME、size、SHA-256及明确错误。loading由前端请求生命周期表示；empty/unbound/missing/denied/error必须可区分，不能将失败清洗为空列表。

事件只接受page选择、已注册对象类型/引用与显式可信办理动作。返回上下文保存Project、包digest、page ID、选择/滚动；对象详情再次通过原后端Project归属查询。缓存与迟到响应以用户/Project/digest/generation/查询上下文隔离，切项目或版本清空旧DTO；权限失效不显示旧项目内容。

原生Vue注册表以静态导入或平台自己声明的懒加载SFC解析组件；无上传包dynamic import/运行时编译/eval。JSON资料使用独立资料视图而非当主题定义。PNG走授权fetch/Blob并回收URL；Markdown关闭原始HTML、内联图片/活动链接并净化；HTML经静态服务策略和空sandbox/CSP，只作自包含报告。首批不含自由JS、SVG/Office/视频/外站或任意ECharts option；可信新组件仍可沿原平台发布扩充。

### 3.3 当前消费者与S04—S06接续接口

主题编排Owner为 `web/src/components/project/themes/`：同一ThemeHost、静态注册表、两份独立manifest／theme及实际ZIP样例位于packages。宿主按定义渲染，业务组件不识别默认／调研ID；第三份独立定义和独立适配器在组件测试中使用同一宿主。样例ZIP的成员、展开定义与资源指纹由verify_project_theme_packages检查，ZIP生产parser由S04补齐；这个受信任样例检查器不接受外部上传。

| 当前可信组件 | 实际输入与表现 | 真实Owner接续 |
| --- | --- | --- |
| summary | Project摘要＋明确counts；counts／description表现 | 原Project摘要与有界治理／正式工作聚合；不能用当前分页长度伪造总量 |
| records | topics／decisions／workTasks；项目或选定议题范围；列表、表格、主从选择、紧凑选择、结论、待办、历史 | 原DTO集合与关联对象仍分别校验；查询按页面＋块隔离，不改变原类型／状态 |
| topic | selectedTopic原DTO的问题、预期产出和进展 | 原议题查询；“课题／战略规划”只改显示名 |
| discussion | 当前topic_id讨论与经核对的标题上下文 | 原评论读取，不直接复用带写操作的讨论整块 |
| json | 声明的application/json资料字节；通用数值／文字摘要及原文 | 指定文件或包内资源；示例JSON中文key不是生产字段规范 |
| image | 声明的PNG字节、metadata及alt | Blob URL按内容更换／离开回收，浏览器解码失败明确恢复 |

加载接口为 `loader.load({selectionId, signal})`，返回 `{manifest, theme, reference, digest}`。selectionId是来源目录中的不透明宿主引用；reference来自已授权加载器，独立于作者theme.id。digest来自原ZIP字节，不能授予来源权限。S04将样例目录／静态加载换为真实有权版本目录／服务加载，并补同一纯契约的ZIP边界校验。可携包只含manifest／theme／声明assets，reference、用户、Project、绑定generation与指定文件映射均留在宿主；S06迁移原包后由目标生成引用并重新绑定，不需改六页定义。

业务接口为 `adapter.read(binding, context, signal)`；准确详情为 `adapter.readObject({kind: object, objectType, id}, context, signal)`。context由宿主冻结userId／projectId／packageRef／digest／bindingGeneration／pageId／selectedTopicId及查询参数。bindingGeneration接真实绑定版本，内部request generation仅用于迟到隔离，不作为后端授权或并发写入凭据。业务ready响应含原DTO value，可附独立related对象集合；empty必须是实际空集合。unbound／missing／denied／error保留原因，loading由前端请求生命周期表达。分页仍按原API的offset／limit参数接续；S03查询控制保存在原页，不将样例条数或限额写成产品容量。

资源ready响应含Uint8Array bytes与metadata `{mediaType, size, sha256}`，json内容另作资料解析。包内asset还与manifest SHA对照；主题不给URL或路径。合成适配只认当前提供的逻辑文件，未提供的声明alias明确unbound，不能据样例survey／distribution名称约束S04绑定。S05用有权Project＋绑定alias＋Workdir读取替换指定文件分支，用来源／版本授权替换包内资源读取。

详情再校验原对象ID／Project及原DTO类型。任务来源快照投影保留decision_id／revision_number／conclusion和原snapshot扩展字段，与任务source_decision_id／source_decision_revision匹配；真实接续可以使用现有任务source.decision.snapshot或准确决策版本用例，不能从当前决定正文重建历史。返回上下文由宿主保存并重读原页，再恢复选择、查询、滚动和焦点；取消或改上下文使旧DTO与旧错误同时失效。S05原办理路由接收相同对象事件，并在原宿主补可信来源返回；本轮只读详情不是新业务写入口。

这些是当前有消费者的替换边界。S04—S06在同一协议上确认和完善真实存储、授权、恢复与迁移，普通接线不推翻本轮宿主、组件与页面定义；出现新自由执行、权限或兼容范围时仍按管理规则提出有证据的调整。

## 4. S03：两主题六页前端样板

进入条件由DEV-DB-001/LOG拥有；当前六页设计与重点模块由SYS第10节R1拥有。开工后先以独立预览入口承载同一ThemeHost，使用合成Project/业务/文件DTO；不在日常Project路由塞假业务数据，不写真实主题绑定。预览使用现有AppLayout/PageHeader/平台明暗样式，后续S04/S05替换加载与数据适配，不重写页面组织。

| 页面 | 默认读到什么 | 关键交互与离开路径 |
| --- | --- | --- |
| 默认／Dashboard | Project摘要、当前议题、批准决定、正式任务；模拟标识明确 | 点击准确对象进入合成宿主详情并返回当前页 |
| 默认／工作台 | 选定议题讨论、关联正式任务及决定 | 切换选定对象不串讨论；资料缺失可解释，不模拟完成写动作 |
| 默认／议题列表 | 按原语义展示议题状态和决定/任务关联 | 选择议题、查看讨论/关联对象；“战略规划”仅显示名测试 |
| 调研／课题脉络 | 同一topics对象、问题／预期产出、讨论脉络及证据入口 | 横向/阅读式组织；选择及对象身份与默认主题一致 |
| 调研／证据资料 | 声明的JSON＋PNG，按必要性加入Markdown/静态HTML | 来源/类型/错误与资料呈现；返回宿主再回本页 |
| 调研／研究结论 | 同一decisions与workTasks，区分讨论文字/正式结论 | 准确决定/任务入口，不从文案推出批准或任务成功 |

执行顺序：

1. 交六页整体及重点模块稿，写清导航、信息优先级、对象入口/返回、浅深色与空错。按S01“76/100，审美较差”改进密度/对齐/标题层级，保留平台语言；已采纳技术不再货比三家。
2. 实现纯Pydantic契约与两个完整包样例，生成工具消费的JSON Schema；提交显式审阅的合法/非法fixture。未知组件、错binding形状、重复页、任意URL/脚本字段为负例；前端固定注册表及包装props与模型对齐，不引入通用表达式/设计器。
3. 实现ThemeHost、局部page选择、有限布局/内容组件、合成数据适配、可信对象导航/返回；每次异步请求冻结Project/digest/generation上下文，旧响应不能修改新页；数据模拟标识与已接服务的真实状态分开。
4. 完成六页交互及状态验证：1440px/390px、浅/深色、键盘focus/顺序、长标题、空列表、加载失败、缺文件/未绑定、未知组件、迟到响应；切主题后同对象身份准确，返回保留页/选择。截图支持设计判断，DOM断言证明交互。
5. 跑相关frontend lint/unit/build、纯契约unit及真实浏览器；全新Reviewer核对六页设计依据、数据模拟、完整diff和后段契约。将实际产出/残余写LOG后交阶段验收，不自报美学通过。

出口：两套六页定义及可信组件已在预览可用；contract/ABI和数据/文件alias有真实consumer；非法定义明确失败；无业务假写入；模拟适配可由S05替换且页面不改数据类型。交接给S04的是正式包样例、组件清单、逻辑需求、状态/返回验例，不是研究App.vue或lab协议。

## 5. S04：持久保存、维护与项目选择

先完成可问责的后端链路，再接维护界面；不能只让localStorage记住选择。以下实体与接口是实施规格，当前尚不存在；具体命名可随真实Owner结构调整，语义及提交顺序保持。

### 5.1 数据与文件工作包

| 语义实体 | 必须保存及约束 |
| --- | --- |
| ThemeSource | 服务生成source ID、归属域builtin/personal/project、owner uid、可选Project、来源说明、停用/撤回状态。请求者不能伪造builtin或别的owner |
| ThemeVersion | source ID、业务版本、包digest/size、format/ABI、校验信息、真实创建者；unique(source,version)，不同字节同版本409，已发布内容不可改；同hash不是权限 |
| ProjectThemeBinding | Project主键、已授权版本FK、指定文件alias映射、generation；两个Project共用Workdir仍各自独立，更新用Project锁及expectedGeneration防覆盖 |

先补元垒Feature/已采纳提案关联，再在yuanlei域实现实体与真实migrator升版；版本号从当时YUANLEI_SCHEMA_VERSION读取，不复制研究版本或lab表。测试旧版→新版、重复迁移、约束拒绝和升级后原Project数据保留；不回写上游business/knowledge域。

配置独立theme-sources服务卷，目录由服务按认证owner/source/project生成。候选位于受保护来源域，发布blob按digest只读；API实例共享PG与该卷，Agent沙盒/Project Workdir没有卷访问。内置包只读，个人公共与项目专属来源分别鉴权；候选可编辑，发布版本不可覆盖。不要复制研究临时绝对路径、Docker名字或UID。

发布用例按完整校验→临时完整写/fsync→同卷原子无覆盖发布→PG登记版本执行；并发同hash复用前重算字节，DB失败留下未引用完整blob且不改变旧绑定。选择用例先授权来源/Project、核版本和必需文件绑定，再锁Project并检查expectedGeneration，提交新选择。删除/停用来源不能默默破坏已绑定版本；安全撤回明确拒绝加载。清理孤儿必须重查PG引用，不以文件年龄直接删已使用包；本段提供可执行对账/清理入口，不建无consumer的后台任务系统。

### 5.2 窄接口与界面接线

| 用例 | 请求边界与实现职责 |
| --- | --- |
| 来源目录/版本读取 | get_required_user＋来源域权限；只返回可用/可解释版本与元数据，不公开宿主路径 |
| 候选读取/编辑/验证/发布 | owner或授权Project；编辑按候选revision/指纹防覆盖；服务校验错误定位到字段，失败不登记可用版本、不激活 |
| Project主题选择/读取 | ProjectRepository鉴权；选择仅version ID、files逻辑映射和expectedGeneration，uid/可信状态来自服务；加载返回校验后definition/资源元数据/当前generation |
| 文件绑定校验 | 需要完整声明alias集合；每条映射只在该Project Workdir验证普通文件/类型/大小/no-follow；这是S05资源GET的共同Owner，避免存入不可信路径 |

实现位置按第2节新增薄router/service/repository/存储模块，API挂现有server装配；frontend project_theme_api连接同一ThemeHost加载契约。S01占位主题管理页在本段接来源、候选、预览、版本、停用与Project选择；保留平台来源返回项目列表、项目来源返回准确Project。未知/缺包/损坏不能悄悄写回“内置主题已选择”；显示故障并保留可信入口，必要内置阅读页注明临时退路且不改原绑定。

本段验证：真实HTTP＋独立PG查询/卷字节回读；两用户来源拒绝、项目专属不可直接跨项目选择、公共文件不可写、同版本冲突、两次旧generation覆盖拒绝、两Project同Workdir选择不串、编辑不升级原绑定、缺包/篡改/断点失败/重启、文件映射路径及类型拒绝。对压缩包量分别制造raw超限和raw未超但展开超限，不能只看共同413。

出口：候选/版本/Project选择真正持久化，管理UI读真实服务；原子发布及故障恢复/备份回读有证据。S05复用版本读取、alias映射及绑定校验，不再发明文件身份或存储模型。备份需一致保留PG引用与被引用ZIP，恢复后逐个校验digest及绑定；只备份数据库不是合格恢复。

## 6. S05：接通系统数据与指定文件

先将正式页面从S03模拟适配切换为真实调用，独立预览继续明确标模拟，再证明真实数据；使用独立测试环境与合成账号/业务记录验证实际认证边界，不借日常账号或碰日常项目。只读呈现先闭合，必要办理交给现有可信宿主，不通过主题建立通用写代理。

| 逻辑输入 | 真实Owner与接入规则 | 最低证明 |
| --- | --- | --- |
| project | project_service、project_settings及ProjectRepository | 当前Project摘要与独立PG回读一致，非当前用户不可见 |
| topics / decisions | governance_service／repository；governance_board_api | 列表/详情属于当前Project，状态来自原对象；别名不换ID |
| discussions | 已选topic的评论/时间线用例 | 切换topic重新读上下文及游标，不能伪造全局讨论集合或串topic |
| workTasks | project_work_service／ProjectWorkRepository；project_work_api | 正式工作任务与工作建议明确区分，结果/验收不从报告文字猜 |
| 指定文件alias | S04映射＋当前Project授权＋Workdir.read_file | 实际字节/MIME/size/hash与独立文件读相同，绑定路径不返回浏览器 |
| 包内asset alias | 已授权来源/版本及校验后的ZIP成员 | 按声明读字节，猜中hash或alias不能跨来源/Project读取 |

执行顺序：

1. 为每个实际页面binding建立固定宿主适配，保留现有API分页、错误及对象类型；核对当前代码拥有哪些查询，新增有界聚合只放对应业务service，避免N＋1/全量扫描。组件仍只收展示DTO，不接SQL或任意URL。
2. 提供Project资源GET：认证→Project可见性→当前绑定/generation→alias→Workdir普通文件读取/类型/限额→MIME、size、hash或原因。拒绝自由path/query补充路径，不使用thread Viewer创造Conversation。每次请求授权，不能靠第一次预览或hash缓存代替。
3. 将JSON/PNG/Markdown/静态HTML组件接真实授权响应。返回no-store/private及适当nosniff；图片Blob释放，Markdown/HTML遵守第3节内容边界；文件变更以新hash/刷新呈现，缺文件与权限错误显式显示。
4. 将对象入口接现有ProjectInspectionBoardComp的topic_id/decision_id和正式任务路由，讨论保留topic上下文；原业务用例重新查Project归属，返回上下文不接受任意URL。若权限失效清空旧内容并回可信项目入口；不展示旧缓存为可用事实。
5. 在隔离真实HTTP/PG/浏览器中创建合成Project、议题/讨论/决定/正式任务，跨两个主题读取、分页、进入准确详情和返回；修改指定文件后重新读取并对账hash；延迟旧请求、切Project/版本、取消/失权后检查没有串数据。

拒绝集至少包括另一用户/Project对象、错topic讨论、工作建议冒充正式任务、未声明alias、路径穿越/符号链接任意组件、错MIME/超限/缺文件、旧generation、未知组件/事件及任意返回URL。业务操作按原权限与状态限制验证，不增加批准/撤销等“演示成功”接口。

出口：六页所需逻辑需求均有真实路径或明确非首批范围；模拟标识只留在独立预览，正式页不混入fixture；原Owner的授权/状态仍最终执行。交给S06的是实际format/ABI、资源与逻辑需求、两类数据权限/错误/返回验例，不输出身份/凭据打包方案。

## 7. S06：原字节导出、导入预览与目标重绑定

使用两套正式元垒的隔离环境，独立PG/主题卷/用户与Project/Workdir；同一checkout可按隔离Compose命名运行，不用worktree、不复用日常持久数据。仅启两个研究API或共享正式登录账户不满足本段出口。

执行顺序：

1. 授权当前来源/版本后导出原ZIP字节，hash与S04发布记录一致；清单只有manifest/theme/声明资源。禁止自动加入Project业务行、文件映射、generation、启用状态、认证字段或扫描Workdir；原字节不会自动脱敏用户自行放入的文案/资源，导出预览说明可携内容。
2. 目标导入走同一parser/ABI/资源/限额校验，登记目标本地来源和版本、记录目标认证导入者及原声明，初态待绑定。重复导入同字节可复用有权版本；同source/version异字节明确冲突，禁止覆盖已发布包。导入不调用项目选择或业务写接口。
3. 在目标界面选择有权Project，逐个alias选该Project指定文件，核类型/边界/大小；先预览缺文件/缺组件/不兼容原因，再显式激活。源UUID/用户/path即使同字符串也不是目标授权；业务对象使用目标当前Project/选择上下文，不自动重建原业务记录。
4. 在A导出、B导入，以不同用户/Project/目录/文件内容验证：包字节仍相同，B页读到B的对象和文件，PG保存B映射，进入/返回B准确详情；B重启后同选择恢复。A绑定与内容不因B导入改变。
5. 做负例：format/ABI不兼容、坏hash/成员/资源、缺组件/文件、源路径、目标无权Project、重复版本冲突、导入中断/激活失败。失败不改变已有目标选择；没有silent fallback、自动装未知组件或搬运凭据。

出口报告按可携/不携/须重绑/不支持列出实际包内容和DOM/PG/文件结果。只有兼容format/ABI的元垒环境直接支持；任意第三方平台、业务数据库迁移和跨版本自动转换属于明确的新需求，不为了完成导入增加通用兼容层。

## 8. Agent维护与S07默认主题强化

Agent真实生成与有限自主维护是后继工作指引，尚未自动纳入S03—S06验收或本轮开发授权。S06出口评审时明确其作为基架收尾还是独立后继工作包；领取前列出工具范围、目标测试Project、独立验收及用户范围确认。下列约束供该工作包直接使用，不据此提前增加工具或执行LLM试验。S07页面强化仍按既有阶段顺序单独领取。

Agent维护以S04来源/候选和S05真实上下文为基础；先提供受限读取/提交/验证工具，再观察模型生成效果。复用project_run_scope及dashboard_tools的运行上下文模式，工具目标Project由服务从当前run解析，输入只含候选定义/资源和expected revision，不接受uid、宿主路径、其他Project或可信来源标志。服务认证/Project授权与包parser仍最终执行；schema omission/prompt不能替代权限。

生成链路固定为候选→结构/资源验证→明确隔离预览→有权维护者发布新版本→用户选择；自动激活、写公共源及自由执行脚本均不在首批。工具错误返回文件/字段/原因及是否产生候选，非法生成不登记可用版本、不跳过坏块。给模型的Schema来自真实Pydantic Owner，样例取S03正式包，不使用归档lab字段。验证至少包含合成正确包、错组件/数据形状/未声明资源/脚本/版本、被拒项目及错误revision；真实LLM试验只写明确测试Project候选，核文件/DB最终结果，不能把模型回复“成功”当事实。

S07先收集默认主题连续使用的具体问题：找项目/议题是否困难、讨论依据是否看得懂、决定与任务是否混淆、进入办理/返回是否丢位置、长列表是否挤压信息。按高频任务重排摘要/列表/详情/资料入口，复用已经真实接通的注册组件及原业务状态；只在实际缺口处补可信组件，不新建议题/决定状态机或解除协作/Andon暂停。

开始S07先交完整默认主题与模块稿，标明原业务状态、历史依据、空错及路径；每轮落实一个可观察任务链并对照用户反馈。两主题继续共用基架，不把默认主题深化改成另一套运行时；用户评价审美与可理解性，工程验证准确对象、状态和返回。需要增加新的业务操作或自由内容执行时明示范围变化，不用“优化体验”暗中扩权。

## 9. 验证、交接与范围控制

每一工作包在真实Owner处闭合：纯模型/映射用unit，持久化/授权用真实HTTP＋PG/文件，用户交互用真实DOM，故障/重启/导入回读最终状态。新guard有能恢复缺陷并在正确原因失败的负例；合法/非法fixture显式审阅，不由CI同时生成oracle再验证。截图、HTTP 200、模型报告或unit绿灯都不能替代对应高层事实。

按[测试规范](../develop-guides/testing-guidelines.md)运行最小相关集合，再按改动风险扩大。以下命令为现有统一入口；具体主题测试文件在相应阶段创建后加入选择器，本轮没有执行产品主题测试。

```bash
python3 scripts/verify_engineering_contracts.py
python3 -m unittest scripts.test_verify_engineering_contracts
docker compose exec api uv run --group test pytest test/unit -m "not slow"
docker compose exec web pnpm run lint:check
docker compose exec web pnpm run test:unit
docker compose exec web pnpm run build
# 持久化/权限/文件改动按范围运行对应integration，交互再运行实际浏览器。
# 文档变更在docs目录运行npm/pnpm run build，并检查相对链接。
git diff --check
```

阶段交接保存：真实HEAD/完整diff；已实现Owner和实际命令结果；PG/文件/hash/DOM回执；模拟/未接/Not run范围；用户设计/阶段验收原消息及版本；残余缺陷、影响和恢复条件。全新不继承开发上下文的Reviewer审完整需求、确认范围、diff和证据；通过不替用户验收。每轮日常按进度/问题/计划汇报，不用测试数量替代业务结果。

既定路线内的普通页面缺陷、可信组件扩充和实现bug按原Owner修复。下列事项需要明示新的范围/代价：自由JS、任意第三方平台运行、组织协作权限、跨主机不共享存储、无限容量或全自动兼容转换。受影响路径应停在产生副作用前，说明新需求/缺陷、修复方案和恢复条件；已有独立授权且不依赖该问题的工作继续。不能用调低验例/改LOG完成口径逃避失败，也不把本轮已论证机制重新作为后段待选。

备选只在新范围确需时重审：平台维护的SFC主题主要改页面组织/渲染并增加构建/源码Review，原数据/绑定/保存机制可保留；amis或可执行HTML需要新renderer/样式或消息隔离协议和实际接入证据，尚未选用。归档中的库接通/失败不构成当前待办，不依据它们新增依赖。
