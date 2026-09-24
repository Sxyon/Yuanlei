# Yuanlei (元垒)

Yuanlei (元垒) is an AI hub for **individuals** and **enterprises** in the AI era. It serves as your executive office or CEO office, bringing together advice and decision-making, oversight and reporting, and execution and collaboration.

Yuanlei is developed from [Yuxi](https://github.com/xerrors/Yuxi). It retains Yuxi's multi-tenant knowledge base, knowledge graph, LangGraph multi-agent capabilities, MCP/Skills, sandboxes and access controls. Centered on projects, it fulfills three core responsibilities: advice and decision-making, oversight and reporting, and execution and collaboration.

[![Release](https://img.shields.io/github/v/release/Sxyon/Yuanlei?color=046A82)](https://github.com/Sxyon/Yuanlei/releases/latest)
[![License](https://img.shields.io/github/license/Sxyon/Yuanlei.svg?logo=github)](https://github.com/Sxyon/Yuanlei/blob/main/LICENSE)
[![Yuxi upstream](https://img.shields.io/badge/Yuxi-v0.7.3-046A82)](https://github.com/xerrors/Yuxi)

[Governance](docs/develop-guides/yuanlei/README.md) · [Feature index](docs/develop-guides/yuanlei/features/README.md) · [Upstream README mirror](README.yuxi.en.md) · [中文](README.md)

## Yuanlei features

### Organize digital employees around projects

Bind an agent to a project to make it a digital employee that works within that project. Each project can override model and runtime settings. The project scope is checked when a request enters the system and again when it runs.

### Give each project a page for its progress

Project agents can create and maintain a project Dashboard. The current version displays a static HTML/CSS page within the project. Updates use revision checks, and conflicts or file errors are reported explicitly. The Dashboard is currently a display page; it does not generate reports or perform automated oversight.

### Execute and collaborate within projects

- **Multi-repository Git workspaces:** Bind multiple repositories to a project. Each root task uses its own worktree and branch and selects the repositories it needs. Credentials stay with trusted server processes, and pushing requires human approval. [Configuration tutorial](docs/intro/project-git.md) · [Configuration reference](docs/advanced/project-git-reference.md)
- **Agent coding collaboration:** With a dedicated project sandbox enabled, an agent can start, continue, await, and cancel multi-turn coding CLI tasks. Collaboration works turn by turn; integration checks for crash recovery and security hardening remain in progress.
- **Git error recovery:** Git tool argument errors return to the model so it can correct and retry. Branch naming and Run asset checks also handle the relevant retry boundaries.

### Work with files and messages more smoothly

- Select files from personal space in a new conversation. Until the first send, references remain pending and the agent or project can still be changed; sending creates the conversation and records the references.
- Enter does not send a message while choosing Chinese IME candidates. With the manual send lock on, Enter inserts a newline.
- Removing symlinks from personal space leaves their targets intact. Sandbox deletion runs outside the database transaction so external waits do not block Run recovery.

See the [feature index](docs/develop-guides/yuanlei/features/README.md) for implementation status, boundaries, and upstream merge notes, and the [decision records](docs/develop-guides/yuanlei/decisions/README.md) for design choices.

## Tracking upstream Yuxi

Yuanlei tracks `xerrors/Yuxi` and keeps merging upstream features and fixes. The current independent Yuanlei version is `0.1.0`.

| Project | Version | Upstream baseline |
|---|---|---|
| Yuanlei | 0.1.0 | Yuxi v0.7.3 @ dee83624 (2026-09-24) |

- Upstream README mirrors: [README.yuxi.md](README.yuxi.md) · [README.yuxi.en.md](README.yuxi.en.md)
- Single source of truth: [baseline.json](docs/develop-guides/yuanlei/baseline.json)
- Merge process and conflict rules: [upstream sync](docs/develop-guides/yuanlei/upstream-sync.md)
- Upstream project site: <https://xerrors.github.io/Yuxi/>

The capabilities inherited from Yuxi remain available:

- **Knowledge base and RAG**: multi-format ingestion, Embedding/Rerank, retrieval tests, RAG evaluation.
- **Knowledge graph and knowledge map**: Milvus extraction, Neo4j graph, node exploration, file-structure map.
- **Multi-agent and extension ecosystem**: SubAgents, Skills, MCP, Tools and agent configuration.
- **Sandbox workspace and artifacts**: isolated filesystem, generated files, in-browser preview and download.
- **Team governance and operations**: multi-tenancy, user and department permissions, model configuration, API keys and dashboard.

<details>
<summary><strong>View upstream feature screenshots</strong></summary>

![Yuxi unified agent workspace](https://xerrors.oss-cn-shanghai.aliyuncs.com/github/image-20260825145022410.png)

![Yuxi knowledge base and RAG](https://xerrors.oss-cn-shanghai.aliyuncs.com/github/image-20260830144756161.png)

![Yuxi multi-agent orchestration](https://xerrors.oss-cn-shanghai.aliyuncs.com/github/image-20260825152252874.png)

![Yuxi sandbox workspace and file artifacts](https://xerrors.oss-cn-shanghai.aliyuncs.com/github/image-20260825152123583.png)

</details>

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | Vue 3 · Vite · Ant Design · G6 |
| Backend | FastAPI · LangGraph · ARQ worker |
| Storage | PostgreSQL · Redis · MinIO · Milvus · Neo4j |
| Document processing | MinerU · PaddleX · RapidOCR |
| Deployment | Docker Compose |

## Quick start

### Prerequisites

Install [Docker Engine](https://docs.docker.com/get-docker/) and Docker Compose, and prepare a working LLM API.

### 1. Clone and initialize

```bash
git clone https://github.com/Sxyon/Yuanlei.git
cd Yuanlei

# Linux/macOS
./scripts/init.sh

# Windows PowerShell
.\scripts\init.ps1
```

The init script creates `.env`, reads the SiliconFlow API key, and derives independent secrets for JWT, API key derivation and the sandbox provisioner. You can also copy `.env.template` manually and fill in the values.

### 2. Start the development environment

```bash
docker compose up --build -d
docker compose ps
curl --fail http://localhost:5050/api/system/ready
```

Once `status` is `ready`, open [http://localhost:5173](http://localhost:5173), initialize the super administrator and sign in. API docs are at [http://localhost:5050/docs](http://localhost:5050/docs).

When upgrading from an older upstream layout to the current Yuanlei baseline, read [production deployment](docs/advanced/deployment.md) first and complete backup and migration in a maintenance window.

## Documentation

- [Yuanlei and upstream Yuxi](docs/develop-guides/yuanlei/README.md): fork relationship, change ownership rules and sync baseline.
- [Upstream sync](docs/develop-guides/yuanlei/upstream-sync.md): four-phase merge process and conflict rules.
- [Feature index](docs/develop-guides/yuanlei/features/README.md): features Yuanlei adds or changes.
- [Repository conventions](AGENTS.md) and [architecture](ARCHITECTURE.md): read before contributing.
- Upstream documentation site: <https://xerrors.github.io/Yuxi/> (quick start, model configuration, knowledge bases, agents and deployment).
- Upstream releases: <https://github.com/xerrors/Yuxi/releases>.

## Contributing

Issues, documentation improvements, bug fixes and features are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow.

## License and credits

Yuanlei is built on Yuxi and licensed under the MIT License; see [LICENSE](LICENSE). Third-party components pulled in by Docker Compose keep their own licenses; check upstream licenses and source obligations against the actual image versions before redistribution or commercial deployment, as described in the [production deployment guide](docs/advanced/deployment.md).

Thanks to [xerrors/Yuxi](https://github.com/xerrors/Yuxi) and its contributors for the underlying platform.

Yuxi's implementation and documentation draw on these open-source projects:

- [LightRAG](https://github.com/HKUDS/LightRAG): early ideas for graph construction and retrieval;
- [DeepAgents](https://github.com/langchain-ai/deepagents): deep agent framework;
- [DeerFlow](https://github.com/bytedance/deer-flow): sandbox agent architecture;
- [RAGFlow](https://github.com/infiniflow/ragflow): document chunking strategy;
- [LangGraph](https://github.com/langchain-ai/langgraph): agent orchestration;
- [QwenPaw](https://github.com/agentscope-ai/QwenPaw): model configuration and personal file area design.
