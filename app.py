import os
import re
import sys
import json
import uuid
import unicodedata
import base64
import time
import threading
import subprocess
import tempfile
import webbrowser
import urllib.request
import urllib.error
import socket
import traceback
try:
    import cv2
    import numpy as np
except ImportError:
    _hb_py = "/opt/homebrew/bin/python3"
    if os.path.exists(_hb_py) and os.path.realpath(sys.executable) != os.path.realpath(_hb_py):
        os.execv(_hb_py, [_hb_py] + sys.argv)
    raise
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from shift_calendar.image_processing import (
    dewarp_table_image_with_status,
    dewarp_table_image,
    detect_table_grid,
    snap_row_band_to_grid,
    build_labeled_name_column_image,
    build_labeled_ocr_strip,
    detect_event_row_band,
    detect_active_event_columns,
    detect_active_event_spans,
    build_labeled_event_strip,
    optimize_image_for_ai,
)
from shift_calendar.calendar_export import (
    _clamp_half_hour,
    format_hourly_leave_hours,
    apply_hourly_leave_to_summary,
    _CALENDAR_HOLIDAY_RAW_NAMES,
    _normalize_holiday_key,
    CALENDAR_HOLIDAY_EXCLUDED_KEYS,
    split_event_and_skipped_holidays,
    clean_event_text_excluding_holidays,
    create_ics,
    _escape_applescript_str,
    build_apple_calendar_script,
    register_to_apple_calendar,
)


from shift_calendar import config as _config_mod
from shift_calendar import storage as _storage_mod
from shift_calendar.config import (
    DEFAULT_TIME_DEFINITIONS,
    _CONFIG_RUNTIME_KEYS,
    _STORAGE_LOCK,
    _atomic_write_json,
    _atomic_write_text,
    _clamp_int,
    get_local_ip,
)

# ディレクトリと設定ファイルのパス（テストのモンキーパッチ対象）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
HISTORY_DIR = os.path.join(BASE_DIR, "history")
MAX_UNREGISTERED_HISTORY = _storage_mod.MAX_UNREGISTERED_HISTORY
os.makedirs(HISTORY_DIR, exist_ok=True)

# 並行リクエスト保護用ロック（共有状態用）
_STATE_LOCK = threading.RLock()

# プリロード許可拡張子（ローカル画像ファイルのみ）
_ALLOWED_PRELOAD_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".heic", ".heif",
    ".webp", ".bmp", ".tif", ".tiff", ".gif"
}
_LOOPBACK_ADDRS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


def _is_loopback_client(client_address):
    if not client_address or len(client_address) < 1:
        return False
    return str(client_address[0] or "").strip() in _LOOPBACK_ADDRS


def _validate_preload_file_path(file_path):
    """プリロード対象パスが実在する通常の画像ファイルであることを検証する。"""
    if not isinstance(file_path, str) or not file_path.strip() or "\x00" in file_path:
        return False, "ファイルパスが不正です"
    resolved = os.path.realpath(file_path.strip())
    if not os.path.isfile(resolved):
        return False, "ファイルが存在しません"
    ext = os.path.splitext(resolved)[1].lower()
    if ext not in _ALLOWED_PRELOAD_EXTENSIONS:
        return False, "画像ファイル以外はプリロードできません"
    return True, resolved


def _get_allowed_cors_origin(origin_header, server_port=8765):
    """許可されたローカル／同一LANオリジンの場合のみ Origin を返す。"""
    if not origin_header or not isinstance(origin_header, str):
        return None
    origin = origin_header.strip()
    try:
        parsed = urlparse(origin)
    except Exception:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    port = parsed.port
    if port != server_port:
        return None
    allowed_hosts = {"localhost", "127.0.0.1", "::1"}
    local_ip = get_local_ip()
    if local_ip:
        allowed_hosts.add(local_ip.lower())
    if host in allowed_hosts:
        return origin
    return None


# --- 履歴ストレージ（実行時の HISTORY_DIR / CONFIG_PATH / time.strftime を DI 渡し） ---
def _get_history_images_dir():
    return _storage_mod.get_history_images_dir(HISTORY_DIR)

