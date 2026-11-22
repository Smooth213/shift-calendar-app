import base64
import json
import re
import time
import urllib.error
import urllib.request

import cv2
import numpy as np

from shift_calendar.config import DEFAULT_TIME_DEFINITIONS
from shift_calendar.domain import split_event_and_skipped_holidays
from shift_calendar.image_processing import (
    build_labeled_event_strip,
    build_labeled_name_column_image,
    build_labeled_ocr_strip,
    detect_active_event_columns,
    detect_active_event_spans,
    detect_table_grid,
    dewarp_table_image,
    dewarp_table_image_with_status,
    optimize_image_for_ai,
    snap_row_band_to_grid,
)

# Gemini API フォールバックモデル定義（軽量・高速モデル優先）
DEFAULT_LITE_MODELS = (
    "gemini-flash-lite-latest",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
)
DEFAULT_SHIFT_MODELS = DEFAULT_LITE_MODELS + ("gemini-flash-latest",)


def post_gemini_generate_content(api_key, model_name, payload, timeout=60):
    """Gemini generateContent API へ共通形式で POST し、レスポンスJSONを返す。

    APIキーは URL クエリに含めず、x-goog-api-key ヘッダーのみで送信する。
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_gemini_text(resp_data):
    """Gemini レスポンスJSONから先頭候補のテキストを取り出し、Markdownコードフェンスを除去する。"""
    text = resp_data["candidates"][0]["content"]["parts"][0]["text"].strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _request_gemini_json_with_fallback(
    api_key,
    payload,
    models,
    timeout,
    log_tag,
    sleep_fn=None,
    on_attempt=None,
    on_rate_limit=None,
    on_error_retry=None,
    first_model_retries=2,
    raise_on_fatal_http=False,
    rate_limit_sleep=1.2,
    error_sleep=1.0,
):
    """複数モデルへのフォールバック＆リトライ付きで Gemini JSON レスポンスを取得する共通ヘルパー。

    成功時は (parsed_json, model_name) を返す。
    全モデル失敗時は (None, last_error_message) を返す（raise_on_fatal_http=True かつ
    404/429/503 以外の HTTP エラー時は即座に RuntimeError を送出する）。
    """
    _sleep = sleep_fn or time.sleep
    last_error = None

    for m_idx, model_name in enumerate(models):
        max_attempts = first_model_retries if m_idx == 0 else 1
        for attempt in range(max_attempts):
            if on_attempt:
                on_attempt(m_idx, model_name, attempt)
            try:
                t_req = time.time()
                resp_data = post_gemini_generate_content(api_key, model_name, payload, timeout=timeout)
                text = extract_gemini_text(resp_data)
                parsed = json.loads(text)
                print(f"[{log_tag}] Response received in {time.time() - t_req:.1f}s ({model_name})", flush=True)
                return parsed, model_name
            except urllib.error.HTTPError as he:
                error_body = ""
                if raise_on_fatal_http:
                    try:
                        error_body = he.read().decode("utf-8")
                    except Exception:
                        error_body = str(he)
                last_error = f"Gemini APIエラー ({he.code}) [{model_name}]: {error_body or he.reason}"
                print(f"[{log_tag}] HTTP {he.code} ({model_name}, attempt {attempt + 1})", flush=True)
                if he.code == 404:
                    break
                if he.code in (429, 503):
                    if on_rate_limit:
                        on_rate_limit(m_idx, model_name, he.code)
                    _sleep(rate_limit_sleep)
                    continue
                if raise_on_fatal_http:
                    raise RuntimeError(last_error)
                break
            except Exception as exc:
                last_error = f"リクエスト失敗 [{model_name}]: {str(exc)}"
                print(f"[{log_tag}] Retry ({model_name}, attempt {attempt + 1}): {exc}", flush=True)
                if on_error_retry:
                    on_error_retry(m_idx, model_name, exc)
                _sleep(error_sleep)
                continue

    return None, last_error


def _parse_event_ocr_response(parsed_data, n_cols, col_to_span_cols):
    """行事予定 OCR の JSON レスポンスを列番号->行事名マップとスキップ祝日一覧へ正規化する。"""
    raw_events = parsed_data.get("events", []) if isinstance(parsed_data, dict) else []
    result = {}
    skipped_records = []
    seen_skipped_keys = set()

    if not isinstance(raw_events, list):
        return result, skipped_records

    for item in raw_events:
        if not isinstance(item, dict):
            continue
        raw_ev_text = str(item.get("event", "")).strip()
        if not raw_ev_text:
            continue

        ev_text, skipped_names = split_event_and_skipped_holidays(raw_ev_text)
        # AIが軽微な誤字等を含めて祝日・標準行事と判定した単体項目も除外・カウント
        if ev_text and not skipped_names and item.get("is_holiday") is True:
            skipped_names = [ev_text]
            ev_text = ""

        raw_col = item.get("col")
        target_cols = []
        if isinstance(raw_col, str) and ("-" in raw_col or "〜" in raw_col or "~" in raw_col):
            norm_col = raw_col.replace("〜", "-").replace("~", "-")
            parts = [p.strip() for p in norm_col.split("-") if p.strip()]
            if len(parts) == 2:
                try:
                    c_start, c_end = int(parts[0]), int(parts[1])
                    if c_start <= c_end and (c_end - c_start) <= 6:
                        target_cols = list(range(c_start, c_end + 1))
                except ValueError:
                    pass
        if not target_cols:
            try:
                c_single = int(raw_col)
                # 単一番号で返ってきた場合も、結合スパンに属していれば両日へ自動展開
                target_cols = col_to_span_cols.get(c_single, [c_single])
            except (TypeError, ValueError):
                continue

        if skipped_names:
            rep_col = target_cols[0] if target_cols else None
            for sname in skipped_names:
                skey = (rep_col, sname)
                if skey not in seen_skipped_keys:
                    seen_skipped_keys.add(skey)
                    skipped_records.append({"col": rep_col, "name": sname})

        if not ev_text:
            continue

        for col_num in target_cols:
            if 1 <= col_num <= n_cols and col_num not in result:
                result[col_num] = ev_text

    return result, skipped_records


def fetch_column_events_from_gemini(
    api_key,
    event_strip_bytes,
    n_cols,
    models_to_try=None,
    active_col_nums=None,
    active_spans=None,
    skipped_holidays_out=None,
    sleep_fn=None,
    progress_fn=None,
):
    """
    【行事予定の独立OCR】
    シフト記号の読み取りパイプラインとは完全に分離されたリクエストで、
    文字が存在する列（結合セルはワイドカード化）だけを並べたコンパクト画像から縦書きテキストを読み取ります。
    結合セル（例: '4-5'）の行事は自動的に該当する全日（4日・5日の両日）へ展開します。
    """
    _set_progress = progress_fn or (lambda *a, **kw: None)
    if not event_strip_bytes or not api_key or n_cols <= 0:
        return {}

    t_start = time.time()
    span_labels = []
    col_to_span_cols = {}
    if active_spans:
        for (s_col, e_col) in active_spans:
            lbl = str(s_col + 1) if s_col == e_col else f"{s_col + 1}-{e_col + 1}"
            span_labels.append(lbl)
            span_nums = list(range(s_col + 1, e_col + 2))
            for cn in span_nums:
                col_to_span_cols[cn] = span_nums

    if span_labels:
        cols_hint = f"（画像内のカード番号: {span_labels}）"
    elif active_col_nums:
        cols_hint = f"（画像内のカード列番号: {active_col_nums}）"
    else:
        cols_hint = f"（列番号 1〜{n_cols}）"

    print(f"[EVENT-OCR] Starting compact OCR (strip={len(event_strip_bytes)} bytes) {cols_hint}...", flush=True)
    event_b64 = base64.b64encode(event_strip_bytes).decode("utf-8")
    event_prompt = f"""この画像は勤務表の下部にある「行事予定欄」のうち、文字が書かれている列だけを切り出して横に並べたカード画像です{cols_hint}。
