import json
import math
import secrets
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


TRIGGER_MODE_TEXT = {
    0: "关闭",
    1: "连续单点",
    2: "连续长按开火",
}
PIPELINE_MODE_TEXT = {
    0: "性能模式",
    1: "调试模式",
}
MOTION_MODE_TEXT = {
    0: "经典模式",
    1: "神经模式",
}
PANEL_ACTIONS = {
    "pipeline.start",
    "pipeline.stop",
    "settings.save",
    "model.convert",
    "model.netron",
    "update.check",
    "update.apply",
    "background.clear",
    "file.browse_model",
    "file.browse_engine",
    "file.browse_background",
    "esp32.refresh",
    "esp32.auto",
    "esp32.probe",
    "keys.record_aim",
    "keys.record_trigger",
    "keys.reset_aim",
    "keys.reset_trigger",
    "web.client_open",
    "web.heartbeat",
    "web.close",
    "web.shutdown",
}


class MobileControlError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None):
        super().__init__(message)
        self.status = int(status)
        self.code = str(code)
        self.message = str(message)
        self.details = details


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str
    group: str
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    precision: int | None = None
    hot: bool = True

    def to_schema(self):
        item = {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "group": self.group,
            "hot": self.hot,
        }
        if self.min_value is not None:
            item["min"] = self.min_value
        if self.max_value is not None:
            item["max"] = self.max_value
        if self.step is not None:
            item["step"] = self.step
        if self.precision is not None:
            item["precision"] = self.precision
        if self.kind == "triggerMode":
            item["choices"] = [{"value": value, "label": label} for value, label in TRIGGER_MODE_TEXT.items()]
        elif self.kind == "pipelineMode":
            item["choices"] = [{"value": value, "label": label} for value, label in PIPELINE_MODE_TEXT.items()]
        elif self.kind == "motionMode":
            item["choices"] = [{"value": value, "label": label} for value, label in MOTION_MODE_TEXT.items()]
        return item


MOBILE_CONTROL_FIELDS = (
    FieldSpec("card_opacity", "透明度", "int", "外观", 0, 100, 1, 0),
    FieldSpec("background_image_path", "背景图片", "path", "外观"),
    FieldSpec("model_path", "模型文件", "path", "文件", hot=False),
    FieldSpec("engine_path", "引擎文件", "path", "文件", hot=False),
    FieldSpec("imgsz", "输入尺寸", "int", "运行", 160, 2048, 32, 0, False),
    FieldSpec("roi", "ROI", "int", "运行", 64, 2048, 32, 0, False),
    FieldSpec("pipeline_mode", "运行模式", "pipelineMode", "运行", hot=False),
    FieldSpec("motion_mode", "移动模式", "motionMode", "运行"),
    FieldSpec("lghub_enabled", "LGHUB 驱动", "bool", "输入", hot=False),
    FieldSpec("esp32_enabled", "ESP32 驱动", "bool", "输入", hot=False),
    FieldSpec("esp32_port", "ESP32 串口", "serialPort", "输入", hot=False),
    FieldSpec("esp32_baud", "ESP32 波特率", "int", "输入", 1200, 2000000, 9600, 0, False),
    FieldSpec("aim_keys", "自瞄按键", "keyCsv", "输入"),
    FieldSpec("trigger_keys", "扳机按键", "keyCsv", "输入"),
    FieldSpec("conf", "置信度", "float", "基础", 0.0, 1.0, 0.01, 3),
    FieldSpec("nms", "NMS", "float", "基础", 0.0, 1.0, 0.01, 3),
    FieldSpec("fps_limit", "帧率限制", "int", "基础", 0, 360, 1, 0),
    FieldSpec("selected_classes_text", "目标类别", "classCsv", "基础"),
    FieldSpec("pid_p", "PID-P", "float", "瞄准", -10.0, 10.0, 0.01, 3),
    FieldSpec("pid_i", "PID-I", "float", "瞄准", -10.0, 10.0, 0.001, 3),
    FieldSpec("pid_d", "PID-D", "float", "瞄准", -10.0, 10.0, 0.001, 3),
    FieldSpec("y_offset", "Y 轴偏移", "float", "瞄准", 0.0, 1.0, 0.01, 3),
    FieldSpec("neural_curvature", "神经曲率", "float", "瞄准", 0.0, 0.60, 0.01, 2),
    FieldSpec("neural_tremor", "神经微抖", "float", "瞄准", 0.0, 1.60, 0.01, 2),
    FieldSpec("trigger_mode", "扳机模式", "triggerMode", "扳机"),
    FieldSpec("trigger_delay", "扳机间隔", "float", "扳机", 0.0, 1000.0, 1.0, 1),
    FieldSpec("trigger_hitbox_enter_scale", "进入范围", "float", "扳机", 0.50, 2.50, 0.05, 2),
    FieldSpec("trigger_hitbox_exit_scale", "保持范围", "float", "扳机", 0.50, 3.00, 0.05, 2),
    FieldSpec("trigger_hold_grace_ms", "宽限 ms", "float", "扳机", 0.0, 250.0, 1.0, 1),
    FieldSpec("kalman_en", "卡尔曼", "bool", "稳定"),
    FieldSpec("kalman_pred", "预测强度", "float", "稳定", 0.0, 4.0, 0.1, 1),
    FieldSpec("stick_enable", "粘性锁定", "bool", "稳定"),
    FieldSpec("stick_int", "粘性强度", "float", "稳定", 0.0, 5.0, 0.01, 3),
    FieldSpec("stick_rad", "粘性半径", "float", "稳定", 0.0, 2.0, 0.01, 3),
    FieldSpec("recoil_en", "压枪", "bool", "压枪"),
    FieldSpec("trigger_recoil_en", "扳机压枪", "bool", "压枪"),
    FieldSpec("recoil_strength", "压枪力度", "float", "压枪", 0.0, 20.0, 0.1, 2),
    FieldSpec("recoil_delay", "压枪延迟", "float", "压枪", 0.0, 1000.0, 1.0, 1),
)
FIELD_BY_KEY = {field.key: field for field in MOBILE_CONTROL_FIELDS}


def mobile_control_schema():
    return [field.to_schema() for field in MOBILE_CONTROL_FIELDS]


def _coerce_bool(value, key):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{key} must be boolean")


def _coerce_float(value, spec: FieldSpec):
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{spec.key} must be a number")
    if not math.isfinite(parsed):
        raise ValueError(f"{spec.key} must be finite")
    if spec.min_value is not None and parsed < spec.min_value:
        raise ValueError(f"{spec.key} must be >= {spec.min_value}")
    if spec.max_value is not None and parsed > spec.max_value:
        raise ValueError(f"{spec.key} must be <= {spec.max_value}")
    return parsed


def _coerce_int(value, spec: FieldSpec):
    parsed = _coerce_float(value, spec)
    return int(round(parsed))


def _coerce_trigger_mode(value):
    if isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit()):
        parsed = int(value)
        if parsed in TRIGGER_MODE_TEXT:
            return TRIGGER_MODE_TEXT[parsed]
    text = str(value).strip()
    if text in TRIGGER_MODE_TEXT.values():
        return text
    aliases = {
        "off": 0,
        "none": 0,
        "single": 1,
        "click": 1,
        "hold": 2,
        "press": 2,
    }
    lowered = text.lower()
    if lowered in aliases:
        return TRIGGER_MODE_TEXT[aliases[lowered]]
    raise ValueError("trigger_mode must be 0, 1, 2, or a known trigger mode label")


def _coerce_enum_mode(value, key, mapping, aliases):
    if isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit()):
        parsed = int(value)
        if parsed in mapping:
            return mapping[parsed]
    text = str(value).strip()
    if text in mapping.values():
        return text
    lowered = text.lower()
    if lowered in aliases:
        return mapping[aliases[lowered]]
    raise ValueError(f"{key} must be one of {', '.join(str(item) for item in mapping)}")


def _coerce_path(value, key):
    text = str(value or "").strip()
    if "\x00" in text:
        raise ValueError(f"{key} contains an invalid character")
    if len(text) > 1024:
        raise ValueError(f"{key} is too long")
    return text


