# 多模态模型能力探查与展示

状态：已实现
类型：模型能力发现与管理体验
主要 Owner：`backend/package/yuxi/models/providers/service.py`

## 需求与失败场景

代理渠道可能对同名模型屏蔽或改写能力，单靠官方模型文档无法说明当前渠道实际公布了什么。不同模型目录协议/服务又使用不同响应包裹和输入模态字段，现有管理页只从外部模型目录投影图片标记，无法区分当前渠道声明、官方精确档案、目录提示和未知。

## 必须保留的业务语义

- 能力事实限定在已配置 provider 渠道、`provider_type` 协议和精确 model ID；不能因同名模型跨渠道继承。
- 只把语义明确表示“输入”的目录字段归一为 `text`、`image`、`audio`、`video`、`file`、`pdf`。模态列表内表示支持；显式完整输入列表中未列出的已知模态表示不支持；无输入声明则是未知。
- `modalities` 等未标注方向的列表、输出模态和生成方法不等同于输入能力；不能据此打支持标记。
- 证据优先级为管理员精确图片覆盖、当前渠道模型目录显式输入声明、精确官方渠道档案、未知。外部模型目录仅可作为来源独立的展示提示，不能覆盖当前渠道事实或运行时 profile。
- 探查只调用管理员配置的模型目录端点，不发推理请求、不发送媒体内容，也不对同一 URL 盲目轮询其他协议。
- 管理列表在模型名称旁显示紧凑模态图标；图片状态可展示支持/不支持/未知，其他模态只展示有确认或外部目录提示的项目，避免增加模态列。
- 远端候选 `resolved_capabilities` 是返回时计算的渠道 profile，不是管理员 override；只有明确输入元数据随模型配置保留。

## 与 Yuxi 的边界

Yuxi 继续拥有 provider 配置、模型目录请求和模型缓存。元垒在既有 provider 服务与能力 profile 上归一化渠道输入元数据，并将结果投影到现有管理页；不创建并行 provider、模型目录或能力持久化中心。

## 稳定集成点

| 集成角色 | Owner | 语义 |
|---|---|---|
| 目录协议响应归一化 | `yuxi.models.providers.service` | 读取当前渠道已配置端点、协议认证和响应包裹；从输入方向明确的字段抽取模态声明 |
| 状态解析与出处 | `yuxi.models.providers.capabilities` | 渠道声明优先于官方精确图片档案；保留 supported/unsupported/unknown 和来源 |
| 远端候选 | `fetch_remote_models` / 远端模型 API | 每次按当前渠道实时解析，结果不落为管理员能力覆盖 |
| 管理展示 | `ModelProviderManagePanel.vue` / `modelMetadata.js` | 已启用模型及候选模型在名称旁显示来源明确的能力标签 |

完整协议 wire 和用户/工具图片输入行为由[LLM 原生图片输入与能力感知](native-llm-image-input.md)拥有；本 Feature 只拥有目录元数据发现与管理展示。

## 上游依赖

依赖现有 provider 配置、模型目录端点、模型缓存 profile、OpenCode 模型元数据目录和 Vue 管理页。若上游提供按渠道、协议、模型 ID 区分并带出处的输入模态 profile，则采用上游事实并删除重复目录归一化逻辑；单纯布尔 vision 或全局模型目录不满足替换条件。

## 合并判断

- 上游增加带出处、按渠道与协议区分的能力声明时，复用其 Owner 并删除重复的字段适配。
- 上游仅增加模型名全局 `vision` 属性或未区分输入/输出模态时，继续保留当前渠道解析语义。

## 替换或删除条件

上游完整提供当前渠道目录能力的读取、出处与未知状态后，可迁移到上游事实并移除此归一层。若管理页不再消费多模态标签且运行时图片 Feature 已独立拥有全部能力事实，则删除本 Feature 与其展示逻辑。

## 决策与证据

- [按渠道归一化多模态能力元数据](../decisions/implemented/2026-09-24-channel-scoped-multimodal-metadata.md)
- 后端 owner-local 证据：`backend/test/unit/services/test_model_provider_service.py`、`backend/test/unit/services/test_model_capabilities.py`
- 前端 owner-local 证据：`web/test/unit/model_metadata_catalog.test.js`、`ModelProviderManagePanel.vue` lint/build 与真实管理页面检查
- 未对真实 provider 目录发送请求；外部 provider 字段漂移仍可能使能力保持 unknown。
