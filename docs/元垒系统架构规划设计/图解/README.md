# 系统关系与专项证据

本目录保留仍有阅读价值的关系图、批准设计和代表直接证据。当前状态见[主题LOG](../LOG-DB-001-Dashboard进度基线与执行记录.md)及[协作LOG](../LOG-CA-001-协作接入与Andon暂停盘点与事实进展.md)，历史图上的阶段用语按绘制日期解释。

## 关系与设计

| 图稿 | 用途与边界 |
| --- | --- |
| <a href="01-platform/platform-target.html" target="_blank" rel="noopener">系统目标架构</a> | 产品对象与反馈闭环；目标关系图，完整目标尚未全部交付 |
| <a href="34-theme-overview-20261018/project-theme.html" target="_blank" rel="noopener">项目主题当前架构</a> | 按63dc5af7源码核对完整项目宿主、可信业务能力、主题服务与数据／文件Owner；[候选](34-theme-overview-20261018/candidate.json)及[最终校验回执](34-theme-overview-20261018/verified/project-theme.finalize-summary.json)随图保存 |
| <a href="21-full-project-theme-20261013/review.html" target="_blank" rel="noopener">全项目主题批准原型</a> | DB-P07 R3页面组织及代表交互；[批准回执](21-full-project-theme-20261013/design-approval.json)固定准确字节，原型使用合成数据 |
| <a href="04-collaboration/collaboration-target.html" target="_blank" rel="noopener">协作冻结目标</a> | 准确委派与逐级处理的目标职责；Andon尚未实现 |
| <a href="06-andon/andon-return.html" target="_blank" rel="noopener">Andon逐级返回</a> | 问题、答复与等待attempt的设计时序；不作为实际恢复证明 |

## 直接证据

存储恢复及早期真实数据回执由主题LOG直接链接。后段证据按读者问题进入：[全项目实施](22-s05r-system-review-20261014/review.md)、[双入口切换](26-s04-r-evidence-20261016/README.md)、[制作管理](31-theme-authoring-m1-20261016/README.md)、[真实消费](32-theme-consumption-r2-20261017/README.md)、[跨实例迁移与审查](33-theme-migration-20261017/README.md)。三套内置样例的历史HTTP／PG、包摘要与浏览器回读在`28-theme-samples-evidence-20261016`中保存。

机器回执只证明其具体版本和环境；截图证明当时可见状态。后续检查输出使用独立目录，不覆盖历史成功或失败证据。失效原型、布局试稿、重复capture和修复回执已移出当前目录，精确过程由Git保留。
