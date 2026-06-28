import ast
import ctypes
import json
import locale
import math
import os
import ipaddress
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import warnings
import webbrowser
from pathlib import Path
from urllib.parse import unquote, urlparse

try:
    import winreg
except ImportError:
    winreg = None

from backend.mobile_control_server import (
    MOBILE_CONTROL_FIELDS,
    MobileControlError,
    MobileControlServer,
    validate_config_patch,
)
from backend.update_manager import (
    UpdateError,
    apply_staged_update,
    load_manifest,
    stage_update,
)


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_ulong), ("dwHighDateTime", ctypes.c_ulong)]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class ClassSelectionState:
    def __init__(self):
        self._items = []

    @staticmethod
    def _class_id_from_option(option, index):
        text = str(option or "").strip()
        match = re.match(r"^\s*(\d+)(?:\s*[-:：].*)?$", text)
        return match.group(1) if match else str(index)

    def row_count(self):
        return len(self._items)

    def set_items(self, options, selected_ids):
        selected = {str(item) for item in (selected_ids or [])}
        items = []
        if not options:
            options = ["0 - 默认类别"]
        for index, option in enumerate(options):
            class_id = self._class_id_from_option(option, index)
            _, _, class_name = str(option).partition(" - ")
            class_name = class_name.strip() or f"class_{class_id}"
            items.append(
                {
                    "classId": class_id,
                    "className": class_name,
                    "display": f"{class_id} - {class_name}",
                    "checked": class_id in selected if selected else index == 0,
                }
            )
        self._items = items

    def selected_ids(self):
        return [item["classId"] for item in self._items if item["checked"]]

    def set_checked_from_csv(self, csv_text: str):
        selected = {part.strip() for part in str(csv_text).split(",") if part.strip()}
        if not self._items:
            return
        for item in self._items:
            item["checked"] = item["classId"] in selected


