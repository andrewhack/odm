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
# Look for the dir that actually contains devicemgmt.wsdl - onvif-zeep's
# package layout has moved around between versions (sometimes onvif/wsdl,
# sometimes onvif/zeep/wsdl, sometimes via pkg_resources).
WSDL_DIR="$(uv run python -c '
from pathlib import Path
import onvif, sys
for p in Path(onvif.__file__).parent.rglob("devicemgmt.wsdl"):
    print(p.parent); sys.exit(0)
# try site-packages root as a fallback
root = Path(onvif.__file__).parent.parent
for p in root.rglob("devicemgmt.wsdl"):
    print(p.parent); sys.exit(0)
')"
if [ -z "$WSDL_DIR" ] || [ ! -d "$WSDL_DIR" ]; then
    echo "ERROR: could not locate onvif wsdl directory"
    uv run python -c "import onvif, os; print('onvif path:', onvif.__file__); print(os.listdir(os.path.dirname(onvif.__file__)))"
    exit 2
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
