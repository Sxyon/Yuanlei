# 候选发布验证与 CLI 独立发布

状态：implemented
类型：process
Owner：.github/workflows/system-tests.yml

## 问题

应用发布与 CLI 包版本独立，但应用 Release 触发未升版 CLI 的重复 PyPI 上传。候选 tag 缺少完整 CI 触发，运行链路中的部分 HTTP 测试缺少认证变量而跳过，Ruff 安装整个后端依赖使检查受无关镜像下载失败影响。

## 决策

`.github/workflows` 中的发布门禁监听 `v[0-9]*` tag，覆盖工程契约、后端、前端、运行链路、依赖审计和文档构建；分支继续使用原有路径过滤。文档部署保留 main 分支限制。Ruff workflow 从后端锁文件读取工具版本并通过官方 PyPI 独立安装，检查 lint、格式和导入顺序。

运行链路 workflow 为 Run 结果归属、API Key 和 Skill 授权测试显式传入 CI 初始化的账号。工程契约 verifier 同步要求这些命令携带认证变量；恢复缺少账号的命令会使 gate 失败。

`publish-yuxi-cli.yml` 仅保留手动发布入口，CLI 包版本由其 pyproject 拥有。应用 Release 不触发 PyPI 写入。维护者以最近的正式 tag 为发布说明基线，候选验证成功后在相同提交新增正式 tag；操作由[贡献指南](../../contributing.md#候选版本与正式发布)维护。

## 替代方案

- 仅依赖 main 的路径过滤检查：无法直接查看候选 tag 的全部发布门禁结果。
- 应用发布时跳过 PyPI 已有文件：掩盖未升版 CLI 代码的误发布，继续耦合独立产品版本。
- Ruff 安装全部后端依赖：增加耗时和与格式检查无关的下载失败面。

## 后果

候选和正式 tag 都运行完整 CI，增加运行成本。CLI 发布需要维护者显式操作。真实 provider 与生产备份恢复仍由相应探针和部署演练验证，workflow 成功不证明这些未执行范围。

Runtime System Tests 的 job 预算为 60 分钟，覆盖 GitHub 新 runner 冷缓存构建 sandbox-provisioner、API 和 worker 后的完整检查；构建阶段超时会使后续测试保持未执行并阻断发布。

## 验证

- `python3 -m unittest scripts.test_release_workflows` 验证真实 workflow 的发布事件；删除任一门禁的 tag 触发或恢复 CLI 的 release 触发均被负向案例拒绝。该检查由 trust workflow 执行。
- `python3 scripts/verify_engineering_contracts.py` 与 `python3 -m unittest scripts.test_verify_engineering_contracts` 检查认证命令接线；删除账号或密码参数会使对应 HTTP 门禁报错。
- `docker compose exec -T api uv run --no-sync --no-dev pytest test/integration/api/test_agent_run_result_causality.py test/integration/api/test_apikey_router.py test/integration/api/test_skill_artifact_authorization.py -q -rs` 在真实服务上通过 18 项，零跳过；断言 Run 持久化归属、API Key 生命周期与撤权后的 Skill artifact 访问。
- Actionlint 校验工作流语法；Ruff、后端 unit 和文档构建分别由实际命令验证。远端 workflow 结果在 PR 中记录，不以本地配置检查替代 GitHub 执行。
