# 项目主题的可信多页运行时

状态：S03—S06工程已接入；2026-10-18按用户要求阶段暂停。正式A／B启动迁移证据、人工验收及验收后全量未完成，当前状态由[专项LOG](../../../元垒系统架构规划设计/LOG-DB-001-Dashboard进度基线与执行记录.md)拥有。
类型：新增能力
主要 Owner：[全项目主题决策](../decisions/proposed/2026-10-14-full-project-theme.md)

## 需求与失败场景

项目需要以日常管理、精简观察、课题调研等不同方式组织全部页面、详情、编辑和办理，同时保留原业务身份、状态、权限与历史。只替换概览或导航会遗漏项目作用域；各主题复制业务代码会分叉授权与状态；上传页面自由执行脚本及请求会突破数据边界。

主题采用受控JSON定义与平台可信Vue能力组合。当前三套组织和ABI3有限呈现共用同一宿主；自定义主题缺失能力在同一壳内继承基础版本。用户制作和字段说明分别见[使用指南](../../../intro/project-theme-authoring.md)与[配置参考](../../../advanced/project-theme-reference.md)，稳定产品范围见[主题设计](../../../元垒系统架构规划设计/SYS-DB-001-Dashboard系统需求与架构设计.md)。

## 必须保留的业务语义

- 主题改变组织、有限布局及平台词汇，业务对象ID、DTO、用户正文、历史、状态和最终授权由原Owner执行。正式任务来源决定ID与冻结修订成对，当前决定不替换执行当次依据。
- 包仅声明可信能力、有限布局、逻辑业务引用、文件alias和声明素材；不授予用户／Project权限，不携任意脚本、SFC、SQL、请求URL或宿主路径。未知依赖、组件及非法资源明确拒绝。
- 草稿、不可变发布版、唯一Project绑定分别拥有事实；保存或发布不自动应用，选择以generation拒绝旧写，共用Workdir不共享主题选择。来源停用保留旧加载，安全撤回拒绝加载并保存原因，故障保留原绑定及显式恢复入口。
- 宿主按当前用户、Project、准确包、generation和页面选择隔离异步结果，切换保护未保存输入，准确对象再次核对归属；返回使用宿主保存的原页、查询、滚动和焦点。
- 完整能力及混合主题预览复用有权Project的真实宿主，绑定准确version或候选revision，临时文件映射不写持久选择。正文inert只读，后端继续最终授权；历史纯区块预览明确使用合成适配。
- Project文件由目标alias映射经原Workdir no-follow边界读取，实际JSON／PNG与包内素材分别校验。alias为项目级，文件是实时字节，不能暗示逐议题附件或固定文件快照。
- 导出读取准确授权已发布版本的原ZIP；导入只读预检，确认重传核SHA后保存目标草稿，发布与应用分别确认。目标身份、业务行、凭据、路径／映射及generation留在目标环境；作者自行写入包素材的内容随原字节携带。

## 与 Yuxi 的边界

AppLayout拥有平台外壳，ProjectLayout拥有项目主题、导航、有限能力继承、预览及草稿作用域。可信能力组件直接消费原治理、工作、结果、资料、智能体和设置Owner；旧URL解析到新能力，静态HTML Dashboard继续保持无脚本隔离。

## 稳定集成点

Pydantic主题契约及包parser拥有定义、ZIP和媒体校验，生成Schema供前端边界使用。ProjectThemeService拥有来源／Project授权、来源→Project锁顺序、文件及PG提交；ProjectThemeRepository拥有持久查询和可见性；ThemeStore拥有原ZIP的无覆盖持久化、摘要和no-follow。yuanlei域保存来源／版本／Project绑定／维护事件，业务及knowledge域继续归上游。

## 上游依赖

依赖Project可见性、原业务DTO及状态用例、Conversation／Run身份、Vue外壳、明暗token与Workdir安全原语。

## 合并判断

上游重构时允许迁移实现位置，需保留完整项目作用域、准确来源版本、冻结依据、旧链接、可信返回、草稿保护和目标文件授权。

上游提供等价主题后，比较能力组合、来源／版本、持久选择、不可变字节、恢复和授权语义，再采用或缩小差异。

## 替换或删除条件

已有用户包和绑定需要明确迁移路径；需求结束后才按消费者及数据承诺删除。自由脚本renderer不能直接替代当前受控边界。

## 决策与证据

| 取舍 | 决策 |
| --- | --- |
| 可信组件、受控包与原业务Owner | [实施路线](../decisions/proposed/2026-10-12-project-theme-implementation.md)、[全项目覆盖](../decisions/proposed/2026-10-14-full-project-theme.md) |
| 不可变存储及业务／文件消费 | [存储](../decisions/implemented/2026-10-13-project-theme-storage.md)、[真实数据](../decisions/implemented/2026-10-13-project-theme-live-data.md) |
| 双入口、三套组织及真实预览 | [切换恢复](../decisions/implemented/2026-10-16-project-theme-switch.md)、[内置样例](../decisions/implemented/2026-10-16-project-theme-samples.md)、[预览一致性](../decisions/implemented/2026-10-16-project-theme-preview-parity.md) |
| 制作、词汇／资料及迁移恢复 | [制作反馈](../decisions/implemented/2026-10-16-theme-authoring-feedback.md)、[真实消费](../decisions/implemented/2026-10-17-theme-evidence-consumption.md)、[原包迁移](../decisions/implemented/2026-10-17-theme-portability-closeout.md) |

[专项LOG](../../../元垒系统架构规划设计/LOG-DB-001-Dashboard进度基线与执行记录.md)集中当前阶段确认与证据入口；测试分别覆盖纯契约、实际宿主、第三份定义、真实HTTP／PG、文件字节和DOM，不用模拟或HTTP状态替代最终事实。S06现有证据app省略正式startup且无schema版本登记，不能证明正式migrator／ready；分段补验不改记主迁移脚本一次整链通过。

多实例、Agent生成维护工具及有限自动发布授权、更多格式／素材、团队权限与第三方平台适配仍待按真实需求细化，边界见[维护与接续](../../../元垒系统架构规划设计/DEV-DB-002-项目主题实施指南.md)。当前工程实现和相关检查不补记人工验收或最终结项。

契约Owner：`backend/package/yuxi/services/project_theme_contract.py`；原ZIP与HTTP／PG回归：`backend/test/integration/api/test_project_themes_api.py`；宿主与制作交互回归：`web/test/unit/projectThemeDraft.test.js`及相关主题用例。
