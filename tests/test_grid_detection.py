import os
import sys
import unittest
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import app

REAL_PHOTO_DEC = "/Users/saradafumiaki/.gemini/antigravity/brain/ca4c4967-a1cf-4e3a-a9f1-d292a88207fc/.user_uploaded/media_1795158343825_0d8e0e9a.jpg"
REAL_PHOTO_NOV = "/Users/saradafumiaki/.gemini/antigravity/brain/ca4c4967-a1cf-4e3a-a9f1-d292a88207fc/.user_uploaded/media_1795164404714_8aef28eb.jpg"


class TestGridDetectionPhase2(unittest.TestCase):
    """Phase 2: 幾何学的グリッド検出（縦区切り線・横罫線・対象者行スナップ）を保証するテスト"""

    @unittest.skipUnless(os.path.exists(REAL_PHOTO_DEC), "12月実写真が存在しないためスキップ")
    def test_01_dec_grid_36_columns_and_row_snap(self):
        """12月シフト表: 厳密に36列が均一幅で検出され、皿田行が実横罫線にスナップすること"""
        with open(REAL_PHOTO_DEC, "rb") as f:
            raw = f.read()
        dewarped, _ = app.dewarp_table_image(raw)
        grid = app.detect_table_grid(dewarped)

        self.assertIsNotNone(grid, "12月表のグリッド検出に失敗")
        self.assertEqual(grid["n_cols"], 36, f"12月表は36列であるべきですが {grid['n_cols']} 列が検出されました")
        self.assertEqual(len(grid["grid_x"]), 37)
        self.assertEqual(len(grid["grid_x_norm"]), 37)

        diffs = np.diff(grid["grid_x"])
        self.assertGreaterEqual(int(diffs.min()), 30, f"列幅が狭すぎる箇所あり: min={diffs.min()}")
        self.assertLessEqual(int(diffs.max()), 45, f"列幅が広すぎる箇所あり: max={diffs.max()}")
        self.assertGreaterEqual(len(grid["h_lines"]), 15, f"横罫線本数が不足: {len(grid['h_lines'])}")

        # 皿田行のおおよその位置(330..350)を渡したとき、実横罫線ペアへ綺麗にスナップすること
        sy1, sy2 = app.snap_row_band_to_grid(grid, 330, 350)
        self.assertIn(sy1, grid["h_lines_norm"])
        self.assertIn(sy2, grid["h_lines_norm"])
        self.assertGreater(sy2, sy1)
        self.assertLessEqual(sy2 - sy1, 40)
        print(f"  [PASS] Dec Grid: {grid['n_cols']} cols (width {diffs.min()}..{diffs.max()}px), {len(grid['h_lines'])} h_lines, snapped_row=[{sy1}, {sy2}]")

    @unittest.skipUnless(os.path.exists(REAL_PHOTO_NOV), "11月実写真が存在しないためスキップ")
    def test_02_nov_grid_35_columns_and_row_snap(self):
        """11月シフト表(斜め25°壁紙): 厳密に35列が均一幅で検出され、皿田行が実横罫線にスナップすること"""
        with open(REAL_PHOTO_NOV, "rb") as f:
            raw = f.read()
        dewarped, _ = app.dewarp_table_image(raw)
        grid = app.detect_table_grid(dewarped)

        self.assertIsNotNone(grid, "11月表のグリッド検出に失敗")
        self.assertEqual(grid["n_cols"], 35, f"11月表は35列であるべきですが {grid['n_cols']} 列が検出されました")
        self.assertEqual(len(grid["grid_x"]), 36)
        self.assertEqual(len(grid["grid_x_norm"]), 36)

        diffs = np.diff(grid["grid_x"])
        self.assertGreaterEqual(int(diffs.min()), 30, f"列幅が狭すぎる箇所あり: min={diffs.min()}")
        self.assertLessEqual(int(diffs.max()), 46, f"列幅が広すぎる箇所あり: max={diffs.max()}")
        self.assertGreaterEqual(len(grid["h_lines"]), 13, f"横罫線本数が不足: {len(grid['h_lines'])}")

        # 11月表での皿田行のおおよその位置(520..545)を実横罫線ペアへスナップ
        sy1, sy2 = app.snap_row_band_to_grid(grid, 520, 545)
        self.assertIn(sy1, grid["h_lines_norm"])
        self.assertIn(sy2, grid["h_lines_norm"])
        self.assertGreater(sy2, sy1)
        self.assertLessEqual(sy2 - sy1, 60)
        print(f"  [PASS] Nov Grid: {grid['n_cols']} cols (width {diffs.min()}..{diffs.max()}px), {len(grid['h_lines'])} h_lines, snapped_row=[{sy1}, {sy2}]")

    def test_03_invalid_bytes_returns_none(self):
        """異常系: 不正なバイト列でクラッシュせず None を返すこと"""
        self.assertIsNone(app.detect_table_grid(b"invalid-bytes"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
