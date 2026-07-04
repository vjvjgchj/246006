import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PySide6.QtCore import QCoreApplication
except Exception:  # pragma: no cover - PySide6 is optional in some environments
    QCoreApplication = None

from backend.qml_bridge import QmlBridge


@unittest.skipIf(QCoreApplication is None, "PySide6 is not available")
class QmlBridgeClassSelectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QCoreApplication.instance() or QCoreApplication([])

    def _bridge(self, root: Path) -> QmlBridge:
        (root / "runtime").mkdir(exist_ok=True)
        return QmlBridge(str(root))

    def test_empty_selected_classes_survives_model_refresh(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bridge = self._bridge(root)
            try:
                bridge.selected_classes_text = ""

                bridge._apply_parsed_model_info(["0 - enemy", "1 - teammate"], "parsed")

                self.assertEqual(bridge.selected_classes_text, "")
                self.assertEqual(bridge._selected_classes_list(), [])
                self.assertEqual(bridge.class_model.selected_ids(), [])
            finally:
                bridge.shutdown()

    def test_empty_selected_classes_patch_writes_empty_runtime_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "models").mkdir()
            engine = root / "models" / "hp.engine"
            engine.write_bytes(b"engine")
            (root / "gui_settings.json").write_text(
                json.dumps({"selected_classes": ["0"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            bridge = self._bridge(root)
            bridge.engine_path = str(engine)
            bridge.class_model.set_items(["0 - enemy", "1 - teammate"], ["0"])
            try:
                bridge.saveSettings({"selected_classes_text": ""})
                self.assertTrue(bridge._write_pipeline_config())
                config_text = (root / "runtime" / "config.txt").read_text(encoding="utf-8")
                settings = json.loads((root / "gui_settings.json").read_text(encoding="utf-8"))

                self.assertEqual(bridge.selected_classes_text, "")
                self.assertEqual(bridge._selected_classes_list(), [])
                self.assertEqual(bridge.class_model.selected_ids(), [])
                self.assertEqual(settings["selected_classes"], [])
                self.assertIn("target_classes=\n", config_text)
            finally:
                bridge.shutdown()

    def test_lghub_missing_virtual_mouse_is_rebuilt_before_pipeline_start(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bridge = self._bridge(root)
            calls = []
            present_results = iter([False, False, True])
            try:
                bridge._has_present_ghub_virtual_mouse = lambda: next(present_results)
                bridge._is_process_elevated = lambda: True
                bridge._find_lghub_virtual_driver_manager = (
                    lambda: r"C:\ProgramData\LGHUB\depots\741892\driver_hid_virtual\virtual_driver_manager.exe"
                )
                bridge._run_lghub_virtual_driver_manager = (
                    lambda manager, arg: calls.append(("manager", arg)) or True
                )
                bridge._trigger_pnp_device_scan = lambda: calls.append(("scan", "")) or True

                with patch("backend.qml_bridge.time.sleep", lambda _seconds: None):
                    self.assertTrue(bridge._ensure_lghub_virtual_mouse_ready())

                self.assertEqual(
                    calls,
                    [
                        ("manager", "--uninstall"),
                        ("manager", "--install"),
                        ("scan", ""),
                    ],
                )
                self.assertTrue(
                    any("Logitech G HUB Virtual Mouse 已恢复" in line for line in bridge._log_lines)
                )
            finally:
                bridge.shutdown()

    def test_lghub_missing_virtual_mouse_blocks_start_without_admin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bridge = self._bridge(root)
            try:
                bridge._has_present_ghub_virtual_mouse = lambda: False
                bridge._is_process_elevated = lambda: False
                bridge._find_lghub_virtual_driver_manager = (
                    lambda: self.fail("repair manager should not be searched without admin")
                )

                self.assertFalse(bridge._ensure_lghub_virtual_mouse_ready())
                self.assertTrue(any("请以管理员身份运行面板" in line for line in bridge._log_lines))
            finally:
                bridge.shutdown()

    def test_start_pipeline_stops_before_writing_config_when_lghub_repair_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bridge = self._bridge(root)
            try:
                bridge.lghub_enabled = True
                bridge._ensure_lghub_virtual_mouse_ready = lambda: False
                bridge._write_pipeline_config = (
                    lambda: self.fail("config should not be written when GHUB repair fails")
                )

                bridge.startPipeline({})
            finally:
                bridge.shutdown()


if __name__ == "__main__":
    unittest.main()
