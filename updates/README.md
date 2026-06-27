# Neko GitHub Update Flow

This folder contains the static update manifest that can be hosted from:

- Gitee raw: `https://gitee.com/w246006/246006/raw/main/updates/stable.json`
- Raw GitHub fallback: `https://raw.githubusercontent.com/vjvjgchj/246006/main/updates/stable.json`

## Current Compatibility Rule

The updater supports two manifest shapes:

- `files[]`: legacy per-file updates. Keep this for bridge releases.
- `packages[]`: preferred zip package updates for multi-file releases.

Do not switch all customers to a `packages[]`-only manifest until their local
panel already contains package-capable `backend/update_manager.py`.

## Preferred Package Release Flow

1. Push this repository content to `https://gitee.com/w246006/246006.git`.
2. Build an update package zip with `tools\make_update_package.py`.
3. Create a GitHub Release with a new tag such as `v2026.06.27.2`.
4. Upload the zip package as a release asset.
5. Generate `updates/stable.json` with `packages[]`.
6. Commit and push `updates/stable.json` to the default branch.
7. The client panel can then check, download, verify, apply, and roll back the package.

Example package:

```powershell
python tools\make_update_package.py `
  --output dist\update_packages\neko-core-v2026.06.27.2.zip `
  --include runtime\TRT_ZeroCopy_Pipeline.exe `
  --include backend `
  --include qml `
  --include updates
```

Example package manifest:

```powershell
python tools\make_github_update_manifest.py `
  --tag v2026.06.27.2 `
  --package dist\update_packages\neko-core-v2026.06.27.2.zip `
  --package-name core `
  --notes "package update release"
```

## Bridge Release For Older Clients

If a customer has a client that only understands `files[]`, publish a bridge
manifest first. The bridge should update the panel/updater files using `files[]`
or ship a full replacement package manually. After customers have the
package-capable updater, future releases can be `packages[]`.

Legacy single-file manifest generation is still available:

```powershell
python tools\make_github_update_manifest.py --tag v2026.06.27.1 --notes "legacy runtime-only update"
```

The updater protects these local files by default:

- `.updates`
- `runtime/config.txt`
- `runtime/logi_driver.dll`
- `gui_settings.json`
