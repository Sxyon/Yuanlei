# 持久化开发 Gitea 配置

状态：implemented
类型：bug-fix
Owner：docker-compose.yml

## 问题

开发环境只把 `/var/lib/gitea` 绑定到宿主数据目录。Gitea 在 `/etc/gitea` 保存配置和密钥，镜像为该路径创建匿名 Docker volume。迁移宿主数据目录时，仓库和数据库可以复制，但原配置不会随之迁移。

## 决策

Compose 把 `/etc/gitea` 绑定到 `${YUXI_STATE_DIR}/gitea-config`。开发 Gitea 的数据库、仓库和配置由同一个状态目录共同持有。

## 替代方案

继续使用匿名 volume 并在每次环境迁移时手工定位和挂载旧卷。这会让状态目录的副本缺少恢复现有 Gitea 实例所需的密钥。

## 后果

备份或迁移开发 Gitea 时需要同时保留两个目录。`gitea-config` 含密钥，不进入 Git。同步上游 Compose 时应保留 `/etc/gitea` 的持久化挂载，直到上游提供等价方式。

## 验证

`docker compose --profile git-integration config` 展示两个宿主 bind mount；重建 Gitea 后，容器实际挂载 `/etc/gitea`，配置文件与原实例字节一致，并能读取原有仓库。
