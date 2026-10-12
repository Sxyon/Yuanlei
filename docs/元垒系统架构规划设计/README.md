# 元垒系统规划｜当前入口

读者：用户与专项执行者。版本：2026-10-12方案采纳及研究归档。此目录维护当前系统目标、专项设计、开发任务和事实进度。当前技术方案已采纳，后续执行读DEV-DB-002；S02调查基线只供归档追溯，启动任务必须核最新源码/HEAD。本轮文档与归档不声明产品已实现，不恢复协作专项。

## 1. 先看图，再逐项核对

从<a href="图解/10-stage-relations-20261011/stage-acceptance.html" target="_blank" rel="noopener">DB-G09｜S01—S07顺序推进与验收图</a>及[当前阶段审阅入口](DEV-MG-002-DB-D00设计审阅阅读计划.md)进入。按S01到S07依次实施验收；运行/保存/数据/迁移路线已采纳，具体工作包见DEV-DB-002。DB-G09保留顺序关系，图内当时状态由当前LOG覆盖。

<a href="图解/index.html" target="_blank" rel="noopener">打开图解导航</a>，或依次阅读下表。图均标明目标/候选/暂停范围；它们不是已上线能力截图。图文核对依据与校验状态在[整理记录](LOG-MG-002-目录重整与图文核对记录.md)。

| 图号 | 图解 | 用于判断什么 | 文档与状态 |
| --- | --- | --- | --- |
| PL-G01 | <a href="图解/01-platform/platform-target.html" target="_blank" rel="noopener">系统目标架构</a> | 项目、研讨、工作、上下文、准确结果和复盘如何连接 | SYS-PL-001；目标关系 |
| DB-G02 | <a href="图解/02-dashboard/dashboard-architecture.html" target="_blank" rel="noopener">旧Dashboard候选架构</a> | 保留旧机制取舍供比较 | 历史候选；当前不定案 |
| DB-G03 | <a href="图解/03-dashboard-tasks/dashboard-tasks.html" target="_blank" rel="noopener">旧Dashboard开发任务</a> | 追溯旧DB-D00/T01—13 | 已停止领取；历史用途 |
| CA-G04 | <a href="图解/04-collaboration/collaboration-target.html" target="_blank" rel="noopener">协作冻结目标架构</a> | 委派、准确交付、补充、问题和持久处理职责 | SYS-CA-001；全面暂停 |
| DB-G05 | <a href="图解/05-topic/topic-relations.html" target="_blank" rel="noopener">议题详情模块关系</a> | M1—M6在同页组织，如何进入准确办理并返回 | SYS-DB-002；仅示范，未确认 |
| CA-G06 | <a href="图解/06-andon/andon-return.html" target="_blank" rel="noopener">Andon逐级处理与返回</a> | 哪一级先判断、何时上报、答案怎样匹配回原尝试 | SYS-CA-001；暂停的未实现目标 |
| CA-G07 | <a href="图解/07-collaboration-tasks/collaboration-frozen-tasks.html" target="_blank" rel="noopener">协作冻结后继任务</a> | 重启前提、C1—C6及第二渠道的真实依赖 | DEV-CA-001、LOG-CA-001；当前不领取 |
| DB-G08 | 渐进推进流程候选 | 当前段调查、试验、阶段判断和中断 | 校验未通过，暂无交付图；文字规则见DEV |
| DB-G09 | <a href="图解/10-stage-relations-20261011/stage-acceptance.html" target="_blank" rel="noopener">S01—S07推进与验收关系</a> | 七段顺序、原要求1—12映射、验收出口与未通过重审 | 当前推进图；非完成状态或远期技术定案 |
| DB-G13 | <a href="图解/13-theme-execution-20261012/theme-execution.html" target="_blank" rel="noopener">项目主题已采纳执行结构</a> | 固定Vue/受控包、持久版本/选择、双数据与迁移工作分责 | SYS-DB-001／DEV-DB-002；技术已采纳、产品未实施 |
| DB-G10/11 | <a href="图解/11-s01-entry-20261011/project-entry.html" target="_blank" rel="noopener">S01 P1—P4原型与关系/保存序列</a> | 页面布局、点击关系、字段缺口与候选原子保存 | SYS-DB-001第8节；P1—P4本地产品已实施验收；LOG第15节 |

整体关系图之外，页面布局和模块理念见SYS-DB-002。数值图表属于项目大屏的数据表现，不由Archify代替实现。

## 2. 当前文档职责

