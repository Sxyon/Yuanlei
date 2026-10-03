# 项目设置与资源管理

状态：部分实现；设置与弱关联已接入，Git 生命周期待实现与验收
类型：新增业务能力
主要 Owner：`backend/package/yuxi/services/project_service.py`

## 需求与失败场景

项目需要属性、名称与描述及资源管理，作为后续任务与通知的配置基础。负责人不代表访问授权，管理状态不代表执行禁用。Git 任务跨智能体执行需要稳定工作区与可观察的遗留成果，不能在运行失败或切换智能体时丢失。

## 必须保留的业务语义

项目默认计划中、无优先级、负责人为创建者、日期为空。描述最多 255 字符。知识库关联单向、不授予权限、不自动加入每次运行。Git 资源完整检出所选分支，不限制仓库内任务修改范围；执行模式与审批模式相互独立。任务共享工作区、持续占用、排队与人工清理保护用户修改，审批在产生副作用的真实边界执行。

## 与 Yuxi 的边界

依赖 Project 可见性、ProjectAgent 绑定、项目任务与 AgentRun 请求执行链、UserWorkspace 路径边界和现有 Git 凭据、审批、Gitea provider。新增持久化由 yuanlei schema 管理，不改变上游项目状态与授权语义。

## 稳定集成点

Project service/repository 拥有设置与所有权；知识库权限 Owner 决定关联可见性；Git executor、请求队列与任务执行服务拥有工作区、排队和外部操作。

## 上游依赖

依赖 Project/Conversation 身份、AgentRun ownership、知识库权限解析、UserWorkspace 与 Git 审批链路。

## 合并判断

上游调整对应 Owner 时迁移集成点，保留管理属性不授权、关联不授权、工作成果不丢失和保护规则在副作用边界生效的语义。

## 替换或删除条件

上游提供等价的设置、弱关联、任务工作区、持续占用与受保护 Git 操作时逐项采用并缩小差异；业务需求退出时先核对持久数据与已有工作成果。

## 决策与证据

- [项目设置与任务 Git 资源生命周期](../decisions/proposed/2026-10-03-project-settings-resources.md)
- [现有 Project Git 语义](project-git-worktrees.md)
