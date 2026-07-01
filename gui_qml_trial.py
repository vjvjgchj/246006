import os
import sys

from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from backend.qml_bridge import QmlBridge


def main():
    project_root = os.path.dirname(os.path.abspath(__file__))
    qml_path = os.path.join(project_root, "qml", "Main.qml")

    QQuickStyle.setStyle("Basic")
    app = QApplication(sys.argv)

    backend = QmlBridge(project_root)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    app.aboutToQuit.connect(backend.shutdown)
    engine.load(os.path.abspath(qml_path))

    if not engine.rootObjects():
        raise SystemExit(f"QML load failed: {qml_path}")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
