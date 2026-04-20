# Writes src/onvifcfg/_buildinfo.py with the current git short SHA + UTC
# timestamp.  Called from the Windows build scripts before pyinstaller.
$ErrorActionPreference = 'Stop'
$repo = Resolve-Path (Join-Path $PSScriptRoot '..')
$sha = try { (git -C $repo rev-parse --short=7 HEAD).Trim() } catch { 'dev' }
$ts  = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$dest = Join-Path $repo 'src\onvifcfg\_buildinfo.py'
$content = @"
`"""Build-time metadata (regenerated on every build).`"""

GIT_SHA = "$sha"
BUILD_TIME = "$ts"
"@
Set-Content -Path $dest -Value $content -Encoding UTF8
Write-Host "    wrote _buildinfo.py (sha=$sha, time=$ts)"
