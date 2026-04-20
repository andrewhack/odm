<#
.SYNOPSIS
  Build the onvifcfg Windows .exe installer (Inno Setup).

.DESCRIPTION
  1. uv sync --extra build
  2. PyInstaller one-file bundle -> dist/onvifcfg.exe (same bundle as the
     MSI build; bundles onvif WSDLs, web/templates, web/static)
  3. Inno Setup -> dist/onvifcfg-setup-<version>.exe

.REQUIREMENTS
  - Python 3.11+
  - uv (https://docs.astral.sh/uv/)
  - Inno Setup 6 (ISCC.exe on PATH)
      Install via:  choco install innosetup -y

.EXAMPLE
  pwsh packaging/exe/build-exe.ps1
#>
$ErrorActionPreference = 'Stop'

$repo = Resolve-Path (Join-Path $PSScriptRoot '..\..')
Set-Location $repo

$version = (Select-String -Path pyproject.toml -Pattern '^version = "(.*)"' | Select-Object -First 1).Matches[0].Groups[1].Value
Write-Host ">>> onvifcfg version $version"

if (Test-Path dist)  { Remove-Item -Recurse -Force dist }
if (Test-Path build) { Remove-Item -Recurse -Force build }

Write-Host ">>> uv sync"
uv sync --extra build

Write-Host ">>> stamping build info"
pwsh -File scripts/write_buildinfo.ps1

Write-Host ">>> resolving onvif WSDL directory"
$finder = @"
from pathlib import Path
import onvif, sys
for p in Path(onvif.__file__).parent.rglob('devicemgmt.wsdl'):
    print(p.parent); sys.exit(0)
root = Path(onvif.__file__).parent.parent
for p in root.rglob('devicemgmt.wsdl'):
    print(p.parent); sys.exit(0)
"@
$wsdlDir = (uv run python -c $finder).Trim()
if (-not $wsdlDir -or -not (Test-Path $wsdlDir -PathType Container)) {
    throw "could not locate onvif WSDL directory"
}
Write-Host "    $wsdlDir"

Write-Host ">>> pyinstaller"
uv run pyinstaller `
    --name onvifcfg `
    --onefile `
    --clean `
    --noconfirm `
    --paths src `
    --add-data "${wsdlDir};onvif/wsdl" `
    --add-data "src/onvifcfg/web/templates;onvifcfg/web/templates" `
    --add-data "src/onvifcfg/web/static;onvifcfg/web/static" `
    --collect-all onvif `
    --collect-all wsdiscovery `
    --collect-all zeep `
    src\onvifcfg\__main__.py

if (-not (Test-Path 'dist\onvifcfg.exe')) {
    throw "pyinstaller did not produce dist\onvifcfg.exe"
}

Write-Host ">>> inno setup compile"
$iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    # Common default install path.
    $candidate = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
    if (Test-Path $candidate) { $iscc = $candidate }
}
if (-not $iscc) {
    throw "ISCC.exe not found. Install Inno Setup 6 (choco install innosetup -y) or add it to PATH."
}

& $iscc "/DAppVersion=$version" packaging\exe\onvifcfg.iss
if ($LASTEXITCODE -ne 0) { throw "ISCC failed (exit $LASTEXITCODE)" }

$exe = "dist\onvifcfg-setup-$version.exe"
if (-not (Test-Path $exe)) {
    throw "Inno Setup did not produce $exe"
}

Write-Host ">>> produced: $exe"
Get-Item $exe | Format-List FullName, Length, LastWriteTime
