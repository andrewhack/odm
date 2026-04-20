# Writes src/onvifcfg/_buildinfo.py with the current git short SHA + UTC
# timestamp. Called by the Windows build scripts *after* uv sync so the
# copy that lands in .venv site-packages also reflects the stamp.
$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$sha  = try { (& git -C $repo rev-parse --short=7 HEAD 2>$null).Trim() } catch { '' }
if (-not $sha) { $sha = 'dev' }
$ts   = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')

$srcFile = Join-Path $repo 'src\onvifcfg\_buildinfo.py'
$body = @"
`"""Build-time metadata (regenerated on every build).`"""

GIT_SHA = "$sha"
BUILD_TIME = "$ts"
"@
Set-Content -Path $srcFile -Value $body -Encoding UTF8
Write-Host "    wrote $srcFile (sha=$sha, time=$ts)"

# Belt-and-suspenders: if the project is already installed into a venv
# (uv sync ran earlier), also overwrite the site-packages copy so the
# PyInstaller trace picks up the real SHA even if the install was not
# editable.
$venvPython = Join-Path $repo '.venv\Scripts\python.exe'
if (Test-Path $venvPython) {
    $detect = @"
import importlib.util, sys
spec = importlib.util.find_spec("onvifcfg._buildinfo")
print(spec.origin if spec and spec.origin else "", end="")
"@
    $venvFile = (& uv --directory $repo run python -c $detect).Trim()
    if ($venvFile -and $venvFile -ne $srcFile) {
        Copy-Item -Force $srcFile $venvFile
        Write-Host "    also wrote $venvFile"
    }
}

# PyInstaller can pick up stale .pyc files from __pycache__; scrub them.
Get-ChildItem -Path (Join-Path $repo 'src') -Recurse -Force -Directory -Filter '__pycache__' |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
