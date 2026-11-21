import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import app as shift_app


class TestPhase2HistoryStorage(unittest.TestCase):
    def test_01_image_separated_from_json_and_restored_on_detail(self):
        """新規保存時に画像が history_images/<id>.b64 へ分離され、JSONは軽量・詳細取得で完全復元されること"""
        with tempfile.TemporaryDirectory() as parent_dir:
            hist_dir = os.path.join(parent_dir, "history")
            img_dir = os.path.join(parent_dir, "history_images")
            large_b64 = "data:image/jpeg;base64," + ("A" * 50000)
            with patch.object(shift_app, "HISTORY_DIR", hist_dir):
                hid = shift_app.save_history({
                    "id": "sep_test_01",
                    "title": "2026年11月シフト",
                    "registered": True,
                    "image_base64": large_b64,
                    "shifts": [{"date": "2026-11-01", "type": "日", "status": "work"}],
                })

                json_path = os.path.join(hist_dir, f"{hid}.json")
                img_path = os.path.join(img_dir, f"{hid}.b64")
                self.assertTrue(os.path.isfile(json_path))
                self.assertTrue(os.path.isfile(img_path))
                # HISTORY_DIR 直下には JSON のみ存在する
                self.assertEqual(os.listdir(hist_dir), [f"{hid}.json"])

                # JSON 自体は軽量（image_base64 を含まない）
                with open(json_path, "r", encoding="utf-8") as f:
                    raw_json = json.load(f)
                self.assertNotIn("image_base64", raw_json)
                self.assertEqual(raw_json.get("image_file"), f"{hid}.b64")
                self.assertTrue(raw_json.get("has_image"))
                self.assertLess(os.path.getsize(json_path), 2048)

                # 一覧では has_image=True
                hist_list = shift_app.get_history_list()
                self.assertEqual(len(hist_list), 1)
                self.assertTrue(hist_list[0]["has_image"])

                # 詳細では元の文字列が完全一致で復元される
                detail = shift_app.get_history_detail(hid)
                self.assertEqual(detail["image_base64"], large_b64)

    def test_02_legacy_inline_json_backward_compatibility_and_lazy_migration(self):
        """旧形式（JSON内 image_base64 直書き）がそのまま読め、再保存時に分離形式へ自動移行されること"""
        with tempfile.TemporaryDirectory() as parent_dir:
            hist_dir = os.path.join(parent_dir, "history")
            img_dir = os.path.join(parent_dir, "history_images")
            os.makedirs(hist_dir, exist_ok=True)
            legacy_id = "legacy_202610"
            legacy_img = "data:image/png;base64,LEGACY_DATA_12345"
            legacy_path = os.path.join(hist_dir, f"{legacy_id}.json")
            with open(legacy_path, "w", encoding="utf-8") as f:
                json.dump({
                    "id": legacy_id,
                    "title": "旧形式シフト",
                    "created_at": "2026-10-01 09:00:00",
                    "registered": True,
                    "image_base64": legacy_img,
                    "shifts": [{"date": "2026-10-01", "type": "早A", "status": "work"}],
                }, f, ensure_ascii=False)

            with patch.object(shift_app, "HISTORY_DIR", hist_dir):
                # そのまま一覧・詳細が読める
                items = shift_app.get_history_list()
                self.assertEqual(len(items), 1)
                self.assertTrue(items[0]["has_image"])
                detail = shift_app.get_history_detail(legacy_id)
                self.assertEqual(detail["image_base64"], legacy_img)

                # 同一IDで画像未指定の上書き保存をすると分離形式へ移行しつつ画像を保持
                shift_app.save_history({
                    "id": legacy_id,
                    "title": "旧形式シフト（更新）",
                    "shifts": [{"date": "2026-10-01", "type": "日", "status": "work"}],
                })
                with open(legacy_path, "r", encoding="utf-8") as f:
                    migrated_raw = json.load(f)
                self.assertNotIn("image_base64", migrated_raw)
                self.assertTrue(migrated_raw.get("has_image"))
                self.assertTrue(os.path.isfile(os.path.join(img_dir, f"{legacy_id}.b64")))

                detail_after = shift_app.get_history_detail(legacy_id)
                self.assertEqual(detail_after["image_base64"], legacy_img)

    def test_03_delete_and_prune_remove_separated_image_files(self):
        """delete_history および prune_unregistered_history で分離画像ファイルも漏れなく削除されること"""
        with tempfile.TemporaryDirectory() as parent_dir:
            hist_dir = os.path.join(parent_dir, "history")
            img_dir = os.path.join(parent_dir, "history_images")
            with patch.object(shift_app, "HISTORY_DIR", hist_dir):
                # 未登録を7件保存 -> 古い2件が自動剪定される
                ids = []
                for i in range(7):
                    hid = shift_app.save_history({
                        "id": f"unreg_{i:02d}",
                        "created_at": f"2026-11-0{i+1} 10:00:00",
                        "registered": False,
                        "image_base64": f"IMG_{i}",
                        "shifts": [{"date": f"2026-11-0{i+1}", "type": "日", "status": "work"}],
                    })
                    ids.append(hid)

                # 古い2件の分離画像も削除されていること
                for pruned_id in ids[:2]:
                    self.assertFalse(os.path.exists(os.path.join(hist_dir, f"{pruned_id}.json")))
                    self.assertFalse(os.path.exists(os.path.join(img_dir, f"{pruned_id}.b64")))

                # 残った5件の分離画像は存在すること
                for kept_id in ids[2:]:
                    self.assertTrue(os.path.isfile(os.path.join(img_dir, f"{kept_id}.b64")))

                # 明示削除でJSONと分離画像の両方が消えること
                target_id = ids[-1]
                self.assertTrue(shift_app.delete_history(target_id))
                self.assertFalse(os.path.exists(os.path.join(hist_dir, f"{target_id}.json")))
                self.assertFalse(os.path.exists(os.path.join(img_dir, f"{target_id}.b64")))

    def test_04_image_file_path_traversal_is_blocked(self):
        """image_file にディレクトリトラバーサルが含まれても画像ディレクトリ外を読まないこと"""
        with tempfile.TemporaryDirectory() as parent_dir:
            hist_dir = os.path.join(parent_dir, "history")
            os.makedirs(hist_dir, exist_ok=True)
            outside_secret = os.path.join(parent_dir, "secret.txt")
            with open(outside_secret, "w", encoding="utf-8") as f:
                f.write("TOP_SECRET")

            malicious_json = os.path.join(hist_dir, "evil_hist.json")
            with open(malicious_json, "w", encoding="utf-8") as f:
                json.dump({
                    "id": "evil_hist",
                    "title": "不正参照テスト",
                    "image_file": "../secret.txt",
                    "shifts": [],
                }, f)

            with patch.object(shift_app, "HISTORY_DIR", hist_dir):
                detail = shift_app.get_history_detail("evil_hist")
                self.assertIsNotNone(detail)
                self.assertNotEqual(detail.get("image_base64"), "TOP_SECRET")
                self.assertFalse(bool(detail.get("image_base64")))


if __name__ == "__main__":
    unittest.main()