各カードの上部には赤い文字で「列番号(col)」が書かれており（複数日にわたる結合セルは "4-5" のように範囲で記載）、その下に縦書きで「行事予定・イベント名」が書かれています。

【厳守ルール】
1. 左のカードから順番に、上部の赤い列番号(col)と、その下の縦書き文字(event)を読み取ってJSONで出力してください。
2. カード上部に "4-5" のようにハイフン付きの範囲番号がある場合は複数日にまたがる行事なので、"col": "4-5" のようにそのまま出力してください。
3. 縦書きの文字は上から下へ読み、通常の横書きテキストにして "event" に入れてください。
4. 矢印や丸印などの記号だけで文字が書かれていないカードは出力しないでください。
5. 濃いグレー背景（日曜日・祝日など）のカード内の文字も見落とさず読み取ってください。
6. 日本の祝日・休日（文化の日、勤労感謝の日、元日、元旦など）や大晦日・クリスマス（縦書きの Xmas などアルファベット表記を含む）のカードも、絶対に省略せずすべてそのまま読み取って出力してください（重複スキップの判定と件数集計はアプリ側で行います）。

【出力JSONフォーマット】
{{
  "events": [
    {{"col": "4-5", "event": "感謝祭"}},
    {{"col": 10, "event": "主任会議"}},
    {{"col": 27, "event": "Xmas"}},
    {{"col": 33, "event": "大晦日"}},
    {{"col": 34, "event": "元旦"}}
  ]
}}
"""
    event_payload = {
        "contents": [{
            "parts": [
                {"text": event_prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": event_b64}},
            ]
        }],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.0,
            "maxOutputTokens": 1024,
        },
    }

    event_models = list(models_to_try) if models_to_try else list(DEFAULT_LITE_MODELS)
    parsed, model_or_err = _request_gemini_json_with_fallback(
        api_key=api_key,
        payload=event_payload,
        models=event_models,
        timeout=15,
        log_tag="EVENT-OCR",
        sleep_fn=sleep_fn,
        on_attempt=lambda m_idx, m_name, attempt: _set_progress(
            88 + min(8, m_idx * 2 + attempt),
            "ステップ 4/4: 縦書きの行事予定をAIで読み取り中...",
            f"モデル: {m_name} (試行 {attempt + 1}) {cols_hint}",
            step=4,
            active=True,
        ),
        on_rate_limit=lambda _m_idx, m_name, code: _set_progress(
            90,
            "ステップ 4/4: 縦書きの行事予定をAIで読み取り中...",
            f"API混雑({code})のため別モデルへ切替・再試行中 ({m_name})...",
            step=4,
            active=True,
        ),
        first_model_retries=2,
        raise_on_fatal_http=False,
        rate_limit_sleep=1.5,
        error_sleep=1.0,
    )
    if parsed is None:
        return {}

    result, skipped_records = _parse_event_ocr_response(parsed, n_cols, col_to_span_cols)
    if isinstance(skipped_holidays_out, list):
        skipped_holidays_out.clear()
        skipped_holidays_out.extend(skipped_records)
    print(
        f"[EVENT-OCR] Completed in {time.time() - t_start:.1f}s ({model_or_err}): "
        f"{len(result)} events, {len(skipped_records)} skipped holidays -> {result}",
        flush=True,
    )
    return result


def analyze_events_only(
    api_key,
    image_bytes,
    dewarp_fn=None,
    detect_grid_fn=None,
    fetch_events_fn=None,
    progress_fn=None,
    detect_spans_fn=None,
    build_strip_fn=None,
):
    """
    【Step 2（独立API）: 下部「縦書き行事予定」のみの解析】
    Step 1 でシフト記号を表示した後に呼び出され、行事予定のみを抽出して返します。
    """
    _dewarp = dewarp_fn or dewarp_table_image
    _detect_grid = detect_grid_fn or detect_table_grid
    _fetch_events = fetch_events_fn or fetch_column_events_from_gemini
    _set_progress = progress_fn or (lambda *a, **kw: None)
    _detect_spans = detect_spans_fn or detect_active_event_spans
    _build_strip = build_strip_fn or build_labeled_event_strip

    _set_progress(80, "ステップ 4/4: 下部の行事予定セルを切り出し中...", "グリッドと文字領域を解析しています", step=4, active=True)
    processed_bytes, _ = _dewarp(image_bytes, api_key)
    grid_info = _detect_grid(processed_bytes)
    if not grid_info:
        _set_progress(100, "解析完了", "グリッド未検出のため行事予定をスキップしました", step=4, active=False)
        return {"events": {}, "active_cols": [], "n_cols": 0}

    proc_img = cv2.imdecode(np.frombuffer(processed_bytes, np.uint8), cv2.IMREAD_COLOR)
    if proc_img is None:
        _set_progress(100, "解析完了", "画像デコードスキップ", step=4, active=False)
        return {"events": {}, "active_cols": [], "n_cols": grid_info["n_cols"]}

    active_spans = _detect_spans(proc_img, grid_info)
    active_col_nums = []
    for (s_col, e_col) in active_spans:
        for cn in range(s_col + 1, e_col + 2):
            if cn not in active_col_nums:
                active_col_nums.append(cn)
    if not active_spans:
        _set_progress(100, "解析完了", "行事予定の記載はありませんでした", step=4, active=False)
        return {"events": {}, "active_cols": [], "n_cols": grid_info["n_cols"]}

    event_strip_bytes = _build_strip(proc_img, grid_info)
    if not event_strip_bytes:
        _set_progress(100, "解析完了", "行事予定欄が存在しませんでした", step=4, active=False)
        return {"events": {}, "active_cols": active_col_nums, "n_cols": grid_info["n_cols"]}

    skipped_holidays = []
    col_events = _fetch_events(
        api_key,
        event_strip_bytes,
        grid_info["n_cols"],
        active_col_nums=active_col_nums,
        active_spans=active_spans,
        skipped_holidays_out=skipped_holidays,
    ) or {}

    skipped_count = len(skipped_holidays)
    if col_events:
        skip_suffix = f"（日本の祝日等 {skipped_count} 件スキップ）" if skipped_count > 0 else ""
        _set_progress(100, "すべての解析が完了しました", f"行事予定を {len(col_events)} 件抽出しました{skip_suffix}", step=4, active=False)
    elif skipped_count > 0:
        _set_progress(100, "すべての解析が完了しました", f"日本の祝日・標準行事 {skipped_count} 件をスキップしました（職場行事なし）", step=4, active=False)
    else:
        _set_progress(100, "シフト解析完了（行事予定は未取得）", "API混雑のため行事予定を取得できませんでした（「行事のみ再取得」で再試行できます）", step=4, active=False)

    events_dict = {str(k): v for k, v in col_events.items()}
    return {
        "events": events_dict,
        "active_cols": active_col_nums,
        "n_cols": grid_info["n_cols"],
        "extracted_count": len(col_events),
        "skipped_holidays_count": skipped_count,
        "skipped_holidays": skipped_holidays,
    }


def _identify_target_row(api_key, proc_img, grid_info, target_name, progress_fn, sleep_fn):
    """氏名列ラベル画像から対象スタッフの行インデックスを特定する。見つからない場合は None。"""
    name_col_bytes, n_rows = build_labeled_name_column_image(proc_img, grid_info)
    if not name_col_bytes or n_rows < 3:
        return None

    name_b64 = base64.b64encode(name_col_bytes).decode("utf-8")
    row_prompt = f"""この画像は勤務表の左端「氏名列」の各行に赤文字で ROW 0, ROW 1, ROW 2, ... の行番号を付けたものです。
