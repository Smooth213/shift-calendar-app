import io
import json
import os
import re
import time
import zipfile
from datetime import datetime

from shift_calendar.config import _STORAGE_LOCK, _atomic_write_json, _atomic_write_text
from shift_calendar.domain import (
    _clamp_half_hour,
    apply_hourly_leave_to_summary,
    sanitize_history_id,
)

MAX_UNREGISTERED_HISTORY = 5

# 履歴JSONの軽量メタデータキャッシュ: {abs_history_dir: {fname: (mtime_ns, size, parsed_dict)}}
_HISTORY_JSON_CACHE = {}


def _load_cached_history_records(history_dir):
    """history_dir 内の .json ファイルを (mtime_ns, size) 指紋付きでキャッシュ読込する。
    呼び出し元は _STORAGE_LOCK を保持していること。
    """
    abs_dir = os.path.abspath(history_dir)
    if not os.path.isdir(abs_dir):
        _HISTORY_JSON_CACHE.pop(abs_dir, None)
        return []

    dir_cache = _HISTORY_JSON_CACHE.setdefault(abs_dir, {})
    seen_fnames = set()
    records = []

    with os.scandir(abs_dir) as it:
        for entry in it:
            if not entry.name.endswith(".json") or not entry.is_file():
                continue
            fname = entry.name
            seen_fnames.add(fname)
            try:
                st = entry.stat()
                sig = (st.st_mtime_ns, st.st_size)
            except OSError:
                continue

            cached = dir_cache.get(fname)
            if cached is not None and cached[0] == sig[0] and cached[1] == sig[1]:
                records.append((fname, cached[2]))
                continue

            try:
                with open(entry.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    dir_cache[fname] = (sig[0], sig[1], data)
                    records.append((fname, data))
                else:
                    dir_cache.pop(fname, None)
            except Exception:
                dir_cache.pop(fname, None)

    for stale in list(dir_cache.keys()):
        if stale not in seen_fnames:
            dir_cache.pop(stale, None)

    return records


def get_history_images_dir(history_dir):
    """history_dir に対応する兄弟画像ディレクトリ（例: history -> history_images）を返す。"""
    hist_abs = os.path.abspath(history_dir)
    parent = os.path.dirname(hist_abs)
    name = os.path.basename(hist_abs) or "history"
    return os.path.join(parent, f"{name}_images")


def resolve_history_image_path(history_dir, image_file):
    """image_file が画像専用ディレクトリ配下に収まることを検証して実パスを返す。"""
    if not isinstance(image_file, str) or not image_file.strip():
        return None
    img_dir_real = os.path.realpath(get_history_images_dir(history_dir))
    cleaned = image_file.strip()
    if cleaned.startswith("images/") or cleaned.startswith("images\\"):
        cleaned = cleaned[len("images/"):]
    if os.path.isabs(cleaned) or "/" in cleaned or "\\" in cleaned or cleaned in (".", ".."):
        return None
    candidate = os.path.realpath(os.path.join(img_dir_real, cleaned))
    if candidate == img_dir_real or not candidate.startswith(img_dir_real + os.sep):
        return None
    return candidate


def save_history_image(history_dir, safe_id, image_b64_str):
    """履歴の image_base64 文字列を history_images/<safe_id>.b64 に分離保存し、ファイル名を返す。"""
    fname = f"{safe_id}.b64"
    img_dir = get_history_images_dir(history_dir)
    abs_path = os.path.join(img_dir, fname)
    _atomic_write_text(abs_path, str(image_b64_str))
    return fname


def load_history_image(history_dir, data):
    """分離保存された画像ファイル（または旧形式の image_base64）から画像文字列を復元する。"""
    img_inline = data.get("image_base64")
    if img_inline:
        return img_inline
    img_file = data.get("image_file")
    if img_file:
        abs_path = resolve_history_image_path(history_dir, img_file)
        if abs_path and os.path.isfile(abs_path):
            try:
                with open(abs_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                return ""
    return ""


def delete_history_image(history_dir, safe_id, image_file=None):
    """履歴に紐づく分離画像ファイルを削除する（存在しない場合は何もしない）。"""
    candidates = []
    if image_file:
        resolved = resolve_history_image_path(history_dir, image_file)
        if resolved:
            candidates.append(resolved)
    if safe_id:
        resolved_default = resolve_history_image_path(history_dir, f"{safe_id}.b64")
        if resolved_default and resolved_default not in candidates:
            candidates.append(resolved_default)
    for path in candidates:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass
    try:
        img_dir = get_history_images_dir(history_dir)
        if os.path.isdir(img_dir) and not os.listdir(img_dir):
            os.rmdir(img_dir)
    except Exception:
        pass


def prune_unregistered_history(history_dir, max_keep=MAX_UNREGISTERED_HISTORY):
    """未登録の履歴JSONを直近 max_keep 件のみ残し、それより古い未登録ファイルを削除する。
    登録済み（registered=True）の履歴は削除しない。
    """
    with _STORAGE_LOCK:
        deleted_ids = []
        if not os.path.exists(history_dir):
            return deleted_ids

        unregistered_entries = []
        for fname in os.listdir(history_dir):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(history_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if bool(data.get("registered", False)):
                    continue
                sort_key = (str(data.get("created_at", "")), fname)
                unregistered_entries.append((sort_key, data.get("id", fname[:-5]), fpath, data.get("image_file")))
            except Exception:
                continue

        unregistered_entries.sort(key=lambda x: x[0], reverse=True)
        keep_limit = max(0, int(max_keep))
        for _, hist_id, fpath, img_file in unregistered_entries[keep_limit:]:
            try:
                os.remove(fpath)
                safe_id = sanitize_history_id(hist_id)
                delete_history_image(history_dir, safe_id, img_file)
                deleted_ids.append(hist_id)
            except Exception:
                pass
        return deleted_ids


def get_history_list(history_dir):
    with _STORAGE_LOCK:
        items = []
        for fname, data in _load_cached_history_records(history_dir):
            has_img = bool(data.get("image_base64") or data.get("image_file") or data.get("has_image"))
            items.append({
                "id": data.get("id", fname[:-5]),
                "title": data.get("title", "シフト"),
                "created_at": data.get("created_at", ""),
                "registered": bool(data.get("registered", False)),
                "registered_at": data.get("registered_at", ""),
                "target_name": data.get("target_name", "皿田"),
                "shifts_count": len(data.get("shifts", [])),
                "has_image": has_img,
                "image_name": data.get("image_name", ""),
            })
        items.sort(key=lambda x: (x.get("registered_at") or x.get("created_at") or "", x.get("id") or ""), reverse=True)
        return items


def get_history_detail(history_dir, hist_id):
    with _STORAGE_LOCK:
        safe_id = sanitize_history_id(hist_id)
        fpath = os.path.join(history_dir, f"{safe_id}.json")
        if os.path.exists(fpath):
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
                data.setdefault("registered", False)
                data.setdefault("registered_at", "")
                if not data.get("image_base64") and data.get("image_file"):
                    loaded_img = load_history_image(history_dir, data)
                    if loaded_img:
                        data["image_base64"] = loaded_img
                return data
        return None


def save_history(history_dir, data, max_keep=MAX_UNREGISTERED_HISTORY, strftime_fn=None):
    fmt_time = strftime_fn or time.strftime
    with _STORAGE_LOCK:
        os.makedirs(history_dir, exist_ok=True)
        payload = dict(data)
        explicit_id = payload.get("id")
        raw_id = explicit_id or fmt_time("%Y%m%d_%H%M%S")
        safe_id = sanitize_history_id(raw_id) or fmt_time("%Y%m%d_%H%M%S")

        if not explicit_id:
            candidate = safe_id
            suffix = 1
            while os.path.exists(os.path.join(history_dir, f"{candidate}.json")):
                candidate = f"{safe_id}_{suffix}"
                suffix += 1
            safe_id = candidate

        fpath = os.path.join(history_dir, f"{safe_id}.json")
        existing = None
        if explicit_id and os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = None

        if existing:
            merged = dict(existing)
            for k, v in payload.items():
                if k in ("image_base64", "image_file", "mime_type", "image_name", "dewarp_status", "created_at", "registered_at") and not v:
                    continue
                merged[k] = v
            if "registered" not in payload:
                merged["registered"] = bool(existing.get("registered", False))
            else:
                merged["registered"] = bool(payload.get("registered", False))
            payload = merged
        else:
            payload["registered"] = bool(payload.get("registered", False))
            payload.setdefault("registered_at", "")

        payload["id"] = safe_id
        if not payload.get("created_at"):
            payload["created_at"] = fmt_time("%Y-%m-%d %H:%M:%S")

        img_b64 = payload.pop("image_base64", None)
        if img_b64:
            payload["image_file"] = save_history_image(history_dir, safe_id, img_b64)
            payload["has_image"] = True
        elif payload.get("image_file"):
            resolved = resolve_history_image_path(history_dir, payload.get("image_file"))
            payload["has_image"] = bool(resolved and os.path.isfile(resolved))
        else:
            payload["has_image"] = False

        _atomic_write_json(fpath, payload)

        prune_unregistered_history(history_dir, max_keep=max_keep)
        return safe_id


def mark_history_registered(history_dir, hist_id=None, history_data=None, max_keep=MAX_UNREGISTERED_HISTORY, strftime_fn=None):
    """カレンダー登録完了時に該当履歴を登録済み（registered=True）として保存・昇格する。"""
    fmt_time = strftime_fn or time.strftime
    with _STORAGE_LOCK:
        now_str = fmt_time("%Y-%m-%d %H:%M:%S")
        safe_id = sanitize_history_id(hist_id)

        if safe_id:
            existing = get_history_detail(history_dir, safe_id)
            if existing:
                merged = dict(existing)
                if isinstance(history_data, dict):
                    for k in ("title", "target_name", "shifts", "image_base64", "mime_type", "image_name", "dewarp_status"):
                        val = history_data.get(k)
                        if k == "shifts":
                            if isinstance(val, list) and len(val) > 0:
                                merged[k] = val
                        elif val:
                            merged[k] = val
                merged["id"] = safe_id
                merged["registered"] = True
                merged["registered_at"] = now_str
                return save_history(history_dir, merged, max_keep=max_keep, strftime_fn=fmt_time)

        if isinstance(history_data, dict) and history_data.get("shifts"):
            payload = dict(history_data)
            payload.pop("id", None)
            payload["registered"] = True
            payload["registered_at"] = now_str
            return save_history(history_dir, payload, max_keep=max_keep, strftime_fn=fmt_time)

        return None


def delete_history(history_dir, hist_id):
    with _STORAGE_LOCK:
        safe_id = sanitize_history_id(hist_id)
        fpath = os.path.join(history_dir, f"{safe_id}.json")
        if os.path.exists(fpath):
            img_file = None
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    img_file = data.get("image_file")
            except Exception:
                pass
            os.remove(fpath)
            delete_history_image(history_dir, safe_id, img_file)
            return True
        return False


def update_history_shift_hourly_leave(history_dir, hist_id, date_str, hours, load_config_fn):
    """指定履歴の該当日の時間有給（0.5時間刻み）とカレンダー登録名を更新して保存する。"""
    safe_id = sanitize_history_id(hist_id)
    if not safe_id:
        raise ValueError("履歴IDが指定されていません")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(date_str or "").strip()):
        raise ValueError("日付の形式が不正です")

    with _STORAGE_LOCK:
        fpath = os.path.join(history_dir, f"{safe_id}.json")
        if not os.path.exists(fpath):
            raise FileNotFoundError("対象の履歴が見つかりません")

        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)

        shifts = data.get("shifts")
        if not isinstance(shifts, list):
            raise ValueError("履歴にシフトデータが含まれていません")

        cfg = load_config_fn()
        max_hours = max(0.5, _clamp_half_hour(cfg.get("paid_leave_hours_per_day"), 8.0, 1.0, 24.0) - 0.5)
        norm_hours = _clamp_half_hour(hours, 0.0, 0.0, max_hours)

        updated_shift = None
        for s in shifts:
            if isinstance(s, dict) and str(s.get("date") or "").strip() == date_str:
                status = str(s.get("status") or "work")
                if status in ("holiday", "paid_leave") or s.get("is_holiday") or s.get("is_paid_leave"):
                    raise ValueError("休みまたは終日有給の日には時間有給を設定できません")
                s["hourly_paid_leave"] = norm_hours
                raw_sum = s.get("summary") or s.get("type") or "出勤"
                s["summary"] = apply_hourly_leave_to_summary(raw_sum, norm_hours, "work")
                updated_shift = dict(s)
                break

        if updated_shift is None:
            raise ValueError("対象の日付が履歴内に見つかりません")

        _atomic_write_json(fpath, data)

        return updated_shift


def update_history_shift(history_dir, hist_id, date_str, updates, load_config_fn):
    """指定履歴の該当日のシフト区分・時間・時間有給・行事予定を更新して保存する。"""
    safe_id = sanitize_history_id(hist_id)
    if not safe_id:
        raise ValueError("履歴IDが指定されていません")
    norm_date = str(date_str or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", norm_date):
        raise ValueError("日付の形式が不正です")
    if not isinstance(updates, dict):
        raise ValueError("更新内容の形式が不正です")

    with _STORAGE_LOCK:
        fpath = os.path.join(history_dir, f"{safe_id}.json")
        if not os.path.exists(fpath):
            raise FileNotFoundError("対象の履歴が見つかりません")

        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)

        shifts = data.get("shifts")
        if not isinstance(shifts, list):
            raise ValueError("履歴にシフトデータが含まれていません")

        cfg = load_config_fn()
        time_defs = cfg.get("time_definitions") or {}
        max_hours = max(0.5, _clamp_half_hour(cfg.get("paid_leave_hours_per_day"), 8.0, 1.0, 24.0) - 0.5)

        updated_shift = None
        for s in shifts:
            if not (isinstance(s, dict) and str(s.get("date") or "").strip() == norm_date):
                continue

            new_type = str(updates.get("type") if "type" in updates else (s.get("type") or "")).strip()
            raw_status = str(updates.get("status") or "").strip()

            if new_type in ("休", "休み") or raw_status == "holiday":
                status = "holiday"
                s["type"] = "休"
                s["status"] = "holiday"
                s["is_holiday"] = True
                s["is_paid_leave"] = False
                s["start_time"] = None
                s["end_time"] = None
                s["hourly_paid_leave"] = 0.0
                s["summary"] = "休み"
            elif new_type in ("有給", "有給休暇") or raw_status == "paid_leave":
                status = "paid_leave"
                s["type"] = "有給"
                s["status"] = "paid_leave"
                s["is_holiday"] = False
                s["is_paid_leave"] = True
                s["start_time"] = None
                s["end_time"] = None
                s["hourly_paid_leave"] = 0.0
                s["summary"] = "有給休暇"
            else:
                if not new_type:
                    raise ValueError("シフト区分を指定してください")
                status = "work"
                def_entry = time_defs.get(new_type) if isinstance(time_defs, dict) else None
                start_t = str(updates.get("start_time") or "").strip()
                end_t = str(updates.get("end_time") or "").strip()
                if not start_t and def_entry:
                    start_t = str(def_entry.get("start") or "").strip()
                if not end_t and def_entry:
                    end_t = str(def_entry.get("end") or "").strip()
                if not start_t:
                    start_t = str(s.get("start_time") or "08:30").strip()
                if not end_t:
                    end_t = str(s.get("end_time") or "17:30").strip()

                raw_hours = updates.get("hourly_paid_leave") if "hourly_paid_leave" in updates else s.get("hourly_paid_leave", 0)
                norm_hours = _clamp_half_hour(raw_hours, 0.0, 0.0, max_hours)

                s["type"] = new_type
                s["status"] = "work"
                s["is_holiday"] = False
                s["is_paid_leave"] = False
                s["start_time"] = start_t
                s["end_time"] = end_t
                s["hourly_paid_leave"] = norm_hours
                base_summary = f"[{new_type}] ({start_t}〜{end_t})" if (start_t and end_t) else f"[{new_type}]"
                s["summary"] = apply_hourly_leave_to_summary(base_summary, norm_hours, status)

            if "event" in updates:
                s["event"] = str(updates.get("event") or "").replace("\r", " ").replace("\n", " ").strip()
            if "memo" in updates:
                s["memo"] = str(updates.get("memo") or "").replace("\r", " ").replace("\n", " ").strip()

            updated_shift = dict(s)
            break

        if updated_shift is None:
            raise ValueError("対象の日付が履歴内に見つかりません")

        _atomic_write_json(fpath, data)
        return updated_shift


_JP_DOW = ("月", "火", "水", "木", "金", "土", "日")


def upsert_manual_calendar_shift(history_dir, date_str, updates, load_config_fn, strftime_fn=None):
    """未登録日への手入力シフトを追加・更新し、手入力用月別履歴（manual_YYYY_MM）へ保存する。

    戻り値: (updated_shift, hist_id)
    """
    norm_date = str(date_str or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", norm_date):
        raise ValueError("日付の形式が不正です")
    try:
        dt = datetime.strptime(norm_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("実在しない日付です") from exc
    if not isinstance(updates, dict):
        raise ValueError("更新内容の形式が不正です")

    _strftime = strftime_fn or time.strftime
    now_str = _strftime("%Y/%m/%d %H:%M")
    ym_slug = f"{dt.year}_{dt.month:02d}"
    hist_id = f"manual_{ym_slug}"

    with _STORAGE_LOCK:
        os.makedirs(history_dir, exist_ok=True)
        fpath = os.path.join(history_dir, f"{hist_id}.json")
        cfg = load_config_fn()
        time_defs = cfg.get("time_definitions") or {}
        max_hours = max(0.5, _clamp_half_hour(cfg.get("paid_leave_hours_per_day"), 8.0, 1.0, 24.0) - 0.5)
        target_name = str(cfg.get("target_name") or "皿田")

        if os.path.exists(fpath):
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data.get("shifts"), list):
                data["shifts"] = []
        else:
            data = {
                "id": hist_id,
                "title": f"{dt.year}年{dt.month}月 手入力シフト",
                "created_at": now_str,
                "registered": True,
                "registered_at": now_str,
                "source": "manual",
                "target_name": target_name,
                "shifts": [],
            }

        data["registered"] = True
        data["registered_at"] = now_str
        if not data.get("target_name"):
            data["target_name"] = target_name

        shifts = data["shifts"]
        existing = None
        for s in shifts:
            if isinstance(s, dict) and str(s.get("date") or "").strip() == norm_date:
                existing = s
                break

        if existing is None:
            existing = {
                "date": norm_date,
                "day_of_week": _JP_DOW[dt.weekday()],
                "type": "",
                "status": "work",
                "is_holiday": False,
                "is_paid_leave": False,
                "hourly_paid_leave": 0.0,
                "start_time": None,
                "end_time": None,
                "summary": "",
                "event": "",
                "memo": "",
            }
            shifts.append(existing)

        new_type = str(updates.get("type") if "type" in updates else (existing.get("type") or "")).strip()
        raw_status = str(updates.get("status") or "").strip()

        if new_type in ("休", "休み") or raw_status == "holiday":
            existing["type"] = "休"
            existing["status"] = "holiday"
            existing["is_holiday"] = True
            existing["is_paid_leave"] = False
            existing["start_time"] = None
            existing["end_time"] = None
            existing["hourly_paid_leave"] = 0.0
            existing["summary"] = "休み"
        elif new_type in ("有給", "有給休暇") or raw_status == "paid_leave":
            existing["type"] = "有給"
            existing["status"] = "paid_leave"
            existing["is_holiday"] = False
            existing["is_paid_leave"] = True
            existing["start_time"] = None
            existing["end_time"] = None
            existing["hourly_paid_leave"] = 0.0
            existing["summary"] = "有給休暇"
        else:
            if not new_type:
                raise ValueError("シフト区分を指定してください")
            def_entry = time_defs.get(new_type) if isinstance(time_defs, dict) else None
            start_t = str(updates.get("start_time") or "").strip()
            end_t = str(updates.get("end_time") or "").strip()
            if not start_t and def_entry:
                start_t = str(def_entry.get("start") or "").strip()
            if not end_t and def_entry:
                end_t = str(def_entry.get("end") or "").strip()
            if not start_t:
                start_t = str(existing.get("start_time") or "08:30").strip()
            if not end_t:
                end_t = str(existing.get("end_time") or "17:30").strip()

            raw_hours = updates.get("hourly_paid_leave") if "hourly_paid_leave" in updates else existing.get("hourly_paid_leave", 0)
            norm_hours = _clamp_half_hour(raw_hours, 0.0, 0.0, max_hours)

            existing["type"] = new_type
            existing["status"] = "work"
            existing["is_holiday"] = False
            existing["is_paid_leave"] = False
            existing["start_time"] = start_t
            existing["end_time"] = end_t
            existing["hourly_paid_leave"] = norm_hours
            base_summary = f"[{new_type}] ({start_t}〜{end_t})" if (start_t and end_t) else f"[{new_type}]"
            existing["summary"] = apply_hourly_leave_to_summary(base_summary, norm_hours, "work")

        if "event" in updates:
            existing["event"] = str(updates.get("event") or "").replace("\r", " ").replace("\n", " ").strip()
        if "memo" in updates:
            existing["memo"] = str(updates.get("memo") or "").replace("\r", " ").replace("\n", " ").strip()

        shifts.sort(key=lambda item: str(item.get("date") or ""))
        _atomic_write_json(fpath, data)
        return dict(existing), hist_id


def get_registered_calendar_shifts(history_dir):
    """登録済み（registered=True）の履歴のみを日付（YYYY-MM-DD）単位で統合して返す。
    同一日付が複数履歴にある場合は registered_at（なければ created_at）および id が新しいものを優先する。
    レスポンス軽量化のため image_base64 は含めない。
    """
    with _STORAGE_LOCK:
        registered_records = []
        for fname, data in _load_cached_history_records(history_dir):
            if not bool(data.get("registered", False)):
                continue
            hist_id = str(data.get("id") or fname[:-5])
            reg_at = str(data.get("registered_at") or "")
            created_at = str(data.get("created_at") or "")
            sort_key = (reg_at or created_at, hist_id)
            registered_records.append((sort_key, hist_id, data))

        registered_records.sort(key=lambda x: x[0])

        shifts_by_date = {}
        for _, hist_id, data in registered_records:
            shifts = data.get("shifts")
            if not isinstance(shifts, list):
                continue
            hist_title = str(data.get("title") or "シフト")
            reg_at = str(data.get("registered_at") or data.get("created_at") or "")
            target_name = str(data.get("target_name") or "皿田")
            for s in shifts:
                if not isinstance(s, dict):
                    continue
                date_str = str(s.get("date") or "").strip()
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
                    continue
                status_val = str(s.get("status") or "work")
                is_hol = bool(s.get("is_holiday", False))
                is_paid = bool(s.get("is_paid_leave", False))
                h_leave = 0.0 if (status_val in ("holiday", "paid_leave") or is_hol or is_paid) else _clamp_half_hour(s.get("hourly_paid_leave"), 0.0, 0.0, 23.5)
                shifts_by_date[date_str] = {
                    "date": date_str,
                    "day_of_week": str(s.get("day_of_week") or ""),
                    "type": str(s.get("type") or ""),
                    "status": status_val,
                    "is_holiday": is_hol,
                    "is_paid_leave": is_paid,
                    "hourly_paid_leave": h_leave,
                    "start_time": s.get("start_time"),
                    "end_time": s.get("end_time"),
                    "summary": str(s.get("summary") or ""),
                    "event": str(s.get("event") or ""),
                    "memo": str(s.get("memo") or ""),
                    "history_id": hist_id,
                    "history_title": hist_title,
                    "registered_at": reg_at,
                    "target_name": target_name,
                }

        available_months = sorted({d[:7] for d in shifts_by_date.keys()})
        return {
            "success": True,
            "shifts_by_date": shifts_by_date,
            "available_months": available_months,
            "registered_histories_count": len(registered_records),
        }


MAX_BACKUP_ZIP_ENTRIES = 1000
MAX_BACKUP_UNCOMPRESSED_BYTES = 200 * 1024 * 1024  # 200MB


def export_history_backup_zip(history_dir, strftime_fn=None):
    """履歴JSON（history/）および分離画像（history_images/）をZIPバイト列へ一括エクスポートする。"""
    fmt_time = strftime_fn or time.strftime
    with _STORAGE_LOCK:
        buf = io.BytesIO()
        histories_count = 0
        images_count = 0
        img_dir = get_history_images_dir(history_dir)

        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if os.path.isdir(history_dir):
                for fname in sorted(os.listdir(history_dir)):
                    if not fname.endswith(".json"):
                        continue
                    fpath = os.path.join(history_dir, fname)
                    if not os.path.isfile(fpath):
                        continue
                    safe_stem = sanitize_history_id(fname[:-5])
                    if not safe_stem:
                        continue
                    with open(fpath, "rb") as f:
                        zf.writestr(f"history/{safe_stem}.json", f.read())
                    histories_count += 1

            if os.path.isdir(img_dir):
                for fname in sorted(os.listdir(img_dir)):
                    if not fname.endswith(".b64"):
                        continue
                    fpath = os.path.join(img_dir, fname)
                    if not os.path.isfile(fpath):
                        continue
                    safe_stem = sanitize_history_id(fname[:-4])
                    if not safe_stem:
                        continue
                    with open(fpath, "rb") as f:
                        zf.writestr(f"history_images/{safe_stem}.b64", f.read())
                    images_count += 1

            manifest = {
                "format_version": 1,
                "exported_at": fmt_time("%Y-%m-%d %H:%M:%S"),
                "histories_count": histories_count,
                "images_count": images_count,
            }
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))

        return buf.getvalue()


