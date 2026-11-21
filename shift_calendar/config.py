import json
import os
import socket
import tempfile
import threading

from shift_calendar.domain import clamp_half_hour as _clamp_half_hour
from shift_calendar.domain import clamp_int as _clamp_int

# 並行リクエスト保護用ロック（再入可能な RLock を使用）
_STORAGE_LOCK = threading.RLock()

_CONFIG_RUNTIME_KEYS = ("local_ip", "mobile_url", "backend_version", "server_version")

ALLOWED_CONFIG_KEYS = frozenset({
    "api_key",
    "default_name",
    "calendar_name",
    "time_definitions",
    "register_holidays",
    "register_paid_leaves",
    "theme",
    "paid_leave_start_month",
    "paid_leave_start_day",
    "paid_leave_annual_days",
    "paid_leave_hours_per_day",
})

# デフォルトの凡例マスター（写真に凡例が写っていなくても次回以降も適用）
DEFAULT_TIME_DEFINITIONS = {
    "早A": {"start": "06:00", "end": "15:00"},
    "早B": {"start": "06:30", "end": "15:30"},
    "早C": {"start": "07:00", "end": "16:00"},
    "早D": {"start": "08:00", "end": "17:00"},
    "日":  {"start": "08:30", "end": "17:30"},
    "遅A": {"start": "09:00", "end": "18:00"},
    "遅B": {"start": "09:30", "end": "18:30"},
    "遅C": {"start": "10:00", "end": "19:00"},
}


def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _atomic_write_json(path, data):
    """同一ディレクトリに一時ファイルを書き出して fsync 後に os.replace でアトミック置換する。"""
    parent_dir = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=parent_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise


def _atomic_write_text(path, text):
    """同一ディレクトリに一時ファイルを書き出して fsync 後に os.replace でアトミック置換する。"""
    parent_dir = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".b64", dir=parent_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise


def load_config(config_path, local_ip_fn=None):
    ip_getter = local_ip_fn or get_local_ip
    with _STORAGE_LOCK:
        cfg = {
            "api_key": "",
            "default_name": "皿田",
            "calendar_name": "シフトカレンダー",
            "time_definitions": dict(DEFAULT_TIME_DEFINITIONS),
            "register_holidays": True,
            "register_paid_leaves": True,
            "theme": "system",
            "paid_leave_start_month": 4,
            "paid_leave_start_day": 1,
            "paid_leave_annual_days": 20,
            "paid_leave_hours_per_day": 8.0,
        }
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    cfg.update(saved)
                    if "time_definitions" not in saved:
                        cfg["time_definitions"] = dict(DEFAULT_TIME_DEFINITIONS)
            except Exception:
                pass
        cfg["paid_leave_start_month"] = _clamp_int(cfg.get("paid_leave_start_month"), 4, 1, 12)
        cfg["paid_leave_start_day"] = _clamp_int(cfg.get("paid_leave_start_day"), 1, 1, 31)
        cfg["paid_leave_annual_days"] = _clamp_int(cfg.get("paid_leave_annual_days"), 20, 0, 365)
        cfg["paid_leave_hours_per_day"] = _clamp_half_hour(cfg.get("paid_leave_hours_per_day"), 8.0, 1.0, 24.0)
        cfg["local_ip"] = ip_getter()
        cfg["mobile_url"] = f"http://{cfg['local_ip']}:8765"
        cfg["backend_version"] = "events_v2"
        return cfg


def save_config(cfg, config_path):
    with _STORAGE_LOCK:
        clean_cfg = {k: v for k, v in dict(cfg).items() if k not in _CONFIG_RUNTIME_KEYS}
        _atomic_write_json(config_path, clean_cfg)
