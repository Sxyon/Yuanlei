# OpenClaw 准确文本委派与结果导入

状态：proposed
类型：feature
Owner：backend/package/yuxi/delegation/contracts.py

开包顺序与整体范围由[协作与 Andon 整体提案](2026-10-09-collaboration-andon-baseline.md)部分取代：先审阅 C0，再将本文准确文本边界并入 C1。本文不再作为独立立即开包建议；T1 证据继续有效。

## 问题

[T1-O 实际试验](../../../../元垒系统架构规划设计/第一阶段专项/两个专项初次任务执行/协作接入-C3T1O协议试验结果-2026-10-09.md) 已取得准确 session/run 的持久文本、终态和同消息补充。现有元垒注册、委派与 Result Owner 尚无 OpenClaw Adapter；现有句柄不能完整恢复远端 Agent、sessionKey 和生命周期修订。外部协议成功不能直接登记为产品接入完成。

## 提案

增加 Gateway 原生文本执行器，复用 DelegatedExecutor、DelegationService、channel_delegation repository 与 import_execution_result。运行阶段仅引用显式配置的远端专属目标；不自动改远端长期配置，不建设连接中心、通用框架或完整 Andon。

operation 拥有输入及持久映射；Adapter 拥有真实远端创建、运行、观察和来源校验；DelegationService 保留 owner/lease、可信回收事务与 Workdir 边界；Result Owner 拥有待验收版本和 source 唯一性。按实际消费者评估现有 request_json/result_json 与句柄的最小扩充；需要持久新结构时仅进 yuanlei schema。正式文本、可选补充、公共来源及原始 usage 分开保存；不得把 summary 默认为补充，也不得把本地文本文件标成远端产物。

以准确 terminalReceipt、持久 assistant 消息和 session/run 映射闭合成功回收。accepted 或等待超时不能形成成功；来源不符、非终态、静默/空输出、模型错误和截断输出拒绝导入。接受响应不明时保留待核对，不自动制造第二次调用；重启/幂等证明完成前不承诺 exactly-once。业务验收继续由本地 Result Owner 办理。

## 替代方案

受控 CLI 可复用既有命令操作，但会增加进程/输出解析与取消边界，本轮证据来自 Gateway，先实现 CLI 需要另补运行试验。仅拿 terminalReply 导入会弱化持久消息来源验证；扫描私有 transcript 会承担非公共协议耦合；独立结果表和通用连接框架会重复既有 Owner，均不推荐作为首包。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
| --- | --- | --- | --- | --- | --- |
| 准确当次文本 | 相邻 Run、delta 或输入冒充交付 | Gateway Adapter collect | T1-O 原生回读；后续产品入口隔离 E2E | wrong-run/session/agent、缺消息、非终态、静默、错误/截断 | Not run |
| 持久映射与恢复观察 | 请求中断后失去准确归属或重发 | delegation repository / dispatch | 真实 PG 新事务回读；接受响应丢失、服务重启试验 | 身份缺失/修订改变时拒绝；不重发新尝试 | Not run |
| 结果与业务验收分开 | 回收直接接受或覆盖历史 | Result Owner | 真实 PG/Workdir 与产品直接入口 | 并发 owner、重复 collect、原结果保持 | Not run |
| 补充来自同一次 | 混入别次结果或越限冒充通过 | Adapter / result persistence | T1-O 同消息 supplement；后续持久回读 | 错 Run、缺补充、超过明确字符上限 | Not run |
| 权限与配置隔离 | 管理身份下发模型、改日常配置 | wire / executor boundary | T1-O prospective deny-all 与 no-successful-tools 回执 | 直接工具入口、逐 RPC 最小 scope 及配置错目标 | Not run |

矩阵结果对应尚未实现的产品增量。T1-O 已证明的协议样本和未通过的严格补充长度由试验报告单独登记，不能填作产品验收通过。

## 风险

本轮没有证明准确取消、timeout 强制截止、内部失败重试、重启、并发、原运行续接或远端文件交付；Adapter 首包只开放已验证且有实际消费者的文本能力。后台失败必须保留可观察入口，不能通过修改本地状态宣称远端停止或恢复。

保留后续逐级答复匹配、答案采用/解除阻塞/任务完成分离、明确新尝试恢复和个人有限授权目标；先验证具体草案，继而验证授权范围内的新草案与撤权/过期/旧版本拒绝。正式业务批准及组织权限系统不在首包范围。
