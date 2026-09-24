# 能力驱动的 LLM 原生图片输入

状态：implemented
类型：feature
Owner：backend/package/yuxi/models/providers/capabilities.py

## 问题

模型能力原先只由 Web 的 models.dev 快照展示，API 与 Worker 没有能区分渠道、协议、精确模型 ID 的运行时事实。中间件按 SDK 类型猜测 tool 图片兼容性，并在 Provider 图片报错后按错误文本触发 OCR。用户输入也把图片 MIME 固定为 JPEG，缺少实际图片内容校验。

目标供应商能力以官方模型目录与协议文档为基准：OpenAI GPT-6 Astra、Sol、Luna，以及 DeepSeek `deepseek-flash` 和官方列出的 V4 兼容别名支持原生图片输入；DeepSeek `deepseek-v4-pro` 不支持图片输入。OpenAI Chat Completions 的图片能力不等价于 Agent 工具调用能力；GPT-6 Astra 的工具请求需要 Responses，Sol/Luna 当前 Chat 工具调用要求显式 `reasoning_effort=none`。OpenAI [模型目录](https://developers.openai.com/api/docs/models)、[最新模型指南](https://developers.openai.com/api/docs/guides/latest-model)和 DeepSeek [模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)、[更新日志](https://api-docs.deepseek.com/updates/)、[Vision 指南](https://api-docs.deepseek.com/guides/vision/)是这些精确档案的事实来源。

## 决策

- 图片能力由 provider、当前实际协议、model ID 三元组解析。精确官方图片档案、同渠道明确输入模态元数据和管理员精确图片覆盖按优先级合并；无证据时为 `unknown`。官方 DeepSeek `deepseek-v4-pro` 档案精确匹配时为 `unsupported`，代理渠道仍为 `unknown`。能力与来源写入现有 `ModelInfo`/Redis 视图，并由 `/models/v2` 同时提供给 API、Worker 和 Web，不新建能力表或第二模型目录。多模态目录字段和来源优先级由[按渠道归一化多模态能力元数据](2026-09-24-channel-scoped-multimodal-metadata.md)扩展。远端候选使用同一解析器，将结果以独立 `resolved_capabilities` 字段返回；该字段不是可持久化的管理员配置。
- 管理员覆盖只接受当前支持的图片输入与 tool-result 字段；官方档案仅在 provider、host、protocol、model ID 精确匹配时生效。代理渠道不会继承官方支持声明。
- 用户输入沿用 LangChain 标准消息块与历史 `image_url`，保留多图顺序、detail 和真实 MIME。边界校验 base64、HTTP(S)/data URL、真实图片字节和 MIME 一致性；单图解码后不超过 5 MiB，并在 Base64 解码前拒绝超限内容。Worker 仅修复精确匹配旧直接图片入口记录的 JPEG 标注 PNG，不改写其他历史消息。无效数据在入队或发起 Provider 请求前失败。旧的空 `image_content` 仍按文本请求处理。
- `ImageInputCompatibilityMiddleware` 按能力档案决定发送或结构化拒绝。Chat Completions 的 tool 图片提升为紧随 tool 结果的合成 user 图片，不写回 checkpoint state；未经 wire 合同验证的原生 tool 图片拒绝。供应商图片报错不再触发隐式 OCR；OCR 仍作为显式工具。
- GPT-6 Astra 在当前 tool-enabled Agent Chat 图中 fail-closed，直到 Responses adapter 可承载所需工具协议；Sol/Luna 的 Chat 工具调用仅在请求明确配置 `reasoning_effort=none` 时放行，wire 必须原样携带该值。该工作不静默改写 reasoning 或自动切换协议。
- 真实模型、协议和路由事实由源码与请求载荷拥有；Decision 不定义新的能力注册中心。模型边界异常保留结构化分类，但本次不改变长期 Run/API error contract，也不新增逐请求图片审计事件。
- 管理列表使用 `/models/v2` 的 profile，在模型名称旁以紧凑图标 tag 显示已启用模型的图片输入状态，不按模态增加表格列；远端候选使用返回的 `resolved_capabilities`。OpenCode 模型目录只保留为候选展示补充：当前渠道未知时可以展示目录标记，但必须提示它不是渠道声明；明确 unsupported 时目录 image 标记不得覆盖。其他输入模态的字段识别与展示见上述多模态决策。

## 替代方案

- 只按模型名维护 `vision=true` 或将 models.dev/OpenCode 投影当作最终真相：无法区分代理渠道与实际协议，也可能因目录延迟误删图片；拒绝。
- 把 `resolved_capabilities` 合并到可编辑的 `capabilities` 配置对象：远端候选勾选入库时可能将解析档案误存为管理员覆盖；拒绝。
- 对未知能力乐观试发，再按错误文案学习或自动 OCR：产生外部副作用、信息丢失且错误归因不可靠；拒绝。
- 为本次改动重建 Attachment/Emitter 栈或新增能力数据库：与现有 LangChain 内容块、provider JSON 配置和 Redis 运行时视图重复；拒绝。
- 一期同时实现 Responses、Anthropic、Gemini、Ollama 和真实供应商探针：超出当前 Chat Completions 图片主链路；后续由实际 adapter 与校准证据驱动。

## 后果

- unknown 与 unsupported 的图片请求会在调用 Provider 前失败，即使某个渠道碰巧接受图片；管理员可以针对精确模型配置覆盖。纯文本请求保持兼容。
- GPT-6 Astra 的图片能力可被准确展示，但当前通用 Agent 图因工具协议约束不能借 Chat Completions 执行；Responses adapter 是开放该路径的前置条件。
- 合成 tool 图片只属于本轮 Provider request 投影，不增加持久消息、审计记录或 checkpoint 标记。重放正确性由实际 checkpoint/E2E 路径持续验证。
- 直接 API 与模型消息共用 5 MiB 解码后单图上限，与现有 image processor 输出预算一致；系统不下载远端图片 URL，以免引入 SSRF 与新的对象生命周期。
- 上游若提供等价的带出处能力档案，应采用上游 Owner 并移除重复解析；仅布尔 vision 标志不足以取代协议与 tool-result 语义。
- 远端候选列表会在 `/models` 缺少模态字段时仍展示已核实的精确后端档案；未纳入 profile 的模型继续明确显示未知，目录提示不会被渲染成运行时支持保证。

## 验证

| 验收主张 | 直接证据 | 负向证据 | 当前结果 |
|---|---|---|---|
| 能力按渠道、协议、模型精确解析并保留出处 | resolver、cache、provider service 与 `/models/v2` 单测 | 同名跨渠道/协议不命中；未知不升级为支持；官方 DeepSeek V4 Pro 明确不支持图片 | 通过：相关 136 个后端 unit 全部通过 |
| 官方目标模型可发出原生 user image，格式、顺序与 detail 保留 | Astra/Sol/Luna/DeepSeek Chat Completions HTTP MockTransport wire 测试 | 坏字节、MIME 不匹配和不支持/未知档案在 Provider 前拒绝 | 通过：wire 与图片入口负向测试通过 |
| GPT-6 Chat 工具调用约束不被静默绕过 | Astra/Sol/Luna profile 与 `reasoning_effort=none` wire 测试 | Astra 与缺少显式 `none` 的 Sol/Luna 工具请求结构化拒绝 | 通过：能力 middleware 与 wire 测试通过 |
| API→PostgreSQL→Worker→Provider stub 图片主链路完整 | deterministic native-image E2E；stub 校验收到 PNG data URL，PostgreSQL 回读 `image_content`、`raw_message`、Run 与最终输出；历史误标修复与超限前置拒绝有 unit 覆盖 | 含测试标记但未收到有效 user PNG 时 stub 返回 422；过大输入不得进入 Base64 解码或 request 队列 | 通过：正向 assembled-path 与相关负向/历史兼容测试通过 |
| Web 上传 MIME 与后端能力展示保持一致 | MIME unit、`ModelProviderManagePanel` 当前页面、Web lint、unit 与 production build | PNG 不得被改写为 JPEG；前端不覆盖后端 profile | 通过：2026-09-24 本地登录页面实测 DeepSeek `deepseek-flash` 显示 supported/`deepseek_vision_docs`，`DeepSeek-V4-Pro` 显示 unsupported/`deepseek_models_docs`；图标在名称旁保持对齐 |
| 远端候选和已启用列表展示一致的图片输入证据 | `fetch_remote_models` 对 DeepSeek 精确模型解析 profile；目录与 profile 合并逻辑 unit；已启用模型读取 `/models/v2` | 未知 profile 不伪装支持；明确不支持优先于目录 image 标记；候选 profile 不进入管理员覆盖配置 | 通过：后端相关 44 unit、Web 元数据 2 unit；未对真实供应商触发 `/models` 请求 |
| 工程契约与文档索引闭合 | `verify_engineering_contracts.py` 与其 unittest | Decision/Feature 链接及 Owner 路径由检查器验证 | 通过：128 decisions、11 Yuanlei features、33 routers 等索引检查；70 个 unittest 通过 |
| 文档站链接与导航构建 | `cd docs && pnpm run build` | 死链接检查不忽略或绕过 | 未通过：未修改的 `develop-guides/yuanlei/features/brand-identity.md` 指向不存在的 `.vitepress/theme/components/YuanleiHome.vue` |
| 全后端 unit 兼容 | `pytest test/unit -m "not slow"` | — | 2550 通过、57 跳过；3 个既有 XLS 测试因容器缺少可选 `xlrd` 失败，与图片变更无关 |
| 真实官方/代理 Provider 行为和 checkpoint 历史重放经过校准 | 手工真实 Provider probe 与独立 checkpoint replay | 不用 mock 冒充 Provider 或 checkpoint 证据 | Not run：无专用 Provider probe；checkpoint 重放不属于一期 assembled-path gate |

验证命令与结果：

```bash
python3 scripts/verify_engineering_contracts.py
python3 -m unittest scripts.test_verify_engineering_contracts
docker compose exec api uv run --group test pytest test/unit -m "not slow"
docker compose exec api uv run --no-sync --no-dev pytest test/e2e/test_deterministic_agent_path_e2e.py::test_replay_rejects_requests_outside_deterministic_contract test/e2e/test_deterministic_agent_path_e2e.py::test_deterministic_agent_run_sends_native_user_image_to_provider -q
docker compose exec web pnpm run lint:check
docker compose exec web pnpm run test:unit
docker compose exec web pnpm run build
cd docs && pnpm run build
git diff --check
```

`docker compose exec -T api uv run --frozen --group test pytest test/unit/services/test_model_provider_service.py test/unit/services/test_model_capabilities.py -q` 为 44 passed；本次 V4 Pro 精确档案与代理隔离用例在 `test_model_capabilities.py` 的 17 项中通过。Web lint 通过，`pnpm run test:unit` 为 382 passed，production build 通过（存在 chunk size 提示）。工程契约检查与其 70 个 unittest 通过。文档构建仍被既有 `brand-identity.md` 指向不存在的 `YuanleiHome.vue` 死链阻断，与本决策链接无关。真实供应商远端模型列表没有执行，避免在验证中向供应商发送本地配置的 API Key。

E2E 使用本地确定性 Provider stub，不调用真实 Provider。Full package Ruff 检查在未修改的 sandbox/provider 与 storage/manager 文件上报告 lint/format 问题；受影响 Python 文件单独 lint/format 检查通过。
