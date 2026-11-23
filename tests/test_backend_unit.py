"""バックエンド（shift_calendar/*）の純粋関数・境界値・異常系を対象とした単体テスト（テストピラミッド底辺）"""
import unittest

import cv2
import numpy as np

from shift_calendar import calendar_export, config, domain, image_processing, qr


def _make_clean_grid_jpeg(num_cols=36, num_rows=10, width=1600, height=700):
    """歪みのない合成グリッド表のJPEGバイト列を生成する。"""
    img = np.full((height, width, 3), 255, dtype=np.uint8)
    x0, x1 = 40, width - 40
    y0, y1 = 40, height - 40
    xs = np.linspace(x0, x1, num_cols + 1).astype(int)
    ys = np.linspace(y0, y1, num_rows + 1).astype(int)
    for x in xs:
        cv2.line(img, (int(x), y0), (int(x), y1), (30, 30, 30), 2)
    for y in ys:
        cv2.line(img, (x0, int(y)), (x1, int(y)), (30, 30, 30), 2)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    assert ok
    return buf.tobytes(), xs, ys


class TestBackendUnit(unittest.TestCase):
    """shift_calendar パッケージの低レイヤー単体テスト"""

    # --- domain.py ---
    def test_01_clamp_int_boundaries_and_invalid(self):
        self.assertEqual(domain.clamp_int("15", 1, 1, 31), 15)
        self.assertEqual(domain.clamp_int(-5, 1, 1, 31), 1)
        self.assertEqual(domain.clamp_int(99, 1, 1, 31), 31)
        self.assertEqual(domain.clamp_int("abc", 4, 1, 12), 4)
        self.assertEqual(domain.clamp_int(None, 20, 0, 60), 20)

    def test_02_clamp_half_hour_snapping_and_bounds(self):
        self.assertEqual(domain.clamp_half_hour(1.24, 0.0, 0.0, 8.0), 1.0)
        self.assertEqual(domain.clamp_half_hour(1.26, 0.0, 0.0, 8.0), 1.5)
        self.assertEqual(domain.clamp_half_hour(-0.1, 0.0, 0.0, 8.0), 0.0)
        self.assertEqual(domain.clamp_half_hour(99.0, 0.0, 0.0, 8.0), 8.0)
        self.assertEqual(domain.clamp_half_hour("bad", 7.5, 1.0, 24.0), 7.5)

    def test_03_format_hourly_leave_hours_variants(self):
        self.assertEqual(domain.format_hourly_leave_hours(0), "")
        self.assertEqual(domain.format_hourly_leave_hours(-1), "")
        self.assertEqual(domain.format_hourly_leave_hours(2.0), "2")
        self.assertEqual(domain.format_hourly_leave_hours(1.5), "1.5")
        self.assertEqual(domain.format_hourly_leave_hours(1.49), "1.5")

    def test_04_apply_hourly_leave_to_summary_work_and_reset(self):
        self.assertEqual(
            domain.apply_hourly_leave_to_summary("[日] (08:30〜17:30)", 1.5, "work"),
            "[日] (08:30〜17:30)（時間有給1.5h）",
        )
        self.assertEqual(
            domain.apply_hourly_leave_to_summary("[日] (08:30〜17:30)（時間有給1h）", 2.0, "work"),
            "[日] (08:30〜17:30)（時間有給2h）",
        )
        self.assertEqual(
            domain.apply_hourly_leave_to_summary("[日] (08:30〜17:30)（時間有給1.5h）", 0, "work"),
            "[日] (08:30〜17:30)",
        )
        self.assertEqual(
            domain.apply_hourly_leave_to_summary("休み（時間有給2h）", 2.0, "holiday"),
            "休み",
        )
        self.assertEqual(domain.apply_hourly_leave_to_summary("", 1.5, "work"), "時間有給1.5h")

    def test_05_sanitize_history_id_strips_unsafe_chars(self):
        self.assertEqual(domain.sanitize_history_id("20261123_001-a"), "20261123_001-a")
        self.assertEqual(domain.sanitize_history_id("../../etc/passwd"), "etcpasswd")
        self.assertEqual(domain.sanitize_history_id("id with spaces/\\:*?"), "idwithspaces")
        self.assertEqual(domain.sanitize_history_id(None), "")

    def test_06_clean_event_text_excluding_holidays_mixed_and_single(self):
        self.assertEqual(domain.clean_event_text_excluding_holidays("勤労感謝の日"), "")
        self.assertEqual(domain.clean_event_text_excluding_holidays("敬老の日・敬老会"), "敬老会")
        self.assertEqual(domain.clean_event_text_excluding_holidays("クリスマス / クリスマス会"), "クリスマス会")
        self.assertEqual(domain.clean_event_text_excluding_holidays("主任会議"), "主任会議")
        self.assertEqual(domain.clean_event_text_excluding_holidays(""), "")

    # --- calendar_export.py ---
    def test_07_escape_ics_text_all_rfc5545_chars(self):
        raw = "A\\B;C,D\r\nE\rF\nG"
        escaped = calendar_export._escape_ics_text(raw)
        self.assertEqual(escaped, r"A\\B\;C\,D\nE\nF\nG")
        self.assertEqual(calendar_export._escape_ics_text(None), "")

    def test_08_escape_applescript_str_quotes_backslashes_newlines(self):
        raw = '  "早A"\\test\r\nline2  '
        self.assertEqual(calendar_export._escape_applescript_str(raw), r'\"早A\"\\test  line2')
        self.assertEqual(calendar_export._escape_applescript_str(None), "")

    def test_09_prepare_shift_export_fields_work_holiday_paid(self):
        is_allday, summary = calendar_export._prepare_shift_export_fields(
            {"status": "work", "type": "早A", "summary": "[早A] (06:00〜15:00)", "hourly_paid_leave": 1.5}
        )
        self.assertFalse(is_allday)
        self.assertEqual(summary, "[早A] (06:00〜15:00)（時間有給1.5h）")

        is_hol, hol_sum = calendar_export._prepare_shift_export_fields(
            {"status": "holiday", "summary": "休み", "hourly_paid_leave": 2.0}
        )
        self.assertTrue(is_hol)
        self.assertEqual(hol_sum, "休み")

        is_paid, paid_sum = calendar_export._prepare_shift_export_fields({"is_paid_leave": True, "type": "有給"})
        self.assertTrue(is_paid)
        self.assertEqual(paid_sum, "有給")

    def test_10_format_osascript_error_permission_and_generic(self):
        perm_msg = calendar_export._format_osascript_error("execution error: Not authorized to send Apple events (-1743)")
        self.assertIn("アクセス権限がありません", perm_msg)
        self.assertIn("-1743", perm_msg)

        gen_msg = calendar_export._format_osascript_error("some unknown failure")
        self.assertIn("カレンダー登録エラー", gen_msg)
        self.assertIn("some unknown failure", gen_msg)

        empty_msg = calendar_export._format_osascript_error("")
        self.assertIn("osascript の実行に失敗しました", empty_msg)

    def test_11_register_to_apple_calendar_empty_shifts_returns_zero(self):
        count, msg = calendar_export.register_to_apple_calendar([])
        self.assertEqual(count, 0)
        self.assertIn("登録対象のシフトがありません", msg)

    def test_12_create_ics_excludes_events_when_flag_false(self):
        shifts = [
            {
                "date": "2026-11-10",
                "status": "work",
                "type": "日",
                "start_time": "08:30",
                "end_time": "17:30",
                "summary": "[日] (08:30〜17:30)",
                "event": "主任会議",
            }
        ]
        ics_with = calendar_export.create_ics(shifts, include_events=True)
        ics_without = calendar_export.create_ics(shifts, include_events=False)
        self.assertIn("主任会議", ics_with)
        self.assertNotIn("主任会議", ics_without)

    # --- config.py ---
    def test_13_validate_time_definitions_accepts_valid_and_normalizes(self):
        cleaned = config.validate_time_definitions(
            {" 早A ": {"start": "06:00", "end": "15:00"}, "日": {"start": "08:30", "end": "17:30"}}
        )
        self.assertEqual(cleaned["早A"], {"start": "06:00", "end": "15:00"})
        self.assertEqual(cleaned["日"], {"start": "08:30", "end": "17:30"})

    def test_14_validate_time_definitions_rejects_bad_types_and_empty(self):
        with self.assertRaises(ValueError):
            config.validate_time_definitions([])
        with self.assertRaises(ValueError):
            config.validate_time_definitions({})
        with self.assertRaises(ValueError):
            config.validate_time_definitions({"休み": {"start": "08:00", "end": "17:00"}})

    def test_15_validate_time_definitions_rejects_invalid_time_format(self):
        with self.assertRaises(ValueError):
            config.validate_time_definitions({"早A": {"start": "25:00", "end": "15:00"}})
        with self.assertRaises(ValueError):
            config.validate_time_definitions({"早A": {"start": "08:00", "end": "bad"}})

    # --- qr.py ---
    def test_16_qr_encode_matrix_ascii_and_utf8_dimensions(self):
        m_ascii = qr.encode_qr_matrix("http://192.168.1.10:8765")
        self.assertEqual(len(m_ascii), len(m_ascii[0]))
        self.assertGreaterEqual(len(m_ascii), 21)

        m_utf8 = qr.encode_qr_matrix("http://192.168.1.10:8765/?label=シフト確認テスト")
        self.assertEqual(len(m_utf8), len(m_utf8[0]))
        self.assertGreaterEqual(len(m_utf8), len(m_ascii))

    def test_17_qr_encode_matrix_empty_and_oversized_raise_value_error(self):
        with self.assertRaises(ValueError):
            qr.encode_qr_matrix("")
        with self.assertRaises(ValueError):
            qr.encode_qr_matrix(None)
        with self.assertRaises(ValueError):
            qr.encode_qr_matrix("A" * 5000)

    def test_18_qr_render_svg_xml_escapes_aria_label_and_dimensions(self):
        svg = qr.render_qr_svg("http://127.0.0.1:8765/?a=1&b=<tag>", border=4, size=180)
        self.assertIn('width="180" height="180"', svg)
        self.assertIn("&amp;b=&lt;tag&gt;", svg)
        self.assertIn("<path d=", svg)
        self.assertTrue(svg.startswith("<svg ") and svg.endswith("</svg>"))

    # --- image_processing.py ---
    def test_19_image_detect_table_grid_synthetic_36_columns(self):
        jpg, _, _ = _make_clean_grid_jpeg(num_cols=36, num_rows=12, width=1600, height=700)
        grid = image_processing.detect_table_grid(jpg)
        self.assertIsNotNone(grid)
        self.assertEqual(grid["n_cols"], 36)
        self.assertGreaterEqual(len(grid["h_lines"]), 10)

    def test_20_image_detect_table_grid_synthetic_35_columns(self):
        jpg, _, _ = _make_clean_grid_jpeg(num_cols=35, num_rows=10, width=1600, height=650)
        grid = image_processing.detect_table_grid(jpg)
        self.assertIsNotNone(grid)
        self.assertEqual(grid["n_cols"], 35)

    def test_21_snap_row_band_to_grid_snaps_to_nearest_row_lines(self):
        grid = {"h_lines_norm": [100.0, 200.0, 300.0, 400.0, 500.0]}
        ymin, ymax = image_processing.snap_row_band_to_grid(grid, 212.0, 290.0)
        self.assertEqual((ymin, ymax), (200.0, 300.0))

    def test_22_snap_row_band_to_grid_fallback_on_missing_or_degenerate_grid(self):
        self.assertEqual(image_processing.snap_row_band_to_grid(None, 210, 290), (210, 290))
        self.assertEqual(image_processing.snap_row_band_to_grid({"h_lines_norm": [100.0]}, 210, 290), (210, 290))

    def test_23_optimize_image_for_ai_fallback_on_invalid_bytes(self):
        bad = b"not-a-valid-image-bytes"
        out = image_processing.optimize_image_for_ai(bad)
        self.assertEqual(out, bad)

    def test_24_optimize_image_for_ai_returns_valid_jpeg_for_synthetic_image(self):
        jpg, _, _ = _make_clean_grid_jpeg(num_cols=10, num_rows=5, width=600, height=300)
        out = image_processing.optimize_image_for_ai(jpg)
        self.assertIsInstance(out, (bytes, bytearray))
        self.assertGreater(len(out), 100)
        arr = np.frombuffer(out, dtype=np.uint8)
        decoded = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        self.assertIsNotNone(decoded)


if __name__ == "__main__":
    unittest.main()
