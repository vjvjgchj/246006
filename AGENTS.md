# Project Operating Rules

This repository directory is the packaged panel/runtime workspace. Treat it as the
active runtime package, not as the authoritative C++ core source tree.

## Directory Roles

- `E:\4.29\429\neko` is the active panel/runtime package.
- `E:\4.29\429\neko\backend\web_panel_controller.py` is the active Web panel backend. It writes runtime config, validates `--capabilities`, and launches the runtime executable.
- `E:\4.29\429\neko\backend\mobile_control_server.py` contains the Web panel UI shell and local HTTP control server.
- The old QML panel chain is retired. Do not recreate `backend\qml_bridge.py`, `qml\Main.qml`, `6_run_qml_panel.vbs`, `run_panel_hidden.pyw`, or `gui_qml_trial.py` unless the user explicitly asks to restore the archived QML path.
- `E:\4.29\429\neko\runtime` is the directory the panel actually runs from.
- `E:\4.29\429\neko\runtime\config.txt` is the runtime config consumed by the executable.
- `E:\4.29\429\neko\gui_settings.json` is panel state only; do not treat it as the runtime's final source of truth.
- `E:\4.29\429\trt_cpp_pipeline` is the current formal C++ source and build environment for `TRT_ZeroCopy_Pipeline.exe`.
- `E:\4.29\429\trt_cpp_pipeline\build_ninja` is the formal Ninja build output.
- `E:\4.29\429\neko\branches` contains old or experimental copies. Do not use it as the current runtime-core source unless the user explicitly asks to work on an archived branch.

## Runtime Core Workflow

- Make runtime C++ changes in `E:\4.29\429\trt_cpp_pipeline`, not under `neko\branches`.
- Build the core with the Visual Studio dev environment and Ninja output under `trt_cpp_pipeline\build_ninja`.
- Deploy the core by copying only `E:\4.29\429\trt_cpp_pipeline\build_ninja\TRT_ZeroCopy_Pipeline.exe` to `E:\4.29\429\neko\runtime\TRT_ZeroCopy_Pipeline.exe`.
- Do not run broad deployment scripts blindly if they may overwrite runtime DLLs.
- Preserve `E:\4.29\429\neko\runtime\logi_driver.dll` unless the user explicitly asks to update the input driver DLL.
- Do not replace the working runtime `logi_driver.dll` with `E:\4.29\429\trt_cpp_pipeline\build_ninja\logi_driver.dll`; the latter is a small build artifact and is not the currently working direct-syscall/LGS runtime DLL.
- `ghub_device4.dll` is abandoned for the current Logitech path.

## Logitech/Input Driver Notes

- The active Logitech path is the direct-syscall/LGS-compatible `logi_driver.dll` in `neko\runtime`.
- This DLL is expected to be used by the running core from `neko\runtime`.
- Some real mouse movement tests require the main program to run as Administrator.
- If GHUB/LGS enumeration fails, verify the actual virtual HID device path and runtime logs before changing C++ movement logic.

## PID Controller Ownership

- The current PID implementation lives in `E:\4.29\429\trt_cpp_pipeline\src\aim_pid_controller.h`.
- The current PID unit test lives in `E:\4.29\429\trt_cpp_pipeline\tests\aim_pid_controller`.
- Do not create or maintain a second PID implementation under `E:\4.29\429\neko\shared`.
- Any compatibility file under `neko\shared` must forward to the formal source or clearly state that it is archived compatibility glue.

## Required Capability Contract

The panel expects `TRT_ZeroCopy_Pipeline.exe --capabilities` to include these values:

- `capture_path=ROI_COPY_ONLY`
- `direct_interop=disabled`
- `config_safe_parse=1`
- `trt_ready_check=1`
- `cuda_error_check=1`
- `preprocess_1to1_fast_path=1`
- `target_class_postprocess=1`
- `roi_resource_double_buffer=1`
- `async_result_double_buffer=0`
- `low_latency_current_frame_result=1`
- `pinned_best_target_host=1`
- `trigger_hysteresis=1`
- `trigger_pulse_click=1`
- `trigger_recoil=1`
- `license_status=1`
- `texture_preprocess_plugin=1`
- `texture_preprocess_plugin_fp16=1`

## Build Command

Use this pattern for formal core builds:

```powershell
cmd /c "call ""D:\Program Files\Microsoft Visual Studio\18\Community\Common7\Tools\VsDevCmd.bat"" -arch=x64 -host_arch=x64 >nul && ""D:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe"" -C ""E:\4.29\429\trt_cpp_pipeline\build_ninja"" TRT_ZeroCopy_Pipeline"
```

## Verification

- Run `E:\4.29\429\trt_cpp_pipeline\tests\aim_pid_controller\pid_controller_test.exe` after PID edits.
- Run `E:\4.29\429\neko\runtime\TRT_ZeroCopy_Pipeline.exe --capabilities` after deploying a core.
- Check `E:\4.29\429\neko\runtime\logi_driver.dll` size before and after deployment; the working direct-syscall DLL is currently the larger runtime DLL, not the small build artifact.
- If panel files are edited, sync the corresponding files under `E:\4.29\429\neko\dist\neko` when that release copy is in scope.
