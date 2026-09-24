# 元垒（Yuanlei）

元垒（Yuanlei）是 AI 时代的 **个人** / **企业** 的AI中枢系统，是您的总裁办、CEO办公室，集参谋与决策、督查与汇报、执行与协同为一体 的 AI 平台。

元垒是一个基于 [Yuxi](https://github.com/xerrors/Yuxi) 的二次开发改造版本：保留上游的多租户知识库、知识图谱、LangGraph 多智能体、MCP/Skills、沙盒与权限能力，并围绕「项目」实现参谋与决策、督查与汇报、执行与协同 三大核心职责。

[![Release](https://img.shields.io/github/v/release/Sxyon/Yuanlei?color=046A82)](https://github.com/Sxyon/Yuanlei/releases/latest)
[![License](https://img.shields.io/github/license/Sxyon/Yuanlei.svg?logo=github)](https://github.com/Sxyon/Yuanlei/blob/main/LICENSE)
[![Yuxi 上游基线](https://img.shields.io/badge/Yuxi-v0.7.3-046A82)](https://github.com/xerrors/Yuxi)

[元垒治理与决策](docs/develop-guides/yuanlei/README.md) · [差异化功能索引](docs/develop-guides/yuanlei/features/README.md) · [上游 README 镜像](README.yuxi.md) · [English](README.en.md)

## 元垒特性

### 以项目组织数字员工

将 Agent 绑定到项目，组成在所属项目内工作的数字员工。项目可以覆盖模型和运行参数；请求接入与执行时都会校验项目范围，防止数字员工在其他项目运行。

### 让项目进展有可查看的页面

项目数字员工可以创建和维护项目 Dashboard。当前版本提供静态 HTML/CSS 页面，可在项目内查看；页面更新有版本校验，冲突或文件异常会明确提示。Dashboard 目前是展示页面，不承担自动督查或报告生成。

### 在项目中执行与协作

- **多仓库 Git 工作区**：项目可绑定多个仓库；根任务使用独立的 worktree 和分支，并选择本次任务要使用的仓库。凭据保留在可信服务端，推送需要人工批准。[配置教程](docs/intro/project-git.md) · [配置参考](docs/advanced/project-git-reference.md)
- **Agent 编码协作**：启用项目专属 Sandbox 后，Agent 可通过编码 CLI 发起、继续、等待和取消多轮编码任务。当前支持按轮次协作；崩溃恢复的真实集成验证和安全加固仍在迭代。
- **Git 错误恢复**：Git 工具的参数错误会返回给模型，便于修正后重试；分支名称和 Run 恢复时的资产校验也兼容相应边界。

### 顺畅、安全地使用工作空间

- 新对话可以从个人空间选择文件；首次发送前只保存待引用文件，仍可切换 Agent 和项目，发送时才创建对话并登记引用。
- 中文输入法选字时按回车不会误发消息；手动发送锁开启后，回车用于换行。
- 清理个人空间中的符号链接时保留链接目标；Sandbox 删除在数据库事务外执行，避免外部等待阻塞 Run 恢复。

各项能力的实现状态、边界和上游合并注意项见[元垒差异化功能索引](docs/develop-guides/yuanlei/features/README.md)；设计取舍见[元垒决策记录](docs/develop-guides/yuanlei/decisions/README.md)。

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
