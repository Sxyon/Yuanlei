#!/usr/bin/env bash
# M0 探针：AIO 沙盒内 opencode/codex 契约取证。
#
# 安全约定：
#   - 密钥只通过 `docker run -e KEY`（从调用者环境透传）注入，不进入 argv、日志或报告；
#   - opencode 渲染配置包含 apiKey，报告只输出 provider/baseURL/model 字段；
#   - 调用者在外部 source .env 并导出 OPENCODE_*/CODEX_* 后运行本脚本。
#
# 用法：
#   set -a; . ./.env; set +a
#   export OPENCODE_PROVIDER=sf OPENCODE_MODEL=... OPENCODE_BASE_URL=... OPENCODE_API_KEY=...
#   export CODEX_MODEL=... CODEX_BASE_URL=... CODEX_API_KEY=...
#   bash scripts/probes/coding_cli_probe.sh [--keep]
set -uo pipefail

IMAGE="${SANDBOX_IMAGE:-enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:1.11.0}"
KEEP=0
[ "${1:-}" = "--keep" ] && KEEP=1
NAME="pat-cli-probe-$(date +%s)"
STATE_DIR="$HOME/.pat-probe-state"

cleanup() {
  if [ "$KEEP" = "0" ]; then
    docker rm -f "$NAME" >/dev/null 2>&1 || true
  else
    echo "[keep] container: $NAME"
  fi
}
trap cleanup EXIT

say() { printf '\n==== %s ====\n' "$1"; }
# 只输出配置的非密字段
sanitize_opencode_config() {
  docker exec "$NAME" python3 -c '
import json,sys
try:
    cfg=json.load(open("/home/gem/.config/opencode/config.json"))
except Exception as e:
    print("config not found:",e); sys.exit(0)
print("model:",cfg.get("model"))
for name,p in (cfg.get("provider") or {}).items():
    print("provider:",name,"npm:",p.get("npm"),"baseURL:",(p.get("options") or {}).get("baseURL"))
    print("models:",list((p.get("models") or {}).keys()))
    print("apiKey present:", bool((p.get("options") or {}).get("apiKey")))
' 2>&1
}

say "boot container (core profile)"
docker run -d --name "$NAME" \
  -e DISABLE_BROWSER=true -e DISABLE_MCP_BROWSER=true -e DISABLE_VNC=true \
  -e DISABLE_JUPYTER=true -e DISABLE_CODE_SERVER=true -e DISABLE_NODEJS_REPL=true \
  -e CHECK_YUXI_SANDBOX_ENV_EXISTS=True \
  -e USER=gem -e USER_UID=1000 -e USER_GID=1000 \
  -e OPENCODE_PROVIDER -e OPENCODE_MODEL -e OPENCODE_BASE_URL -e OPENCODE_API_KEY \
  -e OPENCODE_PROVIDER_NPM \
  -e CODEX_MODEL -e CODEX_BASE_URL -e CODEX_API_KEY -e CODEX_CONFIG_TOML \
  "$IMAGE" >/dev/null

say "wait for sandbox api (port 8080)"
for i in $(seq 1 60); do
  if docker exec "$NAME" sh -c 'curl -sf -o /dev/null http://127.0.0.1:8080/ || exit 1' 2>/dev/null; then
    echo "ready after ~$((i*2))s"; break
  fi
  [ "$i" = "60" ] && { echo "TIMEOUT waiting for sandbox api"; docker logs "$NAME" | tail -20; exit 1; }
  sleep 2
done

say "cli versions"
docker exec "$NAME" sh -c 'opencode --version 2>/dev/null; codex --version 2>/dev/null; node --version'

say "supervisor programs"
docker exec "$NAME" supervisorctl status 2>/dev/null | head -30 || echo "(supervisorctl unavailable)"

say "listening ports"
docker exec "$NAME" sh -c "ss -ltn 2>/dev/null | awk '{print \$4}' | sort -u | head -30"

say "opencode processes"
docker exec "$NAME" sh -c "ps -eo pid,comm,args | grep -i opencode | grep -v grep | head -10" || true

say "rendered opencode config (sanitized)"
sanitize_opencode_config

say "rendered codex config"
docker exec "$NAME" sh -c 'for f in /home/gem/.codex/config.toml /home/gem/.config/codex/config.toml; do [ -f "$f" ] && echo "path: $f" && cat "$f"; done' 2>&1 | head -30

say "codex exec full help (raw, first 120 lines)"
docker exec "$NAME" sh -c 'codex exec --help 2>&1' | sed -n '1,120p' || true

say "opencode run smoke (json events, as gem)"
docker exec -u gem -e HOME=/home/gem "$NAME" sh -c '
  cd /home/gem && timeout 120 opencode run --format json "Reply with exactly: PONG" > /tmp/opencode-run.jsonl 2>/tmp/opencode-run.err
  echo "exit=$?"
  echo "--- stdout head ---"; head -c 1800 /tmp/opencode-run.jsonl
  echo; echo "--- stdout tail ---"; tail -c 800 /tmp/opencode-run.jsonl
  echo; echo "--- stderr tail ---"; tail -c 500 /tmp/opencode-run.err
' 2>&1

