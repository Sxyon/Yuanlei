# 个人空间附件引用与延迟线程创建

状态：实现已接入，部分真实链路待验证
类型：产品交互与附件契约扩展
主要 Owner：`web/src/components/AgentChatComponent.vue`

## 需求与失败场景

新对话打开或确认文件选择器会提前创建线程，导致用户在首次发送前被锁定到当前 Agent。原选择器依赖 threadId 并浏览 Project Workdir，无法在无线程状态浏览用户个人空间；后端引用契约也只接受 Workdir 路径。

## 必须保留的业务语义

- 打开选择器和无线程确认文件都不创建线程。
- 首次发送前引用只存在前端缓存，用户仍可切换 Agent 和 Project。
- 发送时先创建真实线程，再在个人空间边界内物化引用；引用失败时中止发送并保留缓存。
- workspace 引用只登记 runtime 路径，不复制源文件；删除引用只删元数据并保留源文件。
- 旧客户端未提供 `source` 时继续使用 `workdir` 兼容语义。

## 与 Yuxi 的边界

Yuxi 继续拥有 Conversation、附件元数据、Workdir 引用和聊天发送主链路。元垒增加个人空间浏览、发送前缓存、`source: workspace` 校验和 runtime 路径映射。

## 稳定集成点

| 集成角色 | 当前 Owner | Yuanlei 语义 |
|---|---|---|
| 无线程状态与发送时序 | `AgentChatComponent.vue` | 确认只缓存，发送时物化 |
| 个人空间选择器 | `ProjectFilePickerModal.vue` | 无 threadId 浏览 Workspace tree |
| 附件引用契约 | `attachment_service.py`、`chat_router.py` | 按 source 选择 Workdir 或 Workspace 校验 |
| 模型路径 | chat service 与 workspace paths | 只暴露 Sandbox 可读 runtime 路径 |

## 上游依赖

该能力依赖线程创建时机、Agent 切换锁定条件、附件引用 API、Workspace tree、runtime user-data 映射和模型附件上下文。上游重写聊天组件或附件契约时需要按用户旅程验证，不以组件名称决定保留方式。

## 合并判断

- 上游原生支持发送前 draft 和个人空间引用：采用上游状态模型，保留不复制、fail-closed 和源文件不删除语义。
- 上游只调整选择器 UI：迁移缓存与发送时序，不机械保留旧组件结构。
- 上游取消 Workdir 引用兼容：先确认现有客户端和持久附件数据，再决定是否移除默认值。

## 替换或删除条件

上游能力覆盖无线程浏览、发送前缓存、个人空间授权、runtime 路径、不复制和失败恢复后，可以删除元垒实现。需求改为上传快照或复制文件时必须建立新 Decision，明确字节 Owner、配额和删除语义。

## 决策与证据

- [附件文件选择改为个人空间浏览并延迟线程创建](../decisions/proposed/2026-09-17-attachment-picker-workspace-browse-deferred-thread.md)
- Web 文件选择测试、`backend/test/unit/services/test_attachment_service.py` 和 HTTP integration 用例拥有当前证据；真实页面与缺少测试账号的链路保持 Decision 中的 `Not run`。
