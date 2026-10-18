# 原包迁移与独立审查证据

历史范围：2026-10-17首版及2026-10-18定向审查。当前主题阶段暂停；正式A／B启动迁移、人工验收和验收后全量尚未完成。相关命令及当前出口见[主题LOG](../../LOG-DB-001-Dashboard进度基线与执行记录.md)，使用路径见[用户指南](../../../intro/project-theme-authoring.md)。

## 已证明的产品边界

准确授权版本导出原ZIP；导入只读预检零写入，确认保存目标草稿，不自动发布或应用；有权目标Project及alias真实预览后，发布和分配分别生效。未编辑原包在B发布再导出与A逐字节一致，SHA-256为`353d7fdcd262a43efd992fa9f7807eb78879b380c6729df241503f953c3854c4`。目标身份、业务与文件映射留在目标，A和B对照项目保持。

| 材料 | 证明什么 |
| --- | --- |
| [首版浏览器回执](browser-checks.json)、[HTTP／PG／ZIP／文件与负例](http-pg-files.json) | 首版真实认证、路由、草稿／版本／绑定及目标资料；15项负例含越权、非法包、依赖、旧修订、版本冲突、错误文件和旧generation |
| [新来源响应丢失](recovery-check.json)、[既有来源恢复](existing-recovery-check.json)、[旧修订冲突](stale-revision-check.json) | 首版对应样本的恢复，后续修复与当前证明范围以下列审查材料为准 |
| [部署边界回读](review-20261018/deployment-boundary.json) | A／B简化证据app省略正式startup，两库无schema版本登记，ready503，不能证明正式migrator／就绪 |
| [导入恢复6项](review-20261018/import-review.json) | 连续导入、最终新建模式、真实POST后丢响应、排除另一同摘要来源、准确候选及绑定保持 |
| [重启后PG与原包](review-20261018/restart-pg-bytes.json)、[重启后独立浏览器](review-20261018/restart-browser-review.json) | 等待超时后B恢复可读，目标JSON／PNG、准确绑定及显式切回，DOM／HTTP／PG一致，A及B2保持 |
| [B真实再导出](review-20261018/reexport-review.json)及[A原ZIP](a-original.theme.zip) | 两端逐字节及响应摘要一致 |
| [环境指纹](environment.json)、[首版重启回读](restart-ready.json)、[说明链接](theme-guide-links.json) | 各时点的环境、liveness与界面帮助入口；正式ready缺口按审查材料读取 |

代表截图：[A准确原包导出](a-export-1440.png)、[B预检](b-preflight-1440.png)、[B真实资料](review-20261018/b-preview-1440.png)、[连续导入修复前](review-20261018/before-repeat-import.png)／[修复后](review-20261018/after-repeat-import.png)、[新建目标响应丢失核实](review-20261018/after-new-target-recovery.png)、[重启后切回](review-20261018/restart-browser-restored.png)。其余截图只作同次观察佐证。

## 环境与复现边界

A／B共享PG进程但使用不同数据库、主题文件根、用户、Project及Workdir；跨实例token401。会话材料保持私有，日常库及三套内置ZIP没有作为故障目标。证据入口`backend/test/e2e/project_theme_app.py`装配真实routers、认证、PG和文件，但省略正式应用lifespan；现有回执不能称正式部署迁移通过。

主脚本曾因旧同名数据定位及重启等待超时失败，准确来源定位和独立补验分别保留；不能将分段补验改记为一次主脚本整链通过。首版JSON中的成功状态只代表其执行时点，当前结论按LOG和独立审查范围判断。

复现脚本位于`backend/test/e2e/project_theme_migration_*`及`project_theme_import_review.py`，原私有会话／输出变量和启动命令可从整理前`63dc5af7`的本页恢复。恢复专项后先核脚本依赖、准确来源ID及具名隔离范围；主脚本失败时不运行依赖成功报告的后继脚本。旧recovery／stale脚本依赖首版固定样本，当前执行前需重新确认条件。

本轮最终前端13＋18相关用例、parser／契约48项、最新真实HTTP／PG竞争负例3项通过；完整历史命令见LOG。没有运行全量，人工及正式A／B证据仍待完成。新增恢复态主要为1440浅色观察，暗色、窄屏、跨浏览器及生产恢复未补验。
