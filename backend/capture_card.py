"""OpenCV-backed Windows capture-card discovery and preview support.

The QML layer receives only JPEG data URLs and metadata. Raw OpenCV frames remain
inside this service's worker thread so their lifetime is never coupled to Qt's UI
thread.
"""

from __future__ import annotations

import base64
import importlib
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


PIXEL_FORMATS: Tuple[str, ...] = ("AUTO", "RGB32", "NV12", "YUY2", "MJPG")
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
DEFAULT_FPS = 30.0
DEFAULT_PIXEL_FORMAT = "MJPG"
MAX_DEVICE_INDEX = 63


@dataclass(frozen=True)
class CaptureCardConfig:
    """The requested DirectShow input settings for one capture device."""

    device_index: int = -1
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fps: float = DEFAULT_FPS
    pixel_format: str = DEFAULT_PIXEL_FORMAT

    @classmethod
    def from_mapping(cls, values: Optional[Dict[str, Any]], fallback: Optional["CaptureCardConfig"] = None):
        fallback = fallback or cls()
        values = values or {}
        return cls(
            device_index=_clamp_int(
                values.get("capture_card_device_index", values.get("device_index", fallback.device_index)),
                fallback.device_index,
                -1,
                MAX_DEVICE_INDEX,
            ),
            width=_clamp_int(
                values.get("capture_card_width", values.get("width", fallback.width)),
                fallback.width,
                160,
                7680,
            ),
            height=_clamp_int(
                values.get("capture_card_height", values.get("height", fallback.height)),
                fallback.height,
                120,
                4320,
            ),
            fps=_clamp_float(
                values.get("capture_card_fps", values.get("fps", fallback.fps)),
                fallback.fps,
                1.0,
                240.0,
            ),
            pixel_format=_normalize_pixel_format(
                values.get("capture_card_pixel_format", values.get("pixel_format", fallback.pixel_format)),
                fallback.pixel_format,
            ),
        )

    def as_settings(self) -> Dict[str, Any]:
        return {
            "capture_card_device_index": self.device_index,
            "capture_card_width": self.width,
            "capture_card_height": self.height,
            "capture_card_fps": self.fps,
            "capture_card_pixel_format": self.pixel_format,
        }


@dataclass(frozen=True)
class CaptureCardDevice:
    """A device visible through OpenCV's DirectShow backend."""

    index: int
    name: str
    width: int = 0
    height: int = 0
    fps: float = 0.0
    pixel_format: str = ""

    def as_map(self) -> Dict[str, Any]:
        size_text = f"{self.width}x{self.height}" if self.width > 0 and self.height > 0 else "尺寸待协商"
        fps_text = f"{self.fps:.1f} fps" if self.fps > 0 else "帧率待协商"
        format_text = self.pixel_format or "格式待协商"
        return {
            "id": f"dshow:{self.index}",
            "index": self.index,
            "name": self.name,
            "display": f"{self.name}  |  {size_text}  |  {fps_text}  |  {format_text}",
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "pixelFormat": self.pixel_format,
            "backend": "dshow" if os.name == "nt" else "opencv",
        }


@dataclass(frozen=True)
class CaptureCardStatus:
    session_id: int
    text: str
    level: str = "info"
    active: Optional[bool] = None

    def as_map(self) -> Dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "text": self.text,
            "level": self.level,
            "active": self.active,
        }


@dataclass(frozen=True)
class CaptureCardPreviewFrame:
    session_id: int
    data_url: str
    width: int
    height: int
    captured_at: float

    def as_map(self) -> Dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "dataUrl": self.data_url,
            "width": self.width,
            "height": self.height,
            "capturedAt": self.captured_at,
        }


