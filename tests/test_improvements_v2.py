"""項目1〜7の改善機能（静的ファイル分割・ローカルQR・カレンダー安全性・区分編集・カレンダー直接修正・ZIPバックアップ復元）の検証テスト。"""

import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import app as shift_app
from shift_calendar.calendar_export import _format_osascript_error, register_to_apple_calendar
from shift_calendar.config import validate_time_definitions
from shift_calendar.qr import encode_qr_matrix, render_qr_svg
from shift_calendar.storage import (
    export_history_backup_zip,
    get_history_detail,
    get_registered_calendar_shifts,
    import_history_backup_zip,
    save_history,
    update_history_shift,
)
from tests.dom_harness import extract_index_script, run_node_harness


class _MockRequestHandler(shift_app.RequestHandler):
    """ソケットなしで RequestHandler メソッドを直接テストするための軽量モック。"""

    def __init__(self, path="/", client_ip="127.0.0.1", headers=None):
        self.path = path
        self.client_address = (client_ip, 54321)
        self.headers = headers or {}
        self.wfile = io.BytesIO()
        self.response_status = None
        self.response_headers = {}

    def send_response(self, code, message=None):
        self.response_status = code

    def send_header(self, keyword, value):
        self.response_headers[keyword] = value

    def end_headers(self):
        pass

    def send_error(self, code, message=None, explain=None):
        self.response_status = code


