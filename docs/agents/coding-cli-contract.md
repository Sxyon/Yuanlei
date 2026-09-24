# 编码 CLI 契约（M0 探针结果）

状态：M0 出证文档；探针脚本 `scripts/probes/coding_cli_probe.sh`；证据日志副本见 `tmp/pat-m0/cli-probe5.log`（本地临时，不入库）
关联：`docs/develop-guides/yuanlei/decisions/proposed/2026-09-18-agent-driven-coding-cli-sessions.md`、`docs/develop-guides/planning/agent-coding-execution-plan.md`

本文记录 AIO 沙盒镜像内 opencode/codex 的实测契约，作为适配器实现的事实来源。所有密钥仅经 env 透传，未进入命令、日志或本文。

## 镜像基线

- 镜像：`enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:1.11.0`（本地已有，8.81GB）。
- 版本：opencode `1.4.6`，codex-cli `0.139.0`，node `v22.23.0`（`/usr/local/bin/opencode`、codex 全局 npm）。
- `core` profile（provisioner 默认）下 supervisor 只运行 `nginx` 与 `python-server`；`code-server`、`jupyter`、`nodejs-repl`、浏览器/VNC 均 STOPPED 且不监听端口。**opencode server 不会自启**（4096 默认无监听），必须在会话开始时由我方启动。
- 沙盒 API：对外经 nginx `PUBLIC_PORT=8080`，`/v1/*` 转发到 `SANDBOX_SRV_PORT=8091`；终端 UI 位于 `/terminal`，WebSocket 代理端口 `WEBSOCKET_PROXY_PORT=6080`。
- 沙盒内命令以用户 `gem`（uid 1000）执行；`docker exec` 默认 root 会读到 `/root` 配置，探针与实现都必须以 `gem` + `HOME=/home/gem` 运行 CLI。

## 配置渲染（env → CLI 配置）

镜像入口 `gem.sh:553-640` 消费环境变量并写入用户 home；生产路径为 `/home/gem/.config/opencode/config.json` 与 `/home/gem/.codex/config.toml`。

| CLI | 触发变量 | 结果 |
|---|---|---|
| opencode | `OPENCODE_API_KEY` + `OPENCODE_MODEL` + `OPENCODE_PROVIDER` + `OPENCODE_BASE_URL`（+ `OPENCODE_PROVIDER_NPM`） | `model = "<provider>/<model>"`，provider 使用 `@ai-sdk/openai-compatible` 或 `@ai-sdk/anthropic`，`options.apiKey` 写入配置文件 |
| opencode | `OPENCODE_JSON` | 整份配置直写（高级） |
| codex | `CODEX_CONFIG_TOML` | 整份 `config.toml` 直写（推荐，平台按会话策略生成） |
| codex | `CODEX_API_KEY`/`ARK_API_KEY`/`OPENAI_API_KEY` + `CODEX_MODEL` + `CODEX_BASE_URL` | 渲染 provider 配置；镜像模板默认 `wire_api = "responses"` |

实测确认：两套渲染均生效；opencode 配置包含 apiKey 明文，任何回显/审计必须脱敏。密钥只允许经 env 注入，不进入 argv。

## opencode 1.4.6 契约

命令面（实测 `--help`）：

- `opencode run [message] --format json [-s <sessionID> | -c] [-m provider/model] [--agent <name>] [-f file] [--attach url] [--dir path]`：非交互执行；`--format json` 输出 JSONL 事件。
- `opencode serve --port <n> --hostname 127.0.0.1`：headless HTTP server；`opencode attach <url>` 可附着。
- `opencode acp`：ACP server（P6 预留接入点）。
- `opencode session list|delete`；顶层 `opencode export [sessionID]`/`import`。
- `opencode agent list`：内置 `build`、`plan`（primary），`explore`、`general`（subagent），`compaction`、`summary`、`title`。**`plan` agent 原生存在，可直接用于计划轮。**
- 权限模型：`build` agent 声明 permission 规则（`"*": allow`、`doom_loop: ask`、`external_directory: ask`（tool-output 除外）、`question: deny`），可按会话渲染配置收紧。

JSON 事件样本（成功一轮，模型经 OpenAI 兼容端点）：

```text
{"type":"step_start","sessionID":"ses_...","part":{"type":"step-start","messageID":"msg_..."}}
{"type":"text","sessionID":"ses_...","part":{"type":"text","text":"PONG","time":{...}}}
{"type":"step_finish","sessionID":"ses_...","part":{"type":"step-finish","reason":"stop","tokens":{"total":10370,"input":10077,"output":3,"reasoning":34,"cache":{"write":0,"read":256}},"cost":0}}
```

- 事件带 `sessionID`、`step_finish.tokens` 与 `cost`，可直接支撑用量与终态判定；未知 `type` 必须记 `warning`，不得丢弃。
- 原生会话续跑：首轮取得 `ses_*`，`opencode run -s <ses_id>` 续跑成功（同一 sessionID，cache read > 0）。**跨 Run 恢复成立。**
- 状态持久化：设置 `XDG_DATA_HOME`/`XDG_CONFIG_HOME`/`XDG_CACHE_HOME` 后，`opencode.db`（会话/消息）、`storage/session_diff`、日志、provider 依赖缓存全部落在指定目录 → 将 XDG 指向 `agents/coding/<session>/cli-state/` 即获得跨沙盒重建的会话与配置持久化。
- 程序化通道：`opencode serve` 监听 127.0.0.1:4096 后，直连 `/`、`/session` 均 200；经沙盒 nginx 通用端口代理（请求头 `x-aio-proxy-port: 4096` → `http://127.0.0.1:8080/`）同样 200，因此 **provisioner HTTP 代理可直接承载 opencode server 的 HTTP/SSE**（其代理不支持 WebSocket upgrade）。
- `serve` 默认无密码（日志告警 `OPENCODE_SERVER_PASSWORD is not set`）；实现必须设置密码或仅绑定回环并依赖 provisioner 代理的鉴权边界。