class CaptureCardService:
    """Keeps DirectShow probing and preview capture off the Qt UI thread."""

    def __init__(
        self,
        cv2_loader: Optional[Callable[[], Any]] = None,
        max_probe_devices: int = 12,
        preview_fps: float = 3.0,
        preview_max_edge: int = 960,
    ):
        self._cv2_loader = cv2_loader or self._import_cv2
        self._cv2_loaded = False
        self._cv2 = None
        self._cv2_error = ""
        self._max_probe_devices = max(1, min(int(max_probe_devices), MAX_DEVICE_INDEX + 1))
        self._preview_fps = max(0.5, min(float(preview_fps), 10.0))
        self._preview_max_edge = max(160, min(int(preview_max_edge), 1920))
        self._lock = threading.RLock()
        self._preview_thread: Optional[threading.Thread] = None
        self._preview_stop_event: Optional[threading.Event] = None
        self._preview_capture = None
        self._preview_session_id = 0

    @staticmethod
    def _import_cv2():
        return importlib.import_module("cv2")

    def availability(self) -> Tuple[bool, str]:
        cv2 = self._load_cv2()
        if cv2 is None:
            detail = f" ({self._cv2_error})" if self._cv2_error else ""
            return False, f"采集卡不可用: 未安装 OpenCV{detail}"
        backend_name = "DirectShow" if os.name == "nt" else "OpenCV"
        return True, f"采集卡就绪: {backend_name} / OpenCV"

    def enumerate_devices(self) -> Tuple[List[Dict[str, Any]], str]:
        """Return available video-input devices without reading live frames.

        Opening a DirectShow filter is sufficient to find cards even when no HDMI
        signal is connected. Reading during discovery would block on some cards.
        """

        cv2 = self._load_cv2()
        if cv2 is None:
            return [], self.availability()[1]

        device_names = self._directshow_device_names()
        probe_count = max(self._max_probe_devices, len(device_names))
        devices: List[Dict[str, Any]] = []
        for index in range(probe_count):
            capture = self._open_capture(cv2, index)
            try:
                if capture is None or not self._is_opened(capture):
                    continue
                width = _safe_int(self._capture_get(capture, getattr(cv2, "CAP_PROP_FRAME_WIDTH", -1)))
                height = _safe_int(self._capture_get(capture, getattr(cv2, "CAP_PROP_FRAME_HEIGHT", -1)))
                fps = _safe_float(self._capture_get(capture, getattr(cv2, "CAP_PROP_FPS", -1)))
                pixel_format = self._capture_fourcc(capture, cv2)
                name = device_names[index] if index < len(device_names) else f"视频输入 {index}"
                devices.append(
                    CaptureCardDevice(
                        index=index,
                        name=name,
                        width=width,
                        height=height,
                        fps=fps,
                        pixel_format=pixel_format,
                    ).as_map()
                )
            finally:
                self._release_capture(capture)

        if devices:
            return devices, f"采集卡扫描完成: 发现 {len(devices)} 个视频输入设备"
        return [], "采集卡扫描完成: 未发现可用视频输入设备"

    def start_preview(
        self,
        config: CaptureCardConfig,
        on_frame: Callable[[CaptureCardPreviewFrame], None],
        on_status: Callable[[CaptureCardStatus], None],
    ) -> Tuple[bool, str, int]:
        cv2 = self._load_cv2()
        if cv2 is None:
            return False, self.availability()[1], 0
        if config.device_index < 0:
            return False, "请选择一个采集卡视频输入后再打开预览。", 0

        self.stop_preview()
        with self._lock:
            self._preview_session_id += 1
            session_id = self._preview_session_id
            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._preview_loop,
                args=(session_id, stop_event, config, on_frame, on_status),
                daemon=True,
                name=f"neko-capture-preview-{session_id}",
            )
            self._preview_stop_event = stop_event
            self._preview_thread = thread
        thread.start()
        return True, "采集卡预览正在连接...", session_id

    def stop_preview(self, timeout: float = 1.5) -> bool:
        with self._lock:
            thread = self._preview_thread
            stop_event = self._preview_stop_event
            capture = self._preview_capture
        if thread is None:
            return False
        if stop_event is not None:
            stop_event.set()
        # Releasing a DirectShow capture unblocks most pending read calls.
        self._release_capture(capture)
        if thread is not threading.current_thread():
            thread.join(max(0.0, timeout))
        with self._lock:
            if self._preview_thread is thread and not thread.is_alive():
                self._preview_thread = None
                self._preview_stop_event = None
                self._preview_capture = None
        return True

    def is_preview_running(self) -> bool:
        with self._lock:
            thread = self._preview_thread
            stop_event = self._preview_stop_event
            return bool(thread and thread.is_alive() and stop_event and not stop_event.is_set())

    def _preview_loop(
        self,
        session_id: int,
        stop_event: threading.Event,
        config: CaptureCardConfig,
        on_frame: Callable[[CaptureCardPreviewFrame], None],
        on_status: Callable[[CaptureCardStatus], None],
    ) -> None:
        cv2 = self._load_cv2()
        capture = None
        connected = False
        failed_reads = 0
        next_emit_at = 0.0
        try:
            if cv2 is None:
                self._emit_status(on_status, CaptureCardStatus(session_id, self.availability()[1], "error", False))
                return
            capture = self._open_capture(cv2, config.device_index)
            with self._lock:
                if self._preview_session_id == session_id:
                    self._preview_capture = capture
            if capture is None or not self._is_opened(capture):
                self._emit_status(
                    on_status,
                    CaptureCardStatus(
                        session_id,
                        f"采集卡预览失败: 无法打开视频输入 {config.device_index}",
                        "error",
                        False,
                    ),
                )
                return

            self._configure_capture(capture, cv2, config)
            actual_width = _safe_int(self._capture_get(capture, getattr(cv2, "CAP_PROP_FRAME_WIDTH", -1)))
            actual_height = _safe_int(self._capture_get(capture, getattr(cv2, "CAP_PROP_FRAME_HEIGHT", -1)))
            actual_fps = _safe_float(self._capture_get(capture, getattr(cv2, "CAP_PROP_FPS", -1)))
            actual_format = self._capture_fourcc(capture, cv2) or config.pixel_format
            self._emit_status(
                on_status,
                CaptureCardStatus(
                    session_id,
                    "采集卡预览已连接: "
                    f"输入 {config.device_index} / "
                    f"{actual_width or config.width}x{actual_height or config.height} / "
                    f"{actual_fps or config.fps:.1f} fps / {actual_format}",
                    "success",
                    True,
                ),
            )
            connected = True

            while not stop_event.is_set():
                ok, frame = self._capture_read(capture)
                if not ok or frame is None:
                    failed_reads += 1
                    if failed_reads in (1, 8):
                        self._emit_status(
                            on_status,
                            CaptureCardStatus(
                                session_id,
                                "采集卡未收到视频帧，请检查 HDMI/AV视频信号和输入格式。",
                                "warn",
                                True,
                            ),
                        )
                    stop_event.wait(0.08)
                    continue

                failed_reads = 0
                now = time.monotonic()
                if now < next_emit_at:
                    continue
                next_emit_at = now + 1.0 / self._preview_fps
                preview = self._encode_preview(cv2, session_id, frame)
                if preview is not None:
                    self._safe_callback(on_frame, preview)
        except Exception as exc:
            self._emit_status(
                on_status,
                CaptureCardStatus(session_id, f"采集卡预览异常: {exc}", "error", False),
            )
        finally:
            self._release_capture(capture)
            with self._lock:
                if self._preview_session_id == session_id:
                    self._preview_capture = None
                    if self._preview_thread is threading.current_thread():
                        self._preview_thread = None
                        self._preview_stop_event = None
            if connected:
                self._emit_status(on_status, CaptureCardStatus(session_id, "采集卡预览已停止。", "info", False))

    def _load_cv2(self):
        with self._lock:
            if self._cv2_loaded:
                return self._cv2
            self._cv2_loaded = True
        try:
            cv2 = self._cv2_loader()
        except Exception as exc:  # Optional dependency: never prevent the panel from starting.
            with self._lock:
                self._cv2_error = str(exc).strip()
                self._cv2 = None
            return None
        if cv2 is None:
            with self._lock:
                self._cv2_error = "模块不可用"
                self._cv2 = None
            return None
        with self._lock:
            self._cv2 = cv2
        return cv2

    def _directshow_device_names(self) -> Sequence[str]:
        if os.name != "nt":
            return ()
        try:
            from pygrabber.dshow_graph import FilterGraph  # type: ignore

            return tuple(str(name).strip() for name in FilterGraph().get_input_devices() if str(name).strip())
        except Exception:
            return ()

    @staticmethod
    def _capture_backend(cv2) -> int:
        return getattr(cv2, "CAP_DSHOW", getattr(cv2, "CAP_ANY", 0)) if os.name == "nt" else getattr(cv2, "CAP_ANY", 0)

    def _open_capture(self, cv2, index: int):
        backend = self._capture_backend(cv2)
        try:
            return cv2.VideoCapture(index, backend)
        except TypeError:
            return cv2.VideoCapture(index)
        except Exception:
            return None

    @staticmethod
    def _is_opened(capture) -> bool:
        try:
            return bool(capture and capture.isOpened())
        except Exception:
            return False

    @staticmethod
    def _capture_get(capture, property_id):
        if property_id < 0:
            return 0
        try:
            return capture.get(property_id)
        except Exception:
            return 0

    @staticmethod
    def _capture_read(capture):
        try:
            return capture.read()
        except Exception:
            return False, None

    @staticmethod
    def _release_capture(capture) -> None:
        if capture is None:
            return
        try:
            capture.release()
        except Exception:
            pass

    def _configure_capture(self, capture, cv2, config: CaptureCardConfig) -> None:
        settings = (
            (getattr(cv2, "CAP_PROP_FRAME_WIDTH", -1), config.width),
            (getattr(cv2, "CAP_PROP_FRAME_HEIGHT", -1), config.height),
            (getattr(cv2, "CAP_PROP_FPS", -1), config.fps),
            (getattr(cv2, "CAP_PROP_BUFFERSIZE", -1), 1),
        )
        for property_id, value in settings:
            if property_id < 0:
                continue
            try:
                capture.set(property_id, value)
            except Exception:
                pass
        if config.pixel_format == "AUTO":
            return
        fourcc_property = getattr(cv2, "CAP_PROP_FOURCC", -1)
        fourcc_factory = getattr(cv2, "VideoWriter_fourcc", None)
        if fourcc_property < 0 or not callable(fourcc_factory):
            return
        try:
            # DirectShow calls this RGB32 while OpenCV's fourcc helper expects
            # the four-character RGB3 code for the same uncompressed layout.
            fourcc = "RGB3" if config.pixel_format == "RGB32" else config.pixel_format
            capture.set(fourcc_property, fourcc_factory(*fourcc))
        except Exception:
            pass

    def _capture_fourcc(self, capture, cv2) -> str:
        value = _safe_int(self._capture_get(capture, getattr(cv2, "CAP_PROP_FOURCC", -1)))
        if value <= 0:
            return ""
        try:
            chars = "".join(chr((value >> (8 * offset)) & 0xFF) for offset in range(4)).strip("\x00 ")
        except Exception:
            return ""
        return chars if chars.isprintable() else ""

    def _encode_preview(self, cv2, session_id: int, frame) -> Optional[CaptureCardPreviewFrame]:
        width, height = _frame_size(frame)
        if width <= 0 or height <= 0:
            return None
        preview_frame = frame
        largest = max(width, height)
        if largest > self._preview_max_edge and hasattr(cv2, "resize"):
            scale = self._preview_max_edge / float(largest)
            target_size = (max(1, int(width * scale)), max(1, int(height * scale)))
            try:
                preview_frame = cv2.resize(frame, target_size)
                width, height = target_size
            except Exception:
                pass
        quality_flag = getattr(cv2, "IMWRITE_JPEG_QUALITY", None)
        params = [quality_flag, 82] if quality_flag is not None else []
        try:
            ok, encoded = cv2.imencode(".jpg", preview_frame, params)
        except TypeError:
            ok, encoded = cv2.imencode(".jpg", preview_frame)
        except Exception:
            return None
        if not ok or encoded is None:
            return None
        try:
            binary = encoded.tobytes() if hasattr(encoded, "tobytes") else bytes(encoded)
        except Exception:
            return None
        if not binary:
            return None
        data_url = "data:image/jpeg;base64," + base64.b64encode(binary).decode("ascii")
        return CaptureCardPreviewFrame(session_id, data_url, width, height, time.time())

    @staticmethod
    def _safe_callback(callback, payload) -> None:
        try:
            callback(payload)
        except Exception:
            pass

    def _emit_status(self, callback, status: CaptureCardStatus) -> None:
        self._safe_callback(callback, status)


def _clamp_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        result = int(float(value))
    except (TypeError, ValueError):
        result = fallback
    return max(minimum, min(maximum, result))


def _clamp_float(value: Any, fallback: float, minimum: float, maximum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = fallback
    if result != result:  # NaN
        result = fallback
    return max(minimum, min(maximum, result))


def _normalize_pixel_format(value: Any, fallback: str) -> str:
    candidate = str(value or "").strip().upper()
    if candidate in PIXEL_FORMATS:
        return candidate
    return fallback if fallback in PIXEL_FORMATS else DEFAULT_PIXEL_FORMAT


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(round(float(value))))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if result > 0.0 and result == result else 0.0


def _frame_size(frame) -> Tuple[int, int]:
    shape = getattr(frame, "shape", ())
    if len(shape) < 2:
        return 0, 0
    try:
        return int(shape[1]), int(shape[0])
    except (TypeError, ValueError):
        return 0, 0
