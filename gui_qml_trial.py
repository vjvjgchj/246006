import os
import sys

from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from backend.qml_bridge import QmlBridge
from keyauth_login import show_login


def main():
    project_root = os.path.dirname(os.path.abspath(__file__))
    qml_path = os.path.join(project_root, "qml", "Main.qml")

    try:
        QQuickStyle.setStyle("Basic")
        app = QApplication(sys.argv)

        # 启动卡密验证
        login_ok = show_login()
        if not login_ok:
            print("卡密验证取消或失败，程序退出。")
            sys.exit(0)

        backend = QmlBridge(project_root)
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("backend", backend)
        app.aboutToQuit.connect(backend.shutdown)
        engine.load(os.path.abspath(qml_path))

        if not engine.rootObjects():
            raise SystemExit(f"QML 加载失败: {qml_path}")

        sys.exit(app.exec())
    except BaseException:
        raise


if __name__ == "__main__":
    main()