スタッフ「{target_name}」の名前が書かれている行の番号（整数）を特定し、以下のJSONのみで出力してください。
{{"row_index": 8, "matched_name": "{target_name}"}}"""
    row_payload = {
        "contents": [{"parts": [{"text": row_prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": name_b64}}]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }

    parsed, _ = _request_gemini_json_with_fallback(
        api_key=api_key,
        payload=row_payload,
        models=DEFAULT_LITE_MODELS,
        timeout=20,
        log_tag="PHASE2",
        sleep_fn=sleep_fn,
        on_attempt=lambda r_idx, m_name, _attempt: progress_fn(
            34 + min(10, r_idx * 2),
            f"ステップ 2/4: 「{target_name}」の行位置を特定中...",
            f"モデル: {m_name} (全 {grid_info['n_cols']} 列検出済み)",
            step=2,
            active=True,
        ),
        first_model_retries=1,
        raise_on_fatal_http=False,
        rate_limit_sleep=1.0,
        error_sleep=1.0,
    )
    if not isinstance(parsed, dict):
        return None
    try:
        cand_idx = int(parsed.get("row_index", -1))
    except (TypeError, ValueError):
        return None
    if 2 <= cand_idx < len(grid_info["h_lines"]) - 1:
        print(f"[PHASE2] Identified '{target_name}' at exact ROW {cand_idx} (matched: {parsed.get('matched_name')})", flush=True)
        return cand_idx
    return None


def _build_shift_ocr_prompt_and_image(target_name, processed_bytes, grid_info, exact_row_idx, ocr_strip_bytes):
    """シフト記号 OCR 用のプロンプト文字列と Base64 画像を構築する。"""
    if ocr_strip_bytes and grid_info and exact_row_idx is not None:
        img_b64 = base64.b64encode(ocr_strip_bytes).decode("utf-8")
        n_cols = grid_info["n_cols"]
        prompt = f"""この画像は勤務表のタイトル（上段）と、対象者「{target_name}」のシフトを列番号 1〜{n_cols} の赤い数字付きで拡大切り出しした専用画像です。
