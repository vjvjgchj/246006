import ast
import ctypes
import json
import locale
import math
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import warnings
from pathlib import Path
from urllib.parse import unquote, urlparse

try:
    import winreg
except ImportError:
    winreg = None

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Property,
    QProcess,
    QUrl,
    QTimer,
    Qt,
    Signal,
    Slot,
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


class ClassSelectionModel(QAbstractListModel):
    ClassIdRole = Qt.UserRole + 1
    ClassNameRole = Qt.UserRole + 2
    CheckedRole = Qt.UserRole + 3
    DisplayRole = Qt.UserRole + 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        item = self._items[index.row()]
        if role == self.ClassIdRole:
            return item["classId"]
        if role == self.ClassNameRole:
            return item["className"]
        if role == self.CheckedRole:
            return item["checked"]
        if role in (Qt.DisplayRole, self.DisplayRole):
            return item["display"]
        return None

    def roleNames(self):
        return {
            self.ClassIdRole: b"classId",
            self.ClassNameRole: b"className",
            self.CheckedRole: b"checked",
            self.DisplayRole: b"display",
        }

    def set_items(self, options, selected_ids):
        selected_set = set(str(x) for x in (selected_ids or []))
        items = []
        if not options:
            options = ["0 - 默认类别"]
        for index, option in enumerate(options):
            class_id, _, class_name = option.partition(" - ")
            class_id = class_id.strip() or str(index)
            class_name = class_name.strip() or f"class_{class_id}"
            items.append(
                {
                    "classId": class_id,
                    "className": class_name,
                    "display": f"{class_id} - {class_name}",
                    "checked": class_id in selected_set if selected_set else index == 0,
                }
            )
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    def selected_ids(self):
        return [item["classId"] for item in self._items if item["checked"]]

    def set_checked_from_csv(self, csv_text: str):
        selected = {part.strip() for part in str(csv_text).split(",") if part.strip()}
        if not self._items:
            return
        for row, item in enumerate(self._items):
            checked = item["classId"] in selected
            if item["checked"] == checked:
                continue
            item["checked"] = checked
            model_index = self.index(row, 0)
            self.dataChanged.emit(model_index, model_index, [self.CheckedRole])

    @Slot(int, bool)
    def setChecked(self, row: int, checked: bool):
        if row < 0 or row >= len(self._items):
            return
        item = self._items[row]
        if item["checked"] == checked:
            return
        item["checked"] = checked
        model_index = self.index(row, 0)
        self.dataChanged.emit(model_index, model_index, [self.CheckedRole])


class LogListModel(QAbstractListModel):
    TextRole = Qt.UserRole + 1
    LevelRole = Qt.UserRole + 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        item = self._items[index.row()]
        if role in (Qt.DisplayRole, self.TextRole):
            return item["text"]
        if role == self.LevelRole:
            return item["level"]
        return None

    def roleNames(self):
        return {
            self.TextRole: b"text",
            self.LevelRole: b"level",
        }

    def append_line(self, text: str, level: str):
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append({"text": text, "level": level})
        self.endInsertRows()
        if len(self._items) > 400:
            extra = len(self._items) - 400
            self.beginRemoveRows(QModelIndex(), 0, extra - 1)
            del self._items[:extra]
            self.endRemoveRows()


