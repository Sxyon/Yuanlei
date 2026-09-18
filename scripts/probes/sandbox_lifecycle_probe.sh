#!/usr/bin/env bash
# M0 探针：provisioner 沙盒生命周期契约取证。
#
# 使用独立 provisioner 实例（独立端口、独立 Docker 网络前缀与地址池、独立 scratch 挂载），
# 不触碰 compose 开发栈；结束时按 generation 删除沙盒并清理。
#
# 用法：bash scripts/probes/sandbox_lifecycle_probe.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE="${SANDBOX_IMAGE:-enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:1.11.0}"
PROV_IMAGE="${PROBE_PROVISIONER_IMAGE:-pat-sandbox-provisioner:0.7.3}"
PORT="${PROBE_PORT:-18002}"
RUN_ID="$(date +%s)"
NAME="pat-probe-provisioner-$RUN_ID"
SANDBOX_ID="$(printf 'probe:%s' "$RUN_ID" | shasum -a 256 | cut -c1-12)"
THREAD_ID="probe-$RUN_ID"
TOKEN="$(openssl rand -hex 24)"
SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/pat-lifecycle-probe.XXXXXX")"

say() { printf '\n==== %s ====\n' "$1"; }
api() { curl -s -o /tmp/pat-probe-resp.json -w '%{http_code}' -H "Authorization: Bearer $TOKEN" "$@"; }
json() { python3 -c "import json,sys; d=json.load(open('/tmp/pat-probe-resp.json')); print($1)"; }

cleanup() {
  GEN="$(curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT/api/sandboxes/$SANDBOX_ID" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("generation") or "")
except Exception: print("")' 2>/dev/null)"
  if [ -n "${GEN:-}" ]; then
    curl -s -X DELETE -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT/api/sandboxes/$SANDBOX_ID?expected_generation=$GEN" >/dev/null 2>&1 || true
  fi
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  rm -rf "$SCRATCH"
}
trap cleanup EXIT

say "scratch: $SCRATCH / sandbox_id: $SANDBOX_ID"

mkdir -p "$SCRATCH/user-data" "$SCRATCH/skill-projections"
mkdir -p "$SCRATCH/user-data/shared/$THREAD_ID/workspace/projects/probe"
mkdir -p "$SCRATCH/skill-projections/$THREAD_ID"
printf 'CHECK_YUXI_SANDBOX_ENV_EXISTS=True\n' > "$SCRATCH/sandbox.env"

say "start isolated provisioner"
docker run -d --name "$NAME" \
  -p "127.0.0.1:$PORT:8002" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$SCRATCH/user-data:/app/user-data" \
  -v "$SCRATCH/skill-projections:/app/skill-projections" \
  -v "$SCRATCH/sandbox.env:/app/sandbox.env:ro" \
  -v "$REPO_ROOT/docker/sandbox_provisioner/app.py:/app/app.py:ro" \
  -e PROVISIONER_BACKEND=docker \
  -e PROVISIONER_PUBLIC_URL="http://127.0.0.1:$PORT" \
  -e SANDBOX_PROVISIONER_TOKEN="$TOKEN" \
  -e SANDBOX_IMAGE="$IMAGE" \
  -e SANDBOX_IDLE_TIMEOUT_SECONDS=12 \
  -e SANDBOX_IDLE_CHECK_INTERVAL_SECONDS=2 \
  -e SANDBOX_EXEC_TIMEOUT_SECONDS=5 \
  -e SANDBOX_HEALTH_TIMEOUT_SECONDS=180 \
  -e DOCKER_NETWORK_PREFIX="pat-probe-sandbox" \
  -e DOCKER_ADDRESS_POOL="10.252.240.0/20" \
  -e DOCKER_SANDBOX_PREFIX="pat-probe-sandbox" \
  "$PROV_IMAGE" >/dev/null

for i in $(seq 1 30); do
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  [ "$i" = "30" ] && { echo "provisioner not healthy"; docker logs "$NAME" | tail -20; exit 1; }
  sleep 1
done
curl -s "http://127.0.0.1:$PORT/health" | python3 -m json.tool | head -12

