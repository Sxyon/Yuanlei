# 接入 Langfuse

Langfuse 是 Yuxi 的可选观测服务。它把一次 AgentRun 中的模型调用、工具调用、耗时和错误放到同一条 trace 中，方便按用户、线程、智能体和请求排查问题。

Langfuse 不拥有 Yuxi 的消息、运行状态或最终结果。即使 Langfuse 未配置、初始化失败或暂时不可用，聊天和 AgentRun 仍按本地业务链路运行。

## 能看到什么

Yuxi 会把本地运行信息映射到 Langfuse：

| Yuxi 信息 | Langfuse 字段 | 用途 |
| --- | --- | --- |
| 用户 `uid` | `user_id` | 按用户筛选 |
| 对话 `thread_id` | `session_id` | 查看同一线程的多轮运行 |
| 一次请求 | trace | 查看模型、工具、耗时和错误 |
| `agent_id`、operation 等 | metadata / tags | 按智能体和调用类型筛选 |

对话中的助手消息支持点赞或点踩。Yuxi 先把反馈保存到本地业务表；消息有对应 trace 时，再向 Langfuse 写入 `user-feedback` score。点赞为 `1`，点踩为 `0`，点踩原因作为 comment 保存。

## 配置

在 API 和 worker 的运行环境中设置：

```bash
LANGFUSE_PUBLIC_KEY=<your-public-key>
LANGFUSE_SECRET_KEY=<your-secret-key>
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

`LANGFUSE_BASE_URL` 用于自托管或指定区域；留空时使用 SDK 默认地址。需要显式关闭时设置：

```bash
LANGFUSE_ENABLED=false
```

`LANGFUSE_ENABLED` 不填写时默认开启，但只有同时提供公钥、密钥且安装了 Langfuse SDK，实际 tracing 才会启用。修改环境变量后重新创建 API 和 worker 容器；如果修改了依赖，还要重新构建镜像：

```bash
docker compose up -d --force-recreate api worker
```

密钥只放在受保护的运行环境中，不要写入仓库、Agent 环境或公开日志。

## 验证是否生效

1. 重启 API 和 worker。
2. 用测试账号发起一次真实对话，记录线程和大致时间。
3. 在 Langfuse 控制台按 `session_id`、`agent_id` 或时间筛选 trace。
4. 核对 trace 中的模型调用、工具调用、metadata 和耗时。
5. 对助手消息提交一次测试反馈，再检查 `user-feedback` score。

超级管理员还可以在 Yuxi 的调试面板中开启对话 Debug，从消息对应的 Run 入口打开 Langfuse trace。Yuxi 会先检查当前用户是否能看到这个 Run，再读取 Run 自身的 trace ID；历史 Run 可以从其权威输出消息兼容读取。配置 Langfuse 的 Run 在模型执行前固化关联，因此执行中失败、取消或中断且没有最终输出时仍可跳转。没有持久化 trace、Langfuse 未配置或 URL 不在允许来源时，页面会提示不可用，不会从相邻 Run 推测结果。

PostgreSQL 同时按 LangGraph lifecycle 保存可见 Model 与 Tool 调用的关键审计事实，包括稳定来源键、严格顺序、观察时间、执行状态和 monotonic 耗时；Model 另外保存可靠的 Provider usage，Tool 保存 effective input、输出或错误。运行中的 `model_audit` AIMessage 和 `tool_audit` ToolMessage 不进入普通历史；Model 声明的 pending ToolCall 用于审批兼容，工具开始后的执行事实由 ToolMessage 单向覆盖，最终回答仍由 AgentRun 的 `output_message_id` 确定。超级管理员可在消息时序调试面板按 Run 查看交错时间线。本地审计不依赖 Langfuse 导出，也不宣称每条 AIMessage/ToolMessage 已关联 Langfuse observation。

## 常见问题

- **看不到 trace**：检查 API/worker 是否读取到两组密钥、Langfuse SDK 是否安装，以及 `LANGFUSE_BASE_URL` 是否可访问。
- **聊天成功但没有 score**：本地反馈需要先保存；只有已关联 trace 的助手消息才会同步 score。
- **控制台显示旧数据**：Langfuse 客户端有缓冲，运行结束后会刷新；业务结果仍以 Yuxi 的 PostgreSQL 记录为准。

## 代码和测试入口

- [Langfuse 服务](https://github.com/xerrors/Yuxi/blob/main/backend/package/yuxi/services/langfuse_service.py)
- [反馈服务](https://github.com/xerrors/Yuxi/blob/main/backend/package/yuxi/services/feedback_service.py)
- [Langfuse 单元测试](https://github.com/xerrors/Yuxi/blob/main/backend/test/unit/services/test_langfuse_service.py)
