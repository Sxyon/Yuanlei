# 附件文件选择改为个人空间浏览并延迟线程创建

状态：proposed
类型：bug-fix
Owner：web/src/components/AgentChatComponent.vue

正文分工：线程创建时机与待引用缓存由 `web/src/components/AgentChatComponent.vue` 拥有；选择器浏览源由 `web/src/components/ProjectFilePickerModal.vue` 拥有；workspace 引用校验与持久化契约由 `backend/package/yuxi/services/attachment_service.py` 拥有；待引用 chip 展示由 `web/src/components/AgentInputArea.vue` 拥有。

## 问题

新对话（`currentChatId` 为空）时，附件面板的「项目文件」入口存在三个互相放大的缺陷：

1. **打开选择器就提前创建线程**。原 `handleProjectFileSelect` 在用户尚未选择任何文件时调用 `ensureAttachmentThread()` 创建线程，只为让 `ProjectFilePickerModal` 有 `threadId` 可加载树。线程一旦创建，`AgentView.vue` 的智能体切换入口把「当前对话已绑定智能体」视为锁定状态（`disabled: hasActiveThread && agent.value !== selectedAgentId`），用户从此无法再切换智能体。
2. **选择器确认即落库，仍然早于首次发送**。第一版修复把线程创建推迟到选择器确认时，但用户实际要求是：首次会话**发送之前**，引用只是前端缓存状态；确认时不应创建线程、不应调用引用接口。确认即落库仍然会锁定智能体选择。
3. **浏览源依赖线程且不符合需求**。`ProjectFilePickerModal.vue` 通过 `getViewerFileSystemTree(threadId, path)` 浏览当前 Project Workdir，需求是浏览**用户个人空间**（`/api/workspace/tree`，无需 threadId），与新对话创建前 Workdir 为空、无内容可选的事实一致。

后端 `reference_attachments_view` 只接受当前 Project Workdir scope 路径，个人空间 scope（如 `/docs/需求.md`）无法引用。

## 提案

1. **前端浏览源切换**：`ProjectFilePickerModal.vue` 改用 `getWorkspaceTree` 加载根与子目录；节点 `key` 用 workspace scope `path`，`isLeaf = !entry.is_dir`；确认时把 scope path 与 `source: 'workspace'` 传给父组件。`threadId` prop 已移除。
2. **首次发送前只缓存**：无线程时，选择器确认只把文件写入前端缓存 `pendingWorkspaceReferences`（path + name，去重），不创建线程、不调用引用接口；缓存以「发送时引用」chip 展示在输入框上方，可单独移除。智能体与项目在发送前始终可切换。
3. **首次发送时物化**：`handleSendMessage` 在确保线程存在后，把缓存文件通过引用接口落库到真实线程，引用成功后将 `@file` token 追加到本次发送文本（标题只基于用户原始输入），`fetchThreadAttachments` 后清空缓存；失败则中止发送、保留缓存并报错（fail-closed）。已有线程时，选择器确认保持立即引用（原交互不变）。
4. **后端引用契约扩展**：`AttachmentReferenceItem` 增加 `source: Literal['workdir', 'workspace'] = 'workdir'`；`reference_attachments_view` 对 `workspace` 来源改用 `Workspace(str(uid)).stat_authorized_path(scope, root='/')` 在用户个人空间边界内校验（拒绝越界、目录、symlink），登记 `path = runtime_user_data_path(scope)`（`/home/gem/user-data/<scope>`），`source` 保持 `"reference"`；`workdir` 来源行为不变，且 workdir 绑定改为按需解析（workspace 来源不触碰 Workdir）。`delete_thread_attachment_view` 对引用附件先判定来源再解析 Workdir 绑定，保证 Workdir 绑定失效的线程也能删除 workspace 引用。
5. **模型可见性**：`chat_service._with_attachment_context` 把附件 `path` 原样写入本轮模型输入；个人空间 runtime 路径已在沙盒挂载（`/home/gem/user-data` 即 UserWorkspace 根），Agent 可直接 `read_file`，无需复制字节。用户确认：**不复制**，仅登记引用。
6. **文案**：`AttachmentOptionsComponent.vue` 与 Modal 标题/空态从「项目空间/项目文件」改为「个人空间」；删除引用的语义不变（元数据删除、源文件保留）。
7. **统一浏览范围**：已有线程与无线程均浏览个人空间（用户确认）。

## 替代方案

