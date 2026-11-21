"""シフトカレンダー登録アプリのドメイン共通ユーティリティ。

config / storage / calendar_export / gemini_client から一方向で参照される
低レイヤーの純粋関数を集約する。
"""
import re
import unicodedata


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