各列番号（1 から {n_cols} まで）の下には、縦に3段で
  ・1段目: 日付（数字）
  ・2段目: 曜日（日/月/火/水/木/金/土）
  ・3段目: 「{target_name}」のシフト記号（例: 休, 早A, 早B, 早C, 早D, 日, 遅A, 遅B, 遅C, 有, ①, ②, ③, ④ 等）
が並んでいます。

【厳守ルール】
1. 上段のタイトル（例: R 8年 12月 → year: 2026, main_month: 12、R 8年 11月 → year: 2026, main_month: 11）から西暦年(year)と対象月(main_month)を読み取ってください（令和8年 = 2026年）。
2. 赤い列番号 1 から {n_cols} まで、1つも飛ばさず・重複させず、必ず全 {n_cols} 件を順番に出力してください。
3. 各列番号の真下にある3段目の文字をそのまま正確に shift_text に転記してください（早B と 早A、休 と 早B 等を絶対に混同しないでください）。
4. 各列の読み取り確信度を confidence ("high" / "medium" / "low") で出力してください。文字がかすれている・潰れている・迷う場合は "medium" または "low" にしてください。

【出力JSONフォーマット】
{{
  "year": 2026,
  "main_month": 12,
  "target_name": "{target_name}",
  "columns": [
    {{
      "col": 1,
      "date": 29,
      "day_of_week": "日",
      "shift_text": "休",
      "confidence": "high"
    }}
  ]
}}
"""
        return prompt, img_b64

    col_count_hint = (
        f"\n- 【幾何学検出済み】この表の有効な日付列数は厳密に【全 {grid_info['n_cols']} 列】です。必ず 1 列目から {grid_info['n_cols']} 列目まで 1 列の過不足もなく出力してください。"
        if grid_info else ""
    )
    optimized_bytes = optimize_image_for_ai(processed_bytes)
    img_b64 = base64.b64encode(optimized_bytes).decode("utf-8")
    prompt = f"""この正面に垂直・平行補正された勤務表画像において、指定されたスタッフ「{target_name}」のシフトを全列（左端から右端まで）読み取ってください。

