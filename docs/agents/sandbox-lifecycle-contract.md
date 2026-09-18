# 沙盒生命周期契约（M0 探针结果）

状态：M0 出证文档；探针脚本 `scripts/probes/sandbox_lifecycle_probe.sh`；证据日志副本见 `tmp/pat-m0/lifecycle-probe5.log`（本地临时，不入库）
关联：`docs/develop-guides/yuanlei/decisions/proposed/2026-09-18-agent-dedicated-sandbox-lifecycle.md`、`docs/develop-guides/planning/agent-coding-execution-plan.md`

本文记录 provisioner 沙盒生命周期与执行租约的实测契约。探针使用独立 provisioner 实例（独立端口、独立 Docker 网络前缀 `pat-probe-sandbox` 与地址池 `10.252.240.0/20`、独立 scratch 挂载），不触碰 Compose 开发栈；结束时按 generation 删除。

## provisioner API 回放

| 操作 | 路径 | 语义 |
|---|---|---|
| create | `POST /api/sandboxes` | 幂等创建/复用；内部等待沙盒健康；返回 `generation`（Docker=容器 id，K8s=Pod uid） |
| discover | `GET /api/sandboxes/{id}` | 404 表示不存在；**成功时会计入 idle 活动（touch）** |
| touch | `POST /api/sandboxes/{id}/touch` | 保活并刷新 idle |
| list | `GET /api/sandboxes` | 权威 inventory；不 touch |
| delete | `DELETE /api/sandboxes/{id}?expected_generation=` | generation 不匹配返回 409；404 按幂等成功处理 |
| quiesce | `POST /api/sandboxes/quiesce` | 停机静默删除（未在本轮实测） |

创建前置校验（本轮实测踩到并确认）：`workdir_path` 指向的目录必须已存在且无 symlink 组件；`<skill-projections>/<uid>` 目录必须已存在且无 symlink。生产分别由 Workspace resolver 与 skill projection 服务提供，沙盒层不自行创建（保持路径边界）。

## 实测结果

环境：`SANDBOX_IDLE_TIMEOUT_SECONDS=12`、`SANDBOX_IDLE_CHECK_INTERVAL_SECONDS=2`、`SANDBOX_EXEC_TIMEOUT_SECONDS=5`（避免自动上调）。

| 场景 | 观察 |
|---|---|
| create | HTTP 200，返回 generation（64 位容器 id），容器 `Up (health: starting)` → 最终 healthy |
| touch 保活（idle 窗口内） | touch 后 8s 查询 200；二次 touch 后 4s 查询 200 |
| 静默闲置 | 停止一切 API 调用 16s 后单次 discover → 404，容器已被删除（`docker ps -a` 无残留） |
| 轮询 discover 的反例 | 每 2s 轮询 discover 时永远 200：**discover 自身刷新 idle 计时**，reaper 不会触发 |
| provisioner 重启存活 | `docker restart` 后 health 恢复，discover 200 且 generation 与重启前一致；容器继续运行 |
| generation fence | 按当前 generation 删除 200；携带过期 generation 删除 409 |

## 关键语义与设计结论

