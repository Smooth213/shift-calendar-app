import os
import sys
import unittest
import cv2
import numpy as np

# プロジェクトルートをパスに追加
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import app

# 実画像テストフィクスチャ（存在する場合に自動検証）
REAL_PHOTO_DEC = "/Users/saradafumiaki/.gemini/antigravity/brain/ca4c4967-a1cf-4e3a-a9f1-d292a88207fc/.user_uploaded/media_1795158343825_0d8e0e9a.jpg"
REAL_PHOTO_NOV = "/Users/saradafumiaki/.gemini/antigravity/brain/ca4c4967-a1cf-4e3a-a9f1-d292a88207fc/.user_uploaded/media_1795164404714_8aef28eb.jpg"


def measure_horizontal_tilt_deg(img):
    """画像内の主要横罫線群から水平傾き角度の中央値(度)を計測"""
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    binary = cv2.adaptiveThreshold(
        cv2.GaussianBlur(gray, (3, 3), 0), 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 21, 10
    )
    kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (max(30, w // 18), 1))
    horiz = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel_h)
    lines = cv2.HoughLinesP(horiz, 1, np.pi / 180, threshold=80, minLineLength=w // 8, maxLineGap=20)
    angles = []
    if lines is not None:
        for l in lines:
            x1, y1, x2, y2 = l.flatten()
            dx, dy = x2 - x1, y2 - y1
            if dx < 0:
                dx, dy = -dx, -dy
            if dx > 0:
                ang = float(np.degrees(np.arctan2(dy, dx)))
                if -15.0 < ang < 15.0:
                    angles.append(ang)
    return float(np.median(angles)) if angles else 99.0, len(angles)


def measure_vertical_tilt_deg(img):
    """画像内の主要縦罫線群から垂直からの傾き角度の中央値(度)を計測"""
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    sx = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
    sy = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
    vert_only = np.maximum(0.0, sx - 0.7 * sy)
    vert_bin = (vert_only > np.percentile(vert_only, 92)).astype(np.uint8) * 255
    vert_bin = cv2.morphologyEx(vert_bin, cv2.MORPH_CLOSE, np.ones((7, 1), np.uint8))
    lines = cv2.HoughLinesP(vert_bin, 1, np.pi / 180, threshold=60, minLineLength=max(45, h // 8), maxLineGap=20)
    angles = []
    if lines is not None:
        for l in lines:
            x1, y1, x2, y2 = l.flatten()
            dx, dy = x2 - x1, y2 - y1
            if dy < 0:
                dx, dy = -dx, -dy
            if dy > 0:
                ang = float(np.degrees(np.arctan2(dx, dy)))
                if -15.0 < ang < 15.0:
                    angles.append(ang)
    return float(np.median(angles)) if angles else 99.0, len(angles)


def create_synthetic_warped_table():
    """
    外部ファイルに依存しない合成テスト画像を作成：
    ザラザラ壁紙ノイズ背景の上に、18度回転＋台形歪み＋中央アーチたわみを持つ格子表を描画
    """
    rng = np.random.default_rng(42)
    # 薄い壁紙クロス風テクスチャ背景 (輝度 215 ± 8)
    bg = np.full((1200, 900, 3), 215, dtype=np.uint8)
    noise = rng.integers(-8, 9, size=(1200, 900, 1))
    bg = np.clip(bg.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    # クリーンな白紙の格子表を生成 (幅600 x 高さ420)
    tw, th = 600, 420
    table = np.full((th, tw, 3), 248, dtype=np.uint8)
    # 12行 x 20列の格子線を描画
    for r in range(13):
        y = int(round(r * (th - 1) / 12))
        cv2.line(table, (0, y), (tw - 1, y), (30, 30, 30), 2)
    for c in range(21):
        x = int(round(c * (tw - 1) / 20))
        cv2.line(table, (x, 0), (x, th - 1), (30, 30, 30), 2)
    # 日曜日列風の網掛け帯を3本追加
    for col_idx in [1, 8, 15]:
        x1 = int(round(col_idx * (tw - 1) / 20)) + 2
        x2 = int(round((col_idx + 1) * (tw - 1) / 20)) - 2
        table[2:th-2, x1:x2] = (table[2:th-2, x1:x2].astype(np.float32) * 0.65).astype(np.uint8)

    # 紙のアーチ状たわみ（中央が16px上に盛り上がる曲面）を付与
    mx, my = np.meshgrid(np.arange(tw, dtype=np.float32), np.arange(th, dtype=np.float32))
    arch = 16.0 * np.sin(np.pi * mx / float(tw))
    my_warped = np.clip(my + arch, 0, th - 1).astype(np.float32)
    curved_table = cv2.remap(table, mx, my_warped, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    # 斜め18度＋台形歪みで背景に合成
    src = np.float32([[0, 0], [tw - 1, 0], [tw - 1, th - 1], [0, th - 1]])
    dst = np.float32([[90, 280], [780, 440], [710, 860], [110, 740]])
    M = cv2.getPerspectiveTransform(src, dst)
    warped_on_bg = cv2.warpPerspective(curved_table, M, (900, 1200))
    mask = cv2.warpPerspective(np.full((th, tw), 255, dtype=np.uint8), M, (900, 1200))
    bg[mask > 0] = warped_on_bg[mask > 0]

    _, buf = cv2.imencode(".jpg", bg, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return buf.tobytes()


class TestDewarpingPhase1(unittest.TestCase):
    """Phase 1: 3段階 H+V メッシュ補正の品質・精度・べき等性・耐性を保証するテスト"""

    def _assert_grid_quality(self, img_bytes, expected_h_range, label):
        out_bytes, out_b64 = app.dewarp_table_image(img_bytes)
        self.assertIsNotNone(out_b64, f"[{label}] corrected_b64 が None です")
        self.assertTrue(out_b64.startswith("data:image/jpeg;base64,"), f"[{label}] Base64プレフィックス不正")

        out_img = cv2.imdecode(np.frombuffer(out_bytes, np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(out_img, f"[{label}] 出力画像のデコードに失敗")
        oh, ow = out_img.shape[:2]

        # 1. 解像度・アスペクト比保証（途中行での欠け・潰れ防止）
        self.assertEqual(ow, 1400, f"[{label}] 出力幅が1400pxではありません: {ow}")
        self.assertGreaterEqual(oh, expected_h_range[0], f"[{label}] 出力高さが低すぎます（欠けの可能性）: {oh}")
        self.assertLessEqual(oh, expected_h_range[1], f"[{label}] 出力高さが高すぎます: {oh}")

        # 2. 水平精度保証（横罫線の中央値傾き <= 0.5°）
        h_angle, h_count = measure_horizontal_tilt_deg(out_img)
        self.assertGreaterEqual(h_count, 10, f"[{label}] 補正後画像から十分な横罫線が検出できません ({h_count}本)")
        self.assertLessEqual(abs(h_angle), 0.5, f"[{label}] 横罫線の残留傾きが許容値(0.5°)を超過: {h_angle:.3f}°")

        # 3. 垂直精度保証（縦罫線の中央値傾き <= 0.8°）
        v_angle, v_count = measure_vertical_tilt_deg(out_img)
        self.assertGreaterEqual(v_count, 5, f"[{label}] 補正後画像から十分な縦罫線が検出できません ({v_count}本)")
        self.assertLessEqual(abs(v_angle), 0.8, f"[{label}] 縦罫線の残留傾きが許容値(0.8°)を超過: {v_angle:.3f}°")

        # 4. 二重補正防止（べき等性保証）
        out_bytes_2nd, out_b64_2nd = app.dewarp_table_image(out_bytes)
        self.assertIsNotNone(out_b64_2nd, f"[{label}] 2回目補正で None が返りました")
        self.assertEqual(out_bytes, out_bytes_2nd, f"[{label}] 二重補正防止が機能せず再変換されました")

        print(f"  [PASS] {label}: size={ow}x{oh}, H-tilt={h_angle:+.3f}° ({h_count} lines), V-tilt={v_angle:+.3f}° ({v_count} lines), idempotent=OK")
        return out_img

    def test_01_synthetic_warped_and_noisy_bg(self):
        """合成テスト: 壁紙ノイズ＋18°斜め台形＋アーチたわみ画像が水平・垂直に補正されること"""
        raw = create_synthetic_warped_table()
        self._assert_grid_quality(raw, expected_h_range=(800, 1300), label="Synthetic_18deg_Arch")

    @unittest.skipUnless(os.path.exists(REAL_PHOTO_DEC), "12月実写真ファイルが存在しないためスキップ")
    def test_02_real_photo_dec_refrigerator(self):
        """実写真1(12月・冷蔵庫背景・縦長): 水平・垂直精度、マグネット除去、べき等性を保証"""
        with open(REAL_PHOTO_DEC, "rb") as f:
            raw = f.read()
        out_img = self._assert_grid_quality(raw, expected_h_range=(1100, 1450), label="Real_Dec_Fridge")

        # 上部20%にピンクマグネット領域が大きく残っていないこと
        top_part = out_img[:int(out_img.shape[0] * 0.2), :]
        pink_pixels = int(((top_part[:, :, 2] > 150) & (top_part[:, :, 1] < 140) & (top_part[:, :, 0] < 140)).sum())
        self.assertLess(pink_pixels, 500, f"上部にマグネットが残っています (pink_pixels={pink_pixels})")

    @unittest.skipUnless(os.path.exists(REAL_PHOTO_NOV), "11月実写真ファイルが存在しないためスキップ")
    def test_03_real_photo_nov_wallpaper_25deg(self):
        """実写真2(11月・壁紙テクスチャ・斜め25°・横長): 壁紙誤検出ゼロ・水平垂直精度・べき等性を保証"""
        with open(REAL_PHOTO_NOV, "rb") as f:
            raw = f.read()
        self._assert_grid_quality(raw, expected_h_range=(400, 560), label="Real_Nov_Wall_25deg")

    def test_04_invalid_and_blank_image_fallback(self):
        """異常系: 破損データ・白紙画像でもクラッシュせず安全にフォールバックすること"""
        b_err, b64_err = app.dewarp_table_image(b"not-a-valid-image")
        self.assertEqual(b_err, b"not-a-valid-image")
        self.assertIsNone(b64_err)

        blank = np.full((600, 600, 3), 255, dtype=np.uint8)
        _, buf = cv2.imencode(".jpg", blank)
        blank_bytes = buf.tobytes()
        b_blank, b64_blank = app.dewarp_table_image(blank_bytes)
        self.assertEqual(b_blank, blank_bytes)
        self.assertIsNone(b64_blank)


if __name__ == "__main__":
    unittest.main(verbosity=2)
