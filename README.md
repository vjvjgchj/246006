# Neko Runtime Package

This directory is the packaged Neko panel/runtime workspace. The active panel is the QML panel. The Web panel remains as a fallback/diagnostic entry, but update packages must not delete the QML chain by default.

## Main Files

- `6_run_qml_panel.vbs`: launches the QML panel without a console window.
- `run_panel_hidden.pyw`: QML panel bootstrapper.
- `gui_qml_trial.py`: QML application entry.
- `qml/Main.qml`: QML user interface.
- `backend/qml_bridge.py`: QML bridge that writes runtime config, validates capabilities, and launches the runtime executable.
- `6_run_web_panel.vbs`: optional Web fallback entry.
- `backend/web_panel_controller.py`: Web fallback controller.
- `runtime/`: runtime directory used by the panel.
- `runtime/TRT_ZeroCopy_Pipeline.exe`: inference core executable.
- `runtime/config.txt`: runtime config consumed by the executable.
- `runtime/logi_driver.dll`: preserved input driver DLL.
- `gui_settings.json`: panel state only, not the runtime's final source of truth.

## First Run

1. Install the VC++ runtime with `1_install_vcredist.bat` if needed.
2. Install Python dependencies with `5_install_panel_python_deps.bat` if needed.
3. Start the panel with `6_run_qml_panel.vbs`.
4. In the QML panel, select the model/engine, adjust parameters, save, and start the runtime.

## Update Rule

QML is the main chain. Do not add these paths to `delete[]` unless you are intentionally publishing a Web-only rollback:

- `qml/`
- `backend/qml_bridge.py`
- `6_run_qml_panel.vbs`
- `run_panel_hidden.pyw`
- `gui_qml_trial.py`

Update packages should preserve customer-local files such as `runtime/config.txt`, `runtime/logi_driver.dll`, and `gui_settings.json`.
