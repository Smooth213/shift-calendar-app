import os
import subprocess
import tempfile
from datetime import datetime, timedelta

from shift_calendar.domain import (
    CALENDAR_HOLIDAY_EXCLUDED_KEYS,
    _CALENDAR_HOLIDAY_RAW_NAMES,
    _clamp_half_hour,
    _normalize_holiday_key,
    apply_hourly_leave_to_summary,
    clean_event_text_excluding_holidays,
    split_event_and_skipped_holidays,
)


def _escape_ics_text(text):
    """RFC 5545 Section 3.3.11 に従い ICS TEXT 値の特殊文字をエスケープする。"""
    s = str(text or "")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\\", "\\\\")
    s = s.replace(";", "\\;")
    s = s.replace(",", "\\,")
    s = s.replace("\n", "\\n")
    return s


def _prepare_shift_export_fields(shift):
    """シフト1件から出力共通の (is_allday, summary) を算出する。"""
    status = shift.get("status")
    is_allday = bool(status in ("holiday", "paid_leave") or shift.get("is_holiday") or shift.get("is_paid_leave"))
    raw_summary = shift.get("summary") or shift.get("type") or "シフト"
    if not is_allday:
        h_leave = _clamp_half_hour(shift.get("hourly_paid_leave"), 0.0, 0.0, 23.5)
        if h_leave > 0.0:
            raw_summary = apply_hourly_leave_to_summary(raw_summary, h_leave, "work")
    return is_allday, raw_summary


def create_ics(shifts, calendar_name="シフトカレンダー", include_events=True):
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Shift Calendar Importer//JP",
        f"X-WR-CALNAME:{_escape_ics_text(calendar_name)}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH"
    ]
    for s in shifts:
        date_str = s["date"].replace("-", "")
        is_allday, raw_summary = _prepare_shift_export_fields(s)
        summary = _escape_ics_text(raw_summary)
        shift_type = _escape_ics_text(s.get("type") or "")
        uid = f"shift-{date_str}@shift-calendar-app"

        dt = datetime.strptime(s["date"], "%Y-%m-%d")
        next_date_str = (dt + timedelta(days=1)).strftime("%Y%m%d")

        # 終日イベント（休み・有給休暇）
        memo_text = str(s.get("memo") or "").replace("\r", " ").replace("\n", " ").strip()
        memo_suffix = f" / メモ: {_escape_ics_text(memo_text)}" if memo_text else ""

        if is_allday:
            ics_lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{date_str}T000000Z",
                f"DTSTART;VALUE=DATE:{date_str}",
                f"DTEND;VALUE=DATE:{next_date_str}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:区分: {shift_type}{memo_suffix}",
                "END:VEVENT"
            ])
        # 時間指定の出勤イベント
        elif s.get("start_time") and s.get("end_time"):
            start_str = s["start_time"].replace(":", "") + "00"
            end_str = s["end_time"].replace(":", "") + "00"
            dtstart = f"{date_str}T{start_str}"
            dtend = f"{date_str}T{end_str}"
            ics_lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{date_str}T000000Z",
                f"DTSTART;TZID=Asia/Tokyo:{dtstart}",
                f"DTEND;TZID=Asia/Tokyo:{dtend}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:シフト区分: {shift_type}{memo_suffix}",
                "END:VEVENT"
            ])

        # 行事予定（終日イベント：出勤日・休み・有給いずれの日も別イベントとして出力）
        event_text = str(s.get("event") or "").replace("\r", " ").replace("\n", " ").strip()
        if include_events and event_text:
            event_uid = f"event-{date_str}@shift-calendar-app"
            ics_lines.extend([
                "BEGIN:VEVENT",
                f"UID:{event_uid}",
                f"DTSTAMP:{date_str}T000000Z",
                f"DTSTART;VALUE=DATE:{date_str}",
                f"DTEND;VALUE=DATE:{next_date_str}",
                f"SUMMARY:{_escape_ics_text(event_text)}",
                "DESCRIPTION:行事予定",
                "END:VEVENT"
            ])

    ics_lines.append("END:VCALENDAR")
    return "\r\n".join(ics_lines)


def _escape_applescript_str(text):
    return str(text or "").replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ").strip()


