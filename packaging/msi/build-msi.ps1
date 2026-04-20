<#
.SYNOPSIS
  Build the onvifcfg Windows MSI.

.DESCRIPTION
  1. uv sync --extra build
  2. PyInstaller one-file bundle -> dist/onvifcfg.exe (bundling the onvif-
     zeep WSDL directory explicitly so the frozen app can resolve it)
  3. WiX v4 -> dist/onvifcfg-<version>.msi

.REQUIREMENTS
  - Python 3.11+
  - uv (https://docs.astral.sh/uv/)
  - WiX v4+ (dotnet tool install -g wix --version 4.0.6)

.EXAMPLE
  pwsh packaging/msi/build-msi.ps1
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
    uv run python -c "import onvif, os; print('onvif:', onvif.__file__); print(os.listdir(os.path.dirname(onvif.__file__)))"
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

Write-Host ">>> wix build"
$msi = "dist\onvifcfg-$version.msi"
wix build `
    -arch x64 `
    -d Version=$version `
    -d BuildDir="$repo\dist" `
    -out $msi `
    packaging\msi\onvifcfg.wxs

if (-not (Test-Path $msi)) {
    throw "wix did not produce $msi"
}

# Optional Authenticode signing.  Set MSI_SIGNING_PFX_BASE64 and
# MSI_SIGNING_PFX_PASSWORD env vars (typically GitHub Secrets) to a
# code-signing PFX; the build signs the MSI + EXE with signtool and
# exports the public cert as dist/onvifcfg.cer.  Unsigned builds
# continue to work - SmartScreen users should use install.ps1 which
# bypasses the Zone.Identifier check.
if ($env:MSI_SIGNING_PFX_BASE64) {
    Write-Host ">>> authenticode signing"
    $pfxPath = Join-Path $env:TEMP "onvifcfg-signing.pfx"
    [IO.File]::WriteAllBytes($pfxPath, [Convert]::FromBase64String($env:MSI_SIGNING_PFX_BASE64))
    $pwd = $env:MSI_SIGNING_PFX_PASSWORD
    $signtool = (Get-ChildItem "C:\Program Files (x86)\Windows Kitsin\*d\signtool.exe" |
                 Sort-Object FullName -Descending | Select-Object -First 1).FullName
    if (-not $signtool) { throw 'signtool.exe not found; is the Windows SDK installed?' }
    foreach ($target in 'dist\onvifcfg.exe', $msi) {
        & $signtool sign /f $pfxPath /p $pwd `
            /tr http://timestamp.digicert.com /td sha256 /fd sha256 `
            /d 'onvifcfg' /du 'https://github.com/andrewhack/odm' $target
    }
    # Export the public cert alongside the MSI so users can import it
    # into Trusted Publishers to skip the 'unknown publisher' UAC prompt.
    $cert = Get-PfxData -FilePath $pfxPath -Password (ConvertTo-SecureString $pwd -AsPlainText -Force)
    Export-Certificate -Cert $cert.EndEntityCertificates[0] -FilePath 'dist\onvifcfg.cer' -Type CERT | Out-Null
    Remove-Item $pfxPath -Force
    Write-Host "    signed $msi and dist\onvifcfg.exe"
    Write-Host "    public cert at dist\onvifcfg.cer"
} else {
    Write-Host ">>> skipping authenticode signing (MSI_SIGNING_PFX_BASE64 not set)"
}

Write-Host ">>> produced: $msi"
Get-Item $msi | Format-List FullName, Length, LastWriteTime
