import json
import unittest
import urllib.error
import urllib.request

from backend.mobile_control_server import (
    FIELD_BY_KEY,
    MobileControlError,
    MobileControlServer,
    MOTION_MODE_TEXT,
    PIPELINE_MODE_TEXT,
    TRIGGER_MODE_TEXT,
    WEB_PANEL_HTML,
    mobile_control_schema,
    validate_config_patch,
)


def request_json(url, method="GET", payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=2.0) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def request_text(url):
    with urllib.request.urlopen(url, timeout=2.0) as response:
        return response.status, response.read().decode("utf-8")


def request_text_response(url):
    with urllib.request.urlopen(url, timeout=2.0) as response:
        return response.status, response.read().decode("utf-8"), response.headers.get("Content-Type", "")


class MobileControlServerTest(unittest.TestCase):
    def test_validate_patch_rejects_unknown_fields(self):
        with self.assertRaises(MobileControlError) as caught:
            validate_config_patch({"texture_preprocess_plugin": 1})

        self.assertEqual(caught.exception.status, 422)
        self.assertEqual(caught.exception.code, "VALIDATION_ERROR")

    def test_validate_patch_coerces_safe_fields(self):
        clean = validate_config_patch(
            {
                "conf": "0.42",
                "fps_limit": "144",
                "kalman_en": "true",
                "trigger_mode": 1,
                "trigger_hitbox_enter_scale": "2.50",
                "card_opacity": "15",
            }
        )

        self.assertEqual(clean["conf"], 0.42)
        self.assertEqual(clean["fps_limit"], 144)
        self.assertIs(clean["kalman_en"], True)
        self.assertEqual(clean["trigger_mode"], TRIGGER_MODE_TEXT[1])
        self.assertEqual(clean["trigger_hitbox_enter_scale"], 2.5)
        self.assertEqual(clean["card_opacity"], 15)

    def test_validate_patch_coerces_advanced_runtime_fields(self):
        clean = validate_config_patch(
            {
                "model_path": "models/hp.onnx",
                "engine_path": "models/hp.engine",
                "imgsz": "640",
                "roi": "416",
                "pipeline_mode": 1,
                "motion_mode": "neural",
                "aim_keys": "0x02,5",
                "trigger_keys": "1",
                "lghub_enabled": "false",
                "esp32_enabled": "true",
                "esp32_port": "COM3",
                "esp32_baud": "115200",
                "card_opacity": "92",
                "background_image_path": "assets/bg.png",
            }
        )

        self.assertEqual(clean["model_path"], "models/hp.onnx")
        self.assertEqual(clean["engine_path"], "models/hp.engine")
        self.assertEqual(clean["imgsz"], 640)
        self.assertEqual(clean["roi"], 416)
        self.assertEqual(clean["pipeline_mode"], PIPELINE_MODE_TEXT[1])
        self.assertEqual(clean["motion_mode"], MOTION_MODE_TEXT[1])
        self.assertEqual(clean["aim_keys"], "2,5")
        self.assertEqual(clean["trigger_keys"], "1")
        self.assertIs(clean["lghub_enabled"], False)
        self.assertIs(clean["esp32_enabled"], True)
        self.assertEqual(clean["esp32_port"], "COM3")
        self.assertEqual(clean["esp32_baud"], 115200)
        self.assertEqual(clean["card_opacity"], 92)
        self.assertEqual(clean["background_image_path"], "assets/bg.png")

    def test_theme_fields_are_removed_from_web_schema(self):
        schema = {item["key"]: item for item in mobile_control_schema()}

        self.assertNotIn("theme_name", schema)
        self.assertNotIn("custom_theme_color", schema)
        self.assertNotIn("theme", {item["kind"] for item in schema.values()})

        with self.assertRaises(MobileControlError) as caught:
            validate_config_patch({"theme_name": "紫电星云"})

        self.assertEqual(caught.exception.status, 422)
        self.assertIn("theme_name", str(caught.exception.details))

    def test_validate_patch_rejects_out_of_range_values(self):
        with self.assertRaises(MobileControlError) as caught:
            validate_config_patch({"conf": "1.5"})

        self.assertEqual(caught.exception.status, 422)
        self.assertIn("conf", str(caught.exception.details))

    def test_schema_marks_non_hot_runtime_fields(self):
        schema = {item["key"]: item for item in mobile_control_schema()}

        self.assertIn("engine_path", schema)
        self.assertFalse(schema["engine_path"]["hot"])
        self.assertFalse(FIELD_BY_KEY["roi"].hot)
        self.assertTrue(schema["conf"]["hot"])

    def test_http_requires_pin_for_state_and_patch(self):
        server = MobileControlServer(
            state_provider=lambda: {"config": {"conf": 0.5}, "logs": []},
            update_handler=lambda patch: {"config": patch, "logs": []},
            host="127.0.0.1",
            port=0,
            pin="123456",
        )
        server.start()
        try:
            base_url = f"http://127.0.0.1:{server.port}"
            status, body = request_json(f"{base_url}/api/state")
            self.assertEqual(status, 403)
            self.assertEqual(body["error"]["code"], "FORBIDDEN")

            status, body = request_json(f"{base_url}/api/config", method="PATCH", payload={"conf": 0.4})
            self.assertEqual(status, 403)
            self.assertEqual(body["error"]["code"], "FORBIDDEN")
        finally:
            server.stop()

    def test_patch_updates_and_returns_state(self):
        state = {"config": {"conf": 0.5}, "runtime": {"isPipelineRunning": False}, "logs": ["ready"]}

        def update_handler(patch):
            state["config"].update(patch)
            return dict(state)

        server = MobileControlServer(
            state_provider=lambda: dict(state),
            update_handler=update_handler,
            host="127.0.0.1",
            port=0,
            pin="123456",
        )
        server.start()
        try:
            base_url = f"http://127.0.0.1:{server.port}"
            status, body = request_json(
                f"{base_url}/api/config?pin=123456",
                method="PATCH",
                payload={"conf": "0.33", "trigger_mode": 2},
            )

            self.assertEqual(status, 200)
            self.assertTrue(body["ok"])
            self.assertEqual(body["data"]["config"]["conf"], 0.33)
            self.assertEqual(body["data"]["config"]["trigger_mode"], TRIGGER_MODE_TEXT[2])
        finally:
            server.stop()

    def test_pipeline_actions_call_action_handler(self):
        actions = []

        def action_handler(action, payload):
            actions.append((action, payload))
            return {"config": {}, "runtime": {"isPipelineRunning": action == "pipeline.start"}, "logs": [action]}

        server = MobileControlServer(
            state_provider=lambda: {"config": {}, "logs": []},
            update_handler=lambda patch: {"config": patch, "logs": []},
            action_handler=action_handler,
            host="127.0.0.1",
            port=0,
            pin="123456",
        )
        server.start()
        try:
            base_url = f"http://127.0.0.1:{server.port}"
            status, body = request_json(f"{base_url}/api/pipeline/start?pin=123456", method="POST", payload={})

            self.assertEqual(status, 200)
            self.assertTrue(body["data"]["runtime"]["isPipelineRunning"])
            self.assertEqual(actions, [("pipeline.start", {})])
        finally:
            server.stop()

    def test_panel_action_endpoint_calls_action_handler(self):
        actions = []

        def action_handler(action, payload):
            actions.append((action, payload))
            return {"config": {}, "runtime": {"isPipelineRunning": False}, "logs": [action]}

        server = MobileControlServer(
            state_provider=lambda: {"config": {}, "logs": []},
            update_handler=lambda patch: {"config": patch, "logs": []},
            action_handler=action_handler,
            host="127.0.0.1",
            port=0,
            pin="123456",
        )
        server.start()
        try:
            base_url = f"http://127.0.0.1:{server.port}"
            status, body = request_json(
                f"{base_url}/api/action?pin=123456",
                method="POST",
                payload={"action": "update.check", "payload": {"source": "sidebar"}},
            )

            self.assertEqual(status, 200)
            self.assertTrue(body["ok"])
            self.assertEqual(actions, [("update.check", {"source": "sidebar"})])
        finally:
            server.stop()

    def test_file_browse_actions_are_allowed_by_panel_endpoint(self):
        actions = []

        def action_handler(action, payload):
            actions.append((action, payload))
            return {"config": {}, "runtime": {"isPipelineRunning": False}, "logs": [action]}

        server = MobileControlServer(
            state_provider=lambda: {"config": {}, "logs": []},
            update_handler=lambda patch: {"config": patch, "logs": []},
            action_handler=action_handler,
            host="127.0.0.1",
            port=0,
            pin="123456",
        )
        server.start()
        try:
            base_url = f"http://127.0.0.1:{server.port}"
            status, body = request_json(
                f"{base_url}/api/action?pin=123456",
                method="POST",
                payload={"action": "file.browse_model", "payload": {}},
            )

            self.assertEqual(status, 200)
            self.assertTrue(body["ok"])
            self.assertEqual(actions, [("file.browse_model", {})])
        finally:
            server.stop()

    def test_serves_web_panel_shell(self):
        server = MobileControlServer(
            state_provider=lambda: {"config": {}, "logs": []},
            update_handler=lambda patch: {"config": patch, "logs": []},
            host="127.0.0.1",
            port=0,
            pin="123456",
        )
        server.start()
        try:
            status, body, content_type = request_text_response(f"http://127.0.0.1:{server.port}/?pin=123456")
            self.assertEqual(status, 200)
            self.assertIn("Neko Web 面板", body)
            self.assertIn('charset="utf-8"', body)
            self.assertIn("charset=utf-8", content_type.lower())
            self.assertIn("/api/config", body)
            self.assertNotIn("theme_name", body)
            self.assertNotIn("custom_theme_color", body)
            for text in (
                "TRT Quantum",
                "控制面板",
                "运行状态",
                "Update",
                "系统监控",
                "模型编译",
                "运行控制",
                "基础参数",
                "自瞄参数",
                "扳机、粘性与压枪",
                "目标类别",
                "ESP32 串口",
                "Web 面板",
                "日志",
                "录入",
                "自瞄键:",
                "扳机键:",
                "推理运行中",
                "已开启",
                "请先停止",
                "暂无日志",
            ):
                self.assertIn(text, body)
            for text in ("shell-grid", "side-card", "collectConfigFromDom", "beginKeyRecord", "data-field-key"):
                self.assertIn(text, body)
            self.assertIn('input.className = "switch";\n        input.dataset.fieldKey = field.key;', body)
            self.assertIn('id="browseModelBtn">浏览模型</button>', body)
            self.assertIn('id="browseEngineBtn">浏览引擎</button>', body)
            self.assertIn('panelAction("file.browse_model")', body)
            self.assertIn('panelAction("file.browse_engine")', body)
            self.assertIn('id="closeWebBtn"', body)
            self.assertIn("关闭 Web 面板</button>", body)
            self.assertIn('id="mobileUrlInput"', body)
            self.assertIn('id="copyMobileUrlBtn"', body)
            self.assertIn("function copyText(text)", body)
            self.assertIn("function renderLogs(lines)", body)
            self.assertIn("logs.replaceChildren();", body)
            self.assertIn('document.createElement("a")', body)
            self.assertIn("state?.web?.url || state?.web?.localUrl", body)
            self.assertNotIn('logs.textContent = (state?.logs || []).join("\\n")', body)
            self.assertIn('notifyClientOpen()', body)
            self.assertIn('function notifyClientClosed', body)
            self.assertIn('notifyClientClosed("pagehide")', body)
            self.assertIn('sendLifecycleAction("web.close", {reason});', body)
            self.assertIn('sendLifecycleAction("web.shutdown", {reason: "button"});', body)
            self.assertNotIn('notifyClientClosed("button")', body)
            self.assertIn('function adjustNumberByWheel', body)
            self.assertIn('number.addEventListener("wheel"', body)
        finally:
            server.stop()

    def test_web_panel_actions_use_lightweight_render_to_avoid_jitter(self):
        body = WEB_PANEL_HTML

        self.assertIn("function shouldRebuildConfigAfterAction(action)", body)
        self.assertIn("const rebuildConfig = shouldRebuildConfigAfterAction(action);", body)
        self.assertIn("renderState(rebuildConfig);", body)
        self.assertIn("if (!rebuildConfig) syncConfigControlsFromState();", body)
        self.assertNotIn("renderState(true);\n        setToast(\"宸叉墽琛? \" + action);", body)

    def test_key_recording_blocks_browser_mouse_shortcuts(self):
        body = WEB_PANEL_HTML

        self.assertIn("function handleRecordingPointerEvent(event)", body)
        self.assertIn("event.stopImmediatePropagation();", body)
        self.assertIn("const mouseVk = {0: 1, 1: 4, 2: 2, 3: 5, 4: 6}[event.button];", body)
        for event_name in ("pointerdown", "pointerup", "mousedown", "mouseup", "auxclick", "contextmenu"):
            self.assertIn(f'document.addEventListener("{event_name}", handleRecordingPointerEvent, true);', body)

    def test_key_recording_collects_multiple_keys_until_escape(self):
        body = WEB_PANEL_HTML

        self.assertIn("let recordingKeys = [];", body)
        self.assertIn("function addRecordedKey(vk)", body)
        self.assertIn("function commitKeyRecord()", body)
        self.assertIn('panelAction(target === "aim" ? "keys.record_aim" : "keys.record_trigger", {keys: recordingKeys});', body)
        self.assertIn("commitKeyRecord();", body)
        self.assertNotIn("finishKeyRecord(event.keyCode || event.which || 0);", body)
        self.assertNotIn("finishKeyRecord(mouseVk || 0);", body)

    def test_web_panel_removes_appearance_background_and_stickiness(self):
        body = WEB_PANEL_HTML

        for removed in (
            'id="appearanceFields"',
            'id="backgroundFields"',
            'id="backgroundState"',
            'id="browseBackgroundBtn"',
            'id="clearBackgroundBtn"',
            'panelAction("file.browse_background")',
            'panelAction("background.clear")',
            'renderFields("appearanceFields"',
            'renderFields("backgroundFields"',
            '"stick_enable"',
            '"stick_int"',
            '"stick_rad"',
        ):
            self.assertNotIn(removed, body)

    def test_web_panel_renders_class_choice_list(self):
        body = WEB_PANEL_HTML

        self.assertIn("function renderClassChoices()", body)
        self.assertIn('id="classChoiceList"', body)
        self.assertIn("data-class-id", body)
        self.assertIn('schedulePatch("selected_classes_text"', body)

    def test_class_choice_keeps_pending_selection_during_poll_refresh(self):
        body = WEB_PANEL_HTML

        self.assertIn("const pendingValues = new Map();", body)
        self.assertIn('pendingConfigValue("selected_classes_text"', body)
        self.assertIn("pendingValues.set(key, value);", body)
        self.assertIn("for (const [pendingKey, pendingValue] of pendingValues)", body)
        self.assertIn("payload[key] = submittedValue;", body)
        self.assertIn("checkbox.checked = true;", body)
        self.assertIn('state.config = {...state.config, selected_classes_text: next};', body)


if __name__ == "__main__":
    unittest.main()
