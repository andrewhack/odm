# Windows MSI packaging

This branch produces a Windows MSI installer for `onvifcfg`.

## Install (recommended — bypasses Defender SmartScreen)

Open **PowerShell as Administrator** and run:

```powershell
irm https://raw.githubusercontent.com/andrewhack/odm/main/packaging/msi/install.ps1 | iex
```

This downloads the MSI via .NET `WebClient` (which does not tag the file
with a `Zone.Identifier` Alternate Data Stream) and runs msiexec directly,
so Defender SmartScreen never engages. The MSI itself is the same artifact
you'd get from the [releases page](https://github.com/andrewhack/odm/releases).

To uninstall:

```powershell
irm https://raw.githubusercontent.com/andrewhack/odm/main/packaging/msi/install.ps1 | iex -Uninstall
```

## Install (manual — hits SmartScreen)

If you'd rather download from the browser, Defender SmartScreen will block
the unsigned MSI with "Microsoft Defender SmartScreen prevented an
unrecognized app from starting". Two ways through:

- **Unblock the file**: right-click the downloaded `.msi` → Properties →
  tick "Unblock" → OK. Then double-click to install.
- **Bypass on the dialog**: click "More info" on the SmartScreen popup →
  "Run anyway".

## Why isn't the MSI signed?

Authenticode signing doesn't fully remove SmartScreen — Microsoft uses a
separate download-reputation system. Options we've evaluated are tracked
in [docs/ROADMAP.md](../../docs/ROADMAP.md#msi-code-signing-defender-smartscreen-workaround):

- **End-user `install.ps1`** (done — recommended)
- **SignPath.io OSS program** (free, TBD)
- **Azure Trusted Signing** (~$10/month, cleanest UX)
- **EV Code Signing certificate** (~$300-700/year, instant reputation)

The build script has a hook: if the repo's GitHub Secrets contain
`MSI_SIGNING_PFX_BASE64` and `MSI_SIGNING_PFX_PASSWORD`, `build-msi.ps1`
will sign the MSI with `signtool.exe` and also export the public
certificate as `dist/onvifcfg.cer` for users who want to import it into
their Trusted Publishers store. Unsigned builds still work.

## Build from source

Requires Python 3.11+, `uv`, and WiX v4 (`dotnet tool install -g wix --version 4.0.6`):

```powershell
pwsh packaging\msi\build-msi.ps1
```

Output: `dist/onvifcfg-<version>.msi` (and `dist/onvifcfg.cer` if signed).

## CI

`.github/workflows/release.yml` on the `main` branch builds this MSI on a
`windows-latest` runner for every `v*` tag and publishes it as a release
asset. See the workflow for the `windows-latest` SDK + uv + WiX install
steps.
