# S06主题迁移、专项收尾与试运行交接

状态：开发交付待人工验收。下文保留2026-10-17首版证据；2026-10-18独立审查修复及证据边界见本页末节和LOG61。正式部署启动／迁移证据、人工验收及前后端全量未闭合，专项不得标记最终完成。

## 本轮实现的能力

- **准确版本原包导出**：主题管理“已发布版本”先可查看“包成员”，展示项目文件alias与包内素材，再按准确版本重新授权并回读原始ZIP，返回原字节SHA-256；不从DTO重新打包，不自动携带项目绑定、文件路径、业务数据、凭据或身份。作者写入素材的内容原样保留，不承诺自动脱敏。撤回版本拒绝导出，停用版本沿既有读取语义。
- **导入只读预检**：平台主题管理提供“导入主题包”，有界接收ZIP后展示主题名、作者声明、原包摘要、format／ABI／基础界面、页面、素材和必须重绑的项目文件alias；取消不产生来源、候选或绑定。
- **确认保存草稿**：默认新建个人主题草稿，也可明确写入有权维护的既有主题草稿；既有目标核候选revision，内置来源拒绝。确认时重传实际字节并核对预检摘要，只保存草稿，不自动发布、应用或覆盖已发布版。
- **接续原制作与使用链**：导入后定位准确草稿，选择目标Project并临时映射文件后做真实只读预览；发布生成不可变版本，明确分配后才改变项目选择。冲突、同版本异字节、重复导入和响应丢失均有核实入口。
- **跨实例迁移**：隔离A／B使用不同数据库、主题文件根、用户Workdir与实例ID，走真实登录、前端、API、PG、ZIP和文件链路；A原包导出→B预检草稿→B资料预览→发布→分配→重启→切回。A原选择和内容不变，B再导出与A原包同hash。

