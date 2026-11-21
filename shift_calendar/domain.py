"""シフトカレンダー登録アプリのドメイン共通ユーティリティ。

config / storage / calendar_export / gemini_client から一方向で参照される
低レイヤーの純粋関数を集約する。
"""
import re


def clamp_int(val, default, min_val, max_val):
    """整数値を min_val〜max_val の範囲に収める。変換不能時は default を返す。"""
    try:
        num = int(val)
    except (TypeError, ValueError):
        return default
    return max(min_val, min(max_val, num))


def clamp_half_hour(val, default=0.0, min_val=0.0, max_val=24.0):
    """数値を0.5時間（30分）刻みに丸め、min_val〜max_valの範囲に収める。"""
    try:
        num = float(val)
    except (TypeError, ValueError):
        num = float(default)
    snapped = round(num * 2.0) / 2.0
    clamped = max(float(min_val), min(float(max_val), snapped))
    return 0.0 if clamped == 0.0 else clamped


def format_hourly_leave_hours(hours):
    """時間有給の数値を表示用文字列（例: '2', '1.5'）に整形する。0以下は空文字。"""
    h = clamp_half_hour(hours, 0.0, 0.0, 24.0)
    if h <= 0.0:
        return ""
    if h.is_integer():
        return str(int(h))
    return f"{h:.1f}"


def apply_hourly_leave_to_summary(summary, hours, status="work"):
    """出勤日のカレンダー登録名末尾に（時間有給Xh）を付記／0時間や休み時は除去する。"""
    base = str(summary or "").strip()
    base = re.sub(r"\s*[（(]時間有給\s*[0-9]+(?:\.[0-9]+)?h[)）]\s*$", "", base).strip()
    h = clamp_half_hour(hours, 0.0, 0.0, 23.5)
    if status == "work" and h > 0.0:
        h_str = format_hourly_leave_hours(h)
        if base:
            return f"{base}（時間有給{h_str}h）"
        return f"時間有給{h_str}h"
    return base


def sanitize_history_id(raw_id):
    """履歴IDから安全な英数字・アンダースコア・ハイフンのみを抽出する。"""
    return "".join(c for c in str(raw_id or "") if c.isalnum() or c in ("_", "-"))


# 既存モジュール・テスト互換用エイリアス
_clamp_int = clamp_int
_clamp_half_hour = clamp_half_hour