def build_apple_calendar_script(shifts, calendar_name="シフトカレンダー", include_events=True):
    script_items = []
    event_count = 0
    for s in shifts:
        d = s["date"] # YYYY-MM-DD
        is_allday, raw_summary = _prepare_shift_export_fields(s)
        summary = _escape_applescript_str(raw_summary)
        shift_type = _escape_applescript_str(s.get("type") or "")
        event_text = _escape_applescript_str(s.get("event") or "")
        memo_text = _escape_applescript_str(s.get("memo") or "")
        memo_suffix = f" / メモ: {memo_text}" if memo_text else ""

        parts = d.split("-")
        y, m, day = int(parts[0]), int(parts[1]), int(parts[2])

        # 重複防止（同日既存イベントの上書き削除用日時）
        delete_and_prep_script = f"""
            set evStart to current date
            set day of evStart to 1
            set year of evStart to {y}
            set month of evStart to {m}
            set day of evStart to {day}
            set hours of evStart to 0
            set minutes of evStart to 0
            set seconds of evStart to 0

            set evEnd to current date
            set day of evEnd to 1
            set year of evEnd to {y}
            set month of evEnd to {m}
            set day of evEnd to {day}
            set hours of evEnd to 23
            set minutes of evEnd to 59
            set seconds of evEnd to 59

            -- 同一日の既存シフト予定を削除（二重登録・前月末/翌月初重複の自動上書き）
            try
                delete (every event of theCal whose start date >= evStart and start date <= evEnd)
            end try
        """

        day_commands = []
        created_shift = False

        # 終日イベント（休み・有給）
        if is_allday:
            day_commands.append(
                f'make new event at end of events of theCal with properties {{summary:"{summary}", start date:evStart, end date:evEnd, allday event:true, description:"区分: {shift_type}{memo_suffix}"}}'
            )
            created_shift = True
            event_count += 1
        # 時間指定（出勤）
        elif s.get("start_time") and s.get("end_time"):
            st_parts = s["start_time"].split(":")
            et_parts = s["end_time"].split(":")
            day_commands.append(f"""
            set hours of evStart to {int(st_parts[0])}
            set minutes of evStart to {int(st_parts[1])}
            set seconds of evStart to 0

            set hours of evEnd to {int(et_parts[0])}
            set minutes of evEnd to {int(et_parts[1])}
            set seconds of evEnd to 0

            make new event at end of events of theCal with properties {{summary:"{summary}", start date:evStart, end date:evEnd, allday event:false, description:"シフト区分: {shift_type}{memo_suffix}"}}
            """)
            created_shift = True
            event_count += 1

        # 行事予定（終日イベント：休み・有給の日でも2件目として両方登録）
        if include_events and event_text:
            day_commands.append(f"""
            set hours of evStart to 0
            set minutes of evStart to 0
            set seconds of evStart to 0
            set hours of evEnd to 23
            set minutes of evEnd to 59
            set seconds of evEnd to 59
            make new event at end of events of theCal with properties {{summary:"{event_text}", start date:evStart, end date:evEnd, allday event:true, description:"行事予定"}}
            """)
            event_count += 1

        if created_shift or (include_events and event_text):
            script_items.append(f"""
            {delete_and_prep_script}
            {"".join(day_commands)}
            """)

    cal_name_escaped = _escape_applescript_str(calendar_name)
    full_script = f"""
    tell application "Calendar"
        activate
        set calName to "{cal_name_escaped}"
        set targetCal to missing value
        repeat with c in calendars
            if name of c is calName then
                set targetCal to c
                exit repeat
            end if
        end repeat
        if targetCal is missing value then
            set targetCal to make new calendar with properties {{name:calName, color:{{65000, 38000, 0}}}}
        else
            try
                set color of targetCal to {{65000, 38000, 0}}
            end try
        end if
        set theCal to targetCal
        {"".join(script_items)}
    end tell
    """
    return full_script, event_count


DEFAULT_OSASCRIPT_TIMEOUT_SEC = 60


def _format_osascript_error(stderr_text):
    """osascript のエラー出力をユーザー向けの分かりやすいメッセージへ整形する。"""
    raw = str(stderr_text or "").strip()
    lower = raw.lower()
    if (
        "-1743" in raw
        or "not authorized" in lower
        or "not permitted" in lower
        or "permission" in lower
        or "権限" in raw
    ):
        return (
            "Appleカレンダーへのアクセス権限がありません。"
            "macOSの「システム設定 → プライバシーとセキュリティ → オートメーション」から"
            "カレンダー操作の許可を有効にしてください。"
            + (f"（詳細: {raw}）" if raw else "")
        )
    return f"カレンダー登録エラー: {raw or 'osascript の実行に失敗しました'}"


def register_to_apple_calendar(shifts, calendar_name="シフトカレンダー", include_events=True, timeout=DEFAULT_OSASCRIPT_TIMEOUT_SEC):
    if not shifts:
        return 0, "登録対象のシフトがありません"

    full_script, event_count = build_apple_calendar_script(shifts, calendar_name, include_events=include_events)

    # 一時スクリプトファイルを経由して安全に実行
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", encoding="utf-8", delete=False) as tf:
        tf.write(full_script)
        temp_path = tf.name

    try:
        try:
            res = subprocess.run(["osascript", temp_path], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Appleカレンダーへの登録がタイムアウトしました（{timeout}秒）。"
                "カレンダーアプリのアクセス許可ダイアログが表示されていないか確認し、再度お試しください。"
            ) from exc
        if res.returncode != 0:
            raise RuntimeError(_format_osascript_error(res.stderr))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return event_count, "登録が完了しました"
