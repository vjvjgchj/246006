import tempfile
import unittest
import urllib.request
from pathlib import Path

from backend.mobile_control_server import MobileControlServer
from backend.web_panel_controller import WebPanelController


class WebPanelControllerTest(unittest.TestCase):
    def test_controller_loads_without_qt_and_updates_hot_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "runtime").mkdir()
            (root / "models").mkdir()
            controller = WebPanelController(str(root), start_background_tasks=False)
            try:
                state = controller.update_handler({"conf": 0.42, "aim_keys": "0x02,6"})

                self.assertEqual(state["config"]["conf"], 0.42)
                self.assertEqual(state["config"]["aim_keys"], "2,6")
                self.assertEqual(state["model"]["aimKeysDisplay"], "右键 (VK:2) + 侧键2 (VK:6)")
                self.assertNotIn("theme_name", state["config"])
                self.assertNotIn("custom_theme_color", state["config"])
            finally:
                controller.shutdown()

    def test_save_action_persists_web_config_without_theme_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "runtime").mkdir()
            controller = WebPanelController(str(root), start_background_tasks=False)
            try:
                controller.update_handler({"card_opacity": 77, "background_image_path": "assets/bg.png"})
                controller.action_handler("settings.save", {})
                settings = (root / "gui_settings.json").read_text(encoding="utf-8")

                self.assertIn('"card_opacity": 77', settings)
                self.assertIn('"background_image_path": "assets\\\\bg.png"', settings)
                self.assertNotIn("theme_name", settings)
                self.assertNotIn("custom_theme_color", settings)
            finally:
                controller.shutdown()

    def test_non_hot_fields_are_locked_while_pipeline_is_running(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "runtime").mkdir()
            controller = WebPanelController(str(root), start_background_tasks=False)
            controller.pipeline_process = object()
            controller._write_pipeline_config = lambda: True
            try:
                with self.assertRaises(Exception) as caught:
                    controller.update_handler({"engine_path": "models/a.engine"})

                self.assertIn("Stop pipeline", str(caught.exception))
            finally:
                controller.pipeline_process = None
                controller.shutdown()

    def test_full_qml_style_payload_allows_unchanged_non_hot_fields_while_running(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "runtime").mkdir()
            controller = WebPanelController(str(root), start_background_tasks=False)
            controller.pipeline_process = object()
            controller._write_pipeline_config = lambda: True
            try:
                state = controller.update_handler(
                    {
                        "engine_path": "",
                        "model_path": "",
                        "imgsz": 416,
                        "roi": 416,
                        "pipeline_mode": "性能模式",
                        "conf": "0.41",
                    }
                )

                self.assertEqual(state["config"]["conf"], 0.41)

                with self.assertRaises(Exception) as caught:
                    controller.update_handler({"roi": 640})

                self.assertIn("Stop pipeline", str(caught.exception))
            finally:
                controller.pipeline_process = None
                controller.shutdown()

    def test_record_key_actions_update_display_without_config_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "runtime").mkdir()
            controller = WebPanelController(str(root), start_background_tasks=False)
            try:
                state = controller.action_handler("keys.record_aim", {"vk": 5})

                self.assertEqual(state["config"]["aim_keys"], "5")
                self.assertEqual(state["model"]["aimKeysDisplay"], "侧键1 (VK:5)")
            finally:
                controller.shutdown()

    def test_record_key_actions_accept_multiple_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "runtime").mkdir()
            controller = WebPanelController(str(root), start_background_tasks=False)
            try:
                state = controller.action_handler("keys.record_aim", {"keys": [2, 6]})

                self.assertEqual(state["config"]["aim_keys"], "2,6")
                self.assertIn("VK:2", state["model"]["aimKeysDisplay"])
                self.assertIn("VK:6", state["model"]["aimKeysDisplay"])
            finally:
                controller.shutdown()

    def test_file_browse_actions_update_qml_equivalent_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "runtime").mkdir()
            (root / "models").mkdir()
            model_path = root / "models" / "hp.onnx"
            engine_path = root / "models" / "hp.engine"
            background_path = root / "bg.png"
            model_path.write_bytes(b"model")
            engine_path.write_bytes(b"engine")
            background_path.write_bytes(b"image")
            controller = WebPanelController(str(root), start_background_tasks=False)
            selected = {
                "model": str(model_path),
                "engine": str(engine_path),
                "background": str(background_path),
            }
            controller._choose_local_file = lambda purpose: selected[purpose]
            try:
                state = controller.action_handler("file.browse_model", {})
                self.assertEqual(state["config"]["model_path"], "models\\hp.onnx")
                self.assertIn("已选择模型", "\n".join(state["logs"]))

                state = controller.action_handler("file.browse_engine", {})
                self.assertEqual(state["config"]["engine_path"], "models\\hp.engine")
                self.assertIn("已选择引擎", "\n".join(state["logs"]))

                state = controller.action_handler("file.browse_background", {})
                self.assertEqual(state["config"]["background_image_path"], "bg.png")
                self.assertEqual(state["runtime"]["backgroundStatusText"], "背景: 图片 bg.png")
            finally:
                controller.shutdown()

    def test_start_web_panel_refuses_when_fixed_port_is_already_open(self):
        blocker = MobileControlServer(
            state_provider=lambda: {"config": {}, "logs": []},
            update_handler=lambda patch: {"config": patch, "logs": []},
            host="0.0.0.0",
            port=0,
            pin="111111",
        )
        blocker.start()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                (root / "runtime").mkdir()
                controller = WebPanelController(str(root), start_background_tasks=False)
                controller.web_panel_port = blocker.port
                try:
                    url = controller.start_web_panel(open_browser=False)

                    self.assertEqual(url, "")
                    self.assertIsNone(controller.web_panel_server)
                    self.assertIn("固定端口", "\n".join(controller._log_lines))
                finally:
                    controller.shutdown()
        finally:
            blocker.stop()

    def test_start_web_panel_reuses_existing_session_pin_for_same_port(self):
        existing = MobileControlServer(
            state_provider=lambda: {"config": {}, "logs": []},
            update_handler=lambda patch: {"config": patch, "logs": []},
            host="0.0.0.0",
            port=0,
            pin="111111",
        )
        existing.start()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                (root / "runtime").mkdir()
                controller = WebPanelController(str(root), start_background_tasks=False)
                controller.web_panel_port = existing.port
                controller._write_web_panel_session(existing)
                try:
                    url = controller.start_web_panel(open_browser=False)

                    self.assertIn(f":{existing.port}/?pin=111111", url)
                    self.assertEqual(controller.web_panel_pin, "111111")
                    self.assertIsNone(controller.web_panel_server)
                    self.assertTrue(controller.shutdown_requested())
                finally:
                    controller.shutdown()
        finally:
            existing.stop()

    def test_lan_host_rejects_virtual_benchmark_and_link_local_addresses(self):
        self.assertFalse(WebPanelController._is_usable_web_panel_lan_ip("198.18.0.1"))
        self.assertFalse(WebPanelController._is_usable_web_panel_lan_ip("198.19.255.255"))
        self.assertFalse(WebPanelController._is_usable_web_panel_lan_ip("169.254.1.2"))
        self.assertFalse(WebPanelController._is_usable_web_panel_lan_ip("127.0.0.1"))
        self.assertTrue(WebPanelController._is_usable_web_panel_lan_ip("10.153.161.128"))
        self.assertTrue(WebPanelController._is_usable_web_panel_lan_ip("192.168.43.20"))

    def test_web_close_only_unregisters_client_without_shutdown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "runtime").mkdir()
            controller = WebPanelController(str(root), start_background_tasks=False)
            try:
                controller.action_handler("web.client_open", {"client_id": "tab-a"})
                self.assertFalse(controller.shutdown_requested())

                controller.action_handler("web.close", {"client_id": "tab-a"})

                self.assertFalse(controller.shutdown_requested())
                self.assertNotIn("tab-a", controller._web_clients)
            finally:
                controller.shutdown()

    def test_web_shutdown_requests_controller_shutdown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "runtime").mkdir()
            controller = WebPanelController(str(root), start_background_tasks=False)
            try:
                controller.action_handler("web.client_open", {"client_id": "tab-a"})
                controller.action_handler("web.shutdown", {"client_id": "tab-a", "reason": "button"})

                self.assertTrue(controller.shutdown_requested())
                self.assertEqual(controller._web_clients, {})
            finally:
                controller.shutdown()


if __name__ == "__main__":
    unittest.main()