## codex-cli 0.139.0 契约

命令面（实测 `codex exec --help`）：

- `codex exec [PROMPT| -] --json [-m model] [-C dir] [-s read-only|workspace-write|danger-full-access] [--skip-git-repo-check] [--ephemeral] [-p profile] [-o last-message-file] [--output-schema file]`；prompt 支持 stdin。
- `codex exec resume <thread_id | --last> [PROMPT]`：原生会话续跑。
- `codex exec review`：非交互代码审查；`codex review` 顶层同义。
- `codex app-server`（实验性，含 daemon/remote-control）、`codex mcp-server`（stdio）。
- 审批与沙盒：审批策略来自 config（`approval_policy`），命令行提供 `-s/--sandbox` 三档策略与 `--dangerously-bypass-approvals-and-sandbox`。**头less 模式没有逐命令交互审批入口**，命令级审批只能在 P4 app-server / P5 TTY 中实现。

JSON 事件样本（成功一轮，Responses API 端点）：

```text
{"type":"thread.started","thread_id":"01a0b45b-..."}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"PONG"}}
{"type":"turn.completed","usage":{"input_tokens":10608,"cached_input_tokens":10368,"output_tokens":3,"reasoning_output_tokens":0}}
```

失败路径事件：`error`（含 `Reconnecting... n/5`）、`turn.failed`，均带 `message`；适配器据此收敛失败原因。

**关键结论：codex 0.139 只支持 Responses API。** `wire_api = "chat"` 被显式拒绝（`is no longer supported`）；`wire_api = "responses"` 要求端点实现 `/v1/responses`。实测：SiliconFlow `/v1/responses` → 404（不可用）；DeepSeek 官方 `https://api.deepseek.com/v1/responses` → 200，`codex exec --json` 成功返回 PONG 与 usage。因此 codex 执行器必须满足：

1. 凭据解析时校验 provider 能力（Responses 兼容），不满足则 `executor_unavailable` 显式失败；
2. 模型出口候选：OpenAI 官方、DeepSeek 官方、ARK（镜像默认 Responses），或平台未来的 Responses 兼容网关；
3. 计划轮用 `-s read-only`（配置 `approval_policy=never`）表达只读，执行轮按策略给 `workspace-write`。

状态持久化：`CODEX_HOME` 指向 `agents/coding/<session>/codex-home` 后，`state_*.sqlite`、`logs_*.sqlite`、`sessions/`、`skills/` 均落在该目录；`codex exec resume <thread_id>` 接受此前 thread id。**跨 Run 恢复成立**（本轮 resume 因 API 侧超时 124，但会话查找与恢复路径已触发；需在 M5 用稳定窗口复验成功样本）。

## 终端与 WebSocket

- `GET /v1/shell/terminal-url` 返回 `http://127.0.0.1:8080/terminal?session_id=<uuid>`（沙盒内部地址）。终端页面属于 nginx 8080 站点，交互数据面走 WebSocket（`WEBSOCKET_PROXY_PORT=6080`）。
- provisioner 代理明确剥离 `Upgrade` 等 hop-by-hop 头、methods 不含 WS（`docker/sandbox_provisioner/app.py:74,2146-2215`），**浏览器终端必须新增 WS 代理能力**（P5 设计不变）；不达标时降级为程序化只读 + HTTP 输入。

## 未验证项与降级

| 项目 | 状态 | 降级/后续 |
|---|---|---|
| codex 成功 resume 样本 | 会话目录与 thread 接受已验证；成功轮因 API 超时未复现 | M5 用稳定窗口复验；失败按 `resume_degraded` 处理 |
| opencode 工具调用（tool_call）事件样本 | 未触发（简单问答无工具） | M4 合同测试用真实工具任务录制 fixtures；未知事件记 warning |
| 取消语义（SIGTERM/进程组） | 未测 | M4/M5 通过 SDK session kill 实测并写合同测试 |
| `opencode acp` 协议细节 | 仅确认命令存在 | P6 spike |
| 自定义 `OPENCODE_JSON` 全量配置 | 未测 | 高级用户通道，实现时用同一探针脚本扩展 |
| 镜像 `browser`/`full` profile 下的差异 | 未测（当前部署 core） | 不影响本设计；如需浏览器工具再测 |

## 设计含义（结论 → 动作）

| 结论 | 对设计的动作 |
|---|---|
| core 不自启 opencode server | 会话启动需显式拉起 `opencode serve`（P4）或只用 `run`（P2） |
| 事件含 usage/cost/sessionID | 归一化事件保留 tokens/cost/session_ref；用量预算可行 |
| `plan` agent 存在 | 计划轮用 `--agent plan`；codex 用 `-s read-only` |
| codex Responses-only | 凭据预检必须校验端点能力；不满足显式失败，不做静默回退 |
| XDG/CODEX_HOME 生效 | 跨沙盒重建的 CLI 状态持久化方案成立；写入会话目录 |
| serve 经 nginx 端口代理可达 | P4 程序化通道可复用 provisioner HTTP 代理，无需新协议 |
| GET discover 会 touch（见生命周期契约） | 会话保活走 supervisor touch；对账用 list |
| 终端需 WS 代理 | P5 为必要条件；不可用则降级 |
