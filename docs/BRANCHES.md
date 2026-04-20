# Branch layout

This repository uses a **multi-branch packaging model**. Every platform
installer lives on its own long-lived branch and is **never merged into
`main`**. The `.github/workflows/release.yml` job checks each branch out
separately (`actions/checkout@v4` with `ref: <branch>`) and builds the
corresponding artifact on the matching runner OS.

If GitHub shows you a *"Compare & pull request"* banner for any of the
branches below — **ignore it**. Merging them into `main` would collapse
the layout, pull Windows-only / Linux-only packaging files into the
common tree, and break the release workflow.

## Branches

| Branch         | Purpose                                       | Lives on this branch only                               | CI runner          |
| -------------- | --------------------------------------------- | ------------------------------------------------------- | ------------------ |
| `main`         | Python source, tests, docs, CI workflow       | Everything under `src/`, `tests/`, `docs/`, `.github/`  | n/a                |
| `linux`        | Debian / Ubuntu `.deb` installer              | `packaging/deb/build-deb.sh`, `packaging/deb/nfpm.yaml` | `ubuntu-latest`    |
| `windows-msi`  | Windows MSI installer (WiX v4)                | `packaging/msi/onvifcfg.wxs`, `build-msi.ps1`, `install.ps1` | `windows-latest`  |
| `windows-exe`  | Windows EXE installer (Inno Setup)            | `packaging/exe/onvifcfg.iss`, `build-exe.ps1`           | `windows-latest`   |

## How changes flow

```
                  main (authoritative source)
                   |
      +------------+------------+
      |            |            |
    linux     windows-msi   windows-exe
   (rebased)   (rebased)     (rebased)
```

When something changes on `main` that the packaging branches need (source
layout, new dependency, renamed module), **rebase each branch onto main**:

```bash
git checkout linux        && git rebase main && git push -f origin linux
git checkout windows-msi  && git rebase main && git push -f origin windows-msi
git checkout windows-exe  && git rebase main && git push -f origin windows-exe
```

The force-push is expected — these branches are rebase-based, not
merge-based. Nothing depends on their commit SHAs being stable.

## Tagging a release

Tag `vX.Y.Z` on `main`. `release.yml` fans out, builds `.deb` on Ubuntu,
`.msi` + `.exe` on Windows, then attaches all three to the GitHub release:

```bash
git checkout main
git tag -a v0.1.1 -m "onvifcfg v0.1.1"
git push origin v0.1.1
```

If you just rebased the packaging branches, push them **before** tagging
so the workflow picks up the new tips.

## Why not a monorepo tree?

Two reasons:

1. **Platform separation.** Keeping `packaging/msi/` out of the Linux
   build tree (and vice versa) means `uv sync` on either OS never sees
   irrelevant files, and the repo clone stays lean.
2. **Independent iteration.** The Windows signing / SmartScreen story
   evolves on a different schedule than the Debian packaging rules;
   separate branches let each track its own history without polluting
   `main`'s log.

## Dismissing the GitHub banner

- It auto-clears ~24h after the last branch push.
- Or click the small `x` on the banner to dismiss per-branch.
- Or just ignore it — it doesn't affect anything.
