# LOG-CA-001｜协作接入与 Andon 暂停盘点与事实进展

记录日期：2026-10-10。状态：按用户决定全面暂停专项新增推进。源码基线：`codex/dashboard`，`3c5ee33c64f82fcb5214f29e7b7198730bdeed55`；协作工程提交：`be41fced4745a6650031f4a2b3bf35f792f0be62`。

本文维护进展、原反馈、已确定细节、未验与暂停交接。目标设计见 [SYS-CA-001](SYS-CA-001-协作接入与Andon系统设计.md)，工程冻结和重启前提见 [DEV-CA-001](DEV-CA-001-协作接入与Andon冻结落地细节.md)。

## 0. 目录集成时点与状态口径

本文第1节及原测试表是2026-10-10初次重整的时点证据。当前目录已集成，产品基线仍为3c5ee33c；工作树已有管理与文档改动，不能继续称当前工作树干净。此轮没有重跑产品HTTP/PG/worker或远端试验，新增图稿与文档检查单独记录。


## 1. 暂停决定的执行边界

停止新的开发包、平台对接写试验、模型付费运行、部署切换、权限扩大、Andon和正式授权建设。本轮只做只读盘点、相关本地测试及outputs归档。没有发送原会话消息、取消运行、关闭Gateway、禁用已合并服务、删除数据或修改业务权限。

这份暂停记录需要在原会话继续工作前传达。保留当前代码和历史证据，不将暂停误写为“零成果”或“C1产品验收完成”。

## 2. 历史推进和反馈吸收

| 阶段/节点 | 产物与作用 | 判定与保留方式 |
| --- | --- | --- |
| 首轮C0/C1、C2研究 | 对配置/运输/交付/求助提出候选，留下未知项 | 保留来源；局部选择不足以管理整体，旧轮次停止充当进度刻度 |
| T0前置、T1卡 | 核查目标/权限/版本、精确授权对象 | 提高外部动作边界准确性，但单卡研究不能覆盖整个协作层 |
| Multica止损，6a672f4后进入代码 | 非done或缺可信输出源拒绝collect；description不再冒充结果 | 有效缺陷修复，当前代码仍保持；不代表Multica接入闭环 |
| T1-O协议试验，93416ef对应报告 | 一次MiniMax-M3文本终态、准确session/run、持久输出与独立算术；补充240字符超过原200标准 | 原协议证据有用；该超限事实保留；不是产品Adapter/Andon/取消证明 |
| 93416ef全面重规划 | 重新提出整体生成/协作契约、完整包与Owner | 值得吸收，仍混合设计/执行/证据，管理职责未完全拆开 |
| 7f7cee的C0整体稿 | 任务包、Q/node/outbox、多级返回、授权、指南和C1—C6出口 | 整体设计更完整；代码尚未实现时不能写能力已具备 |
| 7f7cee独立复核 | 发现details_ref/complete矛盾、200硬常量、成功事项分类、共享投影和逻辑去重边界 | 局部反馈已吸收或写入后续；不是专项全局验收 |
| be41fced工程 | C1 API/数据/Adapter/parser/补充/partial投影，相关测试和产品卡 | 有真实工程增量，仍无新远端产品卡与真实worker模型闭环 |
| 3c5ee33c合并 | C1与Dashboard D1在同分支，旧四处工程gate措辞已被D1提交修正 | 以合并后的源和检查为当前事实，不重复旧失败状态 |

### 原T1证据的边界

原记录显示无需取消，新增session/Agent活跃目录已清理，原生归档/废纸篓保留、非本卡配置指纹未变。本轮没有再次核这些远端对象和配置；它们是原时点证据。240字符不能追认原200卡为通过。当前任务协议预算可配是新的产品行为，不改变原试验结论。

## 3. 已实现工程清单

| 模块 | 当前源码可确认的实现 | 已确定限制 |
| --- | --- | --- |
| 个人连接 |本人CRUD、地址允许表、密文凭据、项目许可、CAS修改/禁用 | 仅OpenClaw Provider；尚无完整配置前端；部署配置是否就绪未核 |
| 精确目标 | 远端identity、修订、只读策略核验 | 依赖专属目标、固定版协议和scope，不能接管日常Agent |
| 持久attempt | 委派来源唯一、root/predecessor、项目/用户/连接/目标FK，输入hash、绑定/观察/正式来源/补充 | 多级后继链尚未实际验；源码v37不证明日常库迁移已执行 |
| 两类HTTP与根Run工具 | 共用DelegationService，正式工作入口接受目标，根工具重验worker lease | 实际worker模型执行未验；工具直接调用不等于完整模型链 |
| OpenClaw Adapter | 固定protocol4/2026.9.8；session/Run意图先持久；接受不明只核原Run；公开回读来源 | 真实产品入口未验；取消/原生恢复/附件/长报告不发布 |
| 协作protocol | 结构/字节/operation-attempt/工作context校验 | parser不能独立证明实际执行身份或业务正确性 |
| 正式交付与补充 | 正式Result pending和完整Workdir；补充摘要预算、inline详情hash/complete；notices；拒绝观察独立保存 | 远端整个JSON≤4096 UTF-16；格式失败不创建成功结果 |
| 共享投影 | 唯一collaboration.read/1 Schema，C1实际partial尝试/结果读取 | 生产问题链、真实宿主权限/动作及C5 UI未实现 |
| Multica | dispatch/status保留，collect未done拒绝，done缺正式来源仍拒绝 | 成功回收有意暂停，不能说整个渠道已可交付 |

