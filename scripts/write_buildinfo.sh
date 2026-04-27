#!/usr/bin/env bash
# Writes src/onvifcfg/_buildinfo.py with the current git short SHA + UTC
# timestamp.  Called from build scripts *after* uv sync so the copy that
# lands in .venv site-packages also reflects the stamp.
#
# Idempotent; safe to call repeatedly.
set -eu

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

SHA="$(git -C "$REPO" rev-parse --short=7 HEAD 2>/dev/null || echo dev)"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# Pull project.version from pyproject.toml so the frozen build matches
# the release tag without a second source of truth.
VER="$(awk -F'"' '/^version[[:space:]]*=[[:space:]]*"/{print $2; exit}' "$REPO/pyproject.toml")"
[ -n "$VER" ] || VER="dev"

SRC_FILE="$REPO/src/onvifcfg/_buildinfo.py"
cat > "$SRC_FILE" <<PYEOF
"""Build-time metadata (regenerated on every build)."""

GIT_SHA = "${SHA}"
BUILD_TIME = "${TS}"
VERSION = "${VER}"
PYEOF
echo "    wrote ${SRC_FILE} (sha=${SHA}, time=${TS}, version=${VER})"

# Belt-and-suspenders: if the project is already installed into a venv
# (uv sync ran earlier), also overwrite the site-packages copy so the
# PyInstaller trace picks up the real SHA even if the install was not
# editable.
if [ -x "$REPO/.venv/bin/python" ] || [ -x "$REPO/.venv/Scripts/python.exe" ]; then
    VENV_FILE="$(
        uv --directory "$REPO" run python - <<'DETECT'
import importlib.util, sys
spec = importlib.util.find_spec("onvifcfg._buildinfo")
print(spec.origin if spec and spec.origin else "", end="")
DETECT
    )"
    # Same-inode test (-ef) so an editable install (where the venv copy
    # is just a path that resolves back to SRC_FILE) is detected even
    # when the textual paths differ (msys2 /c/... vs Windows C:\...).
    if [ -n "$VENV_FILE" ] && ! [ "$VENV_FILE" -ef "$SRC_FILE" ]; then
        cp "$SRC_FILE" "$VENV_FILE"
        echo "    also wrote ${VENV_FILE}"
    fi
fi

# PyInstaller has been known to pick up stale .pyc files from __pycache__;
# scrub them to be safe.
find "$REPO/src" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
