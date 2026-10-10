# DEV-CA-001｜协作接入与 Andon 冻结落地细节

版本：1.0。设计见 [SYS-CA-001](SYS-CA-001-协作接入与Andon系统设计.md)，当前状态只在 [LOG-CA-001](LOG-CA-001-协作接入与Andon暂停盘点与事实进展.md)维护。本页记录可重建工程的落点、确定细节、保留限制与重启前提。**本页不安排当前执行，不恢复原试验授权。**

## 1. 当前工程装配

源码装配以[准确交付机制](../mechanisms/collaborator-delivery.md)及下表Owner为准；<a href="图解/04-collaboration/collaboration-target.html" target="_blank" rel="noopener">CA-G04</a>专门表示冻结目标，不能代替实际工程图。

本节描述已存在代码装配。公开RPC真实产品入口、实际worker模型链路以及部署状态的证据见LOG；Andon问题树不在此图中冒充已实现。

## 2. 当前Owner与修改位置

| Owner/路径 | 当前职责 | 重启时检查重点 |
| --- | --- | --- |
| `backend/server/routers/collaborator_router.py` | 本人连接/目标CRUD及只读核验 | 权限、CAS、密钥不可回显、禁用及许可撤销 |
| `backend/server/routers/delegation_router.py` | 通用委派、正式工作、回收、补充及尝试投影 | 两类入口一致、准确对象可见性、失败HTTP语义 |
| `backend/package/yuxi/services/collaborator_service.py` | 地址允许表、密文凭据、项目许可、目标策略与attempt解析 | 版本漂移、当前许可和远端副作用前lease |
| `backend/package/yuxi/repositories/collaborator_repository.py` | 持久连接/目标/attempt查询与锁 | 外键和归属不能绕过 |
| `backend/package/yuxi/services/delegation_service.py` | 委派intent、协议任务包、回收Owner、结果及补充 | 先持久后外发、重复/迟到、失败观察、准确来源 |
| `backend/package/yuxi/delegation/openclaw.py` | 固定Gateway运输、session/Run绑定与公开输出核对 | 实际版本/scope、来源完整性、短输出限制 |
| `backend/package/yuxi/delegation/protocol.py` 和 `schemas/` | 版本结构、字节、依据、摘要预算和详细报告核验 | 文档/Schema/fixtures一致、拒绝不改变正式事实 |
| `backend/package/yuxi/storage/postgres/models_business.py` / manager / migration | `yuanlei`v37新增模型及执行器约束 | 实际部署版本另核，不把源码版本当已迁移 |
| `backend/package/yuxi/services/project_work_result_service.py` | 原工作结果及验收 | notices可追溯，正式结果不被补充替换 |
| `backend/package/yuxi/delegation/multica.py` | 既有工作项接口及成功回收止损 | 未证来源不恢复成功collect |

## 3. 已确定的实现细节

### 3.1 配置与持久结构

个人连接只支持 OpenClaw，model数据库CHECK明确 `provider_key='openclaw'`；不能因此宣称已支持任意Provider配置。连接项目许可、目标及attempt通过复合FK保归属，许可撤销保留旧行供历史引用。

连接密文使用专属32字节密钥AES-GCM及绑定连接/uid的AAD；地址只能是部署者明确列举的ws/wss端点。当前配置项为 `YUANLEI_COLLABORATION_KEY`、`YUANLEI_OPENCLAW_ALLOWED_ENDPOINTS`。重启时只核配置是否符合要求，不输出其值或直接改日常配置。

连接/目标修改递增revision，目标核验失效。目标仅引用远端identity，不创建或接管日常Agent。当前还没有完整个人连接管理前端；工程API可用性与个人可操作配置界面需要分开评判。

### 3.2 准确下发与接受不明

派发冻结工作条件/context/目标/配置和模型；task包与实际rendered input hash落库。session key、run id、idempotency均由attempt派生；外发前保存create/dispatch标记。创建回执丢失不重复创建，运行接受不明不再发第二次agent调用，只核准确原Run。

当前Gateway固定协议4和2026.9.8，call总超时35秒。真实派发参数包含 `deliver=false`、`disableMessageTool=true`、`timeout=60`；目标须空fallback/skills、关闭memory search、deny-all，且session库存实际核验为live-session全部excluded。版本/scope漂移拒绝，不升级或降级其他目标。

这些参数是源码细节，不能证明日常Gateway已具备该公开协议或计量有硬预算。目标核验和调用间缺少已证原子远端锁，需要专属目标冻结。

### 3.3 准确交付与输出限制

回收核对准确session/run/turn、visible终态、空successfulToolNames、未reroute、请求/实际模型一致；公开history完整且唯一当前输入/assistant，输入hash准确；持久正文与terminalReply相同、stopReason为stop。

整个返回文本超过4096 UTF-16单位被拒，这是当前Adapter明确限制。正式文本另有128KiB/100000字符上限，但前者的大预算不能绕过提供者4096整包限制。当前不接受未经验证的artifact refs，不能承诺附件或长报告。