def _coerce_serial_port(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError("esp32_port must not be empty")
    if "\x00" in text or len(text) > 64:
        raise ValueError("esp32_port is invalid")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-")
    if any(char not in allowed for char in text):
        raise ValueError("esp32_port contains unsupported characters")
    return text


def _coerce_key_csv(value, key):
    values = []
    for part in str(value).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            parsed = int(part, 16) if part.lower().startswith("0x") else int(part)
        except ValueError:
            raise ValueError(f"{key} must contain numeric VK codes")
        if parsed < 1 or parsed > 255:
            raise ValueError(f"{key} VK codes must be 1..255")
        values.append(str(parsed))
    if not values:
        raise ValueError(f"{key} must contain at least one VK code")
    return ",".join(dict.fromkeys(values))


def _coerce_class_csv(value):
    if isinstance(value, list):
        parts = [str(item).strip() for item in value]
    else:
        parts = [part.strip() for part in str(value).split(",")]
    clean = []
    for part in parts:
        if not part:
            continue
        if not part.isdigit():
            raise ValueError("selected_classes_text must contain numeric class ids")
        parsed = int(part)
        if parsed < 0 or parsed > 999:
            raise ValueError("selected_classes_text class ids must be 0..999")
        clean.append(str(parsed))
    if not clean:
        raise ValueError("selected_classes_text must contain at least one class id")
    return ",".join(dict.fromkeys(clean))


def validate_config_patch(payload):
    if not isinstance(payload, dict):
        raise MobileControlError(400, "INVALID_JSON", "Request body must be a JSON object")
    unknown = sorted(key for key in payload if key not in FIELD_BY_KEY)
    if unknown:
        raise MobileControlError(
            422,
            "VALIDATION_ERROR",
            "Unsupported config field",
            {"fields": unknown},
        )

    clean = {}
    errors = {}
    for key, value in payload.items():
        spec = FIELD_BY_KEY[key]
        try:
            if spec.kind == "bool":
                clean[key] = _coerce_bool(value, key)
            elif spec.kind == "float":
                clean[key] = _coerce_float(value, spec)
            elif spec.kind == "int":
                clean[key] = _coerce_int(value, spec)
            elif spec.kind == "triggerMode":
                clean[key] = _coerce_trigger_mode(value)
            elif spec.kind == "pipelineMode":
                clean[key] = _coerce_enum_mode(
                    value,
                    key,
                    PIPELINE_MODE_TEXT,
                    {"performance": 0, "perf": 0, "debug": 1},
                )
            elif spec.kind == "motionMode":
                clean[key] = _coerce_enum_mode(
                    value,
                    key,
                    MOTION_MODE_TEXT,
                    {"classic": 0, "normal": 0, "neural": 1},
                )
            elif spec.kind == "classCsv":
                clean[key] = _coerce_class_csv(value)
            elif spec.kind == "path":
                clean[key] = _coerce_path(value, key)
            elif spec.kind == "serialPort":
                clean[key] = _coerce_serial_port(value)
            elif spec.kind == "keyCsv":
                clean[key] = _coerce_key_csv(value, key)
            else:
                raise ValueError(f"{key} has unsupported type")
        except ValueError as exc:
            errors[key] = str(exc)
    if errors:
        raise MobileControlError(422, "VALIDATION_ERROR", "Invalid config value", errors)
    return clean


def _json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _error_payload(exc: MobileControlError):
    error = {"code": exc.code, "message": exc.message}
    if exc.details is not None:
        error["details"] = exc.details
    return {"ok": False, "error": error}


class FastThreadingHTTPServer(ThreadingHTTPServer):
    """Avoid slow reverse-DNS lookup when binding to 0.0.0.0 on Windows."""

    daemon_threads = True

    def server_bind(self):
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        host, port = self.server_address[:2]
        self.server_name = host or "0.0.0.0"
        self.server_port = port


_LEGACY_WEB_PANEL_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Neko Web 面板</title>
  <style>
    :root {
      --bg: #07141b;
      --panel: rgba(12, 30, 38, .78);
      --panel-strong: rgba(14, 43, 53, .92);
      --line: rgba(116, 224, 211, .26);
      --text: #ecfff9;
      --muted: #91bcb7;
      --accent: #7be0c6;
      --accent2: #ffbf69;
      --danger: #ff6f7d;
      --ok: #70e59b;
      color-scheme: dark;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      font-family: "Bahnschrift", "DIN Alternate", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at 12% 8%, rgba(123, 224, 198, .18), transparent 28rem),
        radial-gradient(circle at 88% 18%, rgba(255, 191, 105, .13), transparent 24rem),
        linear-gradient(135deg, #051014 0%, #0a222c 48%, #07141b 100%);
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,.028) 1px, transparent 1px);
      background-size: 48px 48px;
      opacity: .72;
    }
    main {
      width: min(1660px, calc(100vw - 20px));
      margin: 0 auto;
      padding: 8px 0 14px;
      position: relative;
    }
    header {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      align-items: end;
      margin-bottom: 8px;
    }
    h1 {
      margin: 0;
      font-size: clamp(22px, 3vw, 38px);
      line-height: .98;
      letter-spacing: -.035em;
    }
    .subtitle { color: var(--muted); margin-top: 4px; max-width: 960px; font-size: 12px; }
    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.06);
      padding: 8px 10px;
      border-radius: 999px;
      white-space: nowrap;
    }
    .dot { width: 9px; height: 9px; border-radius: 999px; background: var(--danger); box-shadow: 0 0 18px currentColor; }
    .dot.running { background: var(--ok); }
    .top-grid {
      display: grid;
      grid-template-columns: minmax(320px, .95fr) minmax(300px, .8fr) minmax(460px, 1.25fr);
      gap: 10px;
      align-items: start;
    }
    .card {
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(12, 30, 38, .88);
      box-shadow: 0 8px 28px rgba(0,0,0,.22);
      overflow: hidden;
    }
    .card h2 {
      margin: 0;
      padding: 12px 14px 2px;
      font-size: 16px;
      letter-spacing: .02em;
    }
    .card small { display: block; color: var(--muted); padding: 0 14px 8px; font-size: 12px; }
    .toolbar {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      padding: 10px 14px 12px;
    }
    button {
      border: 0;
      color: #062019;
      background: var(--accent);
      border-radius: 10px;
      padding: 9px 12px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }
    button.secondary { color: var(--text); background: rgba(255,255,255,.08); border: 1px solid var(--line); }
    button.danger { color: #22070a; background: var(--danger); }
    button:disabled { opacity: .48; cursor: not-allowed; }
    .pin-row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      padding: 10px 14px;
      background: rgba(0,0,0,.16);
      border-top: 1px solid rgba(255,255,255,.06);
    }
    input, select {
      width: 100%;
      color: var(--text);
      background: rgba(2, 12, 16, .68);
      border: 1px solid rgba(145, 188, 183, .32);
      border-radius: 10px;
      padding: 8px 10px;
      font: inherit;
      outline: none;
    }
    input:focus, select:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(123,224,198,.13); }
    .section { padding: 2px 12px 12px; }
    .section-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin: 10px 0 6px;
      color: var(--accent2);
      text-transform: uppercase;
      letter-spacing: .09em;
      font-size: 12px;
      font-weight: 800;
    }
    .tabs {
      display: flex;
      gap: 6px;
      overflow-x: auto;
      padding: 8px 12px 0;
      scrollbar-width: thin;
    }
    .tab {
      flex: 0 0 auto;
      color: var(--text);
      background: rgba(255,255,255,.06);
      border: 1px solid rgba(145,188,183,.22);
      padding: 7px 10px;
      border-radius: 999px;
      font-size: 12px;
    }
    .tab.active {
      color: #062019;
      background: var(--accent);
      border-color: transparent;
    }
    .config-card { content-visibility: auto; contain-intrinsic-size: 520px; }
    .fields { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
    .field {
      display: grid;
      gap: 6px;
      padding: 8px;
      border-radius: 12px;
      background: rgba(255,255,255,.055);
      border: 1px solid rgba(255,255,255,.06);
    }
    .field label {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      color: var(--muted);
      font-size: 12px;
    }
    .field b { color: var(--text); font-size: 12px; }
    input[type="range"] { padding: 0; accent-color: var(--accent); }
    .bool-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
    .switch { width: 22px; height: 22px; accent-color: var(--accent); }
    .log {
      height: clamp(160px, 22vh, 260px);
      overflow: auto;
      margin: 0 10px 10px;
      padding: 9px;
      border-radius: 12px;
      background: rgba(0,0,0,.34);
      color: #cce8e2;
      font-family: "Cascadia Mono", "Consolas", monospace;
      font-size: 12px;
      white-space: pre-wrap;
      border: 1px solid rgba(255,255,255,.06);
    }
    .toast {
      min-height: 22px;
      padding: 0 14px 10px;
      color: var(--muted);
    }
    .toast.error { color: var(--danger); }
    @media (max-width: 1280px) {
      .top-grid { grid-template-columns: 1fr 1fr; }
      .top-grid .log-card { grid-column: 1 / -1; }
      .fields { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
    @media (max-width: 860px) {
      header, .top-grid { grid-template-columns: 1fr; }
      .top-grid .log-card { grid-column: auto; }
      .fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .status-pill { justify-self: start; }
    }
    @media (max-width: 560px) {
      .fields { grid-template-columns: 1fr; }
      .pin-row { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Neko Web 面板</h1>
        <div class="subtitle">PC 侧 Web 面板。电脑访问 127.0.0.1，手机访问电脑局域网地址，配置直接写入当前 Neko 运行链路。</div>
      </div>
      <div class="status-pill"><span id="runDot" class="dot"></span><span id="runText">连接中</span></div>
    </header>

    <div class="top-grid">
      <section class="card">
        <h2>访问</h2>
        <small>局域网设备必须带 PIN 才能读写参数。</small>
        <div class="pin-row">
          <input id="pinInput" autocomplete="one-time-code" placeholder="输入 PIN" />
          <button id="connectBtn" class="secondary">连接</button>
        </div>
        <div id="toast" class="toast"></div>
      </section>

      <section class="card">
        <h2>运行</h2>
        <small id="runtimeMeta">等待状态...</small>
        <div class="toolbar">
          <button id="startBtn">启动推理</button>
          <button id="stopBtn" class="danger">停止推理</button>
          <button id="refreshBtn" class="secondary">刷新</button>
        </div>
      </section>

      <section class="card log-card">
        <h2>日志</h2>
        <small>最近 160 行面板/核心日志。</small>
        <pre id="logs" class="log">暂无日志。</pre>
      </section>
    </div>

    <section class="card config-card" style="margin-top:10px">
      <h2>实时参数</h2>
      <small>热更新项可直接写入；模型、引擎、ROI 等非热更新项需先停止推理。</small>
      <div id="configTabs" class="tabs" role="tablist" aria-label="参数分组"></div>
      <div id="configRoot" class="section"></div>
    </section>
  </main>
  <script>
    const pinInput = document.getElementById("pinInput");
    const toast = document.getElementById("toast");
    const configTabs = document.getElementById("configTabs");
    const configRoot = document.getElementById("configRoot");
    const logs = document.getElementById("logs");
    const runDot = document.getElementById("runDot");
    const runText = document.getElementById("runText");
    const runtimeMeta = document.getElementById("runtimeMeta");
    const pending = new Map();
    let state = null;
    let pollTimer = null;
    let activeGroupName = "";
    let configRenderToken = 0;

    function getPin() {
      return pinInput.value.trim();
    }

    function setToast(message, isError = false) {
      toast.textContent = message || "";
      toast.className = isError ? "toast error" : "toast";
    }

    function withPin(path) {
      const url = new URL(path, window.location.href);
      url.searchParams.set("pin", getPin());
      return url.toString();
    }

    async function api(path, options = {}) {
      const response = await fetch(withPin(path), {
        ...options,
        headers: {"Content-Type": "application/json", ...(options.headers || {})}
      });
      const body = await response.json();
      if (!response.ok || !body.ok) {
        const error = body.error || {message: "请求失败"};
        throw new Error(error.message + (error.details ? ": " + JSON.stringify(error.details) : ""));
      }
      return body.data;
    }

    function formatValue(value, precision) {
      if (typeof value !== "number") return value ?? "";
      if (typeof precision === "number") return value.toFixed(precision);
      return String(value);
    }

    function groupedSchema(schema) {
      const groups = [];
      for (const field of schema || []) {
        let group = groups.find(item => item.name === field.group);
        if (!group) {
          group = {name: field.group, fields: []};
          groups.push(group);
        }
        group.fields.push(field);
      }
      return groups;
    }

    function runWhenIdle(callback) {
      if ("requestIdleCallback" in window) {
        window.requestIdleCallback(callback, {timeout: 160});
        return;
      }
      setTimeout(callback, 0);
    }

    function chooseDefaultGroup(groups) {
      for (const name of ["基础", "瞄准", "扳机", "稳定", "运行", "输入", "文件", "压枪"]) {
        if (groups.some(group => group.name === name)) return name;
      }
      return groups[0]?.name || "";
    }

    function schedulePatch(key, value) {
      clearTimeout(pending.get(key));
      pending.set(key, setTimeout(async () => {
        pending.delete(key);
        try {
          state = await api("/api/config", {method: "PATCH", body: JSON.stringify({[key]: value})});
          renderState(false);
          setToast("已写入: " + key);
        } catch (err) {
          setToast(err.message, true);
        }
      }, 120));
    }

    function renderField(field) {
      const value = state?.config?.[field.key];
      const locked = !!state?.runtime?.isPipelineRunning && field.hot === false;
      const wrap = document.createElement("div");
      wrap.className = "field";
      const label = document.createElement("label");
      label.innerHTML = `<span>${field.label}${locked ? "（请先停止）" : ""}</span><b>${formatValue(value, field.precision)}</b>`;
      wrap.appendChild(label);

      if (field.kind === "bool") {
        const row = document.createElement("div");
        row.className = "bool-row";
        const hint = document.createElement("span");
        hint.textContent = value ? "已开启" : "已关闭";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.className = "switch";
        input.dataset.fieldKey = field.key;
        input.checked = !!value;
        input.disabled = locked;
        input.addEventListener("change", () => schedulePatch(field.key, input.checked));
        row.append(hint, input);
        wrap.appendChild(row);
        return wrap;
      }

      if (field.kind === "triggerMode" || field.kind === "pipelineMode" || field.kind === "motionMode") {
        const select = document.createElement("select");
        for (const choice of field.choices || []) {
          const option = document.createElement("option");
          option.value = choice.value;
          option.textContent = choice.label;
          option.selected = choice.label === value;
          select.appendChild(option);
        }
        select.disabled = locked;
        select.addEventListener("change", () => schedulePatch(field.key, Number(select.value)));
        wrap.appendChild(select);
        return wrap;
      }

      if (field.kind === "classCsv" || field.kind === "path" || field.kind === "serialPort" || field.kind === "keyCsv") {
        const input = document.createElement("input");
        input.value = value ?? "";
        input.disabled = locked;
        input.placeholder = field.kind === "classCsv" ? "0,1,3" : "";
        if (field.kind === "path") {
          const listId = field.key + "Candidates";
          input.setAttribute("list", listId);
          const dataList = document.createElement("datalist");
          dataList.id = listId;
          const candidates = field.key === "model_path"
            ? (state?.files?.modelCandidates || [])
            : (state?.files?.engineCandidates || []);
          for (const item of candidates) {
            const option = document.createElement("option");
            option.value = item.path;
            option.label = item.name || item.path;
            dataList.appendChild(option);
          }
          wrap.appendChild(dataList);
        }
        input.addEventListener("change", () => schedulePatch(field.key, input.value));
        wrap.appendChild(input);
        return wrap;
      }

      const number = document.createElement("input");
      number.type = "number";
      number.value = value ?? "";
      number.disabled = locked;
      if (field.min !== undefined) number.min = field.min;
      if (field.max !== undefined) number.max = field.max;
      if (field.step !== undefined) number.step = field.step;
      number.addEventListener("change", () => schedulePatch(field.key, number.value));
      wrap.appendChild(number);

      if (field.min !== undefined && field.max !== undefined) {
        const range = document.createElement("input");
        range.type = "range";
        range.min = field.min;
        range.max = field.max;
        range.step = field.step || 1;
        range.value = value ?? field.min;
        range.disabled = locked;
        range.addEventListener("input", () => {
          number.value = range.value;
          label.querySelector("b").textContent = range.value;
          schedulePatch(field.key, range.value);
        });
        wrap.appendChild(range);
      }
      return wrap;
    }

    function renderConfigGroups() {
      const groups = groupedSchema(state?.schema);
      configTabs.replaceChildren();
      configRoot.replaceChildren();
      if (!groups.length) {
        configRoot.textContent = "暂无可调参数。";
        return;
      }
      if (!groups.some(group => group.name === activeGroupName)) {
        activeGroupName = chooseDefaultGroup(groups);
      }

      const tabFragment = document.createDocumentFragment();
      for (const group of groups) {
        const tab = document.createElement("button");
        tab.type = "button";
        tab.className = group.name === activeGroupName ? "tab active" : "tab";
        tab.setAttribute("role", "tab");
        tab.setAttribute("aria-selected", String(group.name === activeGroupName));
        tab.textContent = `${group.name} ${group.fields.length}`;
        tab.addEventListener("click", () => {
          activeGroupName = group.name;
          renderConfigGroups();
        });
        tabFragment.appendChild(tab);
      }
      configTabs.appendChild(tabFragment);

      const group = groups.find(item => item.name === activeGroupName) || groups[0];
      const title = document.createElement("div");
      title.className = "section-title";
      title.textContent = `${group.name} · ${group.fields.length} 项`;
      const fields = document.createElement("div");
      fields.className = "fields";
      const fieldFragment = document.createDocumentFragment();
      for (const field of group.fields) fieldFragment.appendChild(renderField(field));
      fields.appendChild(fieldFragment);
      configRoot.append(title, fields);
    }

    function scheduleConfigRender() {
      const token = ++configRenderToken;
      configRoot.setAttribute("aria-busy", "true");
      if (!configRoot.childElementCount) {
        configRoot.textContent = "参数加载中...";
      }
      runWhenIdle(() => {
        if (token !== configRenderToken) return;
        renderConfigGroups();
        configRoot.removeAttribute("aria-busy");
      });
    }

    function renderState(rebuildConfig = true) {
      const running = !!state?.runtime?.isPipelineRunning;
      runDot.className = running ? "dot running" : "dot";
      runText.textContent = running ? "推理运行中" : "推理已停止";
      runtimeMeta.textContent = [
        state?.runtime?.statusModeText || "模式: --",
        state?.runtime?.fpsMetricText || "FPS: --",
        state?.runtime?.latencyMetricText || "延迟: --"
      ].join("  |  ");
      logs.textContent = (state?.logs || []).join("\n") || "暂无日志。";
      logs.scrollTop = logs.scrollHeight;
      document.getElementById("startBtn").disabled = running;
      document.getElementById("stopBtn").disabled = !running;

      if (!rebuildConfig) return;
      scheduleConfigRender();
    }

    async function loadState(rebuild = true) {
      if (!getPin()) {
        setToast("请输入 PIN 后连接。", true);
        return;
      }
      try {
        state = await api("/api/state");
        renderState(rebuild);
        setToast("已连接 Web 面板。");
        if (!pollTimer) pollTimer = setInterval(() => loadState(false), 1400);
      } catch (err) {
        setToast(err.message, true);
      }
    }

    async function postAction(path) {
      try {
        state = await api(path, {method: "POST", body: "{}"});
        renderState(true);
      } catch (err) {
        setToast(err.message, true);
      }
    }

    document.getElementById("connectBtn").addEventListener("click", () => loadState(true));
    document.getElementById("refreshBtn").addEventListener("click", () => loadState(true));
    document.getElementById("startBtn").addEventListener("click", () => postAction("/api/pipeline/start"));
    document.getElementById("stopBtn").addEventListener("click", () => postAction("/api/pipeline/stop"));

    const urlPin = new URLSearchParams(window.location.search).get("pin") || "";
    pinInput.value = urlPin;
    if (urlPin) requestAnimationFrame(() => loadState(true));
  </script>
</body>
</html>
"""


WEB_PANEL_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Neko Web 面板</title>
  <style>
    :root {
      --bg: #071120;
      --sidebar: rgba(11, 20, 40, .94);
      --surface: rgba(11, 23, 48, .88);
      --surface2: rgba(16, 37, 78, .82);
      --field: rgba(29, 56, 88, .70);
      --line: #5ef2ff;
      --line-soft: rgba(94, 242, 255, .34);
      --accent: #5ef2ff;
      --accent2: #00ffc8;
      --text: #fbf8ff;
      --muted: #9dcbde;
      --danger: #ff6d91;
      --ok: #55f0a6;
      color-scheme: dark;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      font-family: "Microsoft YaHei UI", "Bahnschrift", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at 16% 9%, rgba(94, 242, 255, .20), transparent 24rem),
        radial-gradient(circle at 88% 12%, rgba(0, 255, 200, .13), transparent 28rem),
        linear-gradient(135deg, #071120 0%, #10254e 44%, #0a6d86 100%);
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image: linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px);
      background-size: 44px 44px;
      opacity: .5;
    }
    button, input, select { font: inherit; }
    button {
      min-height: 34px;
      border: 1px solid var(--line-soft);
      border-radius: 12px;
      color: var(--text);
      background: rgba(11, 23, 48, .86);
      font-weight: 800;
      cursor: pointer;
    }
    button.primary { color: #062019; background: var(--accent); border-color: transparent; }
    button.danger { background: linear-gradient(90deg, #5a1232, var(--danger)); border-color: rgba(255, 109, 145, .55); }
    button:disabled { cursor: not-allowed; opacity: .46; }
    input, select {
      width: 100%;
      min-height: 34px;
      color: var(--text);
      background: var(--field);
      border: 1px solid var(--line-soft);
      border-radius: 12px;
      padding: 6px 10px;
      outline: none;
    }
    input:focus, select:focus { box-shadow: 0 0 0 3px rgba(36, 220, 255, .12); }
    input[type="range"] { min-height: 20px; padding: 0; accent-color: var(--accent); }
    .shell-grid {
      position: relative;
      width: min(1460px, calc(100vw - 20px));
      min-height: 100vh;
      margin: 0 auto;
      display: grid;
      grid-template-columns: 270px minmax(0, 1fr);
      gap: 14px;
      padding: 14px 0;
    }
    .sidebar {
      position: sticky;
      top: 14px;
      height: calc(100vh - 28px);
      overflow: auto;
      border: 1px solid var(--line-soft);
      border-radius: 24px;
      background: linear-gradient(180deg, rgba(11, 20, 40, .96), rgba(11, 23, 48, .90));
      padding: 14px;
    }
    .brand {
      margin: 0;
      white-space: pre-line;
      font-size: 30px;
      line-height: 1.05;
      letter-spacing: -.04em;
    }
    .panel-label { margin: 6px 0 12px; color: var(--muted); font-size: 13px; }
    .side-card, .card {
      border: 1px solid var(--line-soft);
      border-radius: 22px;
      background: var(--surface);
    }
    .side-card { padding: 12px; margin-bottom: 12px; }
    .side-card.purple { border-color: var(--line-soft); }
    .side-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin: 0 0 8px;
      font-size: 18px;
      font-weight: 900;
    }
    .meta-list { display: grid; gap: 7px; color: var(--muted); font-size: 13px; }
    .license-box {
      display: grid;
      grid-template-columns: 58px minmax(0, 1fr);
      gap: 8px;
      align-items: center;
      margin-top: 12px;
      padding: 10px;
      border: 1px solid var(--line-soft);
      border-radius: 16px;
      background: rgba(255,255,255,.045);
    }
    .badge {
      display: inline-flex;
      justify-content: center;
      align-items: center;
      min-height: 28px;
      border-radius: 10px;
      border: 1px solid rgba(0, 255, 200, .56);
      color: var(--accent2);
      font-weight: 900;
      font-size: 12px;
      background: rgba(0, 255, 200, .12);
    }
    .button-row { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; margin-top: 10px; }
    .metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; text-align: center; }
    .ring {
      display: grid;
      place-items: center;
      gap: 3px;
      min-height: 76px;
      border-radius: 17px;
      background: rgba(12, 15, 45, .58);
      border: 1px solid rgba(255,255,255,.06);
    }
    .ring b { font-size: 18px; }
    .ring span { color: var(--muted); font-size: 12px; }
    .live {
      border: 1px solid var(--line-soft);
      color: var(--accent2);
      border-radius: 999px;
      padding: 4px 13px;
      font-size: 11px;
      letter-spacing: .12em;
      background: rgba(0, 255, 200, .12);
    }
    .main { min-width: 0; }
    .card {
      padding: 16px;
      margin-bottom: 14px;
      background: rgba(11, 23, 48, .88);
    }
    .card-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }
    .card h2 { margin: 0; font-size: 22px; letter-spacing: -.03em; }
    .hint { color: var(--muted); font-size: 13px; }
    .subgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-items: start; }
    .group {
      border: 1px solid var(--line-soft);
      border-radius: 19px;
      padding: 10px;
      background: rgba(13, 12, 35, .26);
    }
    .group h3 {
      display: flex;
      align-items: center;
      gap: 7px;
      margin: -4px 0 10px;
      font-size: 16px;
    }
    .help-dot {
      display: inline-grid;
      place-items: center;
      width: 18px;
      height: 18px;
      border-radius: 50%;
      border: 1px solid var(--line);
      color: var(--line);
      font-size: 12px;
    }
    .fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 10px; }
    .fields.one { grid-template-columns: 1fr; }
    .fields.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .field { display: grid; grid-template-columns: 82px minmax(0, 1fr); gap: 8px; align-items: center; }
    .field label { color: var(--muted); font-size: 12px; min-width: 0; }
    .field label b { display: block; color: var(--text); font-size: 12px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; }
    .field.control-only { grid-template-columns: 1fr; }
    .field.control-only label { display: none; }
    .field.full { grid-column: 1 / -1; }
    .bool-row { display: flex; align-items: center; gap: 9px; }
    .switch { width: 22px; min-height: 22px; accent-color: var(--accent2); }
    .wide-row { display: grid; grid-template-columns: 82px minmax(0, 1fr) 112px; gap: 10px; align-items: center; margin-bottom: 8px; }
    .wide-row.two { grid-template-columns: 82px minmax(0, 1fr); }
    .actions { display: flex; gap: 10px; flex-wrap: wrap; }
    .actions button { min-width: 118px; padding-inline: 14px; }
    .capture-line { color: var(--accent2); font-size: 13px; margin-top: 8px; }
    .class-choice-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; }
    .class-choice {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      padding: 8px 10px;
      border: 1px solid var(--line-soft);
      border-radius: 12px;
      background: rgba(255,255,255,.045);
      color: var(--text);
      font-size: 13px;
    }
    .class-choice input { width: 18px; min-height: 18px; flex: 0 0 auto; accent-color: var(--accent2); }
    .class-choice span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .key-record-grid { display: grid; grid-template-columns: 1fr auto auto; gap: 8px; align-items: center; margin-top: 9px; }
    .key-display { min-width: 0; color: var(--muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    body.recording * { cursor: crosshair !important; }
    .log {
      min-height: 210px;
      max-height: 300px;
      overflow: auto;
      margin: 0;
      padding: 12px;
      border-radius: 14px;
      border: 1px solid rgba(255,255,255,.08);
      background: rgba(0,0,0,.32);
      color: #dfefff;
      font: 12px/1.45 "Cascadia Mono", Consolas, monospace;
      white-space: pre-wrap;
      user-select: text;
    }
    .log a { color: var(--accent2); text-decoration: underline; user-select: all; }
    .copy-line {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      margin-top: 9px;
    }
    .copy-line input {
      min-width: 0;
      height: 34px;
      padding: 0 10px;
      border-radius: 10px;
      border: 1px solid rgba(255,255,255,.12);
      background: rgba(0,0,0,.22);
      color: var(--text);
      font: 12px "Cascadia Mono", Consolas, monospace;
    }
    .copy-line button { min-height: 34px; padding: 0 10px; }
    .toast { min-height: 24px; color: var(--muted); font-size: 13px; }
    .toast.error { color: var(--danger); }
    @media (max-width: 1180px) {
      .shell-grid { grid-template-columns: 1fr; padding: 10px; }
      .sidebar { position: relative; top: 0; height: auto; }
    }
    @media (max-width: 860px) {
      .subgrid, .fields, .fields.three, .wide-row, .wide-row.two { grid-template-columns: 1fr; }
      .field { grid-template-columns: 1fr; gap: 4px; }
      .brand { font-size: 32px; }
      .card h2 { font-size: 24px; }
    }
  </style>
</head>
<body>
  <main class="shell-grid">
    <aside class="sidebar" aria-label="控制面板侧栏">
      <h1 class="brand" aria-label="TRT Quantum">TRT
Quantum</h1>
      <div class="panel-label">控制面板</div>

      <section class="side-card">
        <h2 class="side-title">运行状态</h2>
        <div class="meta-list">
          <div id="runStateText">推理已停止 / 推理运行中时请先停止再改非热更新项</div>
          <div id="statusMode">模式: 连接中</div>
          <div id="statusModel">模型: --</div>
          <div id="statusEngine">引擎: --</div>
          <div id="statusBackground">背景: --</div>
        </div>
        <div class="license-box">
          <div id="licenseBadge" class="badge">检查中</div>
          <div class="meta-list">
            <strong id="licenseExpiry">--</strong>
            <span id="licenseRemain">正在刷新</span>
          </div>
        </div>
      </section>

      <section class="side-card purple">
        <h2 class="side-title">Update</h2>
        <div class="meta-list">
          <div id="updateStatus">更新: 未检查</div>
          <div id="updateVersions">Local: -- / Latest: --</div>
        </div>
        <div class="button-row">
          <button id="checkUpdateBtn">Check</button>
          <button id="applyUpdateBtn" class="primary">Apply</button>
        </div>
      </section>

      <section class="side-card">
        <h2 class="side-title">系统监控 <span class="live">LIVE</span></h2>
        <div class="metrics">
          <div class="ring"><b id="cpuRing">--</b><span>CPU</span></div>
          <div class="ring"><b id="gpuRing">--</b><span>GPU</span></div>
          <div class="ring"><b id="memRing">--</b><span>内存</span></div>
        </div>
        <div class="meta-list" style="margin-top:10px">
          <div id="latencyLine">推理延迟: --</div>
          <div id="fpsLine">帧率: --</div>
        </div>
      </section>

      <section class="side-card purple">
        <h2 class="side-title">Web 面板</h2>
        <div class="pin-row">
          <input id="pinInput" autocomplete="one-time-code" placeholder="输入 PIN" />
          <button id="connectBtn">连接</button>
        </div>
        <div class="button-row">
          <button id="closeWebBtn" class="danger">关闭 Web 面板</button>
        </div>
        <div class="copy-line">
          <input id="mobileUrlInput" readonly value="" placeholder="连接后显示手机访问地址" />
          <button id="copyMobileUrlBtn" class="ghost" type="button">复制</button>
        </div>
        <div id="toast" class="toast"></div>
      </section>
    </aside>

    <section class="main">
      <section class="card config-card">
        <h2>模型编译</h2>
        <div class="wide-row">
          <label>模型路径</label>
          <div id="modelPathField"></div>
          <button id="browseModelBtn">浏览模型</button>
        </div>
        <div class="wide-row">
          <label>结构预览</label>
          <button id="netronBtn">查看结构</button>
          <span class="hint">可手输路径，也可在本机弹出文件选择框。</span>
        </div>
        <div class="wide-row">
          <label>输入尺寸</label>
          <div id="imgszField"></div>
          <button id="convertBtn" class="primary">编译 TexPre FP16</button>
        </div>
      </section>

      <section class="card config-card">
        <h2>运行控制</h2>
        <div class="wide-row">
          <label>引擎文件</label>
          <div id="enginePathField"></div>
          <button id="browseEngineBtn">浏览引擎</button>
        </div>
        <div id="modelInfoText" class="hint" style="margin-bottom:12px">模型信息: 未解析</div>
        <div class="actions" style="margin-bottom:14px">
          <button id="startBtn" class="primary">启动推理</button>
          <button id="stopBtn" class="danger">停止推理</button>
          <button id="refreshBtn">刷新</button>
        </div>

        <div class="subgrid">
          <div>
            <div class="group">
              <h3>基础参数 <span class="help-dot">?</span></h3>
              <div id="basicFields" class="fields"></div>
              <div class="capture-line">采集链路: ROI CopySubresourceRegion (仅复制中心 ROI)</div>
            </div>
            <div class="group" style="margin-top:14px">
              <h3>自瞄参数 <span class="help-dot">?</span></h3>
              <div id="aimFields" class="fields"></div>
            </div>
            <div class="group" style="margin-top:14px">
              <h3>目标类别 <span class="help-dot">?</span></h3>
              <div id="classChoiceList" class="class-choice-list"></div>
              <input id="selectedClassesHidden" data-field-key="selected_classes_text" type="hidden" />
            </div>
            <div class="group" style="margin-top:14px">
              <h3>触发按键 <span class="help-dot">?</span></h3>
              <div id="keyFields" class="fields"></div>
              <div class="key-record-grid">
                <div class="key-display">自瞄键: <span id="aimKeyDisplay">右键 (VK:2)</span></div>
                <button id="recordAimBtn">录入</button>
                <button id="resetAimBtn">重置</button>
                <div class="key-display">扳机键: <span id="triggerKeyDisplay">左键 (VK:1)</span></div>
                <button id="recordTriggerBtn">录入</button>
                <button id="resetTriggerBtn">重置</button>
              </div>
            </div>
          </div>

          <div>
            <div class="group">
              <h3>扳机、粘性与压枪 <span class="help-dot">?</span></h3>
              <div id="triggerFields" class="fields"></div>
              <div id="stabilityFields" class="fields" style="margin-top:10px"></div>
              <div id="recoilFields" class="fields" style="margin-top:10px"></div>
            </div>
            <div class="group" style="margin-top:14px">
              <h3>ESP32 串口 <span class="help-dot">?</span></h3>
              <div id="inputFields" class="fields"></div>
              <div id="esp32Status" class="hint" style="margin-top:9px">ESP32 检测: 未执行</div>
              <div class="actions" style="margin-top:10px">
                <button id="esp32RefreshBtn">刷新串口</button>
                <button id="esp32AutoBtn">自动检测</button>
                <button id="esp32ProbeBtn">测试连接</button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <h2>日志</h2>
          <span class="hint">最近 160 行面板/核心日志</span>
        </div>
        <pre id="logs" class="log">暂无日志。</pre>
      </section>
    </section>
  </main>

  <script>
    const $ = (id) => document.getElementById(id);
    const pinInput = $("pinInput");
    const toast = $("toast");
    const logs = $("logs");
    const mobileUrlInput = $("mobileUrlInput");
    const copyMobileUrlBtn = $("copyMobileUrlBtn");
    const pending = new Map();
    const pendingValues = new Map();
    let state = null;
    let schemaByKey = new Map();
    let pollTimer = null;
    let heartbeatTimer = null;
    let configRenderToken = 0;
    let classPatchSerial = 0;
    let recordingTarget = "";
    let recordingKeys = [];
    let recordingMouseSuppressUntil = 0;
    const clientId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;

    function getPin() { return pinInput.value.trim(); }
    function setToast(message, isError = false) {
      toast.textContent = message || "";
      toast.className = isError ? "toast error" : "toast";
    }
    async function copyText(text) {
      const value = String(text || "").trim();
      if (!value) {
        setToast("暂无可复制的地址。", true);
        return;
      }
      try {
        await navigator.clipboard.writeText(value);
      } catch (_) {
        mobileUrlInput.focus();
        mobileUrlInput.select();
        document.execCommand("copy");
      }
      setToast("已复制手机访问地址。");
    }
    function withPin(path) {
      const url = new URL(path, window.location.href);
      url.searchParams.set("pin", getPin());
      return url.toString();
    }
    async function api(path, options = {}) {
      const response = await fetch(withPin(path), {
        ...options,
        headers: {"Content-Type": "application/json", ...(options.headers || {})}
      });
      const body = await response.json();
      if (!response.ok || !body.ok) {
        const error = body.error || {message: "请求失败"};
        throw new Error(error.message + (error.details ? ": " + JSON.stringify(error.details) : ""));
      }
      return body.data;
    }
    function runWhenIdle(callback) {
      if ("requestIdleCallback" in window) {
        window.requestIdleCallback(callback, {timeout: 180});
        return;
      }
      setTimeout(callback, 0);
    }
    function formatValue(value, precision) {
      if (typeof value !== "number") return value ?? "";
      return typeof precision === "number" ? value.toFixed(precision) : String(value);
    }
    function metricText(value) {
      return typeof value === "number" && value >= 0 ? `${Math.round(value)}` : "--";
    }
    function renderLogs(lines) {
      const list = Array.isArray(lines) ? lines : [];
      logs.replaceChildren();
      const text = list.length ? list.join("\n") : "暂无日志。";
      const pattern = /(https?:\/\/[^\s<>"']+)/g;
      let cursor = 0;
      for (const match of text.matchAll(pattern)) {
        if (match.index > cursor) logs.appendChild(document.createTextNode(text.slice(cursor, match.index)));
        const link = document.createElement("a");
        link.href = match[0];
        link.textContent = match[0];
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.title = "点击打开，右键可复制链接";
        logs.appendChild(link);
        cursor = match.index + match[0].length;
      }
      if (cursor < text.length) logs.appendChild(document.createTextNode(text.slice(cursor)));
      logs.scrollTop = logs.scrollHeight;
    }
    function controlValue(control, field) {
      if (control.type === "checkbox") return control.checked;
      if (field?.choices) return Number(control.value);
      return control.value;
    }
    function pendingConfigValue(key, fallback) {
      return pendingValues.has(key) ? pendingValues.get(key) : fallback;
    }
    function collectConfigFromDom() {
      const config = {...(state?.config || {})};
      document.querySelectorAll("[data-field-key]").forEach((control) => {
        const key = control.dataset.fieldKey;
        const field = schemaByKey.get(key);
        if (!field) return;
        config[key] = controlValue(control, field);
      });
      for (const [pendingKey, pendingValue] of pendingValues) config[pendingKey] = pendingValue;
      return config;
    }
    function syncConfigControlsFromState() {
      if (!state?.config) return;
      const running = !!state?.runtime?.isPipelineRunning;
      document.querySelectorAll("[data-field-key]").forEach((control) => {
        const key = control.dataset.fieldKey;
        const field = schemaByKey.get(key);
        if (!field) return;
        const value = state.config[key];
        const locked = running && field.hot === false;
        control.disabled = locked;
        if (control.type === "checkbox") {
          control.checked = !!value;
          const hint = control.closest(".bool-row")?.querySelector("span");
          if (hint) hint.textContent = value ? "已开启" : "已关闭";
        } else if (control.tagName === "SELECT") {
          for (const option of control.options) {
            option.selected = option.textContent === value || String(option.value) === String(value);
          }
        } else {
          control.value = value ?? "";
        }
        const labelValue = control.closest(".field")?.querySelector("label b");
        if (labelValue) labelValue.textContent = formatValue(value, field.precision);
        const range = control.parentElement?.querySelector('input[type="range"]');
        if (range) {
          range.disabled = locked;
          range.value = value ?? field.min ?? "";
        }
      });
      renderClassChoices();
    }
    function shouldRebuildConfigAfterAction(action) {
      return false;
    }
    function schedulePatch(key, value) {
      pendingValues.set(key, value);
      clearTimeout(pending.get(key));
      pending.set(key, setTimeout(async () => {
        pending.delete(key);
        const submittedValue = pendingValues.get(key);
        try {
          state = await api("/api/config", {method: "PATCH", body: JSON.stringify({[key]: submittedValue})});
          if (pendingValues.get(key) === submittedValue) pendingValues.delete(key);
          renderState(false);
          setToast("已写入: " + key);
        } catch (err) {
          setToast(err.message, true);
        }
      }, 120));
    }
    async function commitClassSelection(value) {
      const text = String(value || "0").split(",").map(item => item.trim()).filter(Boolean).join(",") || "0";
      const serial = ++classPatchSerial;
      pendingValues.set("selected_classes_text", text);
      clearTimeout(pending.get("selected_classes_text"));
      pending.delete("selected_classes_text");
      const hidden = $("selectedClassesHidden");
      if (hidden) hidden.value = text;
      if (state?.config) state.config = {...state.config, selected_classes_text: text};
      renderClassChoices();
      try {
        const nextState = await api("/api/config", {method: "PATCH", body: JSON.stringify({selected_classes_text: text})});
        if (serial !== classPatchSerial) return;
        state = nextState;
        if (pendingValues.get("selected_classes_text") === text) pendingValues.delete("selected_classes_text");
        renderState(false);
        setToast("宸插啓鍏? selected_classes_text");
      } catch (err) {
        if (serial !== classPatchSerial) return;
        setToast(err.message, true);
      }
    }
    async function panelAction(action, payload = null) {
      const configActions = new Set(["pipeline.start", "settings.save", "model.convert", "model.netron", "esp32.auto", "esp32.probe"]);
      const actionPayload = payload !== null ? payload : (configActions.has(action) ? collectConfigFromDom() : {});
      try {
        state = await api("/api/action", {method: "POST", body: JSON.stringify({action, payload: actionPayload})});
        const rebuildConfig = shouldRebuildConfigAfterAction(action);
        renderState(rebuildConfig);
        if (!rebuildConfig) syncConfigControlsFromState();
        setToast("已执行: " + action);
      } catch (err) {
        setToast(err.message, true);
      }
    }
    function sendLifecycleAction(action, payload = {}) {
      if (!getPin()) return;
      const body = JSON.stringify({action, payload: {client_id: clientId, ...payload}});
      const url = withPin("/api/action");
      if (navigator.sendBeacon) {
        const blob = new Blob([body], {type: "application/json"});
        navigator.sendBeacon(url, blob);
        return;
      }
      fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body, keepalive: true}).catch(() => {});
    }
    async function notifyClientOpen() {
      if (!getPin()) return;
      try {
        await api("/api/action", {
          method: "POST",
          body: JSON.stringify({action: "web.client_open", payload: {client_id: clientId}})
        });
      } catch (_) {}
    }
    function notifyClientClosed(reason = "pagehide") {
      sendLifecycleAction("web.close", {reason});
    }
    function startHeartbeat() {
      if (heartbeatTimer) return;
      sendLifecycleAction("web.heartbeat");
      heartbeatTimer = setInterval(() => {
        sendLifecycleAction("web.heartbeat");
      }, 2000);
    }
    async function closeWebPanel() {
      sendLifecycleAction("web.shutdown", {reason: "button"});
      setToast("正在关闭 Web 面板和推理核心...");
      window.setTimeout(() => window.close(), 120);
    }
    function beginKeyRecord(target) {
      recordingTarget = target;
      recordingKeys = [];
      recordingMouseSuppressUntil = Date.now() + 5000;
      document.body.classList.add("recording");
      setToast(`${target === "aim" ? "自瞄键" : "扳机键"}录入中：按键盘/鼠标，ESC 取消`);
    }
    function cancelKeyRecord() {
      recordingTarget = "";
      recordingKeys = [];
      recordingMouseSuppressUntil = Date.now() + 350;
      document.body.classList.remove("recording");
      setToast("已取消按键录入。");
    }
    function addRecordedKey(vk) {
      if (!recordingTarget || !vk || vk < 1 || vk > 255) return;
      const text = String(vk);
      if (!recordingKeys.includes(text)) recordingKeys.push(text);
      recordingMouseSuppressUntil = Date.now() + 5000;
      setToast(`Recorded: ${recordingKeys.join(" + ")}. Press ESC to save.`);
    }
    function commitKeyRecord() {
      const target = recordingTarget;
      if (!target) return;
      const fallback = target === "aim" ? "2" : "1";
      if (!recordingKeys.length) recordingKeys.push(fallback);
      recordingTarget = "";
      recordingMouseSuppressUntil = Date.now() + 450;
      document.body.classList.remove("recording");
      panelAction(target === "aim" ? "keys.record_aim" : "keys.record_trigger", {keys: recordingKeys});
      recordingKeys = [];
    }
    function swallowRecordingEvent(event) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
    }
    function handleRecordingPointerEvent(event) {
      if (!recordingTarget && Date.now() > recordingMouseSuppressUntil) return;
      swallowRecordingEvent(event);
      if (!recordingTarget) return;
      if (!["pointerdown", "mousedown"].includes(event.type)) return;
      const mouseVk = {0: 1, 1: 4, 2: 2, 3: 5, 4: 6}[event.button];
      addRecordedKey(mouseVk || 0);
    }
    document.addEventListener("keydown", (event) => {
      if (!recordingTarget) return;
      swallowRecordingEvent(event);
      if (event.key === "Escape") {
        commitKeyRecord();
        return;
      }
      addRecordedKey(event.keyCode || event.which || 0);
    }, true);
    document.addEventListener("pointerdown", handleRecordingPointerEvent, true);
    document.addEventListener("pointerup", handleRecordingPointerEvent, true);
    document.addEventListener("mousedown", handleRecordingPointerEvent, true);
    document.addEventListener("mouseup", handleRecordingPointerEvent, true);
    document.addEventListener("auxclick", handleRecordingPointerEvent, true);
    document.addEventListener("contextmenu", handleRecordingPointerEvent, true);
    function makeDatalist(wrap, field) {
      if (field.key !== "model_path" && field.key !== "engine_path") return "";
      const listId = `${field.key}Candidates`;
      const dataList = document.createElement("datalist");
      dataList.id = listId;
      const candidates = field.key === "model_path" ? state?.files?.modelCandidates || [] : state?.files?.engineCandidates || [];
      for (const item of candidates) {
        const option = document.createElement("option");
        option.value = item.path;
        option.label = item.name || item.path;
        dataList.appendChild(option);
      }
      wrap.appendChild(dataList);
      return listId;
    }
    function parseClassItems() {
      const selectedText = pendingConfigValue("selected_classes_text", state?.config?.selected_classes_text || "0");
      const selected = new Set(String(selectedText || "0").split(",").map(item => item.trim()).filter(Boolean));
      const lines = String(state?.model?.availableClassesText || "").split(/\r?\n/).map(item => item.trim()).filter(Boolean);
      const fallbackIds = [...selected, ...Array.from({length: 80}, (_, index) => String(index))];
      const classSource = lines.length ? lines : Array.from(new Set(fallbackIds)).map(id => `${id} - class_${id}`);
      return classSource.map((item, index) => {
        const match = String(item).match(/^\s*(\d+)/);
        const classId = match ? match[1] : String(index);
        return {
          id: classId || String(index),
          label: item,
          checked: selected.size ? selected.has(classId) : index === 0,
        };
      });
    }
    function renderClassChoices() {
      const target = $("classChoiceList");
      if (!target) return;
      target.replaceChildren();
      for (const item of parseClassItems()) {
        const label = document.createElement("label");
        label.className = "class-choice";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.dataset.classId = item.id;
        checkbox.checked = item.checked;
        checkbox.addEventListener("change", () => {
          const values = Array.from(target.querySelectorAll("input[data-class-id]:checked"))
            .map(input => input.dataset.classId)
            .filter(Boolean);
          const next = values.length ? values.join(",") : item.id;
          if (!values.length) checkbox.checked = true;
          const hidden = $("selectedClassesHidden");
          if (hidden) hidden.value = next;
          if (state?.config) state.config = {...state.config, selected_classes_text: next};
          commitClassSelection(next);
        });
        const text = document.createElement("span");
        text.textContent = item.label;
        label.append(checkbox, text);
        target.appendChild(label);
      }
      const hidden = $("selectedClassesHidden");
      if (hidden) hidden.value = pendingConfigValue("selected_classes_text", state?.config?.selected_classes_text || "0");
    }
    function renderField(field, options = {}) {
      const value = state?.config?.[field.key];
      const locked = !!state?.runtime?.isPipelineRunning && field.hot === false;
      const wrap = document.createElement("div");
      wrap.className = `field ${options.full ? "full" : ""} ${options.controlOnly ? "control-only" : ""}`.trim();
      const label = document.createElement("label");
      const name = document.createElement("span");
      name.textContent = field.label + (locked ? "（请先停止）" : "");
      const current = document.createElement("b");
      current.textContent = formatValue(value, field.precision);
      label.append(name, current);
      wrap.appendChild(label);

      if (field.kind === "bool") {
        const row = document.createElement("div");
        row.className = "bool-row";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.className = "switch";
        input.dataset.fieldKey = field.key;
        input.checked = !!value;
        input.disabled = locked;
        const hint = document.createElement("span");
        hint.textContent = value ? "已开启" : "已关闭";
        input.addEventListener("change", () => schedulePatch(field.key, input.checked));
        row.append(input, hint);
        wrap.appendChild(row);
        return wrap;
      }

      if (field.choices) {
        const select = document.createElement("select");
        select.dataset.fieldKey = field.key;
        for (const choice of field.choices) {
          const option = document.createElement("option");
          option.value = choice.value;
          option.textContent = choice.label;
          option.selected = choice.label === value || choice.value === value;
          select.appendChild(option);
        }
        select.disabled = locked;
        select.addEventListener("change", () => {
          schedulePatch(field.key, Number(select.value));
        });
        wrap.appendChild(select);
        return wrap;
      }

      if (["classCsv", "path", "serialPort", "keyCsv"].includes(field.kind)) {
        const input = document.createElement("input");
        input.dataset.fieldKey = field.key;
        input.value = value ?? "";
        input.disabled = locked;
        input.placeholder = field.kind === "classCsv" ? "0,1,3" : "";
        const listId = makeDatalist(wrap, field);
        if (listId) input.setAttribute("list", listId);
        input.addEventListener("change", () => schedulePatch(field.key, input.value));
        wrap.appendChild(input);
        return wrap;
      }

      const number = document.createElement("input");
      number.type = "number";
      number.dataset.fieldKey = field.key;
      number.value = value ?? "";
      number.disabled = locked;
      if (field.min !== undefined) number.min = field.min;
      if (field.max !== undefined) number.max = field.max;
      if (field.step !== undefined) number.step = field.step;
      number.addEventListener("change", () => schedulePatch(field.key, number.value));
      number.addEventListener("wheel", (event) => {
        adjustNumberByWheel(event, number, field, current);
      }, {passive: false});
      wrap.appendChild(number);
      if (field.min !== undefined && field.max !== undefined) {
        const range = document.createElement("input");
        range.type = "range";
        range.min = field.min;
        range.max = field.max;
        range.step = field.step || 1;
        range.value = value ?? field.min;
        range.disabled = locked;
        range.addEventListener("input", () => {
          number.value = range.value;
          current.textContent = range.value;
          schedulePatch(field.key, range.value);
        });
        wrap.appendChild(range);
      }
      return wrap;
    }
    function decimalPlaces(value) {
      const text = String(value ?? "");
      return text.includes(".") ? text.split(".")[1].length : 0;
    }
    function clampNumber(value, field) {
      let next = Number(value);
      if (!Number.isFinite(next)) next = 0;
      if (field.min !== undefined) next = Math.max(Number(field.min), next);
      if (field.max !== undefined) next = Math.min(Number(field.max), next);
      return next;
    }
    function adjustNumberByWheel(event, input, field, currentLabel) {
      if (input.disabled || document.activeElement !== input) return;
      event.preventDefault();
      const step = Number(field.step || input.step || 1) || 1;
      const direction = event.deltaY < 0 ? 1 : -1;
      const precision = Math.max(decimalPlaces(step), Number(field.precision || 0));
      const currentValue = input.value === "" ? Number(state?.config?.[field.key] ?? 0) : Number(input.value);
      const next = clampNumber((Number.isFinite(currentValue) ? currentValue : 0) + direction * step, field);
      const text = precision > 0 ? next.toFixed(precision) : String(Math.round(next));
      input.value = text;
      currentLabel.textContent = text;
      const range = input.parentElement?.querySelector('input[type="range"]');
      if (range) range.value = text;
      schedulePatch(field.key, text);
    }
    function renderFields(targetId, keys, options = {}) {
      const target = $(targetId);
      target.replaceChildren();
      for (const key of keys) {
        const field = schemaByKey.get(key);
        if (field) target.appendChild(renderField(field, options[key] || {}));
      }
    }
    function renderConfig() {
      schemaByKey = new Map((state?.schema || []).map(field => [field.key, field]));
      renderFields("modelPathField", ["model_path"], {model_path: {controlOnly: true}});
      renderFields("imgszField", ["imgsz"], {imgsz: {controlOnly: true}});
      renderFields("enginePathField", ["engine_path"], {engine_path: {controlOnly: true}});
      renderFields("basicFields", ["roi", "conf", "nms", "fps_limit", "pipeline_mode", "motion_mode"]);
      renderFields("aimFields", ["pid_p", "pid_i", "pid_d", "y_offset", "neural_curvature", "neural_tremor"]);
      renderClassChoices();
      renderFields("keyFields", ["aim_keys", "trigger_keys"]);
      renderFields("triggerFields", ["trigger_mode", "trigger_delay", "trigger_hitbox_enter_scale", "trigger_hitbox_exit_scale", "trigger_hold_grace_ms"]);
      renderFields("stabilityFields", ["kalman_en", "kalman_pred"]);
      renderFields("recoilFields", ["recoil_en", "trigger_recoil_en", "recoil_strength", "recoil_delay"]);
      renderFields("inputFields", ["lghub_enabled", "esp32_enabled", "esp32_port", "esp32_baud"]);
    }
    function scheduleConfigRender() {
      const token = ++configRenderToken;
      for (const id of ["basicFields"]) $(id).textContent = "参数加载中...";
      runWhenIdle(() => {
        if (token !== configRenderToken) return;
        renderConfig();
      });
    }
    function renderState(rebuildConfig = true) {
      const runtime = state?.runtime || {};
      const update = state?.update || {};
      const metrics = state?.metrics || {};
      const esp32 = state?.esp32 || {};
      const running = !!runtime.isPipelineRunning;
      $("statusMode").textContent = runtime.statusModeText || "模式: --";
      $("runStateText").textContent = running ? "推理运行中" : "推理已停止 / 非热更新项运行中请先停止";
      $("statusModel").textContent = runtime.statusModelText || "模型: --";
      $("statusEngine").textContent = runtime.statusEngineText || "引擎: --";
      $("statusBackground").textContent = runtime.backgroundStatusText || "背景: 默认渐变";
      $("licenseBadge").textContent = runtime.licenseBadgeText || "检查中";
      $("licenseExpiry").textContent = runtime.licenseExpiryCompactText || "--";
      $("licenseRemain").textContent = runtime.licenseRemainingText || "正在刷新";
      $("updateStatus").textContent = update.statusText || "更新: 未检查";
      $("updateVersions").textContent = `Local: ${update.currentVersion || "--"} / Latest: ${update.latestVersion || "--"}`;
      $("applyUpdateBtn").disabled = !update.available || update.running || running;
      $("checkUpdateBtn").disabled = !!update.running;
      $("browseModelBtn").disabled = running;
      $("browseEngineBtn").disabled = running;
      $("cpuRing").textContent = metricText(metrics.cpuUsageValue);
      $("gpuRing").textContent = metricText(metrics.gpuUsageValue);
      $("memRing").textContent = metricText(metrics.memoryUsageValue);
      $("latencyLine").textContent = runtime.latencyMetricText || "推理延迟: --";
      $("fpsLine").textContent = runtime.fpsMetricText || "帧率: --";
      $("modelInfoText").textContent = state?.model?.modelInfoText || "模型信息: 未解析";
      $("aimKeyDisplay").textContent = state?.model?.aimKeysDisplay || "右键 (VK:2)";
      $("triggerKeyDisplay").textContent = state?.model?.triggerKeysDisplay || "左键 (VK:1)";
      renderClassChoices();
      $("esp32Status").textContent = `${esp32.scanStatus || "ESP32 检测: 未执行"} / ${esp32.serialPortsText || "串口候选: 未扫描"}`;
      $("startBtn").disabled = running;
      $("stopBtn").disabled = !running;
      mobileUrlInput.value = state?.web?.url || state?.web?.localUrl || "";
      renderLogs(state?.logs);
      if (rebuildConfig) scheduleConfigRender();
    }
    async function loadState(rebuild = true) {
      if (!getPin()) {
        setToast("请输入 PIN 后连接。", true);
        return;
      }
      try {
        state = await api("/api/state");
        renderState(rebuild);
        setToast("已连接 Web 面板。");
        if (!pollTimer) pollTimer = setInterval(() => loadState(false), 1400);
        await notifyClientOpen();
        startHeartbeat();
      } catch (err) {
        setToast(err.message, true);
      }
    }
    $("connectBtn").addEventListener("click", () => loadState(true));
    $("closeWebBtn").addEventListener("click", () => closeWebPanel());
    copyMobileUrlBtn.addEventListener("click", () => copyText(mobileUrlInput.value));
    $("refreshBtn").addEventListener("click", () => loadState(true));
    $("startBtn").addEventListener("click", () => panelAction("pipeline.start"));
    $("stopBtn").addEventListener("click", () => panelAction("pipeline.stop"));
    $("convertBtn").addEventListener("click", () => panelAction("model.convert"));
    $("netronBtn").addEventListener("click", () => panelAction("model.netron"));
    $("checkUpdateBtn").addEventListener("click", () => panelAction("update.check"));
    $("applyUpdateBtn").addEventListener("click", () => panelAction("update.apply"));
    $("browseModelBtn").addEventListener("click", () => panelAction("file.browse_model"));
    $("browseEngineBtn").addEventListener("click", () => panelAction("file.browse_engine"));
    $("esp32RefreshBtn").addEventListener("click", () => panelAction("esp32.refresh"));
    $("esp32AutoBtn").addEventListener("click", () => panelAction("esp32.auto"));
    $("esp32ProbeBtn").addEventListener("click", () => panelAction("esp32.probe"));
    $("recordAimBtn").addEventListener("click", () => beginKeyRecord("aim"));
    $("recordTriggerBtn").addEventListener("click", () => beginKeyRecord("trigger"));
    $("resetAimBtn").addEventListener("click", () => panelAction("keys.reset_aim"));
    $("resetTriggerBtn").addEventListener("click", () => panelAction("keys.reset_trigger"));

    const urlPin = new URLSearchParams(window.location.search).get("pin") || "";
    pinInput.value = urlPin;
    if (urlPin) requestAnimationFrame(() => loadState(true));
    window.addEventListener("pagehide", () => notifyClientClosed("pagehide"));
    window.addEventListener("beforeunload", () => notifyClientClosed("beforeunload"));
  </script>
</body>
</html>
"""


class MobileControlServer:
    def __init__(
        self,
        state_provider,
        update_handler,
        action_handler=None,
        host="0.0.0.0",
        port=24600,
        pin=None,
    ):
        self.state_provider = state_provider
        self.update_handler = update_handler
        self.action_handler = action_handler
        self.host = host
        self.requested_port = int(port)
        self.pin = str(pin or f"{secrets.randbelow(1000000):06d}")
        self._httpd = None
        self._thread = None

    @property
    def port(self):
        if self._httpd is None:
            return self.requested_port
        return int(self._httpd.server_address[1])

    def start(self):
        if self._httpd is not None:
            return
        handler = self._make_handler()
        self._httpd = FastThreadingHTTPServer((self.host, self.requested_port), handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="NekoWebPanel", daemon=True)
        self._thread.start()

    def stop(self):
        httpd = self._httpd
        self._httpd = None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def _make_handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "NekoWebPanel/1.0"

            def log_message(self, format, *args):
                return

            def do_OPTIONS(self):
                self._send_empty(204)

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path in ("", "/"):
                    self._send_html(WEB_PANEL_HTML)
                    return
                if parsed.path == "/api/health":
                    self._send_json(200, {"ok": True, "data": {"status": "ok"}})
                    return
                if parsed.path == "/api/state":
                    self._require_pin(parsed)
                    self._send_json(200, {"ok": True, "data": owner._state()})
                    return
                self._send_error(MobileControlError(404, "NOT_FOUND", "Endpoint not found"))

            def do_PATCH(self):
                parsed = urlparse(self.path)
                if parsed.path != "/api/config":
                    self._send_error(MobileControlError(404, "NOT_FOUND", "Endpoint not found"))
                    return
                self._require_pin(parsed)
                payload = self._read_json()
                clean = validate_config_patch(payload)
                data = owner.update_handler(clean)
                self._send_json(200, {"ok": True, "data": owner._with_schema(data)})

            def do_POST(self):
                parsed = urlparse(self.path)
                if parsed.path not in ("/api/pipeline/start", "/api/pipeline/stop", "/api/action"):
                    self._send_error(MobileControlError(404, "NOT_FOUND", "Endpoint not found"))
                    return
                self._require_pin(parsed)
                payload = self._read_json()
                if parsed.path == "/api/action":
                    if not isinstance(payload, dict):
                        raise MobileControlError(400, "INVALID_JSON", "Request body must be a JSON object")
                    action = str(payload.get("action", "")).strip()
                    action_payload = payload.get("payload") or {}
                    if not isinstance(action_payload, dict):
                        raise MobileControlError(400, "INVALID_JSON", "Action payload must be a JSON object")
                else:
                    action = "pipeline.start" if parsed.path.endswith("/start") else "pipeline.stop"
                    action_payload = {}
                data = owner._action(action, action_payload)
                self._send_json(200, {"ok": True, "data": owner._with_schema(data)})

            def _require_pin(self, parsed):
                query_pin = (parse_qs(parsed.query).get("pin") or [""])[0]
                header_pin = self.headers.get("X-Neko-Pin", "")
                auth = self.headers.get("Authorization", "")
                bearer_pin = auth[7:] if auth.lower().startswith("bearer ") else ""
                candidate = query_pin or header_pin or bearer_pin
                if not secrets.compare_digest(str(candidate), owner.pin):
                    raise MobileControlError(403, "FORBIDDEN", "Invalid or missing PIN")

            def _read_json(self):
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise MobileControlError(400, "INVALID_JSON", "Invalid Content-Length")
                if length <= 0:
                    self._request_body_consumed = True
                    return {}
                if length > 16 * 1024:
                    raise MobileControlError(413, "PAYLOAD_TOO_LARGE", "Request body is too large")
                raw = self.rfile.read(length)
                self._request_body_consumed = True
                try:
                    return json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise MobileControlError(400, "INVALID_JSON", "Request body must be valid JSON")

            def _discard_unread_body(self):
                if getattr(self, "_request_body_consumed", False):
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except (TypeError, ValueError):
                    length = 0
                remaining = max(0, min(length, 16 * 1024))
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 4096))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                self._request_body_consumed = True

            def _send_html(self, body):
                raw = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)

            def _send_json(self, status, payload):
                raw = _json_bytes(payload)
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)

            def _send_empty(self, status):
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _send_error(self, exc):
                self._discard_unread_body()
                self._send_json(exc.status, _error_payload(exc))

            def handle_one_request(self):
                self._request_body_consumed = False
                try:
                    super().handle_one_request()
                except MobileControlError as exc:
                    self._send_error(exc)
                except Exception:
                    self._send_error(MobileControlError(500, "SERVER_ERROR", "Internal server error"))

        return Handler

    def _state(self):
        return self._with_schema(self.state_provider())

    def _with_schema(self, state):
        data = dict(state or {})
        data["schema"] = mobile_control_schema()
        return data

    def _action(self, action, payload):
        action = str(action or "").strip()
        if action not in PANEL_ACTIONS:
            raise MobileControlError(422, "VALIDATION_ERROR", "Unsupported panel action", {"action": action})
        if self.action_handler is None:
            raise MobileControlError(409, "ACTION_UNAVAILABLE", "面板动作接口不可用")
        return self.action_handler(action, dict(payload or {}))
