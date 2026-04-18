# Windows MSI packaging

This branch adds Windows MSI packaging on top of the core Python source
on `main`. The MSI bundles a self-contained PyInstaller `onvifcfg.exe`
— installed systems do **not** need Python 3.11+ on the path.

## Build

From an elevated PowerShell 7+ prompt on Windows:

```powershell
pwsh packaging\msi\build-msi.ps1
```

Produces `dist\onvifcfg-<version>.msi`.

## Build-host requirements

- **Python 3.11+** on PATH
- **uv** — <https://docs.astral.sh/uv/>
- **.NET SDK 6+** and the **WiX v4 toolset**:
  ```powershell
  dotnet tool install -g wix
  ```

## Install

Double-click the MSI, or silently:

```powershell
msiexec /i dist\onvifcfg-<version>.msi /qn
```

Installs to `%ProgramFiles%\onvifcfg\onvifcfg.exe` and adds that
directory to the system PATH. Open a new terminal and run `onvifcfg --help`.

## Uninstall

Control Panel → Apps → onvifcfg → Uninstall, or:

```powershell
msiexec /x dist\onvifcfg-<version>.msi /qn
```

## CI

```yaml
name: build-msi
on: { push: { tags: ['v*'] } }
jobs:
  msi:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - uses: actions/setup-dotnet@v4
        with: { dotnet-version: '8.0.x' }
      - run: dotnet tool install -g wix
      - run: pwsh packaging\msi\build-msi.ps1
      - uses: actions/upload-artifact@v4
        with: { name: msi, path: dist\*.msi }
```
