# 模型输出配置与截断失败

状态：implemented
类型：bug-fix
Owner：backend/package/yuxi/models/chat.py

## 问题

上游模型配置没有进入 ModelInfo 的输出额度。当前安装的 langchain-anthropic 1.6.1 字段默认为 None，但构造 validator 从模型 profile 取 max_output_tokens；未知 profile 使用 `_FALLBACK_MAX_OUTPUT_TOKENS=4096`。当前 DeepSeek Anthropic 的 deepseek-flash、deepseek-v4-pro 均命中 fallback。去敏 PostgreSQL 聚合回读存在 stop_reason=max_tokens、output_tokens=4096 的响应，且存在绑定 completed Run 的截断响应。原故障的具体依赖版本、最终请求和全部中断时序未保存，因此当前复现与历史证据分别表述；4096 输出限额不等同于输入窗口、Agent 步数、超时、累计 token 或用户预算。

全 Anthropic 65536 临时值缺少模型适用边界。远端发现的 max_completion_tokens 原先只作为目录信息，缓存没有对应字段；OpenAI extra_body 白名单也不能为原生 Anthropic 提供额度。

## 决策

`enabled_models` JSON 保存 `default_output_tokens` 与 `max_output_tokens`，由 providers service 校验并经 ModelInfo/Redis 传递。默认额度与能力分离；调用参数优先，select_model 顶层参数优先于 model_params。同层不同输出别名矛盾时明确拒绝。Anthropic 与 OpenAI adapter 在最终请求边界校验额度，Gemini 在最终 generation_config 边界校验；无配置旧模型保留 SDK 既有默认。已知能力不会自动变成请求默认。