- **确认时复制进 Workdir**：快照稳定但双份字节、5 MB 限制语义与上传混淆；用户已确认选择不复制。
- **已有线程保留 Workdir 浏览**：两套浏览源并存，文案与权限校验分叉；用户已确认统一个人空间。
- **确认即落库（第一版实现）**：线程创建早于首次发送，智能体仍被锁定；用户实测反馈后废弃。
- **前端传 runtime virtual_path 而非 scope**：会让引用接口同时接受两种坐标系，校验容易绕过 owning filesystem boundary，拒绝。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 打开选择器、确认引用均不创建线程，首次发送前智能体可继续切换 | 任一动作生成线程、或智能体入口被锁定 | web/src/components/AgentChatComponent.vue | `web/test/unit/projectFilePickerDeferredThread.test.js` 源级断言：打开与缓存分支均无 ensureAttachmentThread/referenceThreadAttachments | 恢复 `await ensureAttachmentThread()` 后断言变红 | Passed |
| 无线程确认只写前端缓存，发送时才引用落库 | 确认即落库、或发送时缓存丢失 | AgentChatComponent.vue `handleProjectFilesSelected` / `handleSendMessage` | 源级断言：缓存分支只写 `pendingWorkspaceReferences`；发送链路先 `ensureActiveThread` 再 `referenceThreadAttachments` 并清空缓存 | 把落库调用移回确认分支后变红 | Passed |
| 选择器浏览个人空间而非 Workdir，不依赖 threadId | 仍请求 `/api/viewer/filesystem/tree` 或依赖 threadId | web/src/components/ProjectFilePickerModal.vue | `web/test/unit/projectFilePickerWorkspace.test.js` 编译真实 SFC 挂载：打开只调 `getWorkspaceTree('/')`，目录懒加载，确认输出 `{path, name, source:'workspace'}` | 恢复 viewer API 调用后 mock 断言变红 | Passed |
| 待引用缓存可移除且随发送清空 | chip 无法移除、或发送后仍残留 | AgentInputArea.vue / AgentChatComponent.vue | 源码装配检查 + lint/build | 移除事件未接续时 chip 仍存在变红 | Inspected |
| `source=workspace` 引用在用户个人空间边界内校验并登记 runtime 路径，不复制字节 | 跨用户、目录、symlink、越界路径被接受；或复制了文件 | backend/package/yuxi/services/attachment_service.py | 后端 unit `test_attachment_service.py`（29 用例，含 workspace 正/负向、不解析 Workdir、删除保源文件） | `..`、目录、symlink、非法 source 用例变红 | Passed |
| `source=workdir` 现有引用行为不变 | 旧调用被破坏 | attachment_service.py、test_attachment_service.py | 既有 `test_reference_attachments_*` 全部通过 | 默认值偏离 `workdir` 时既有用例变红 | Passed |
| 删除 workspace 引用只删元数据、保留源文件 | 误删个人空间文件 | attachment_service.py `delete_thread_attachment_view` | 后端 unit（引用删除后源文件哨兵不变；Workdir 绑定不可解析的线程删除引用仍成功） | 源文件哨兵消失变红 | Passed |
| 模型可见附件路径为沙盒可读 runtime 路径 | 模型收到 workdir scope 或宿主路径 | chat_service.py、paths.py | unit 断言 `path == runtime_user_data_path(scope)`；`verify_engineering_contracts.py` | scope 未映射时断言变红 | Passed |
| 真实 HTTP 主链路 | 前端与后端契约漂移 | server/routers/chat_router.py | `test/integration/api/test_chat_router.py::test_reference_workspace_attachment_registers_runtime_path_without_copying` | 该用例恢复旧行为后变红 | Not run |
| 真实页面交互验证（浅/深色、loading/empty/error、缓存 chip） | 组件在真实装配中失效 | web 页面装配 | `playwright-cli` 截图验证 | 打开面板出现线程、选择器请求 viewer API 时失败 | Not run |

两处 `Not run` 的原因与风险：本环境未配置 `TEST_USERNAME/TEST_PASSWORD`（integration 用例会 skip），也没有 `playwright-cli` 可执行真实页面截图。补跑命令分别为 `docker compose exec api python3 -m pytest test/integration/api/test_chat_router.py::test_reference_workspace_attachment_registers_runtime_path_without_copying` 与 `playwright-cli -s=<session> run-code --filename=web/test/browser/projectFilePicker.js`；未执行前不得宣称这两条链路已通过。

## 风险

- 个人空间文件在引用后被移动/删除时，附件引用会失效；这是「不复制」语义的既定代价。
- 待引用缓存是组件本地状态：用户切到既有线程后再发送，缓存会落到该线程；chip 持续可见，用户可先移除再发送。
- 个人空间树默认隐藏未绑定 Project 的 `projects/` 子树（`_filter_project_tree_entries`），用户可能找不到部分文件；后续如需展示所有目录再显式放开 `include_unbound_project_dirs`。
- 引用接口新增 `source` 字段是 wire contract 扩展；旧客户端不传时回落 `workdir`，保持兼容。
