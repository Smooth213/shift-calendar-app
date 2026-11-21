import base64
import os
import subprocess
import tempfile
import cv2
import numpy as np


def _detect_table_outer_hull(img):
    """基準解像度(長辺1024px)で壁紙ノイズを除去し、勤務表外枠の凸包・スケール・面積比を返す。"""
    orig_h, orig_w = img.shape[:2]
    scale = 1024.0 / max(orig_h, orig_w)
    work_w = int(round(orig_w * scale))
    work_h = int(round(orig_h * scale))
    work_img = cv2.resize(img, (work_w, work_h), interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(work_img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    # C=17により壁紙のザラザラ模様や薄い影を完全消去し、紙上の黒い罫線のみを抽出
    binary = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 17)

    # 孤立ノイズを除去し、罫線ネットワーク（幅/高さ>40px または 面積>200px）のみ残す
    num_l, labels, stats, _ = cv2.connectedComponentsWithStats(binary)
    clean = np.zeros_like(binary)
    for i in range(1, num_l):
        if stats[i, cv2.CC_STAT_WIDTH] > 40 or stats[i, cv2.CC_STAT_HEIGHT] > 40 or stats[i, cv2.CC_STAT_AREA] > 200:
            clean[labels == i] = 255

    closed = cv2.morphologyEx(clean, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None, scale, 0.0

    # 面積と矩形度(solidity)の積が最大の凸包（勤務表の外枠）を選択
    best_hull = None
    best_score = -1.0
    for c in contours:
        area = cv2.contourArea(c)
        if area < (work_w * work_h) * 0.04:
            continue
        hull = cv2.convexHull(c)
        hull_area = cv2.contourArea(hull)
        rect = cv2.minAreaRect(hull)
        rw, rh = rect[1]
        if rw < 50 or rh < 50:
            continue
        sol = hull_area / max(rw * rh, 1.0)
        if sol < 0.65:
            continue
        score = hull_area * (sol ** 2)
        if score > best_score:
            best_score = score
            best_hull = hull

    if best_hull is None:
        return None, scale, 0.0

    area_ratio = cv2.contourArea(best_hull) / float(work_w * work_h)
    return best_hull, scale, area_ratio


def _warp_table_perspective(img, best_hull, scale):
    """Stage 1: 凸包から4隅を特定し、3D射影変換（ホモグラフィ）で正面投影へ起こす。"""
    peri = cv2.arcLength(best_hull, True)
    approx = None
    for eps_ratio in np.linspace(0.01, 0.12, 40):
        cand = cv2.approxPolyDP(best_hull, eps_ratio * peri, True)
        if len(cand) == 4:
            approx = cand.reshape(4, 2).astype(np.float32)
            break
    if approx is None:
        approx = cv2.boxPoints(cv2.minAreaRect(best_hull)).astype(np.float32)

    # X座標で左2点・右2点、それぞれY座標で上下に分けて TL, TR, BR, BL を確定（±45°対応）
    x_sorted = approx[np.argsort(approx[:, 0])]
    tl, bl = x_sorted[:2][np.argsort(x_sorted[:2, 1])]
    tr, br = x_sorted[2:][np.argsort(x_sorted[2:, 1])]

    src_pts = np.array([tl, tr, br, bl], dtype=np.float32) / scale

    w_est = 0.5 * (np.linalg.norm(src_pts[1] - src_pts[0]) + np.linalg.norm(src_pts[2] - src_pts[3]))
    h_est = 0.5 * (np.linalg.norm(src_pts[3] - src_pts[0]) + np.linalg.norm(src_pts[2] - src_pts[1]))
    out_w = 1400
    aspect = h_est / max(w_est, 1.0)
    # 上部の「R8年○月・時間凡例」領域を含めるため、表の縦横比に応じた上部マージンを設定
    top_margin_ratio = 0.24 if aspect < 0.55 else 0.10
    table_h = int(round(out_w * aspect))
    top_pad = int(round(table_h * top_margin_ratio))
    bot_pad = 45  # 最下部バンドの連鎖追跡で画面外クリップが起きないための下部余裕
    out_h = max(400, min(1650, table_h + top_pad + bot_pad))
    side_pad = 10

    dst_pts = np.array([
        [side_pad, top_pad],
        [out_w - 1 - side_pad, top_pad],
        [out_w - 1 - side_pad, out_h - 1 - bot_pad],
        [side_pad, out_h - 1 - bot_pad]
    ], dtype=np.float32)

    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped = cv2.warpPerspective(img, M, (out_w, out_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return warped, top_pad, table_h


def _track_chained_shifts(profs, start_idx, end_idx, seg_a, seg_b, limit_len, step_lim, ref_weight, prev_weight):
    """基準スライスから左右／上下へ連鎖スライス追跡を行い、各スライスの最適シフト量配列を返す。"""
    n = len(profs)
    shifts = [0] * n
    ref_mid = profs[start_idx][seg_a:seg_b]

    for direction in (1, -1):
        rng = range(start_idx + 1, end_idx) if direction == 1 else range(start_idx - 1, -1, -1)
        for idx in rng:
            prev_d = shifts[idx - direction]
            prev_seg = profs[idx - direction][max(0, seg_a + prev_d):min(limit_len, seg_b + prev_d)]
            best_d, best_sc = prev_d, -1e18
            for d in range(prev_d - step_lim, prev_d + step_lim + 1):
                if seg_a + d < 0 or seg_b + d > limit_len:
                    continue
                cand = profs[idx][seg_a + d:seg_b + d]
                sc = ref_weight * np.dot(ref_mid, cand)
                if len(prev_seg) == len(cand):
                    sc += prev_weight * np.dot(prev_seg, cand)
                if sc > best_sc:
                    best_sc, best_d = sc, d
            shifts[idx] = best_d
    return shifts


def _straighten_horizontal_lines(warped, top_pad, table_h):
    """Stage 2: Chained Slice Tracking による全6バンド横罫線の完全水平化。"""
    oh, ow = warped.shape[:2]
    w_gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    sy = np.abs(cv2.Sobel(w_gray, cv2.CV_32F, 0, 1, ksize=3))
    sx = np.abs(cv2.Sobel(w_gray, cv2.CV_32F, 1, 0, ksize=3))
    horiz_only = np.maximum(0.0, sy - 0.7 * sx)
    horiz_energy = cv2.GaussianBlur(horiz_only, (15, 5), 0)

    n_x = 32
    xs = np.linspace(int(ow * 0.05), ow - 12, n_x + 1, dtype=int)
    xc_list = [0.5 * (xs[i] + xs[i + 1]) for i in range(n_x)]
    mid_i = n_x // 2

    bands_y = [
        (max(5, top_pad - 20), top_pad + int(table_h * 0.14)),
        (top_pad + int(table_h * 0.12), top_pad + int(table_h * 0.30)),
        (top_pad + int(table_h * 0.26), top_pad + int(table_h * 0.48)),
        (top_pad + int(table_h * 0.44), top_pad + int(table_h * 0.64)),
        (top_pad + int(table_h * 0.60), top_pad + int(table_h * 0.84)),
        (top_pad + int(table_h * 0.78), top_pad + table_h + 5)
    ]
    step_lim = max(4, min(9, int(table_h * 0.012)))
    x_all = np.arange(ow, dtype=np.float32)

    band_dys = []
    band_cy = []
    profs = [horiz_energy[:, xs[i]:xs[i + 1]].mean(axis=1) for i in range(n_x)]
    for b_idx, (ya, yb) in enumerate(bands_y):
        cur_lim = step_lim if b_idx < 4 else max(step_lim, int(table_h * 0.018))
        ref_w = 0.4 if b_idx < 4 else 0.1
        dys = _track_chained_shifts(profs, mid_i, n_x, ya, yb, oh, cur_lim, ref_w, 1.0)
        poly = np.poly1d(np.polyfit(xc_list, dys, 4))
        band_dys.append(poly(x_all).astype(np.float32))
        band_cy.append(0.5 * (ya + yb))

    mx, my = np.meshgrid(np.arange(ow, dtype=np.float32), np.arange(oh, dtype=np.float32))
    anchors_y = np.array([0.0] + band_cy + [float(oh - 1)], dtype=np.float32)
    for x in range(ow):
        dy_vals = np.array([band_dys[0][x]] + [bd[x] for bd in band_dys] + [band_dys[-1][x]], dtype=np.float32)
        my[:, x] += np.interp(my[:, x], anchors_y, dy_vals).astype(np.float32)

    return cv2.remap(warped, mx, my, interpolation=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _straighten_vertical_lines(stage2_img, top_pad, table_h):
    """Stage 3: Chained Slice Tracking による4ゾーン全縦罫線の完全垂直化。"""
    oh, ow = stage2_img.shape[:2]
    s2_gray = cv2.cvtColor(stage2_img, cv2.COLOR_BGR2GRAY)
    sy2 = np.abs(cv2.Sobel(s2_gray, cv2.CV_32F, 0, 1, ksize=3))
    sx2 = np.abs(cv2.Sobel(s2_gray, cv2.CV_32F, 1, 0, ksize=3))
    vert_only = np.maximum(0.0, sx2 - 0.7 * sy2)
    vert_energy = cv2.GaussianBlur(vert_only, (5, 15), 0)

    n_y = 16
    ys = np.linspace(top_pad, top_pad + table_h, n_y + 1, dtype=int)
    yc_list = [0.5 * (ys[j] + ys[j + 1]) for j in range(n_y)]
    mid_j = 5

    x_zones = [
        (int(ow * 0.04), int(ow * 0.28)),
        (int(ow * 0.26), int(ow * 0.52)),
        (int(ow * 0.50), int(ow * 0.76)),
        (int(ow * 0.74), int(ow * 0.98))
    ]
    zone_cx = [0.5 * (xa + xb) for (xa, xb) in x_zones]
    y_all = np.arange(oh, dtype=np.float32)
    zone_dxs = []
    step_lim_x = 5
    profs_x = [vert_energy[ys[j]:ys[j + 1], :].mean(axis=0) for j in range(n_y)]

    for (xa, xb) in x_zones:
        dxs = _track_chained_shifts(profs_x, mid_j, n_y, xa, xb, ow, step_lim_x, 1.2, 0.6)
        poly_x = np.poly1d(np.polyfit(yc_list, dxs, 2))
        zone_dxs.append(poly_x(y_all).astype(np.float32))

    mx3, my3 = np.meshgrid(np.arange(ow, dtype=np.float32), np.arange(oh, dtype=np.float32))
    anchors_x = np.array([0.0] + zone_cx + [float(ow - 1)], dtype=np.float32)
    for y in range(oh):
        dx_vals = np.array([zone_dxs[0][y]] + [zd[y] for zd in zone_dxs] + [zone_dxs[-1][y]], dtype=np.float32)
        mx3[y, :] += np.interp(mx3[y, :], anchors_x, dx_vals).astype(np.float32)

    remapped_full = cv2.remap(stage2_img, mx3, my3, interpolation=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return remapped_full[:top_pad + table_h + 8, :]


def dewarp_table_image_with_status(image_bytes, api_key=None):
    """
    【Phase 1: 汎用2段階補正（壁紙ノイズ耐性・斜め撮影ホモグラフィ ＋ 内部たわみ補正）】
    Stage 1: 壁紙の凹凸や背景ノイズを除去して勤務表の格子ネットワーク外枠（凸包）のみを抽出し、
             4隅の厳密な3D射影変換（cv2.warpPerspective）で斜め撮影（±45°）や台形歪みを正面投影へ補正。
    Stage 2: 正面投影後に残る紙のアーチ状たわみを内部横罫線の相互相関で計測し、
             全横罫線・全縦罫線を水平・垂直の直線グリッドに整列させます。
    ※縦長表・横長表のアスペクト比を自動維持し、すでに補正済みの画像の二重補正を自動防止します。
    ※引数 api_key は既存呼び出し・テスト互換のため保持（内部では未使用）。
    戻り値: (processed_bytes, corrected_b64_or_none, status)
      status: "applied" | "already_dewarped" | "not_applied"
    """
    del api_key
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return image_bytes, None, "not_applied"

        orig_h, orig_w = img.shape[:2]
        best_hull, scale, area_ratio = _detect_table_outer_hull(img)
        if best_hull is None:
            return image_bytes, None, "not_applied"

        # 二重補正防止ガード: すでに表領域が画像全体の70%以上を占める横長補正済み画像ならそのまま返す
        if orig_w >= orig_h and area_ratio > 0.70:
            print(f"[DEWARP] Image already dewarped (area_ratio={area_ratio:.2f}), skipping double warp.")
            b64 = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("utf-8")
            return image_bytes, b64, "already_dewarped"

        warped, top_pad, table_h = _warp_table_perspective(img, best_hull, scale)
        stage2_img = _straighten_horizontal_lines(warped, top_pad, table_h)
        processed_img = _straighten_vertical_lines(stage2_img, top_pad, table_h)
        print(f"[DEWARP] Chained 3-Stage H+V Mesh Dewarping completed: {orig_w}x{orig_h} -> {processed_img.shape[1]}x{processed_img.shape[0]}")

        _, buf = cv2.imencode(".jpg", processed_img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        warped_bytes = buf.tobytes()
        warped_b64 = "data:image/jpeg;base64," + base64.b64encode(warped_bytes).decode("utf-8")
        return warped_bytes, warped_b64, "applied"
    except Exception as e:
        print("dewarp_table_image fallback:", e)
        return image_bytes, None, "not_applied"


def dewarp_table_image(image_bytes, api_key=None):
    """既存呼び出し互換ラッパー: (processed_bytes, corrected_b64_or_none) を返す"""
    processed_bytes, corrected_b64, _ = dewarp_table_image_with_status(image_bytes, api_key)
    return processed_bytes, corrected_b64


def detect_table_grid(image_bytes):
    """
    【Phase 2: 対象者の行帯および全日付列の縦区切り線の幾何学的決定】
    Phase 1 で水平・垂直化された勤務表画像から、OpenCVにより以下を1ピクセル精度で直接抽出します：
      - h_lines: 貫通する全横罫線のY座標リスト（文字の横画は除外）
      - grid_x:  1日目左端〜最終日右端までの全日付列の縦区切り線X座標リスト（n_cols + 1 本）
      - h_lines_norm / grid_x_norm: 0〜1000 正規化座標
    """
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return None

        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        bin_inv = cv2.adaptiveThreshold(
            cv2.GaussianBlur(gray, (3, 3), 0), 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 21, 10
        )

        # 1. 横罫線（幅 w//10 の貫通する水平線のみ抽出し、文字の横画を完全除外）
        horiz_mask = cv2.morphologyEx(bin_inv, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(30, w // 10), 1)))
        horiz_prof = horiz_mask[:, int(w * 0.08):int(w * 0.96)].mean(axis=1)
        min_row_gap = max(14, int(h * 0.018))
        h_lines = []
        for y in range(15, h - 4):
            if horiz_prof[y] > 45.0 and horiz_prof[y] == max(horiz_prof[max(0, y - min_row_gap // 2):min(h, y + min_row_gap // 2 + 1)]):
                if not h_lines or y - h_lines[-1] >= min_row_gap:
                    h_lines.append(int(y))

        table_top_y = h_lines[0] if h_lines else int(h * 0.1)

        # 2. 縦罫線（貫通縦線マスク + SobelXハイブリッド → マーカー塗りの薄い線も、文字の縦画排除も両立）
        vert_mask = cv2.morphologyEx(bin_inv, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(30, h // 9))))
        sy = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
        sx = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
        sx_only = np.maximum(0.0, sx - 0.6 * sy)

        y_end = min(h - 4, table_top_y + int((h - table_top_y) * 0.92))
        vp_mask = cv2.GaussianBlur(vert_mask[table_top_y:y_end, :].astype(np.float32), (5, 1), 0).mean(axis=0)
        vp_sobel = cv2.GaussianBlur(sx_only[table_top_y:y_end, :], (3, 1), 0).mean(axis=0)
        vert_prof = (vp_mask / max(float(vp_mask.max()), 1.0)) * 0.7 + (vp_sobel / max(float(vp_sobel.max()), 1.0)) * 0.3

        v_thresh = max(0.18, float(np.percentile(vert_prof, 62)))
        peaks = []
        for x in range(3, w - 2):
            if vert_prof[x] > v_thresh and vert_prof[x] == max(vert_prof[max(0, x - 12):min(w, x + 13)]):
                if not peaks or x - peaks[-1] >= 24:
                    peaks.append(int(x))

        if len(peaks) < 10:
            return None

        diffs = np.diff(peaks)
        valid_diffs = diffs[(diffs >= 26) & (diffs <= 48)]
        col_w = float(np.median(valid_diffs)) if len(valid_diffs) > 5 else 36.0

        # 氏名列左端（最初の間隔が他列より広い）を分離し、1日目の左罫線から開始
        start_idx = 0
        for i in range(len(peaks) - 1):
            if abs((peaks[i + 1] - peaks[i]) - col_w) <= col_w * 0.30:
                start_idx = i
                break
        grid_x = peaks[start_idx:]

        # 欠損した縦線（間隔が col_w * 1.6 以上）を局所ピークスナップ付きで線形補間
        filled_x = [grid_x[0]]
        for x_next in grid_x[1:]:
            base_x = filled_x[-1]
            gap = x_next - base_x
            if gap > col_w * 1.6:
                steps = int(round(gap / col_w))
                for s in range(1, steps):
                    ideal = int(round(base_x + gap * s / steps))
                    xa, xb = max(0, ideal - 6), min(w - 1, ideal + 6)
                    filled_x.append(int(xa + int(np.argmax(vert_prof[xa:xb + 1]))))
            filled_x.append(int(x_next))

        h_lines_norm = [int(round(y * 1000.0 / h)) for y in h_lines]
        grid_x_norm = [int(round(x * 1000.0 / w)) for x in filled_x]
        n_cols = len(filled_x) - 1
        print(f"[GRID] Detected {n_cols} date columns (col_w={col_w:.1f}px, x={filled_x[0]}..{filled_x[-1]}), {len(h_lines)} horizontal lines")

        return {
            "h_lines": h_lines,
            "grid_x": filled_x,
            "h_lines_norm": h_lines_norm,
            "grid_x_norm": grid_x_norm,
            "n_cols": n_cols,
            "col_w": col_w,
            "w": w,
            "h": h
        }
    except Exception as e:
        print("detect_table_grid fallback:", e)
        return None


def snap_row_band_to_grid(grid, ref_ymin, ref_ymax):
    """
    AIが返した対象者行のY帯 [ref_ymin, ref_ymax] (0〜1000正規化座標) の中心Yに最も一致する
    実在の横罫線ペア [y_top_norm, y_bottom_norm] へ厳密にスナップします。
    """
    if not grid or not grid.get("h_lines_norm") or len(grid["h_lines_norm"]) < 2:
        return ref_ymin, ref_ymax
    if ref_ymin is None or ref_ymax is None or ref_ymax <= ref_ymin:
        return ref_ymin, ref_ymax

    cy = 0.5 * (ref_ymin + ref_ymax)
    h_norm = grid["h_lines_norm"]
    for i in range(len(h_norm) - 1):
        if h_norm[i] <= cy <= h_norm[i + 1]:
            return h_norm[i], h_norm[i + 1]
    return ref_ymin, ref_ymax


def build_labeled_name_column_image(img, grid):
    """
    【Phase 2】氏名列の各横罫線行に 'ROW 0', 'ROW 1', ... の赤い行番号ラベルを印字した
    2倍拡大画像を生成します。座標推測ではなく行番号選択にすることで行ズレを0%にします。
    """
    h, w = img.shape[:2]
    h_lines = grid["h_lines"]
    grid_x = grid["grid_x"]
    if len(h_lines) < 3 or len(grid_x) < 2:
        return None, 0

    name_w = min(w, grid_x[0] + 8)
    y_top = h_lines[0]
    y_bot = min(h, h_lines[-1])
    name_crop = img[y_top:y_bot, :name_w].copy()

    scale_n = 2.0
    name_big = cv2.resize(
        name_crop,
        (max(1, int(name_w * scale_n)), max(1, int((y_bot - y_top) * scale_n))),
        interpolation=cv2.INTER_CUBIC
    )
    label_w = 120
    canvas = np.full((name_big.shape[0], name_big.shape[1] + label_w, 3), 255, dtype=np.uint8)
    canvas[:, label_w:] = name_big

    n_rows = len(h_lines) - 1
    for idx in range(n_rows):
        ry1 = int((h_lines[idx] - y_top) * scale_n)
        ry2 = int((h_lines[idx + 1] - y_top) * scale_n)
        cv2.line(canvas, (0, ry1), (canvas.shape[1], ry1), (0, 0, 220), 2)
        cy = (ry1 + ry2) // 2 + 8
        cv2.putText(canvas, f"ROW {idx}", (8, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (0, 0, 220), 2, cv2.LINE_AA)

    # 下部の長いメモ欄を省き、スタッフ一覧が収まる高さに制限（最大1400px）
    canvas = canvas[:min(canvas.shape[0], 1400), :]
    _, buf = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return buf.tobytes(), n_rows


def build_labeled_ocr_strip(img, grid, target_row_idx):
    """
    【Phase 4】タイトル帯（年月）＋ [日付行・曜日行・対象者行] の3行だけを2段に折り返し、
    各マス目の真上に列番号 1..N と赤い仕切り線を大きく印字した専用OCR画像を生成します。
    """
    h_lines = grid["h_lines"]
    grid_x = grid["grid_x"]
    n_cols = len(grid_x) - 1
    if target_row_idx < 2 or target_row_idx >= len(h_lines) - 1 or n_cols < 10:
        return None

    title_strip = img[:h_lines[0], :min(img.shape[1], 800)].copy()

    r_date = img[h_lines[0]:h_lines[1], :]
    r_dow = img[h_lines[1]:h_lines[2], :]
    r_tgt = img[h_lines[target_row_idx]:h_lines[target_row_idx + 1], :]
    combined = np.vstack([r_date, r_dow, r_tgt])

    mid = (n_cols + 1) // 2
    scale_s = 2.2
    strips = []
    for seg_start, seg_end in [(0, mid), (mid, n_cols)]:
        x1 = grid_x[seg_start]
        x2 = grid_x[seg_end]
        sub = combined[:, x1:x2]
        sub_big = cv2.resize(
            sub,
            (max(1, int((x2 - x1) * scale_s)), max(1, int(sub.shape[0] * scale_s))),
            interpolation=cv2.INTER_CUBIC
        )
        bar_h = 46
        panel = np.full((bar_h + sub_big.shape[0] + 10, sub_big.shape[1] + 20, 3), 255, dtype=np.uint8)
        panel[bar_h:bar_h + sub_big.shape[0], 10:10 + sub_big.shape[1]] = sub_big
        for k in range(seg_start, seg_end):
            lx = 10 + int((grid_x[k] - x1) * scale_s)
            rx = 10 + int((grid_x[k + 1] - x1) * scale_s)
            cv2.line(panel, (lx, 0), (lx, bar_h + sub_big.shape[0]), (0, 0, 220), 2)
            cv2.line(panel, (rx, 0), (rx, bar_h + sub_big.shape[0]), (0, 0, 220), 2)
            cx = (lx + rx) // 2 - (16 if k + 1 >= 10 else 8)
            cv2.putText(panel, str(k + 1), (cx, 33), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 0, 220), 2, cv2.LINE_AA)
        strips.append(panel)

    max_w = max(title_strip.shape[1], strips[0].shape[1], strips[1].shape[1])

    def pad_w(im, mw):
        if im.shape[1] >= mw:
            return im
        out = np.full((im.shape[0], mw, 3), 255, dtype=np.uint8)
        out[:, :im.shape[1]] = im
        return out

    gap = np.full((18, max_w, 3), 240, dtype=np.uint8)
    final_strip = np.vstack([pad_w(title_strip, max_w), gap, pad_w(strips[0], max_w), gap, pad_w(strips[1], max_w)])
    _, buf = cv2.imencode(".jpg", final_strip, [cv2.IMWRITE_JPEG_QUALITY, 94])
    return buf.tobytes()


def detect_event_row_band(grid, img=None):
    """
    【行事予定行の幾何学特定】
    detect_table_grid が抽出した h_lines から、勤務表の下部にある
    「縦書きで縦長に確保された行事予定セル行」の (y_top, y_bottom) を特定します。
    下部に複数の縦長行（行事予定行・空欄行・栄養士行など）がある場合は、
    文字密度が最も高い縦長行（画像未指定時は最上位の縦長行）を選択します。
    該当する縦長行が存在しない場合は None を返し、スタッフ行を誤認しません。
    """
    if not grid:
        return None
    h_lines = grid.get("h_lines") or []
    img_h = int(grid.get("h") or 0)
    if len(h_lines) < 4 or img_h <= 0:
        return None

    gaps = [h_lines[i + 1] - h_lines[i] for i in range(len(h_lines) - 1)]
    if not gaps:
        return None
    med_h = float(np.median(gaps))
    # 2行結合セル（通常行の約2倍）を誤認せず、横長表の行事欄（高さ約70px）も確実に拾えるよう相対倍率2.5倍・下限36pxとする
    min_event_h = max(med_h * 2.5, 36.0)

    tall_bands = []
    for idx in range(2, len(gaps)):
        if gaps[idx] >= min_event_h:
            tall_bands.append((int(h_lines[idx]), int(h_lines[idx + 1])))

    # 最下端の罫線が画像端ギリギリで h_lines に含まれなかった場合の保険
    tail_h = (img_h - 2) - h_lines[-1]
    if not tall_bands and tail_h >= min_event_h:
        tall_bands.append((int(h_lines[-1]), int(img_h - 2)))

    if not tall_bands:
        return None
    if len(tall_bands) == 1 or img is None:
        return tall_bands[0]

    # 複数の縦長行がある場合、日付列領域内で文字（非罫線インク）が最も多い行を選択
    grid_x = grid.get("grid_x") or []
    x_start = int(grid_x[0]) if len(grid_x) >= 2 else 0
    x_end = int(grid_x[-1]) if len(grid_x) >= 2 else img.shape[1]
    best_band = tall_bands[0]
    best_score = -1.0

    for (y1, y2) in tall_bands:
        pad_y = min(10, max(2, (y2 - y1) // 12))
        roi = img[y1 + pad_y:max(y1 + pad_y + 1, y2 - pad_y), x_start:x_end]
        if roi.size == 0:
            continue
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
        bin_inv = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 21, 14
        )
        # 貫通する縦罫線を除去して文字インクのみをカウント
        v_len = max(15, bin_inv.shape[0] // 2)
        v_lines = cv2.morphologyEx(bin_inv, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_len)))
        text_only = cv2.subtract(bin_inv, cv2.dilate(v_lines, np.ones((3, 5), np.uint8)))
        score = float(np.count_nonzero(text_only))
        if score > best_score:
            best_score = score
            best_band = (y1, y2)

    return best_band


def detect_active_event_columns(img, grid, band=None):
    """
    【行事予定が存在する列のOpenCV事前抽出】
    行事予定行 (y1..y2) の全日付列 (0..n_cols-1) を走査し、
    罫線および網掛け背景を除いた文字インク比率が閾値 (0.020) 以上の列インデックス一覧を返します。
    空欄列（通常36列中25列以上）を事前に除外することで、OCR画像を約1/4に軽量化します。
    """
    if img is None or not grid:
        return []
    if band is None:
        band = detect_event_row_band(grid, img=img)
    if not band:
        return []

    y1, y2 = band
    grid_x = grid.get("grid_x") or []
    n_cols = len(grid_x) - 1
    if n_cols < 1 or y2 - y1 < 20:
        return []

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    active_cols = []
    for k in range(n_cols):
        x1, x2 = int(grid_x[k]), int(grid_x[k + 1])
        cell = gray[y1 + 8:max(y1 + 9, y2 - 8), x1 + 4:max(x1 + 5, x2 - 4)]
        if cell.size == 0:
            continue
        b = cv2.adaptiveThreshold(
            cv2.GaussianBlur(cell, (3, 3), 0),
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            15,
            11
        )
        ratio = float(np.count_nonzero(b)) / float(b.size)
        if ratio >= 0.020:
            active_cols.append(k)
    return active_cols


def detect_active_event_spans(img, grid, band=None):
    """
    【結合セル対応: 行事予定スパン (start_col, end_col) の抽出】
    文字が存在する列を抽出したうえで、行事予定行の内部境界に貫通する縦罫線が存在しない
    隣接列（2日結合・3日結合セル等）を1つのスパン (start_col, end_col) (0-based inclusive) に統合します。
    """
    if img is None or not grid:
        return []
    if band is None:
        band = detect_event_row_band(grid, img=img)
    if not band:
        return []

    active_cols = detect_active_event_columns(img, grid, band=band)
    if not active_cols:
        return []

    y1, y2 = band
    grid_x = grid.get("grid_x") or []
    n_cols = len(grid_x) - 1
    if n_cols < 2:
        return [(k, k) for k in active_cols]

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    img_w = gray.shape[1]
    pad_y = min(8, max(2, (y2 - y1) // 10))
    ya, yb = y1 + pad_y, max(y1 + pad_y + 1, y2 - pad_y)

    # 内部境界 b (1..n_cols-1: 列 b-1 と列 b の間) に貫通する縦罫線があるかを判定
    has_border = {}
    for b in range(1, n_cols):
        x = int(grid_x[b])
        strip = gray[ya:yb, max(0, x - 2):min(img_w, x + 3)]
        if strip.size == 0:
            has_border[b] = True
            continue
        left_bg = float(np.median(gray[ya:yb, max(0, x - 8):max(1, x - 4)]))
        right_bg = float(np.median(gray[ya:yb, min(img_w - 1, x + 4):min(img_w, x + 8)]))
        bg = 0.5 * (left_bg + right_bg)
        row_min = strip.min(axis=1).astype(float)
        dark_ratio = float(np.mean((bg - row_min) > 20.0))
        has_border[b] = (dark_ratio >= 0.72)

    # 縦罫線が1本も描かれていない合成テスト画像などでは結合を行わない安全ガード
    if not any(has_border.values()):
        return [(k, k) for k in active_cols]

    # 各 active 列を、縦罫線が途切れている左右の結合セル範囲まで拡張して統合（最大4列）
    spans = []
    for k in active_cols:
        s, e = k, k
        while s > 0 and not has_border.get(s, True) and (e - s + 1) < 4:
            s -= 1
        while e < n_cols - 1 and not has_border.get(e + 1, True) and (e - s + 1) < 4:
            e += 1
        if spans and s <= spans[-1][1] + 0:
            spans[-1] = (spans[-1][0], max(spans[-1][1], e))
        else:
            spans.append((s, e))
    return spans


def build_labeled_event_strip(img, grid):
    """
    【行事予定専用OCRストリップ生成】
    シフト記号OCR（build_labeled_ocr_strip）とは完全に独立して、
    下部の縦長「行事予定欄」のうち文字が存在する列（結合セルはワイドカード化）だけを
    等倍拡大カードとして1段に並べ、各カードの真上に赤い列番号（単一: '7' / 結合: '4-5'）を印字します。
    """
    if img is None or not grid:
        return None
    band = detect_event_row_band(grid, img=img)
    if not band:
        return None

    y1, y2 = band
    grid_x = grid.get("grid_x") or []
    n_cols = len(grid_x) - 1
    if n_cols < 10 or y2 - y1 < 20:
        return None

    active_spans = detect_active_event_spans(img, grid, band=band)
    if active_spans:
        # 縦長表は1.8倍、横長表など高さが低い行事欄は最大3.0倍に自動拡大して縦書き文字を鮮明化
        scale_s = max(1.8, min(3.0, 260.0 / float(max(1, y2 - y1))))
        bar_h = 44
        cards = []
        for (s_col, e_col) in active_spans:
            x1, x2 = int(grid_x[s_col]), int(grid_x[e_col + 1])
            sub = img[y1:y2, x1:x2]
            cw = max(44, int(round((x2 - x1) * scale_s)))
            ch = max(1, int(round((y2 - y1) * scale_s)))
            sub_big = cv2.resize(sub, (cw, ch), interpolation=cv2.INTER_CUBIC)
            card = np.full((bar_h + ch + 8, cw + 8, 3), 255, dtype=np.uint8)
            card[bar_h:bar_h + ch, 4:4 + cw] = sub_big
            cv2.rectangle(card, (2, 2), (cw + 5, bar_h + ch + 5), (0, 0, 220), 2)
            cv2.line(card, (2, bar_h), (cw + 5, bar_h), (0, 0, 220), 2)
            label = str(s_col + 1) if s_col == e_col else f"{s_col + 1}-{e_col + 1}"
            (tw, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.85, 2)
            tx = max(4, (cw + 8 - tw) // 2)
            cv2.putText(card, label, (tx, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 0, 220), 2, cv2.LINE_AA)
            cards.append(card)

        panel = np.hstack(cards)
        if panel.shape[1] < 320:
            padded = np.full((panel.shape[0], 320, 3), 255, dtype=np.uint8)
            padded[:, :panel.shape[1]] = panel
            panel = padded
        _, buf = cv2.imencode(".jpg", panel, [cv2.IMWRITE_JPEG_QUALITY, 88])
        return buf.tobytes()

    row_crop = img[y1:y2, :]
    row_h = max(1, y2 - y1)
    # 縦書き文字の縦横比を保ったまま拡大（最大高さ320pxに収めて軽量・高速化）
    scale_s = max(1.3, min(1.7, 320.0 / float(row_h)))
    mid = (n_cols + 1) // 2
    strips = []

    for seg_start, seg_end in [(0, mid), (mid, n_cols)]:
        x1 = grid_x[seg_start]
        x2 = grid_x[seg_end]
        sub = row_crop[:, x1:x2]
        sub_big = cv2.resize(
            sub,
            (max(1, int(round((x2 - x1) * scale_s))), max(1, int(round(sub.shape[0] * scale_s)))),
            interpolation=cv2.INTER_CUBIC
        )
        bar_h = 46
        panel = np.full((bar_h + sub_big.shape[0] + 10, sub_big.shape[1] + 20, 3), 255, dtype=np.uint8)
        panel[bar_h:bar_h + sub_big.shape[0], 10:10 + sub_big.shape[1]] = sub_big
        for k in range(seg_start, seg_end):
            lx = 10 + int(round((grid_x[k] - x1) * scale_s))
            rx = 10 + int(round((grid_x[k + 1] - x1) * scale_s))
            cv2.line(panel, (lx, 0), (lx, bar_h + sub_big.shape[0]), (0, 0, 220), 2)
            cv2.line(panel, (rx, 0), (rx, bar_h + sub_big.shape[0]), (0, 0, 220), 2)
            cx = (lx + rx) // 2 - (16 if k + 1 >= 10 else 8)
            cv2.putText(panel, str(k + 1), (cx, 33), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 0, 220), 2, cv2.LINE_AA)
        strips.append(panel)

    max_w = max(strips[0].shape[1], strips[1].shape[1])

    def pad_w(im, mw):
        if im.shape[1] >= mw:
            return im
        out = np.full((im.shape[0], mw, 3), 255, dtype=np.uint8)
        out[:, :im.shape[1]] = im
        return out

    gap = np.full((18, max_w, 3), 240, dtype=np.uint8)
    final_strip = np.vstack([pad_w(strips[0], max_w), gap, pad_w(strips[1], max_w)])
    _, buf = cv2.imencode(".jpg", final_strip, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return buf.tobytes()


def optimize_image_for_ai(image_bytes):
    """
    Gemini Vision APIのパッチ分割によるテーブル列ズレを防ぐため、
    画像幅を2400pxに自動最適化する（macOS標準のsipsを使用）。
    正規化座標 [ymin, xmin, ymax, xmax] はアスペクト比維持のため完全一致します。
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f_in, \
             tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f_out:
            in_path = f_in.name
            out_path = f_out.name
            f_in.write(image_bytes)
            f_in.flush()
        
        cmd = ["sips", "--resampleWidth", "2400", in_path, "--out", out_path]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        with open(out_path, "rb") as f:
            resized_bytes = f.read()
        return resized_bytes
    except Exception:
        return image_bytes
    finally:
        if 'in_path' in locals() and os.path.exists(in_path):
            os.remove(in_path)
        if 'out_path' in locals() and os.path.exists(out_path):
            os.remove(out_path)
