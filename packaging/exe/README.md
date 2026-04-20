# Windows .exe installer (Inno Setup)

An alternative to the MSI. Same PyInstaller-bundled `onvifcfg.exe` under
the hood, wrapped in an Inno Setup single-file installer.

## Install

Download `onvifcfg-setup-<version>.exe` from the
[latest release](https://github.com/andrewhack/odm/releases/latest),
double-click it.

SmartScreen behaviour is unchanged vs. MSI — the installer is unsigned,
so you'll see "Windows protected your PC" on first run. Click
**More info** → **Run anyway**. Or launch it from an elevated prompt via
`Start-Process .\onvifcfg-setup-<version>.exe` which skips the
Zone.Identifier check.

After install:

- `onvifcfg` is available from a new terminal (Start Menu → PowerShell)
- Start Menu folder **onvifcfg** contains `web UI` and `command help`
  shortcuts
- Uninstall from Add/Remove Programs as usual

## What it does

Installs `onvifcfg.exe` to `%ProgramFiles%\onvifcfg\` and, if the
"Add onvifcfg to the system PATH" task is ticked (default), appends
that folder to the system PATH. Both steps are reversed on uninstall.

## Build from source

Requires Python 3.11+, `uv`, and Inno Setup 6 on PATH:

```powershell
choco install innosetup -y
pwsh packaging\exe\build-exe.ps1
```

Output: `dist/onvifcfg-setup-<version>.exe`.

## CI

`.github/workflows/release.yml` on the `main` branch builds this
installer on a `windows-latest` runner for every `v*` tag, alongside
the MSI and DEB.
