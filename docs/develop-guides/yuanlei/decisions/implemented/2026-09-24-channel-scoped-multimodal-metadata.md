# 按渠道归一化多模态能力元数据

状态：implemented
类型：feature
Owner：backend/package/yuxi/models/providers/service.py

## 问题

远端模型目录以不同字段和响应包裹声明输入模态；模型代理可能过滤或改写这些信息，同名模型在不同渠道不应共用结果。此前服务只识别部分 `architecture.input_modalities` 字段，而管理页也无法区分当前渠道声明、官方精确档案、外部目录提示和未知。

## 决策

- 远端能力探查限定在 provider 配置的 `provider_type`、模型列表 endpoint、认证和 model ID。支持不同列表响应包裹及明确表达输入方向的常见模态字段，并归一到 `text`、`image`、`audio`、`video`、`file`、`pdf`。不会把泛化 `modalities` 数组或输出模态当成输入证据。
- 只查询已配置的模型列表 endpoint；不向同一 URL 盲目试发其他协议请求，也不发模型推理请求或传输图片、音频、视频样例。Anthropic 与 Gemini 使用各自模型目录认证头；OpenAI 兼容与 OpenRouter 使用 Bearer 认证。
- 显式、完整的输入模态列表中列出的已知模态为 `supported`，未列出的已知模态为 `unsupported`；目录没有输入声明时保持 `unknown`。来源按模态分别记录：管理员精确图片覆盖只替换图片来源，当前渠道目录声明为其声明的各模态提供来源，精确官方渠道档案只兜底图片来源。外部模型目录只补充候选展示，不覆盖渠道 profile。
- 能力档案继续使用现有 `ModelInfo`、Redis 视图和远端模型 API，不建立第二模型目录。远端候选的 `resolved_capabilities` 仅是计算结果，不作为管理员覆盖持久化；明确的目录输入模态仍随被启用的模型配置保存。兼容原有 `image_input` 读取方。
- 管理页在模型名旁显示模态图标，不增加表格列。图片可见 supported、unsupported、unknown；其他模态只展示已确认能力或带来源的外部目录提示。用户主动刷新远端模型后，当前渠道匹配的档案同步到已启用模型行；管理员图片覆盖保持优先。

## 替代方案

- 按模型名或模型家族推断能力：无法区分代理渠道的过滤差异，拒绝。
- 只以官方文档或全局模型目录作为结论：不能证明当前中转渠道能力，拒绝作为主事实源；精确官方档案仅作兜底，目录仅作提示。
- 发送样例媒体进行推理探测：产生费用并向外部渠道发送内容，拒绝。
- 对同一地址轮询多个猜测协议：认证和端点语义不同，可能误调用或泄露凭据，拒绝；按显式配置的协议和 endpoint 解析。
- 把目录缺少的模态判定为不支持：把未知误报为否，拒绝。

## 后果

- 渠道声明优先于同名模型的官方档案；无显式元数据的中转站模型会继续显示未知，而不会被伪装成支持或不支持。
- 协议字段不统一或不完整时仍可能保持未知。新增协议元数据形状须有语义明确的输入声明及负向测试，不得从输出能力、方法名或推理行为猜测输入能力。
- 外部目录提示不是渠道转发保证。已启用模型的原生图片请求仍由[能力驱动的 LLM 原生图片输入](2026-09-21-capability-driven-native-image-input.md)中的运行时 profile fail-closed 规则拥有。

## 验证

| 验收主张 | 直接证据 | 负向证据 | 当前结果 |
|---|---|---|---|
| 不同目录响应包裹和输入字段归一为同一结构 | `test_model_provider_service.py` 的协议形状、字段别名、认证和 model envelope 用例 | 泛化 `modalities`、输出模态、损坏声明和空字符串不能成为输入证据 | 通过：后端相关服务、resolver 与 router 共 67 项 unit |
| 渠道声明覆盖官方档案且能力不跨渠道，覆盖来源按模态隔离 | `test_model_capabilities.py` 中解析优先级、按模态来源与精确官方渠道用例 | 代理渠道保持 unknown；显式空输入列表只得出 unsupported；图片管理员覆盖不改变音频/视频来源 | 通过：后端能力 resolver 用例覆盖 |
| 探查只访问配置的模型目录，不做推理探测 | `test_fetch_models_requests_only_the_configured_directory_endpoint` | HTTP mock 断言只有配置 endpoint 的单次 GET | 通过；未向真实供应商请求 |
| 模型名称旁展示来源清楚的多模态标签 | Web model metadata tests、lint、production build 与本地管理页截图 | unknown 以中性问号显示，目录提示不覆盖明确 unsupported | 通过：Web unit 3 项、lint/build 通过；本地页面确认 DeepSeek Flash 与 V4 Pro 图标紧邻名称且无独立能力列 |
| 决策、Feature 与工程链接一致 | `verify_engineering_contracts.py`、其 unit、文档 build | 不忽略决策链接和已有无关死链 | 通过：工程检查与其 70 个 unit 通过；VitePress build 唯一残留为既有 `brand-identity.md` 指向缺失 `YuanleiHome.vue` 的死链 |
