# 个人协作者的准确文本交付

本文面向接入开发者与维护者，解释C1本地工程边界。前置知识是[编码执行](coding-execution.md)和[配置系统](../advanced/configuration.md)。真实OpenClaw产品入口验收另需整卡授权；短文本T1只证明当时的协议调用。

## 连接、目标与执行快照

个人连接保存提供者、允许地址、密文凭据及项目许可；目标引用远端Agent身份与只读核验。C1仅为OpenClaw增加个人连接，Multica仍使用既有实例配置，成功回收保持止损拒绝。每次委派沿用正式工作的资料/条件修订，生成一个准确attempt和版本任务包。连接/目标修改递增revision并使旧核验失效，撤销项目许可保留历史外键行。

## 派发与来源Owner

通用HTTP、正式工作HTTP和根Run工具使用同一委派服务。项目和工作归属先由数据库重验，根Run工具还重验真实worker lease。任务包包含目标、资料指纹、条件修订、预算、delivery-only规则及缺授权处理；当前没有可调用求助/答复工具，受阻返回结构化材料，由直接委派者人工办理。

PG提交委派intent和创建session标记后调用 `sessions.create`；回执须给出准确sessionId和生命周期版本。派发前重读Agent、模型、空fallback/skills、关闭记忆及工具库存；持久保存唯一runId和调用标记后执行 `agent`。接受回执与目标/session/Run绑定。回执丢失时新的恢复Owner仅 `agent.wait` 核对原Run，不再发第二次模型动作；未知创建不自动重建session。

## 正式交付与独立补充

回收同时核对成功终态、session/Run/turn、明确空成功工具数组、模型快照、公开历史中当次输入指纹及唯一assistant来源。历史读取显式指定session、字符和字节预算；分页或截断来源不形成结果。OpenClaw安装版终态文本最多4096 UTF-16单位，任务约定整个返回JSON在此范围内，正式正文与补充共同计入；受控详细报告也须遵守此提供者预算。

协作协议Schema由 `backend/package/yuxi/delegation/schemas/` 拥有。补充 `details_ref` 支持内联文本、字节数和SHA-256，`complete` 只表示报告完整性。摘要默认200 code point、当次可约定1—8192；超预算保存原文、预算与不合规事实，正式交付保持独立。非阻塞 `notices` 必须 `blocking=false`，保存在来源材料并在Result.unresolved标明非阻塞。真实阻塞、附件未验、来源错配、非法详细报告均不能形成成功Result/artifact。

成功输出在同一Owner事务生成唯一pending Result及Workdir产物，业务验收继续由原Result用例办理。准确来源已证而结构/交付失败的有界原文存入attempt观察；来源未证的材料不伪称已核验。补充/观察按准确operation单独读取。重复回收保留既有幂等结果；旧Owner不能写新Owner的事实或释放其租约。

## 权限、失败与历史

连接仅本人可见；目标/项目/连接/尝试关系由数据库约束拒绝串线。真实远端副作用前校验当前许可、版本与有效租约；远端核验到调用之间缺少已证明原子配置锁，专属目标必须冻结。配置变更后旧尝试的远端读操作会拒绝，已保存本地证据继续可读。凭据缺失/允许地址缺失以明确错误失败，不降级到其他Agent。

唯一 `collaboration.read/1` 读投影区分处理者、接收方、等待执行者与人的义务，C1实际返回partial及准确Result动作。问题链、答复送达、采用和恢复尚未实现；Dashboard联合样例只证明候选对象导航及return token匹配，不伪造这些运行事实。C2—C6继续沿整体基线推进，有限授权保留授权内新草案目标。

## 接入开发者与验证

1. 读取运行时Schema和固定正负例，明确提供者真实输出/恢复上限。
2. 在现有入口和委派Owner复用目标核验、资料快照和intent提交；平台注册存在不代表实际安装版支持。
3. 实现公开运输回执及准确读回，不扫描私有transcript，不复制Run事实。
4. 在隔离真实HTTP/PG/Workdir验证错来源、撤权、漂移、未终态、晚Owner、回执丢失及重复回收。
5. 通过独立Review后按具体整卡验证真实产品入口；各提供者只发布已证明能力。

源码Owner为 `DelegationService`、`CollaboratorService`、`OpenClawExecutor`、`CollaboratorRepository` 与原Result服务；直接证据见 `test_openclaw_delivery.py`、`test_collaboration_protocol.py` 及[C1工程验收与远端卡](../元垒系统架构规划设计/归档/2026-10-10-重整前/第一阶段专项/协作接入-C1工程验收与远端产品卡-2026-10-10.md)。
