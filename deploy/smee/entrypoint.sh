#!/bin/sh
set -eu

if [ -z "${GITHUB_WEBHOOK_PROXY_URL:-}" ]; then
  echo "GitHub webhook forwarding disabled: GITHUB_WEBHOOK_PROXY_URL is empty"
  exec tail -f /dev/null
fi

target="${GITHUB_WEBHOOK_TARGET_URL:-http://api:8000/integrations/github/webhook}"
exec smee --url "$GITHUB_WEBHOOK_PROXY_URL" --target "$target"
