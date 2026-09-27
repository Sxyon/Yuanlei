# 将开发 PostgreSQL 数据放入命名卷

状态：implemented
类型：bug-fix
Owner：docker-compose.yml

## 问题

开发 Compose 把宿主状态目录绑定到 `/var/lib/postgresql`。`postgres:16` 镜像在 `/var/lib/postgresql/data` 声明 volume，实际数据库落入 Docker 匿名卷；复制状态目录不会包含数据库，删除并重建容器后也不会重新挂载原匿名卷。在 Docker Desktop 上直接把宿主目录绑定到实际数据目录会造成首次初始化时所有权不稳定。

## 决策

Compose 将项目作用域的 `postgres-data` 命名卷挂载到 `/var/lib/postgresql/data`。数据库不依赖宿主 bind mount 的所有权映射，普通容器重建继续使用同一命名卷。

## 替代方案

直接把宿主目录绑定到 `/var/lib/postgresql/data` 可以随目录复制数据，但 Docker Desktop 的所有权映射使该方案在当前开发环境无法可靠初始化。继续使用匿名卷则使普通容器重建丢失原卷关联。

## 后果

新建开发环境的数据库随 Compose 项目名隔离，在 `docker compose down` 后保留，但不包含在 `${YUXI_STATE_DIR}` 的目录副本中。迁移或备份环境时需要单独处理命名卷。已有环境必须在停机后迁移其匿名卷中的数据，不能仅改挂载目标并直接启动。同步上游 Compose 时要核对镜像版本和实际 `PGDATA`。

## 验证

`docker compose config` 展示项目命名卷到容器 `/var/lib/postgresql/data` 的挂载；启动后通过容器实际挂载、Schema 迁移结果和 `/api/system/ready` 核对，并在普通 `down`/`up` 后重新读取同一数据库。
