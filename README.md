# Neko Web Runtime Package

This directory is the packaged Neko panel/runtime workspace. The active panel is now Web-only; the old QML panel chain has been retired.

## Main Files

- `6_run_web_panel.vbs`: launches the Web panel without a console window.
- `run_web_panel_hidden.pyw`: Web panel bootstrapper.
- `backend/web_panel_controller.py`: panel controller that writes runtime config, validates capabilities, and launches the runtime executable.
- `backend/mobile_control_server.py`: local Web UI and HTTP control server.
- `runtime/`: runtime directory used by the panel.
- `runtime/TRT_ZeroCopy_Pipeline.exe`: inference core executable.
- `runtime/config.txt`: runtime config consumed by the executable.
- `runtime/logi_driver.dll`: preserved input driver DLL.
- `gui_settings.json`: panel state only, not the runtime's final source of truth.

## First Run

1. Install the VC++ runtime with `1_install_vcredist.bat` if needed.
2. Install Python dependencies with `5_install_panel_python_deps.bat` if needed.
3. Start the panel with `6_run_web_panel.vbs`.
4. In the Web panel, select the model/engine, adjust parameters, save, and start the runtime.

## Web-Only Migration

The following QML-era files are retired and should be removed by update packages:

- `qml/`
- `backend/qml_bridge.py`
- `6_run_qml_panel.vbs`
- `run_panel_hidden.pyw`
- `gui_qml_trial.py`
- `keyauth_login.py`

Update manifests should include these paths in `delete[]` so existing customer directories are cleaned automatically.
