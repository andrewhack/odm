<#
.SYNOPSIS
  One-line installer for onvifcfg that bypasses Windows Defender SmartScreen.

.DESCRIPTION
  SmartScreen blocks unsigned installers that arrive from the Internet Zone.
  A browser download tags the .msi with a Zone.Identifier Alternate Data
  Stream; MsiExec's launch path checks that ADS and shows the "unrecognized
  app" dialog. This script downloads the MSI via .NET WebClient (which does
  not set Zone.Identifier) and runs msiexec directly, so SmartScreen never
  engages on the launch path.

  The MSI is still the same artifact as on the GitHub release page.

.EXAMPLE
  # paste into an elevated PowerShell 7+ prompt:
  irm https://raw.githubusercontent.com/andrewhack/odm/main/packaging/msi/install.ps1 | iex

  # or, if you already downloaded the script:
  pwsh packaging\msi\install.ps1
#>
param(
    [string]$Version = "0.1.0",
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

$url = "https://github.com/andrewhack/odm/releases/download/v$Version/onvifcfg-$Version.msi"
$tmp = Join-Path $env:TEMP "onvifcfg-$Version.msi"

if ($Uninstall) {
    Write-Host ">>> uninstalling onvifcfg" -ForegroundColor Cyan
    Start-Process msiexec.exe -ArgumentList '/x', $tmp, '/qb' -Wait -Verb RunAs
    exit 0
}

Write-Host ">>> downloading onvifcfg $Version from $url" -ForegroundColor Cyan
$wc = New-Object System.Net.WebClient
$wc.Headers.Add("User-Agent", "onvifcfg-install.ps1")
$wc.DownloadFile($url, $tmp)
Write-Host "    saved to $tmp"

Write-Host ">>> launching installer" -ForegroundColor Cyan
Start-Process msiexec.exe -ArgumentList '/i', $tmp, '/qb' -Wait -Verb RunAs

Write-Host ""
Write-Host "onvifcfg installed. Open a new terminal and run 'onvifcfg --help'" -ForegroundColor Green
Write-Host "or start the local web UI with 'onvifcfg serve' and open http://127.0.0.1:3003/"
