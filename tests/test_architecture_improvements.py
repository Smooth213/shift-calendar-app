import ast
import io
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import app
from shift_calendar import calendar_export, domain, storage
from tests.dom_harness import run_node_harness


def _invoke_post(path, raw_body, client_address=("127.0.0.1", 50000)):
    handler = app.RequestHandler.__new__(app.RequestHandler)
    handler.path = path
    handler.client_address = client_address
    handler.headers = {"Content-Length": str(len(raw_body))}
    handler.rfile = io.BytesIO(raw_body)
    handler.wfile = io.BytesIO()
    handler.server = type("Srv", (), {"server_port": 8765})()
    captured = {"status": None, "headers": {}}

    def send_response(code, message=None):
        del message
        captured["status"] = code

    def send_header(k, v):
        captured["headers"][k] = v

    def end_headers():
        pass

    handler.send_response = send_response
    handler.send_header = send_header
    handler.end_headers = end_headers
    handler.do_POST()
    body_bytes = handler.wfile.getvalue()
    try:
        parsed = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        parsed = body_bytes.decode("utf-8", errors="replace")
    return captured["status"], parsed


class TestArchitectureImprovements(unittest.TestCase):
    def test_01_gemini_client_does_not_depend_on_calendar_export(self):
        """項目1: gemini_client.py は calendar_export に依存せず domain を参照すること"""
        gemini_path = os.path.join(PROJECT_ROOT, "shift_calendar", "gemini_client.py")
        with open(gemini_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), gemini_path)
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
        self.assertNotIn("shift_calendar.calendar_export", imported_modules)
        self.assertIn("shift_calendar.domain", imported_modules)
        self.assertIs(calendar_export.split_event_and_skipped_holidays, domain.split_event_and_skipped_holidays)
        self.assertIs(app.split_event_and_skipped_holidays, domain.split_event_and_skipped_holidays)

    def test_02_create_ics_escapes_rfc5545_special_chars(self):
        """項目4: create_ics がカンマ・セミコロン・バックスラッシュ・改行をエスケープすること"""
        shifts = [{
            "date": "2026-12-01",
            "type": "早A,特;別",
            "status": "work",
            "start_time": "06:00",
            "end_time": "15:00",
            "summary": "会議,A;B\\C\n補足",
            "event": "行事,A;B\\C",
        }]
        ics = calendar_export.create_ics(shifts, calendar_name="勤務,予定;表", include_events=True)
        self.assertIn("X-WR-CALNAME:勤務\\,予定\\;表", ics)
        self.assertIn("SUMMARY:会議\\,A\\;B\\\\C\\n補足", ics)
        self.assertIn("DESCRIPTION:シフト区分: 早A\\,特\\;別", ics)
        self.assertIn("SUMMARY:行事\\,A\\;B\\\\C", ics)

    def test_03_post_config_filters_unknown_keys_and_validates_types(self):
        """項目3: POST /api/config が未許可キーを除外し、不正型には HTTP 400 を返すこと"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            with patch.object(app, "CONFIG_PATH", cfg_path):
                payload = json.dumps({
                    "default_name": "テスト太郎",
                    "malicious_key": "should_not_be_saved",
                    "theme": "dark",
                }).encode("utf-8")
                status, resp = _invoke_post("/api/config", payload)
                self.assertEqual(status, 200)
                self.assertTrue(resp.get("success"))
                with open(cfg_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self.assertEqual(saved.get("default_name"), "テスト太郎")
                self.assertNotIn("malicious_key", saved)

                # 不正な time_definitions 型は 400
                bad_payload = json.dumps({"time_definitions": ["invalid"]}).encode("utf-8")
                status_bad, _ = _invoke_post("/api/config", bad_payload)
                self.assertEqual(status_bad, 400)

                # JSON配列（非dict）は 400
                status_arr, _ = _invoke_post("/api/config", b"[1, 2, 3]")
                self.assertEqual(status_arr, 400)

    def test_04_post_endpoints_return_400_on_client_input_errors(self):
        """項目3: 不正JSON・不正Base64・非配列shifts 等で HTTP 400 を返すこと"""
        status_json, _ = _invoke_post("/api/register", b"{invalid json")
        self.assertEqual(status_json, 400)

        status_shifts, _ = _invoke_post("/api/register", json.dumps({"shifts": "not-a-list"}).encode("utf-8"))
        self.assertEqual(status_shifts, 400)

        status_b64, _ = _invoke_post(
            "/api/dewarp_preview",
            json.dumps({"image_base64": "!!!not-base64!!!"}).encode("utf-8"),
        )
        self.assertEqual(status_b64, 400)

        status_no_img, _ = _invoke_post(
            "/api/analyze",
            json.dumps({"api_key": "dummy-key", "image_base64": ""}).encode("utf-8"),
        )
        self.assertEqual(status_no_img, 400)

    def test_05_storage_cache_reuses_unchanged_and_tracks_external_updates(self):
        """項目6: 履歴キャッシュが未変更ファイルの再読込を抑止し、外部更新・削除に即座に追従すること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "h1.json")
            rec1 = {
                "id": "h1",
                "title": "初回タイトル",
                "created_at": "2026-11-01 10:00:00",
                "registered": True,
                "registered_at": "2026-11-01 10:05:00",
                "shifts": [{"date": "2026-11-01", "type": "日", "status": "work"}],
            }
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(rec1, f, ensure_ascii=False)

            storage._HISTORY_JSON_CACHE.clear()
            list1 = storage.get_history_list(tmpdir)
            self.assertEqual(len(list1), 1)
            self.assertEqual(list1[0]["title"], "初回タイトル")

            # 2回目はキャッシュヒットし json.load を呼ばないこと
            with patch("shift_calendar.storage.json.load", side_effect=AssertionError("should use cache")):
                list2 = storage.get_history_list(tmpdir)
                cal = storage.get_registered_calendar_shifts(tmpdir)
            self.assertEqual(list2[0]["title"], "初回タイトル")
            self.assertIn("2026-11-01", cal["shifts_by_date"])

            # 外部から直接ファイル更新（サイズ＆mtime変更）したら即反映されること
            rec2 = dict(rec1, title="外部更新後タイトル_長め")
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(rec2, f, ensure_ascii=False)
            st = os.stat(fpath)
            os.utime(fpath, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

            list3 = storage.get_history_list(tmpdir)
            self.assertEqual(list3[0]["title"], "外部更新後タイトル_長め")

            # 外部から削除したら即座に消えること
            os.remove(fpath)
            list4 = storage.get_history_list(tmpdir)
            self.assertEqual(list4, [])

    def test_06_frontend_attribute_escaping_and_refactored_helpers(self):
        """項目2・5: index.html の data-key / option エスケープと切り出し関数が正常動作すること"""
        test_js = r"""
        const ctx = createIndexContext();
        const out = vm.runInContext(`
          shiftOptions.push({ key: '早"A<x>', label: '早"A<x>' });
          const row = createShiftTableRow({
            date: "2026-12-01",
            day_of_week: "火",
            type: '早"A<x>',
            status: "work",
            start_time: "06:00",
            end_time: "15:00",
            summary: "test",
            event: ""
          }, 0);
          renderCalendar([{
            date: "2026-12-01",
            day_of_week: "火",
            type: '早"A<x>',
            status: "work",
            start_time: "06:00",
            end_time: "15:00",
            summary: "test",
            event: ""
          }]);
          const grid = document.getElementById("calendar-body");
          const cellHtml = grid.children.map(c => c.innerHTML).join("|");
          JSON.stringify({
            rowHtml: row.innerHTML,
            cellHtml,
            hasApplyViewer: typeof applyHistoryImageToViewer === "function",
            hasApplyEventsUI: typeof applyEventAnalysisResultUI === "function",
            hasBindControls: typeof bindMonthlyCalendarControls === "function",
          });
        `, ctx);
        console.log(out);
        """
        rc, out, err = run_node_harness(test_js)
        self.assertEqual(rc, 0, msg=f"Node harness failed: {err}")
        data = json.loads(out.strip().splitlines()[-1])
        self.assertIn("&quot;", data["rowHtml"])
        self.assertIn("&lt;x&gt;", data["rowHtml"])
        self.assertNotIn('<x>', data["rowHtml"])
        self.assertIn('data-key="早&quot;A&lt;x&gt;"', data["cellHtml"])
        self.assertTrue(data["hasApplyViewer"])
        self.assertTrue(data["hasApplyEventsUI"])
        self.assertTrue(data["hasBindControls"])


if __name__ == "__main__":
    unittest.main()