def _resolve_history_image_path(image_file):
    return _storage_mod.resolve_history_image_path(HISTORY_DIR, image_file)

def _save_history_image(safe_id, image_b64_str):
    return _storage_mod.save_history_image(HISTORY_DIR, safe_id, image_b64_str)

def _load_history_image(data):
    return _storage_mod.load_history_image(HISTORY_DIR, data)

def _delete_history_image(safe_id, image_file=None):
    return _storage_mod.delete_history_image(HISTORY_DIR, safe_id, image_file)

def prune_unregistered_history(max_keep=None):
    keep = MAX_UNREGISTERED_HISTORY if max_keep is None else max_keep
    return _storage_mod.prune_unregistered_history(HISTORY_DIR, max_keep=keep)

def get_history_list():
    return _storage_mod.get_history_list(HISTORY_DIR)

def get_history_detail(hist_id):
    return _storage_mod.get_history_detail(HISTORY_DIR, hist_id)

def save_history(data):
    return _storage_mod.save_history(HISTORY_DIR, data, max_keep=MAX_UNREGISTERED_HISTORY, strftime_fn=time.strftime)

def mark_history_registered(hist_id=None, history_data=None):
    return _storage_mod.mark_history_registered(HISTORY_DIR, hist_id=hist_id, history_data=history_data, max_keep=MAX_UNREGISTERED_HISTORY, strftime_fn=time.strftime)

def delete_history(hist_id):
    return _storage_mod.delete_history(HISTORY_DIR, hist_id)

def update_history_shift_hourly_leave(hist_id, date_str, hours):
    return _storage_mod.update_history_shift_hourly_leave(HISTORY_DIR, hist_id, date_str, hours, load_config_fn=load_config)

def get_registered_calendar_shifts():
    return _storage_mod.get_registered_calendar_shifts(HISTORY_DIR)

def load_config():
    return _config_mod.load_config(CONFIG_PATH, local_ip_fn=get_local_ip)

def save_config(cfg):
    return _config_mod.save_config(cfg, CONFIG_PATH)

# ハートビート管理（ブラウザを閉じたらターミナルも自動終了するため）
LAST_HEARTBEAT = time.time()
SERVER_INSTANCE = None
PRELOADED_IMAGE = None
SERVER_VERSION = "2026.11.21.v3"
_INITIAL_APP_MTIME = os.path.getmtime(os.path.abspath(__file__)) if os.path.exists(os.path.abspath(__file__)) else 0

# リアルタイム解析進捗ステータス（フロントエンドのプログレスバーと連動）
ANALYZE_PROGRESS = {
    "active": False,
    "percent": 0,
    "step": 0,
    "phase": "待機中",
    "detail": "",
    "updated_at": 0.0
}

def set_analyze_progress(percent, phase, detail="", step=1, active=True):
    with _STATE_LOCK:
        ANALYZE_PROGRESS["active"] = bool(active)
        ANALYZE_PROGRESS["percent"] = int(max(0, min(100, percent)))
        ANALYZE_PROGRESS["step"] = int(step)
        ANALYZE_PROGRESS["phase"] = str(phase or "")
        ANALYZE_PROGRESS["detail"] = str(detail or "")
        ANALYZE_PROGRESS["updated_at"] = time.time()

def get_analyze_progress():
    with _STATE_LOCK:
        return dict(ANALYZE_PROGRESS)



from shift_calendar import gemini_client as _gemini_mod
from shift_calendar.gemini_client import post_gemini_generate_content


def fetch_column_events_from_gemini(api_key, event_strip_bytes, n_cols, models_to_try=None, active_col_nums=None, active_spans=None, skipped_holidays_out=None):
    return _gemini_mod.fetch_column_events_from_gemini(
        api_key,
        event_strip_bytes,
        n_cols,
        models_to_try=models_to_try,
        active_col_nums=active_col_nums,
        active_spans=active_spans,
        skipped_holidays_out=skipped_holidays_out,
        sleep_fn=time.sleep,
        progress_fn=set_analyze_progress,
    )


