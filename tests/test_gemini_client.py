import io
import json
import os
import sys
import unittest
import urllib.error
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shift_calendar import gemini_client


class _DummyResponse:
    def __init__(self, payload_dict):
        self._body = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestGeminiClientRefactor(unittest.TestCase):
    def test_01_post_gemini_uses_header_only_without_url_query_key(self):
        """APIキーはURLクエリに載せず x-goog-api-key ヘッダーのみで送信すること"""
        captured = {}

        def fake_urlopen(req, timeout=60):
            captured["url"] = req.full_url
            captured["headers"] = {k.lower(): v for k, v in req.header_items()}
            captured["timeout"] = timeout
            return _DummyResponse({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            res = gemini_client.post_gemini_generate_content("SECRET_KEY_123", "gemini-2.5-flash", {"contents": []}, timeout=12)

        self.assertIn("candidates", res)
        self.assertNotIn("SECRET_KEY_123", captured["url"])
        self.assertNotIn("?key=", captured["url"])
        self.assertEqual(captured["headers"].get("x-goog-api-key"), "SECRET_KEY_123")
        self.assertEqual(captured["timeout"], 12)

    def test_02_normalize_shift_columns_handles_year_month_rollover_and_grid_snap(self):
        """前月・当月・翌月の年跨ぎ日付判定とグリッド座標吸着が正確に動作すること"""
        parsed = {
            "year": 2026,
            "main_month": 1,
            "columns": [
                {"col": 1, "date": "31日", "day_of_week": "水", "shift_text": "休"},
                {"col": 2, "date": 1, "day_of_week": "木", "shift_text": "早A"},
                {"col": 3, "date": 2, "day_of_week": "金", "shift_text": "有"},
                {"col": 4, "date": "invalid", "day_of_week": "土", "shift_text": "日"},
                {"col": 5, "date": 1, "day_of_week": "日", "shift_text": "遅B"},
            ],
        }
        grid_info = {
            "h_lines_norm": [0, 100, 200, 300, 400],
            "grid_x_norm": [100, 200, 300, 400, 500],
        }
        shifts, year, month = gemini_client.normalize_shift_columns(parsed, grid_info=grid_info, exact_row_idx=2)
        self.assertEqual((year, month), (2026, 1))
        self.assertEqual([s["date"] for s in shifts], ["2025-12-31", "2026-01-01", "2026-01-02", "2026-02-01"])
        self.assertEqual(shifts[0]["box_2d"], [200, 100, 300, 200])
        self.assertEqual(shifts[1]["box_2d"], [200, 200, 300, 300])

    def test_03_enrich_shift_records_classifies_work_holiday_and_paid_leave(self):
        """休み・有給・出勤のステータスと時間・サマリー補完が正しく行われること"""
        shifts = [
            {"date": "2026-12-01", "type": "休"},
            {"date": "2026-12-02", "type": "有"},
            {"date": "2026-12-03", "type": "早A"},
        ]
        gemini_client.enrich_shift_records(shifts)
        self.assertEqual(shifts[0]["status"], "holiday")
        self.assertEqual(shifts[0]["summary"], "休み")
        self.assertEqual(shifts[1]["status"], "paid_leave")
        self.assertEqual(shifts[1]["summary"], "有給休暇")
        self.assertEqual(shifts[2]["status"], "work")
        self.assertEqual(shifts[2]["start_time"], "06:00")
        self.assertEqual(shifts[2]["end_time"], "15:00")
        self.assertEqual(shifts[2]["summary"], "[早A] (06:00〜15:00)")

    def test_04_fallback_prompt_has_no_hardcoded_colleague_names(self):
        """全体画像フォールバック用プロンプトに特定同僚名のハードコードが含まれないこと"""
        prompt, _ = gemini_client._build_shift_ocr_prompt_and_image("山田", b"\xff\xd8\xff", None, None, None)
        for forbidden in ("タイン", "松岡", "藤本", "岡田竜", "唐川", "柴田"):
            self.assertNotIn(forbidden, prompt)
        self.assertIn("山田", prompt)

    def test_05_request_with_fallback_switches_model_on_503(self):
        """503応答時に次モデルへフォールバックしてJSONを返すこと"""
        called_models = []

        def fake_post(api_key, model_name, payload, timeout=60):
            called_models.append(model_name)
            if model_name == "model-a":
                raise urllib.error.HTTPError("https://example.test", 503, "Busy", {}, io.BytesIO(b"busy"))
            return {"candidates": [{"content": {"parts": [{"text": "{\"ok\": true}"}]}}]}

        with patch.object(gemini_client, "post_gemini_generate_content", side_effect=fake_post):
            parsed, used = gemini_client._request_gemini_json_with_fallback(
                api_key="KEY",
                payload={},
                models=["model-a", "model-b"],
                timeout=5,
                log_tag="TEST",
                sleep_fn=lambda _: None,
                first_model_retries=1,
            )

        self.assertEqual(parsed, {"ok": True})
        self.assertEqual(used, "model-b")
        self.assertEqual(called_models, ["model-a", "model-b"])


if __name__ == "__main__":
    unittest.main()
