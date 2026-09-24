# LLM 原生图片输入与能力感知

状态：已实现一期
类型：新增能力与上游模型兼容
主要 Owner：`backend/package/yuxi/models/providers/capabilities.py`

## 需求与失败场景

元垒需要让支持视觉的聊天模型直接接收用户图片与工具返回的图片，而不是先把图片转成 OCR 文本。原有实现只在前端从 models.dev 快照展示图片能力，后端运行时没有同一能力事实；图片适配只按 `ChatOpenAI` 类型判断，供应商拒绝后再按错误文案触发 OCR。当前一期实现以 provider profile、图片校验、Chat Completions wire 和真实 API/Worker/provider stub 主链路闭合该问题；Responses adapter 与付费真实 Provider 校准不在一期范围。

首批目标是 OpenAI GPT-6 Astra、Sol、Luna 与 DeepSeek Flash 系列的原生图片输入。DeepSeek `deepseek-v4-pro` 官方渠道明确不支持图片输入。具体模型 ID 必须绑定实际供应商渠道与当前实际协议，不能仅凭名称相似自动继承能力。GPT-6 Astra 的 Chat Completions 工具调用不可用；Sol/Luna 仅在 `reasoning_effort=none` 时可用。图片输入支持不能推导成 Agent 工具工作流兼容。

## 必须保留的业务语义

- 模型图片能力按 `(provider_id, protocol, model_id)` 解析；同名模型的其他渠道不自动继承。
- `supported`、`unsupported` 与 `unknown` 是不同状态；未知能力不会被伪装为支持。官方 DeepSeek `deepseek-v4-pro` 档案精确匹配时为 `unsupported`，代理渠道仍为 `unknown`。
- 用户图片与工具结果图片分别判断。模型支持用户图片，不代表当前协议允许图片留在 tool result 中。
- Chat Completions 工具调用约束单独解析；不为兼容而静默切换 Responses 或降低 reasoning effort。
- GPT-6 Astra 的图片档案为 supported 不代表当前 Agent 可用：现有 Chatbot/SubAgent graph 都向模型提供工具 schema，因此 Chat Completions 请求会因其 `responses_required` 约束而 fail-closed，直到 Responses adapter 或无工具 graph 存在。
- 支持时发送原生图片内容；不支持或未知时在请求发往供应商前返回结构化错误，不静默 OCR、不丢图后继续回答。
- 纯文本请求、历史 OpenAI `image_url` 消息和现有模型供应商配置保持兼容；恢复历史 direct-image 消息时，只对与存储 `image_content` 完全相同、但旧版标成 JPEG 的 data URL 纠正真实 MIME。所有入口的单图解码后上限为 5 MiB。
- 能力来源、最终取值与协议转换结果可解释，但日志和审计不记录图片 base64、凭据或受保护 URL。

## 与 Yuxi 的边界

Yuxi 拥有模型供应商、`ModelInfo` 缓存、LangChain 消息与 Agent middleware 装配。元垒在这些真实 Owner 上增加运行时能力档案与图片输入装配，不创建平行模型注册中心，不把能力判断放进前端，也不改写附件持久化领域。

OCR 与文档解析继续作为显式工具能力存在，但不再承担 LLM 原生图片输入失败后的自动兼容路径。

## 稳定集成点

| 集成角色 | 当前 Owner | Yuanlei 语义 |
|---|---|---|
| 能力配置与解析 | `yuxi.models.providers.capabilities` | 合并管理员精确覆盖、同渠道远端元数据与已核实官方精确档案，保留出处 |
| Worker 运行时视图 | `ModelInfo` / `ModelCache` | API 与 Worker 消费同一协议和能力档案 |
| 远端模型候选 | `fetch_remote_models` | 对未启用候选复用同一能力解析，返回独立的 `resolved_capabilities` 展示字段，不将解析结果写成管理员覆盖 |
| 用户消息兼容 | `input_message_service.py` | 接受现有字符串、`image_url` 与历史 `raw_message`，保留真实 MIME |
| 模型输入装配 | `model_input.py` | 按能力校验图片并决定提升 tool 图片为 user 消息或拒绝 |
| Wire 发射 | `models/chat.py` | 能力档案反映当前实际 adapter；未来扩协议需实现对应 adapter，不能仅配置切换 |
| UI 展示 | `/models/v2`、远端模型 API、`ModelProviderManagePanel` | 图片与其他已知输入模态在名称旁以紧凑 tag 展示；远端候选区分当前渠道解析结果与目录提示。多模态字段归一规则见[多模态能力探查 Feature](multimodal-model-capability-discovery.md) |

## 上游依赖

该能力依赖 LangChain 标准内容块、各 Provider SDK 的消息转换、OpenAI 兼容 Chat Completions 载荷，以及管理员配置与精确官方模型事实。OpenCode 模型目录可以补足远端候选的展示信息，但不作为运行时图片能力事实；有效支持状态与来源由后端 profile 拥有。依赖升级可能改变内容块或 tool result，必须由 wire 合同测试和确定性 assembled-path E2E 重新证明。

## 合并判断

- 上游提供带出处、支持渠道/协议维度的模型能力档案时，采用上游事实并删除重复解析层。
- 上游只提供布尔 `vision` 时，保留 tool 图片与协议差异的 Yuanlei 语义。
- Provider SDK 原生统一 tool 图片后，可以缩小角色提升矩阵，但必须保留不支持协议的负向案例。
- 外部目录更新不能自动覆盖管理员显式配置或已验证的精确渠道覆盖。

## 替换或删除条件

只有上游同时覆盖运行时能力解析、结构化错误、历史消息兼容和 tool 图片协议差异，并通过同一 assembled-path 证据后，才删除本差异。单纯 UI 出现视觉徽标或供应商声称支持图片，不构成替代证据。

## 决策与证据

- [能力驱动的 LLM 原生图片输入](../decisions/implemented/2026-09-21-capability-driven-native-image-input.md)
- 当前差距可由 `backend/package/yuxi/models/providers/cache.py`、`backend/package/yuxi/agents/middlewares/model_input.py`、`backend/test/unit/services/test_model_cache.py` 与 `backend/test/unit/middlewares/test_model_input_middleware.py` 定位。
- 一期由模型能力解析单测、Provider wire 合同测试、API/Worker 确定性 E2E 与显式真实供应商探针共同提供证据；后者需要专用凭据且不是 CI gate。
