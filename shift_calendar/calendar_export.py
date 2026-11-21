import os
import re
import subprocess
import tempfile
import unicodedata

from shift_calendar.domain import (
    _clamp_half_hour,
    apply_hourly_leave_to_summary,
    format_hourly_leave_hours,
)




# Googleカレンダー「日本の祝日（その他の行事を含む）」相当の除外対象（正規化後キー）
_CALENDAR_HOLIDAY_RAW_NAMES = (
    # 国民の祝日・休日（18種＋表記揺れ・略称）
    "元日", "元旦",
    "成人の日",
    "建国記念の日", "建国記念日",
    "天皇誕生日",
    "春分の日",
    "昭和の日",
    "憲法記念日",
    "みどりの日", "緑の日",
    "こどもの日", "子供の日", "子どもの日", "端午の節句",
    "海の日",
    "山の日",
    "敬老の日",
    "秋分の日",
    "スポーツの日", "体育の日",
    "文化の日",
    "勤労感謝の日",
    "振替休日", "振り替え休日", "振休",
    "国民の休日",
    # Googleカレンダー「日本の祝日（その他の行事を含む）」の主な標準行事・表記揺れ
    "銀行休業日",
    "節分",
    "バレンタインデー", "バレンタイン", "valentine", "valentineday", "valentinesday",
    "ひな祭り", "ひなまつり", "雛祭り", "雛まつり", "桃の節句",
    "母の日",
    "父の日",
    "七夕", "たなばた",
    "ハロウィン", "ハロウィーン", "halloween",
    "七五三",
    "クリスマスイブ", "クリスマスイヴ", "xmasイブ", "xmasイヴ", "xmaseve", "christmaseve",
    "クリスマス", "xmas", "christmas",
    "大晦日", "大みそか", "おおみそか",
)


def _normalize_holiday_key(text):
    """全角/半角・大文字/小文字・記号ゆれ・よくあるOCR誤字を吸収して照合用キーへ正規化する。"""
    s = unicodedata.normalize("NFKC", str(text or "")).strip().lower()
    # 縦書きOCRで起こりやすい誤字の正規化（「曰」→「日」）
    s = s.replace("曰", "日")
    # 括弧・引用符・空白・中黒・ドット・ハイフン等の区切り記号を除去（カタカナ長音「ー」は保持）
    s = re.sub(r"[\s'’\"`.,・/／\-‐‑–—()（）【】\[\]「」『』!！?？]+", "", s)
    return s


CALENDAR_HOLIDAY_EXCLUDED_KEYS = frozenset(
    _normalize_holiday_key(name) for name in _CALENDAR_HOLIDAY_RAW_NAMES
)


def split_event_and_skipped_holidays(event_text):
    """
    行事テキストを「残すべき職場行事」と「スキップした祝日・標準行事リスト」へ分離する。
    - 単体で祝日/一般歳時記に一致する場合は ("", [raw]) を返す。
    - 併記されている場合（例: 「敬老の日・敬老会」「クリスマス / クリスマス会」）は
      祝日側のみを skipped へ移し、職場・施設固有の行事（「敬老会」「クリスマス会」）を保持する。
    - 「クリスマス会」「敬老会」などの職場イベント単体は完全一致しないため誤除外しない。
    """
    raw = str(event_text or "").strip()
    if not raw:
        return "", []
    if _normalize_holiday_key(raw) in CALENDAR_HOLIDAY_EXCLUDED_KEYS:
        return "", [raw]

    # 区切り文字で複数要素が併記されている場合はトークン単位で祝日のみ除外
    parts = [p.strip() for p in re.split(r"[・/／、,\n\r\t　 ]+", raw) if p.strip()]
    if len(parts) > 1:
        kept = []
        skipped = []
        for p in parts:
            if _normalize_holiday_key(p) in CALENDAR_HOLIDAY_EXCLUDED_KEYS:
                skipped.append(p)
            else:
                kept.append(p)
        if not kept:
            return "", skipped
        if skipped:
            return "・".join(kept), skipped
    return raw, []


def clean_event_text_excluding_holidays(event_text):
    """
    Googleカレンダー「日本の祝日（その他の行事を含む）」と重複する祝日・一般歳時記を除外したテキストを返す。
    """
    kept, _ = split_event_and_skipped_holidays(event_text)
    return kept


def create_ics(shifts, calendar_name="シフトカレンダー", include_events=True):
    from datetime import datetime, timedelta
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Shift Calendar Importer//JP",
        f"X-WR-CALNAME:{calendar_name}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH"
    ]
    for idx, s in enumerate(shifts):
        date_str = s["date"].replace("-", "")
        status = s.get("status")
        is_allday = status in ("holiday", "paid_leave") or s.get("is_holiday") or s.get("is_paid_leave")
        raw_summary = s.get("summary") or s.get("type") or "シフト"
        if not is_allday:
            h_leave = _clamp_half_hour(s.get("hourly_paid_leave"), 0.0, 0.0, 23.5)
            if h_leave > 0.0:
                raw_summary = apply_hourly_leave_to_summary(raw_summary, h_leave, "work")
        summary = raw_summary
        uid = f"shift-{date_str}@shift-calendar-app"

        dt = datetime.strptime(s["date"], "%Y-%m-%d")
        next_date_str = (dt + timedelta(days=1)).strftime("%Y%m%d")

        # 終日イベント（休み・有給休暇）
        if status in ("holiday", "paid_leave") or s.get("is_holiday") or s.get("is_paid_leave"):
            ics_lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{date_str}T000000Z",
                f"DTSTART;VALUE=DATE:{date_str}",
                f"DTEND;VALUE=DATE:{next_date_str}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:区分: {s.get('type')}",
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
                f"DESCRIPTION:シフト区分: {s.get('type')}",
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
                f"SUMMARY:{event_text}",
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
        status = s.get("status")
        is_allday = status in ("holiday", "paid_leave") or s.get("is_holiday") or s.get("is_paid_leave")
        raw_summary = s.get("summary") or s.get("type") or "シフト"
        if not is_allday:
            h_leave = _clamp_half_hour(s.get("hourly_paid_leave"), 0.0, 0.0, 23.5)
            if h_leave > 0.0:
                raw_summary = apply_hourly_leave_to_summary(raw_summary, h_leave, "work")
        summary = _escape_applescript_str(raw_summary)
        shift_type = _escape_applescript_str(s.get("type") or "")
        event_text = _escape_applescript_str(s.get("event") or "")

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
        if status in ("holiday", "paid_leave") or s.get("is_holiday") or s.get("is_paid_leave"):
            day_commands.append(
                f'make new event at end of events of theCal with properties {{summary:"{summary}", start date:evStart, end date:evEnd, allday event:true, description:"区分: {shift_type}"}}'
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

            make new event at end of events of theCal with properties {{summary:"{summary}", start date:evStart, end date:evEnd, allday event:false, description:"シフト区分: {shift_type}"}}
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


def register_to_apple_calendar(shifts, calendar_name="シフトカレンダー", include_events=True):
    if not shifts:
        return 0, "登録対象のシフトがありません"

    full_script, event_count = build_apple_calendar_script(shifts, calendar_name, include_events=include_events)

    # 一時スクリプトファイルを経由して安全に実行
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", encoding="utf-8", delete=False) as tf:
        tf.write(full_script)
        temp_path = tf.name

    try:
        res = subprocess.run(["osascript", temp_path], capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"カレンダー登録エラー: {res.stderr.strip()}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return event_count, "登録が完了しました"