精确任务、约束和人工路径分别由[SYS第16节](../../SYS-DB-001-Dashboard系统需求与架构设计.md#_16-s06迁移、专项收尾与试运行交接-2026-10-17)、[DEV第7节](../../DEV-DB-002-项目主题实施指南.md#_7-s06-主题迁移、专项收尾与试运行交接-当前实施卡)和[LOG第60节](../../LOG-DB-001-Dashboard进度基线与执行记录.md#_60-s06主题迁移、专项收尾与试运行交接-2026-10-17)拥有。本页只保留人工操作、证据索引、限制和交接。

## 人工测试入口

日常产品入口即可验证主流程；主题配置字段、制作步骤和限制见[制作和使用项目主题](../../../intro/project-theme-authoring.md)与[项目主题配置参考](../../../advanced/project-theme-reference.md)。主题管理页右上角提供“使用说明”，编辑草稿下方提供“配置参考”，导入弹窗也提供使用说明入口。跨实例文件重绑由执行者在隔离A／B完成，用户不需要查数据库或构造故障。

1. **导出**：项目→主题管理→平台内置或我的主题→准确来源→已发布版本→“导出原包”。观察下载文件名、完成提示中的版本／字节数／SHA-256，以及下载文件仍是原ZIP而不是页面定义。
2. **预检与取消**：主题管理→“导入主题包”→选择ZIP。观察只读预检摘要；直接取消后目录来源数、草稿修订和项目选择均不变。
3. **保存草稿**：重新导入，保留默认“新建我的主题草稿”或明确选择既有主题，填写目标名称→“确认保存草稿”。观察提示“草稿已保存，尚未发布／应用”，并自动定位准确草稿修订；目标主题的已发布版本仍为原样。
4. **目标预览**：草稿“预览已保存草稿”→选择有权目标项目→填写文件alias路径→开始只读预览。观察预览页读取目标项目自己的JSON／PNG；未填写的alias明确显示未绑定；预览不改变已保存主题选择。
5. **发布与分配**：发布新版本（不自动应用）→在准确版本行“分配到项目”→选择目标项目、填写文件映射并“应用主题”。刷新或重开页面后新主题保持；随后从“项目主题设置”显式选择旧版本并应用，观察generation推进和旧主题恢复。
6. **失败观察**：重复导入同版本异字节时，草稿可保存但发布会提示版本冲突；并发窗口写入旧revision会被拒绝；导入响应丢失时出现“导入结果待核实”，先核实准确草稿，不重复创建来源。

用户无需手工制造所有负例。越权、非法ZIP、不支持ABI、内置目标、旧revision、错误媒体、缺失文件、旧generation、跨实例会话和字节一致性由执行者完成。

## 实际证据

| 场景 | 可核对结果 |
| --- | --- |
| A导出 | 包成员面板展示facts／chart与不携内容；下载字节SHA-256 `353d7fdc…854c4`与版本记录、A容器存储文件三方一致；文件名由版本安全生成 |
| B预检 | 显示`3.1.0-r2`、format 1／ABI 3／基础界面1、页面10个、文件alias facts／chart；PG来源／版本／绑定计数不变 |
| 取消 | 关闭预检弹窗后无来源、无候选写入 |
| 导入草稿 | B新增个人来源、候选revision 1、digest与A原包相同；版本数0，未自动发布或应用 |
| 目标预览 | 预览页`data-persisted-theme-version`仍为B旧主题；资料区显示B的`samples 99`、`origin B`、`B项目真实资料`及B自己的PNG |
| 发布／分配 | 发布digest仍为A原包；B1 generation推进、B2对照项目不变；PG绑定与HTTP一致 |
| 重启 | B API重启后准确版本选择保持，业务与资料仍可读取 |
| 切回 | 显式选择旧默认3.0.0，generation继续推进；B1恢复旧主题版本 |
| A不变 | A来源候选摘要／修订、来源与版本计数、项目绑定及当前主题摘要均不变 |
| 再导出 | B发布版本再导出与A原包逐字节一致，响应摘要相同 |
| 响应丢失 | 新来源与既有来源导入响应和首次目录核实均失败时显示待核实入口；显式重新核实后定位已保存草稿，新来源只创建一次，既有来源revision前进且未新增版本 |
| 负例 | 15项跨实例：token 401、越权来源／项目、非法ZIP、ABI 4、预检摘要不符、内置目标、旧revision、同版本异字节、未绑定alias、错误JSON／PNG、缺文件、旧generation均按目标原因失败；integration另覆盖项目专属来源导入、错误project、版本长度预检与确认、新建身份写入中断、已保存但回读失败；浏览器另验既有草稿被外部HTTP推进后409并刷新目录（revision前进1） |

详细结果：

- [浏览器36项检查与请求计数](browser-checks.json)
- [HTTP／PG／ZIP／Workdir对账及15项负例](http-pg-files.json)
- [新来源响应丢失检查](recovery-check.json)、[既有来源响应丢失检查](existing-recovery-check.json)、[旧revision并发刷新检查](stale-revision-check.json)、[下载文件名检查](download-filename-check.json)
- [运行代码／镜像与文件摘要](environment.json)、[重启后健康与绑定回读](restart-ready.json)、[主题管理使用说明入口检查](theme-guide-links.json)
- [预检实际文本](b-preflight.txt)、[包成员实际文本](a-package-details.txt)、[含素材包成员文本](a-package-assets.txt)
- 截图：[A导出](a-export-1440.png)、[A包成员](a-package-details-1440.png)、[A含素材包成员](a-package-assets-1440.png)、[B预检](b-preflight-1440.png)、[B导入草稿](b-imported-draft-1440.png)、[B目标资料预览](b-preview-1440.png)、[B发布](b-published-1440.png)、[B应用](b-applied-1440.png)、[B切回](b-restored-loaded-1440.png)、[B对照项目](b-control-1440.png)、[新来源响应丢失恢复](b-import-recovery-1440.png)、[既有来源响应丢失恢复](b-import-existing-recovery-1440.png)、[旧revision并发刷新](b-import-stale-1440.png)、[主题管理使用说明入口](theme-guide-entry-1440.png)。
- [A原包](a-original.theme.zip)：原ZIP样本；不自动携带项目业务、绑定、凭据或宿主路径，作者声明素材原样保留。

## 隔离环境

| 实例 | 容器／端口 | 数据库 | 文件与身份边界 |
| --- | --- | --- | --- |
| A | `yuanlei-s04-repair`／15064，前端15174 | `yuanlei_s04_repair_evidence` | 原有S04／S05证据主题与Workdir；实例ID沿用A |
| B | `yuanlei-s06-b`／15065，前端15175 | `yuanlei_s06_evidence_b` | 独立主题文件卷`yuanlei-s06-b-data`、独立用户Workdir与`instance-s06-b-evidence` |

两实例共享同一PostgreSQL进程，但数据库、主题域、用户目录和浏览器源隔离；A token在B、B token在A均401。会话凭据只留在私有临时文件，未写入文档或Git。日常库、日常主题文件和三套内置ZIP未被覆盖或自动升级。

A／B沿用仓库既有`project_theme_app`证据入口，运行真实routers、认证、PG、migrator、主题文件域和前端；它不执行`server.main`完整startup lifespan，因此`/api/system/ready`的`startup`项为`not_complete`（503）。本证据只用`/health`确认进程存活，并以真实API成功、PG绑定回读、ZIP／Workdir hash和浏览器DOM证明主题链路，不宣称该证据实例是平台全量ready。

## 复现命令

以下命令用于复现隔离证据；会话文件、数据库口令和容器环境只放在私有临时目录，不写入文档或Git。A需保留S05-R2证据源`S05-R2证据 · 调研 · 阅读工作室`的`3.1.0-r2`版本，否则需替换脚本中的准确来源／版本标识。

```bash
# 0. 前置：日常compose已运行，A证据容器yuanlei-s04-repair可访问。
export PRIVATE=/tmp/s06-evidence        # 私有目录，权限600
export THEME_EVIDENCE_OUTPUT="$PWD/docs/元垒系统架构规划设计/图解/33-theme-migration-20261017"
mkdir -p "$PRIVATE"

# 1. 读取A／B私有会话（不要打印或提交）
docker exec yuanlei-s04-repair sh -c 'cat /tmp/s04-repair/session.json' > "$PRIVATE/a-session.json"
./backend/test/e2e/start_project_theme_migration_b.sh
docker exec yuanlei-s06-b sh -c 'cat /tmp/s06-b/session.json' > "$PRIVATE/b-session.json"
chmod 600 "$PRIVATE"/*.json

# 2. 两个真实前端源，分别代理到A／B；Playwright直接使用真实页面和HTTP
(cd web && VITE_API_URL=http://127.0.0.1:15064 pnpm exec vite --port 15174 --strictPort) &
(cd web && VITE_API_URL=http://127.0.0.1:15065 pnpm exec vite --port 15175 --strictPort) &
for _ in $(seq 1 60); do
  curl -fsS http://127.0.0.1:15174/ >/dev/null && curl -fsS http://127.0.0.1:15175/ >/dev/null && break
  sleep 1
done

# 3. 依次运行：主迁移→HTTP/PG/文件/负例→新来源响应丢失→既有来源响应丢失
#    →旧revision并发→重启回读。host需已有httpx与Python Playwright浏览器；
#    web依赖用pnpm安装，浏览器不可用时设置THEME_EVIDENCE_CHROMIUM。
export THEME_EVIDENCE_A_API=http://127.0.0.1:15064
export THEME_EVIDENCE_B_API=http://127.0.0.1:15065
export THEME_EVIDENCE_WEB_A=http://127.0.0.1:15174
export THEME_EVIDENCE_WEB_B=http://127.0.0.1:15175
export THEME_EVIDENCE_A_SESSION="$PRIVATE/a-session.json"
export THEME_EVIDENCE_B_SESSION="$PRIVATE/b-session.json"
python3 backend/test/e2e/project_theme_migration_browser.py
python3 backend/test/e2e/project_theme_migration_evidence.py
python3 backend/test/e2e/project_theme_migration_recovery.py
python3 backend/test/e2e/project_theme_migration_existing_recovery.py
python3 backend/test/e2e/project_theme_migration_stale.py
python3 backend/test/e2e/project_theme_migration_restart.py
```

`start_project_theme_migration_b.sh`只创建缺失的B数据库／卷并重启B容器，不删除既有B数据；需要从干净B重跑时，由执行者显式删除`yuanlei_s06_evidence_b`和`yuanlei-s06-b-data`后重新运行。`project_theme_migration_evidence.py`依赖主迁移已创建`B迁移草稿-UI`；`stale`脚本读取当前候选修订并推进后验证409刷新，不依赖固定修订号。B的`/ready`现状与边界见[重启回读](restart-ready.json)。`a-package-assets-*`与`download-filename-check.json`为手工补充证据，分别由A历史来源“调研·依据阅读”的包成员弹窗和一次准确版本导出生成。

## 关键取舍

- **原字节优先**：导出和未编辑导入直接读写`ThemeStore`中的原ZIP；只有用户实际编辑定义或替换素材后才生成新digest。原包内作者自行写入的文案／JSON／PNG会随包带走，导出界面不承诺自动脱敏。
- **预检不落库**：预检只解析并返回摘要；确认时浏览器重传同一文件，服务端重新解析并核对摘要，避免新增预检blob、token或跨请求状态表。
- **来源身份本地化**：包内`theme.id`、manifest.source和digest只代表作者声明与字节，不授予来源权限；目标生成自己的source／version身份。
- **三步分离**：导入只保存草稿，发布只生成不可变版本，分配才改变Project绑定。未新增自动发布、自动应用、第二套绑定或导入状态机。
- **文件alias重绑**：ZIP只携逻辑alias和声明素材；项目文件路径、预览query、generation、业务行、凭据和宿主路径留在目标环境。缺少文件可以保存和预检，但不能应用。
- **结果不明先核实**：导入请求异常时先读取有权目录与候选digest；只有唯一匹配才定位草稿，不自动重建来源。既有草稿并发由revision拒绝，同版本异字节由发布拒绝。

## 兼容与限制

- 当前包协议为formatVersion 1、componentAbi 1—3、baseVersion 1；页面、块、能力和呈现由当前parser与可信Vue消费者判定，未知ABI／字段／成员明确拒绝。
- 包内素材只支持application/json和image/png；ZIP上限8 MiB、展开32 MiB、128个成员、页面32、每页64块、PNG合计1600万像素；项目文件单文件8 MiB。
- 不自动下载组件、执行上传代码、猜字段转换或迁移业务状态；跨平台适配、自由Vue、模板市场／团队分享、批量升级和自动转换不在本轮。
- 普通用户不能恢复数据库；部署维护者需同时备份PG与主题文件域，按来源／版本／绑定逐项核对。

## 备份与恢复

- 主题事实由`project_theme_sources`、`project_theme_versions`、`project_theme_bindings`、`project_theme_events`与主题文件域（Compose中的`theme-sources`卷或部署配置的`YUXI_THEME_SOURCES_DIR`）共同拥有；两者必须同一恢复点。
- 恢复后在主题管理“存储检查与维护”核对引用包、孤儿、临时残留和缺失／损坏；不要用另一实例的同名版本代替。
- 导入身份已建但草稿未完成时，打开该身份重新上传完整ZIP；不要重复创建。候选并发冲突先重新读取修订；同版本异字节先修改`theme.version`再发布。
- 来源停用保留既有绑定加载，安全撤回停止全部版本加载并保留原绑定与历史；恢复来源不自动改项目选择。

## 未验与试运行

- 前后端全量unit／integration／E2E未运行；人工验收未完成。S01—S05的旧人工确认和全量状态沿用各自LOG，本轮没有补记通过。
- 隔离证据入口不执行完整`server.main` lifespan，`/ready`的startup检查为未完成；这是证据服务边界，不是主题路由、认证、持久化或文件链路失败。平台全量ready未在本轮证明。
- 新增导入弹窗与恢复态只验证了1440浅色真实页面；暗色、375／768窄屏、所有控件组合和跨浏览器矩阵未验。
- 未运行付费模型、组织协作、外部执行器和生产数据演练；协作接入与Andon继续暂停。
- 试运行从实际项目管理、蓝图／议题／讨论／决定、计划／工作、证据资料和主题维护出发；实际问题继续记入[LOG](../../LOG-DB-001-Dashboard进度基线与执行记录.md)的试运行节，按影响等级记录恢复动作，不在试运行后清理真实数据。
- Agent专用主题生成／维护工具和有限自主发布授权、丰富素材／模板库、更多内容格式、组织协作及第三方平台适配仍是后继目标，不计入本次结项。

## 2026-10-18独立审查

审查基线为`858f91d5`，当前需求达成、每项修复前后效果、影响面、实际命令及未验清单由[LOG第61节](../../LOG-DB-001-Dashboard进度基线与执行记录.md#_61-s06独立审查与定向修复-2026-10-18-待人工验收)拥有，原第60节保留历史。本轮没有提交、推送、画图或运行全量。

直接材料：[保存成功却禁用再次导入的修复前页面](review-20261018/before-repeat-import.png)、[相同场景修复后按钮可用](review-20261018/b-imported-draft-1440.png)、[目标B真实资料预览](review-20261018/b-preview-1440.png)、[B准确议题办理返回](review-20261018/b-applied-1440.png)、[正式部署边界回读](review-20261018/deployment-boundary.json)、[重启后PG绑定与原ZIP摘要](review-20261018/restart-pg-bytes.json)。截图与PG本身不替代浏览器恢复；B恢复可访问后已独立补验，主脚本超时事实保留，正式启动检查仍未完成。

主浏览器脚本重复执行时可设置`THEME_EVIDENCE_IMPORT_NAME`为本轮独立样本名，按本次新增的准确来源ID写入`browser-checks.json`；独立对账脚本读取该ID，不再选择目录第一个同名历史来源。主脚本失败时不得运行依赖成功报告的后续脚本或复用旧报告冒充本次通过。新增`project_theme_import_review.py`验证连续导入与切回新建后真实提交但响应丢失的恢复，使用相同的私有会话及输出变量；未完成的实际结果按LOG61登记。

A／B省略正式startup且都未登记schema版本；`/ready`均503。本轮不通过补写版本表、调整ready或清空数据来补齐证据，正式部署迁移／启动链仍按SYS16.4验收。

补验结果：[连续导入及最终模式恢复6项检查](review-20261018/import-review.json)、[连续导入页面](review-20261018/after-repeat-import.png)、[切回新建后响应丢失恢复](review-20261018/after-new-target-recovery.png)、[重启后浏览器读取及显式切回](review-20261018/restart-browser-review.json)、[重启后B资料页面](review-20261018/restart-browser-recovered.png)、[旧版恢复页面](review-20261018/restart-browser-restored.png)。`project_theme_migration_finish_review.py`用于已重启B恢复可访问后的独立读取及切回；它沿用相同私有会话／输出变量，不再次重启、不改A，不作为正式startup验证。运行前B1须仍绑定本次迁移主题，成功后恢复旧默认版本。

[目标B发布版真实再导出](review-20261018/reexport-review.json)已与A下载ZIP逐字节比较，SHA一致。旧`recovery／existing_recovery／stale`脚本仍依赖首版固定合成名称，仅按首版环境复现；本轮使用独立审查脚本，不把旧输出混入本轮结果。