def analyze_events_only(api_key, image_bytes):
    return _gemini_mod.analyze_events_only(
        api_key,
        image_bytes,
        dewarp_fn=dewarp_table_image,
        detect_grid_fn=detect_table_grid,
        fetch_events_fn=fetch_column_events_from_gemini,
        progress_fn=set_analyze_progress,
        detect_spans_fn=detect_active_event_spans,
        build_strip_fn=build_labeled_event_strip,
    )


def call_gemini_api(api_key, image_bytes, mime_type, target_name, master_definitions=None):
    return _gemini_mod.call_gemini_api(
        api_key,
        image_bytes,
        mime_type,
        target_name,
        master_definitions=master_definitions,
        dewarp_status_fn=dewarp_table_image_with_status,
        detect_grid_fn=detect_table_grid,
        progress_fn=set_analyze_progress,
        sleep_fn=time.sleep,
    )


# 自動終了・ホットリロード監視スレッド（ブラウザを完全に閉じた後に終了／app.py更新時に自動再起動）
def auto_shutdown_watcher():
    global LAST_HEARTBEAT, SERVER_INSTANCE
    app_file = os.path.abspath(__file__)
    # 起動直後はブラウザの初期表示を十分待つ
    for _ in range(10):
        time.sleep(2)
        try:
            with _STATE_LOCK:
                is_active = bool(ANALYZE_PROGRESS.get("active"))
            if _INITIAL_APP_MTIME and os.path.getmtime(app_file) != _INITIAL_APP_MTIME and not is_active:
                print("[HOT-RELOAD] app.py の更新を検知しました。サーバーを自動再起動します...", flush=True)
                if SERVER_INSTANCE:
                    try:
                        SERVER_INSTANCE.socket.close()
                    except Exception:
                        pass
                os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception:
            pass
    while True:
        time.sleep(2)
        try:
            with _STATE_LOCK:
                is_active = bool(ANALYZE_PROGRESS.get("active"))
                last_hb = LAST_HEARTBEAT
            if _INITIAL_APP_MTIME and os.path.getmtime(app_file) != _INITIAL_APP_MTIME and not is_active:
                print("[HOT-RELOAD] app.py の更新を検知しました。サーバーを自動再起動します...", flush=True)
                if SERVER_INSTANCE:
                    try:
                        SERVER_INSTANCE.socket.close()
                    except Exception:
                        pass
                os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception:
            with _STATE_LOCK:
                last_hb = LAST_HEARTBEAT
        # バックグラウンドタブのスロットリング対策として300秒間無通信の場合のみ自動停止
        if time.time() - last_hb > 300:
            print("ブラウザが閉じられたことを検知しました（無通信）。サーバーを終了します...")
            if SERVER_INSTANCE:
                threading.Thread(target=SERVER_INSTANCE.shutdown).start()
            break

