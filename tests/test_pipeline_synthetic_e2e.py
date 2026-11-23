"""外部実写真に依存しない合成勤務表画像を用いたフルパイプライン結合テスト（テストピラミッド頂点層）"""
import json
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from shift_calendar import calendar_export, gemini_client, image_processing


def _build_synthetic_shift_sheet(
    num_cols=36,
    num_staff_rows=8,
    event_row_height=110,
    staff_row_height=42,
    tilt_deg=0.0,
    with_background_noise=False,
    event_col_indices=(4, 12, 24),
):
    """勤務表（スタッフ行＋最下部縦長行事行＋任意で傾き・背景ノイズ）の合成JPEGを生成する。"""
    col_w = 40
    table_w = num_cols * col_w
    table_h = num_staff_rows * staff_row_height + event_row_height
    margin = 140 if (tilt_deg != 0.0 or with_background_noise) else 40
    canvas_w = table_w + margin * 2
    canvas_h = table_h + margin * 2

    if with_background_noise:
        rng = np.random.default_rng(2026)
        canvas = rng.integers(145, 195, size=(canvas_h, canvas_w, 3), dtype=np.uint8)
        # 紙領域を白く描画
        cv2.rectangle(canvas, (margin - 18, margin - 18), (margin + table_w + 18, margin + table_h + 18), (252, 252, 252), -1)
    else:
        canvas = np.full((canvas_h, canvas_w, 3), 255, dtype=np.uint8)

    x0, y0 = margin, margin
    xs = [x0 + i * col_w for i in range(num_cols + 1)]
    ys = [y0 + i * staff_row_height for i in range(num_staff_rows + 1)]
    ys.append(ys[-1] + event_row_height)

    # 縦線・横線を描画
    for x in xs:
        cv2.line(canvas, (x, ys[0]), (x, ys[-1]), (25, 25, 25), 2)
    for y in ys:
        cv2.line(canvas, (xs[0], y), (xs[-1], y), (25, 25, 25), 2)

    # 行事行（最下部）の指定列に縦書きテキスト風の黒い文字ストロークを描画
    ev_y1, ev_y2 = ys[-2], ys[-1]
    for col_idx in event_col_indices:
        if 0 <= col_idx < num_cols:
            cx = (xs[col_idx] + xs[col_idx + 1]) // 2
            for k in range(3):
                cy = ev_y1 + 24 + k * 24
                cv2.putText(canvas, "A", (cx - 8, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 2, cv2.LINE_AA)

    if tilt_deg != 0.0:
        center = (canvas_w / 2.0, canvas_h / 2.0)
        rot_m = cv2.getRotationMatrix2D(center, tilt_deg, 0.94)
        border_val = (170, 170, 170) if with_background_noise else (255, 255, 255)
        canvas = cv2.warpAffine(canvas, rot_m, (canvas_w, canvas_h), borderValue=border_val)

    ok, buf = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 95])
    assert ok
    return buf.tobytes()


