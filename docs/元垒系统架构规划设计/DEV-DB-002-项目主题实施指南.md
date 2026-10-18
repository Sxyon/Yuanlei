# DEV-DB-002｜项目主题维护与接续

本页供维护者定位实现、处理恢复和准备后续补验。需求见[SYS](SYS-DB-001-Dashboard系统需求与架构设计.md)，暂停及实际证据见[LOG](LOG-DB-001-Dashboard进度基线与执行记录.md)。本页中的补验顺序在专项恢复后使用；当前没有自动领取任务。

## 实现与事实Owner

| 边界 | Owner与职责 |
| --- | --- |
| 协议与输入 | [Pydantic契约](https://github.com/Sxyon/Yuanlei/blob/main/backend/package/yuxi/services/project_theme_contract.py)与[包parser](https://github.com/Sxyon/Yuanlei/blob/main/backend/package/yuxi/themes/packages.py)拥有定义、ZIP成员、依赖、实际媒体及预算；生成Schema供前端边界使用 |
| HTTP与用例 | [主题router](https://github.com/Sxyon/Yuanlei/blob/main/backend/server/routers/project_theme_router.py)负责认证、有界输入及错误装配；[ProjectThemeService](https://github.com/Sxyon/Yuanlei/blob/main/backend/package/yuxi/services/project_theme_service.py)拥有来源／Project授权、锁、文件与数据库提交顺序 |
| 持久查询与文件 | [主题repository](https://github.com/Sxyon/Yuanlei/blob/main/backend/package/yuxi/repositories/project_theme_repository.py)保存来源、版本、唯一Project绑定及维护事件；[ThemeStore](https://github.com/Sxyon/Yuanlei/blob/main/backend/package/yuxi/themes/store.py)拥有原ZIP的no-follow、原子无覆盖写入和摘要回读 |
| 制作与应用 | [ProjectThemeManager](https://github.com/Sxyon/Yuanlei/blob/main/web/src/components/project/ProjectThemeManager.vue)与[ProjectThemeSelection](https://github.com/Sxyon/Yuanlei/blob/main/web/src/components/project/ProjectThemeSelection.vue)通过统一API维护草稿、预览、版本与分配；平台与项目入口共用绑定 |
| 项目宿主 | [AppLayout](https://github.com/Sxyon/Yuanlei/blob/main/web/src/layouts/AppLayout.vue)与[ProjectLayout](https://github.com/Sxyon/Yuanlei/blob/main/web/src/layouts/ProjectLayout.vue)统一导航、作用域、草稿离开、真实预览和故障；[能力映射](https://github.com/Sxyon/Yuanlei/blob/main/web/src/components/project/themes/workspaceCapabilities.js)拥有继承及准确路由 |
| 业务与资料 | 原治理／工作等API拥有业务结果；主题文件用例在Project授权后复用Workdir。ThemeHost消费受控区块，真实能力页消费原业务组件 |

部署拓扑与主题卷以[Compose](https://github.com/Sxyon/Yuanlei/blob/main/docker-compose.yml)为准，新增元垒结构只进yuanlei域并经storage-migrator。运行事实以源码为准，本页不维护第二份字段或限额清单。

## 必须沿用的工程约束

来源锁先于Project锁；草稿以expectedRevision拒绝并发旧写，Project选择以expectedGeneration拒绝旧绑定。完整ZIP先安全持久，再登记PG引用；PG失败可能留下未引用完整包，维护时按真实引用核对。

发布只消费已保存修订，同来源同版本同字节可复用，异字节冲突拒绝。版本引用与不可变原包成对，绑定以Project主键拥有；共享Workdir不会共享主题选择。停用和安全撤回分别处理，故障不隐式写默认绑定。

预检不落库，确认导入重新解析实际字节并核SHA。结果恢复按最终新建／既有模式核对准确身份、名称、归属、修订及摘要；提交后候选又变化时显式待核实，保留输入和准确目标，不能混合本次摘要与相邻修订。当前四类恢复修复及证据见LOG。

用户、Project、准确版本／候选修订、digest和generation共同限定异步结果。实际编辑Owner登记未保存字段，切换／预览前统一保护；关闭浮层、页面缓存和失权清理都遵循当前作用域。只读inert负责产品体验，服务端权限负责授权。

Project文件alias固定表示项目级资料；目标映射留在绑定或临时预览意图。包内资源按准确包引用读取，JSON／PNG均核实际字节和类型。缺少映射或坏文件明确显示原因；预览失败不能补合成数据。

## 维护与恢复

使用者从[主题制作指南](../intro/project-theme-authoring.md)完成复制、编辑、预览、发布、应用及导入导出。维护者按以下边界处理异常：

| 情况 | 操作与可观察结果 |
| --- | --- |
| 草稿409 | 重新读取准确候选，保留本地输入供比较；已发布版和项目绑定保持 |
| 新来源身份已建但草稿缺失 | 核实准确来源后向同一身份上传完整ZIP；避免重复创建 |
| 导入保存结果不明 | 回读目标修订及摘要，唯一准确结果才定位；候选被另一窗口修改时保留文件／预检并解释变化 |
| 发布同版本异字节 | 修改草稿版本标识，重新保存校验后发布；历史版本继续保留 |
| 包缺失、损坏或来源撤回 | 展示故障和可信基础界面，从平台项目主题设置显式选择有权旧版；不覆盖原绑定来掩盖故障 |
| 存储残留 | 检查引用与字节，清理单独确认，并在来源锁内重核；引用包与不安全目录项不能删除 |
| 部署恢复 | PostgreSQL与主题文件域取同一恢复点，恢复后核对来源、版本、绑定、原ZIP摘要和文件映射；主题切回不恢复业务行及Workdir字节 |

## 恢复专项后的验证顺序

先确认新任务范围与当前代码、环境和用户反馈，再处理[LOG的未验项](LOG-DB-001-Dashboard进度基线与执行记录.md)。正式A／B部署需独立数据库、主题根、身份与Workdir，运行正式migrator和应用startup，证明schema兼容及ready；现有简化证据app只证明主题链路。

随后用准确发布原包走A→B草稿→目标真实预览→发布→应用→业务办理返回→刷新／重启→显式切回，同时读PG、ZIP和DOM，证明A与B对照项目保持。主脚本失败后补验各段要分别报告；旧回执不能替代新结果。

相关检查优先覆盖契约、实际HTTP／PG和真实页面。前端聚焦用例为`projectThemeDraft`、`projectThemePreview`、`projectThemeSwitch`、`projectThemeSamples`；后端主题契约／包unit及`test_project_themes_api.py`覆盖授权、原包、预检零写、旧修订、文件和恢复负例。迁移与恢复脚本位于`backend/test/e2e/project_theme_*`，其入口、前置数据和输出依赖需按当前源码重核，旧固定同名样本不可盲用。

人工代表路径：项目→主题管理→准确版本导出→预检取消→确认保存草稿（仍可再次导入）→有权目标Project和alias预览（旧选择保持）→发布（项目仍旧版）→分配→显式切回。冲突时观察解释、输入保留和核实入口；人工无需制造数据库故障。反馈修正并明确验收后，按当轮执行者约定做全量，命令由[测试规范](../develop-guides/testing-guidelines.md)拥有。

## 保留的后继需求

主题多实例、升级时缺字段沿稳定旧版、引用版本与历史保留，仍是待细化需求；当前唯一Project绑定不宣称已经具备多实例管理。更多格式、模板素材库和跨平台运行需真实消费者与兼容证据。

Agent制作与自动维护另行设计：默认人工模式，首次启用由本人明确确认；本人可显式授权固定模板、准确素材版本及槽字段范围内有限自动维护。自由组合自动启用需额外具体授权，布局维护权限与生成业务数据的采纳权限分别确认。超界只留草稿，过期／撤权／旧修订拒绝，当前稳定版保留。工具、授权消费和自动启用均属于未交付后继能力，当前页面按钮不授予这些权限。