class TestImprovementsV2(unittest.TestCase):
    # --- Phase 1: 静的ファイル配信とパストラバーサル防止 ---
    def test_01_static_asset_resolution_and_traversal_blocked(self):
        css_path, css_type = shift_app._resolve_static_asset_path("styles.css")
        js_path, js_type = shift_app._resolve_static_asset_path("app.js")
        self.assertIsNotNone(css_path)
        self.assertIn("text/css", css_type)
        self.assertIsNotNone(js_path)
        self.assertIn("javascript", js_type)

        for bad in ("../config.json", "../../etc/passwd", "app.py", "..\\config.json", "sub/../../app.py", ""):
            path, ctype = shift_app._resolve_static_asset_path(bad)
            self.assertIsNone(path, msg=f"不正パスが許可されました: {bad}")
            self.assertIsNone(ctype)

    # --- Phase 2: ローカルQR生成とAppleカレンダー安全性 ---
    def test_02_local_qr_svg_decodable_and_no_external_qr_api(self):
        det = cv2.QRCodeDetector()
        for url in ("http://192.168.1.25:8765", "http://my-mac.local:8765/?tab=calendar"):
            mat = encode_qr_matrix(url)
            border, scale = 4, 8
            dim = len(mat) + border * 2
            img = np.full((dim * scale, dim * scale), 255, dtype=np.uint8)
            for r, row in enumerate(mat):
                for c, val in enumerate(row):
                    if val:
                        y, x = (r + border) * scale, (c + border) * scale
                        img[y:y + scale, x:x + scale] = 0
            decoded, _, _ = det.detectAndDecode(img)
            self.assertEqual(decoded, url)
            svg = render_qr_svg(url)
            self.assertTrue(svg.startswith("<svg "))
            self.assertIn("</svg>", svg)

        # フロントエンドに外部QRサービスへの参照が残っていないこと
        script_src = extract_index_script()
        self.assertNotIn("api.qrserver.com", script_src)
        self.assertIn("/api/qr.svg", script_src)

    def test_03_apple_calendar_timeout_and_permission_error_messages(self):
        shifts = [{"date": "2026-11-22", "status": "work", "type": "早A", "start_time": "06:00", "end_time": "15:00", "summary": "[早A] (06:00〜15:00)"}]
        with patch("shift_calendar.calendar_export.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=5)):
            with self.assertRaises(RuntimeError) as ctx:
                register_to_apple_calendar(shifts, timeout=5)
            self.assertIn("タイムアウト", str(ctx.exception))
            self.assertIn("5秒", str(ctx.exception))

        perm_msg = _format_osascript_error("execution error: Not authorized to send Apple events to Calendar. (-1743)")
        self.assertIn("オートメーション", perm_msg)
        self.assertIn("-1743", perm_msg)

    def test_04_register_confirm_message_warns_on_non_default_calendar(self):
        test_js = r"""
        const ctx = createIndexContext();
        const out = vm.runInContext(`
          const sample = [
            { date: "2026-11-01", event: "会議" },
            { date: "2026-11-02", event: "" }
          ];
          JSON.stringify({
            defMsg: buildRegisterConfirmMessage(sample, "シフトカレンダー", true),
            customMsg: buildRegisterConfirmMessage(sample, "仕事用メイン", true)
          });
        `, ctx);
        console.log(out);
        """
        rc, out, err = run_node_harness(test_js)
        self.assertEqual(rc, 0, msg=f"Node harness failed: {err}")
        data = json.loads(out.strip().splitlines()[-1])
        self.assertIn("2026-11-01 〜 2026-11-02", data["defMsg"])
        self.assertIn("行事予定 1件", data["defMsg"])
        self.assertNotIn("【注意】", data["defMsg"])
        self.assertIn("【注意】", data["customMsg"])
        self.assertIn("仕事用メイン", data["customMsg"])

    # --- Phase 3: シフト区分バリデーション・カレンダータブ直接修正 ---
    def test_05_validate_time_definitions_rules(self):
        valid = validate_time_definitions({"早A": {"start": "06:00", "end": "15:00"}, "夜勤": {"start": "16:30", "end": "09:30"}})
        self.assertEqual(valid["夜勤"], {"start": "16:30", "end": "09:30"})

        for bad in (
            {},
            {"": {"start": "08:00", "end": "17:00"}},
            {"休": {"start": "08:00", "end": "17:00"}},
            {"有給": {"start": "08:00", "end": "17:00"}},
            {"早A": {"start": "25:00", "end": "17:00"}},
            {"早A": {"start": "08:00", "end": "bad"}},
        ):
            with self.assertRaises(ValueError, msg=f"不正定義が通りました: {bad}"):
                validate_time_definitions(bad)

    def test_06_update_history_shift_type_event_and_paid_leave(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_id = save_history(tmpdir, {
                "title": "2026年11月度",
                "registered": True,
                "shifts": [
                    {
                        "date": "2026-11-10",
                        "type": "早A",
                        "status": "work",
                        "is_holiday": False,
                        "is_paid_leave": False,
                        "start_time": "06:00",
                        "end_time": "15:00",
                        "hourly_paid_leave": 2.0,
                        "summary": "[早A] (06:00〜15:00)（時間有給2h）",
                        "event": "",
                    }
                ],
            })
            cfg_loader = lambda: {
                "time_definitions": {"遅B": {"start": "09:30", "end": "18:30"}},
                "paid_leave_hours_per_day": 8.0,
            }

            # 出勤区分変更＋行事予定追加
            updated = update_history_shift(tmpdir, hist_id, "2026-11-10", {"type": "遅B", "event": "避難訓練"}, cfg_loader)
            self.assertEqual(updated["type"], "遅B")
            self.assertEqual(updated["start_time"], "09:30")
            self.assertEqual(updated["end_time"], "18:30")
            self.assertEqual(updated["summary"], "[遅B] (09:30〜18:30)（時間有給2h）")
            self.assertEqual(updated["event"], "避難訓練")

            # 有給へ変更すると時間有給は自動で 0.0 になる
            updated_paid = update_history_shift(tmpdir, hist_id, "2026-11-10", {"type": "有給"}, cfg_loader)
            self.assertEqual(updated_paid["status"], "paid_leave")
            self.assertTrue(updated_paid["is_paid_leave"])
            self.assertEqual(updated_paid["hourly_paid_leave"], 0.0)
            self.assertEqual(updated_paid["summary"], "有給休暇")

    def test_07_frontend_calendar_direct_shift_edit_flow(self):
        test_js = r"""
        const calls = [];
        const ctx = createIndexContext(async (url, opts) => {
          calls.push({ url, method: (opts && opts.method) || "GET", body: opts && opts.body ? JSON.parse(opts.body) : null });
          if (url === "/api/calendar_shifts/update") {
            return { ok: true, json: async () => ({ success: true, apple_calendar_synced: true }) };
          }
          if (url === "/api/calendar_shifts") {
            return { ok: true, json: async () => ({ success: true, shifts_by_date: {}, available_months: [] }) };
          }
          return { ok: true, json: async () => ({}) };
        });
        const out = await vm.runInContext(`
          (async () => {
            masterTimeDefs = { "早A": { start: "06:00", end: "15:00" }, "遅C": { start: "10:00", end: "19:00" } };
            AppState.calendar.shiftsByDate = {
              "2026-11-15": {
                date: "2026-11-15",
                type: "早A",
                status: "work",
                start_time: "06:00",
                end_time: "15:00",
                event: "",
                history_id: "hist_123",
                history_title: "2026年11月度"
              }
            };
            renderSelectedDateDetail("2026-11-15");
            const editVisible = getEl("cal-detail-shift-edit-box").classList.contains("is-visible");
            const typeOptionsHtml = getEl("cal-detail-shift-type").innerHTML;
            getEl("cal-detail-shift-type").value = "遅C";
            getEl("cal-detail-event-input").value = "研修会";
            getEl("cal-detail-hourly-sync-apple").checked = true;
            await getEl("btn-cal-save-shift").dispatchAsync("click");
            return { editVisible, typeOptionsHtml };
          })()
        `, ctx);
        console.log(JSON.stringify({ out, calls }));
        """
        rc, out, err = run_node_harness(test_js)
        self.assertEqual(rc, 0, msg=f"Node harness failed: {err}")
        payload = json.loads(out.strip().splitlines()[-1])
        self.assertTrue(payload["out"]["editVisible"])
        self.assertIn("遅C", payload["out"]["typeOptionsHtml"])
        upd_calls = [c for c in payload["calls"] if c["url"] == "/api/calendar_shifts/update"]
        self.assertEqual(len(upd_calls), 1)
        self.assertEqual(upd_calls[0]["body"]["type"], "遅C")
        self.assertEqual(upd_calls[0]["body"]["event"], "研修会")
        self.assertTrue(upd_calls[0]["body"]["sync_apple_calendar"])

    # --- Phase 4: 履歴ZIPバックアップ／復元とセキュリティ ---
    def test_08_history_backup_zip_roundtrip_and_non_destructive_merge(self):
        with tempfile.TemporaryDirectory() as src_dir, tempfile.TemporaryDirectory() as dst_dir:
            h1 = save_history(src_dir, {
                "id": "hist_202611",
                "title": "2026年11月度",
                "registered": True,
                "image_base64": "ZmFrZV9pbWFnZV9kYXRh",
                "shifts": [{"date": "2026-11-01", "type": "有給", "status": "paid_leave", "is_paid_leave": True}],
            })
            zip_bytes = export_history_backup_zip(src_dir)
            self.assertGreater(len(zip_bytes), 0)

            # 空ディレクトリへ復元
            res1 = import_history_backup_zip(dst_dir, zip_bytes, overwrite=False)
            self.assertEqual(res1["imported_histories"], 1)
            self.assertEqual(res1["skipped_histories"], 0)
            self.assertEqual(res1["imported_images"], 1)

            detail = get_history_detail(dst_dir, h1)
            self.assertIsNotNone(detail)
            self.assertEqual(detail["image_base64"], "ZmFrZV9pbWFnZV9kYXRh")
            cal = get_registered_calendar_shifts(dst_dir)
            self.assertIn("2026-11-01", cal["shifts_by_date"])

            # 2回目（overwrite=False）は既存IDがスキップされること
            res2 = import_history_backup_zip(dst_dir, zip_bytes, overwrite=False)
            self.assertEqual(res2["imported_histories"], 0)
            self.assertEqual(res2["skipped_histories"], 1)

    def test_09_history_restore_rejects_malicious_zip_and_non_loopback(self):
        with tempfile.TemporaryDirectory() as dst_dir:
            # パストラバーサルZIP
            bad_buf = io.BytesIO()
            with zipfile.ZipFile(bad_buf, "w") as zf:
                zf.writestr("../escape.json", "{}")
            with self.assertRaises(ValueError):
                import_history_backup_zip(dst_dir, bad_buf.getvalue())

            # 壊れたJSONを含むZIP
            broken_buf = io.BytesIO()
            with zipfile.ZipFile(broken_buf, "w") as zf:
                zf.writestr("history/ok_1.json", '{"id": "ok_1", "shifts": []}')
                zf.writestr("history/bad_2.json", "{invalid json")
            with self.assertRaises(ValueError):
                import_history_backup_zip(dst_dir, broken_buf.getvalue())
            # 事前検証により1件も書き込まれていないこと
            self.assertEqual(os.listdir(dst_dir), [])

            # 非ループバック端末からの /api/history/restore は 403 拒否
            handler = _MockRequestHandler(path="/api/history/restore", client_ip="192.168.1.50")
            body = json.dumps({"zip_base64": base64.b64encode(b"dummy").decode("ascii")}).encode("utf-8")
            handler._handle_post_history_restore(body)
            self.assertEqual(handler.response_status, 403)


if __name__ == "__main__":
    unittest.main()
