import os
import shutil
import sys
import time
import traceback
from datetime import datetime


def _project_root():
    return os.path.dirname(os.path.abspath(__file__))


def _log_path():
    log_dir = os.path.join(_project_root(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "web_panel_launcher.log")


def _show_error(message):
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            message,
            "Neko web panel startup failed",
            0x00000010,
        )
    except Exception:
        pass


def _cleanup_retired_qml_paths(root, log):
    retired_paths = [
        "qml",
        os.path.join("backend", "qml_bridge.py"),
        "6_run_qml_panel.vbs",
        "run_panel_hidden.pyw",
        "gui_qml_trial.py",
        "keyauth_login.py",
    ]
    for relative in retired_paths:
        target = os.path.abspath(os.path.join(root, relative))
        try:
            if os.path.commonpath([root, target]) != root:
                print(f"[WARN] Skip unsafe retired path: {relative}", file=log)
                continue
            if os.path.isdir(target):
                shutil.rmtree(target)
                print(f"[INFO] Removed retired QML directory: {relative}", file=log)
            elif os.path.isfile(target):
                os.remove(target)
                print(f"[INFO] Removed retired QML file: {relative}", file=log)
        except Exception as exc:
            print(f"[WARN] Failed to remove retired QML path {relative}: {exc}", file=log)


def main():
    root = _project_root()
    os.chdir(root)
    log_file = _log_path()
    with open(log_file, "a", encoding="utf-8", buffering=1) as log:
        sys.stdout = log
        sys.stderr = log
        print("")
        print("=" * 72)
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Starting Neko web panel")
        print(f"Python: {sys.executable}")
        print(f"Root:   {root}")

        try:
            _cleanup_retired_qml_paths(root, log)
            from backend.web_panel_controller import WebPanelController

            controller = WebPanelController(root)
            target = controller.start_web_panel(open_browser=True)
            print(f"Open:   {target or 'Web panel did not provide a URL.'}")
            try:
                while not controller.shutdown_requested():
                    time.sleep(0.5)
            finally:
                controller.shutdown()
        except SystemExit:
            raise
        except BaseException:
            traceback.print_exc()
            _show_error(
                "Neko Web 面板启动失败。\n\n"
                f"错误详情已写入：\n{log_file}"
            )
            raise


if __name__ == "__main__":
    main()