say "opencode session resume (native, as gem)"
docker exec -u gem -e HOME=/home/gem "$NAME" sh -c '
  SID=$(grep -o "\"sessionID\":\"[^\"]*\"" /tmp/opencode-run.jsonl | head -1 | cut -d\" -f4)
  echo "first session: $SID"
  timeout 90 opencode run --format json -s "$SID" "Reply with exactly: PONG3" > /tmp/opencode-resume.jsonl 2>/tmp/opencode-resume.err
  echo "resume exit=$?"
  echo "--- resumed session ids ---"; grep -o "\"sessionID\":\"[^\"]*\"" /tmp/opencode-resume.jsonl | sort -u | head -3
  echo "--- tail ---"; tail -1 /tmp/opencode-resume.jsonl | head -c 900
' 2>&1

say "opencode agent surface (as gem)"
docker exec -u gem -e HOME=/home/gem "$NAME" sh -c '
  echo "--- agents ---"
  timeout 20 opencode agent list 2>&1 | grep -E "^[a-zA-Z].*\((primary|subagent)\)" | head -20
  echo "--- session subcommands ---"
  opencode session --help 2>&1 | sed -n "/Commands:/,/Options:/p" | head -20
' 2>&1

say "opencode session persistence (XDG override, as gem)"
docker exec -u gem -e HOME=/home/gem "$NAME" sh -c '
  mkdir -p /home/gem/user-data/agents/coding/probe/.state/{data,config,cache}
  export XDG_DATA_HOME=/home/gem/user-data/agents/coding/probe/.state/data
  export XDG_CONFIG_HOME=/home/gem/user-data/agents/coding/probe/.state/config
  export XDG_CACHE_HOME=/home/gem/user-data/agents/coding/probe/.state/cache
  timeout 60 opencode run "Reply with exactly: PONG2" >/dev/null 2>&1; echo "run exit=$?"
  echo "--- files under probe state ---"
  find /home/gem/user-data/agents/coding/probe/.state -maxdepth 4 | head -30
' 2>&1

say "codex exec smoke (json events, as gem)"
docker exec -u gem -e HOME=/home/gem "$NAME" sh -c '
  mkdir -p /home/gem/user-data/probe-workdir && cd /home/gem/user-data/probe-workdir && git init -q 2>/dev/null || true
  timeout 120 codex exec --json --skip-git-repo-check "Reply with exactly: PONG" > /tmp/codex-run.jsonl 2>/tmp/codex-run.err
  echo "exit=$?"
  echo "--- stdout head ---"; head -c 1800 /tmp/codex-run.jsonl
  echo; echo "--- stdout tail ---"; tail -c 600 /tmp/codex-run.jsonl
  echo; echo "--- stderr tail ---"; tail -c 800 /tmp/codex-run.err
' 2>&1

say "codex home persistence + native resume (CODEX_HOME override, as gem)"
docker exec -u gem -e HOME=/home/gem "$NAME" sh -c '
  export CODEX_HOME=/home/gem/user-data/agents/coding/probe/codex-home
  mkdir -p "$CODEX_HOME" && cd /home/gem/user-data/probe-workdir
  timeout 120 codex exec --json --skip-git-repo-check "Reply with exactly: PONG2" > /tmp/codex-persist.jsonl 2>/tmp/codex-persist.err
  echo "run exit=$?"
  TID=$(grep -o "\"thread_id\":\"[^\"]*\"" /tmp/codex-persist.jsonl | head -1 | cut -d\" -f4)
  echo "thread: $TID"
  timeout 120 codex exec resume "$TID" --json "Reply with exactly: PONG4" > /tmp/codex-resume.jsonl 2>/tmp/codex-resume.err
  echo "resume exit=$?"
  echo "--- resumed thread ids ---"; grep -o "\"thread_id\":\"[^\"]*\"" /tmp/codex-resume.jsonl | sort -u | head -3
  echo "--- resume tail ---"; tail -1 /tmp/codex-resume.jsonl | head -c 600
  echo; echo "--- persist stderr (if any) ---"; head -c 300 /tmp/codex-persist.err
  echo "--- state files ---"; find "$CODEX_HOME" -maxdepth 1 -name "*.sqlite" -o -maxdepth 1 -name "sessions" | head -10
' 2>&1

say "opencode serve + generic port proxy (x-aio-proxy-port, as gem)"
docker exec -u gem -e HOME=/home/gem "$NAME" sh -c '
  nohup opencode serve --port 4096 --hostname 127.0.0.1 >/tmp/serve.log 2>&1 &
  for i in $(seq 1 15); do
    curl -sf -o /dev/null --max-time 2 http://127.0.0.1:4096/ && break
    sleep 1
  done
  echo "--- direct 4096 ---"; curl -s -o /dev/null -w "%{http_code}\n" --max-time 5 http://127.0.0.1:4096/
  echo "--- direct /session ---"; curl -s -o /dev/null -w "%{http_code}\n" --max-time 5 http://127.0.0.1:4096/session
  echo "--- via nginx x-aio-proxy-port ---"; curl -s -o /dev/null -w "%{http_code}\n" --max-time 5 -H "x-aio-proxy-port: 4096" http://127.0.0.1:8080/
  echo "--- serve log tail ---"; tail -5 /tmp/serve.log
' 2>&1

say "terminal url via sandbox api"
docker exec "$NAME" sh -c '
  echo "--- /v1/shell/terminal-url ---"
  curl -s --max-time 10 http://127.0.0.1:8080/v1/shell/terminal-url | head -c 600
  echo
  echo "--- /v1/sandbox ---"
  curl -s --max-time 10 http://127.0.0.1:8080/v1/sandbox | head -c 400
' 2>&1

say "done ($NAME)"