| 类型 | 当前Owner | 维护范围 |
| --- | --- | --- |
| SYS 系统 | [SYS-PL-001](SYS-PL-001-系统架构与阶段边界.md) | 总体概念、第一/二/三阶段边界 |
| SYS 项目主题 | [SYS-DB-001](SYS-DB-001-Dashboard系统需求与架构设计.md) | 项目主题需求、入口、已采纳技术路线及产品支持边界 |
| DEV 实施指南 | [DEV-DB-002](DEV-DB-002-项目主题实施指南.md) | 已采纳契约、S03—S07工作包、接入Owner、拒绝案例与交接；不维护进度 |
| SYS 设计审阅 | [SYS-DB-002](SYS-DB-002-议题详情设计审阅示范.md) | 带编号草图、模块理念和关系图的候选示范；正式稿继续补齐 |
| DEV 项目主题 | [DEV-DB-001](DEV-DB-001-Dashboard开发任务与实施约束.md) | 阶段领取、顺序、范围与实施指南入口 |
| LOG Dashboard | [LOG-DB-001](LOG-DB-001-Dashboard进度基线与执行记录.md) | 唯一任务状态、实际证据、用户确认及反馈 |
| SYS 协作 | [SYS-CA-001](SYS-CA-001-协作接入与Andon系统设计.md) | 冻结目标；正式交付、逐级返回、有限授权、接入原则 |
| DEV 协作 | [DEV-CA-001](DEV-CA-001-协作接入与Andon冻结落地细节.md) | 已确定工程、限制和重启条件，无当前实施安排 |
| LOG 协作 | [LOG-CA-001](LOG-CA-001-协作接入与Andon暂停盘点与事实进展.md) | 已建/未验/未实现、原反馈及暂停残余 |
| DEV 管理 | [DEV-MG-001](DEV-MG-001-专项推进与设计汇报机制.md) | 领取、设计审阅、确认范围、双维度汇报与Reviewer |
| DEV 审阅指南 | [DEV-MG-002](DEV-MG-002-DB-D00设计审阅阅读计划.md) | DB-D00阅读顺序、审查重点与分项反馈方式；引用SYS设计和LOG事实 |
| LOG 整理 | [LOG-MG-002](LOG-MG-002-目录重整与图文核对记录.md) | 此轮归档、依赖修正、图稿/文档检查及限制 |

文件按类型-专项-三位编号命名。SYS不维护任务进度，DEV不把计划写成完成，LOG不偷偷改需求。新轮次更新这些Owner并保留事实记录，不再新建另一份主总纲。

## 3. 任务领取与当前边界

S01设计追溯入口为[SYS-DB-001第8节P1—P4 R1](SYS-DB-001-Dashboard系统需求与架构设计.md#_8-db-s01-项目入口设计审阅-r1)，提供完整全景、隔离原型及DB-G10/11；R2已确认icon／slug同步实施：上传复用智能体，标识保留大小写且全局不区分大小写唯一、设定后不可修改。P1—P4已整体确认，正式落地约束见SYS第8.8节。字段实施与真实回读见[SYS第8.7节](SYS-DB-001-Dashboard系统需求与架构设计.md#_8-7-已确认身份字段实施范围-r2)及LOG第13节；S01总体验收由LOG第16节原用户结论拥有。用户已明确采纳S02 R3，本轮形成[DEV-DB-002执行指南](DEV-DB-002-项目主题实施指南.md)并归档研究；S03产品开发未启动。后续领取先读SYS第9节、DEV-DB-001、指南对应工作包及LOG第20节；不默认读取/执行历史候选或重复审批技术方案。新页面布局仍按DEV-MG设计审阅，用户判断目标/关键边界，执行者承担常规技术实现。

协作与Andon全面暂停。保留代码、迁移、原证据与目标；仅整理文档不启动新Adapter、远端试验、计量运行或正式业务批准。C1工程不等于真实产品交付或完整Andon。

本目录通过根AGENTS进入专项任务，具体执行规则见DEV-MG-001。图稿变化同步更新对应SYS/DEV和LOG；真实代码图需冻结代码版本及源码证据，目标图明确说明计划性质。

## 4. 历史材料

[S02技术调研归档](归档/2026-10-12-DB-S02技术调研/README.md)保存原报告、102份资料/实验/回执/图与截图，清单含移动前/后的指纹。只供追溯；旧待确认、lab接口/表/身份、脚本路径、试验CSS/阈值和候选依赖不作为当前任务。当前执行与状态分别由DEV-DB-002和LOG拥有。

[渐进推进前快照](归档/2026-10-11-渐进推进前/README.md)保留旧SYS/DEV及阅读计划，旧T任务停止领取。DB-G02/03原生成字节保留，入口标历史，不再作为当前必然架构或进度路线。

[重整前归档](归档/2026-10-10-重整前/README.md)保留65份历史文档与证据文件，另有3份仅本地保留、不进入Git的系统目录元数据、原时点结论、图稿和样例。归档首行说明历史用途，原路径、归档路径和移动前指纹见映射。旧阶段编号可定位证据，不能成为当前完成度或任务入口。

暂停与新设计保留原已实现增量，未执行产品回滚、数据库清理或业务配置变更。

当前S01的P1—P4已确认，落地修订由SYS第8.8节拥有，原用户确认和本地开发纠正见LOG第14节。设计先归档为3a0ff83a，产品随后在当前本地主checkout完成实施与验收，见SYS第8.9节及LOG第15节；S01用户已验收76/100“基本能用，审美较差”，作为后续设计依据。S02技术路线已采纳并归档，隔离试验事实与用户实验验收分别记录；指南已形成，S03未启动，见LOG第20节。