## 4. 上一轮四项问题的当前结果

1. **details_ref/complete：已吸收进运行时Schema与parser。** 当前只接受受控inline文本，独立字节/指纹验证；不能扩称支持任意远端报告下载。本轮相关unit通过。
2. **摘要200常量：已调整。** 当次任务预算1—8192、默认200，保存超预算原文和不合规标志。原T1严格200标准未追认改变。
3. **非阻塞事项：已补notices。** 明确blocking=false，Result携带非阻塞说明；严重阻塞仍不成功，本轮相关unit通过。
4. **共享投影：已统一Schema与5组联合样例。** 当前C1生产partial投影已在，生产宿主/问题UI仍未接；不能把合成映射检查记为真实Andon联验。

逻辑问题去重在C1文档已明确 `(source_attempt_id,client_question_key)` 加独立receipt；尚无真实Q/revision实现，因此当前只是后续确定设计。处理Run排队、撤权、接替负控也仍待建设。

## 5. Andon 与授权逐项未交付

| 目标 | 当前状态 | 原资料价值 |
| --- | --- | --- |
| 下游模型实际看见版本任务规则 | C1任务渲染代码和模拟来源验证已在；真实产品入口未验 | 可复用任务包、实际input hash方案 |
| 稳定Q/revision/node与收件去重 | 未实现 | C0字段、逻辑key/receipt与CAS规则可用 |
| 直接上级真实读取资料并解答 | 未实现 | 受限处理Run、普通FIFO方案保留 |
| B→A→H逐级转交/返回 | 未实现 | 场景和11条合成事件是设计oracle |
| 持久outbox、送达/采用、崩溃接替 | 未实现 | action唯一键、匹配字段和故障矩阵可用 |
| blocked终态后准确新attempt | 有predecessor结构基础；业务处理/采用链未实现 | 模式区分和旧答案拒绝原则保留 |
| 原生question/wait恢复 | 未验证/未接入 | 不阻塞采用blocked-return设计，但不作能力声明 |
| Agent有限正式批准 | 未实现 | exact/集合/typed授权目标保留 |
| 问题时间线、收件箱真实义务、UI办理 | 未实现 | 读Schema/设计稿已具备，不是运行事实 |
| 第二真实Provider和独立接入者 | 未完成 | Multica环境/来源未知及文档基准继续保留 |

**当前系统已经有“准确文本交付工程”，完整协作机制和Andon仍主要是设计。** 这也是暂停盘点的核心事实，不能再用C0/C1轮次或大量测试总数弱化它。

## 6. 测试证据与本轮复核

### 本轮独立执行

| 检查 | 结果 | 范围 |
| --- | --- | --- |
| 当前commit/差异、API→service→Adapter→parser→model与结果链 | 已检查 | 确认工程装配和当前限制 |
| 工程契约gate | 通过 | 当前合并分支；旧4项措辞失败已修正 |
| 检查器unit | 70通过 | 静态检查器 |
| protocol/policy相关unit | 13通过，约6.37s | 固定Schema/正负例、摘要预算、详情指纹、非阻塞事项、投影、正文预算、策略与总超时 |
| pytest缓存告警 | cache目录权限不足 | 测试全部通过，未修改容器权限 |
| 首次标准uv测试命令 | 依赖镜像opentelemetry-sdk读取超时，未进入pytest | 不能把环境失败当产品回归失败或成功；没有继续修环境 |
| 已有环境替代命令 | `uv run --no-sync pytest ...`通过上述13项 | 不同步依赖，使用现有环境 |
| 新远端产品、真实HTTP/PG、实际worker/模型 | 本轮未执行 | 专项暂停；原证据另列 |
| 全量后端/前端、docs build | 本轮未重复 | 无仓库产品变更；只检查相关代码与outputs文档 |
| 新归档文档结构 | 7份Markdown链接、命名、围栏及任务映射检查通过 | 不证明运行时或产品能力 |

