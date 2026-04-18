# Debian / Ubuntu .deb packaging

This branch adds Debian packaging on top of the core Python source on
`main`. The `.deb` bundles a self-contained PyInstaller binary, so the
installed system does **not** need Python 3.11+ on the path.

## Build

```bash
bash packaging/deb/build-deb.sh
```

Produces `dist/onvifcfg_<version>_amd64.deb`.

## Build-host requirements

- **Python 3.11+** with `uv` installed
- **[nfpm](https://nfpm.goreleaser.com/)** — install via
  `curl -sLO https://github.com/goreleaser/nfpm/releases/latest/download/nfpm_amd64.deb && sudo dpkg -i nfpm_amd64.deb`
- Standard build tools (`build-essential`)

## Install

```bash
sudo dpkg -i dist/onvifcfg_*_amd64.deb
# or
sudo apt install ./dist/onvifcfg_*_amd64.deb
```

Puts `/usr/bin/onvifcfg` and docs under `/usr/share/doc/onvifcfg/`.

## Uninstall

```bash
sudo apt remove onvifcfg
```

## CI

Drop this in a GitHub Actions workflow (Ubuntu runner) to get a build
on every tag:

```yaml
name: build-deb
on: { push: { tags: ['v*'] } }
jobs:
  deb:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: |
          curl -sLO https://github.com/goreleaser/nfpm/releases/latest/download/nfpm_amd64.deb
          sudo dpkg -i nfpm_amd64.deb
      - run: bash packaging/deb/build-deb.sh
      - uses: actions/upload-artifact@v4
        with: { name: deb, path: dist/*.deb }
```
