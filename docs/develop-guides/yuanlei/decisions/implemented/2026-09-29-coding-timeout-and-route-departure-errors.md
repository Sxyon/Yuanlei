# 编码超时错误与页面离开请求

状态：implemented
类型：bug-fix
Owner：backend/package/yuxi/services/coding_execution_service.py

## 问题

用户的项目 AgentRun 使用 `deepseek:deepseek-flash`，其供应商协议为 Anthropic、Base URL 为 `https://api.deepseek.com`，请求 `/v1/messages` 后收到 404。上游模型调用按已选协议创建 Anthropic 客户端，直接使用配置的 Base URL；DeepSeek 的 Anthropic-compatible Base URL 应为 `https://api.deepseek.com/anthropic`，由模型供应商配置负责。项目任务委派没有覆盖该 Base URL，也不应改写默认模型或执行器。

另一个 OpenCode 凭据引用路径确实丢弃了供应商协议：引用 Anthropic 供应商时，环境构造仍选默认 OpenAI-compatible SDK。沙盒执行超时后返回非零退出码和普通文本 `Error: timed out`；当 CLI 没有结构化 error 事件时，编码 turn 虽然被判失败，却把错误详情留空。会话详情接口也没有返回 turn 的已持久化错误字段，编码会话工具也没有展示该字段。被 KeepAlive 缓存的项目任务详情和智能体工作台在离开页面后收到空路由参数，继续请求 `/undefined` 资源。

## 决策

编码执行失败时优先保存结构化执行器错误或基础设施错误；非零退出且只有普通输出时，仅将包含 `timed out` 的输出归一为固定超时诊断，其余情况保存退出码，不持久化任意 CLI 原文。会话详情返回 session 与 turn 错误字段，编码会话工具呈现 turn 错误。引用 Anthropic 模型供应商的 OpenCode 凭据使用 `@ai-sdk/anthropic`；Base URL 由供应商配置提供。命令超时仍按现有 deadline 结束并成为失败，不自动重跑同一命令；前端沿用会话状态轮询并在终态显示错误。人工重新委派创建新的执行意图。

两个 KeepAlive 页面在路由资源标识缺失时使旧加载失效并停止读取，不拼接空标识调用 API。

事实 Owner 分工：AgentRun 的模型供应商协议/Base URL 解析由 `backend/package/yuxi/models/providers/service.py` 和 provider cache 拥有，协议客户端构造由 `backend/package/yuxi/models/chat.py` 拥有；OpenCode 引用凭据的协议到 SDK 映射由 `backend/package/yuxi/services/coding_credential_service.py` 拥有；turn/session 失败收敛和错误持久化由 `backend/package/yuxi/services/coding_execution_service.py` 拥有，会话详情序列化由 `backend/package/yuxi/services/coding_session_service.py` 拥有；编码会话错误可见性由 `web/src/components/ToolCallingResult/tools/CodingSessionTool.vue` 拥有；空路由状态和迟到请求防护分别由 `web/src/views/ProjectAgentWorkbenchView.vue`、`web/src/views/ProjectWorkTaskView.vue` 拥有。

## 替代方案

- 超时后继续定时重复执行命令：不能判断先前进程是否已产生副作用，可能重复修改工作区。
- 超时后只轮询会话状态：执行层已经按 deadline 失败，轮询不能恢复该 CLI 进程，只会延迟反馈。
- 解析器未知文本时丢弃：导致用户只看到 `executor_error`，无法据此决定是否重试。
- 将模型供应商的协议映射到默认 OpenAI-compatible 客户端：与供应商显式选择的 Anthropic 协议冲突，无法形成正确的 OpenCode 请求。

## 后果

超时会及时进入可观察的终态，错误详情不包含任意命令输出。失败不会触发自动重试；是否重新委派由用户决定。治理委派和聊天中的编码会话通过 coding session 详情读取错误；独立项目工作任务继续以其 ProjectWorkExecution 与 AgentRun 状态为准。本决定不改变默认执行器或模型配置。

DeepSeek 的 404 属于模型供应商 Base URL 配置；用户将 Anthropic 协议供应商的 Base URL 改为 `https://api.deepseek.com/anthropic` 后，标准 Anthropic 客户端会拼接 `/v1/messages`。此配置归模型供应商维护，不产生上游代码修复。开发环境 OpenCode 没有进行升级或执行验证；当前日志只证明一次 sandbox 超时，不能据此判定 OpenCode 全局不可用。

## 验证

- Unit：非零退出码且无 JSON error 事件时，turn 与 session 均持久化固定超时诊断；未知非零输出不会写入错误字段。
- Unit：引用 Anthropic 模型供应商时，OpenCode 环境选用 Anthropic SDK，并将供应商 Base URL 原样传递。
- Web unit：编码会话工具显示 turn 错误文本。
- Web unit：KeepAlive 页面离开后不再使用空路由参数请求任务详情、执行列表或智能体工作台。
- 真实 DeepSeek/OpenCode 请求：不执行；供应商协议端点由 [DeepSeek Anthropic API 文档](https://api-docs.deepseek.com/guides/anthropic_api/) 作为配置依据，容器内 OpenCode 可用性留待容器更新后验证。
- Web lint、build 与开发页面导航验证；最终命令和结果以本次交付记录为准。
