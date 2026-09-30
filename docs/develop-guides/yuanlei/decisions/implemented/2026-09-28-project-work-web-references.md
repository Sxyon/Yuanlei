# 项目任务网页引用

状态：implemented
类型：feature
Owner：backend/package/yuxi/services/project_work_service.py
关联 Feature：[独立项目工作任务与 Issue](../../features/project-work-tasks.md)

## 问题

任务详情与评论能记录文字结论，但无法把可核对的网页资料作为独立条目保存。把链接直接写入评论会失去稳定标题、添加人和可撤销入口。

## 决策

在 yuanlei schema v17 增加 `project_work_references`，每条引用绑定一个任务，保存标题、HTTP(S) URL、添加人 UID 和创建时间。任务详情按创建顺序返回引用。当前项目用户可添加或移除，service 与 repository 均核对 active selectable Project 归属；项目或任务删除由外键级联清理。URL 只保存并展示，不由服务器抓取；拒绝非 HTTP(S)、含用户凭据、空主机、空白或控制字符地址。页面使用新窗口链接并设置 `noopener noreferrer`。

## 替代方案

- 将链接混入任务详情 JSON：每条引用没有独立作者与创建时间，也难以单独移除。
- 将链接写入评论：无法形成任务当前引用列表，删除评论还会破坏讨论的追加式语义。
- 服务端抓取并复制网页：增加外部网络、SSRF 和内容生命周期约束，当前需求只需保存引用。

## 后果

引用是用户提供的网页地址，目标页面可变或失效；元垒保存其地址和来源记录，不声称内容快照。项目文件附件仍需独立设计，不能把网页 URL 当作已上传文件。

## 验证

隔离 PostgreSQL 的 v16→v17 迁移与重复执行、真实 HTTP 的添加/回读/移除及跨项目和跨用户拒绝均通过，包含异常主机/端口、非 HTTP(S) 与缺少双斜杠的负向地址。Web lint、相关单测、build 和文档 build 通过；真实浏览器在临时项目任务中添加、回读并移除网页引用，临时数据已清理。后端全量 unit 的 `uv run` 因可编辑安装文件权限失败；直接 `python -m pytest` 得到 2716 passed、61 skipped、6 failed，其中 5 项是本次版本升级后未更新的迁移测试 mock，修正后相关 18 项通过；余下一项是与本功能无关的跨进程技能锁测试，在单独重跑时仍因其子进程超时失败。完整 unit gate 仍未通过。