class RequestHandler(BaseHTTPRequestHandler):
    def _send_cors_headers(self):
        headers = getattr(self, "headers", None)
        origin = headers.get("Origin") if headers else None
        server_port = getattr(getattr(self, "server", None), "server_port", 8765) or 8765
        allowed = _get_allowed_cors_origin(origin, server_port=server_port)
        if allowed:
            self.send_header("Access-Control-Allow-Origin", allowed)
            self.send_header("Vary", "Origin")

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        headers = getattr(self, "headers", None)
        origin = headers.get("Origin") if headers else None
        server_port = getattr(getattr(self, "server", None), "server_port", 8765) or 8765
        if origin and not _get_allowed_cors_origin(origin, server_port=server_port):
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        global LAST_HEARTBEAT
        with _STATE_LOCK:
            LAST_HEARTBEAT = time.time()
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            html_path = os.path.join(BASE_DIR, "index.html")
            if os.path.exists(html_path):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.end_headers()
                with open(html_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, "index.html not found")
        elif parsed.path in ("/favicon.ico", "/favicon.png"):
            ico_path = os.path.join(BASE_DIR, "favicon.png")
            if os.path.exists(ico_path):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                with open(ico_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404)
        elif parsed.path == "/apple-touch-icon.png":
            touch_path = os.path.join(BASE_DIR, "apple-touch-icon.png")
            if os.path.exists(touch_path):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                with open(touch_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404)
        elif parsed.path == "/api/config":
            cfg_data = dict(load_config())
            cfg_data["server_version"] = SERVER_VERSION
            self._send_json(cfg_data)
        elif parsed.path == "/api/analyze_progress":
            self._send_json(get_analyze_progress())
        elif parsed.path == "/api/heartbeat":
            self._send_json({"status": "alive"})
        elif parsed.path == "/api/get_preloaded":
            with _STATE_LOCK:
                preloaded = dict(PRELOADED_IMAGE) if PRELOADED_IMAGE else None
            if preloaded:
                # リロード時も常に最新の補正画像を返せるようNoneに破棄しない
                self._send_json({"has_image": True, "data": preloaded})
            else:
                self._send_json({"has_image": False})
        elif parsed.path == "/api/history":
            self._send_json({"history": get_history_list()})
        elif parsed.path == "/api/calendar_shifts":
            self._send_json(get_registered_calendar_shifts())
        elif parsed.path == "/api/history/detail":
            qs = parse_qs(parsed.query)
            hist_id = qs.get("id", [""])[0]
            detail = get_history_detail(hist_id)
            if detail:
                self._send_json({"success": True, "data": detail})
            else:
                self._send_json({"error": "履歴が見つかりません"}, 404)
        else:
            self.send_error(404)

    def do_POST(self):
        global LAST_HEARTBEAT, PRELOADED_IMAGE
        with _STATE_LOCK:
            LAST_HEARTBEAT = time.time()
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        if parsed.path == "/api/config":
            try:
                data = json.loads(body.decode("utf-8"))
                cfg = load_config()
                cfg.update(data)
                cfg["paid_leave_start_month"] = _clamp_int(cfg.get("paid_leave_start_month"), 4, 1, 12)
                cfg["paid_leave_start_day"] = _clamp_int(cfg.get("paid_leave_start_day"), 1, 1, 31)
                cfg["paid_leave_annual_days"] = _clamp_int(cfg.get("paid_leave_annual_days"), 20, 0, 365)
                cfg["paid_leave_hours_per_day"] = _clamp_half_hour(cfg.get("paid_leave_hours_per_day"), 8.0, 1.0, 24.0)
                save_config(cfg)
                self._send_json({"success": True, "config": load_config()})
            except Exception as e:
                self._send_json({"error": str(e)}, 400)

        elif parsed.path == "/api/analyze":
            try:
                req_data = json.loads(body.decode("utf-8"))
                image_data = req_data.get("image_base64")
                mime_type = req_data.get("mime_type", "image/jpeg")
                target_name = req_data.get("target_name") or "皿田"
                api_key = req_data.get("api_key") or load_config().get("api_key")
                master_defs = req_data.get("time_definitions") or load_config().get("time_definitions")

                if not api_key:
                    raise ValueError("APIキーが設定されていません")
                if not image_data:
                    raise ValueError("画像データがありません")

                if "," in image_data:
                    header, image_data = image_data.split(",", 1)
                    if "image/png" in header:
                        mime_type = "image/png"
                    elif "image/jpeg" in header or "image/jpg" in header:
                        mime_type = "image/jpeg"

                raw_bytes = base64.b64decode(image_data)
                # 解析開始時点でクイックアクション自動解析フラグを消費（リロード・別端末での重複自動解析を防止）
                with _STATE_LOCK:
                    if PRELOADED_IMAGE and PRELOADED_IMAGE.get("auto_analyze"):
                        PRELOADED_IMAGE["auto_analyze"] = False
                print(f"[ANALYZE] Received image size: {len(raw_bytes)} bytes, Target: {target_name}")
                result = call_gemini_api(api_key, raw_bytes, mime_type, target_name, master_defs)
                c_len = len(result.get("corrected_image_base64") or "")
                print(f"[ANALYZE] Finished. Corrected image b64 len: {c_len}")

                # 補正後画像が生成された場合、プリロード保持データも補正後画像に同期
                if result.get("corrected_image_base64"):
                    with _STATE_LOCK:
                        if PRELOADED_IMAGE:
                            PRELOADED_IMAGE["image_base64"] = result["corrected_image_base64"]
                            PRELOADED_IMAGE["file_size"] = len(result["corrected_image_base64"])

                self._send_json({"success": True, "data": result})
            except Exception as e:
                traceback.print_exc()
                set_analyze_progress(0, "解析エラー", str(e), step=3, active=False)
                self._send_json({"error": str(e)}, 500)

        elif parsed.path == "/api/analyze_events":
            try:
                req_data = json.loads(body.decode("utf-8"))
                image_data = req_data.get("image_base64")
                api_key = req_data.get("api_key") or load_config().get("api_key")
                if not api_key:
                    raise ValueError("APIキーが設定されていません")
                if not image_data:
                    raise ValueError("画像データがありません")
                if "," in image_data:
                    _, image_data = image_data.split(",", 1)
                raw_bytes = base64.b64decode(image_data)
                ev_result = analyze_events_only(api_key, raw_bytes)
                self._send_json({"success": True, "data": ev_result})
            except Exception as e:
                traceback.print_exc()
                set_analyze_progress(100, "行事予定の読み取りに失敗しました", str(e), step=4, active=False)
                self._send_json({"error": str(e)}, 500)

        elif parsed.path == "/api/register":
            try:
                req_data = json.loads(body.decode("utf-8"))
                shifts = req_data.get("shifts", [])
                cal_name = req_data.get("calendar_name") or "シフトカレンダー"
                include_events = bool(req_data.get("include_events", True))
                history_id = req_data.get("history_id")
                history_payload = req_data.get("history_payload")

                count, msg = register_to_apple_calendar(shifts, cal_name, include_events=include_events)
                updated_hist_id = None
                registered_at = ""
                if history_id or history_payload:
                    updated_hist_id = mark_history_registered(history_id, history_payload)
                    if updated_hist_id:
                        detail = get_history_detail(updated_hist_id)
                        if detail:
                            registered_at = detail.get("registered_at", "")
                self._send_json({
                    "success": True,
                    "count": count,
                    "message": msg,
                    "history_id": updated_hist_id,
                    "registered_at": registered_at
                })
            except Exception as e:
                traceback.print_exc()
                self._send_json({"error": str(e)}, 500)

        elif parsed.path == "/api/export_ics":
            try:
                req_data = json.loads(body.decode("utf-8"))
                shifts = req_data.get("shifts", [])
                cal_name = req_data.get("calendar_name") or "シフトカレンダー"
                include_events = bool(req_data.get("include_events", True))

                ics_content = create_ics(shifts, cal_name, include_events=include_events)
                self.send_response(200)
                self.send_header("Content-Type", "text/calendar; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="shifts.ics"')
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(ics_content.encode("utf-8"))
            except Exception as e:
                traceback.print_exc()
                self._send_json({"error": str(e)}, 500)

        elif parsed.path == "/api/preload":
            try:
                if not _is_loopback_client(getattr(self, "client_address", None)):
                    self._send_json({"error": "ローカル端末以外からのプリロードは許可されていません"}, 403)
                    return
                data = json.loads(body.decode("utf-8"))
                file_path = data.get("file_path", "")
                ok, resolved_or_err = _validate_preload_file_path(file_path)
                if not ok:
                    self._send_json({"error": resolved_or_err}, 400)
                    return

                import mimetypes
                mime = mimetypes.guess_type(resolved_or_err)[0] or "image/jpeg"
                fname = os.path.basename(resolved_or_err)
                with open(resolved_or_err, "rb") as f:
                    raw_bytes = f.read()

                # 受け取り時点で即座に水平・垂直補正（Phase 1: Dewarping）を実行
                processed_bytes, corrected_b64, dewarp_status = dewarp_table_image_with_status(raw_bytes)
                if corrected_b64:
                    final_b64 = corrected_b64
                    fsize = len(processed_bytes)
                else:
                    final_b64 = base64.b64encode(raw_bytes).decode("utf-8")
                    fsize = len(raw_bytes)

                with _STATE_LOCK:
                    PRELOADED_IMAGE = {
                        "preload_id": f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}",
                        "auto_analyze": True,
                        "image_base64": final_b64,
                        "mime_type": "image/jpeg" if corrected_b64 else mime,
                        "file_name": fname,
                        "file_size": fsize,
                        "dewarp_status": dewarp_status
                    }
                self._send_json({"success": True, "file_name": fname})
            except Exception as e:
                traceback.print_exc()
                self._send_json({"error": str(e)}, 500)

        elif parsed.path == "/api/dewarp_preview":
            try:
                data = json.loads(body.decode("utf-8"))
                img_b64 = data.get("image_base64", "")
                if "," in img_b64:
                    img_b64 = img_b64.split(",", 1)[1]
                raw = base64.b64decode(img_b64)
                proc_bytes, corr_b64, dewarp_status = dewarp_table_image_with_status(raw)
                self._send_json({
                    "success": True,
                    "corrected_image_base64": corr_b64 or data.get("image_base64"),
                    "dewarp_status": dewarp_status
                })
            except Exception as e:
                traceback.print_exc()
                self._send_json({"error": str(e)}, 500)

        elif parsed.path == "/api/calendar_shifts/hourly_leave":
            try:
                req_data = json.loads(body.decode("utf-8"))
                hist_id = req_data.get("history_id")
                date_str = req_data.get("date")
                hours = req_data.get("hourly_paid_leave", 0)
                sync_apple = bool(req_data.get("sync_apple_calendar", False))
                cal_name = req_data.get("calendar_name") or load_config().get("calendar_name") or "シフトカレンダー"
                include_events = bool(req_data.get("include_events", True))

                updated_shift = update_history_shift_hourly_leave(hist_id, date_str, hours)
                synced = False
                if sync_apple:
                    register_to_apple_calendar([updated_shift], cal_name, include_events=include_events)
                    synced = True

                self._send_json({
                    "success": True,
                    "shift": updated_shift,
                    "apple_calendar_synced": synced
                })
            except (ValueError, FileNotFoundError) as e:
                self._send_json({"error": str(e)}, 400)
            except Exception as e:
                traceback.print_exc()
                self._send_json({"error": str(e)}, 500)

        elif parsed.path == "/api/history/save":
            try:
                data = json.loads(body.decode("utf-8"))
                hist_id = save_history(data)
                self._send_json({"success": True, "id": hist_id})
            except Exception as e:
                traceback.print_exc()
                self._send_json({"error": str(e)}, 500)

        elif parsed.path == "/api/history/delete":
            try:
                data = json.loads(body.decode("utf-8"))
                hist_id = data.get("id", "")
                success = delete_history(hist_id)
                self._send_json({"success": success})
            except Exception as e:
                traceback.print_exc()
                self._send_json({"error": str(e)}, 500)

        elif parsed.path == "/api/shutdown":
            self._send_json({"success": True})
            if SERVER_INSTANCE:
                threading.Thread(target=SERVER_INSTANCE.shutdown).start()

        else:
            self.send_error(404)

def run():
    global SERVER_INSTANCE
    port = 8765
    local_ip = get_local_ip()
    server_address = ("0.0.0.0", port)
    SERVER_INSTANCE = ThreadingHTTPServer(server_address, RequestHandler)
    print("=" * 55)
    print(" 📅 シフトカレンダー登録アプリ 起動完了")
    print(f"  💻 Macでのアクセス:    http://localhost:{port}")
    print(f"  📱 iPhoneでのアクセス:  http://{local_ip}:{port} (同一Wi-Fi)")
    print("=" * 55)
    
    # 自動終了ウォッチャースレッド起動
    watcher = threading.Thread(target=auto_shutdown_watcher, daemon=True)
    watcher.start()
    
    SERVER_INSTANCE.serve_forever()

if __name__ == "__main__":
    run()
