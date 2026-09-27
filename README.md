# 元垒（Yuanlei）

元垒（Yuanlei）是 AI 时代的 **个人** / **企业** 的AI中枢系统，是您的总裁办、CEO办公室，集参谋与决策、督查与汇报、执行与协同为一体 的 AI 平台。

元垒是一个基于 [Yuxi](https://github.com/xerrors/Yuxi) 的二次开发改造版本：保留上游的多租户知识库、知识图谱、LangGraph 多智能体、MCP/Skills、沙盒与权限能力，并围绕「项目」实现参谋与决策、督查与汇报、执行与协同 三大核心职责。

[![Release](https://img.shields.io/github/v/release/Sxyon/Yuanlei?color=046A82)](https://github.com/Sxyon/Yuanlei/releases/latest)
[![License](https://img.shields.io/github/license/Sxyon/Yuanlei.svg?logo=github)](https://github.com/Sxyon/Yuanlei/blob/main/LICENSE)
[![Yuxi 上游基线](https://img.shields.io/badge/Yuxi-v0.7.3-046A82)](https://github.com/xerrors/Yuxi)

[元垒治理与决策](docs/develop-guides/yuanlei/README.md) · [差异化功能索引](docs/develop-guides/yuanlei/features/README.md) · [上游 README 镜像](README.yuxi.md) · [English](README.en.md)

## 元垒的理念

每个人和每个公司，都应该拥有属于自己的AI平台。
铁打的营盘，流水的兵 —— 元垒就是你的指挥部，五花八门的AI产品是你的兵。
商业产品再好用也应当是协作，不应该把个人或公司 all in 依赖绑定某个产品之上。

## 元垒适合的场景

- 一个可以完全掌控和管理的 AI 平台。
- 公司、产品、项目 的 蓝图、决策、演进、行动的可追溯管理平台。
- 项目维度 的 统筹规划、细化议题、明确决策、落地执行为一体的管理工作。
- 让智能体调用外部智能体协作开展工作，如opencode、codex、multica等。

## 元垒特性

元垒以项目为工作单位，把持续演进的方案、可审核的治理事实、数字员工执行和结果查看连接起来。[项目工作台使用指南](docs/intro/project-workbench.md)从一份蓝图开始，走通议题、决策、任务和督查。

### 参谋与决策：方案和结论有出处

- **可演进的项目蓝图**：在项目 Workdir 中创建、编辑 Markdown 蓝图，记录目标、范围和验收标准；旧版可整份归档并在工作台回看。文件本身是正文的事实源，项目数字员工与人使用同一份目录。
- **议题讨论与人工审核**：项目成员用 Markdown 提出议题，在审核前修改并追加讨论；审核通过或拒绝后保留只读历史。决策记录结论、理由及关联议题，任务可关联议题和决策。外部渠道导入的议题和任务先作为待审核提议，不能直接成为正式事实。
- **项目数字员工**：Agent 可绑定到指定项目并使用项目级配置覆盖；请求接入和执行时都检查所属项目，避免跨项目运行。

### 执行与协同：任务有执行者和交付物

- **本地任务委派**：已审核且指派给项目数字员工的任务，可在项目工作台委派给 Codex 或 OpenCode，随后查看状态并回收结果和 Workdir 产物。Agent 也可在启用项目专属 Sandbox 后开展按轮次的编码协作；崩溃恢复的真实集成验证与安全加固仍在迭代。
- **多仓库 Git 工作区**：项目可绑定多个仓库；根任务使用独立 worktree 和分支，并选择本次任务的仓库。凭据留在可信服务端，推送需要人工批准。[配置教程](docs/intro/project-git.md) · [配置参考](docs/advanced/project-git-reference.md)
- **外部渠道桥接**：配置 Multica 后，可拉取外部议题和任务作为待审核提议，也可委派并核对远端工作；元垒保留治理事实与本地委派状态。未配置 Multica 时，项目治理和本地编码委派仍可用。

### 督查与汇报：进展可回看

- **跨项目督查板**：汇总当前用户可见项目的待处理议题、待审核任务、待决策事项和失败或中断的执行；单项目工作台提供蓝图、治理、委派和汇报入口。督查板读取治理与 Run 事实，不另建一份执行状态。
- **项目概览与自定义页面**：默认 Dashboard 展示蓝图、议题—决策—任务关系图、汇报和执行动态；项目数字员工也可维护静态 HTML/CSS 展示页。自定义页面只负责展示，不自动生成督查结论或周期报告。

### 沿用并扩展平台能力

元垒继续提供 Yuxi 的知识库、图谱、Skills、MCP、多智能体和隔离工作区，并增加按当前模型渠道识别输入模态、原生图片输入和能力状态展示。个人空间文件可在首次发送消息时再绑定对话；中文输入法组合态和手动发送锁也在输入区生效。各项差异的状态、边界和上游合并条件见[元垒差异化功能索引](docs/develop-guides/yuanlei/features/README.md)。

## 跟随 Yuxi 上游

元垒跟踪上游 `xerrors/Yuxi`，持续合并上游的新能力与修复。当前元垒独立版本为 `0.1.0`。

| 项目 | 版本 | 上游基线 |
|---|---|---|
| 元垒 | 0.1.0 | Yuxi v0.7.3 @ dee83624（2026-09-24） |

- 上游 README 原文镜像：[README.yuxi.md](README.yuxi.md) · [README.yuxi.en.md](README.yuxi.en.md)
- 同步基线单一事实源：[baseline.json](docs/develop-guides/yuanlei/baseline.json)
- 同步流程、冲突分类与取舍规则：[上游同步流程](docs/develop-guides/yuanlei/upstream-sync.md)
- 上游项目主页：<https://xerrors.github.io/Yuxi/>

Yuxi 提供的基础能力继续可用：

- **知识库与 RAG**：多格式入库、Embedding/Rerank、检索测试、RAG 评估。
- **知识图谱与知识导图**：Milvus 抽取、Neo4j 图谱、节点探索与文件结构导图。
- **多智能体与扩展生态**：SubAgents、Skills、MCP、Tools 与 Agent 配置。
- **沙盒工作区与产物**：隔离文件系统、文件生成、在线预览与下载。
- **团队治理与运行管理**：多租户、用户与部门权限、模型配置、API Key 与 Dashboard。

<details>
<summary><strong>展开上游能力截图</strong></summary>

![Yuxi 统一智能体工作台](https://xerrors.oss-cn-shanghai.aliyuncs.com/github/image-20260825145022410.png)

![Yuxi 知识库与 RAG](https://xerrors.oss-cn-shanghai.aliyuncs.com/github/image-20260830144756161.png)

![Yuxi 多智能体编排](https://xerrors.oss-cn-shanghai.aliyuncs.com/github/image-20260825152252874.png)

![Yuxi 沙盒工作区与文件产物](https://xerrors.oss-cn-shanghai.aliyuncs.com/github/image-20260825152123583.png)

</details>


## 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | Vue 3 · Vite · Ant Design · G6 |
| 后端 | FastAPI · LangGraph · ARQ worker |
| 存储 | PostgreSQL · Redis · MinIO · Milvus · Neo4j |
| 文档处理 | MinerU · PaddleX · RapidOCR |
| 部署 | Docker Compose |

## 快速启动

### 前置条件

安装 [Docker Engine](https://docs.docker.com/get-docker/) 和 Docker Compose，并准备一个可用的大模型 API。

### 1. 获取代码并初始化

```bash
git clone https://github.com/Sxyon/Yuanlei.git
cd Yuanlei

# Linux/macOS
./scripts/init.sh

# Windows PowerShell
.\scripts\init.ps1
```

初始化脚本会创建 `.env`、读取 SiliconFlow API Key，并为 JWT、API Key 派生和 Sandbox provisioner 生成独立的安全密钥。也可以手动复制 `.env.template` 并填写这些值。

### 2. 启动开发环境

```bash
docker compose up --build -d
docker compose ps
curl --fail http://localhost:5050/api/system/ready
```

返回的 `status` 为 `ready` 后，打开 [http://localhost:5173](http://localhost:5173)，按页面提示初始化超级管理员并登录。API 文档位于 [http://localhost:5050/docs](http://localhost:5050/docs)。

从旧上游版本升级到当前元垒基线时，先阅读[生产部署与升级](docs/advanced/deployment.md)，在停机窗口完成备份和迁移。

## 文档导航

- [项目工作台使用指南](docs/intro/project-workbench.md)：蓝图、议题、决策、任务、委派和督查的操作路径。
- [项目治理与督查机制](docs/mechanisms/project-governance.md)：新增模块的事实归属、审核流程和执行边界。
- [元垒与上游 Yuxi](docs/develop-guides/yuanlei/README.md)：fork 关系、改动归属规则和同步基线。
- [上游同步流程](docs/develop-guides/yuanlei/upstream-sync.md)：四阶段合并流程与冲突取舍规则。
- [差异化功能索引](docs/develop-guides/yuanlei/features/README.md)：元垒新增和改变的行为。
- [框架开发约定](AGENTS.md)、[架构说明](ARCHITECTURE.md)：参与开发前阅读。
- 上游用户文档站：<https://xerrors.github.io/Yuxi/>（快速开始、模型配置、知识库、智能体、部署）。
- 上游版本记录：<https://github.com/xerrors/Yuxi/releases>。

## 参与贡献

欢迎提交 Issue、改进文档、修复 Bug 和贡献功能。开发流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证与致谢

元垒基于 Yuxi 构建，遵循 MIT License，详见 [LICENSE](LICENSE)。Docker Compose 引入的第三方组件遵循各自许可证；再分发和商业部署前，请按实际镜像版本核对上游许可和源码义务，相关边界见[生产部署指南](docs/advanced/deployment.md)。

感谢 [xerrors/Yuxi](https://github.com/xerrors/Yuxi) 及其贡献者提供的基础平台。

Yuxi 的实现和文档参考了以下开源项目：

- [LightRAG](https://github.com/HKUDS/LightRAG)：早期图谱构建和检索思路；
- [DeepAgents](https://github.com/langchain-ai/deepagents)：深度智能体框架；
- [DeerFlow](https://github.com/bytedance/deer-flow)：沙盒智能体架构思路；
- [RAGFlow](https://github.com/infiniflow/ragflow)：文档分块策略；
- [LangGraph](https://github.com/langchain-ai/langgraph)：智能体编排基础；
- [QwenPaw](https://github.com/agentscope-ai/QwenPaw)：模型配置和个人文件区域设计。
