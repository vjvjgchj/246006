import json
import tempfile
import threading
import time
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

    def test_running_pipeline_keeps_restart_only_settings_until_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bridge = self._bridge(root)

            class RunningProcess:
                def poll(self):
                    return None

            bridge.pipeline_process = RunningProcess()
            bridge._write_pipeline_config = lambda: True
            try:
                bridge.updateVisualSettings(
                    {
                        "roi": 640,
                        "lghub_enabled": False,
                        "pipeline_mode": "调试模式",
                        "conf": 0.321,
                    }
                )

                self.assertEqual(bridge.roi, 416)
                self.assertTrue(bridge.lghub_enabled)
                self.assertEqual(bridge.pipeline_mode, "性能模式")
                self.assertAlmostEqual(bridge.conf, 0.321)
            finally:
                bridge.pipeline_process = None
                bridge.shutdown()

    def test_config_replace_failure_keeps_previous_runtime_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "models").mkdir()
            engine = root / "models" / "hp.engine"
            engine.write_bytes(b"engine")
            bridge = self._bridge(root)
            bridge.engine_path = str(engine)
            config_path = root / "runtime" / "config.txt"
            config_path.write_text("previous-config\n", encoding="utf-8")
            try:
                with patch("backend.atomic_file.os.replace", side_effect=OSError("replace failed")):
                    self.assertFalse(bridge._write_pipeline_config())
                self.assertEqual(config_path.read_text(encoding="utf-8"), "previous-config\n")
            finally:
                bridge.shutdown()

    def test_esp32_worker_updates_qt_model_on_main_thread(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bridge = self._bridge(root)
            main_thread_id = threading.get_ident()
            append_thread_ids = []
            original_append = bridge.log_model.append_line

            def recording_append(text, level):
                append_thread_ids.append(threading.get_ident())
                original_append(text, level)

            bridge.log_model.append_line = recording_append
            bridge._list_serial_ports = lambda: []
            try:
                bridge.autoDetectEsp32Serial()
                deadline = time.time() + 2.0
                while bridge.esp32_scan_running and time.time() < deadline:
                    self._app.processEvents()
                    time.sleep(0.01)
                self._app.processEvents()

                self.assertFalse(bridge.esp32_scan_running)
                self.assertTrue(append_thread_ids)
                self.assertEqual(set(append_thread_ids), {main_thread_id})
            finally:
                bridge.shutdown()

    def test_stop_pipeline_signals_graceful_event_before_kill(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bridge = self._bridge(root)
            calls = []

            class GracefulProcess:
                pid = 1234

                def poll(self):
                    return None

                def wait(self, timeout=None):
                    calls.append(("wait", timeout))
                    return 0

                def kill(self):
                    calls.append(("kill", None))

            bridge.pipeline_process = GracefulProcess()
            bridge._pipeline_stop_event_name = "Local\\NekoPipelineStop-test"
            bridge._signal_pipeline_stop_event = lambda: calls.append(("signal", None)) or True
            try:
                bridge.stopPipeline()
                self.assertEqual(calls[0], ("signal", None))
                self.assertNotIn(("kill", None), calls)
            finally:
                bridge.pipeline_process = None
                bridge.shutdown()

    def test_capture_card_refresh_prefers_formal_core_devices_and_maps_preview(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bridge = self._bridge(root)
            try:
                bridge._runtime_capture_card_devices = lambda: (
                    [{"index": 7, "name": "USB HDMI Capture", "backend": "media_foundation"}],
                    "",
                )
                bridge.capture_card_service.enumerate_devices = lambda: (
                    [{"index": 2, "name": "USB HDMI Capture", "backend": "dshow"}],
                    "采集卡就绪",
                )

                bridge.refreshCaptureCardDevices()
                deadline = time.time() + 2.0
                while bridge.capture_card_refresh_running and time.time() < deadline:
                    self._app.processEvents()
                    time.sleep(0.01)
                self._app.processEvents()

                self.assertFalse(bridge.capture_card_refresh_running)
                self.assertEqual(len(bridge.captureCardDevices), 1)
                self.assertEqual(bridge.captureCardDevices[0]["backend"], "media_foundation")
                self.assertEqual(bridge.captureCardDevices[0]["index"], 7)
                self.assertEqual(bridge.captureCardDevices[0]["previewIndex"], 2)
                self.assertEqual(bridge.captureCardDeviceIndexValue, 7)
            finally:
                bridge.shutdown()

    def test_capture_card_config_writes_formal_core_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "models").mkdir()
            engine = root / "models" / "capture.engine"
            engine.write_bytes(b"engine")
            bridge = self._bridge(root)
            try:
                bridge.engine_path = str(engine)
                bridge.setCaptureCardConfig(
                    {
                        "capture_source": "capture_card",
                        "capture_card_device_index": 3,
                        "capture_card_device_name": "HDMI IN",
                        "capture_card_width": 1920,
                        "capture_card_height": 1080,
                        "capture_card_fps": 59.94,
                        "capture_card_pixel_format": "MJPG",
                        "capture_preview": True,
                    }
                )

                self.assertTrue(bridge._write_pipeline_config())
                config_text = (root / "runtime" / "config.txt").read_text(encoding="utf-8")

                self.assertIn("capture_source=capture_card\n", config_text)
                self.assertIn("capture_card_device_index=3\n", config_text)
                self.assertIn("capture_card_device_name=HDMI IN\n", config_text)
                self.assertIn("capture_card_width=1920\n", config_text)
                self.assertIn("capture_card_height=1080\n", config_text)
                self.assertIn("capture_card_fps=59.940\n", config_text)
                self.assertIn("capture_card_pixel_format=mjpg\n", config_text)
                self.assertIn("capture_preview=1\n", config_text)
            finally:
                bridge.shutdown()

    def test_pipeline_start_and_shutdown_release_capture_preview(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bridge = self._bridge(root)
            released = []
            try:
                bridge.capture_source = "capture_card"
                bridge.capture_card_preview_active = True
                bridge.stopCaptureCardPreview = lambda: released.append("preview")
                bridge.lghub_enabled = False
                bridge._write_pipeline_config = lambda: False

                bridge.startPipeline({})
                bridge.shutdown()

                self.assertEqual(released, ["preview", "preview"])
            finally:
                bridge.pipeline_process = None


if __name__ == "__main__":
    unittest.main()
