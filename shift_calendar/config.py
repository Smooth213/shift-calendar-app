import json
import os
import re
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

_HHMM_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_RESERVED_SHIFT_KEYS = frozenset({"休", "休み", "有給", "有給休暇"})


def validate_time_definitions(raw_defs):
    """シフト区分定義（time_definitions）を検証・正規化して返す。不正時は ValueError。"""
    if not isinstance(raw_defs, dict):
        raise ValueError("time_definitions はオブジェクト形式で指定してください")
    if len(raw_defs) == 0:
        raise ValueError("シフト区分は1件以上登録してください")
    if len(raw_defs) > 30:
        raise ValueError("シフト区分は30件以下にしてください")

    normalized = {}
    for raw_key, raw_val in raw_defs.items():
        key = str(raw_key or "").strip()
        if not key:
            raise ValueError("シフト区分名が空の項目があります")
        if len(key) > 20 or any(ord(ch) < 32 for ch in key):
            raise ValueError(f"シフト区分名が不正です: {key!r}")
        if key in _RESERVED_SHIFT_KEYS:
            raise ValueError(f"シフト区分名「{key}」は予約語のため使用できません")
        if key in normalized:
            raise ValueError(f"シフト区分名「{key}」が重複しています")
        if not isinstance(raw_val, dict):
            raise ValueError(f"シフト区分「{key}」の時間定義が不正です")
        start = str(raw_val.get("start") or "").strip()
        end = str(raw_val.get("end") or "").strip()
        if not _HHMM_RE.match(start) or not _HHMM_RE.match(end):
            raise ValueError(f"シフト区分「{key}」の時刻は HH:MM 形式で指定してください")
        normalized[key] = {"start": start, "end": end}
    return normalized


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
