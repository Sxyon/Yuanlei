# 模型输出上限与截断

状态：已实现
类型：上游缺陷修复
主要 Owner：backend/package/yuxi/models/chat.py

## 需求与失败场景

长任务在 4096 token 处截断。Anthropic 兼容模型不在 SDK profile 中时命中短输出 fallback；部分输出和工具参数需要可靠的完整性判断。

## 必须保留的业务语义

调用显式额度优先于模型默认；最大能力只用于合法性判断；截断响应保留内容与结束原因，不能执行其工具或自动完成工作；已有工具步骤不自动重放。

## 与 Yuxi 的边界

直接扩展现有供应商模型 JSON 与运行边界，不新增表或供应商配置系统。元垒把输出截断纳入原有 Run failed 和部分消息通道。

## 稳定集成点

供应商 enabled_models JSON、Redis ModelInfo、load_chat_model/select_model、Agent model middleware、chat_service 部分输出与 Run 错误通道。

## 上游依赖

LangChain 供应商 SDK 的请求装配、response_metadata 与 ModelError 非重试语义。

## 合并判断

上游改变消息合并或模型 middleware 时，确认结束原因保留到工具执行前；上游新增输出配置时优先采用等价能力。

## 替换或删除条件

上游提供等价配置传递与截断结果处理时采用上游实现；供应商改变模型协议或能力时重新核对默认配置。

## 决策与证据

[输出配置与截断决策](../decisions/implemented/2026-10-09-model-output-limits.md)；协议与负向测试入口为 `backend/test/unit/models/test_output_limits.py`，运行链路证据见 `backend/test/e2e/test_output_limits_e2e.py`。
