import io
import json
import os
import sys
import unittest
import urllib.error
from unittest.mock import patch
import cv2
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import app


class TestEventExtractionAndCalendarExport(unittest.TestCase):
    def _make_sample_grid(self, include_tall_bottom=True):
        # 通常行 12行（高さ28px）＋ 必要なら最下部に縦長の行事予定行（高さ140px）
        h_lines = [100 + i * 28 for i in range(13)]
        if include_tall_bottom:
            h_lines.append(h_lines[-1] + 140)
        grid_x = [120 + i * 36 for i in range(32)]  # 31列
        return {
            "h_lines": h_lines,
            "grid_x": grid_x,
            "n_cols": 31,
            "w": 1400,
            "h": h_lines[-1] + 10,
        }

    def test_01_detect_event_row_band_finds_tall_bottom_row(self):
        """最下部に縦長の行事予定セルがある場合にその帯を正確に検出すること"""
        grid = self._make_sample_grid(include_tall_bottom=True)
        band = app.detect_event_row_band(grid)
        self.assertIsNotNone(band)
        self.assertEqual(band, (grid["h_lines"][-2], grid["h_lines"][-1]))

    def test_02_detect_event_row_band_returns_none_without_tall_row(self):
        """すべての行が均一高さ（行事欄なし）の表ではスタッフ行を誤認せず None を返すこと"""
        grid = self._make_sample_grid(include_tall_bottom=False)
        band = app.detect_event_row_band(grid)
        self.assertIsNone(band)

    def test_02b_detect_event_row_band_picks_text_row_among_multiple_tall_rows(self):
        """下部に複数の縦長行（行事行・空行・栄養士行）がある場合、文字が書かれた行事行を選ぶこと"""
        h_lines = [100 + i * 35 for i in range(13)]
        y_event_top = h_lines[-1]
        y_event_bot = y_event_top + 185
        y_blank_bot = y_event_bot + 185
        y_nutri_bot = y_blank_bot + 190
        h_lines.extend([y_event_bot, y_blank_bot, y_nutri_bot])
        grid = {
            "h_lines": h_lines,
            "grid_x": [120 + i * 36 for i in range(32)],
            "n_cols": 31,
            "w": 1400,
            "h": y_nutri_bot + 10,
        }
        img = np.full((grid["h"], grid["w"], 3), 255, dtype=np.uint8)
        # 1段目の縦長行（行事予定行）にのみ文字を模擬描画
        cv2.putText(img, "EVENT", (260, y_event_top + 95), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
        band = app.detect_event_row_band(grid, img=img)
        self.assertEqual(band, (y_event_top, y_event_bot))

    def test_02c_detect_event_row_band_handles_landscape_compact_table(self):
        """横長表（通常行21px・2行結合41px・行事行72px）でも行事行を検出し2行結合を誤認しないこと"""
        h_lines = [77, 97, 117, 137, 157, 178, 200, 217, 239, 260, 281, 322, 343, 363, 435]
        grid = {
            "h_lines": h_lines,
            "grid_x": [78 + i * 37 for i in range(36)],
            "n_cols": 35,
            "w": 1400,
            "h": 469,
        }
        band = app.detect_event_row_band(grid)
        self.assertEqual(band, (363, 435))

    def test_03_build_labeled_event_strip_produces_valid_jpeg(self):
        """行事予定専用ストリップ画像が正常なJPEGとして生成されること"""
        grid = self._make_sample_grid(include_tall_bottom=True)
        dummy_img = np.full((grid["h"], grid["w"], 3), 255, dtype=np.uint8)
        strip_bytes = app.build_labeled_event_strip(dummy_img, grid)
        self.assertIsNotNone(strip_bytes)
        decoded = cv2.imdecode(np.frombuffer(strip_bytes, np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(decoded)
        self.assertGreater(decoded.shape[0], 100)
        self.assertGreater(decoded.shape[1], 300)

    def test_03b_detect_active_event_columns_filters_only_text_columns(self):
        """31列中、文字が書かれた列だけをOpenCVで事前抽出してコンパクトストリップ化できること"""
        grid = self._make_sample_grid(include_tall_bottom=True)
        img = np.full((grid["h"], grid["w"], 3), 255, dtype=np.uint8)
        y1, y2 = grid["h_lines"][-2], grid["h_lines"][-1]
        for col_idx in (4, 11):  # 5列目と12列目にのみ縦書き文字相当の黒描画
            x1 = grid["grid_x"][col_idx]
            cv2.rectangle(img, (x1 + 12, y1 + 30), (x1 + 22, y1 + 100), (0, 0, 0), -1)
        active = app.detect_active_event_columns(img, grid)
        self.assertEqual(active, [4, 11])
        strip_bytes = app.build_labeled_event_strip(img, grid)
        self.assertIsNotNone(strip_bytes)
        decoded = cv2.imdecode(np.frombuffer(strip_bytes, np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(decoded)
        self.assertGreaterEqual(decoded.shape[1], 320)

    def test_03c_detect_active_event_spans_merges_borderless_two_day_cell(self):
        """間の縦罫線が消えている2日結合セルを1つのスパン(4-5)として自動検出し、他列は分離維持すること"""
        grid = self._make_sample_grid(include_tall_bottom=True)
        img = np.full((grid["h"], grid["w"], 3), 255, dtype=np.uint8)
        y1, y2 = grid["h_lines"][-2], grid["h_lines"][-1]
        gx = grid["grid_x"]
        # 結合境界 (b=4: 列3と列4の間 = 1-basedで4列目と5列目の間) 以外の全縦罫線を描画
        for b in range(len(gx)):
            if b == 4:
                continue
            cv2.line(img, (gx[b], y1), (gx[b], y2), (0, 0, 0), 2)
        # 結合セル(4-5列目の中央)と単一セル(11列目)に文字相当の黒描画
        cv2.rectangle(img, (gx[4] - 8, y1 + 30), (gx[4] + 8, y1 + 105), (0, 0, 0), -1)
        cv2.rectangle(img, (gx[10] + 12, y1 + 30), (gx[10] + 22, y1 + 105), (0, 0, 0), -1)

        spans = app.detect_active_event_spans(img, grid)
        self.assertEqual(spans, [(3, 4), (10, 10)])

        strip_bytes = app.build_labeled_event_strip(img, grid)
        self.assertIsNotNone(strip_bytes)
        decoded = cv2.imdecode(np.frombuffer(strip_bytes, np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(decoded)

    def test_04_create_ics_outputs_both_holiday_and_event_as_allday(self):
        """休み・有給・出勤の各日で行事予定が別々の終日イベントとして出力されること"""
        shifts = [
            {
                "date": "2026-12-01",
                "type": "早A",
                "status": "work",
                "start_time": "06:00",
                "end_time": "15:00",
                "summary": "[早A] (06:00〜15:00)",
                "event": "避難訓練",
            },
            {
                "date": "2026-12-02",
                "type": "休",
                "status": "holiday",
                "is_holiday": True,
                "start_time": None,
                "end_time": None,
                "summary": "休み",
                "event": "誕生会",
            },
            {
                "date": "2026-12-03",
                "type": "有給",
                "status": "paid_leave",
                "is_paid_leave": True,
                "start_time": None,
                "end_time": None,
                "summary": "有給休暇",
                "event": "全体会議",
            },
            {
                # event キーを持たない旧履歴データとの後方互換性確認
                "date": "2026-12-04",
                "type": "日",
                "status": "work",
                "start_time": "08:30",
                "end_time": "17:30",
                "summary": "[日] (08:30〜17:30)",
            },
        ]

        ics_with_events = app.create_ics(shifts, "シフトカレンダー", include_events=True)
        self.assertEqual(ics_with_events.count("BEGIN:VEVENT"), 7)
        self.assertIn("UID:shift-20261202@shift-calendar-app", ics_with_events)
        self.assertIn("SUMMARY:休み", ics_with_events)
        self.assertIn("UID:event-20261202@shift-calendar-app", ics_with_events)
        self.assertIn("SUMMARY:誕生会", ics_with_events)
        self.assertIn("UID:event-20261203@shift-calendar-app", ics_with_events)
        self.assertIn("SUMMARY:全体会議", ics_with_events)
        self.assertIn("UID:event-20261201@shift-calendar-app", ics_with_events)
        self.assertIn("SUMMARY:避難訓練", ics_with_events)

        ics_without_events = app.create_ics(shifts, "シフトカレンダー", include_events=False)
        self.assertEqual(ics_without_events.count("BEGIN:VEVENT"), 4)
        self.assertNotIn("UID:event-20261202@shift-calendar-app", ics_without_events)
        self.assertNotIn("SUMMARY:誕生会", ics_without_events)

    def test_05_build_apple_calendar_script_registers_two_allday_events_on_holiday(self):
        """休みの日に行事がある場合、AppleScriptで休みと行事の両方が終日イベントとして生成されること"""
        shifts = [
            {
                "date": "2026-12-02",
                "type": "休",
                "status": "holiday",
                "is_holiday": True,
                "summary": "休み",
                "event": "クリスマス会",
            },
            {
                "date": "2026-12-03",
                "type": "早B",
                "status": "work",
                "start_time": "06:30",
                "end_time": "15:30",
                "summary": "[早B] (06:30〜15:30)",
                "event": "防災訓練",
            },
        ]

        script, count = app.build_apple_calendar_script(shifts, "シフトカレンダー", include_events=True)
        self.assertEqual(count, 4)
        self.assertIn('summary:"休み", start date:evStart, end date:evEnd, allday event:true', script)
        self.assertIn('summary:"クリスマス会", start date:evStart, end date:evEnd, allday event:true', script)
        self.assertIn('summary:"[早B] (06:30〜15:30)", start date:evStart, end date:evEnd, allday event:false', script)
        self.assertIn('summary:"防災訓練", start date:evStart, end date:evEnd, allday event:true', script)

        script_off, count_off = app.build_apple_calendar_script(shifts, "シフトカレンダー", include_events=False)
        self.assertEqual(count_off, 2)
        self.assertNotIn("クリスマス会", script_off)
        self.assertNotIn("防災訓練", script_off)

    def test_06_fetch_column_events_falls_back_on_503_and_parses_events(self):
        """先頭モデルがHTTP 503でも別モデルへフォールバックして行事予定を確実に抽出すること"""
        grid = self._make_sample_grid(include_tall_bottom=True)
        img = np.full((grid["h"], grid["w"], 3), 255, dtype=np.uint8)
        strip_bytes = app.build_labeled_event_strip(img, grid)

        call_urls = []

        class FakeResp:
            def __init__(self, payload_obj):
                self._raw = json.dumps(payload_obj).encode("utf-8")

            def read(self):
                return self._raw

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def fake_urlopen(req, timeout=15):
            call_urls.append(req.full_url)
            if len(call_urls) <= 2:
                raise urllib.error.HTTPError(
                    req.full_url, 503, "Service Unavailable", {}, io.BytesIO(b"overloaded")
                )
            return FakeResp({
                "candidates": [{
                    "content": {
                        "parts": [{
                            "text": json.dumps({
                                "events": [
                                    {"col": 7, "event": "労力奉仕"},
                                    {"col": 12, "event": "お餅つき"},
                                    {"col": 99, "event": "範囲外無視"}
                                ]
                            }, ensure_ascii=False)
                        }]
                    }
                }]
            })

        with patch("app.time.sleep", return_value=None), patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = app.fetch_column_events_from_gemini("dummy-key", strip_bytes, 31, active_col_nums=[7, 12])

        self.assertEqual(result, {7: "労力奉仕", 12: "お餅つき"})
        self.assertGreaterEqual(len(call_urls), 3)
        self.assertIn("gemini-2.5-flash-lite", call_urls[2])
        self.assertEqual(app.ANALYZE_PROGRESS["step"], 4)

    def test_06b_fetch_column_events_expands_merged_span_to_both_days(self):
        """結合セル('4-5'または単一'4'返却)の行事が両日(4と5)へ自動展開されること"""
        grid = self._make_sample_grid(include_tall_bottom=True)
        img = np.full((grid["h"], grid["w"], 3), 255, dtype=np.uint8)
        strip_bytes = app.build_labeled_event_strip(img, grid)

        class FakeResp:
            def __init__(self, payload_obj):
                self._raw = json.dumps(payload_obj).encode("utf-8")

            def read(self):
                return self._raw

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        # ケース1: AIが "4-5" 範囲表記で返却した場合
        resp_range = FakeResp({
            "candidates": [{"content": {"parts": [{"text": json.dumps({
                "events": [{"col": "4-5", "event": "感謝祭"}, {"col": 14, "event": "主任会議"}]
            }, ensure_ascii=False)}]}}]
        })
        with patch("urllib.request.urlopen", return_value=resp_range):
            res1 = app.fetch_column_events_from_gemini("dummy-key", strip_bytes, 35, active_spans=[(3, 4), (13, 13)])
        self.assertEqual(res1, {4: "感謝祭", 5: "感謝祭", 14: "主任会議"})

        # ケース2: AIが結合スパン内の単一番号 4 だけを返却した場合も両日へ展開されること
        resp_single = FakeResp({
            "candidates": [{"content": {"parts": [{"text": json.dumps({
                "events": [{"col": 4, "event": "感謝祭"}]
            }, ensure_ascii=False)}]}}]
        })
        with patch("urllib.request.urlopen", return_value=resp_single):
            res2 = app.fetch_column_events_from_gemini("dummy-key", strip_bytes, 35, active_spans=[(3, 4)])
        self.assertEqual(res2, {4: "感謝祭", 5: "感謝祭"})

    def test_07_analyze_events_only_updates_progress_and_returns_events(self):
        """analyze_events_onlyが行事列を抽出してプログレスを100%完了に更新すること"""
        grid = self._make_sample_grid(include_tall_bottom=True)
        img = np.full((grid["h"], grid["w"], 3), 255, dtype=np.uint8)
        y1, y2 = grid["h_lines"][-2], grid["h_lines"][-1]
        x1 = grid["grid_x"][6]
        cv2.rectangle(img, (x1 + 10, y1 + 25), (x1 + 24, y1 + 110), (0, 0, 0), -1)
        _, buf = cv2.imencode(".jpg", img)
        img_bytes = buf.tobytes()

        with patch("app.dewarp_table_image", return_value=(img_bytes, "data:image/jpeg;base64,xxx")), \
             patch("app.detect_table_grid", return_value=grid), \
             patch("app.fetch_column_events_from_gemini", return_value={7: "労力奉仕"}) as mock_fetch:
            res = app.analyze_events_only("dummy-key", img_bytes)

        mock_fetch.assert_called_once()
        self.assertEqual(res["events"], {"7": "労力奉仕"})
        self.assertEqual(res["active_cols"], [7])
        self.assertEqual(res["extracted_count"], 1)
        self.assertEqual(app.ANALYZE_PROGRESS["percent"], 100)
        self.assertFalse(app.ANALYZE_PROGRESS["active"])
        self.assertEqual(app.ANALYZE_PROGRESS["step"], 4)

        # 文字が1列もない白紙画像ではAPIを呼ばず即100%完了すること
        blank_img = np.full((grid["h"], grid["w"], 3), 255, dtype=np.uint8)
        _, b_buf = cv2.imencode(".jpg", blank_img)
        blank_bytes = b_buf.tobytes()
        with patch("app.dewarp_table_image", return_value=(blank_bytes, "data:image/jpeg;base64,xxx")), \
             patch("app.detect_table_grid", return_value=grid), \
             patch("app.fetch_column_events_from_gemini") as mock_fetch_blank:
            res_blank = app.analyze_events_only("dummy-key", blank_bytes)
        mock_fetch_blank.assert_not_called()
        self.assertEqual(res_blank["events"], {})
        self.assertEqual(app.ANALYZE_PROGRESS["percent"], 100)
        self.assertFalse(app.ANALYZE_PROGRESS["active"])

    def test_08_set_analyze_progress_clamps_and_stores_fields(self):
        """プログレス更新関数が0〜100の範囲制限と進捗情報を正確に保持すること"""
        app.set_analyze_progress(-20, "開始", "詳細A", step=1, active=True)
        self.assertEqual(app.ANALYZE_PROGRESS["percent"], 0)
        self.assertTrue(app.ANALYZE_PROGRESS["active"])
        self.assertEqual(app.ANALYZE_PROGRESS["step"], 1)
        self.assertEqual(app.ANALYZE_PROGRESS["phase"], "開始")

        app.set_analyze_progress(150, "完了", "詳細B", step=4, active=False)
        self.assertEqual(app.ANALYZE_PROGRESS["percent"], 100)
        self.assertFalse(app.ANALYZE_PROGRESS["active"])
        self.assertEqual(app.ANALYZE_PROGRESS["step"], 4)
        self.assertEqual(app.ANALYZE_PROGRESS["detail"], "詳細B")


if __name__ == "__main__":
    unittest.main()
