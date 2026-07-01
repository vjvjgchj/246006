# Neko Launcher

`NekoLauncher.bat` and `NekoLauncher.ps1` are a minimal in-place installer/updater.

Place both files in the user's `neko` directory and run `NekoLauncher.bat`.
By default, the launcher treats its own directory as the install/update target.
After a successful package install, it starts `6_run_qml_panel.vbs` by default
and falls back to `6_run_web_panel.vbs` only when the QML entry is missing.

Default manifest:

```text
https://gitee.com/w246006/246006/raw/main/updates/stable.json
```

The manifest must use the newer `packages[]` zip format. The launcher does not
support legacy `files[]` manifests because it is intended for first install or
package-based repair from a lightweight bootstrap.

Protected local paths:

```text
.updates
runtime/config.txt
runtime/logi_driver.dll
gui_settings.json
```

Test with a custom manifest:

```bat
NekoLauncher.bat -ManifestUrl "E:\path\to\stable-package-local.json" -NoLaunch -Force
```