【最重要：対象者「{target_name}」の名前セル特定ルール】
- 表の左端氏名列において、「{target_name}」の名前セルを正確に特定し、その境界矩形 "target_name_box_2d": [ymin, xmin, ymax, xmax] (0〜1000の正規化座標) を出力してください。
- 上下の隣接行のスタッフと絶対に混同せず、「{target_name}」本人の行のみを横方向に追跡してください。

【最重要：列アライメント（日付ズレ防止ルール）】
- 表最上部の日付ヘッダー（例: 29, 30, 1, 2, 3, 4, ...）と曜日ヘッダーを1日も飛ばさずに全列追跡してください。{col_count_hint}
- 表の「日曜日列（縦全体が黒または濃い網掛けの列）」を目印ピンとして、1列の狂いもなく各日付と「{target_name}」のマス目を対応付けてください。

【出力JSONフォーマット】
{{
  "year": 2026,
  "main_month": 12,
  "target_name": "{target_name}",
  "target_name_box_2d": [ymin, xmin, ymax, xmax],
  "columns": [
    {{
      "col": 1,
      "date": 29,
      "day_of_week": "日",
      "is_sunday": true,
      "shift_text": "休",
      "confidence": "high",
      "box_2d": [ymin, xmin, ymax, xmax]
    }}
  ]
}}
"""
    return prompt, img_b64


def _resolve_target_row_band(parsed_res, grid_info, exact_row_idx):
    """対象者行の上下Y座標帯 (ref_ymin, ref_ymax) を決定する。"""
    if grid_info and exact_row_idx is not None:
        return grid_info["h_lines_norm"][exact_row_idx], grid_info["h_lines_norm"][exact_row_idx + 1]

    ref_ymin = None
    ref_ymax = None
    target_box = parsed_res.get("target_name_box_2d")
    if isinstance(target_box, list) and len(target_box) == 4 and target_box[2] > target_box[0]:
        ref_ymin = target_box[0]
        ref_ymax = target_box[2]

    if grid_info and ref_ymin is not None and ref_ymax is not None:
        ref_ymin, ref_ymax = snap_row_band_to_grid(grid_info, ref_ymin, ref_ymax)

    return ref_ymin, ref_ymax


def normalize_shift_columns(parsed_res, grid_info=None, exact_row_idx=None):
    """Gemini の columns / shifts 出力から日付(YYYY-MM-DD)・座標付きのシフト配列を構築する純粋関数。"""
    ref_ymin, ref_ymax = _resolve_target_row_band(parsed_res, grid_info, exact_row_idx)
    raw_columns = parsed_res.get("columns", [])
    main_year = int(parsed_res.get("year", 2026))
    main_month = int(parsed_res.get("main_month", 12))

    shifts = []
    if raw_columns:
        first_day_1_idx = None
        for i, c in enumerate(raw_columns):
            try:
                d_val = int(str(c.get("date", "")).replace("日", "").strip())
                if d_val == 1:
                    first_day_1_idx = i
                    break
            except (TypeError, ValueError):
                continue

        for i, c in enumerate(raw_columns):
            try:
                d_val = int(str(c.get("date", "")).replace("日", "").strip())
            except (TypeError, ValueError):
                continue

            dow = str(c.get("day_of_week", "")).strip()
            st_type = str(c.get("shift_text", c.get("sarada_text", c.get("type", "")))).strip()
            box = c.get("box_2d")

            # 月の判定（前月・当月・翌月）
            if first_day_1_idx is not None and i < first_day_1_idx:
                m = main_month - 1
                y = main_year
                if m < 1:
                    m = 12
                    y -= 1
            elif first_day_1_idx is not None and i > first_day_1_idx and (d_val == 1 or (i > 25 and d_val <= 15)):
                m = main_month + 1
                y = main_year
                if m > 12:
                    m = 1
                    y += 1
            else:
                m = main_month
                y = main_year

            date_str = f"{y:04d}-{m:02d}-{d_val:02d}"

            # 幾何学グリッド座標（実罫線交点）へ厳密に吸着
            col_idx = len(shifts)
            if (
                grid_info
                and ref_ymin is not None
                and ref_ymax is not None
                and col_idx < len(grid_info["grid_x_norm"]) - 1
            ):
                box = [
                    ref_ymin,
                    grid_info["grid_x_norm"][col_idx],
                    ref_ymax,
                    grid_info["grid_x_norm"][col_idx + 1],
                ]
            elif ref_ymin is not None and ref_ymax is not None and isinstance(box, list) and len(box) == 4:
                box = [ref_ymin, box[1], ref_ymax, box[3]]

            raw_conf = str(c.get("confidence", "high") or "high").strip().lower()
            conf_val = raw_conf if raw_conf in ("high", "medium", "low") else "high"

            shifts.append({
                "date": date_str,
                "day_of_week": dow,
                "type": st_type,
                "confidence": conf_val,
                "box_2d": box,
            })
    else:
        shifts = list(parsed_res.get("shifts", []))
        if ref_ymin is not None and ref_ymax is not None:
            for s in shifts:
                box = s.get("box_2d")
                if isinstance(box, list) and len(box) == 4:
                    s["box_2d"] = [ref_ymin, box[1], ref_ymax, box[3]]

    return shifts, main_year, main_month


def enrich_shift_records(shifts, master_definitions=None):
    """各シフト要素に status / start_time / end_time / summary / event を補完する。"""
    defs = master_definitions or DEFAULT_TIME_DEFINITIONS
    for s in shifts:
        st_type = str(s.get("type", "")).strip()
        if st_type in ("休", "休み") or s.get("status") == "holiday":
            s["status"] = "holiday"
            s["is_holiday"] = True
            s["is_paid_leave"] = False
            s["start_time"] = None
            s["end_time"] = None
            s["summary"] = "休み"
        elif st_type in ("㊒", "有", "有給", "有休") or s.get("status") == "paid_leave":
            s["status"] = "paid_leave"
            s["is_holiday"] = False
            s["is_paid_leave"] = True
            s["start_time"] = None
            s["end_time"] = None
            s["summary"] = "有給休暇"
        else:
            s["status"] = "work"
            s["is_holiday"] = False
            s["is_paid_leave"] = False
            if st_type in defs and (not s.get("start_time") or not s.get("end_time")):
                s["start_time"] = defs[st_type].get("start")
                s["end_time"] = defs[st_type].get("end")

            time_info = f" ({s['start_time']}〜{s['end_time']})" if s.get("start_time") else ""
            s["summary"] = f"[{st_type}]{time_info}"
        s["event"] = str(s.get("event") or "").strip()
        raw_conf = str(s.get("confidence") or "high").strip().lower()
        s["confidence"] = raw_conf if raw_conf in ("high", "medium", "low") else "high"
    return shifts


def evaluate_shift_quality(shifts, master_definitions=None):
    """解析済みシフト配列の読み取り精度・異常を評価し、各要素へ quality_level / quality_reasons を付与する。

    戻り値: {"score_percent": int, "total": int, "ok_count": int, "warning_count": int, "error_count": int, "review_count": int}
    """
    defs = master_definitions or DEFAULT_TIME_DEFINITIONS
    if not isinstance(shifts, list) or not shifts:
        return {
            "score_percent": 100,
            "total": 0,
            "ok_count": 0,
            "warning_count": 0,
            "error_count": 0,
            "review_count": 0,
        }

    date_counts = {}
    for s in shifts:
        if isinstance(s, dict):
            d = str(s.get("date") or "").strip()
            if d:
                date_counts[d] = date_counts.get(d, 0) + 1

    consecutive_work = 0
    ok_count = 0
    warning_count = 0
    error_count = 0
    score_sum = 0.0

    for s in shifts:
        if not isinstance(s, dict):
            continue
        reasons = []
        level = "ok"

        date_str = str(s.get("date") or "").strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            level = "error"
            reasons.append("日付形式が不正です")
        elif date_counts.get(date_str, 0) > 1:
            level = "error"
            reasons.append("同一日付が重複しています")

        status = str(s.get("status") or "work")
        st_type = str(s.get("type") or "").strip()
        is_work = status == "work" and not s.get("is_holiday") and not s.get("is_paid_leave")

        if is_work:
            consecutive_work += 1
            if not st_type:
                level = "error"
                reasons.append("シフト記号が空です")
            elif st_type not in defs and (not s.get("start_time") or not s.get("end_time")):
                level = "error"
                reasons.append(f"未定義のシフト記号です ({st_type})")
            elif not s.get("start_time") or not s.get("end_time"):
                if level != "error":
                    level = "warning"
                reasons.append("開始・終了時刻が未設定です")
            if consecutive_work >= 6:
                if level != "error":
                    level = "warning"
                reasons.append(f"{consecutive_work}連勤になっています（要確認）")
        else:
            consecutive_work = 0

        conf = str(s.get("confidence") or "high").strip().lower()
        if conf == "low":
            if level != "error":
                level = "warning"
            reasons.append("AI読み取り確信度が低いセルです")
        elif conf == "medium":
            if level != "error":
                level = "warning"
            reasons.append("AI読み取り確信度が中程度です")

        s["quality_level"] = level
        s["quality_reasons"] = reasons

        if level == "error":
            error_count += 1
            score_sum += 0.0
        elif level == "warning":
            warning_count += 1
            score_sum += 0.6
        else:
            ok_count += 1
            score_sum += 1.0

    total = ok_count + warning_count + error_count
    score_percent = int(round((score_sum / total) * 100)) if total > 0 else 100
    return {
        "score_percent": max(0, min(100, score_percent)),
        "total": total,
        "ok_count": ok_count,
        "warning_count": warning_count,
        "error_count": error_count,
        "review_count": warning_count + error_count,
    }


def call_gemini_api(
    api_key,
    image_bytes,
    mime_type,
    target_name,
    master_definitions=None,
    dewarp_status_fn=None,
    detect_grid_fn=None,
    progress_fn=None,
    sleep_fn=None,
):
    del mime_type
    _dewarp_with_status = dewarp_status_fn or dewarp_table_image_with_status
    _detect_grid = detect_grid_fn or detect_table_grid
    _set_progress = progress_fn or (lambda *a, **kw: None)
    _sleep = sleep_fn or time.sleep
    defs = master_definitions or DEFAULT_TIME_DEFINITIONS

    # 【Phase 1】たわみ・撮影角度の歪みを正面の真っ直ぐな長方形グリッドに平坦化
    _set_progress(10, "ステップ 1/4: 画像の歪み・たわみを補正中...", "OpenCV ホモグラフィ＋メッシュ歪み補正を実行しています", step=1, active=True)
    processed_bytes, corrected_b64, dewarp_status = _dewarp_with_status(image_bytes, api_key)

    # 【Phase 2】平坦化画像から全横罫線および全日付列の縦区切り線を幾何学的に確定
    _set_progress(24, "ステップ 2/4: 罫線グリッドと日付列を検出中...", "横罫線および日付列の縦区切り線を抽出しています", step=2, active=True)
    grid_info = _detect_grid(processed_bytes) if corrected_b64 else None
    exact_row_idx = None
    ocr_strip_bytes = None
    active_event_col_nums = []

    if grid_info:
        proc_img = cv2.imdecode(np.frombuffer(processed_bytes, np.uint8), cv2.IMREAD_COLOR)
        if proc_img is not None:
            active_cols = detect_active_event_columns(proc_img, grid_info)
            active_event_col_nums = [k + 1 for k in active_cols]
            exact_row_idx = _identify_target_row(api_key, proc_img, grid_info, target_name, _set_progress, _sleep)
            if exact_row_idx is not None:
                ocr_strip_bytes = build_labeled_ocr_strip(proc_img, grid_info, exact_row_idx)

    prompt, img_b64 = _build_shift_ocr_prompt_and_image(
        target_name, processed_bytes, grid_info, exact_row_idx, ocr_strip_bytes
    )
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}},
            ]
        }],
        "generationConfig": {"response_mime_type": "application/json"},
    }

    # Phase 2 直後のバースト 503 を防ぐための短いクールダウン
    if exact_row_idx is not None:
        _sleep(0.4)

    try:
        parsed_res, model_or_err = _request_gemini_json_with_fallback(
            api_key=api_key,
            payload=payload,
            models=DEFAULT_SHIFT_MODELS,
            timeout=25,
            log_tag="SHIFT-OCR",
            sleep_fn=_sleep,
            on_attempt=lambda m_idx, m_name, attempt: _set_progress(
                50 + min(20, m_idx * 4 + attempt * 2),
                "ステップ 3/4: シフト記号をAIで読み取り中...",
                f"モデル: {m_name} (試行 {attempt + 1})",
                step=3,
                active=True,
            ),
            on_rate_limit=lambda m_idx, m_name, code: _set_progress(
                54 + min(18, m_idx * 3),
                "ステップ 3/4: シフト記号をAIで読み取り中...",
                f"API混雑({code})のため別モデルへ切替・再試行中 ({m_name})...",
                step=3,
                active=True,
            ),
            on_error_retry=lambda m_idx, m_name, _exc: _set_progress(
                54 + min(18, m_idx * 3),
                "ステップ 3/4: シフト記号をAIで読み取り中...",
                f"応答待機タイムアウトのため別モデルへ切替中 ({m_name})...",
                step=3,
                active=True,
            ),
            first_model_retries=2,
            raise_on_fatal_http=True,
            rate_limit_sleep=1.2,
            error_sleep=1.0,
        )
    except RuntimeError as fatal_err:
        _set_progress(0, "解析エラー", str(fatal_err), step=3, active=False)
        raise

    if parsed_res is None:
        err_msg = model_or_err or "全モデルへのリクエストに失敗しました"
        _set_progress(0, "解析エラー", err_msg, step=3, active=False)
        raise RuntimeError(err_msg)

    shifts, main_year, main_month = normalize_shift_columns(parsed_res, grid_info=grid_info, exact_row_idx=exact_row_idx)
    enrich_shift_records(shifts, master_definitions=defs)
    quality_summary = evaluate_shift_quality(shifts, master_definitions=defs)

    has_events_candidate = bool(active_event_col_nums)
    _set_progress(
        75 if has_events_candidate else 100,
        "ステップ 3/4: シフト記号の読み取り完了" if has_events_candidate else "解析完了",
        f"全 {len(shifts)} 日分のシフトを抽出しました" + ("（続けて行事予定を読み取ります）" if has_events_candidate else ""),
        step=3 if has_events_candidate else 4,
        active=has_events_candidate,
    )

    parsed_res["shifts"] = shifts
    parsed_res["quality_summary"] = quality_summary
    parsed_res["year_month"] = f"{main_year:04d}-{main_month:02d}"
    parsed_res["corrected_image_base64"] = corrected_b64
    parsed_res["dewarp_status"] = dewarp_status
    parsed_res["has_event_candidates"] = has_events_candidate
    parsed_res["active_event_cols"] = active_event_col_nums
    return parsed_res