1. **reaper 只读全局 TTL，不支持按沙盒策略**（`app.py:1768-1778`）。`persistent` 的闲置 suspend 与 `resident` 的永不回收需要扩展 `CreateSandboxRequest`（`lifecycle`/`idle_timeout_seconds`，0=永不）与 record，并让 reaper 按记录判定；扩展必须可选且旧请求行为不变。
2. **任何 discover/touch/proxy 流量都会续命**。生命周期 supervisor 的 inventory 对账必须使用 `GET /api/sandboxes`（列表，不 touch），不能逐沙盒 discover；否则长驻策略会被自己的巡检无限延长。
3. **容器跨 provisioner 进程重启存活**，权威事实在 Docker/K8s 侧；provisioner 的重启种子来自 backend list（`SandboxIdleReaper._seed_existing`），重启会刷新所有沙盒的 idle 起点。supervisor 必须容忍「记录 active 但容器被外部删除」与「容器存在但记录缺失」两种情况并显式收敛。
4. **执行租约不存在于现状**：provider 只有进程内 `threading.Lock` 与 provisioner 侧操作 pin（创建/删除互斥），跨进程/跨 Run 无所有权。串行语义必须由新增的 PostgreSQL 行级租约承担（设计见提案，M3 实现）。
5. **generation fence 可直接复用**为租约接管的防双写手段：suspend/rebuild 后 generation 变化，旧持有者下一次操作必然失败。
6. `sandbox_id` 由应用按 scope 确定性派生（当前 `sha256(uid:thread)[:12]`）。扩展为 `thread` / `agent-project` 两种 scope 时，创建前置目录校验、`workdir_path` 一致性与 404/409 语义全部保持不变。
7. **镜像 profile 覆盖不可被请求改写**（既有实现），生命周期字段只能来自平台配置与集中策略，不能来自用户 env。

## 共享契约冻结（M0）

以下为两份提案的公共接口，M1/M2 实现不得各自解释：

1. **scope 与 id**：`thread:{uid}:{thread_id}` 或 `agent-project:{uid}:{agent_slug}:{project_id}`；`sandbox_id = sha256(scope_key)[:12]`；Run 的 `runtime_scope_id` 保持不透明字符串，校验同时接受两种形态。
2. **执行租约**：`sandbox_busy(owner_kind, owner_id, expires_at)`；TTL 120s、心跳 30s（与 Run lease 对齐）；获取失败进入等待并产生 `yuxi.sandbox_waiting`，超时（默认 600s）返回结构化错误；接管前必须校验 generation。
3. **凭证/环境指纹**：`credential_fingerprint = hash(解析后的非密配置 + 密文版本 + 相关沙盒 env 贡献)`；由凭据解析输出，沙盒层只存储与比较。
4. **事件命名**：`yuxi.sandbox_waiting`、`yuxi.sandbox_rebuilt`、`yuxi.sandbox_rebuild_required`、`yuxi.coding_session_event`；未知事件记 `warning`，禁止静默丢弃。
5. **迁移版本**：一个发布窗口内新增表只升一次 yuanlei 版本；两批表格同期落地一次性进 v4，分开落地则后者顺延并同步更新两份提案的交叉引用。business/knowledge 域不动。

## 未验证项与后续

| 项目 | 状态 | 后续 |
|---|---|---|
| Kubernetes 后端生命周期 | 未测（本轮 Docker） | 有 K8s 环境时复跑同一脚本；generation=Pod uid 语义一致 |
| quiesce 停机静默 | 未测 | 实现 supervisor 前补测 |
| Docker 守护进程重启（非 provisioner） | 未测 | 生产运维场景，记录为已知未验证 |
| reaper 与长命令执行的竞争 | 未测 | M2/M3 用 idle < exec 的极端配置验证「不误杀运行中命令」的保护 |
| 按沙盒 TTL/resident 扩展 | 代码事实确认当前不支持 | M2 实现并用本脚本扩展用例验证 |
| 租约过期接管双写防护 | 设计已定 | M3 负向测试：旧 owner 在 generation 变化后写入必须失败 |

## 设计含义（结论 → 动作）

| 结论 | 对设计的动作 |
|---|---|
| discover 会 touch | supervisor 用 list 对账；会话保活显式 touch |
| reaper 全局 TTL | M2 扩展 provisioner 可选字段；resident 跳过 |
| 容器跨 provisioner 重启存活 | 收敛任务以容器事实为准，记录可与容器短暂不一致 |
| 无跨进程租约 | M3 新增 PG 行级租约，Run/coding turn/终端统一持有 |
| generation fence 可用 | 接管与重建的安全内核直接复用 |
| 创建要求 workdir/skill 目录存在 | 会话启动前必须通过 Workspace/skill resolver 准备目录，失败显式返回 |
