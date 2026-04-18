#!/usr/bin/env bash
# Build a Debian/Ubuntu .deb containing a PyInstaller-bundled onvifcfg binary.
#
# Requirements on the build host:
#   - Python 3.11+ with uv
#   - PyInstaller (pulled in via `uv sync --extra build`)
#   - nfpm (https://nfpm.goreleaser.com/)
#
# Output: dist/onvifcfg_<version>_amd64.deb

set -euo pipefail

cd "$(dirname "$0")/../.."

VERSION="$(awk -F\" '/^version = /{print $2; exit}' pyproject.toml)"
echo ">>> building onvifcfg ${VERSION}"

rm -rf dist build

echo ">>> installing deps"
uv sync --extra build

echo ">>> resolving onvif WSDL directory"
WSDL_DIR="$(uv run python -c 'import os, onvif; print(os.path.join(os.path.dirname(onvif.__file__), "wsdl"))')"
if [ ! -d "$WSDL_DIR" ]; then
    echo "ERROR: onvif wsdl directory not found at: $WSDL_DIR"; exit 2
fi
echo "    $WSDL_DIR"

echo ">>> pyinstaller bundle"
uv run pyinstaller \
    --name onvifcfg \
    --onefile \
    --clean \
    --noconfirm \
    --paths src \
    --add-data "${WSDL_DIR}:onvif/wsdl" \
    --add-data "src/onvifcfg/web/templates:onvifcfg/web/templates" \
    --add-data "src/onvifcfg/web/static:onvifcfg/web/static" \
    --collect-all onvif \
    --collect-all wsdiscovery \
    --collect-all zeep \
    src/onvifcfg/__main__.py

echo ">>> nfpm deb"
nfpm pkg --packager deb \
    --config packaging/deb/nfpm.yaml \
    --target "dist/onvifcfg_${VERSION}_amd64.deb"

echo ">>> produced: dist/onvifcfg_${VERSION}_amd64.deb"
ls -lh "dist/onvifcfg_${VERSION}_amd64.deb"
