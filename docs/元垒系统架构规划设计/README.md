# 元垒系统规划

本目录面向产品负责人、设计与开发者，保存系统目标、专项设计、维护边界和接续所需事实。使用方法与字段查阅分别进入[项目主题使用指南](../intro/project-theme-authoring.md)和[配置参考](../advanced/project-theme-reference.md)；运行架构以[ARCHITECTURE.md](https://github.com/Sxyon/Yuanlei/blob/main/ARCHITECTURE.md)为准。

## 当前状态

2026-10-18，按用户“主题专项，暂时告一段路”的要求，主题专项阶段暂停。已有功能与数据保留，恢复须用户明确指令。暂停与最终验收分别登记：正式A／B启动迁移证据、人工验收和验收后全量仍待完成，详见[主题状态](LOG-DB-001-Dashboard进度基线与执行记录.md)。协作接入与Andon继续暂停。

## 阅读入口

| 要解决的问题 | 文档 |
| --- | --- |
| 元垒的对象、业务闭环与个人／组织阶段边界 | [系统架构与阶段边界](SYS-PL-001-系统架构与阶段边界.md) |
| 项目主题覆盖什么，哪些产品取舍需要保留 | [主题需求与设计](SYS-DB-001-Dashboard系统需求与架构设计.md) |
| 主题实现如何定位，怎样维护、恢复和补验 | [主题维护与接续](DEV-DB-002-项目主题实施指南.md) |
| 主题已做什么、确认到哪里、还缺哪些证据 | [主题状态与证据](LOG-DB-001-Dashboard进度基线与执行记录.md) |
| 协作与Andon的冻结目标、实现边界和恢复条件 | [冻结设计](SYS-CA-001-协作接入与Andon系统设计.md)／[接续约束](DEV-CA-001-协作接入与Andon冻结落地细节.md)／[暂停状态](LOG-CA-001-协作接入与Andon暂停盘点与事实进展.md) |
| 新专项如何设计、确认、交付与验收 | [推进机制](DEV-MG-001-专项推进与设计汇报机制.md) |
| 组件、生命周期与冻结目标的关系 | [图解](图解/README.md) |

SYS拥有需求与取舍，DEV拥有维护与实施约束，LOG拥有状态、确认依据、证据与未验范围。源码、Schema、Compose及测试拥有运行事实；[Feature](../develop-guides/yuanlei/features/README.md)解释业务差异及生命周期，[Decision](../develop-guides/yuanlei/decisions/README.md)解释非显然取舍。

## 材料保留与历史定位

当前页只维护接续需要的信息。已吸收的研究、逐轮纠偏、旧任务卡、重复截图及图稿修复副本从工作树移除；批准设计和代表直接证据保留在图解目录。历史精确内容以整理前提交`63dc5af7`为定位，可用`git show 63dc5af7:docs/元垒系统架构规划设计/<原路径>`读取。旧授权只解释当时范围，恢复工作仍以当前用户指令和暂停状态为准。

本轮整理的范围与取舍见[文档收敛决策](../develop-guides/yuanlei/decisions/implemented/2026-10-18-planning-document-consolidation.md)。整理不清理运行数据、主题包、绑定或外部资源。
