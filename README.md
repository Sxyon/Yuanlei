# 元垒（Yuanlei）

元垒是一个基于 [Yuxi](https://github.com/xerrors/Yuxi) 的个人化改造版本：保留上游的多租户知识库、知识图谱、LangGraph 多智能体、MCP/Skills、沙盒与权限能力，并围绕「项目」补齐 Git 多仓库工作区、项目数字员工和更贴合个人协作习惯的交互。

[![Release](https://img.shields.io/github/v/release/Sxyon/Yuanlei?color=046A82)](https://github.com/Sxyon/Yuanlei/releases/latest)
[![License](https://img.shields.io/github/license/Sxyon/Yuanlei.svg?logo=github)](https://github.com/Sxyon/Yuanlei/blob/main/LICENSE)
[![Yuxi 上游基线](https://img.shields.io/badge/Yuxi-v0.7.3-046A82)](https://github.com/xerrors/Yuxi)

[元垒治理与决策](docs/develop-guides/yuanlei/README.md) · [差异化功能索引](docs/develop-guides/yuanlei/features/README.md) · [上游 README 镜像](README.yuxi.md) · [English](README.en.md)

## 元垒特性

### Project Git 多仓库工作区

为项目绑定多个 Git 仓库，每个根任务获得独立 worktree 和任务分支；凭据使用 AES-256-GCM 加密，可信进程独占 fetch/push，Agent 只能通过需要人工审批的 `git_push_branch` 推送。用户可以选择参与本次任务的仓库，未被选择的仓库不会产生远端副作用。

- 教程：[Project Git 配置](docs/intro/project-git.md)
- 参考：[仓库、配置和分支](docs/advanced/project-git-reference.md)

### 项目数字员工

把 Agent 绑定到项目，组成只在所属项目内工作的数字员工：绑定后运行边界 fail-closed，模型与运行参数支持项目级覆盖，同一绑定行是后续项目记忆、常驻沙盒与 Workflow 成员的挂载点。

### Git 工具错误自愈与 DeepSeek 兼容

Git 工具的输入校验失败收敛为模型可见的 error ToolMessage，模型可以修正参数重试；分支 slug 大小写静默归一；Run manifest 指纹排除 worktree 运行时派生字段，恢复重试不再误判资产漂移。

### 个人空间附件引用

新对话引用个人空间文件时，选择器浏览个人空间而不是项目 Workdir；首次发送前引用只保留在前端缓存，发送时才落库，智能体与项目在发送前始终可以切换。

### 输入区与工作区体验

- 中文输入法组合态回车不触发发送，避免拼音候选误发。
- 提供手动发送锁，锁定状态下回车改为换行。
- 个人空间删除含符号链接的目录时，只删除链接目录项，链接目标保持不变。

### Runtime cleanup 事务外执行

Sandbox 删除等待从数据库事务中拆出：短事务预检、事务外删除、短事务复核并清除 fence，Run 恢复事务与 reconciler 不再被外部等待阻塞。

完整清单、语义 Owner 和上游合并注意项见[元垒差异化功能索引](docs/develop-guides/yuanlei/features/README.md)；这些改动的原因与取舍见[元垒决策记录](docs/develop-guides/yuanlei/decisions/README.md)。

## 跟随 Yuxi 上游

元垒跟踪上游 `xerrors/Yuxi`，持续合并上游的新能力与修复。当前元垒独立版本为 `0.1.0`。

| 项目 | 版本 | 上游基线 |
|---|---|---|
| 元垒 | 0.1.0 | Yuxi v0.7.3 @ 5a1bdc3c（2026-09-18） |

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


## 赞助商

| 赞助商 | 介绍 |
| :---: | :--- |
| <img src="https://xerrors.oss-cn-shanghai.aliyuncs.com/github/%E4%B8%8B%E8%BD%BD.jpeg" alt="Fluxion AI LOGO" width="180" /> | Fluxion AI面向个人开发者、技术团队与企业，通过统一API接入并管理全球主流AI模型；通过多线路动态调度提升可用性，模型表现、响应时间与费用透明可查。根据不同模型与线路，API调用成本较官方或基准价格可降低40%—98%。专属链接[注册](https://fluxionai.space/register?source=github&campaign=yuxi&promo=YUXI) 获 $7 API 额度 |

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