启动 bootstrap 仅对官方 HTTPS `api.deepseek.com/anthropic` 的 deepseek-flash、deepseek-v4-pro 补缺失默认 65536 和能力 393216，并保留管理员显式额度及 null、模型 endpoint override、代理与其他模型。默认选择沿用受影响模型的临时缓解值，能力范围来自 [DeepSeek 模型规格](https://api-docs.deepseek.com/quick_start/pricing/)与 [Chat Completions 参数定义](https://api-docs.deepseek.com/api/create-chat-completion/)；[Anthropic 兼容说明](https://api-docs.deepseek.com/guides/anthropic_api/)确认 max_tokens 支持。全 Anthropic 分支硬编码移除。

主 Agent 与子 Agent 在模型响应合并后、工具执行前识别输出额度与上下文窗口截断，以非重试 ModelError 进入已有错误通道。`chat_service` 保存部分响应文本、原始消息块、结束原因和同 Run 输出绑定，worker 持久 failed；旧 checkpoint、已完成工具步骤和产物保留。正常 end_turn、stop_sequence 与合法 tool_use 沿用既有行为。通用 adapter 保留结束原因，流式完整结束才标记 is_full；普通 HTTP `/api/chat/call` 对截断返回 422，detail 包含原因与部分输出。

## 替代方案

保留全供应商硬编码会误用未知能力；只修改 select_model 会漏过 Agent load_chat_model。自动续写与重放需要副作用恢复策略，超出修复范围。截断直接 fail closed 是当前最小有界处理，父 Agent 可消费失败子 Run 的结果后形成完整说明。

## 后果

用户在模型编辑弹窗设置默认输出，进程内配置缓存最多 5 秒后生效。未知模型留空仍可能命中短 SDK 默认，需要管理员按真实渠道设置。额度包含供应商计入输出的推理 token，不能保证生成完整；截断后用户先核对已有产物再继续。项目字段复用现有 JSON，没有新增数据库表或 Schema 版本。上游同步需保留最终输出参数与完整性边界，并在上游具备等价能力时缩小差异。

## 验证

配置说明由[模型配置](../../../../intro/model-config.md#默认输出与截断)拥有。最小负向集合覆盖非法类型、非正整数、超过已知能力、别名冲突和截断工具响应；流式与非流式 TCP 接收端核对两个加载入口的默认 65536、较小 32、合法 131072 与最大边界 393216，长合成响应为 66000 字符且原样保留。真实 API/worker/SSE/PostgreSQL 用例回读同 Run 失败状态、输出指针、内容与结束原因，并回读工具 Message 证明没有执行截断工具；普通 HTTP 返回部分响应与 422。模型配置通过真实管理 API 保存/非法更新拒绝，再从新 ModelCache 读取 Redis 值。

| 直接证据 / 命令 | 结果与范围 |
|---|---|
| `docker compose exec api uv run --no-sync --group test pytest test/unit/models/test_output_limits.py -x -q` | Passed，29 项；SDK 配置与 guard，含 Gemini 最终配置 |
| `docker compose exec api uv run --no-sync --group test pytest test/integration/services/test_output_limits_wire.py -x -q` | Passed，11 项；真实 TCP 与最终 SDK 参数；子后端真实构图验证正常工具、畸形参数截断和合法工具参数截断（准备 fixture，不代替 worker） |
| `docker compose exec api uv run --no-sync --group test pytest test/e2e/test_output_limits_e2e.py -x -q` | 7 passed / 1 xfailed；独立槽位，主 Agent 真实 HTTP/worker/SSE/PG；子 worker 未进入模型，见下方限制 |
| `docker compose exec web node --test test/unit/modelOutputConfiguration.test.js` | Passed，编辑保留输出字段与显式 null |
| `docker compose exec web pnpm run lint:check` / `pnpm run test:unit` / `pnpm run build` | Passed；515 项前端 unit，build 有既有 chunk 大小警告 |
| 真实浏览器设置与错误状态 | Passed；浅色、深色与移动视口字段可读；失败线程重新加载后 DOM 显示部分输出与中文截断提示 |
| `python3 -m unittest scripts.test_verify_engineering_contracts` | Passed，70 项 |
| `docker compose exec api uv run --group test pytest test/unit -m "not slow"` | 2843 passed / 63 skipped / 1 failed，失败为未改动的 Skill 多进程测试 20 秒超时；单独复测同样超时，未修改 Skill 代码或测试 |
| `node node_modules/vitepress/bin/vitepress.js build`（docs 目录，bundled Node） | Passed；相对链接检查已由工程 gate 执行，本变更无断链 |
| 真实 DeepSeek 官方 Anthropic 有界流式探针 | Passed，两模型 request max_tokens=65536、end_turn、output_tokens=8，返回指定合成标记；未消耗完整额度，未复测真实 4096 以上长生成 |
| `python3 scripts/verify_engineering_contracts.py` | 本变更检查通过；整体 Failed，专项旧文档四处对举式否定规则违规，未修改无关专项 |

真实探针使用已有开发凭证、禁用思考与 50 秒应用超时，只回读模型标识、请求额度、结束原因和输出用量，不保存密钥或用户内容。历史问题全部端到端时序仍无法重建。新增负向 oracle 与原有工程 workflow selector 共同维护，独立 Reviewer 负责语义审查。

真实子 Run 的创建端使用 `relation.child_thread_id` 为 runtime_scope_id，既有 worker 执行树校验要求等于创建者 runtime_scope_id；回读 error_type=invalid_runtime_scope，尚未请求模型。E2E 仅在该明确终态限定 xfail，保留未来进入模型后的截断断言。此独立执行树问题未在本次修复中修改，因此子 worker 截断持久化仍未验证。子后端真实构图/TCP 验证只证明 middleware 与工具边界。

独立 Reviewer 从完整需求、最终 diff 与证据审查参数优先级、SDK 边界、部分输出持久化和工具完整性，最终未发现阻断实现缺陷。

HTTP/Run 验证使用独立 Compose 槽位与 PostgreSQL/Redis，没有修改主开发容器的代码或数据。E2E 前需在 API 槽位启动合成接收端：`docker compose exec -d api uv run --no-sync python test/support/output_limit_server.py`；它仅接收 output-test，不调用外部模型。新代码启动后，既有官方 DeepSeek 配置由 bootstrap 补缺失字段。