class WebPanelController:
    SAVE_FILE = "gui_settings.json"
    DEFAULT_UPDATE_MANIFEST_URL = "https://gitee.com/w246006/246006/raw/main/updates/stable.json"
    KALMAN_PRED_DEFAULT = 1.0
    KALMAN_PRED_MIN = 0.0
    KALMAN_PRED_MAX = 4.0

    def __init__(self, project_root: str, start_background_tasks: bool = True):
        self.project_root = os.path.abspath(project_root)
        self.builder_root = os.path.join(self.project_root, "engine_builder")
        self.models_root = os.path.join(self.project_root, "models")
        self.runtime_root = os.path.join(self.project_root, "runtime")
        self.runtime_config_path = os.path.join(self.runtime_root, "config.txt")
        self.runtime_exe_path = os.path.join(self.runtime_root, "TRT_ZeroCopy_Pipeline.exe")

        self.class_model = ClassSelectionState()
        self._log_lines = []
        self.conversion_process = None
        self.pipeline_process = None
        self._pipeline_stop_requested = False
        self._pending_engine_output_path = ""

        self.model_path = ""
        self.engine_path = ""
        self.imgsz = 416
        self.roi = 416
        self.conf = 0.465
        self.nms = 0.591
        self.pid_p = 0.294
        self.pid_i = 0.0
        self.pid_d = 0.0
        self.y_offset = 0.176
        self.fps_limit = 0
        self.trigger_mode = "关闭"
        self.trigger_delay = 100.0
        self.trigger_hitbox_enter_scale = 1.45
        self.trigger_hitbox_exit_scale = 1.80
        self.trigger_hold_grace_ms = 120.0
        self.kalman_en = False
        self.kalman_pred = self.KALMAN_PRED_DEFAULT
        self.recoil_en = False
        self.trigger_recoil_en = False
        self.recoil_strength = 0.0
        self.recoil_delay = 100.0
        self.pipeline_mode = "性能模式"
        self.capture_path_text = "采集链路: ROI CopySubresourceRegion (仅复制中心 ROI)"
        self.motion_mode = "经典模式"
        self.neural_curvature = 0.18
        self.neural_tremor = 0.28
        self.stick_enable = False
        self.stick_int = 0.5
        self.stick_rad = 0.05
        self.lghub_enabled = True
        self.esp32_enabled = False
        self.esp32_port = "COM3"
        self.esp32_baud = 115200
        self.esp32_scan_status = "ESP32 检测: 未执行"
        self.esp32_serial_ports_text = "串口候选: 未扫描"
        self.esp32_scan_running = False
        self.aim_keys = "2"
        self.trigger_keys = "1"
        self.aim_keys_display = "右键 (VK:2)"
        self.trigger_keys_display = "左键 (VK:1)"
        self.card_opacity = 88
        self.background_image_path = ""
        self.background_video_path = ""
        self.background_video_url = ""
        self.background_volume = 35
        self.active_background_mode = "none"
        self.selected_classes_text = "0"
        self.available_classes_text = ""
        self.model_info_text = "模型信息: 未解析"
        self.status_mode_text = "模式: 未启动"
        self.status_model_text = "模型: 未选择"
        self.status_engine_text = "引擎: 未选择"
        self.cpu_metric_text = "CPU: --"
        self.gpu_metric_text = "GPU: --"
        self.memory_metric_text = "内存: --"
        self.cpu_usage_value = -1.0
        self.gpu_usage_value = -1.0
        self.memory_usage_value = -1.0
        self.latency_metric_text = "推理延迟: --"
        self.fps_metric_text = "帧率: --"
        self.license_expiry_text = "授权到期: 检查中..."
        self.license_badge_text = "检查中"
        self.license_expiry_compact_text = "--"
        self.license_remaining_text = "正在刷新"
        self.license_status_detail = "正在读取核心授权状态"
        self.license_seconds_left = -1
        self.license_expiry_unix = 0

        self.update_manifest_url = os.environ.get("NEKO_UPDATE_MANIFEST_URL", self.DEFAULT_UPDATE_MANIFEST_URL)
        self.update_current_version = self._read_update_current_version()
        self.update_latest_version = "--"
        self.update_status_text = "更新: 未检查"
        self.update_available = False
        self.update_running = False
        self._update_pending_manifest = None
        self._update_lock = threading.Lock()
        self._update_in_flight = False

        self.last_true_fps = None
        self.last_infer_latency_ms = None
        self._cpu_prev_idle = None
        self._cpu_prev_total = None
        self._cached_gpu_usage = None
        self._gpu_poll_skip = 0
        self._metrics_lock = threading.Lock()
        self._metrics_sample_in_flight = False
        self._license_status_lock = threading.Lock()
        self._license_status_in_flight = False
        self._fps_pattern = re.compile(r"True FPS:\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
        self._avg_latency_pattern = re.compile(r"Avg Infer Latency:\s*([0-9]+(?:\.[0-9]+)?)\s*ms", re.IGNORECASE)
        self._instant_latency_pattern = re.compile(r"Infer Latency:\s*([0-9]+(?:\.[0-9]+)?)\s*ms", re.IGNORECASE)
        self._auth_expiry_pattern = re.compile(
            r"\[AUTH\]\s+License expires at\s+(.+?)(?:\s+\|\s+seconds_left=(-?\d+))?$",
            re.IGNORECASE,
        )
        self._engine_output_pattern = re.compile(
            r"(?:Engine 模型已保存至|Engine build completed|Texture preprocess plugin engine built):\s*(.+)",
            re.IGNORECASE,
        )

        self.web_panel_server = None
        self.web_panel_pin = ""
        self.web_panel_url = ""
        self.web_panel_local_url = ""
        self.web_panel_status = "Web 面板: 未启动"
        self.web_panel_port = 24600
        self.web_panel_session_path = os.path.join(self.project_root, ".updates", "web_panel_session.json")
        self._web_panel_snapshot_lock = threading.RLock()
        self._web_panel_snapshot = {}
        self._web_panel_file_cache_lock = threading.Lock()
        self._web_panel_file_cache = {"modelCandidates": [], "engineCandidates": []}
        self._web_panel_file_cache_at = 0.0
        self._web_panel_file_cache_ttl = 30.0
        self._web_panel_file_refreshing = False
        self._web_panel_non_hot_fields = {field.key for field in MOBILE_CONTROL_FIELDS if not field.hot}
        self._web_clients_lock = threading.Lock()
        self._web_clients = {}
        self._shutdown_requested = False
        self._stop_event = threading.Event()
        self._background_threads = []

        self.load_settings()
        self._update_status_labels()
        self._refresh_web_panel_snapshot()

        if start_background_tasks:
            self._start_background_tasks()

    def _start_background_tasks(self):
        self._prime_cpu_usage()
        metrics_thread = threading.Thread(target=self._metrics_loop, name="NekoWebMetrics", daemon=True)
        metrics_thread.start()
        self._background_threads.append(metrics_thread)
        threading.Thread(target=self.refreshEsp32SerialPorts, name="NekoWebSerialScan", daemon=True).start()
        self.refreshLicenseStatus()

    def _metrics_loop(self):
        self._update_system_metrics()
        while not self._stop_event.wait(1.5):
            self._update_system_metrics()

    def _emit_state(self):
        self._refresh_web_panel_snapshot()

    def _append_log(self, message: str):
        line = str(message).rstrip()
        if not line:
            return
        self._extract_runtime_metrics(line)
        self._extract_auth_status(line)
        self._log_lines.append(line)
        self._log_lines = self._log_lines[-400:]
        self._refresh_web_panel_snapshot()

    def _decode_process_output(self, raw_bytes: bytes) -> str:
        if not raw_bytes:
            return ""
        encodings = []
        preferred_encoding = locale.getpreferredencoding(False)
        for encoding in ("utf-8", "utf-8-sig", preferred_encoding, "gbk", "cp936"):
            normalized = (encoding or "").strip()
            if normalized and normalized.lower() not in {item.lower() for item in encodings}:
                encodings.append(normalized)
        for encoding in encodings:
            try:
                return raw_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw_bytes.decode("utf-8", errors="replace")

    def _hidden_process_flags(self) -> int:
        if os.name != "nt":
            return 0
        return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    def _is_pipeline_running(self) -> bool:
        if not self.pipeline_process:
            return False
        poll = getattr(self.pipeline_process, "poll", None)
        if callable(poll):
            return poll() is None
        return True

    def _is_conversion_running(self) -> bool:
        if not self.conversion_process:
            return False
        poll = getattr(self.conversion_process, "poll", None)
        return callable(poll) and poll() is None

    def _refresh_web_panel_snapshot(self):
        snapshot = self._make_web_panel_snapshot()
        with self._web_panel_snapshot_lock:
            self._web_panel_snapshot = snapshot

    def _web_panel_state_provider(self):
        with self._web_panel_snapshot_lock:
            return dict(self._web_panel_snapshot)

    def _make_web_panel_snapshot(self):
        return {
            "runtime": {
                "isPipelineRunning": self._is_pipeline_running(),
                "statusModeText": self.status_mode_text,
                "statusModelText": self.status_model_text,
                "statusEngineText": self.status_engine_text,
                "fpsMetricText": self.fps_metric_text,
                "latencyMetricText": self.latency_metric_text,
                "licenseBadgeText": self.license_badge_text,
                "licenseExpiryCompactText": self.license_expiry_compact_text,
                "licenseRemainingText": self.license_remaining_text,
                "backgroundStatusText": self._get_background_status_text(),
            },
            "update": {
                "statusText": self.update_status_text,
                "currentVersion": self.update_current_version,
                "latestVersion": self.update_latest_version,
                "available": self.update_available,
                "running": self.update_running,
                "manifestUrl": self.update_manifest_url,
            },
            "metrics": {
                "cpuText": self.cpu_metric_text,
                "gpuText": self.gpu_metric_text,
                "memoryText": self.memory_metric_text,
                "cpuUsageValue": self.cpu_usage_value,
                "gpuUsageValue": self.gpu_usage_value,
                "memoryUsageValue": self.memory_usage_value,
            },
            "model": {
                "modelInfoText": self.model_info_text,
                "availableClassesText": self.available_classes_text,
                "aimKeysDisplay": self.aim_keys_display,
                "triggerKeysDisplay": self.trigger_keys_display,
            },
            "esp32": {
                "scanStatus": self.esp32_scan_status,
                "serialPortsText": self.esp32_serial_ports_text,
                "scanRunning": self.esp32_scan_running,
            },
            "web": {
                "status": self.web_panel_status,
                "url": self.web_panel_url,
                "localUrl": self.web_panel_local_url,
                "pin": self.web_panel_pin,
            },
            "config": {
                "card_opacity": self.card_opacity,
                "background_image_path": self._to_project_config_path(self.background_image_path),
                "model_path": self._to_project_config_path(self.model_path),
                "engine_path": self._to_project_config_path(self.engine_path),
                "imgsz": self.imgsz,
                "roi": self.roi,
                "pipeline_mode": self.pipeline_mode,
                "motion_mode": self.motion_mode,
                "lghub_enabled": self.lghub_enabled,
                "esp32_enabled": self.esp32_enabled,
                "esp32_port": self.esp32_port,
                "esp32_baud": self.esp32_baud,
                "aim_keys": self.aim_keys,
                "trigger_keys": self.trigger_keys,
                "conf": self.conf,
                "nms": self.nms,
                "fps_limit": self.fps_limit,
                "selected_classes_text": self.selected_classes_text,
                "pid_p": self.pid_p,
                "pid_i": self.pid_i,
                "pid_d": self.pid_d,
                "y_offset": self.y_offset,
                "neural_curvature": self.neural_curvature,
                "neural_tremor": self.neural_tremor,
                "trigger_mode": self.trigger_mode,
                "trigger_delay": self.trigger_delay,
                "trigger_hitbox_enter_scale": self.trigger_hitbox_enter_scale,
                "trigger_hitbox_exit_scale": self.trigger_hitbox_exit_scale,
                "trigger_hold_grace_ms": self.trigger_hold_grace_ms,
                "kalman_en": self.kalman_en,
                "kalman_pred": self.kalman_pred,
                "stick_enable": self.stick_enable,
                "stick_int": self.stick_int,
                "stick_rad": self.stick_rad,
                "recoil_en": self.recoil_en,
                "trigger_recoil_en": self.trigger_recoil_en,
                "recoil_strength": self.recoil_strength,
                "recoil_delay": self.recoil_delay,
            },
            "files": self._web_panel_file_candidates(),
            "logs": list(self._log_lines[-160:]),
        }

    def _web_panel_file_candidates(self):
        now = time.monotonic()
        with self._web_panel_file_cache_lock:
            cached = {
                "modelCandidates": list(self._web_panel_file_cache.get("modelCandidates", [])),
                "engineCandidates": list(self._web_panel_file_cache.get("engineCandidates", [])),
            }
            fresh = now - self._web_panel_file_cache_at < self._web_panel_file_cache_ttl
            refreshing = self._web_panel_file_refreshing
        if fresh:
            return cached
        if not refreshing:
            self._start_web_panel_file_refresh()
        return cached

    def _start_web_panel_file_refresh(self):
        with self._web_panel_file_cache_lock:
            if self._web_panel_file_refreshing:
                return
            self._web_panel_file_refreshing = True

        def worker():
            try:
                model_candidates, engine_candidates = self._scan_web_panel_file_candidates()
                files = {"modelCandidates": model_candidates, "engineCandidates": engine_candidates}
                with self._web_panel_file_cache_lock:
                    self._web_panel_file_cache = files
                    self._web_panel_file_cache_at = time.monotonic()
                    self._web_panel_file_refreshing = False
                with self._web_panel_snapshot_lock:
                    snapshot = dict(self._web_panel_snapshot)
                    snapshot["files"] = {
                        "modelCandidates": list(model_candidates),
                        "engineCandidates": list(engine_candidates),
                    }
                    self._web_panel_snapshot = snapshot
            except Exception:
                with self._web_panel_file_cache_lock:
                    self._web_panel_file_cache_at = time.monotonic()
                    self._web_panel_file_refreshing = False

        threading.Thread(target=worker, name="NekoWebFileScan", daemon=True).start()

    def _scan_web_panel_file_candidates(self):
        model_candidates = []
        engine_candidates = []
        root = Path(self.models_root)
        if not root.exists():
            return model_candidates, engine_candidates
        try:
            paths = sorted(
                (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in (".onnx", ".engine")),
                key=lambda path: str(path).lower(),
            )
        except Exception:
            paths = []
        for path in paths[:240]:
            try:
                value = os.path.relpath(str(path), self.project_root).replace("/", "\\")
            except ValueError:
                value = str(path)
            item = {"name": path.name, "path": value}
            if path.suffix.lower() == ".onnx":
                model_candidates.append(item)
            elif path.suffix.lower() == ".engine":
                engine_candidates.append(item)
        return model_candidates, engine_candidates

    def update_handler(self, patch):
        current_config = self._web_panel_state_provider().get("config", {})
        clean = validate_config_patch(dict(patch or {}))
        locked = sorted(
            key
            for key in set(clean) & self._web_panel_non_hot_fields
            if current_config.get(key) != clean.get(key)
        )
        if locked and self._is_pipeline_running():
            raise MobileControlError(
                409,
                "PIPELINE_RUNNING",
                "Stop pipeline before changing non-hot settings",
                {"fields": locked},
            )
        self._update_from_map(clean)
        try:
            self._persist_settings()
        except Exception as exc:
            self._append_log(f"[ERROR] 实时保存 gui_settings.json 失败: {exc}")
            raise MobileControlError(500, "SETTINGS_WRITE_FAILED", "Failed to write panel settings")

        should_write_runtime_config = self._is_pipeline_running() or self._runtime_config_write_ready()
        if should_write_runtime_config and not self._write_pipeline_config():
            raise MobileControlError(409, "CONFIG_WRITE_FAILED", "Failed to write runtime config")
        self._emit_state()
        return self._web_panel_state_provider()

    def action_handler(self, action, payload=None):
        action = str(action or "").strip()
        raw_payload = dict(payload or {})
        config_actions = {
            "start",
            "pipeline.start",
            "settings.save",
            "model.convert",
            "model.netron",
            "esp32.auto",
            "esp32.probe",
        }
        action_data = validate_config_patch(raw_payload) if action in config_actions and raw_payload else {}
        if action in ("start", "pipeline.start"):
            self.startPipeline(action_data)
        elif action in ("stop", "pipeline.stop"):
            self.stopPipeline()
        elif action == "settings.save":
            self.saveSettings(action_data)
        elif action == "model.convert":
            self.startConversion(action_data)
        elif action == "model.netron":
            if action_data:
                self._update_from_map(action_data)
            self.openNetron()
        elif action == "update.check":
            self.checkForUpdates()
        elif action == "update.apply":
            self.applyAvailableUpdate()
        elif action == "background.clear":
            self.clearBackgroundImage()
        elif action == "file.browse_model":
            self.browseLocalFile("model")
        elif action == "file.browse_engine":
            self.browseLocalFile("engine")
        elif action == "file.browse_background":
            self.browseLocalFile("background")
        elif action == "esp32.refresh":
            self.refreshEsp32SerialPorts()
        elif action == "esp32.auto":
            if action_data:
                self._update_from_map(action_data)
            self.autoDetectEsp32Serial()
        elif action == "esp32.probe":
            if action_data:
                self._update_from_map(action_data)
            self.probeEsp32Connection()
        elif action == "keys.record_aim":
            self.recordKeys("aim", raw_payload)
        elif action == "keys.record_trigger":
            self.recordKeys("trigger", raw_payload)
        elif action == "keys.reset_aim":
            self.resetKeys("aim")
        elif action == "keys.reset_trigger":
            self.resetKeys("trigger")
        elif action in ("web.client_open", "web.heartbeat"):
            self._mark_web_client(raw_payload)
        elif action == "web.close":
            self._close_web_client(raw_payload)
        elif action == "web.shutdown":
            self._request_web_shutdown("button")
        else:
            raise MobileControlError(422, "VALIDATION_ERROR", "Unknown runtime action")
        self._emit_state()
        return self._web_panel_state_provider()

    def _web_client_id(self, payload) -> str:
        text = str(dict(payload or {}).get("client_id", "")).strip()
        return text[:96] if text else "default"

    def _mark_web_client(self, payload):
        client_id = self._web_client_id(payload)
        with self._web_clients_lock:
            self._web_clients[client_id] = time.monotonic()

    def _close_web_client(self, payload):
        client_id = self._web_client_id(payload)
        with self._web_clients_lock:
            self._web_clients.pop(client_id, None)

    def _request_web_shutdown(self, reason: str = ""):
        with self._web_clients_lock:
            self._web_clients.clear()
        self._shutdown_requested = True
        self._append_log(f"[INFO] Web 面板收到关闭请求，正在退出。reason={reason or 'manual'}")
        self._stop_event.set()

    def shutdown_requested(self) -> bool:
        return bool(self._shutdown_requested or self._stop_event.is_set())

    def _choose_local_file(self, purpose: str) -> str:
        purpose = str(purpose or "").strip().lower()
        options = {
            "model": {
                "title": "选择 ONNX 模型",
                "initialdir": self.models_root,
                "filetypes": [("ONNX 模型", "*.onnx"), ("所有文件", "*.*")],
            },
            "engine": {
                "title": "选择 TensorRT Engine",
                "initialdir": self.models_root,
                "filetypes": [("TensorRT Engine", "*.engine"), ("所有文件", "*.*")],
            },
            "background": {
                "title": "选择背景图片",
                "initialdir": self.project_root,
                "filetypes": [
                    ("图片文件", "*.png;*.jpg;*.jpeg;*.bmp;*.webp"),
                    ("所有文件", "*.*"),
                ],
            },
        }
        if purpose not in options:
            raise MobileControlError(422, "VALIDATION_ERROR", "Unknown file browse target")
        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception as exc:
            raise MobileControlError(500, "FILE_DIALOG_UNAVAILABLE", f"无法打开本机文件选择框: {exc}")

        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        try:
            selected = filedialog.askopenfilename(parent=root, **options[purpose])
        finally:
            try:
                root.destroy()
            except Exception:
                pass
        return str(selected or "").strip()

    def browseLocalFile(self, purpose: str):
        purpose = str(purpose or "").strip().lower()
        if purpose in ("model", "engine") and self._is_pipeline_running():
            raise MobileControlError(
                409,
                "PIPELINE_RUNNING",
                "Stop pipeline before changing non-hot settings",
                {"fields": ["model_path" if purpose == "model" else "engine_path"]},
            )
        selected = self._choose_local_file(purpose)
        if not selected:
            self._append_log("[INFO] 已取消本机文件选择。")
            return
        if purpose == "model":
            self._update_from_map({"model_path": selected})
        elif purpose == "engine":
            self._update_from_map({"engine_path": selected})
        elif purpose == "background":
            self._update_from_map(
                {
                    "background_image_path": selected,
                    "background_video_path": "",
                    "background_video_url": "",
                    "active_background_mode": "image",
                }
            )
            self._append_log(f">> 已选择背景图片: {self.background_image_path}")
        else:
            raise MobileControlError(422, "VALIDATION_ERROR", "Unknown file browse target")

    def _is_process_elevated(self) -> bool:
        if os.name != "nt":
            return True
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def _has_present_ghub_virtual_mouse(self) -> bool:
        if os.name != "nt":
            return False
        try:
            result = subprocess.run(
                ["pnputil", "/enum-devices", "/connected"],
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=self._hidden_process_flags(),
            )
        except Exception as exc:
            self._append_log(f"[WARN] GHUB 虚拟鼠标预检失败: {exc}")
            return False
        combined_output = f"{result.stdout}\n{result.stderr}".upper()
        return "LGHUBDEVICE\\VID_046D&PID_C231" in combined_output

    def _pump_pipeline_output(self, process):
        try:
            if process.stdout:
                for raw_line in iter(process.stdout.readline, b""):
                    decoded = self._decode_process_output(raw_line)
                    for line in decoded.splitlines():
                        if line.strip():
                            self._append_log(line)
        except Exception as exc:
            self._append_log(f"[WARN] 推理核心日志读取中断: {exc}")
        finally:
            exit_code = process.wait()
            self._pipeline_finished(int(getattr(process, "pid", -1)), int(exit_code))

    def _load_pyserial(self):
        try:
            import serial
            from serial.tools import list_ports

            return serial, list_ports
        except Exception:
            return None, None

    def _list_serial_ports(self):
        ports = []
        seen = set()
        _, list_ports = self._load_pyserial()
        if list_ports is not None:
            try:
                for port in list_ports.comports():
                    device = str(getattr(port, "device", "")).strip()
                    if not device or device in seen:
                        continue
                    description = str(getattr(port, "description", "") or "").strip()
                    hwid = str(getattr(port, "hwid", "") or "").strip()
                    combined = f"{device} {description} {hwid}".lower()
                    score = 0
                    for keyword in ("esp32", "usb serial", "ch340", "ch343", "cp210", "wch"):
                        if keyword in combined:
                            score += 1
                    ports.append(
                        {
                            "port": device,
                            "description": description or "未知设备",
                            "hwid": hwid,
                            "score": score,
                        }
                    )
                    seen.add(device)
            except Exception:
                pass
        if winreg is not None:
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM")
                index = 0
                while True:
                    try:
                        _, value, _ = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    device = str(value).strip()
                    if device and device not in seen:
                        ports.append({"port": device, "description": "系统串口", "hwid": "", "score": 0})
                        seen.add(device)
                    index += 1
                winreg.CloseKey(key)
            except OSError:
                pass
        ports.sort(key=lambda item: (-int(item.get("score", 0)), item["port"]))
        return ports

    def _probe_serial_port(self, port: str, baud: int):
        serial_mod, _ = self._load_pyserial()
        if serial_mod is None:
            return False, "未安装 pyserial，无法进行串口握手检测。"
        try:
            with serial_mod.Serial(port=port, baudrate=int(baud), timeout=0.35, write_timeout=0.35) as ser:
                time.sleep(1.6)
                try:
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                except Exception:
                    pass

                replies = []
                try:
                    boot_banner = ser.read(256).decode("utf-8", errors="ignore").strip()
                except Exception:
                    boot_banner = ""
                if boot_banner:
                    replies.append(boot_banner)
                    if any(token in boot_banner.upper() for token in ("PONG", "ESP32", "OK")):
                        return True, boot_banner

                for _ in range(3):
                    ser.write(b"PING\n")
                    ser.flush()
                    time.sleep(0.35)
                    reply = ser.read(256).decode("utf-8", errors="ignore").strip()
                    if reply:
                        replies.append(reply)
                        if any(token in reply.upper() for token in ("PONG", "ESP32", "OK")):
                            return True, reply or "收到有效回复"

                reply = " | ".join(part for part in replies if part).strip()
                if any(token in reply.upper() for token in ("PONG", "ESP32", "OK")):
                    return True, reply or "收到有效回复"
                return False, reply or "未收到回复"
        except Exception as exc:
            return False, str(exc)

    def _normalize_path(self, value: str) -> str:
        if not value:
            return ""
        text = str(value).strip()
        if text.startswith("file:///"):
            parsed = urlparse(text)
            return os.path.normpath(unquote(parsed.path.lstrip("/")))
        if text.startswith("file://"):
            parsed = urlparse(text)
            return os.path.normpath(unquote(parsed.path))
        if os.path.isabs(text):
            return os.path.normpath(text)
        return os.path.normpath(os.path.join(self.project_root, text))

    def _to_runtime_engine_config_path(self, engine_path: str) -> str:
        normalized = self._normalize_path(engine_path)
        if not normalized:
            return ""
        try:
            relative = os.path.relpath(normalized, self.runtime_root)
            return relative.replace("/", "\\")
        except ValueError:
            return normalized

    def _to_project_config_path(self, path_value: str) -> str:
        normalized = self._normalize_path(path_value)
        if not normalized:
            return ""
        try:
            relative = os.path.relpath(normalized, self.project_root)
            if not relative.startswith(".."):
                return relative.replace("/", "\\")
        except ValueError:
            pass
        return normalized

    def _is_texture_preprocess_engine(self, engine_path: str) -> bool:
        name = os.path.basename(self._normalize_path(engine_path)).lower()
        return "texpre" in name or "texture_preprocess" in name

    def _texture_plugin_input_size(self, engine_path: str) -> int:
        name = os.path.basename(self._normalize_path(engine_path))
        match = re.search(r"_(\d{3,4})_(?:texpre|texture_preprocess)", name, re.IGNORECASE)
        if match:
            return max(1, int(match.group(1)))
        return max(1, int(self.imgsz or self.roi or 320))

    def _texture_builder_input_size(self) -> int:
        size = self._coerce_int(self.imgsz, self._coerce_int(self.roi, 320))
        return max(32, min(2048, size))

    def _texture_preprocess_engine_path(self, model_path: str, input_size: int) -> str:
        model_name = os.path.splitext(os.path.basename(model_path))[0]
        model_name = re.sub(r"_(?:texpre|texture_preprocess)_?fp16$", "", model_name, flags=re.IGNORECASE)
        if re.search(rf"(?:^|_){input_size}$", model_name):
            return os.path.join(self.models_root, f"{model_name}_texpre_fp16.engine")
        return os.path.join(self.models_root, f"{model_name}_{input_size}_texpre_fp16.engine")

    def _pipeline_mode_code(self) -> str:
        text = str(self.pipeline_mode)
        return "debug" if text in ("调试模式", "璋冭瘯妯″紡") else "performance"

    def _motion_mode_code(self) -> str:
        text = str(self.motion_mode)
        return "neural" if text in ("神经模式", "绁炵粡妯″紡") else "classic"

    def _trigger_mode_code(self) -> int:
        text = str(self.trigger_mode)
        if text in ("连续单点", "杩炵画鍗曠偣"):
            return 1
        if text in ("连续长按开火", "杩炵画闀挎寜寮€鐏火"):
            return 2
        return 0

    def _sanitize_vk_csv(self, raw_text: str, default_value: str) -> str:
        values = []
        for part in str(raw_text).split(","):
            part = part.strip()
            if not part:
                continue
            try:
                parsed = int(part, 16) if part.lower().startswith("0x") else int(part)
                values.append(str(parsed))
            except ValueError:
                continue
        return ",".join(values) if values else default_value

    def _vk_display_name(self, vk_code: int) -> str:
        names = {
            0x01: "左键",
            0x02: "右键",
            0x04: "中键",
            0x05: "侧键1",
            0x06: "侧键2",
            0x10: "Shift",
            0x11: "Ctrl",
            0x12: "Alt",
            0x14: "CapsLock",
            0x20: "空格",
            0x25: "左方向",
            0x26: "上方向",
            0x27: "右方向",
            0x28: "下方向",
        }
        if vk_code in names:
            return names[vk_code]
        if 0x30 <= vk_code <= 0x39:
            return chr(vk_code)
        if 0x41 <= vk_code <= 0x5A:
            return chr(vk_code)
        if 0x70 <= vk_code <= 0x7B:
            return f"F{vk_code - 0x6F}"
        return f"VK:{vk_code}"

    def _format_vk_display(self, raw_text: str, default_value: str) -> str:
        csv_text = self._sanitize_vk_csv(raw_text, default_value)
        labels = []
        for part in csv_text.split(","):
            try:
                vk = int(part)
            except ValueError:
                continue
            labels.append(f"{self._vk_display_name(vk)} (VK:{vk})")
        if not labels:
            fallback = int(default_value.split(",")[0])
            labels.append(f"{self._vk_display_name(fallback)} (VK:{fallback})")
        return " + ".join(labels)

    def _refresh_key_display_from_values(self):
        self.aim_keys = self._sanitize_vk_csv(self.aim_keys, "2")
        self.trigger_keys = self._sanitize_vk_csv(self.trigger_keys, "1")
        self.aim_keys_display = self._format_vk_display(self.aim_keys, "2")
        self.trigger_keys_display = self._format_vk_display(self.trigger_keys, "1")

    def _coerce_int(self, value, default_value: int) -> int:
        text = str(value).strip()
        if not text:
            return default_value
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return default_value

    def _coerce_float(self, value, default_value: float) -> float:
        text = str(value).strip()
        if not text:
            return default_value
        try:
            return float(text)
        except (TypeError, ValueError):
            return default_value

    def _clamp_float(self, value, default_value: float, min_value: float, max_value: float) -> float:
        parsed = self._coerce_float(value, default_value)
        if not math.isfinite(parsed):
            parsed = default_value
        return max(min_value, min(max_value, parsed))

    def _legacy_neural_curvature(self, legacy_strength: float) -> float:
        return max(0.0, min(0.60, 0.05 + legacy_strength * 0.16))

    def _normalize_kalman_pred(self, value, default_value: float = None) -> float:
        fallback = self.KALMAN_PRED_DEFAULT if default_value is None else default_value
        return self._clamp_float(value, fallback, self.KALMAN_PRED_MIN, self.KALMAN_PRED_MAX)

    def _normalize_y_offset(self, value, default_value: float) -> float:
        parsed = self._coerce_float(value, default_value)
        if -0.5 <= parsed < 0.0:
            parsed = parsed + 0.5
        return max(0.0, min(1.0, parsed))

    def _clamp_y_offset(self, value, default_value: float) -> float:
        parsed = self._coerce_float(value, default_value)
        return max(0.0, min(1.0, parsed))

    def _coerce_bool(self, value, default_value: bool) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default_value
        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off"):
            return False
        return default_value

    def _resolve_background_mode(self, preferred_mode: str = "") -> str:
        preferred = str(preferred_mode or "").strip().lower()
        if preferred == "image" and self.background_image_path:
            return "image"
        if preferred == "video" and self.background_video_path:
            return "video"
        if preferred == "web" and self.background_video_url:
            return "web"
        if self.background_image_path:
            return "image"
        if self.background_video_path:
            return "video"
        if self.background_video_url:
            return "web"
        return "none"

    def _reset_runtime_metrics(self):
        self.last_true_fps = None
        self.last_infer_latency_ms = None
        self._update_runtime_metrics_labels()

    def _selected_classes_list(self):
        values = []
        seen = set()
        for part in str(self.selected_classes_text).split(","):
            part = part.strip()
            if part and part.isdigit() and part not in seen:
                values.append(part)
                seen.add(part)
        if values:
            return values
        if self.class_model.row_count() > 0:
            selected = [item for item in self.class_model.selected_ids() if str(item).isdigit()]
            if selected:
                return selected
        return values

    def _sync_selected_classes_text(self):
        self.selected_classes_text = ",".join(self._selected_classes_list()) or "0"

    def _class_options_for_display(self, options):
        clean = [str(option).strip() for option in (options or []) if str(option).strip()]
        if clean:
            return clean
        fallback_ids = []
        for class_id in [*self._selected_classes_list(), *(str(index) for index in range(80))]:
            if class_id not in fallback_ids:
                fallback_ids.append(class_id)
        return [f"{class_id} - class_{class_id}" for class_id in fallback_ids]

    def _update_status_labels(self):
        self.status_model_text = f"模型: {os.path.basename(self.model_path) if self.model_path else '未选择'}"
        self.status_engine_text = f"引擎: {os.path.basename(self.engine_path) if self.engine_path else '未选择'}"

    def _update_from_map(self, data):
        if not data:
            return
        previous_model_path = self.model_path
        previous_engine_path = self.engine_path
        self.model_path = self._normalize_path(str(data.get("model_path", self.model_path)))
        self.engine_path = self._normalize_path(str(data.get("engine_path", self.engine_path)))
        self.imgsz = self._coerce_int(data.get("imgsz", self.imgsz), self.imgsz)
        self.roi = self._coerce_int(data.get("roi", self.roi), self.roi)
        self.conf = self._coerce_float(data.get("conf", self.conf), self.conf)
        self.nms = self._coerce_float(data.get("nms", self.nms), self.nms)
        self.pid_p = self._coerce_float(data.get("pid_p", self.pid_p), self.pid_p)
        self.pid_i = self._coerce_float(data.get("pid_i", self.pid_i), self.pid_i)
        self.pid_d = self._coerce_float(data.get("pid_d", self.pid_d), self.pid_d)
        self.y_offset = self._clamp_y_offset(data.get("y_offset", self.y_offset), self.y_offset)
        self.fps_limit = max(0, self._coerce_int(data.get("fps_limit", self.fps_limit), self.fps_limit))
        self.trigger_mode = str(data.get("trigger_mode", self.trigger_mode)) or "关闭"
        self.trigger_delay = self._coerce_float(data.get("trigger_delay", self.trigger_delay), self.trigger_delay)
        self.trigger_hitbox_enter_scale = self._clamp_float(
            data.get("trigger_hitbox_enter_scale", self.trigger_hitbox_enter_scale),
            self.trigger_hitbox_enter_scale,
            0.50,
            2.50,
        )
        self.trigger_hitbox_exit_scale = self._clamp_float(
            data.get("trigger_hitbox_exit_scale", self.trigger_hitbox_exit_scale),
            self.trigger_hitbox_exit_scale,
            0.50,
            3.00,
        )
        self.trigger_hold_grace_ms = self._clamp_float(
            data.get("trigger_hold_grace_ms", self.trigger_hold_grace_ms),
            self.trigger_hold_grace_ms,
            0.0,
            250.0,
        )
        self.kalman_en = self._coerce_bool(data.get("kalman_en", self.kalman_en), self.kalman_en)
        self.kalman_pred = self._normalize_kalman_pred(data.get("kalman_pred", self.kalman_pred), self.kalman_pred)
        self.recoil_en = self._coerce_bool(data.get("recoil_en", self.recoil_en), self.recoil_en)
        self.trigger_recoil_en = self._coerce_bool(
            data.get("trigger_recoil_en", self.trigger_recoil_en), self.trigger_recoil_en
        )
        self.recoil_strength = self._coerce_float(data.get("recoil_strength", self.recoil_strength), self.recoil_strength)
        self.recoil_delay = self._coerce_float(data.get("recoil_delay", self.recoil_delay), self.recoil_delay)
        stick_enable_value = data.get("stick_enable", data.get("stick_en", self.stick_enable))
        self.stick_enable = self._coerce_bool(stick_enable_value, self.stick_enable)
        self.stick_int = self._coerce_float(data.get("stick_int", self.stick_int), self.stick_int)
        self.stick_rad = self._coerce_float(data.get("stick_rad", self.stick_rad), self.stick_rad)
        lghub_value = data.get("lghub_enabled", data.get("lghub", self.lghub_enabled))
        self.lghub_enabled = self._coerce_bool(lghub_value, self.lghub_enabled)
        self.esp32_enabled = self._coerce_bool(data.get("esp32_enabled", self.esp32_enabled), self.esp32_enabled)
        self.esp32_port = str(data.get("esp32_port", self.esp32_port)).strip() or self.esp32_port
        self.esp32_baud = max(1200, self._coerce_int(data.get("esp32_baud", self.esp32_baud), self.esp32_baud))
        self.card_opacity = self._coerce_int(data.get("card_opacity", self.card_opacity), self.card_opacity)
        self.background_image_path = self._normalize_path(str(data.get("background_image_path", self.background_image_path)))
        self.background_video_path = self._normalize_path(str(data.get("background_video_path", self.background_video_path)))
        self.background_video_url = str(data.get("background_video_url", self.background_video_url)).strip()
        self.background_volume = self._coerce_int(data.get("background_volume", self.background_volume), self.background_volume)
        self.active_background_mode = self._resolve_background_mode(data.get("active_background_mode", self.active_background_mode))
        self.pipeline_mode = str(data.get("pipeline_mode", self.pipeline_mode)) or "性能模式"
        self.motion_mode = str(data.get("motion_mode", self.motion_mode)) or "经典模式"
        self.neural_curvature = self._clamp_float(
            data.get("neural_curvature", self.neural_curvature), self.neural_curvature, 0.0, 0.60
        )
        self.neural_tremor = self._clamp_float(
            data.get("neural_tremor", self.neural_tremor), self.neural_tremor, 0.0, 1.60
        )
        self.aim_keys = str(data.get("aim_keys", self.aim_keys)).strip() or "2"
        self.trigger_keys = str(data.get("trigger_keys", self.trigger_keys)).strip() or "1"
        self._refresh_key_display_from_values()
        selected_classes_value = data.get("selected_classes_text")
        if selected_classes_value is None and isinstance(data.get("selected_classes"), list):
            selected_classes_value = ",".join(str(x) for x in data.get("selected_classes", []))
        self.selected_classes_text = str(
            selected_classes_value if selected_classes_value is not None else self.selected_classes_text
        ).strip() or "0"
        self.class_model.set_checked_from_csv(self.selected_classes_text)
        self._sync_selected_classes_text()
        self._update_status_labels()
        self._handle_path_side_effects(previous_model_path, previous_engine_path)

    def _handle_path_side_effects(self, previous_model_path: str, previous_engine_path: str):
        if self.model_path != previous_model_path:
            if self.model_path:
                self._append_log(f">> 已选择模型: {self.model_path}")
                self.parse_model_info_async(self.model_path)
            else:
                self.available_classes_text = ""
                self.model_info_text = "模型信息: 未解析"
        if self.engine_path != previous_engine_path and self.engine_path:
            self._append_log(f">> 已选择引擎: {self.engine_path}")

    def _settings_path(self):
        return os.path.join(self.project_root, self.SAVE_FILE)

    def _runtime_config_write_ready(self) -> bool:
        return bool(self.engine_path and os.path.exists(self.engine_path))

    def _load_existing_settings(self):
        path = self._settings_path()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception as exc:
            self._append_log(f">> 读取配置文件失败: {exc}")
            return {}

    def _persist_settings(self):
        settings = self._load_existing_settings()
        for obsolete_key in (
            "head_y_offset",
            "body_y_offset",
            "head_classes",
            "body_classes",
            "theme_name",
            "custom_theme_color",
        ):
            settings.pop(obsolete_key, None)
        settings.update(
            {
                "model_path": self._to_project_config_path(self.model_path),
                "engine_path": self._to_project_config_path(self.engine_path),
                "imgsz": self.imgsz,
                "roi": self.roi,
                "conf": self.conf,
                "nms": self.nms,
                "pid_p": self.pid_p,
                "pid_i": self.pid_i,
                "pid_d": self.pid_d,
                "y_offset": self.y_offset,
                "fps_limit": self.fps_limit,
                "kalman_en": self.kalman_en,
                "kalman_pred": self.kalman_pred,
                "recoil_en": self.recoil_en,
                "trigger_recoil_en": self.trigger_recoil_en,
                "recoil_strength": self.recoil_strength,
                "recoil_delay": self.recoil_delay,
                "trigger_mode": self.trigger_mode,
                "trigger_delay": self.trigger_delay,
                "trigger_hitbox_enter_scale": self.trigger_hitbox_enter_scale,
                "trigger_hitbox_exit_scale": self.trigger_hitbox_exit_scale,
                "trigger_hold_grace_ms": self.trigger_hold_grace_ms,
                "stick_enable": self.stick_enable,
                "stick_int": self.stick_int,
                "stick_rad": self.stick_rad,
                "lghub_enabled": self.lghub_enabled,
                "esp32_enabled": self.esp32_enabled,
                "esp32_port": self.esp32_port,
                "esp32_baud": self.esp32_baud,
                "stick_en": 1 if self.stick_enable else 0,
                "lghub": 1 if self.lghub_enabled else 0,
                "card_opacity": self.card_opacity,
                "background_image_path": self._to_project_config_path(self.background_image_path),
                "background_video_path": self._to_project_config_path(self.background_video_path),
                "background_video_url": self.background_video_url,
                "background_volume": self.background_volume,
                "active_background_mode": self.active_background_mode,
                "pipeline_mode": self.pipeline_mode,
                "motion_mode": self.motion_mode,
                "neural_curvature": self.neural_curvature,
                "neural_tremor": self.neural_tremor,
                "aim_keys": self.aim_keys,
                "aim_keys_display": self.aim_keys_display,
                "trigger_keys": self.trigger_keys,
                "trigger_keys_display": self.trigger_keys_display,
                "selected_classes": self._selected_classes_list(),
            }
        )
        with open(self._settings_path(), "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)

    def load_settings(self):
        settings = self._load_existing_settings()
        if not settings:
            return
        legacy_settings_detected = any(
            key in settings for key in ("head_y_offset", "body_y_offset", "head_classes", "body_classes")
        )
        settings_adjusted = legacy_settings_detected or any(
            key in settings for key in ("theme_name", "custom_theme_color")
        )
        self.model_path = self._normalize_path(settings.get("model_path", self.model_path))
        self.engine_path = self._normalize_path(settings.get("engine_path", self.engine_path))
        self.imgsz = int(settings.get("imgsz", self.imgsz))
        self.roi = int(settings.get("roi", self.roi))
        self.conf = float(settings.get("conf", self.conf))
        self.nms = float(settings.get("nms", self.nms))
        self.pid_p = float(settings.get("pid_p", self.pid_p))
        self.pid_i = float(settings.get("pid_i", self.pid_i))
        self.pid_d = float(settings.get("pid_d", self.pid_d))
        raw_y_offset = settings.get("y_offset", self.y_offset)
        self.y_offset = self._normalize_y_offset(raw_y_offset, self.y_offset)
        if self._coerce_float(raw_y_offset, self.y_offset) != self.y_offset:
            legacy_settings_detected = True
            settings_adjusted = True
        self.fps_limit = max(0, int(settings.get("fps_limit", self.fps_limit)))
        self.kalman_en = self._coerce_bool(settings.get("kalman_en", self.kalman_en), self.kalman_en)
        raw_kalman_pred = settings.get("kalman_pred", self.kalman_pred)
        self.kalman_pred = self._normalize_kalman_pred(raw_kalman_pred, self.kalman_pred)
        if self._coerce_float(raw_kalman_pred, self.kalman_pred) != self.kalman_pred:
            settings_adjusted = True
        self.recoil_en = self._coerce_bool(settings.get("recoil_en", self.recoil_en), self.recoil_en)
        self.trigger_recoil_en = self._coerce_bool(
            settings.get("trigger_recoil_en", self.trigger_recoil_en), self.trigger_recoil_en
        )
        self.recoil_strength = float(settings.get("recoil_strength", self.recoil_strength))
        self.recoil_delay = float(settings.get("recoil_delay", self.recoil_delay))
        self.trigger_mode = str(settings.get("trigger_mode", self.trigger_mode)) or "关闭"
        self.trigger_delay = float(settings.get("trigger_delay", self.trigger_delay))
        self.trigger_hitbox_enter_scale = self._clamp_float(
            settings.get("trigger_hitbox_enter_scale", self.trigger_hitbox_enter_scale),
            self.trigger_hitbox_enter_scale,
            0.50,
            2.50,
        )
        self.trigger_hitbox_exit_scale = self._clamp_float(
            settings.get("trigger_hitbox_exit_scale", self.trigger_hitbox_exit_scale),
            self.trigger_hitbox_exit_scale,
            0.50,
            3.00,
        )
        self.trigger_hold_grace_ms = self._clamp_float(
            settings.get("trigger_hold_grace_ms", self.trigger_hold_grace_ms),
            self.trigger_hold_grace_ms,
            0.0,
            250.0,
        )
        self.stick_enable = self._coerce_bool(
            settings.get("stick_enable", settings.get("stick_en", self.stick_enable)), self.stick_enable
        )
        self.stick_int = float(settings.get("stick_int", self.stick_int))
        self.stick_rad = float(settings.get("stick_rad", self.stick_rad))
        self.lghub_enabled = self._coerce_bool(
            settings.get("lghub_enabled", settings.get("lghub", self.lghub_enabled)), self.lghub_enabled
        )
        self.esp32_enabled = self._coerce_bool(settings.get("esp32_enabled", self.esp32_enabled), self.esp32_enabled)
        self.esp32_port = str(settings.get("esp32_port", self.esp32_port)).strip() or self.esp32_port
        self.esp32_baud = max(1200, int(settings.get("esp32_baud", self.esp32_baud)))
        self.card_opacity = int(settings.get("card_opacity", self.card_opacity))
        self.background_image_path = self._normalize_path(settings.get("background_image_path", self.background_image_path))
        self.background_video_path = self._normalize_path(settings.get("background_video_path", self.background_video_path))
        self.background_video_url = str(settings.get("background_video_url", self.background_video_url)).strip()
        self.background_volume = int(settings.get("background_volume", self.background_volume))
        self.active_background_mode = self._resolve_background_mode(settings.get("active_background_mode", self.active_background_mode))
        self.pipeline_mode = str(settings.get("pipeline_mode", self.pipeline_mode)) or "性能模式"
        self.motion_mode = str(settings.get("motion_mode", self.motion_mode)) or "经典模式"
        legacy_strength = settings.get("neural_strength", None)
        legacy_strength_value = None
        if legacy_strength is not None:
            legacy_strength_value = self._clamp_float(legacy_strength, 0.85, 0.0, 1.0)
        self.neural_curvature = self._clamp_float(
            settings.get(
                "neural_curvature",
                self._legacy_neural_curvature(legacy_strength_value)
                if legacy_strength_value is not None
                else self.neural_curvature,
            ),
            self.neural_curvature,
            0.0,
            0.60,
        )
        self.neural_tremor = self._clamp_float(
            settings.get("neural_tremor", self.neural_tremor), self.neural_tremor, 0.0, 1.60
        )
        self.aim_keys = str(settings.get("aim_keys", self.aim_keys)).strip() or "2"
        self.trigger_keys = str(settings.get("trigger_keys", self.trigger_keys)).strip() or "1"
        self._refresh_key_display_from_values()
        selected_classes = settings.get("selected_classes", [])
        if isinstance(selected_classes, list) and selected_classes:
            self.selected_classes_text = ",".join(str(x) for x in selected_classes)
            self.class_model.set_checked_from_csv(self.selected_classes_text)
        self.model_info_text = "模型信息: 已恢复上次配置"
        self._append_log(">> Web 面板已恢复上次保存的参数配置。")
        if settings_adjusted:
            try:
                self._persist_settings()
                if legacy_settings_detected:
                    self._append_log(">> 已自动迁移旧版 Y 偏移配置到 0~1 新语义。")
                else:
                    self._append_log(">> 已清理旧主题字段，当前 Web 只保留固定主题。")
            except Exception as exc:
                self._append_log(f"[WARN] 自动校正配置失败: {exc}")
        if self.model_path and os.path.exists(self.model_path):
            self.parse_model_info_async(self.model_path)

    def _apply_parsed_model_info(self, options, status):
        display_options = self._class_options_for_display(options)
        self.available_classes_text = "\n".join(display_options)
        self.model_info_text = status
        self.class_model.set_items(display_options, self._selected_classes_list())
        self._sync_selected_classes_text()
        self._emit_state()

    def parse_model_info_async(self, file_path: str):
        path = self._normalize_path(file_path)
        if not path or not os.path.exists(path):
            self.model_info_text = "模型信息: 文件不存在"
            self.available_classes_text = ""
            self._emit_state()
            return

        def worker():
            warnings.filterwarnings("ignore")
            options = []
            status = "模型信息: 无法读取类别"
            engine_metadata_unavailable = False
            try:
                if path.endswith(".engine"):
                    engine_metadata_unavailable = True
                    status = "模型信息: Engine 无内置类别信息，请使用 ONNX 解析或手动选择类别"
                elif path.endswith(".pt"):
                    from ultralytics import YOLO

                    model = YOLO(path, task="detect")
                    options = [f"{k} - {v}" for k, v in model.names.items()]
                elif path.endswith(".onnx"):
                    import onnx

                    model = onnx.load(path)
                    names_dict = {}
                    for prop in model.metadata_props:
                        if prop.key != "names":
                            continue
                        parsed = ast.literal_eval(prop.value)
                        if isinstance(parsed, dict):
                            names_dict = {str(k): v for k, v in parsed.items()}
                        elif isinstance(parsed, list):
                            names_dict = {str(i): name for i, name in enumerate(parsed)}
                        break
                    if not names_dict:
                        names_dict = {"0": "class_0"}
                    options = [f"{k} - {v}" for k, v in names_dict.items()]
                if options:
                    status = f"模型信息: 成功解析 {len(options)} 个类别"
                elif not engine_metadata_unavailable:
                    status = "模型信息: 未识别到类别信息"
            except Exception as exc:
                status = f"模型信息: 解析失败 ({exc})"
            self._apply_parsed_model_info(options, status)

        self.model_info_text = "模型信息: 正在解析类别..."
        self._emit_state()
        threading.Thread(target=worker, daemon=True).start()

    def _prime_cpu_usage(self):
        idle, total = self._snapshot_cpu_times()
        self._cpu_prev_idle = idle
        self._cpu_prev_total = total

    def _snapshot_cpu_times(self):
        if not hasattr(ctypes, "windll"):
            return None, None
        idle_time = FILETIME()
        kernel_time = FILETIME()
        user_time = FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle_time), ctypes.byref(kernel_time), ctypes.byref(user_time)
        ):
            return None, None
        idle = (idle_time.dwHighDateTime << 32) | idle_time.dwLowDateTime
        kernel = (kernel_time.dwHighDateTime << 32) | kernel_time.dwLowDateTime
        user = (user_time.dwHighDateTime << 32) | user_time.dwLowDateTime
        return idle, kernel + user

    def _sample_cpu_usage(self):
        idle, total = self._snapshot_cpu_times()
        if idle is None or total is None:
            return None
        if self._cpu_prev_idle is None or self._cpu_prev_total is None:
            self._cpu_prev_idle = idle
            self._cpu_prev_total = total
            return None
        idle_delta = idle - self._cpu_prev_idle
        total_delta = total - self._cpu_prev_total
        self._cpu_prev_idle = idle
        self._cpu_prev_total = total
        if total_delta <= 0:
            return None
        return max(0.0, min(100.0, (total_delta - idle_delta) * 100.0 / total_delta))

    def _sample_memory_usage(self):
        if not hasattr(ctypes, "windll"):
            return None, None, None
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None, None, None
        total_gb = status.ullTotalPhys / (1024 ** 3)
        used_gb = (status.ullTotalPhys - status.ullAvailPhys) / (1024 ** 3)
        return status.dwMemoryLoad, used_gb, total_gb

    def _sample_gpu_usage(self):
        if self._gpu_poll_skip > 0:
            self._gpu_poll_skip -= 1
            return self._cached_gpu_usage
        try:
            output = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                stderr=subprocess.DEVNULL,
                creationflags=self._hidden_process_flags(),
                timeout=0.8,
                text=True,
            ).strip()
        except Exception:
            return None
        if not output:
            return None
        parts = [part.strip() for part in output.splitlines()[0].split(",")]
        if len(parts) < 3:
            return None
        try:
            util = float(parts[0])
            used_mb = float(parts[1])
            total_mb = float(parts[2])
        except ValueError:
            return None
        self._cached_gpu_usage = (util, used_mb / 1024.0, total_mb / 1024.0)
        self._gpu_poll_skip = 1
        return self._cached_gpu_usage

    def _update_runtime_metrics_labels(self):
        self.latency_metric_text = (
            f"推理延迟: {self.last_infer_latency_ms:.2f} ms"
            if self.last_infer_latency_ms is not None
            else "推理延迟: --"
        )
        self.fps_metric_text = (
            f"帧率: {self.last_true_fps:.2f} FPS"
            if self.last_true_fps is not None
            else "帧率: --"
        )

    def refreshEsp32SerialPorts(self):
        ports = self._list_serial_ports()
        if ports:
            summary = ", ".join(item["port"] for item in ports[:12])
            self.esp32_serial_ports_text = f"串口候选: {summary}"
            self._append_log(f"[INFO] 已扫描到串口: {summary}")
            if not self.esp32_port or all(item["port"] != self.esp32_port for item in ports):
                self.esp32_port = ports[0]["port"]
        else:
            self.esp32_serial_ports_text = "串口候选: 未发现可用 COM 口"
            self._append_log("[WARN] 未扫描到可用串口。")
        self._emit_state()

    def _set_esp32_scan_running(self, running: bool):
        self.esp32_scan_running = bool(running)
        self._emit_state()

    def _set_esp32_scan_status(self, text: str):
        self.esp32_scan_status = str(text)
        self._append_log(text)
        self._emit_state()

    def autoDetectEsp32Serial(self):
        if self.esp32_scan_running:
            self._append_log("[WARN] 当前已有 ESP32 检测任务在进行。")
            return

        def worker():
            self._set_esp32_scan_running(True)
            try:
                ports = self._list_serial_ports()
                self.esp32_serial_ports_text = (
                    "串口候选: " + ", ".join(item["port"] for item in ports[:12])
                    if ports
                    else "串口候选: 未发现可用 COM 口"
                )
                if not ports:
                    self._set_esp32_scan_status("[WARN] ESP32 串口自动检测失败: 没有发现可用 COM 口。")
                    return
                baud_candidates = []
                for baud in (self.esp32_baud, 115200, 921600, 460800, 230400):
                    try:
                        parsed = int(baud)
                    except Exception:
                        continue
                    if parsed not in baud_candidates:
                        baud_candidates.append(parsed)
                serial_mod, _ = self._load_pyserial()
                if serial_mod is None:
                    best = ports[0]
                    self.esp32_port = best["port"]
                    self._set_esp32_scan_status(
                        f"[WARN] 已优先选择串口 {best['port']}，但未安装 pyserial，暂无法自动握手验证。"
                    )
                    self._emit_state()
                    return
                for port_item in ports:
                    for baud in baud_candidates:
                        ok, detail = self._probe_serial_port(port_item["port"], baud)
                        self._append_log(f"[INFO] 串口探测 {port_item['port']} @ {baud}: {'OK' if ok else detail}")
                        if ok:
                            self.esp32_port = port_item["port"]
                            self.esp32_baud = baud
                            self._set_esp32_scan_status(
                                f"[SUCCESS] 已探测到 ESP32 串口: {self.esp32_port} @ {self.esp32_baud} | {detail}"
                            )
                            self._emit_state()
                            return
                self._set_esp32_scan_status("[WARN] 未探测到可握手的 ESP32 串口，请确认 COM、波特率和固件 PING/PONG 协议。")
                self._emit_state()
            finally:
                self._set_esp32_scan_running(False)

        threading.Thread(target=worker, daemon=True).start()

    def probeEsp32Connection(self):
        if self.esp32_scan_running:
            self._append_log("[WARN] 当前已有 ESP32 检测任务在进行。")
            return

        def worker():
            self._set_esp32_scan_running(True)
            try:
                ok, detail = self._probe_serial_port(self.esp32_port, self.esp32_baud)
                if ok:
                    self.esp32_serial_ports_text = f"串口候选: 当前目标 {self.esp32_port} @ {self.esp32_baud} 响应正常"
                    self._set_esp32_scan_status(f"[SUCCESS] 串口检测通过: {self.esp32_port} @ {self.esp32_baud} | {detail}")
                else:
                    self._set_esp32_scan_status(f"[WARN] 串口检测失败: {self.esp32_port} @ {self.esp32_baud} | {detail}")
                self._emit_state()
            finally:
                self._set_esp32_scan_running(False)

        threading.Thread(target=worker, daemon=True).start()

    def _extract_runtime_metrics(self, message: str):
        fps_match = self._fps_pattern.search(message)
        if fps_match:
            self.last_true_fps = float(fps_match.group(1))
        avg_latency_match = self._avg_latency_pattern.search(message)
        if avg_latency_match:
            self.last_infer_latency_ms = float(avg_latency_match.group(1))
        else:
            latency_match = self._instant_latency_pattern.search(message)
            if latency_match:
                self.last_infer_latency_ms = float(latency_match.group(1))
        self._update_runtime_metrics_labels()

    def _collect_system_metrics(self):
        metrics = {}
        cpu_usage = self._sample_cpu_usage()
        if cpu_usage is None:
            metrics["cpu_usage_value"] = -1.0
            metrics["cpu_metric_text"] = "CPU: 采样中..."
        else:
            metrics["cpu_usage_value"] = float(cpu_usage)
            metrics["cpu_metric_text"] = f"CPU: {cpu_usage:.1f}%"

        memory_load, used_gb, total_gb = self._sample_memory_usage()
        if memory_load is None:
            metrics["memory_usage_value"] = -1.0
            metrics["memory_metric_text"] = "内存: --"
        else:
            metrics["memory_usage_value"] = float(memory_load)
            metrics["memory_metric_text"] = f"内存: {used_gb:.1f}/{total_gb:.1f} GB ({memory_load}%)"

        gpu_usage = self._sample_gpu_usage()
        if gpu_usage is None:
            metrics["gpu_usage_value"] = -1.0
            metrics["gpu_metric_text"] = "GPU: N/A"
        else:
            util, used_gpu_gb, total_gpu_gb = gpu_usage
            metrics["gpu_usage_value"] = float(util)
            metrics["gpu_metric_text"] = f"GPU: {util:.0f}% | {used_gpu_gb:.1f}/{total_gpu_gb:.1f} GB"
        return metrics

    def _apply_system_metrics(self, metrics):
        if not isinstance(metrics, dict):
            return
        self.cpu_usage_value = float(metrics.get("cpu_usage_value", -1.0))
        self.cpu_metric_text = str(metrics.get("cpu_metric_text", "CPU: --"))
        self.memory_usage_value = float(metrics.get("memory_usage_value", -1.0))
        self.memory_metric_text = str(metrics.get("memory_metric_text", "内存: --"))
        self.gpu_usage_value = float(metrics.get("gpu_usage_value", -1.0))
        self.gpu_metric_text = str(metrics.get("gpu_metric_text", "GPU: N/A"))
        self._emit_state()

    def _update_system_metrics(self):
        with self._metrics_lock:
            if self._metrics_sample_in_flight:
                return
            self._metrics_sample_in_flight = True

        def worker():
            try:
                self._apply_system_metrics(self._collect_system_metrics())
            finally:
                with self._metrics_lock:
                    self._metrics_sample_in_flight = False

        threading.Thread(target=worker, daemon=True).start()

    def _format_seconds_left(self, seconds_left: int) -> str:
        if seconds_left < 0:
            return "已过期"
        days = seconds_left // 86400
        hours = (seconds_left % 86400) // 3600
        minutes = (seconds_left % 3600) // 60
        if days > 0:
            return f"剩余 {days} 天 {hours} 小时"
        if hours > 0:
            return f"剩余 {hours} 小时 {minutes} 分钟"
        return f"剩余 {minutes} 分钟"

    def _compact_license_datetime(self, expires_local: str) -> str:
        text = str(expires_local or "").strip()
        if len(text) >= 16 and text[4:5] == "-" and text[13:14] == ":":
            return text[:16]
        return text or "--"

    def _set_license_success(self, expiry_unix: int, expires_local: str = "", message: str = ""):
        self.license_expiry_unix = max(0, int(expiry_unix or 0))
        self.license_badge_text = "有效"
        if self.license_expiry_unix > 0:
            seconds_left = int(self.license_expiry_unix - time.time())
            if not expires_local:
                expires_local = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.license_expiry_unix))
            remaining = self._format_seconds_left(seconds_left)
            self.license_expiry_compact_text = self._compact_license_datetime(expires_local)
            self.license_remaining_text = remaining
            self.license_expiry_text = f"授权到期: {expires_local}（{remaining}）"
            self.license_seconds_left = seconds_left
        else:
            self.license_expiry_text = "授权状态: 已验证（无到期信息）"
            self.license_expiry_compact_text = "无到期信息"
            self.license_remaining_text = "状态已验证"
            self.license_seconds_left = -1
        self.license_status_detail = message or "授权验证成功"

    def _refresh_cached_license_countdown(self):
        if self.license_expiry_unix <= 0:
            return False
        self._set_license_success(self.license_expiry_unix, message=self.license_status_detail)
        return True

    def _extract_auth_status(self, line: str):
        match = self._auth_expiry_pattern.search(line)
        if not match:
            return
        expires_local = (match.group(1) or "").strip()
        if expires_local.lower() == "unknown":
            self._set_license_success(0, message="核心授权成功，但未返回到期时间")
            self._emit_state()
            return
        try:
            seconds_left = int(match.group(2)) if match.group(2) is not None else -1
        except Exception:
            seconds_left = -1
        expiry_unix = int(time.time()) + seconds_left if seconds_left >= 0 else 0
        self._set_license_success(expiry_unix, expires_local, "核心授权成功")
        self._emit_state()

    def _apply_license_status(self, status):
        if not isinstance(status, dict):
            return
        success = bool(status.get("success", False))
        message = str(status.get("message", "")).strip()
        try:
            seconds_left = int(float(status.get("seconds_left", -1)))
        except Exception:
            seconds_left = -1
        expires_local = str(status.get("expires_local", "")).strip()
        try:
            expires_unix = int(float(status.get("expires_unix", 0)))
        except Exception:
            expires_unix = 0
        if success:
            if expires_unix <= 0 and seconds_left >= 0:
                expires_unix = int(time.time()) + seconds_left
            self._set_license_success(expires_unix, expires_local, message)
        else:
            self.license_expiry_text = "授权状态: 未验证"
            self.license_badge_text = "未验证"
            self.license_expiry_compact_text = "--"
            self.license_remaining_text = "点击刷新"
            self.license_seconds_left = -1
            self.license_expiry_unix = 0
            self.license_status_detail = message or "未读取到已记住的授权"
        self._emit_state()

    def refreshLicenseStatus(self):
        if self._is_pipeline_running():
            if not self._refresh_cached_license_countdown():
                self.license_expiry_text = "授权状态: 核心运行中"
                self.license_badge_text = "运行中"
                self.license_expiry_compact_text = "--"
                self.license_remaining_text = "等待核心日志"
                self.license_status_detail = "推理核心运行中，等待核心授权日志更新到期时间"
                self._emit_state()
            return

        with self._license_status_lock:
            if self._license_status_in_flight:
                return
            self._license_status_in_flight = True

        def worker():
            status = {"success": False, "message": "授权状态读取失败"}
            try:
                exe_path = self.runtime_exe_path
                if not os.path.exists(exe_path):
                    status = {"success": False, "message": f"找不到推理核心: {exe_path}"}
                else:
                    completed = subprocess.run(
                        [exe_path, "--license-status"],
                        cwd=self.runtime_root,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        timeout=18,
                        creationflags=self._hidden_process_flags(),
                    )
                    output = self._decode_process_output(completed.stdout).strip()
                    json_line = next((line for line in output.splitlines() if line.strip().startswith("{")), "")
                    if not json_line:
                        status = {"success": False, "message": "核心未返回授权状态"}
                    else:
                        status = json.loads(json_line)
            except subprocess.TimeoutExpired:
                status = {"success": False, "message": "授权状态读取超时"}
            except Exception as exc:
                status = {"success": False, "message": f"授权状态读取失败: {exc}"}
            finally:
                self._apply_license_status(status)
                with self._license_status_lock:
                    self._license_status_in_flight = False

        threading.Thread(target=worker, daemon=True).start()

    def _read_update_current_version(self) -> str:
        version_file = os.path.join(self.project_root, ".updates", "current_version.txt")
        try:
            with open(version_file, "r", encoding="utf-8") as handle:
                value = handle.read().strip()
                return value or "未记录"
        except Exception:
            return "未记录"

    def _set_update_running(self, running: bool, text: str = ""):
        self.update_running = bool(running)
        if text:
            self.update_status_text = text
        self._emit_state()

    def _apply_update_status(self, status):
        if not isinstance(status, dict):
            return
        self.update_running = bool(status.get("running", False))
        self.update_status_text = str(status.get("message", self.update_status_text)).strip() or self.update_status_text
        self.update_latest_version = str(status.get("latest_version", self.update_latest_version)).strip() or self.update_latest_version
        if "current_version" in status:
            self.update_current_version = str(status.get("current_version") or "未记录")
        if "available" in status:
            self.update_available = bool(status.get("available"))
        if "manifest" in status:
            self._update_pending_manifest = status.get("manifest")
        level = "INFO"
        if status.get("success") is True:
            level = "SUCCESS"
        elif status.get("success") is False and status.get("error"):
            level = "WARN"
        self._append_log(f"[{level}] {self.update_status_text}")
        self._emit_state()

    def _validate_runtime_after_update(self):
        if not os.path.exists(self.runtime_exe_path):
            raise UpdateError(f"runtime exe missing after update: {self.runtime_exe_path}")
        subprocess.check_output(
            [self.runtime_exe_path, "--capabilities"],
            cwd=self.runtime_root,
            stderr=subprocess.STDOUT,
            timeout=18,
            creationflags=self._hidden_process_flags(),
        )

    def checkForUpdates(self):
        with self._update_lock:
            if self._update_in_flight:
                return
            self._update_in_flight = True
        self._set_update_running(True, "正在检查更新...")

        def worker():
            try:
                manifest = load_manifest(self.update_manifest_url)
                current = self._read_update_current_version()
                available = current != manifest.version
                message = f"发现新版本 {manifest.version}" if available else f"当前已是最新版本 {manifest.version}"
                self._apply_update_status(
                    {
                        "success": True,
                        "running": False,
                        "message": message,
                        "latest_version": manifest.version,
                        "current_version": current,
                        "available": available,
                        "manifest": manifest,
                    }
                )
            except Exception as exc:
                self._apply_update_status(
                    {
                        "success": False,
                        "error": True,
                        "running": False,
                        "message": f"检查更新失败: {exc}",
                        "available": False,
                    }
                )
            finally:
                with self._update_lock:
                    self._update_in_flight = False

        threading.Thread(target=worker, daemon=True).start()

    def applyAvailableUpdate(self):
        if self._is_pipeline_running():
            self._apply_update_status(
                {
                    "success": False,
                    "error": True,
                    "running": False,
                    "message": "推理核心运行中，请先停止后再更新",
                    "available": self.update_available,
                }
            )
            return
        with self._update_lock:
            if self._update_in_flight:
                return
            self._update_in_flight = True
        self._set_update_running(True, "正在下载并应用更新...")

        def worker():
            try:
                manifest = self._update_pending_manifest or load_manifest(self.update_manifest_url)
                project_path = Path(self.project_root)
                stage_root = stage_update(project_path, self.update_manifest_url, manifest)
                backup_root = apply_staged_update(
                    project_path,
                    manifest,
                    stage_root,
                    validate=self._validate_runtime_after_update,
                )
                current = self._read_update_current_version()
                self._apply_update_status(
                    {
                        "success": True,
                        "running": False,
                        "message": f"更新完成: {manifest.version}，备份已保存",
                        "latest_version": manifest.version,
                        "current_version": current,
                        "available": False,
                        "backup": str(backup_root),
                    }
                )
            except Exception as exc:
                self._apply_update_status(
                    {
                        "success": False,
                        "error": True,
                        "running": False,
                        "message": f"更新失败，已尝试回滚: {exc}",
                        "available": self.update_available,
                    }
                )
            finally:
                with self._update_lock:
                    self._update_in_flight = False

        threading.Thread(target=worker, daemon=True).start()

    def resetKeys(self, target: str):
        if target == "aim":
            self.aim_keys = "2"
            self.aim_keys_display = "右键 (VK:2)"
            self._append_log(">> 已重置自瞄按键为: 右键")
        elif target == "trigger":
            self.trigger_keys = "1"
            self.trigger_keys_display = "左键 (VK:1)"
            self._append_log(">> 已重置扳机按键为: 左键")
        else:
            self._append_log(f"[ERROR] 未知重置目标: {target}")
            return
        self._emit_state()

    def recordKeys(self, target: str, payload):
        try:
            data = dict(payload or {})
            raw_keys = data.get("keys", data.get("vk", ""))
            raw_text = ",".join(str(item) for item in raw_keys) if isinstance(raw_keys, list) else str(raw_keys)
            keys = self._sanitize_vk_csv(raw_text, "")
            if not keys:
                raise ValueError
            vk = int(keys.split(",", 1)[0])
        except (TypeError, ValueError):
            raise MobileControlError(422, "VALIDATION_ERROR", "按键录入缺少有效 VK")
        if vk < 1 or vk > 255:
            raise MobileControlError(422, "VALIDATION_ERROR", "VK 必须在 1..255 范围内")
        if target == "aim":
            self.aim_keys = keys
            self.aim_keys_display = self._format_vk_display(self.aim_keys, "2")
            self._append_log(f">> 已保存[自瞄]按键配置: {self.aim_keys_display}")
        elif target == "trigger":
            self.trigger_keys = keys
            self.trigger_keys_display = self._format_vk_display(self.trigger_keys, "1")
            self._append_log(f">> 已保存[扳机]按键配置: {self.trigger_keys_display}")
        else:
            raise MobileControlError(422, "VALIDATION_ERROR", "未知按键录入目标")
        self._emit_state()

    def _web_panel_lan_host(self):
        candidates = []
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(0.2)
                sock.connect(("8.8.8.8", 80))
                candidates.append(sock.getsockname()[0])
        except Exception:
            pass
        try:
            for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ip = item[4][0]
                if ip not in candidates:
                    candidates.append(ip)
        except Exception:
            pass
        usable = [ip for ip in candidates if self._is_usable_web_panel_lan_ip(ip)]
        private = [ip for ip in usable if ipaddress.ip_address(ip).is_private]
        if private:
            return private[0]
        if usable:
            return usable[0]
        return "127.0.0.1"

    @staticmethod
    def _is_usable_web_panel_lan_ip(value: str) -> bool:
        try:
            ip = ipaddress.ip_address(str(value or "").strip())
        except ValueError:
            return False
        if ip.version != 4:
            return False
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            return False
        if ip in ipaddress.ip_network("198.18.0.0/15"):
            return False
        return True

    def _is_local_tcp_port_open(self, port: int) -> bool:
        try:
            port = int(port)
        except (TypeError, ValueError):
            return False
        if port <= 0:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.15):
                return True
        except OSError:
            return False

    def _web_panel_url_for(self, host: str, port: int, pin: str) -> str:
        return f"http://{host}:{int(port)}/?pin={pin}"

    def _read_web_panel_session(self) -> dict:
        try:
            with open(self.web_panel_session_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        try:
            port = int(data.get("port", 0))
        except (TypeError, ValueError):
            return {}
        pin = str(data.get("pin", "")).strip()
        if port <= 0 or not pin:
            return {}
        return {"port": port, "pin": pin}

    def _write_web_panel_session(self, server: MobileControlServer) -> None:
        data = {"port": int(server.port), "pin": str(server.pin)}
        directory = os.path.dirname(self.web_panel_session_path)
        os.makedirs(directory, exist_ok=True)
        temp_path = self.web_panel_session_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, self.web_panel_session_path)

    def _clear_web_panel_session(self, port: int | None = None, pin: str | None = None) -> None:
        session = self._read_web_panel_session()
        if port is not None and session.get("port") != int(port):
            return
        if pin is not None and session.get("pin") != str(pin):
            return
        try:
            os.remove(self.web_panel_session_path)
        except FileNotFoundError:
            pass
        except Exception:
            pass

    def _probe_web_panel_session(self, port: int, pin: str) -> bool:
        url = f"http://127.0.0.1:{int(port)}/api/state"
        request = urllib.request.Request(url, headers={"X-Neko-Pin": str(pin)})
        try:
            with urllib.request.urlopen(request, timeout=0.5) as response:
                body = json.loads(response.read().decode("utf-8"))
        except Exception:
            return False
        return bool(body.get("ok") and isinstance(body.get("data"), dict) and "config" in body["data"])

    def _probe_web_panel_server(self, server: MobileControlServer) -> bool:
        return self._probe_web_panel_session(server.port, server.pin)

    def _new_web_panel_server(self, port: int) -> MobileControlServer:
        return MobileControlServer(
            state_provider=self._web_panel_state_provider,
            update_handler=self.update_handler,
            action_handler=self.action_handler,
            host="0.0.0.0",
            port=port,
        )

    def _start_web_panel_server_fixed_port(self) -> MobileControlServer:
        requested_port = int(self.web_panel_port)
        if self._is_local_tcp_port_open(requested_port):
            session = self._read_web_panel_session()
            if session.get("port") == requested_port and self._probe_web_panel_session(requested_port, session.get("pin", "")):
                return None
            raise OSError(f"固定端口 {requested_port} 已被占用，请先关闭旧 Web 面板进程。")

        server = self._new_web_panel_server(requested_port)
        try:
            server.start()
        except OSError as exc:
            raise OSError(f"固定端口 {requested_port} 不可用: {exc}") from exc

        if self._probe_web_panel_server(server):
            self._write_web_panel_session(server)
            return server

        failed_port = server.port
        try:
            server.stop()
        except Exception:
            pass
        raise OSError(f"Web 面板固定端口自检失败: 127.0.0.1:{failed_port}")

    def start_web_panel(self, open_browser: bool = False):
        if self.web_panel_server is not None:
            self._append_log("[INFO] Web 面板已经在运行。")
            self._emit_state()
            if open_browser:
                self.open_web_panel()
            return self.web_panel_local_url or self.web_panel_url
        try:
            server = self._start_web_panel_server_fixed_port()
        except Exception as exc:
            self._append_log(f"[ERROR] Web 面板启动失败: {exc}")
            self._emit_state()
            return ""
        host = self._web_panel_lan_host()
        if server is None:
            session = self._read_web_panel_session()
            port = int(session.get("port", self.web_panel_port))
            pin = str(session.get("pin", "")).strip()
            self.web_panel_pin = pin
            self.web_panel_url = self._web_panel_url_for(host, port, pin)
            self.web_panel_local_url = self._web_panel_url_for("127.0.0.1", port, pin)
            self.web_panel_status = f"Web 面板: 已复用 {host}:{port}"
            self._append_log(f"[INFO] Web 面板端口 {port} 已有会话，复用同一个 PIN。")
            self._emit_state()
            if open_browser:
                self.open_web_panel()
            self._shutdown_requested = True
            self._stop_event.set()
            return self.web_panel_local_url or self.web_panel_url
        self.web_panel_server = server
        self.web_panel_pin = server.pin
        self.web_panel_url = self._web_panel_url_for(host, server.port, server.pin)
        self.web_panel_local_url = self._web_panel_url_for("127.0.0.1", server.port, server.pin)
        self.web_panel_status = f"Web 面板: 已启动 {host}:{server.port}"
        self._append_log(f"[INFO] Web 面板已启动: {self.web_panel_url}")
        self._append_log("[HINT] 手机与电脑需在同一路由器，或手机连接电脑 Windows 移动热点。")
        self._append_log("[HINT] 如果浏览器打不开，请允许 Windows 防火墙的专用网络访问。")
        self._emit_state()
        if open_browser:
            self.open_web_panel()
        return self.web_panel_local_url or self.web_panel_url

    def stop_web_panel(self):
        server = self.web_panel_server
        self.web_panel_server = None
        if server is not None:
            server_port = int(server.port)
            server_pin = str(server.pin)
            try:
                server.stop()
            except Exception as exc:
                self._append_log(f"[WARN] Web 面板停止异常: {exc}")
            self._clear_web_panel_session(server_port, server_pin)
        self.web_panel_pin = ""
        self.web_panel_url = ""
        self.web_panel_local_url = ""
        self.web_panel_status = "Web 面板: 未启动"
        self._append_log("[INFO] Web 面板已停止。")
        self._emit_state()

    def open_web_panel(self):
        if self.web_panel_server is None:
            self.start_web_panel(open_browser=False)
        target = self.web_panel_local_url or self.web_panel_url
        if not target:
            self._append_log("[WARN] Web 面板尚未启动，无法打开。")
            return
        try:
            webbrowser.open(target)
            self._append_log("[INFO] 已在本机浏览器打开 Web 面板。")
        except Exception as exc:
            self._append_log(f"[WARN] 打开 Web 面板失败: {exc}")

    def clearBackgroundImage(self):
        self.background_image_path = ""
        self.background_video_path = ""
        self.background_video_url = ""
        self.active_background_mode = self._resolve_background_mode()
        self._append_log("[INFO] 已恢复默认渐变背景。")
        self._emit_state()

    def openNetron(self):
        model_path = self.model_path.strip()
        if not model_path or not os.path.exists(model_path):
            self._append_log("[ERROR] 请先选择有效模型后再查看结构。")
            return
        try:
            subprocess.Popen(["cmd", "/c", "start", "", "netron", model_path], shell=False)
            self._append_log(f"[INFO] 已尝试用 Netron 打开: {os.path.basename(model_path)}")
        except Exception:
            try:
                subprocess.Popen(["cmd", "/c", "start", "", sys.executable, "-m", "netron", model_path], shell=False)
                self._append_log(f"[INFO] 已通过 python -m netron 打开: {os.path.basename(model_path)}")
            except Exception as exc:
                self._append_log(f"[ERROR] 启动 Netron 失败: {exc}")

    def saveSettings(self, data):
        self._update_from_map(data)
        try:
            self._persist_settings()
            self._append_log(">> 当前配置已保存。")
        except Exception as exc:
            self._append_log(f"[ERROR] 保存配置失败: {exc}")

    def startConversion(self, data):
        self._update_from_map(data)
        model_path = self.model_path
        if not model_path or not os.path.exists(model_path):
            self._append_log("[ERROR] 请先选择有效的 .onnx 文件。")
            return
        if not model_path.lower().endswith(".onnx"):
            self._append_log("[ERROR] 当前独立编译包仅支持 .onnx -> .engine。")
            return
        if self._is_conversion_running():
            self._append_log("[WARN] 当前已有编译任务在运行。")
            return
        builder_path = os.path.join(self.runtime_root, "build_texture_preprocess_engine.exe")
        plugin_path = os.path.join(self.runtime_root, "TexturePreprocessPlugin.dll")
        if not os.path.exists(builder_path):
            self._append_log("[ERROR] 找不到 build_texture_preprocess_engine.exe。")
            self._append_log(f"[HINT] 请确认运行目录存在: {builder_path}")
            return
        if not os.path.exists(plugin_path):
            self._append_log("[ERROR] 找不到 TexturePreprocessPlugin.dll，无法编译 TexPre FP16 引擎。")
            self._append_log(f"[HINT] 请确认运行目录存在: {plugin_path}")
            return
        builder_working_dir = ""
        for candidate_dir in (self.builder_root, self.runtime_root):
            if os.path.exists(os.path.join(candidate_dir, "nvonnxparser_10.dll")):
                builder_working_dir = candidate_dir
                break
        if not builder_working_dir:
            self._append_log("[ERROR] 缺少 TensorRT ONNX 编译依赖 nvonnxparser_10.dll。")
            self._append_log("[HINT] 请确认发布包包含 engine_builder 目录，或重新使用 -IncludeBuilder 生成发布包。")
            return
        self.saveSettings({})
        texture_input_size = self._texture_builder_input_size()
        self._pending_engine_output_path = self._texture_preprocess_engine_path(model_path, texture_input_size)
        os.makedirs(self.models_root, exist_ok=True)
        args = [builder_path, model_path, self._pending_engine_output_path, str(texture_input_size), str(texture_input_size), "1"]
        self._append_log(f">> 开始编译 TexPre FP16 模型: {os.path.basename(model_path)}")
        self._append_log(f">> 输出引擎: {self._pending_engine_output_path}")
        self._append_log(f">> Plugin 输入尺寸: {texture_input_size}x{texture_input_size}")
        self._append_log(">> 当前使用 runtime\\build_texture_preprocess_engine.exe 生成 TexturePreprocessPlugin FP16 Engine。")
        self._append_log(f">> 编译依赖目录: {builder_working_dir}")
        try:
            self.conversion_process = subprocess.Popen(
                args,
                cwd=builder_working_dir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=self._hidden_process_flags(),
            )
        except Exception as exc:
            self.conversion_process = None
            self._append_log(f"[ERROR] 编译进程启动失败: {exc}")
            return
        threading.Thread(target=self._pump_conversion_output, args=(self.conversion_process,), daemon=True).start()

    def _pump_conversion_output(self, process):
        try:
            if process.stdout:
                for raw_line in iter(process.stdout.readline, b""):
                    decoded = self._decode_process_output(raw_line)
                    for line in decoded.splitlines():
                        if line.strip():
                            path_match = self._engine_output_pattern.search(line)
                            if path_match:
                                self._pending_engine_output_path = self._normalize_path(path_match.group(1).strip())
                            self._append_log(line)
        finally:
            exit_code = process.wait()
            self._conversion_finished(int(getattr(process, "pid", -1)), int(exit_code))

    def _conversion_finished(self, process_id, exit_code):
        if self.conversion_process and getattr(self.conversion_process, "pid", -1) != process_id:
            return
        self.conversion_process = None
        if exit_code == 0:
            self._append_log("[SUCCESS] 编译任务完成，.engine 已生成。")
            if self._pending_engine_output_path and os.path.exists(self._pending_engine_output_path):
                self.engine_path = self._pending_engine_output_path
                self._update_status_labels()
                self._append_log(f"[INFO] 已自动回填引擎路径: {self.engine_path}")
                self.saveSettings({})
        else:
            self._append_log(f"[ERROR] 编译失败，退出码: {exit_code}")
        self._pending_engine_output_path = ""
        self._emit_state()

    def _write_pipeline_config(self) -> bool:
        engine_path = self.engine_path
        if not engine_path or not os.path.exists(engine_path):
            self._append_log("[ERROR] 请先选择有效的 .engine 文件。")
            return False
        selected_classes = self._selected_classes_list()
        if not selected_classes:
            self._append_log("[ERROR] 请至少选择一个锁定类别。")
            return False
        aim_keys = self._sanitize_vk_csv(self.aim_keys, "2")
        trigger_keys = self._sanitize_vk_csv(self.trigger_keys, "1")
        pipeline_mode = self._pipeline_mode_code()
        motion_mode = self._motion_mode_code()
        show_preview = 1 if pipeline_mode == "debug" else 0
        trigger_mode = self._trigger_mode_code()
        texture_preprocess_enabled = self._is_texture_preprocess_engine(engine_path)
        texture_plugin_input = self._texture_plugin_input_size(engine_path)
        os.makedirs(os.path.dirname(self.runtime_config_path), exist_ok=True)
        try:
            with open(self.runtime_config_path, "w", encoding="utf-8") as f:
                f.write(f"engine_path={self._to_runtime_engine_config_path(engine_path)}\n")
                f.write(f"roi_w={self.roi}\n")
                f.write(f"roi_h={self.roi}\n")
                f.write(f"conf={self.conf:.3f}\n")
                f.write(f"nms={self.nms:.3f}\n")
                f.write(f"pid_p={self.pid_p:.3f}\n")
                f.write(f"pid_i={self.pid_i:.3f}\n")
                f.write(f"pid_d={self.pid_d:.3f}\n")
                f.write(f"stick_en={1 if self.stick_enable else 0}\n")
                f.write(f"stick_int={self.stick_int:.3f}\n")
                f.write(f"stick_rad={self.stick_rad:.3f}\n")
                f.write(f"y_offset={self.y_offset:.3f}\n")
                f.write(f"fps_limit={self.fps_limit}\n")
                f.write(f"kalman_en={1 if self.kalman_en else 0}\n")
                f.write(f"kalman_pred={self.kalman_pred:.2f}\n")
                f.write(f"recoil_en={1 if self.recoil_en else 0}\n")
                f.write(f"trigger_recoil_en={1 if self.trigger_recoil_en else 0}\n")
                f.write(f"recoil_strength={self.recoil_strength:.3f}\n")
                f.write(f"recoil_delay={self.recoil_delay:.1f}\n")
                f.write(f"trigger_mode={trigger_mode}\n")
                f.write(f"trigger_delay={self.trigger_delay:.1f}\n")
                f.write("trigger_click_hold_ms=45.0\n")
                f.write("trigger_click_gap_ms=10.0\n")
                f.write(f"trigger_hitbox_enter_scale={self.trigger_hitbox_enter_scale:.2f}\n")
                f.write(f"trigger_hitbox_exit_scale={self.trigger_hitbox_exit_scale:.2f}\n")
                f.write(f"trigger_hold_grace_ms={self.trigger_hold_grace_ms:.1f}\n")
                f.write(f"use_lghub={1 if self.lghub_enabled else 0}\n")
                f.write(f"esp32_enabled={1 if self.esp32_enabled else 0}\n")
                f.write(f"esp32_port={self.esp32_port}\n")
                f.write(f"esp32_baud={self.esp32_baud}\n")
                f.write(f"pipeline_mode={pipeline_mode}\n")
                f.write(f"motion_mode={motion_mode}\n")
                f.write(f"neural_curvature={self.neural_curvature:.3f}\n")
                f.write(f"neural_tremor={self.neural_tremor:.3f}\n")
                f.write(f"show_preview={show_preview}\n")
                f.write("async_double_buffer=0\n")
                f.write("roi_resource_double_buffer=1\n")
                if texture_preprocess_enabled:
                    f.write("texture_preprocess_plugin=1\n")
                    f.write(f"plugin_input_w={texture_plugin_input}\n")
                    f.write(f"plugin_input_h={texture_plugin_input}\n")
                f.write(f"aim_keys={aim_keys}\n")
                f.write(f"trigger_keys={trigger_keys}\n")
                f.write(f"target_classes={','.join(selected_classes)}\n")
        except Exception as exc:
            self._append_log(f"[ERROR] 写入 config.txt 失败: {exc}")
            return False
        return True

    def _verify_runtime_executable(self, exe_path: str) -> bool:
        expected_name = "TRT_ZeroCopy_Pipeline.exe"
        if os.path.basename(exe_path).lower() != expected_name.lower():
            self._append_log(f"[ERROR] 推理核心路径异常: {exe_path}")
            return False
        required_capabilities = {
            "capture_path": "ROI_COPY_ONLY",
            "direct_interop": "disabled",
            "config_safe_parse": "1",
            "trt_ready_check": "1",
            "cuda_error_check": "1",
            "preprocess_1to1_fast_path": "1",
            "target_class_postprocess": "1",
            "roi_resource_double_buffer": "1",
            "async_result_double_buffer": "0",
            "low_latency_current_frame_result": "1",
            "pinned_best_target_host": "1",
            "trigger_hysteresis": "1",
            "trigger_pulse_click": "1",
            "trigger_recoil": "1",
            "license_status": "1",
        }
        if self._is_texture_preprocess_engine(self.engine_path):
            required_capabilities.update(
                {
                    "texture_preprocess_plugin": "1",
                    "texture_preprocess_plugin_fp16": "1",
                }
            )
        try:
            capability_output = subprocess.check_output(
                [exe_path, "--capabilities"],
                cwd=os.path.dirname(exe_path),
                stderr=subprocess.STDOUT,
                timeout=2.0,
                creationflags=self._hidden_process_flags(),
            )
            capability_text = self._decode_process_output(capability_output)
            missing = [
                f"{key}={value}"
                for key, value in required_capabilities.items()
                if f"{key}={value}" not in capability_text
            ]
            if missing:
                self._append_log("[ERROR] 推理核心能力声明不完整，已阻止启动。")
                self._append_log(f"[ERROR] 缺少能力: {', '.join(missing)}")
                self._append_log("[HINT] 请重新部署 E:\\4.29\\429\\trt_cpp_pipeline\\deploy_runtime.bat")
                return False
            self._append_log(f"[INFO] 推理核心校验通过: {exe_path}")
            capability_label = "ROI_COPY_ONLY / safe config / TRT ready / CUDA checks / low-latency current-frame result"
            if self._is_texture_preprocess_engine(self.engine_path):
                capability_label += " / TexturePreprocessPlugin FP16"
            self._append_log(f"[INFO] Capabilities: {capability_label}")
            return True
        except Exception as exc:
            self._append_log(f"[ERROR] 推理核心未返回结构化能力信息，已阻止启动: {exc}")
            self._append_log("[HINT] 请重新部署 E:\\4.29\\429\\trt_cpp_pipeline\\deploy_runtime.bat")
            return False

    def startPipeline(self, data):
        self._update_from_map(data)
        if self._is_pipeline_running():
            self._append_log("[WARN] 当前已有推理核心在运行。")
            return
        if self.lghub_enabled:
            is_elevated = self._is_process_elevated()
            ghub_mouse_present = self._has_present_ghub_virtual_mouse()
            if is_elevated:
                self._append_log("[INFO] LGHUB 启动预检: 当前面板具备管理员权限。")
            elif ghub_mouse_present:
                self._append_log(
                    "[WARN] LGHUB 启动预检: 当前面板不是管理员。虽然 PID_C231 已存在，"
                    "但若虚拟鼠标掉失，自动修复可能失败。"
                )
            else:
                self._append_log(
                    "[ERROR] LGHUB 启动预检失败: 未检测到 Logitech G HUB Virtual Mouse "
                    "(PID_C231)，且当前面板不是管理员。请以管理员身份运行面板后重试。"
                )
                return
        if not self._write_pipeline_config():
            return
        engine_path = self.engine_path
        aim_keys = self._sanitize_vk_csv(self.aim_keys, "2")
        trigger_keys = self._sanitize_vk_csv(self.trigger_keys, "1")
        pipeline_mode = self._pipeline_mode_code()
        exe_path = self.runtime_exe_path
        if not os.path.exists(exe_path):
            self._append_log(f"[ERROR] 找不到可执行文件: {exe_path}")
            return
        if not self._verify_runtime_executable(exe_path):
            return
        self.saveSettings({})
        self.status_mode_text = f"模式: {self.pipeline_mode}"
        self.status_engine_text = f"引擎: {os.path.basename(engine_path)}"
        self._reset_runtime_metrics()
        self._emit_state()
        self._append_log(
            f">> 已生成配置: Mode={pipeline_mode.upper()} ROI={self.roi} "
            f"Conf={self.conf:.3f} CapturePath=ROI_COPY_ONLY "
            f"AimKeys=[{aim_keys}] TriggerKeys=[{trigger_keys}]"
        )
        if self._is_texture_preprocess_engine(engine_path):
            self._append_log(
                f"[INFO] TexturePreprocessPlugin FP16 测试链路已启用: "
                f"PluginInput={self._texture_plugin_input_size(engine_path)}"
            )
        self._pipeline_stop_requested = False
        try:
            self.pipeline_process = subprocess.Popen(
                [exe_path],
                cwd=os.path.dirname(exe_path),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=self._hidden_process_flags(),
            )
        except Exception as exc:
            self.pipeline_process = None
            self.status_mode_text = "模式: 未启动"
            self._reset_runtime_metrics()
            self._emit_state()
            self._append_log(f"[ERROR] 推理核心启动失败: {exc}")
            return
        threading.Thread(target=self._pump_pipeline_output, args=(self.pipeline_process,), daemon=True).start()
        self._append_log(f"[INFO] 推理核心已隐藏启动，日志已接入 Web 面板。PID={self.pipeline_process.pid}")

    def _pipeline_finished(self, process_id, exit_code):
        if self.pipeline_process and getattr(self.pipeline_process, "pid", -1) != process_id:
            return
        stopped_by_panel = self._pipeline_stop_requested
        self.pipeline_process = None
        self._pipeline_stop_requested = False
        if stopped_by_panel:
            self._append_log("[INFO] 推理核心已停止。")
        elif exit_code == 0:
            self._append_log("[INFO] 推理核心已退出。")
        else:
            self._append_log(f"[WARN] 推理核心退出，退出码: {exit_code}")
        self.status_mode_text = "模式: 未启动"
        self._reset_runtime_metrics()
        self._emit_state()

    def stopPipeline(self):
        if self._is_pipeline_running():
            self._pipeline_stop_requested = True
            kill = getattr(self.pipeline_process, "kill", None)
            if callable(kill):
                kill()
                try:
                    self.pipeline_process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
            self._append_log("[INFO] 已请求停止推理核心。")
            self.status_mode_text = "模式: 未启动"
            self._reset_runtime_metrics()
            self._emit_state()

    def _get_background_status_text(self):
        if self.active_background_mode == "image" and self.background_image_path:
            return f"背景: 图片 {os.path.basename(self.background_image_path)}"
        if self.active_background_mode == "video" and self.background_video_path:
            return f"背景: 本地视频 {os.path.basename(self.background_video_path)}"
        if self.active_background_mode == "web" and self.background_video_url:
            return "背景: 在线视频"
        return "背景: 默认渐变"

    def shutdown(self):
        self._stop_event.set()
        self.stop_web_panel()
        try:
            self._persist_settings()
        except Exception:
            pass
        if self._is_conversion_running():
            self.conversion_process.kill()
            try:
                self.conversion_process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
        if self._is_pipeline_running():
            self._pipeline_stop_requested = True
            kill = getattr(self.pipeline_process, "kill", None)
            if callable(kill):
                kill()
                try:
                    self.pipeline_process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass
