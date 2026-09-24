---
name: coding-executor
slug: coding-executor
description: "使用沙盒内的 opencode/codex 编码执行器完成实现类任务：先出计划、再分轮实现，并在轮次之间检查结果与调整方向。当用户要求在项目代码中实现功能、修复缺陷、重构或让编码代理接管一段开发任务时使用此技能。"
version: "2026.09.19"
tool_dependencies: ["coding_session_start", "coding_session_send", "coding_session_status", "coding_session_await", "coding_session_control", "coding_session_list"]
---

# 编码执行器技能

当任务需要真实修改项目代码、运行测试或让编码代理分轮推进实现时，使用本技能。

## 可用工具

- `coding_session_start`：启动编码会话并运行第一轮；默认先跑只读计划轮（opencode `--agent plan` / codex `-s read-only`）。
- `coding_session_send`：在既有会话中追加一轮执行消息，用于按计划推进实现。
- `coding_session_status`：查看会话状态、turn 时间线与最近事件，用于判断是否需要调整方向。
- `coding_session_await`：等待当前轮结束（当前为同步执行语义，返回最新状态）。
- `coding_session_control`：控制会话，当前支持 `cancel`。
- `coding_session_list`：列出当前用户的编码会话，用于继续既有会话而不是重复启动。

## 选择执行器

- `opencode`：适合常规实现、重构与多轮迭代，支持计划 agent 与原生会话续跑。
- `codex`：适合需要 Responses API 模型端点与严格沙盒策略的场景。
- 只有配置了对应凭据的执行器才会出现在会话列表中；执行器不可用时工具会显式报错，不要假设可以静默切换。

## 操作流程

1. 先用 `coding_session_start(executor, task, plan_first=true)` 让执行器给出计划；把计划要点复述给用户并等待确认（默认审批模式会先要求用户批准启动）。
2. 确认后使用 `coding_session_send` 分轮推进实现；每轮结束用 `coding_session_status` 检查结果，必要时调整下一条消息。
3. 会话失败或偏离目标时使用 `coding_session_control(action="cancel")` 终止，不要在没有检查结果的情况下连续推进。
4. 会话产物位于项目 Workdir；需要把关键文件展示给用户时使用 `present_artifacts`。
5. 不要把密钥写入消息或文件；执行器凭据由沙盒环境注入，密钥不会出现在会话事件中。
