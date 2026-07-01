import os
import runpy
import sys
import traceback
from datetime import datetime


def _project_root():
    return os.path.dirname(os.path.abspath(__file__))


def _log_path():
    log_dir = os.path.join(_project_root(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "qml_panel_launcher.log")


def _show_error(message):
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            message,
            "Neko QML panel startup failed",
            0x00000010,
        )
    except Exception:
        pass


def main():
    root = _project_root()
    os.chdir(root)
    log_file = _log_path()
    with open(log_file, "a", encoding="utf-8", buffering=1) as log:
        sys.stdout = log
        sys.stderr = log
        print("")
        print("=" * 72)
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Starting Neko QML panel")
        print(f"Python: {sys.executable}")
        print(f"Root:   {root}")
        try:
            runpy.run_path(os.path.join(root, "gui_qml_trial.py"), run_name="__main__")
        except SystemExit:
            raise
        except BaseException:
            traceback.print_exc()
            _show_error(
                "Neko QML 面板启动失败。\n\n"
                f"错误详情已写入:\n{log_file}"
            )
            raise


if __name__ == "__main__":
    main()
