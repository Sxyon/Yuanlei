# DEV-CA-001｜协作接入与Andon接续约束

当前专项暂停。本页保留维护和恢复时需要的工程边界；目标见[SYS](SYS-CA-001-协作接入与Andon系统设计.md)，实际结果见[LOG](LOG-CA-001-协作接入与Andon暂停盘点与事实进展.md)。当前装配由[准确交付机制](../mechanisms/collaborator-delivery.md)、源码和Schema拥有。

## 已有Owner与限制

协作者router负责本人连接／目标的CRUD和只读核验；CollaboratorService负责地址、密文凭据、项目许可、目标策略；CollaboratorRepository负责归属查询和锁。DelegationService拥有委派意图、冻结协议包、外发、回收及结果／补充；OpenClaw Adapter拥有固定Gateway运输与公开来源核对，原Result服务拥有业务验收。精确文件定位见[机制页](../mechanisms/collaborator-delivery.md)。

个人连接当前仅OpenClaw。凭据以专属32字节密钥AES-GCM加密并绑定连接／uid，部署使用`YUANLEI_COLLABORATION_KEY`和`YUANLEI_OPENCLAW_ALLOWED_ENDPOINTS`，允许ws／wss地址由部署者列举。连接／目标revision变动使核验失效，项目许可撤销保留历史引用。源码yuanlei v37为原增量起点，实际部署版本需独立读取。

Adapter固定protocol 4／2026.9.8、总超时35秒；派发含`deliver=false`、`disableMessageTool=true`及`timeout=60`。目标核验要求空fallback／skills、关闭memory search、deny-all及live-session全部excluded。版本或scope漂移拒绝；核验与远端调用之间未证明原子冻结，因此需要专属目标。真实远端产品链路和完整个人连接管理前端尚未验证交付。

## 必须保留的执行语义

派发先持久化operation／attempt、工作条件、Context Pack、目标／配置／模型、实际渲染输入指纹和外发意图。session／run／idempotency从attempt派生；创建或运行接受不明只核原对象，不再创建或第二次调用模型。

回收核对准确session／run／turn、可见终态、无成功工具调用和reroute、模型一致、完整唯一公开history、输入hash、持久正文与terminalReply相等及stopReason=stop。整个返回文本4096 UTF-16单位是当前提供者限制；协议正式文本较大预算不扩大此能力。附件引用及长报告尚未证明。

`details_ref`仅为inline-text与字节／SHA校验。补充摘要预算1—8192 code point，默认200；超预算保存原文、不合规及摘录，合格正式结果独立判断。notices为`blocking=false`。准确来源已证但结构拒绝的有界输出保存为observed_output，不创建成功Result／artifact，也未自动产生Andon问题。

`collaboration.read/1`当前生产投影只有attempt、result、supplement和pending结果人工核对，question／handler／answer_recipient为空；delivery／adoption为none、blocker unknown、completeness partial。未来合成样例不产生真实问题按钮。Multica非done或缺准确可信输出时拒绝成功collect。

## 恢复顺序与进入条件

用户明确恢复后，先只读核当前commit、Schema、Provider版本／协议／scope、目标许可、配置和冻结节点的差异；盘点专属对象、临时进程和凭据残余。原远端卡的日期、目标、额度和清理范围必须重核，旧授权不可重复消费。

1. 先证明当前产品准确交付，从真实HTTP、PG、Workdir及worker／模型正常入口闭合。整卡明确外部对象、计量、停止和清理范围。
2. 再建设直接上级处理：稳定Q／revision／node／outbox、逻辑问题与receipt去重、普通Request／FIFO、blocked终态后的明确后继尝试。
3. 多级返回证明B→A→H→A→B→C、转译、旧答案拒绝、崩溃接替及准确action匹配；送达、采用、恢复分别取证。
4. 个人有限正式批准按一次、有限集合、真实typed类别递进，治理Owner机械校验并同事务消费。
5. 产品详情、收件箱与时间线消费真实问题义务、补充及准确结果；本人待办按当前人类义务去重。
6. 第二Provider的基础交付可在首个产品链路后独立验证；完整指南需第二渠道及真实处理链，供独立接入者按文档实施。

暂停期间保留代码、迁移、fixtures和决策；没有当前任务时不做安装、升级、外部写试验、付费运行或正式批准。现有具体故障按明确独立修复范围处理。