def import_history_backup_zip(history_dir, zip_bytes, overwrite=False):
    """バックアップZIPを検証し、履歴JSONと分離画像を安全に復元する（デフォルトは既存IDスキップ）。"""
    if not isinstance(zip_bytes, (bytes, bytearray)) or len(zip_bytes) == 0:
        raise ValueError("バックアップZIPデータが空です")

    try:
        zf_ctx = zipfile.ZipFile(io.BytesIO(zip_bytes), "r")
    except zipfile.BadZipFile as e:
        raise ValueError("有効なZIPファイルではありません") from e

    parsed_histories = {}
    parsed_images = {}

    with zf_ctx as zf:
        infos = zf.infolist()
        if len(infos) > MAX_BACKUP_ZIP_ENTRIES:
            raise ValueError("ZIP内のファイル数が上限を超えています")

        total_uncompressed = 0
        for info in infos:
            name = info.filename
            if info.is_dir():
                continue
            if not name or name.startswith("/") or "\\" in name or ".." in name.split("/"):
                raise ValueError(f"不正なZIPエントリパスが含まれています: {name}")
            total_uncompressed += int(info.file_size or 0)
            if total_uncompressed > MAX_BACKUP_UNCOMPRESSED_BYTES:
                raise ValueError("ZIP展開サイズが上限を超えています")

            if name == "manifest.json":
                continue

            parts = name.split("/")
            if len(parts) != 2:
                raise ValueError(f"許可されていないZIP階層が含まれています: {name}")
            folder, fname = parts

            if folder == "history" and fname.endswith(".json"):
                stem = fname[:-5]
                safe_id = sanitize_history_id(stem)
                if not safe_id or safe_id != stem:
                    raise ValueError(f"不正な履歴ファイル名です: {fname}")
                raw = zf.read(info)
                try:
                    obj = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    raise ValueError(f"履歴JSONの形式が不正です ({fname}): {e}") from e
                if not isinstance(obj, dict):
                    raise ValueError(f"履歴JSONはオブジェクト形式である必要があります ({fname})")
                obj["id"] = safe_id
                parsed_histories[safe_id] = obj
            elif folder == "history_images" and fname.endswith(".b64"):
                stem = fname[:-4]
                safe_id = sanitize_history_id(stem)
                if not safe_id or safe_id != stem:
                    raise ValueError(f"不正な画像ファイル名です: {fname}")
                raw = zf.read(info)
                try:
                    b64_text = raw.decode("utf-8")
                except UnicodeDecodeError as e:
                    raise ValueError(f"画像データのエンコードが不正です ({fname})") from e
                parsed_images[safe_id] = b64_text
            else:
                raise ValueError(f"許可されていないファイルが含まれています: {name}")

    with _STORAGE_LOCK:
        os.makedirs(history_dir, exist_ok=True)
        imported_histories = 0
        skipped_histories = 0
        imported_images = 0

        for safe_id, obj in parsed_histories.items():
            fpath = os.path.join(history_dir, f"{safe_id}.json")
            if os.path.exists(fpath) and not overwrite:
                skipped_histories += 1
                continue
            if safe_id in parsed_images:
                obj["image_file"] = save_history_image(history_dir, safe_id, parsed_images[safe_id])
                obj["has_image"] = True
                imported_images += 1
            _atomic_write_json(fpath, obj)
            imported_histories += 1

        return {
            "imported_histories": imported_histories,
            "skipped_histories": skipped_histories,
            "imported_images": imported_images,
        }
