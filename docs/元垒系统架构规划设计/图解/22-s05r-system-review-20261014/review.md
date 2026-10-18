# 全项目主题实施证据摘要

历史范围：2026-10-14—15，format 1／ABI 2／baseVersion 1。当前范围与状态见[SYS](../../SYS-DB-001-Dashboard系统需求与架构设计.md)和[LOG](../../LOG-DB-001-Dashboard进度基线与执行记录.md)。本页保留有用结果，不再领取当时S05／S06任务。

## 设计与实际观察

批准对象为<a href="../21-full-project-theme-20261013/review.html" target="_blank" rel="noopener">DB-P07原型</a>，[批准回执](../21-full-project-theme-20261013/design-approval.json)记录SHA-256 `9fbfdbce2d041798634a425cabea7a474be00c9eaf13bc6b24bc1c21d8edef43`。用户2026-10-15审核指出布局与交互偏差，随后按批准源码修正；该次否决不由测试通过撤销。浏览器策略当时拒绝打开本地原型，因此只做源码对照和实际产品观察，没有双页面像素比较。

[实际DOM与交互回读](prototype-alignment-browser.json)记录总览主次栏、议题正文与折叠决定、混合动态、蓝图两布局及草稿、行动计划、结果审核和设置等代表场景。旧界面结构被可信能力组件替换，原业务API、状态、权限和历史继续拥有事实。

## 业务与持久证据范围

合成“社区阅读空间”故事贯通蓝图→议题／评论→批准决定→行动计划纳入工作→两次结果分别不接受／接受→单独完成工作→资料保存及项目助手配置。PG回读工作done、条件修订2和两份结果状态；第三主题独立页面ID和顺序只覆盖部分能力，其余在同壳继承基础v1。无来源决定准确索引和旧链接保持。

官方storage-migrator曾将39升40，旧1条绑定及2条版本逐行对账保持；版本新增不覆盖旧包。项目文件授权复用原安全边界。失权迟到请求和主题浮层卸载有专项负例。

## 历史检查与未验

- `docker compose exec -T api python -m pytest test/unit -m 'not slow' -q`：2922通过／63跳过；规定uv命令因镜像下载未完成。
- `docker compose exec -T api python -m pytest test/integration/api/test_project_themes_api.py -q`：20通过；动态专项2通过／18未选。蓝图／治理真实API23通过。
- `cd web && pnpm run test:unit`：初版571，展示修正后最新完整578通过；全量启动后补充的失权等改动另有10项专项，不能合称末版全量。lint及build通过，工程契约和71项脚本unit通过。
- 工作结果API在原Minio容量不足时失败；独立同版本临时Minio与隔离API复验1通过。原环境容量限制保持，未删除既有对象。
- 375／768／1024／1440 CSS宽度及明暗有观察；原生浏览器200%菜单缩放未执行。视觉放大不替代该项。

外部模型、付费委派、Git发布、真实周期报告、协作和Andon未执行。当前验收状态由最新LOG拥有；历史局部测试和源码Review只证明上述边界。精确过程和命令可从整理前提交`63dc5af7`的本文件恢复。
