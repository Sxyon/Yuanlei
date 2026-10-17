# 真实主题词汇与项目证据的统一消费

状态：implemented
类型：feature
Owner：web/src/layouts/ProjectLayout.vue
关联 Feature：[项目主题](../../features/project-themes.md)

## 问题

上游业务组件拥有议题、决定、讨论与正式工作。主题的显示词汇仅在旧区块宿主消费，真实办理仍固定写“议题”；当前能力主题没有项目文件消费者。全能力真实预览遇到附加资料页会退回合成适配，无法证明应用前后的数据一致。分段方向来自[切换与消费修复提案](../proposed/2026-10-15-project-theme-switch-repair.md)，实施范围由SYS15与DEV12.3拥有。

## 决策

真实业务组件通过有限共享词汇消费当前主题的topicLabel。调用者只传开发者提供的标签、提示或事件类型文案，业务标题、正文、讨论、原因和历史快照保持原文。导航及总览使用同一词汇；主题不改变业务类型、权限、状态或revision。

baseVersion 1且含可信能力页的混合定义复用ProjectLayout真实预览。附加区块页由ProjectThemePanel消费临时准确包及同一真实适配器，ThemeHost以workspacePageId定位该页，主导航和跨页动作由项目路由拥有；嵌入页拒绝未知／能力ID，旧返回仅恢复当前资料页，避免从内层进入合成CapabilityPreview。纯区块历史包保留明确合成的原预览。

预览文件读取使用只读POST `/api/projects/{project_id}/theme/preview-file`。请求携准确version或source＋revision、当前generation、临时files映射及alias。服务按来源→Project锁顺序重新授权和核对引用，复用Workdir no-follow、大小及实际JSON／PNG解码；返回同一字节的长度与SHA-256。临时映射不写binding，选择器用另页预览保留原输入。已应用版本继续使用原alias＋generation文件读取API。预览资产使用准确包引用，禁止误读当前绑定的资产。

资料页复用既有reading／full布局与JSON／PNG可信块，说明项目级文件或包内素材，指纹按需展开。派生新版本通过原复制、编辑、保存校验及发布服务形成，不修改已发布ZIP。没有新ABI、数据库表、选择机制、脚本或自由布局协议。

## 替代方案

只替换旧ThemeHost标签无法改变真实办理。逐主题复制页面会复制业务状态与草稿处理。先应用再预览会改变持久选择；将混合页继续降为合成数据会失去一致性证据。复用真实宿主并增加窄只读文件用例，代价是预览必须有权访问目标项目及明确映射，文件变动需重新读取。

## 后果

Project alias固定表示项目级资料，不是逐课题附件。包定义只携alias和媒体类型；路径、Project、generation及临时预览映射属于目标环境，不进入可携ZIP。包内assets成员及hash可以随包携带；业务数据、账号、权限及可信Vue组件实现不可携带。完整依赖和文件预算由[DEV12.3](../../../../元垒系统架构规划设计/DEV-DB-002-项目主题实施指南.md#_12-3-db-s05-r2-多主题真实表达与双数据联合验证)维护。

预览正文继续inert只读，刷新／离开由外壳处理；它不构成后端授权边界。未绑定或坏绑定不能遮蔽独立准确预览，资料未映射明确unbound，不提供样例。合并上游组件时保留词汇调用范围及业务原文，合并文件边界时复核来源授权、锁顺序和generation。S06、协作及Andon保持暂停。implemented描述工程接线，人工验收状态与未执行的全量检查由LOG58拥有。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
| --- | --- | --- | --- | --- | --- |
| 真实词汇改变且原文保留 | 只改合成页或改写业务正文 | 真实业务组件／useProjectThemeVocabulary | projectWorkspaceState相关用例、同ID浏览器及PG回读 | 第三词汇、未保存输入保持 | Passed |
| 混合预览使用准确真实包 | 旧binding错误或合成资料遮蔽预览 | ProjectLayout／ProjectThemePanel | projectThemeSamples及真实选择入口预览／应用DOM | 未绑定／坏绑定仍渲染准确资料页；无准确包时拒绝 | Passed |
| 文件读取及hash属于目标上下文 | 旧revision、越界、失权或错误类型通过 | ProjectThemeService／Workdir | mixed_preview_files真实HTTP及磁盘回读 | revision／generation／alias／路径／失权／JSON与PNG类型／超限 | Passed |
| 同对象跨主题继续办理 | 复制对象或切回丢业务 | 原治理／工作Owner | 隔离项目A默认→调研→默认、PG正文v3与决定v2／来源v2 | 精简隐藏导航仍能打开准确工作并返回 | Passed |
| 全量及产品最终验收 | 把相关检查当全量 | 用户验收／专项LOG | 用户验收后由用户执行全量 | 禁止提前或分批跑完全量 | Not run：用户明确要求 |

实际证据、命令和未验范围见[LOG58及证据入口](../../../../元垒系统架构规划设计/LOG-DB-001-Dashboard进度基线与执行记录.md#_58-s05-r2真实主题消费与项目证据-2026-10-17)。
