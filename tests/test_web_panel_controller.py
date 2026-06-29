import json
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

    def test_selected_classes_text_is_authoritative_even_when_model_list_lacks_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "runtime").mkdir()
            controller = WebPanelController(str(root), start_background_tasks=False)
            try:
                controller.selected_classes_text = "0,1,3,5,6"

                controller._apply_parsed_model_info([], "no metadata")

                self.assertEqual(controller.selected_classes_text, "0,1,3,5,6")
                self.assertEqual(controller._selected_classes_list(), ["0", "1", "3", "5", "6"])
            finally:
                controller.shutdown()

    def test_selected_classes_patch_is_not_overridden_by_previous_class_model_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "runtime").mkdir()
            controller = WebPanelController(str(root), start_background_tasks=False)
            try:
                controller.class_model.set_items(["0 - head", "1 - body", "3 - hand"], ["0"])

                state = controller.update_handler({"selected_classes_text": "1,3"})

                self.assertEqual(state["config"]["selected_classes_text"], "1,3")
                self.assertEqual(controller._selected_classes_list(), ["1", "3"])
                self.assertEqual(controller.class_model.selected_ids(), ["1", "3"])
            finally:
                controller.shutdown()

    def test_live_selected_classes_patch_persists_gui_settings_immediately(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "runtime").mkdir()
            (root / "gui_settings.json").write_text(
                json.dumps({"selected_classes": ["0", "1", "3", "5", "6"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            controller = WebPanelController(str(root), start_background_tasks=False)
            try:
                state = controller.update_handler({"selected_classes_text": "0"})
                settings = json.loads((root / "gui_settings.json").read_text(encoding="utf-8"))

                self.assertEqual(state["config"]["selected_classes_text"], "0")
                self.assertEqual(settings["selected_classes"], ["0"])
            finally:
                controller.shutdown()

    def test_live_selected_classes_patch_refreshes_runtime_config_when_not_running(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "runtime").mkdir()
            (root / "models").mkdir()
            engine_path = root / "models" / "hp.engine"
            engine_path.write_bytes(b"engine")
            controller = WebPanelController(str(root), start_background_tasks=False)
            controller.engine_path = str(engine_path)
            try:
                state = controller.update_handler({"selected_classes_text": "0"})
                config_text = (root / "runtime" / "config.txt").read_text(encoding="utf-8")

                self.assertEqual(state["config"]["selected_classes_text"], "0")
                self.assertIn("target_classes=0\n", config_text)
            finally:
                controller.shutdown()

    def test_empty_selected_classes_patch_writes_empty_runtime_target_classes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "runtime").mkdir()
            (root / "models").mkdir()
            engine_path = root / "models" / "hp.engine"
            engine_path.write_bytes(b"engine")
            (root / "gui_settings.json").write_text(
                json.dumps({"selected_classes": ["0"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            controller = WebPanelController(str(root), start_background_tasks=False)
            controller.engine_path = str(engine_path)
            controller.class_model.set_items(["0 - head", "1 - body"], ["0"])
            try:
                state = controller.update_handler({"selected_classes_text": ""})
                config_text = (root / "runtime" / "config.txt").read_text(encoding="utf-8")
                settings = json.loads((root / "gui_settings.json").read_text(encoding="utf-8"))

                self.assertEqual(state["config"]["selected_classes_text"], "")
                self.assertEqual(controller._selected_classes_list(), [])
                self.assertEqual(controller.class_model.selected_ids(), [])
                self.assertEqual(settings["selected_classes"], [])
                self.assertIn("target_classes=\n", config_text)
            finally:
                controller.shutdown()

    def test_model_class_refresh_does_not_restore_stale_selected_classes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "runtime").mkdir()
            controller = WebPanelController(str(root), start_background_tasks=False)
            try:
                controller.class_model.set_items(["0 - enemy", "1 - teammate"], ["1"])
                controller.selected_classes_text = ""

                controller._apply_parsed_model_info(["0 - enemy", "1 - teammate"], "parsed")

                self.assertEqual(controller.selected_classes_text, "")
                self.assertEqual(controller._selected_classes_list(), [])
                self.assertEqual(controller.class_model.selected_ids(), [])
            finally:
                controller.shutdown()

    def test_running_pipeline_writes_target_classes_from_latest_patch(self):
        class FakeRunningProcess:
            def poll(self):
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "runtime").mkdir()
            (root / "models").mkdir()
            engine_path = root / "models" / "hp.engine"
            engine_path.write_bytes(b"engine")
            controller = WebPanelController(str(root), start_background_tasks=False)
            controller.engine_path = str(engine_path)
            controller.pipeline_process = FakeRunningProcess()
            try:
                state = controller.update_handler({"selected_classes_text": "1,3,6"})
                config_text = (root / "runtime" / "config.txt").read_text(encoding="utf-8")

                self.assertEqual(state["config"]["selected_classes_text"], "1,3,6")
                self.assertIn("target_classes=1,3,6\n", config_text)
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
