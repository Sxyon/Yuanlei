# 项目类型筛选与蓝图目标模板

状态：implemented
类型：feature
Owner：backend/package/yuxi/services/project_settings_service.py

## 问题

上游 Project 拥有访问与工作目录绑定。元垒已有项目管理设置和 Markdown 蓝图，但缺少用途分类与目标起草入口。长期经营与阶段交付项目需要可区分、可筛选，蓝图起草需要提示预期结果和衡量方式。项目用途不能成为权限或执行状态。

## 决策

在 yuanlei ProjectSettings 增加 project_type（unspecified/ongoing/delivery）、可空 category 与 tags。分类最长 50 字符，标签去首尾空白、去空项、保序去重，单项最长 30 字符、最多 20 项；旧项目返回未指定、空分类和空标签。yuanlei 31→32 只增列与类型约束，可重入，不推断历史用途。列表批量读取设置，缺设置不漏项目；设置返回的项目摘要也包含筛选属性。

现有项目选择组件组合名称、类型、分类与标签筛选。当前项目从完整可访问列表识别，筛选不解除选择、不改变对话项目。设置弹窗在描述后增加三个字段，日期与责任规则继续沿用。

蓝图新建弹窗提供空白、长期经营、阶段交付 Markdown 模板，项目类型只推荐默认项，用户可改选、编辑。切换模板需要确认覆盖已编辑正文，取消保留输入。新建复用独占创建，错误保留草稿；旧蓝图和正在编辑的旧正文不套模板。蓝图列表由后端按同用户 active/selectable Project 的已规范化工作目录比较判断共用，只返回提示，不暴露其他项目身份。

## 替代方案

独立分类中心和领域层增加本批没有消费者的模型与管理入口，暂不采用。模板由后端生成会增加参数和格式协议；首批仅由页面生成可编辑正文，现有文件接口继续拥有创建与覆盖保护。自动套模板或复制共用目录文件会改变已有字节与归属，排除。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 旧设置与项目保持可读，迁移重入保留管理属性 | 默认漏旧项目或清空资源 | ProjectSettings / migrator | 真实 PG 与 settings HTTP integration | 非法类型和超长标签拒绝且不改项目 | 通过 |
| 筛选不改变访问与选择 | 缺记录被排除、当前选择清空 | 项目列表 service / selection | HTTP 列表回读、Web unit 与浏览器 | 无匹配仍保留当前选择，外用户项目不返回 | 通过 |
| 模板编辑、取消、冲突保留草稿与原文件 | 静默覆盖正文 | 工作台 / blueprint service | Web unit、真实文件与页面 | 同名创建失败原字节不变、取消切换保留正文 | 通过 |
| 共用目录提示只比较可见项目 | 泄露不可访问项目、复制文件 | ProjectRepository / blueprint list | HTTP/PG 与文件回读 | 外用户、隐式和已删除项目不触发提示 | 通过 |

### 执行证据

复验命令在仓库根运行：

```bash
docker compose exec -T web node --test test/unit/workSuggestionsPanel.test.js test/unit/workDelegationsPanel.test.js
docker compose exec -T web pnpm run lint:check
docker compose exec -T web pnpm run test:unit
docker compose exec -T web pnpm run build
docker compose exec -T api uv run --group test pytest test/unit -m "not slow"
docker compose exec -T api uv run --group test pytest test/integration/api/test_project_settings_api.py test/integration/services/test_project_blueprint_service.py
docker compose run --rm --no-deps storage-migrator
python3 scripts/verify_engineering_contracts.py
python3 -m unittest scripts.test_verify_engineering_contracts
cd docs && pnpm run build
```


标准 Web 容器使用 Node 24.20.0。P03 两份测试只补 localStorage 初始化和清理，独立执行 5 项通过，标准 lint、unit（477 项）及 build 通过；没有改产品逻辑或删减断言。P04 完整标准 Web unit 488 项通过、lint 与 build 通过。相关模板和筛选交互覆盖已编辑草稿确认取消、同名冲突、切换项目后的迟到响应与确认回调、隐藏当前项目及更名后属性保留。

后端完整 `docker compose exec -T api uv run --group test pytest test/unit -m "not slow"`：2793 passed、63 skipped、7 subtests passed。真实 PostgreSQL 与 HTTP 的项目设置及蓝图相关 integration：23 passed。迁移用例验证真实 31→32 重入、原字段保留与非法类型数据库拒绝；设置 HTTP 验证非法标签拒绝、知识库关联保留与更名摘要保留筛选属性。tags 采用既有 JSON_VALUE：PostgreSQL 为 JSONB，SQLite 单元测试使用 JSON。

本地 shipping storage-migrator 执行成功，schema 从 business=7、knowledge=2、yuanlei=31 变为 7、2、32。迁移前后原 22 个项目、9 条设置、0 条知识库关联的数量和原字段摘要一致，9 条旧设置新增属性均为未指定、空分类、空标签。真实页面使用隔离的普通验收用户；无日期长期项目保存、非法标签错误保留输入、刷新回读、类型/分类/标签组合筛选、无匹配保留当前项目、模板覆盖确认取消、空白模板、取消重开保留草稿、同名失败保留输入、成功创建自定义正文均验证。HTTP 再读确认旧蓝图字节不变、新蓝图正文持久化和共用提示。浅深主题及 450px 模板弹窗截图已检查，操作可见；项目选择组件的隐藏选择语义由 mounted Web unit 验证。

页面验收期间容器磁盘满导致 PostgreSQL 暂时进入恢复模式。定位并清理 Vite 可再生缓存后恢复连接，再读设置和蓝图成功。截图保存在本地验收 artifacts，不提交账号、凭据或用户文件。验收账号已停用，临时凭据已删除；隔离测试项目和蓝图保留为回读证据。

工程检查、70 项检查器 unit、文档 build 和 diff 空白检查通过。P03 真实 Codex 成功产物与 Multica 出向仍未验证。

## 后果

模板是普通 Markdown，完整内容快照与更名后的执行快照验收在 P06。筛选属性不加入执行输入或路由。P03 真实 Codex 成功产物及 Multica 出向继续未验收，不作为本批前置。团队权限、周期工作定义、完整 Context Pack 与目标状态机不在范围。