say "create sandbox (health wait inside)"
CODE=$(api -X POST "http://127.0.0.1:$PORT/api/sandboxes" -H 'content-type: application/json' \
  -d "{\"sandbox_id\":\"$SANDBOX_ID\",\"thread_id\":\"$THREAD_ID\",\"uid\":\"$THREAD_ID\",\"workdir_path\":\"projects/probe\",\"inherit_env\":false}" \
  --max-time 240)
echo "create http=$CODE generation=$(json 'd.get("generation")')"
echo "container: $(docker ps --filter "name=pat-probe-sandbox-$SANDBOX_ID" --format '{{.Names}} {{.Status}}' | head -2)"

say "touch keeps alive (idle=12s, verify within window)"
echo "touch http=$(api -X POST "http://127.0.0.1:$PORT/api/sandboxes/$SANDBOX_ID/touch")"
sleep 8
CODE=$(api "http://127.0.0.1:$PORT/api/sandboxes/$SANDBOX_ID")
echo "discover after touch+8s (inside 12s idle): http=$CODE (expect 200)"
echo "touch again http=$(api -X POST "http://127.0.0.1:$PORT/api/sandboxes/$SANDBOX_ID/touch")"
sleep 4
CODE=$(api "http://127.0.0.1:$PORT/api/sandboxes/$SANDBOX_ID")
echo "discover after second touch+4s: http=$CODE (expect 200)"

say "idle reaper (idle=12s, interval=2s; 注意 GET discover 也会 touch)"
echo "silent wait 16s (no api calls, otherwise polling resets idle timer)"
sleep 16
CODE=$(api "http://127.0.0.1:$PORT/api/sandboxes/$SANDBOX_ID")
echo "discover after silent 16s: http=$CODE (expect 404)"
echo "container: $(docker ps -a --filter "name=pat-probe-sandbox-$SANDBOX_ID" --format '{{.Names}} {{.Status}}' | head -2)"
echo "provisioner log tail: $(docker logs "$NAME" 2>&1 | tail -3 | tr '\n' ' ')"

say "recreate + provisioner restart survival"
CODE=$(api -X POST "http://127.0.0.1:$PORT/api/sandboxes" -H 'content-type: application/json' \
  -d "{\"sandbox_id\":\"$SANDBOX_ID\",\"thread_id\":\"$THREAD_ID\",\"uid\":\"$THREAD_ID\",\"workdir_path\":\"projects/probe\",\"inherit_env\":false}" \
  --max-time 240)
GEN1=$(json 'd.get("generation")')
echo "recreate http=$CODE generation=$GEN1"
docker restart "$NAME" >/dev/null
for i in $(seq 1 30); do curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break; sleep 1; done
CODE=$(api "http://127.0.0.1:$PORT/api/sandboxes/$SANDBOX_ID")
GEN2=$(json 'd.get("generation")')
echo "discover after provisioner restart: http=$CODE generation=$GEN2 (expect 200, same generation)"
echo "container: $(docker ps --filter "name=pat-probe-sandbox-$SANDBOX_ID" --format '{{.Names}} {{.Status}}' | head -2)"

say "delete with expected_generation"
echo "delete http=$(api -X DELETE "http://127.0.0.1:$PORT/api/sandboxes/$SANDBOX_ID?expected_generation=$GEN2")"
echo "discover after delete: http=$(api "http://127.0.0.1:$PORT/api/sandboxes/$SANDBOX_ID") (expect 404)"
echo "wrong generation fence: create again then delete with stale gen"
CODE=$(api -X POST "http://127.0.0.1:$PORT/api/sandboxes" -H 'content-type: application/json' \
  -d "{\"sandbox_id\":\"$SANDBOX_ID\",\"thread_id\":\"$THREAD_ID\",\"uid\":\"$THREAD_ID\",\"workdir_path\":\"projects/probe\",\"inherit_env\":false}" \
  --max-time 240)
echo "recreate http=$CODE; delete with stale generation -> http=$(api -X DELETE "http://127.0.0.1:$PORT/api/sandboxes/$SANDBOX_ID?expected_generation=stale-gen") (expect 409)"

say "done"
