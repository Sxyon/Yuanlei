# 开发 Gitea 局域网端口

状态：implemented
类型：feature
Owner：docker-compose.yml

## 问题

上游开发 Compose 将 Gitea 的 HTTP 和 SSH host 端口绑定在 `127.0.0.1`，同一局域网中的其他设备无法直连这个测试用 Gitea。元垒需要让这些设备访问已有实例，同时保留仓库、SQLite 数据库和配置密钥。

## 决策

`git-integration` profile 的 Gitea 两个 host 端口绑定在 `0.0.0.0`。容器内端口、镜像、数据库路径和两个持久化 bind mount 保持原值。变更端口绑定时先核对实际挂载并备份两个状态目录，再只重建 Gitea。Project Git 服务仍使用 Compose 网络内的 `gitea:3000` 和 `gitea:2222`。

## 替代方案

保留回环绑定并用端口转发访问，能按设备单独开放，但每台客户端都需要额外配置。绑定单个宿主局域网 IP 可缩小暴露范围，但 IP 变化后需要同步修改 Compose。

## 后果

HTTP 和 SSH 同时监听宿主机的所有 IPv4 接口，包括可能存在的 VPN 接口。宿主机防火墙和网络策略负责限制可访问的设备；Gitea 账号和仓库权限仍需独立管理。`ROOT_URL` 继续指向容器网络地址，局域网浏览器中的绝对链接可能无法使用；调整公开 URL 应另行核对内部集成链路。同步上游 Compose 时保留该端口差异，除非访问需求消失。

## 验证

用 `docker inspect` 核对两个 bind mount 和 `0.0.0.0` 端口映射；重建后 Gitea healthcheck 为 healthy，HTTP `/api/healthz`、SQLite `PRAGMA integrity_check` 和已有仓库可读。真实局域网客户端的连通性受宿主机防火墙与网络隔离影响，需从客户端验证。
