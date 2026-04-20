#!/usr/bin/env bash
# Writes src/onvifcfg/_buildinfo.py with the current git short SHA + UTC
# timestamp.  Idempotent; safe to call repeatedly from build scripts.
set -eu
SHA="$(git -C "$(dirname "${BASH_SOURCE[0]}")/.." rev-parse --short=7 HEAD 2>/dev/null || echo dev)"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat > "$(dirname "${BASH_SOURCE[0]}")/../src/onvifcfg/_buildinfo.py" <<EOF
"""Build-time metadata (regenerated on every build)."""

GIT_SHA = "${SHA}"
BUILD_TIME = "${TS}"
EOF
echo "    wrote _buildinfo.py (sha=${SHA}, time=${TS})"
