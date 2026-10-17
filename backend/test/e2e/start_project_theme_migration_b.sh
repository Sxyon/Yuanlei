#!/usr/bin/env bash
# 启动S06隔离实例B；保留既有B数据库和主题卷，不触碰日常库。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
CONTAINER="${THEME_EVIDENCE_CONTAINER:-yuanlei-s06-b}"
VOLUME="${THEME_EVIDENCE_VOLUME:-yuanlei-s06-b-data}"
DB="${THEME_EVIDENCE_DB:-yuanlei_s06_evidence_b}"
IMAGE="${THEME_EVIDENCE_IMAGE:-yuanlei-api:0.7.3}"
PORT="${THEME_EVIDENCE_PORT:-15065}"
NETWORK="${THEME_EVIDENCE_NETWORK:-yuanlei_app-network}"

PGURL="$(docker inspect yuanlei-api-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^POSTGRES_URL=//p')"
[ -n "$PGURL" ] || { echo "无法从api容器读取POSTGRES_URL" >&2; exit 1; }
if ! docker compose exec -T postgres sh -c "psql -U postgres -tAc \"SELECT 1 FROM pg_database WHERE datname='${DB}'\"" | grep -q 1; then
  docker compose exec -T postgres sh -c "createdb -U postgres '${DB}'"
fi
docker volume inspect "$VOLUME" >/dev/null 2>&1 || docker volume create "$VOLUME" >/dev/null
docker run --rm -v "${VOLUME}:/tmp/s06-b" alpine chown -R 1000:1000 /tmp/s06-b
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" --network "$NETWORK" -p "127.0.0.1:${PORT}:5060" \
  --user 1000:1000 -w /app --env-file .env \
  -e POSTGRES_URL="$PGURL" -e THEME_EVIDENCE_DB="$DB" -e RUNNING_IN_DOCKER=true -e YUXI_ENV=development \
  -e YUXI_INSTANCE_ID=instance-s06-b-evidence \
  -e YUXI_GIT_STATE_DIR=/tmp/s06-b/git-state \
  -e YUXI_SKILL_DATA_DIR=/tmp/s06-b/skill-sources \
  -e YUXI_SKILL_PROJECTION_DIR=/tmp/s06-b/skill-projections \
  -e YUXI_RUNTIME_DIR=/tmp/s06-b/runtime \
  -v "${VOLUME}:/tmp/s06-b" \
  -v "${ROOT}/backend/server:/app/server" \
  -v "${ROOT}/backend/package:/app/package" \
  -v "${ROOT}/backend/test:/app/test" \
  -v "${ROOT}/backend/scripts:/app/scripts" \
  "$IMAGE" python /app/test/e2e/project_theme_migration_app.py >/dev/null
for _ in $(seq 1 60); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/api/system/health" 2>/dev/null || true)"
  [ "$code" = "200" ] && break
  sleep 1
done
if [ "${code:-}" != "200" ]; then
  echo "B未恢复health 200" >&2
  docker logs --tail 20 "$CONTAINER" >&2 || true
  exit 1
fi
echo "B health 200; 私有session在容器/tmp/s06-b/session.json（不要写入文档或Git）"
