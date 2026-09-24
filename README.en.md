# Yuanlei (元垒)

Yuanlei is a personal fork of [Yuxi](https://github.com/xerrors/Yuxi): it keeps the multi-tenant knowledge base, knowledge graph, LangGraph multi-agent orchestration, MCP/Skills, sandbox and permission capabilities, and adds project-scoped Git workspaces, project digital employees and interaction refinements.

[![Release](https://img.shields.io/github/v/release/Sxyon/Yuanlei?color=046A82)](https://github.com/Sxyon/Yuanlei/releases/latest)
[![License](https://img.shields.io/github/license/Sxyon/Yuanlei.svg?logo=github)](https://github.com/Sxyon/Yuanlei/blob/main/LICENSE)
[![Yuxi upstream](https://img.shields.io/badge/Yuxi-v0.7.3-046A82)](https://github.com/xerrors/Yuxi)

[Governance](docs/develop-guides/yuanlei/README.md) · [Feature index](docs/develop-guides/yuanlei/features/README.md) · [Upstream README mirror](README.yuxi.en.md) · [中文](README.md)

## Yuanlei features

### Project Git workspaces

Bind multiple Git repositories to a project. Every root task gets an isolated worktree and task branch. Credentials are encrypted with AES-256-GCM, a trusted process owns fetch and push, and the agent can push only through a human-approved `git_push_branch` tool. Users choose which repositories join the current task; repositories without an allocation produce no remote side effects.

- Tutorial: [Project Git configuration](docs/intro/project-git.md)
- Reference: [Repositories, credentials and branches](docs/advanced/project-git-reference.md)

### Project digital employees

Bind agents to a project so they work only inside it. The run boundary fails closed for bound agents, model and runtime parameters can be overridden per project, and the binding row carries future project memory, persistent sandboxes and workflow membership.

### Self-healing Git tool errors and DeepSeek compatibility

Git tool validation failures become model-visible error ToolMessages so the model can correct and retry; branch slugs are normalized to lower case; the Run manifest fingerprint excludes runtime-derived worktree fields, so resume retries no longer misjudge asset drift.

### Personal-space attachment references

When starting a new conversation, the attachment picker browses the user's personal space instead of the project workdir. References stay in frontend cache until the first send, so agent and project selection remains free until then.

### Input and workspace experience

- Enter during IME composition does not submit the message.
- A manual send lock turns Enter into a newline while locked.
- Deleting a personal-space directory that contains symlinks removes only the link entries and leaves targets untouched.

### Runtime cleanup outside the database transaction

Sandbox deletion no longer runs inside the database transaction: a short pre-check, an out-of-transaction delete, and a short re-check that clears the fence. Run recovery and the reconciler are no longer blocked by external waits.

See the [feature index](docs/develop-guides/yuanlei/features/README.md) for owners and upstream merge notes, and the [decision records](docs/develop-guides/yuanlei/decisions/README.md) for rationale.

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
- Upstream documentation site: <https://xerrors.github.io/Yuxi/>.
- Upstream releases: <https://github.com/xerrors/Yuxi/releases>.

## Contributing

Issues, documentation improvements, bug fixes and features are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow.

## License and credits

Yuanlei is built on Yuxi and licensed under the MIT License; see [LICENSE](LICENSE). Third-party components pulled in by Docker Compose keep their own licenses; check upstream licenses and source obligations against the actual image versions before redistribution or commercial deployment, as described in the [production deployment guide](docs/advanced/deployment.md).

Thanks to [xerrors/Yuxi](https://github.com/xerrors/Yuxi) and its contributors for the underlying platform.