### 3.4 补充、事项与失败观察

当前 `details_ref` 实现为inline-text及size_bytes/sha256，parser独立核对；不是任意URL或外部文件下载。`complete`仅说明补充完整性。摘要任务预算可配1—8192 code point，默认200；超摘要预算保存原文、预算、不合规和摘录，不丢正式交付。

非阻塞notices明确 `blocking=false`，正式结果携带“非阻塞”说明。准确来源已证但JSON/交付被拒的有界输出进入attempt.observed_output；blocked并不产生成功Result/Workdir artifact，也尚不自动创建Andon问题。

### 3.5 只读投影与界面接入

唯一Schema为 `collaboration.read/1`，C1代码有accurate attempt/result、supplement_count及pending结果人类核对义务；question/handler/answer_recipient为空，delivery/adoption为none，blocker=unknown，completeness=partial。

联合样例覆盖未来内部处理/本人待办/已送未采用/恢复失败/后继替代，原型有动作匹配检查。当前不能用样例生成真实问题处理按钮；生产宿主权限、问题详情和返回链尚未实现。

## 4. 保留的选择与尚需验证项

| 选择 | 保留理由 | 限制或恢复时要证明 |
| --- | --- | --- |
| Gateway固定版首接 | 原T1协议证据及当前实现可复用 | 真实产品入口尚未验，版本漂移必须重新判断 |
| 每attempt独立委派来源 | 保留现有结果唯一性与历史 | 后继多级链和root聚合实际未验 |
| blocked-return优先 | 不依赖每个平台原生wait | 上级真实处理和新attempt采用未实现 |
| 受限处理Run | 避免任意递归及父Run依赖 | FIFO排队、撤权、父Run结束接替需真实worker验证 |
| 元垒持久Q/node/outbox | 能逐级回溯和重启重投 | 当前仍是设计，不能当已有表/worker |
| exact→有限集合→typed新草案 | 保留用户授权Agent批准部分变更目标 | 真实治理授权消费和typed首类未实现 |
| Multica止损 | 缺可信结果来源不能物化描述 | 部署隔离、任务族与准确输出源未证 |

## 5. 原任务保留位置及重启顺序

原C1—C6保留为目标映射，依赖见<a href="图解/07-collaboration-tasks/collaboration-frozen-tasks.html" target="_blank" rel="noopener">CA-G07冻结后继任务图</a>，不安排当前日期和自动继续：

1. **准确产品交付：** 先核当前实现、schema/部署/依赖/协议漂移和已知限制；再决定是否执行新的C1产品卡，不重复T1基础文本探针。
2. **直接上级：** Q/revision/node/outbox、跨消息逻辑去重、上级普通Request/FIFO处理、终态blocked后显式后继采用。
3. **多级返回：** B→A→H→A→B→C、转译、旧答案、崩溃、接替、准确action匹配；收到/采用/恢复分别证。
4. **个人正式授权：** 具体一次、有限集合、真实需要的typed类别；副作用边界机械核对与同事务消费。
5. **产品办理与投影：** 问题/补充/尝试/结果详情、收件箱义务、时间线和Dashboard导航；实际服务产出的状态进入UI。
6. **第二Provider与接入文档：** C6a基础准确交付可在C1后验证，不等待整个Andon；C6b完整接入指南联验需要第二渠道与C3/C5真实处理链。 Multica隔离证据后真实任务族/输出/支持的求助方式；独立接入者按指南实现受控样例。

暂停不把这些任务移出原目标，也不在Dashboard会话悄悄建设它们。

## 6. 重启门槛与最小准备材料

用户明确重启后，先提交一份针对当前条件的短准备材料：

- 当前commit与v37或后续迁移状态；和冻结节点的代码差异。
- 实际Provider版本/协议/scope、目标策略、专属资源及地址许可是否漂移。
- 本地相关unit/HTTP/PG/Workdir与worker证据；原已通过项只在条件不变时复用。
- 下一包准确目标、真实消费者、功能边界、退出门槛；要写外部对象时给整卡目标/计量/停止/清理范围。
- 前次临时对象/凭据/进程残余事实；未知列出核查，不猜已清理。
- 推荐继续/缩减/调整的具体方案、代价和原因，避免让用户先猜远端ID或选无对比的技术细节。

原C1-O-P1卡日期、Agent名、session计划和绑定附件必须重新核对；暂停不授予其执行。未明确重启前不做安装、升级、远端写动作、付费运行或正式批准。

## 7. 冻结期间维护规则

保留源码、Schema、fixtures、原Decision及去敏证据；不回滚合并、不删除迁移表、不扩大当前能力声明。日常用户主动使用已有功能沿当前权限执行，本专项不会自动新增任务。

若发现影响现有系统的具体故障或敏感数据问题，记录并提出边界明确的独立修复任务；取得相应任务范围后再修复，不借维修恢复整项推进。文档或版本更新引发旧证据过期时在LOG标记，不替换旧历史事实。
