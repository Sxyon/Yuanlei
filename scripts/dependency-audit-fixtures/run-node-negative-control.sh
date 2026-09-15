#!/usr/bin/env bash

set -euo pipefail

fixture_dir="$(mktemp -d)"
trap 'rm -rf "$fixture_dir"' EXIT

pnpm --dir "$fixture_dir" add --lockfile-only --ignore-scripts js-yaml@4.3.0

audit_log="$fixture_dir/audit.log"
if pnpm --dir "$fixture_dir" audit --audit-level=high --prod >"$audit_log" 2>&1; then
  echo "Expected the vulnerable Node.js fixture to fail." >&2
  exit 1
fi

grep -q "js-yaml" "$audit_log"
grep -q "GHSA-5p4m-2wfm-xmqj" "$audit_log"