class TestSyntheticPipelineE2E(unittest.TestCase):
    """合成勤務表を用いた画像補正〜グリッド検出〜行事抽出〜ICS出力の一気通貫テスト"""

    def test_01_warped_table_full_pipeline_dewarp_grid_snap_and_event_spans(self):
        """斜め・ノイズ付き36列勤務表で 歪み補正→グリッド検出→行スナップ→行事帯・列抽出→ストリップ生成 が一気通貫で成功すること"""
        raw_jpg = _build_synthetic_shift_sheet(
            num_cols=36,
            num_staff_rows=8,
            event_row_height=115,
            tilt_deg=10.0,
            with_background_noise=True,
            event_col_indices=(5, 14, 27),
        )
        dewarped_bytes, warped_b64, status = image_processing.dewarp_table_image_with_status(raw_jpg)
        self.assertEqual(status, "applied")
        self.assertIsNotNone(warped_b64)
        self.assertGreater(len(dewarped_bytes), 1000)

        grid = image_processing.detect_table_grid(dewarped_bytes)
        self.assertIsNotNone(grid)
        self.assertGreaterEqual(grid["n_cols"], 30)
        self.assertGreaterEqual(len(grid["h_lines_norm"]), 8)

        # 中間スタッフ行のスナップが実横罫線に吸着すること
        mid_top = grid["h_lines_norm"][3]
        mid_bot = grid["h_lines_norm"][4]
        snapped_y1, snapped_y2 = image_processing.snap_row_band_to_grid(grid, mid_top + 4.0, mid_bot - 4.0)
        self.assertEqual((snapped_y1, snapped_y2), (mid_top, mid_bot))

        # 最下部の行事予定行帯と文字あり列スパンが検出され、ラベル付きストリップJPEGが生成できること
        arr = np.frombuffer(dewarped_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        self.assertIsNotNone(img)
        event_band = image_processing.detect_event_row_band(grid, img=img)
        self.assertIsNotNone(event_band)
        spans = image_processing.detect_active_event_spans(img, grid, band=event_band)
        self.assertGreaterEqual(len(spans), 1)
        strip_bytes = image_processing.build_labeled_event_strip(img, grid)
        self.assertIsNotNone(strip_bytes)
        strip_img = cv2.imdecode(np.frombuffer(strip_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(strip_img)

    def test_02_clean_35col_table_pipeline_and_ocr_strip_generation(self):
        """35列の整った勤務表で 歪み補正べき等性→35列グリッド→名前列画像＆OCRストリップ生成 が正常動作すること"""
        raw_jpg = _build_synthetic_shift_sheet(
            num_cols=35,
            num_staff_rows=9,
            event_row_height=105,
            tilt_deg=0.0,
            with_background_noise=False,
            event_col_indices=(6, 18),
        )
        dewarped_bytes, _warped_b64, status = image_processing.dewarp_table_image_with_status(raw_jpg)
        self.assertIn(status, ("applied", "already_dewarped"))

        grid = image_processing.detect_table_grid(dewarped_bytes)
        self.assertIsNotNone(grid)
        self.assertEqual(grid["n_cols"], 35)

        img = cv2.imdecode(np.frombuffer(dewarped_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        name_col_jpg, n_rows = image_processing.build_labeled_name_column_image(img, grid)
        self.assertIsNotNone(name_col_jpg)
        self.assertGreaterEqual(n_rows, 8)
        self.assertIsNotNone(cv2.imdecode(np.frombuffer(name_col_jpg, dtype=np.uint8), cv2.IMREAD_COLOR))

        ocr_strip_jpg = image_processing.build_labeled_ocr_strip(img, grid, target_row_idx=3)
        self.assertIsNotNone(ocr_strip_jpg)
        self.assertIsNotNone(cv2.imdecode(np.frombuffer(ocr_strip_jpg, dtype=np.uint8), cv2.IMREAD_COLOR))

    def test_03_full_analysis_to_ics_export_pipeline_with_mocked_gemini(self):
        """合成画像＋モックGemini応答から シフト正規化→品質評価→行事抽出（祝日スキップ）→ICS生成 まで一気通貫で動作すること"""
        raw_jpg = _build_synthetic_shift_sheet(
            num_cols=36,
            num_staff_rows=8,
            event_row_height=110,
            tilt_deg=0.0,
            event_col_indices=(5, 10),
        )
        time_defs = {
            "早A": {"start": "06:00", "end": "15:00"},
            "日": {"start": "08:30", "end": "17:30"},
        }
        # 1) シフト正規化＋補完＋品質評価
        parsed_res = {
            "year": 2026,
            "main_month": 11,
            "columns": [
                {"col": 5, "date": 1, "day_of_week": "日", "shift_text": "早A"},
                {"col": 6, "date": 2, "day_of_week": "月", "shift_text": "日"},
                {"col": 7, "date": 3, "day_of_week": "火", "shift_text": "休"},
                {"col": 8, "date": 4, "day_of_week": "水", "shift_text": "有給"},
            ],
        }
        grid = image_processing.detect_table_grid(raw_jpg)
        self.assertIsNotNone(grid)
        shifts, main_year, main_month = gemini_client.normalize_shift_columns(
            parsed_res,
            grid_info=grid,
            exact_row_idx=2,
        )
        self.assertEqual((main_year, main_month), (2026, 11))
        enriched = gemini_client.enrich_shift_records(shifts, time_defs)
        self.assertEqual(len(enriched), 4)
        enriched[1]["hourly_paid_leave"] = 1.5
        enriched[1]["memo"] = "引き継ぎあり"

        quality = gemini_client.evaluate_shift_quality(enriched, time_defs)
        self.assertEqual(quality["error_count"], 0)

        # 2) 行事抽出（Gemini応答をモックし、祝日が除外され職場行事のみ残ることを確認）
        mock_event_resp = {"events": [{"col": "6", "event": "文化の日"}, {"col": "11", "event": "主任会議"}]}
        with patch.object(gemini_client, "_request_gemini_json_with_fallback", return_value=(mock_event_resp, "mock-model")):
            ev_result = gemini_client.analyze_events_only("dummy-key", raw_jpg)
        self.assertIsInstance(ev_result, dict)
        self.assertIn("events", ev_result)
        self.assertEqual(ev_result.get("skipped_holidays_count"), 1)
        skipped_names = [item.get("name") for item in ev_result.get("skipped_holidays", [])]
        self.assertIn("文化の日", skipped_names)
        self.assertEqual(ev_result["events"].get("11"), "主任会議")

        # 職場行事を対象日へ反映して ICS 生成
        enriched[0]["event"] = "主任会議"
        ics_text = calendar_export.create_ics(enriched, calendar_name="シフトカレンダー", include_events=True)
        self.assertIn("BEGIN:VCALENDAR", ics_text)
        self.assertIn("[早A] (06:00〜15:00)", ics_text)
        self.assertIn("[日] (08:30〜17:30)（時間有給1.5h）", ics_text)
        self.assertIn("引き継ぎあり", ics_text)
        self.assertIn("SUMMARY:休み", ics_text)
        self.assertIn("SUMMARY:有給休暇", ics_text)
        self.assertIn("SUMMARY:主任会議", ics_text)


if __name__ == "__main__":
    unittest.main()
