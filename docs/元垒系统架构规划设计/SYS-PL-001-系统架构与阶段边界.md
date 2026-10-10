# SYS-PL-001｜系统架构与阶段边界

版本：1.0，2026-10-10。读者：用户、设计和开发执行者。职责：个人优先的产品架构、概念边界和三阶段范围。技术运行不变量由[ARCHITECTURE](https://github.com/Sxyon/Yuanlei/blob/3c5ee33c64f82fcb5214f29e7b7198730bdeed55/ARCHITECTURE.md)拥有；专项需求、任务和进度通过[目录入口](README.md)查找。本文是设计依据，完成事实由源码与LOG维护。

## 1. 产品目标与入口

元垒在项目内连接方向维护、研讨、选择、工作、交付、验收与复盘。项目承载长期经营或阶段交付，分类/标签承担领域区分。个人用户先维护完整业务闭环，负责人只标明责任，不自动授予权限。平台负责跨项目出口、聊天、收件箱；项目负责自身管理和业务观察。

<a href="图解/01-platform/platform-target.html" target="_blank" rel="noopener">PL-G01系统目标架构图</a>展示对象与反馈关系。箭头标明可选来源、上下文、执行和验收；图中的业务模块不是一组必须新增的服务。项目内允许直接创建人工工作，议题和决定不是所有工作的准入门禁。

## 2. 核心对象与职责

| 对象 | 维护什么 | 不能混淆的边界 |
| --- | --- | --- |
| 项目 | 所属业务空间、分类标签、目录与管理状态 | 分类/负责人不授予权限；共享目录可能共享文件字节 |
| 蓝图 | 方向、目标、约束和复盘 | Markdown是正文事实；目标完成与任务完成分别判断 |
| 议题 | 问题、方案、讨论、证据及当前选择入口 | 单页组织讨论和决定，后端保留独立身份与版本 |
| 决定 | 明确批准的选择、依据、补充/替代/撤销 | 草案不冒充批准；勘误不覆盖原批准事实；可有多条有效决定 |
| 正式工作 | 一次业务范围、要求、责任标识与验收 | 可无议题、无决定、无Agent；来源关联是可选关系 |
| Context Pack | 本次工作的要求、资料、依据及来源指纹 | 输入快照不授予读取权限；引用/hash不承诺旧字节可重放 |
| 执行尝试 | 一次分配、接受、派发、运行与失败 | 同工作可多尝试；人工提交不虚构AgentRun |
| 结果与验收 | 准确交付、文件、意见和业务接受 | Run终态、结果接受、工作完成、目标达成是不同事实 |
| Dashboard | 观察、导航与项目页面管理 | 页面不复制正式业务状态，写操作进入可信办理页 |
| 协作/Andon | 委派来源、补充、问题、逐级答复与恢复义务 | 工程已有基础；完整目标尚未实现，当前暂停 |

议题的纳入资格、研讨进度和结果确认各自表达事实。归档是退出日常关注，不替代拒绝、关闭或达成；删除遵守受保护引用约束。具体状态和约束以[议题机制](../develop-guides/yuanlei/features/project-governance.md)及当前模型为准，页面重排不新增状态机。

## 3. 业务图和数据事实

PostgreSQL拥有业务身份、关联、状态、修订与结果；Workdir/对象服务拥有文件字节。关系图从关联生成，不另存可编辑的业务状态。现有Neo4j知识图谱承担知识关系，不替代业务治理数据。

治理、工作、结果、上下文及协作attempt沿各自service/repository保存。复盘可更新蓝图、重议议题或形成新决定，不能反写旧输入或已接受结果。Context Pack在执行前冻结；同次派发重试沿原输入，新尝试按明确操作重新组装。

项目Dashboard以受控定义、可信Vue素材、项目实例与不可变修订演进；定义/模板和真实数据绑定分开。具体规则由[SYS-DB-001](SYS-DB-001-Dashboard系统需求与架构设计.md)拥有。外部接入、逐级返回和有限正式授权由[SYS-CA-001](SYS-CA-001-协作接入与Andon系统设计.md)拥有，暂停范围由其LOG维护。

## 4. 源码基线与未完成设计

基线：codex/dashboard，3c5ee33c64f82fcb5214f29e7b7198730bdeed55。管理与文档工作树改动单独记录，不冒充已提交产品增量。

| 事实 | 直接源码 | 当前结论 |
| --- | --- | --- |
| 项目分类/标签与弱负责人 | [业务模型](https://github.com/Sxyon/Yuanlei/blob/3c5ee33c64f82fcb5214f29e7b7198730bdeed55/backend/package/yuxi/storage/postgres/models_business.py)的ProjectSettings | 已有字段，旧ed4d598基线的缺口判断不沿用 |
| 议题/决定历史与工作结果 | 同文件GovernanceTopic/Decision、ProjectWorkTask/Result | 已有独立对象与修订；UI融合保留语义 |
| 业务上下文 | [上下文组装](https://github.com/Sxyon/Yuanlei/blob/3c5ee33c64f82fcb5214f29e7b7198730bdeed55/backend/package/yuxi/services/project_work_context_service.py)、[执行尝试](https://github.com/Sxyon/Yuanlei/blob/3c5ee33c64f82fcb5214f29e7b7198730bdeed55/backend/package/yuxi/services/project_work_execution_service.py) | 已有选择、指纹、预算、尝试快照；不是全量可重放承诺 |
| 蓝图并发保存 | [HTTP入口](https://github.com/Sxyon/Yuanlei/blob/3c5ee33c64f82fcb5214f29e7b7198730bdeed55/backend/server/routers/project_blueprint_router.py)、[文件用例](https://github.com/Sxyon/Yuanlei/blob/3c5ee33c64f82fcb5214f29e7b7198730bdeed55/backend/package/yuxi/services/project_blueprint_service.py) | 底层有guard，普通HTTP尚未接预期hash/identity |
| 项目页面 | [治理工作台](https://github.com/Sxyon/Yuanlei/blob/3c5ee33c64f82fcb5214f29e7b7198730bdeed55/web/src/views/ProjectInspectionBoardView.vue)、[Dashboard](https://github.com/Sxyon/Yuanlei/blob/3c5ee33c64f82fcb5214f29e7b7198730bdeed55/web/src/views/ProjectDashboardView.vue) | 已有D1/U5，动态实例/模板/维护闭环尚待建设 |
| 协作交付 | [当前机制](../mechanisms/collaborator-delivery.md)及CA的DEV/LOG | OpenClaw准确文本工程已在；真实产品链/Andon不据此视为完成 |

此表来自源码阅读，不代替真实HTTP/PG/worker或用户观察。专项LOG保留原作者证据与独立验证范围。

## 5. 三阶段边界

| 阶段 | 目标 | 范围与进入条件 |
| --- | --- | --- |
| 第一阶段 | 个人日常闭环 | 项目、蓝图、持续议题、批准决定、正式工作、准确结果、Context Pack；Dashboard重整按DEV实施；协作原目标保留但暂停，因此不宣告总体第一阶段全部完成 |
| 第二阶段 | 持续业务按周期收敛 | 闭环稳定、真实周期困难可复现后，拆工作定义/周期实例，明确时区、唯一周期键、补跑、重试和暂停；再按需求提取目标、Proposal和多对多关系 |
| 第三阶段 | 中小公司多人协作 | 真实成员、组织归属、共享权限、角色和审计；原负责人标识不自动变成员资格或权限 |

Work Definition统一一次性/周期/自动化/监控是目标概念。第一阶段现有任务承担一次性业务实例，保留定时Agent/规则巡检各自含义；第二阶段才建设可重复定义与周期实例，避免把永久in_progress当周期归档。

用户明确授权Agent批准部分正式决定变更属于个人有限授权，不等于组织治理。该目标保留在暂停协作专项，重启后机械核范围与同事务消费；本次文档整理不授予业务批准或远端试验权限。

## 6. 设计审阅与验收

Codex负责完整设计、图稿、推荐、实现与自测；用户判断关键设计和架构取舍。新设计按[推进机制](DEV-MG-001-专项推进与设计汇报机制.md)交编号整体/模块稿与Archify关系图，明确确认版本和范围。旧证据保留，图稿校验不等于实现验收。

验收至少包括人工工作直达、治理到工作、Agent准确交付、旧依据复核、重试上下文、跨项目同名对象、失权/并发及复盘。Dashboard可独立收尾；暂停的Andon仍是总体未完成项，不能用局部专项完成替代原系统目标。