相关命令：`docker compose exec -T api uv run --no-sync pytest test/unit/delegation/test_collaboration_protocol.py test/unit/delegation/test_openclaw_policy.py -q`。

### 原C1作者记录（本轮未重新执行）

作者记录隔离真实HTTP/PG/Workdir加模拟公开WS最终16项通过，扩展FK负控1项，改动工作树完整unit2851/63跳过，策略/超时追加及单项HTTP复验；根Run工具属于直接调用，非实际worker模型执行。Gateway/输入/输出回执由模拟提供者证明装配，不能替代真实OpenClaw。

作者还记录一次隔离HTTP启动超时，未进入业务断言，单独重跑后通过；根因未证明。其全仓gate旧四项失败已经在本分支其他提交修正，历史报告仍反映执行时状态。当前13项unit与gate新结果不替代原HTTP/PG或远端产品验收。

## 7. 暂停后的唯一进度台账

| 保留工作目标 | 当前进展 | 状态 |
| --- | --- | --- |
| C1本地准确交付工程 | 代码已合并，有作者隔离集成和本轮13项unit | 暂停，工程成果保留 |
| C1-O-P1真实产品入口 | 已有整卡，未执行 | 暂停；原卡不自动授权 |
| C2直接上级 | 设计/候选Schema，有部分attempt基础 | 暂停，未实现 |
| C3多级返回与恢复 | 设计/合成因果场景 | 暂停，未实现 |
| C4个人正式授权 | 设计，typed类别待具体化 | 暂停，未实现 |
| C5协作详情和收件箱 | Schema/样例/原型，partial生产读取 | 暂停，完整产品未实现 |
| C6第二渠道与独立接入 | 文档/Multica止损，部署/真实来源缺证 | 暂停，未完成 |

没有“专项完成百分比”。新资料若只补源码事实或冻结说明，在此记录；新增实施和试验需要明确重启决定。

## 8. 管理评价与后续使用

前期有价值成果包括止损、公开协议事实、配置/目标分层、来源核验、错误观察、独立补充、唯一读Schema及C1工程。失败的管理表现是反复把局部卡和研究推进当专项进度，缺整体可用出口，文件混合职责，问题链/授权/接入扩展长期未落地。

本轮把需求设计、落地细节、事实进度分开，避免继续拿局部Adapter完成解释协作机制完成。恢复时先按DEV的重启前提核漂移和具体下一包，向用户提供完整目标、比较、推荐和代价；不要恢复无边界研究，也不要为了“参与感”先让用户选择没有解释的局部参数。

## 9. 交接和残余资源

- 原T1报告记录已清理专属活跃对象；本轮未独立回查远端、归档或当前日常配置。
- C1-O-P1从未执行，文档中的计划对象不能当实际残余；重启需重新确认不存在和无其他consumer。
- C1作者隔离schema/进程/临时Workdir的当前残余，本轮未查；记录为待只读盘点，不能猜已全清理。
- 源码已合并，不回滚/删除v37表；日常实际迁移版本、加密配置和Gateway握手本轮未核，重启时检查。
- 尚未独立证明整个任务接受不明/清理路径在真实Provider上成立，保留具体限制。

## 10. 源证据入口

- [C1工程与远端产品卡](<归档/2026-10-10-重整前/第一阶段专项/协作接入-C1工程验收与远端产品卡-2026-10-10.md>)
- [当前准确交付机制](<../mechanisms/collaborator-delivery.md>)
- [C0整体设计与原包](<归档/2026-10-10-重整前/第一阶段专项/协作接入-C0整体契约基线与C1-C6验收卡-2026-10-09.md>)
- [T1-O原协议试验报告](<归档/2026-10-10-重整前/第一阶段专项/两个专项初次任务执行/协作接入-C3T1O协议试验结果-2026-10-09.md>)
- [委派服务](https://github.com/Sxyon/Yuanlei/blob/3c5ee33c64f82fcb5214f29e7b7198730bdeed55/backend/package/yuxi/services/delegation_service.py)
- [OpenClaw Adapter](https://github.com/Sxyon/Yuanlei/blob/3c5ee33c64f82fcb5214f29e7b7198730bdeed55/backend/package/yuxi/delegation/openclaw.py)
- [协议parser](https://github.com/Sxyon/Yuanlei/blob/3c5ee33c64f82fcb5214f29e7b7198730bdeed55/backend/package/yuxi/delegation/protocol.py)
- [运行时Schema](https://github.com/Sxyon/Yuanlei/blob/3c5ee33c64f82fcb5214f29e7b7198730bdeed55/backend/package/yuxi/delegation/schemas/collaboration-read-v1.json)
- [Multica止损源码](https://github.com/Sxyon/Yuanlei/blob/3c5ee33c64f82fcb5214f29e7b7198730bdeed55/backend/package/yuxi/delegation/multica.py)