class QmlBridge(QObject):
    stateChanged = Signal()
    logTextChanged = Signal()
    conversionRunningChanged = Signal()
    pipelineRunningChanged = Signal()
    pipelineOutputLine = Signal(str)
    pipelineFinishedAsync = Signal(int, int)
    modelParsed = Signal(list, str)
    keyProgress = Signal(str, str)
    keyFinished = Signal(str, str, str, str)
    systemMetricsSampled = Signal(object)
    licenseStatusSampled = Signal(object)
    updateStatusSampled = Signal(object)

    SAVE_FILE = "gui_settings.json"
    DEFAULT_UPDATE_MANIFEST_URL = "https://raw.githubusercontent.com/vjvjgchj/246006/main/updates/stable.json"
    KALMAN_PRED_DEFAULT = 1.0
    KALMAN_PRED_MIN = 0.0
    KALMAN_PRED_MAX = 4.0
    THEME_PRESETS = {
        "极夜青辉": {
            "accent": "#5EF2FF",
            "accent2": "#00FFC8",
            "surface": "#0B1730",
            "surface_alt": "#071120",
            "text": "#F1FBFF",
            "muted": "#9DCBDE",
            "hero_start": "#10254E",
            "hero_end": "#0A6D86",
            "sidebar": "#0B1428",
        },
        "紫电星云": {
            "accent": "#B67BFF",
            "accent2": "#36E6FF",
            "surface": "#16112B",
            "surface_alt": "#090714",
            "text": "#F7F3FF",
            "muted": "#B8B2D8",
            "hero_start": "#2B1451",
            "hero_end": "#163A73",
            "sidebar": "#120D26",
        },
        "熔岩赤曜": {
            "accent": "#FF8A5B",
            "accent2": "#FFD65C",
            "surface": "#22110F",
            "surface_alt": "#120807",
            "text": "#FFF5EE",
            "muted": "#D8B9A7",
            "hero_start": "#4B1D18",
            "hero_end": "#85521A",
            "sidebar": "#190E0B",
        },
        "自定义主题": {
            "accent": "#5EF2FF",
            "accent2": "#00FFC8",
            "surface": "#0B1730",
            "surface_alt": "#071120",
            "text": "#F1FBFF",
            "muted": "#9DCBDE",
            "hero_start": "#10254E",
            "hero_end": "#0A6D86",
            "sidebar": "#0B1428",
        },
    }

    def __init__(self, project_root: str, parent=None):
        super().__init__(parent)
        self.project_root = project_root
        self.builder_root = os.path.join(self.project_root, "engine_builder")
        self.models_root = os.path.join(self.project_root, "models")
        self.runtime_root = os.path.join(self.project_root, "runtime")
        self.runtime_config_path = os.path.join(self.runtime_root, "config.txt")
        self.runtime_exe_path = os.path.join(self.runtime_root, "TRT_ZeroCopy_Pipeline.exe")
        self.modelParsed.connect(self._apply_parsed_model_info)
        self.keyProgress.connect(self._update_recording_display)
        self.keyFinished.connect(self._finish_recording)
        self.pipelineOutputLine.connect(self._handle_pipeline_output_line)
        self.pipelineFinishedAsync.connect(self._pipeline_finished)
        self.systemMetricsSampled.connect(self._apply_system_metrics)
        self.licenseStatusSampled.connect(self._apply_license_status)
        self.updateStatusSampled.connect(self._apply_update_status)
        self.class_model = ClassSelectionModel(self)
        self.log_model = LogListModel(self)
        self._log_lines = []
        self.conversion_process = None
        self.pipeline_process = None
        self._pipeline_stop_requested = False
        self.current_record_target = None
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
        self.theme_name = "极夜青辉"
        self.custom_theme_color = "#5EF2FF"
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
        self._pending_engine_output_path = ""
        self.metrics_timer = QTimer(self)
        self.metrics_timer.setInterval(1500)
        self.metrics_timer.timeout.connect(self._update_system_metrics)
        self._prime_cpu_usage()
        self._update_system_metrics()
        self.metrics_timer.start()
        self.license_status_timer = QTimer(self)
        self.license_status_timer.setInterval(60000)
        self.license_status_timer.timeout.connect(self.refreshLicenseStatus)
        self.license_status_timer.start()
        self.load_settings()
        self.refreshEsp32SerialPorts()
        self.refreshLicenseStatus()
        self._update_status_labels()

    def _emit_state(self):
        self.stateChanged.emit()

    def _set_esp32_scan_running(self, running: bool):
        self.esp32_scan_running = bool(running)
        self._emit_state()

    def _set_esp32_scan_status(self, text: str):
        self.esp32_scan_status = str(text)
        self._append_log(text)
        self._emit_state()

    def _append_log(self, message: str):
        line = message.rstrip()
        if not line:
            return
        self._extract_runtime_metrics(line)
        self._extract_auth_status(line)
        level = "info"
        upper_line = line.upper()
        if "[ERROR]" in upper_line:
            level = "error"
        elif "[WARN]" in upper_line:
            level = "warn"
        elif "[SUCCESS]" in upper_line:
            level = "success"
        self.log_model.append_line(line, level)
        self._log_lines.append(line)
        self._log_lines = self._log_lines[-400:]
        self.logTextChanged.emit()

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
            except LookupError:
                continue
        return raw_bytes.decode("utf-8", errors="replace")

    def _is_pipeline_running(self) -> bool:
        return bool(self.pipeline_process and self.pipeline_process.poll() is None)

    def _hidden_process_flags(self) -> int:
        if os.name != "nt":
            return 0
        return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

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

    def _handle_pipeline_output_line(self, line: str):
        if line.strip():
            self._append_log(line)

    def _pump_pipeline_output(self, process):
        try:
            if process.stdout:
                for raw_line in iter(process.stdout.readline, b""):
                    decoded = self._decode_process_output(raw_line)
                    for line in decoded.splitlines():
                        if line.strip():
                            self.pipelineOutputLine.emit(line)
        except Exception as exc:
            try:
                self.pipelineOutputLine.emit(f"[WARN] 推理核心日志读取中断: {exc}")
            except RuntimeError:
                pass
        finally:
            exit_code = process.wait()
            try:
                self.pipelineFinishedAsync.emit(int(getattr(process, "pid", -1)), int(exit_code))
            except RuntimeError:
                pass

    def _debug_report(self, hypothesis_id: str, location: str, msg: str, data=None):
        env_path = os.path.join(self.project_root, ".dbg", "panel-build-freeze.env")
        url = "http://127.0.0.1:7777/event"
        session_id = "panel-build-freeze"
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("DEBUG_SERVER_URL="):
                        url = line.split("=", 1)[1].strip() or url
                    elif line.startswith("DEBUG_SESSION_ID="):
                        session_id = line.split("=", 1)[1].strip() or session_id
        except Exception:
            pass
        try:
            payload = {
                "sessionId": session_id,
                "runId": "panel-runtime",
                "hypothesisId": hypothesis_id,
                "location": location,
                "msg": msg,
                "data": data or {},
            }
            urllib.request.urlopen(
                urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                ),
                timeout=0.5,
            ).read()
        except Exception:
            pass

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
        serial_mod, list_ports = self._load_pyserial()
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
        text = value.strip()
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
        return "neural" if text in ("神经模式", "绁炵粡妯″紡", "绁炵粡妯″紡") else "classic"

    def _trigger_mode_code(self) -> int:
        text = str(self.trigger_mode)
        if text in ("连续单点", "杩炵画鍗曠偣"):
            return 1
        if text in ("连续长按开火", "杩炵画闀挎寜寮€鐏火"):
            return 2
        return 0

    def _to_file_url(self, path_value: str) -> str:
        normalized = self._normalize_path(path_value)
        if not normalized:
            return ""
        return QUrl.fromLocalFile(normalized).toString()

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
        # Backward compatibility: legacy core used center-based offsets where
        # negative values were used by the legacy center-based offset mode.
        # New core uses 0..1 from head to foot and should keep non-negative inputs unchanged.
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

    def _coerce_color(self, value, default_value: str) -> str:
        text = str(value).strip()
        if not text:
            return default_value
        if len(text) == 7 and text.startswith("#"):
            return text
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

    def _current_palette(self):
        palette = dict(self.THEME_PRESETS.get(self.theme_name, self.THEME_PRESETS["极夜青辉"]))
        if self.theme_name == "自定义主题":
            palette["accent"] = self.custom_theme_color
        return palette

    def _selected_classes_list(self):
        if self.class_model.rowCount() > 0:
            selected = self.class_model.selected_ids()
            if selected:
                return selected
        values = []
        for part in str(self.selected_classes_text).split(","):
            part = part.strip()
            if part:
                values.append(part)
        return values

    def _sync_selected_classes_text(self):
        self.selected_classes_text = ",".join(self._selected_classes_list()) or "0"

    def _update_status_labels(self):
        self.status_model_text = f"模型: {os.path.basename(self.model_path) if self.model_path else '未选择'}"
        self.status_engine_text = f"引擎: {os.path.basename(self.engine_path) if self.engine_path else '未选择'}"
        self._emit_state()

    def _update_from_map(self, data):
        if not data:
            return
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
        self.trigger_delay = self._coerce_float(
            data.get("trigger_delay", self.trigger_delay), self.trigger_delay
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
        esp32_value = data.get("esp32_enabled", self.esp32_enabled)
        self.esp32_enabled = self._coerce_bool(esp32_value, self.esp32_enabled)
        self.esp32_port = str(data.get("esp32_port", self.esp32_port)).strip() or self.esp32_port
        self.esp32_baud = max(1200, self._coerce_int(data.get("esp32_baud", self.esp32_baud), self.esp32_baud))
        self.card_opacity = self._coerce_int(data.get("card_opacity", self.card_opacity), self.card_opacity)
        self.theme_name = str(data.get("theme_name", self.theme_name)) or self.theme_name
        self.custom_theme_color = self._coerce_color(
            data.get("custom_theme_color", self.custom_theme_color), self.custom_theme_color
        )
        self.background_image_path = self._normalize_path(
            str(data.get("background_image_path", self.background_image_path))
        )
        self.background_video_path = self._normalize_path(
            str(data.get("background_video_path", self.background_video_path))
        )
        self.background_video_url = str(data.get("background_video_url", self.background_video_url)).strip()
        self.background_volume = self._coerce_int(
            data.get("background_volume", self.background_volume), self.background_volume
        )
        self.active_background_mode = self._resolve_background_mode(
            data.get("active_background_mode", self.active_background_mode)
        )
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

    def _settings_path(self):
        return os.path.join(self.project_root, self.SAVE_FILE)

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
        for obsolete_key in ("head_y_offset", "body_y_offset", "head_classes", "body_classes"):
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
                "theme_name": self.theme_name,
                "custom_theme_color": self.custom_theme_color,
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
        settings_adjusted = legacy_settings_detected
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
        self.theme_name = str(settings.get("theme_name", self.theme_name)) or self.theme_name
        self.custom_theme_color = self._coerce_color(
            settings.get("custom_theme_color", self.custom_theme_color), self.custom_theme_color
        )
        self.background_image_path = self._normalize_path(
            settings.get("background_image_path", self.background_image_path)
        )
        self.background_video_path = self._normalize_path(
            settings.get("background_video_path", self.background_video_path)
        )
        self.background_video_url = str(settings.get("background_video_url", self.background_video_url)).strip()
        self.background_volume = int(settings.get("background_volume", self.background_volume))
        self.active_background_mode = self._resolve_background_mode(
            settings.get("active_background_mode", self.active_background_mode)
        )
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
        self._append_log(">> QML 试验版已恢复上次保存的参数配置。")
        if settings_adjusted:
            try:
                self._persist_settings()
                if legacy_settings_detected:
                    self._append_log(">> 已自动迁移旧版 Y 偏移配置到 0~1 新语义。")
                else:
                    self._append_log(">> 已自动校正卡尔曼预测系数到安全范围 0.0~4.0。")
            except Exception as exc:
                self._append_log(f"[WARN] 自动校正配置失败: {exc}")
        self._emit_state()
        if self.model_path and os.path.exists(self.model_path):
            self.parse_model_info_async(self.model_path)

    def _apply_parsed_model_info(self, options, status):
        self.available_classes_text = "\n".join(options) if options else "暂无类别信息"
        self.model_info_text = status
        self.class_model.set_items(options, self._selected_classes_list())
        self._sync_selected_classes_text()
        self._emit_state()

    def _prime_cpu_usage(self):
        idle, total = self._snapshot_cpu_times()
        self._cpu_prev_idle = idle
        self._cpu_prev_total = total

    def _snapshot_cpu_times(self):
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
        first_line = output.splitlines()[0]
        parts = [part.strip() for part in first_line.split(",")]
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
        self._emit_state()

    @Slot()
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

    @Slot()
    def autoDetectEsp32Serial(self):
        if self.esp32_scan_running:
            self._append_log("[WARN] 当前已有 ESP32 检测任务在进行。")
            return

        def _worker():
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
                        self._append_log(
                            f"[INFO] 串口探测 {port_item['port']} @ {baud}: {'OK' if ok else detail}"
                        )
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

        threading.Thread(target=_worker, daemon=True).start()

    @Slot()
    def probeEsp32Connection(self):
        if self.esp32_scan_running:
            self._append_log("[WARN] 当前已有 ESP32 检测任务在进行。")
            return

        def _worker():
            self._set_esp32_scan_running(True)
            try:
                ok, detail = self._probe_serial_port(self.esp32_port, self.esp32_baud)
                if ok:
                    self.esp32_serial_ports_text = (
                        f"串口候选: 当前目标 {self.esp32_port} @ {self.esp32_baud} 响应正常"
                    )
                    self._set_esp32_scan_status(
                        f"[SUCCESS] 串口检测通过: {self.esp32_port} @ {self.esp32_baud} | {detail}"
                    )
                else:
                    self._set_esp32_scan_status(
                        f"[WARN] 串口检测失败: {self.esp32_port} @ {self.esp32_baud} | {detail}"
                    )
                self._emit_state()
            finally:
                self._set_esp32_scan_running(False)

        threading.Thread(target=_worker, daemon=True).start()

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

    @Slot()
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

        def _worker():
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
                try:
                    self.licenseStatusSampled.emit(status)
                except RuntimeError:
                    pass
                with self._license_status_lock:
                    self._license_status_in_flight = False

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

    @Slot(str)
    def setUpdateManifestUrl(self, manifest_url: str):
        value = str(manifest_url or "").strip()
        if not value:
            return
        self.update_manifest_url = value
        self.update_status_text = "更新源已设置，等待检查"
        self._emit_state()

    @Slot()
    def checkForUpdates(self):
        with self._update_lock:
            if self._update_in_flight:
                return
            self._update_in_flight = True
        self._set_update_running(True, "正在检查更新...")

        def _worker():
            try:
                manifest = load_manifest(self.update_manifest_url)
                current = self._read_update_current_version()
                available = current != manifest.version
                message = (
                    f"发现新版本 {manifest.version}"
                    if available
                    else f"当前已是最新版本 {manifest.version}"
                )
                self.updateStatusSampled.emit(
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
                self.updateStatusSampled.emit(
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

        threading.Thread(target=_worker, daemon=True).start()

    @Slot()
    def applyAvailableUpdate(self):
        if self._is_pipeline_running():
            self.updateStatusSampled.emit(
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

        def _worker():
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
                self.updateStatusSampled.emit(
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
                self.updateStatusSampled.emit(
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

        threading.Thread(target=_worker, daemon=True).start()

    def _update_system_metrics(self):
        with self._metrics_lock:
            if self._metrics_sample_in_flight:
                return
            self._metrics_sample_in_flight = True

        def _worker():
            try:
                metrics = self._collect_system_metrics()
                try:
                    self.systemMetricsSampled.emit(metrics)
                except RuntimeError:
                    pass
            finally:
                with self._metrics_lock:
                    self._metrics_sample_in_flight = False

        threading.Thread(target=_worker, daemon=True).start()

    def _update_recording_display(self, target: str, display: str):
        if target == "aim":
            self.aim_keys_display = display
        else:
            self.trigger_keys_display = display
        self._emit_state()

    def _finish_recording(self, target: str, value_csv: str, display: str, log_message: str):
        self.current_record_target = None
        if target == "aim":
            self.aim_keys = value_csv
            self.aim_keys_display = display
        else:
            self.trigger_keys = value_csv
            self.trigger_keys_display = display
        self._append_log(log_message)
        self._emit_state()

    def parse_model_info_async(self, file_path: str):
        path = self._normalize_path(file_path)
        if not path or not os.path.exists(path):
            self.model_info_text = "模型信息: 文件不存在"
            self.available_classes_text = ""
            self._emit_state()
            return

        def _worker():
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
                    names_dict = model.names
                    options = [f"{k} - {v}" for k, v in names_dict.items()]
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
            self.modelParsed.emit(options, status)

        self.model_info_text = "模型信息: 正在解析类别..."
        self._emit_state()
        threading.Thread(target=_worker, daemon=True).start()

    @Slot(str)
    def setModelPath(self, value: str):
        self.model_path = self._normalize_path(value)
        self._update_status_labels()
        if self.model_path:
            self._append_log(f">> 已选择模型: {self.model_path}")
            self.parse_model_info_async(self.model_path)
        self._emit_state()

    @Slot(str)
    def setEnginePath(self, value: str):
        self.engine_path = self._normalize_path(value)
        self._update_status_labels()
        if self.engine_path:
            self._append_log(f">> 已选择引擎: {self.engine_path}")
        self._emit_state()

    @Slot(str, result=str)
    def toLocalPath(self, value: str):
        return self._normalize_path(value)

    @Slot(int, bool)
    def setClassChecked(self, row: int, checked: bool):
        self.class_model.setChecked(row, checked)
        self._sync_selected_classes_text()
        if self._is_pipeline_running():
            self._write_pipeline_config()
        self._emit_state()

    @Slot(str)
    def startKeyRecord(self, target: str):
        if self.current_record_target is not None:
            self._append_log("[WARN] 当前已有录入任务在进行。")
            return
        if target not in ("aim", "trigger"):
            self._append_log(f"[ERROR] 未知录入目标: {target}")
            return
        self.current_record_target = target
        if target == "aim":
            self.aim_keys_display = "按 ESC 结束录入..."
        else:
            self.trigger_keys_display = "按 ESC 结束录入..."
        self._append_log(f">> 进入[{ '自瞄' if target == 'aim' else '扳机' }]按键录入模式，按 ESC 结束。")
        self._emit_state()
        threading.Thread(target=self._record_keys_worker, args=(target,), daemon=True).start()

    def _record_keys_worker(self, target: str):
        try:
            try:
                from pynput import keyboard, mouse
            except ImportError:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "pynput"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=self._hidden_process_flags(),
                )
                from pynput import keyboard, mouse

            recorded_vk_codes = set()
            recorded_names = []
            if target == "aim":
                default_vk = 0x02
                default_name = "右键 (VK:2)"
            else:
                default_vk = 0x01
                default_name = "左键 (VK:1)"

            def emit_progress():
                display = " + ".join(recorded_names) + " (按ESC结束)"
                self.keyProgress.emit(target, display)

            def on_press(key):
                try:
                    if key == keyboard.Key.esc:
                        return False
                    vk = None
                    name = ""
                    if hasattr(key, "vk") and key.vk is not None:
                        vk = key.vk
                        name = getattr(key, "name", str(key))
                    elif hasattr(key, "value") and hasattr(key.value, "vk"):
                        vk = key.value.vk
                        name = key.name
                    elif hasattr(key, "char") and key.char:
                        vk = ord(key.char.upper())
                        name = key.char.upper()
                    if vk and vk not in recorded_vk_codes:
                        recorded_vk_codes.add(vk)
                        recorded_names.append(f"{name} (VK:{vk})")
                        emit_progress()
                except Exception:
                    return True
                return True

            def on_click(_x, _y, button, pressed):
                if not pressed:
                    return
                try:
                    mapping = {
                        mouse.Button.left: (0x01, "左键"),
                        mouse.Button.right: (0x02, "右键"),
                        mouse.Button.middle: (0x04, "中键"),
                        mouse.Button.x1: (0x05, "侧键1"),
                        mouse.Button.x2: (0x06, "侧键2"),
                    }
                    if button not in mapping:
                        return
                    vk, name = mapping[button]
                    if vk not in recorded_vk_codes:
                        recorded_vk_codes.add(vk)
                        recorded_names.append(f"{name} (VK:{vk})")
                        emit_progress()
                except Exception:
                    return

            mouse_listener = mouse.Listener(on_click=on_click)
            keyboard_listener = keyboard.Listener(on_press=on_press)
            mouse_listener.start()
            keyboard_listener.start()
            keyboard_listener.join()
            mouse_listener.stop()

            if not recorded_vk_codes:
                recorded_vk_codes.add(default_vk)
                recorded_names.append(default_name)

            value_csv = ",".join(str(vk) for vk in sorted(recorded_vk_codes))
            display = " + ".join(recorded_names)
            log_message = f">> 已保存[{ '自瞄' if target == 'aim' else '扳机' }]按键配置: {display}"
            self.keyFinished.emit(target, value_csv, display, log_message)
        except Exception as exc:
            fallback_value = "2" if target == "aim" else "1"
            fallback_display = "右键 (VK:2)" if target == "aim" else "左键 (VK:1)"
            self.keyFinished.emit(
                target,
                fallback_value,
                fallback_display,
                f"[ERROR] 按键录入失败: {exc}",
            )

    @Slot(str)
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

    @Slot("QVariantMap")
    def updateVisualSettings(self, data):
        self._update_from_map(data)
        if self._is_pipeline_running():
            self._write_pipeline_config()
        self._emit_state()

    @Slot(str)
    def setBackgroundImagePath(self, value: str):
        self.background_image_path = self._normalize_path(value)
        if self.background_image_path:
            self.background_video_path = ""
            self.background_video_url = ""
        self.active_background_mode = self._resolve_background_mode("image")
        self._append_log(
            f"[INFO] 背景已切换为图片: {os.path.basename(self.background_image_path)}"
            if self.background_image_path
            else "[INFO] 已清除背景图片。"
        )
        self._emit_state()

    @Slot()
    def clearBackgroundImage(self):
        self.background_image_path = ""
        self.background_video_path = ""
        self.background_video_url = ""
        self.active_background_mode = self._resolve_background_mode()
        self._append_log("[INFO] 已恢复默认渐变背景。")
        self._emit_state()

    @Slot(str)
    def setBackgroundVideoPath(self, value: str):
        self.background_video_path = self._normalize_path(value)
        if self.background_video_path:
            self.background_image_path = ""
            self.background_video_url = ""
        self.active_background_mode = self._resolve_background_mode("video")
        self._append_log(
            f"[INFO] 背景已切换为本地视频: {os.path.basename(self.background_video_path)}"
            if self.background_video_path
            else "[INFO] 已清除背景视频。"
        )
        self._emit_state()

    @Slot(str)
    def setBackgroundVideoUrl(self, value: str):
        self.background_video_url = str(value).strip()
        if self.background_video_url:
            self.background_image_path = ""
            self.background_video_path = ""
        self.active_background_mode = self._resolve_background_mode("web")
        self._append_log(
            "[INFO] 已设置在线视频背景链接。"
            if self.background_video_url
            else "[INFO] 已清除在线视频背景链接。"
        )
        self._emit_state()

    @Slot()
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
                subprocess.Popen(
                    ["cmd", "/c", "start", "", sys.executable, "-m", "netron", model_path],
                    shell=False,
                )
                self._append_log(f"[INFO] 已通过 python -m netron 打开: {os.path.basename(model_path)}")
            except Exception as exc:
                self._append_log(f"[ERROR] 启动 Netron 失败: {exc}")

    @Slot("QVariantMap")
    def saveSettings(self, data):
        self._update_from_map(data)
        try:
            self._persist_settings()
            self._append_log(">> 当前配置已保存。")
        except Exception as exc:
            self._append_log(f"[ERROR] 保存配置失败: {exc}")

    @Slot("QVariantMap")
    def startConversion(self, data):
        self._update_from_map(data)
        model_path = self.model_path
        if not model_path or not os.path.exists(model_path):
            self._append_log("[ERROR] 请先选择有效的 .onnx 文件。")
            return
        if not model_path.lower().endswith(".onnx"):
            self._append_log("[ERROR] 当前独立编译包仅支持 .onnx -> .engine。")
            return
        if self.conversion_process and self.conversion_process.state() != QProcess.NotRunning:
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
        self._pending_engine_output_path = os.path.join(
            self._texture_preprocess_engine_path(model_path, texture_input_size),
        )
        os.makedirs(self.models_root, exist_ok=True)
        self.conversion_process = QProcess(self)
        self.conversion_process.setProgram(builder_path)
        self.conversion_process.setArguments(
            [model_path, self._pending_engine_output_path, str(texture_input_size), str(texture_input_size), "1"]
        )
        self.conversion_process.setWorkingDirectory(builder_working_dir)
        self.conversion_process.setProcessChannelMode(QProcess.MergedChannels)
        self.conversion_process.readyReadStandardOutput.connect(self._read_conversion_output)
        self.conversion_process.finished.connect(self._conversion_finished)
        # #region debug-point A:start-conversion
        self._debug_report("A", "qml_bridge.py:startConversion", "[DEBUG] starting conversion process", {"model_path": model_path, "builder_path": builder_path, "pending_engine_output_path": self._pending_engine_output_path, "working_directory": builder_working_dir, "arguments": [model_path, self._pending_engine_output_path, str(texture_input_size), str(texture_input_size), "1"]})
        # #endregion
        self.conversionRunningChanged.emit()
        self._append_log(f">> 开始编译 TexPre FP16 模型: {os.path.basename(model_path)}")
        self._append_log(f">> 输出引擎: {self._pending_engine_output_path}")
        self._append_log(f">> Plugin 输入尺寸: {texture_input_size}x{texture_input_size}")
        self._append_log(">> 当前使用 runtime\\build_texture_preprocess_engine.exe 生成 TexturePreprocessPlugin FP16 Engine。")
        self._append_log(f">> 编译依赖目录: {builder_working_dir}")
        self.conversion_process.start()
        # #region debug-point B:post-start-state
        self._debug_report("B", "qml_bridge.py:startConversion", "[DEBUG] conversion process start invoked", {"qt_state_after_start_call": int(self.conversion_process.state())})
        # #endregion

    def _read_conversion_output(self):
        if not self.conversion_process:
            return
        data = self._decode_process_output(self.conversion_process.readAllStandardOutput().data())
        # #region debug-point C:conversion-output
        if data.strip():
            self._debug_report("C", "qml_bridge.py:_read_conversion_output", "[DEBUG] conversion output received", {"length": len(data), "preview": data[:500], "qt_state": int(self.conversion_process.state())})
        # #endregion
        for line in data.splitlines():
            if line.strip():
                path_match = self._engine_output_pattern.search(line)
                if path_match:
                    self._pending_engine_output_path = self._normalize_path(path_match.group(1).strip())
                self._append_log(line)

    def _conversion_finished(self, exit_code, _exit_status):
        # #region debug-point D:conversion-finished
        self._debug_report("D", "qml_bridge.py:_conversion_finished", "[DEBUG] conversion process finished", {"exit_code": int(exit_code), "pending_engine_output_path": self._pending_engine_output_path, "engine_exists": bool(self._pending_engine_output_path and os.path.exists(self._pending_engine_output_path))})
        # #endregion
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
        self.conversionRunningChanged.emit()

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
        config_path = self.runtime_config_path
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        try:
            with open(config_path, "w", encoding="utf-8") as f:
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
                f.write("trigger_hitbox_enter_scale=1.10\n")
                f.write("trigger_hitbox_exit_scale=1.35\n")
                f.write("trigger_hold_grace_ms=70.0\n")
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

    @Slot("QVariantMap")
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
            self.pipelineRunningChanged.emit()
            self._append_log(f"[ERROR] 推理核心启动失败: {exc}")
            return
        threading.Thread(target=self._pump_pipeline_output, args=(self.pipeline_process,), daemon=True).start()
        self.pipelineRunningChanged.emit()
        self._append_log(f"[INFO] 推理核心已隐藏启动，日志已接入 QML 面板。PID={self.pipeline_process.pid}")

    def _read_pipeline_output(self):
        # Pipeline output is pumped by _pump_pipeline_output when using hidden Popen.
        return

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
        self.pipelineRunningChanged.emit()

    @Slot()
    def stopPipeline(self):
        if self._is_pipeline_running():
            self._pipeline_stop_requested = True
            self.pipeline_process.kill()
            try:
                self.pipeline_process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
            self._append_log("[INFO] 已请求停止推理核心。")
            self.status_mode_text = "模式: 未启动"
            self._reset_runtime_metrics()
            self._emit_state()
            self.pipelineRunningChanged.emit()

    @Slot()
    def shutdown(self):
        try:
            self.metrics_timer.stop()
        except Exception:
            pass
        try:
            self._persist_settings()
        except Exception:
            pass
        if self.conversion_process and self.conversion_process.state() != QProcess.NotRunning:
            self.conversion_process.kill()
            self.conversion_process.waitForFinished(500)
        if self._is_pipeline_running():
            self._pipeline_stop_requested = True
            self.pipeline_process.kill()
            try:
                self.pipeline_process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass

    def _get_log_text(self):
        return "\n".join(self._log_lines)

    def _get_model_path(self):
        return self.model_path

    def _get_engine_path(self):
        return self.engine_path

    def _get_models_library_url(self):
        return self._to_file_url(self.models_root)

    def _get_imgsz(self):
        return self.imgsz

    def _get_roi(self):
        return self.roi

    def _get_conf(self):
        return self.conf

    def _get_nms(self):
        return self.nms

    def _get_pid_p(self):
        return self.pid_p

    def _get_pid_i(self):
        return self.pid_i

    def _get_pid_d(self):
        return self.pid_d

    def _get_y_offset(self):
        return self.y_offset

    def _get_fps_limit(self):
        return self.fps_limit

    def _get_trigger_mode(self):
        return self.trigger_mode

    def _get_trigger_delay(self):
        return self.trigger_delay

    def _get_card_opacity(self):
        return self.card_opacity

    def _get_theme_name(self):
        return self.theme_name

    def _get_custom_theme_color(self):
        return self.custom_theme_color

    def _get_background_image_path(self):
        return self.background_image_path

    def _get_background_video_path(self):
        return self.background_video_path

    def _get_background_video_url(self):
        return self.background_video_url

    def _get_background_volume(self):
        return self.background_volume

    def _get_active_background_mode(self):
        return self.active_background_mode

    def _get_background_status_text(self):
        if self.active_background_mode == "image" and self.background_image_path:
            return f"背景: 图片 {os.path.basename(self.background_image_path)}"
        if self.active_background_mode == "video" and self.background_video_path:
            return f"背景: 本地视频 {os.path.basename(self.background_video_path)}"
        if self.active_background_mode == "web" and self.background_video_url:
            return "背景: 在线视频"
        return "背景: 默认渐变"

    def _get_pipeline_mode(self):
        return self.pipeline_mode

    def _get_capture_path_text(self):
        return self.capture_path_text

    def _get_motion_mode(self):
        return self.motion_mode

    def _get_neural_curvature(self):
        return self.neural_curvature

    def _get_neural_tremor(self):
        return self.neural_tremor

    def _get_aim_keys(self):
        return self.aim_keys

    def _get_trigger_keys(self):
        return self.trigger_keys

    def _get_aim_keys_display(self):
        return self.aim_keys_display

    def _get_trigger_keys_display(self):
        return self.trigger_keys_display

    def _get_selected_classes_text(self):
        return self.selected_classes_text

    def _get_available_classes_text(self):
        return self.available_classes_text

    def _get_model_info_text(self):
        return self.model_info_text

    def _get_status_mode_text(self):
        return self.status_mode_text

    def _get_status_model_text(self):
        return self.status_model_text

    def _get_status_engine_text(self):
        return self.status_engine_text

    def _get_cpu_metric_text(self):
        return self.cpu_metric_text

    def _get_gpu_metric_text(self):
        return self.gpu_metric_text

    def _get_memory_metric_text(self):
        return self.memory_metric_text

    def _get_cpu_usage_value(self):
        return self.cpu_usage_value

    def _get_gpu_usage_value(self):
        return self.gpu_usage_value

    def _get_memory_usage_value(self):
        return self.memory_usage_value

    def _get_latency_metric_text(self):
        return self.latency_metric_text

    def _get_fps_metric_text(self):
        return self.fps_metric_text

    def _get_class_model(self):
        return self.class_model

    def _get_log_model(self):
        return self.log_model

    def _get_recording_active(self):
        return self.current_record_target is not None

    def _get_current_record_target(self):
        return self.current_record_target or ""

    def _get_conversion_running(self):
        return bool(self.conversion_process and self.conversion_process.state() != QProcess.NotRunning)

    def _get_pipeline_running(self):
        return self._is_pipeline_running()

    def _get_kalman_en(self):
        return self.kalman_en

    def _get_kalman_pred(self):
        return self.kalman_pred

    def _get_recoil_en(self):
        return self.recoil_en

    def _get_trigger_recoil_en(self):
        return self.trigger_recoil_en

    def _get_recoil_strength(self):
        return self.recoil_strength

    def _get_recoil_delay(self):
        return self.recoil_delay

    def _get_license_expiry_text(self):
        return self.license_expiry_text

    def _get_license_badge_text(self):
        return self.license_badge_text

    def _get_license_expiry_compact_text(self):
        return self.license_expiry_compact_text

    def _get_license_remaining_text(self):
        return self.license_remaining_text

    def _get_license_status_detail(self):
        return self.license_status_detail

    def _get_update_status_text(self):
        return self.update_status_text

    def _get_update_current_version(self):
        return self.update_current_version

    def _get_update_latest_version(self):
        return self.update_latest_version

    def _get_update_available(self):
        return self.update_available

    def _get_update_running(self):
        return self.update_running

    def _get_update_manifest_url(self):
        return self.update_manifest_url

    def _get_stick_enable(self):
        return self.stick_enable

    def _get_stick_int(self):
        return self.stick_int

    def _get_stick_rad(self):
        return self.stick_rad

    def _get_lghub_enabled(self):
        return self.lghub_enabled

    def _get_esp32_enabled(self):
        return self.esp32_enabled

    def _get_esp32_port(self):
        return self.esp32_port

    def _get_esp32_baud(self):
        return self.esp32_baud

    def _get_esp32_scan_status(self):
        return self.esp32_scan_status

    def _get_esp32_serial_ports_text(self):
        return self.esp32_serial_ports_text

    def _get_esp32_scan_running(self):
        return self.esp32_scan_running

    def _get_accent_color(self):
        return self._current_palette()["accent"]

    def _get_accent2_color(self):
        return self._current_palette()["accent2"]

    def _get_surface_color(self):
        return self._current_palette()["surface"]

    def _get_surface_alt_color(self):
        return self._current_palette()["surface_alt"]

    def _get_text_color(self):
        return self._current_palette()["text"]

    def _get_muted_color(self):
        return self._current_palette()["muted"]

    def _get_hero_start_color(self):
        return self._current_palette()["hero_start"]

    def _get_hero_end_color(self):
        return self._current_palette()["hero_end"]

    def _get_sidebar_color(self):
        return self._current_palette()["sidebar"]

    modelPath = Property(str, _get_model_path, notify=stateChanged)
    enginePath = Property(str, _get_engine_path, notify=stateChanged)
    modelsLibraryUrl = Property(str, _get_models_library_url, constant=True)
    imgszValue = Property(int, _get_imgsz, notify=stateChanged)
    roiValue = Property(int, _get_roi, notify=stateChanged)
    confValue = Property(float, _get_conf, notify=stateChanged)
    nmsValue = Property(float, _get_nms, notify=stateChanged)
    pidPValue = Property(float, _get_pid_p, notify=stateChanged)
    pidIValue = Property(float, _get_pid_i, notify=stateChanged)
    pidDValue = Property(float, _get_pid_d, notify=stateChanged)
    yOffsetValue = Property(float, _get_y_offset, notify=stateChanged)
    fpsLimitValue = Property(int, _get_fps_limit, notify=stateChanged)
    triggerModeValue = Property(str, _get_trigger_mode, notify=stateChanged)
    triggerDelayValue = Property(float, _get_trigger_delay, notify=stateChanged)
    cardOpacityValue = Property(int, _get_card_opacity, notify=stateChanged)
    themeNameValue = Property(str, _get_theme_name, notify=stateChanged)
    customThemeColorValue = Property(str, _get_custom_theme_color, notify=stateChanged)
    backgroundImagePathValue = Property(str, _get_background_image_path, notify=stateChanged)
    backgroundVideoPathValue = Property(str, _get_background_video_path, notify=stateChanged)
    backgroundVideoUrlValue = Property(str, _get_background_video_url, notify=stateChanged)
    backgroundVolumeValue = Property(int, _get_background_volume, notify=stateChanged)
    activeBackgroundModeValue = Property(str, _get_active_background_mode, notify=stateChanged)
    backgroundStatusText = Property(str, _get_background_status_text, notify=stateChanged)
    pipelineModeValue = Property(str, _get_pipeline_mode, notify=stateChanged)
    capturePathText = Property(str, _get_capture_path_text, notify=stateChanged)
    motionModeValue = Property(str, _get_motion_mode, notify=stateChanged)
    neuralCurvatureValue = Property(float, _get_neural_curvature, notify=stateChanged)
    neuralTremorValue = Property(float, _get_neural_tremor, notify=stateChanged)
    aimKeysValue = Property(str, _get_aim_keys, notify=stateChanged)
    triggerKeysValue = Property(str, _get_trigger_keys, notify=stateChanged)
    aimKeysDisplayValue = Property(str, _get_aim_keys_display, notify=stateChanged)
    triggerKeysDisplayValue = Property(str, _get_trigger_keys_display, notify=stateChanged)
    selectedClassesText = Property(str, _get_selected_classes_text, notify=stateChanged)
    availableClassesText = Property(str, _get_available_classes_text, notify=stateChanged)
    modelInfoText = Property(str, _get_model_info_text, notify=stateChanged)
    statusModeText = Property(str, _get_status_mode_text, notify=stateChanged)
    statusModelText = Property(str, _get_status_model_text, notify=stateChanged)
    statusEngineText = Property(str, _get_status_engine_text, notify=stateChanged)
    cpuMetricText = Property(str, _get_cpu_metric_text, notify=stateChanged)
    gpuMetricText = Property(str, _get_gpu_metric_text, notify=stateChanged)
    memoryMetricText = Property(str, _get_memory_metric_text, notify=stateChanged)
    cpuUsageValue = Property(float, _get_cpu_usage_value, notify=stateChanged)
    gpuUsageValue = Property(float, _get_gpu_usage_value, notify=stateChanged)
    memoryUsageValue = Property(float, _get_memory_usage_value, notify=stateChanged)
    latencyMetricText = Property(str, _get_latency_metric_text, notify=stateChanged)
    fpsMetricText = Property(str, _get_fps_metric_text, notify=stateChanged)
    classModel = Property(QObject, _get_class_model, constant=True)
    logModel = Property(QObject, _get_log_model, constant=True)
    recordingActive = Property(bool, _get_recording_active, notify=stateChanged)
    currentRecordTarget = Property(str, _get_current_record_target, notify=stateChanged)
    kalmanEnableValue = Property(bool, _get_kalman_en, notify=stateChanged)
    kalmanPredValue = Property(float, _get_kalman_pred, notify=stateChanged)
    recoilEnableValue = Property(bool, _get_recoil_en, notify=stateChanged)
    triggerRecoilEnableValue = Property(bool, _get_trigger_recoil_en, notify=stateChanged)
    recoilStrengthValue = Property(float, _get_recoil_strength, notify=stateChanged)
    recoilDelayValue = Property(float, _get_recoil_delay, notify=stateChanged)
    licenseExpiryText = Property(str, _get_license_expiry_text, notify=stateChanged)
    licenseBadgeText = Property(str, _get_license_badge_text, notify=stateChanged)
    licenseExpiryCompactText = Property(str, _get_license_expiry_compact_text, notify=stateChanged)
    licenseRemainingText = Property(str, _get_license_remaining_text, notify=stateChanged)
    licenseStatusDetail = Property(str, _get_license_status_detail, notify=stateChanged)
    updateStatusText = Property(str, _get_update_status_text, notify=stateChanged)
    updateCurrentVersion = Property(str, _get_update_current_version, notify=stateChanged)
    updateLatestVersion = Property(str, _get_update_latest_version, notify=stateChanged)
    updateAvailable = Property(bool, _get_update_available, notify=stateChanged)
    updateRunning = Property(bool, _get_update_running, notify=stateChanged)
    updateManifestUrl = Property(str, _get_update_manifest_url, notify=stateChanged)
    stickEnableValue = Property(bool, _get_stick_enable, notify=stateChanged)
    stickIntValue = Property(float, _get_stick_int, notify=stateChanged)
    stickRadValue = Property(float, _get_stick_rad, notify=stateChanged)
    lghubEnabledValue = Property(bool, _get_lghub_enabled, notify=stateChanged)
    esp32EnabledValue = Property(bool, _get_esp32_enabled, notify=stateChanged)
    esp32PortValue = Property(str, _get_esp32_port, notify=stateChanged)
    esp32BaudValue = Property(int, _get_esp32_baud, notify=stateChanged)
    esp32ScanStatusValue = Property(str, _get_esp32_scan_status, notify=stateChanged)
    esp32SerialPortsTextValue = Property(str, _get_esp32_serial_ports_text, notify=stateChanged)
    esp32ScanRunningValue = Property(bool, _get_esp32_scan_running, notify=stateChanged)
    accentColor = Property(str, _get_accent_color, notify=stateChanged)
    accent2Color = Property(str, _get_accent2_color, notify=stateChanged)
    surfaceColor = Property(str, _get_surface_color, notify=stateChanged)
    surfaceAltColor = Property(str, _get_surface_alt_color, notify=stateChanged)
    textColor = Property(str, _get_text_color, notify=stateChanged)
    mutedColor = Property(str, _get_muted_color, notify=stateChanged)
    heroStartColor = Property(str, _get_hero_start_color, notify=stateChanged)
    heroEndColor = Property(str, _get_hero_end_color, notify=stateChanged)
    sidebarColor = Property(str, _get_sidebar_color, notify=stateChanged)
    logText = Property(str, _get_log_text, notify=logTextChanged)
    conversionRunning = Property(bool, _get_conversion_running, notify=conversionRunningChanged)
    pipelineRunning = Property(bool, _get_pipeline_running, notify=pipelineRunningChanged)

