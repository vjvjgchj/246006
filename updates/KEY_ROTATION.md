# Update Signing Key Rotation

The former update signing private key was lost. This release establishes a new
trusted update key and requires one manual bootstrap step for installations
that already verify the former key.

## One-Time Bootstrap

1. Download `neko-key-rotation-v2026.08.27.2.zip` from this repository's
   `release_assets` directory.
2. Extract the archive into the Neko installation directory, alongside
   `NekoLauncher.bat` and `6_run_qml_panel.vbs`, and allow the two launcher
   files to be replaced.
3. Run `NekoLauncher.bat` from that installation directory.
4. The launcher verifies the new Gitee `updates/stable.json`, downloads the
   `neko-core-v2026.08.27.2.zip` package, and applies it.

The bootstrap archive does not overwrite `runtime/config.txt`,
`runtime/logi_driver.dll`, or `gui_settings.json`. Those files remain
preserved by the normal updater as well.
