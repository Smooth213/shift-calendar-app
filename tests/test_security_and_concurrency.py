import io
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import app as shift_app


def _make_mock_handler(path, method="GET", body_dict=None, headers=None, client_ip="127.0.0.1"):
    handler = object.__new__(shift_app.RequestHandler)
    handler.path = path
    handler.command = method
    handler.client_address = (client_ip, 54321)
    raw_body = json.dumps(body_dict).encode("utf-8") if body_dict is not None else b""
    hdrs = {"Content-Length": str(len(raw_body))}
    if headers:
        hdrs.update(headers)
    handler.headers = hdrs
    handler.rfile = io.BytesIO(raw_body)
    handler.wfile = io.BytesIO()
    handler._status = None
    handler._resp_headers = {}

    def _send_response(code, message=None):
        handler._status = code

    def _send_header(k, v):
        handler._resp_headers[k] = v

    def _end_headers():
        pass

    handler.send_response = _send_response
    handler.send_header = _send_header
    handler.end_headers = _end_headers
    return handler


class TestPhase1SecurityAndConcurrency(unittest.TestCase):
    def test_01_default_config_has_no_hardcoded_api_key(self):
        """config.json 不在時のデフォルト設定にAPIキーがハードコードされていないこと"""
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_cfg = os.path.join(tmpdir, "config.json")
            with patch.object(shift_app, "CONFIG_PATH", missing_cfg):
                cfg = shift_app.load_config()
                self.assertEqual(cfg.get("api_key"), "")

    def test_02_save_config_excludes_runtime_derived_keys_and_writes_atomically(self):
        """save_config が実行時派生キーを永続化せず、一時ファイルを残さず保存すること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            with patch.object(shift_app, "CONFIG_PATH", cfg_path):
                cfg = shift_app.load_config()
                cfg["calendar_name"] = "テストカレンダー"
                cfg["server_version"] = "9.9.9"
                shift_app.save_config(cfg)

                with open(cfg_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)

                self.assertEqual(saved["calendar_name"], "テストカレンダー")
                for runtime_key in ("local_ip", "mobile_url", "backend_version", "server_version"):
                    self.assertNotIn(runtime_key, saved)

                leftover_tmp = [n for n in os.listdir(tmpdir) if n.startswith(".tmp_")]
                self.assertEqual(leftover_tmp, [])

    def test_03_preload_rejects_non_loopback_client(self):
        """/api/preload がループバック以外（LAN他端末等）からの要求を403で拒否すること"""
        handler = _make_mock_handler(
            "/api/preload",
            method="POST",
            body_dict={"file_path": "/tmp/dummy.png"},
            client_ip="192.168.1.50",
        )
        handler.do_POST()
        self.assertEqual(handler._status, 403)
        resp = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertIn("error", resp)

    def test_04_preload_rejects_non_image_and_missing_files(self):
        """/api/preload が非画像ファイル（.json/.txt等）や存在しないパスを400で拒否すること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            secret_file = os.path.join(tmpdir, "secret.json")
            with open(secret_file, "w", encoding="utf-8") as f:
                f.write('{"api_key":"secret"}')

            # 非画像ファイル
            h1 = _make_mock_handler(
                "/api/preload",
                method="POST",
                body_dict={"file_path": secret_file},
                client_ip="127.0.0.1",
            )
            h1.do_POST()
            self.assertEqual(h1._status, 400)

            # ディレクトリ
            h2 = _make_mock_handler(
                "/api/preload",
                method="POST",
                body_dict={"file_path": tmpdir},
                client_ip="127.0.0.1",
            )
            h2.do_POST()
            self.assertEqual(h2._status, 400)

            # 存在しないファイル
            h3 = _make_mock_handler(
                "/api/preload",
                method="POST",
                body_dict={"file_path": os.path.join(tmpdir, "missing.png")},
                client_ip="127.0.0.1",
            )
            h3.do_POST()
            self.assertEqual(h3._status, 400)

    def test_05_preload_accepts_loopback_image_file(self):
        """/api/preload がループバックからの実在画像ファイルを受け入れること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            img_path = os.path.join(tmpdir, "sample.png")
            # 最小のダミーバイト（dewarpはモックして高速検証）
            with open(img_path, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

            orig_preloaded = shift_app.PRELOADED_IMAGE
            try:
                with patch.object(
                    shift_app,
                    "dewarp_table_image_with_status",
                    return_value=(b"img", None, {"status": "skipped", "label": "補正なし"}),
                ):
                    h = _make_mock_handler(
                        "/api/preload",
                        method="POST",
                        body_dict={"file_path": img_path},
                        client_ip="127.0.0.1",
                    )
                    h.do_POST()
                self.assertEqual(h._status, 200)
                resp = json.loads(h.wfile.getvalue().decode("utf-8"))
                self.assertTrue(resp.get("success"))
                self.assertEqual(resp.get("file_name"), "sample.png")
                self.assertEqual(shift_app.PRELOADED_IMAGE["file_name"], "sample.png")
            finally:
                shift_app.PRELOADED_IMAGE = orig_preloaded

    def test_06_cors_blocks_external_origin_and_allows_local_and_lan(self):
        """外部オリジンにはCORSを許可せず、localhost/LANオリジンのみ許可すること"""
        with patch.object(shift_app, "get_local_ip", return_value="192.168.1.25"):
            # 外部オリジン -> OPTIONS は 403、GET には Allow-Origin なし
            h_evil_opt = _make_mock_handler(
                "/api/config",
                method="OPTIONS",
                headers={"Origin": "https://evil.example.com"},
            )
            h_evil_opt.do_OPTIONS()
            self.assertEqual(h_evil_opt._status, 403)
            self.assertNotIn("Access-Control-Allow-Origin", h_evil_opt._resp_headers)

            h_evil_get = _make_mock_handler(
                "/api/heartbeat",
                method="GET",
                headers={"Origin": "https://evil.example.com"},
            )
            h_evil_get.do_GET()
            self.assertEqual(h_evil_get._status, 200)
            self.assertNotIn("Access-Control-Allow-Origin", h_evil_get._resp_headers)

            # ローカル・LANオリジン -> 許可
            for ok_origin in ("http://localhost:8765", "http://127.0.0.1:8765", "http://192.168.1.25:8765"):
                h_ok = _make_mock_handler(
                    "/api/heartbeat",
                    method="GET",
                    headers={"Origin": ok_origin},
                )
                h_ok.do_GET()
                self.assertEqual(h_ok._status, 200)
                self.assertEqual(h_ok._resp_headers.get("Access-Control-Allow-Origin"), ok_origin)
                self.assertEqual(h_ok._resp_headers.get("Vary"), "Origin")

    def test_07_concurrent_history_save_and_progress_updates_are_safe(self):
        """複数スレッドからの同時 save_history / get_history_list / progress 更新で破損しないこと"""
        with tempfile.TemporaryDirectory() as tmpdir:
            errors = []
            saved_ids = []
            ids_lock = threading.Lock()

            def worker(idx):
                try:
                    for j in range(5):
                        shift_app.set_analyze_progress(idx * 10 + j, f"phase-{idx}", f"detail-{j}", step=1, active=True)
                        snap = shift_app.get_analyze_progress()
                        self.assertIn("percent", snap)
                        hid = shift_app.save_history({
                            "title": f"shift-{idx}-{j}",
                            "registered": (j % 2 == 0),
                            "shifts": [{"date": "2026-11-01", "type": "日", "status": "work"}],
                        })
                        with ids_lock:
                            saved_ids.append(hid)
                        _ = shift_app.get_history_list()
                except Exception as e:
                    errors.append(e)

            with patch.object(shift_app, "HISTORY_DIR", tmpdir):
                threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

                self.assertEqual(errors, [])
                # 保存された全JSONファイルが破損せず読み込めること
                json_files = [f for f in os.listdir(tmpdir) if f.endswith(".json")]
                self.assertGreater(len(json_files), 0)
                for fname in json_files:
                    with open(os.path.join(tmpdir, fname), "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self.assertIn("id", data)
                # 一時ファイルが残留していないこと
                tmp_files = [f for f in os.listdir(tmpdir) if f.startswith(".tmp_")]
                self.assertEqual(tmp_files, [])


if __name__ == "__main__":
    unittest.main()
