"""外部ライブラリ不要のローカルQRコード（ISO/IEC 18004, Byteモード, EC Level M, V1〜V6）SVG生成器。"""

from xml.sax.saxutils import escape as _xml_escape

# Version 1〜6, Error Correction Level M の仕様テーブル
# (version, size, data_codewords, ec_per_block, num_blocks, alignment_centers)
_QR_SPECS_M = (
    (1, 21, 16, 10, 1, ()),
    (2, 25, 28, 16, 1, (6, 18)),
    (3, 29, 44, 26, 1, (6, 22)),
    (4, 33, 64, 18, 2, (6, 26)),
    (5, 37, 86, 24, 2, (6, 30)),
    (6, 41, 108, 16, 4, (6, 34)),
)

# GF(256) 指数・対数テーブル（原始多項式 x^8 + x^4 + x^3 + x^2 + 1 = 0x11D）
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_x = 1
for _i in range(255):
    _GF_EXP[_i] = _x
    _GF_LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _GF_EXP[_i] = _GF_EXP[_i - 255]


def _gf_mul(a, b):
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_generator_poly(degree):
    poly = [1]
    for i in range(degree):
        next_poly = [0] * (len(poly) + 1)
        factor = _GF_EXP[i]
        for j, coeff in enumerate(poly):
            next_poly[j] ^= coeff
            next_poly[j + 1] ^= _gf_mul(coeff, factor)
        poly = next_poly
    return poly


def _rs_compute_ec(data_bytes, ec_count):
    gen = _rs_generator_poly(ec_count)
    rem = list(data_bytes) + [0] * ec_count
    for i in range(len(data_bytes)):
        factor = rem[i]
        if factor != 0:
            for j in range(1, len(gen)):
                rem[i + j] ^= _gf_mul(gen[j], factor)
    return rem[len(data_bytes):]


def _select_spec(byte_len):
    for spec in _QR_SPECS_M:
        # Byteモードヘッダ(4bit) + 文字数(8bit) = 12bit + 終端4bit = 最大2バイト消費
        if byte_len <= spec[2] - 2:
            return spec
    raise ValueError(f"QRコードのデータ長が上限を超えています（{byte_len} bytes, 最大 106 bytes）")


def _encode_data_codewords(payload_bytes, data_capacity):
    bits = []

    def append_bits(val, length):
        for shift in range(length - 1, -1, -1):
            bits.append((val >> shift) & 1)

    # Byte モード指示子 (0100) + 8bit 長さ (Version 1〜9)
    append_bits(0b0100, 4)
    append_bits(len(payload_bytes), 8)
    for b in payload_bytes:
        append_bits(b, 8)

    cap_bits = data_capacity * 8
    # 終端パターン（最大4bit）
    term_len = min(4, cap_bits - len(bits))
    append_bits(0, term_len)
    # バイト境界まで0埋め
    if len(bits) % 8 != 0:
        append_bits(0, 8 - (len(bits) % 8))

    codewords = []
    for i in range(0, len(bits), 8):
        val = 0
        for b in bits[i:i + 8]:
            val = (val << 1) | b
        codewords.append(val)

    # パディングコード語 (0xEC, 0x11 交互)
    pad_idx = 0
    pad_bytes = (0xEC, 0x11)
    while len(codewords) < data_capacity:
        codewords.append(pad_bytes[pad_idx % 2])
        pad_idx += 1

    return codewords


def _interleave_blocks(data_cw, ec_per_block, num_blocks):
    block_size = len(data_cw) // num_blocks
    data_blocks = []
    ec_blocks = []
    for b in range(num_blocks):
        chunk = data_cw[b * block_size:(b + 1) * block_size]
        data_blocks.append(chunk)
        ec_blocks.append(_rs_compute_ec(chunk, ec_per_block))

    result = []
    for i in range(block_size):
        for blk in data_blocks:
            result.append(blk[i])
    for i in range(ec_per_block):
        for blk in ec_blocks:
            result.append(blk[i])
    return result


def _place_function_patterns(size, alignment_centers):
    matrix = [[None] * size for _ in range(size)]
    is_func = [[False] * size for _ in range(size)]

    def set_func(r, c, val):
        if 0 <= r < size and 0 <= c < size:
            matrix[r][c] = bool(val)
            is_func[r][c] = True

    # ファインダパターン（左上・右上・左下）＋セパレータ
    for top, left in ((0, 0), (0, size - 7), (size - 7, 0)):
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = top + dr, left + dc
                if 0 <= r < size and 0 <= c < size:
                    in_outer = 0 <= dr <= 6 and 0 <= dc <= 6
                    on_border = dr in (0, 6) or dc in (0, 6)
                    in_center = 2 <= dr <= 4 and 2 <= dc <= 4
                    set_func(r, c, in_outer and (on_border or in_center))

    # タイミングパターン
    for i in range(8, size - 8):
        val = (i % 2 == 0)
        set_func(6, i, val)
        set_func(i, 6, val)

    # アライメントパターン
    for r_c in alignment_centers:
        for c_c in alignment_centers:
            if is_func[r_c][c_c]:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    val = max(abs(dr), abs(dc)) != 1
                    set_func(r_c + dr, c_c + dc, val)

    # フォーマット情報領域を予約（後で書き込む）
    for i in range(9):
        if i != 6:
            set_func(8, i, False)
            set_func(i, 8, False)
    for i in range(8):
        set_func(8, size - 1 - i, False)
    for i in range(7):
        set_func(size - 1 - i, 8, False)
    # 固定ダークモジュール
    set_func(size - 8, 8, True)

    return matrix, is_func


def _place_data_bits(matrix, is_func, codewords):
    size = len(matrix)
    bits = []
    for cw in codewords:
        for shift in range(7, -1, -1):
            bits.append((cw >> shift) & 1)

    bit_idx = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for dc in (0, -1):
                c = col + dc
                if not is_func[row][c]:
                    bit = bits[bit_idx] if bit_idx < len(bits) else 0
                    matrix[row][c] = bool(bit)
                    bit_idx += 1
        col -= 2
        upward = not upward


def _format_bits(ec_level_bits, mask_id):
    data = (ec_level_bits << 3) | mask_id
    rem = data << 10
    gen = 0b10100110111
    for i in range(14, 9, -1):
        if rem & (1 << i):
            rem ^= gen << (i - 10)
    return ((data << 10) | rem) ^ 0b101010000010010


def _apply_format_info(matrix, mask_id):
    size = len(matrix)
    # EC Level M = 0b00
    fmt = _format_bits(0b00, mask_id)
    bits = [(fmt >> i) & 1 for i in range(15)]

    # 左上周り（LSB=0 は (8,0) からではなく規格順：bit14が(8,0), bit0が(0,8)）
    coords1 = (
        (8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
        (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8),
    )
    for idx, (r, c) in enumerate(coords1):
        matrix[r][c] = bool(bits[14 - idx])

    # 左下（bit14〜bit8）・右上（bit7〜bit0）
    for i in range(7):
        matrix[size - 1 - i][8] = bool(bits[14 - i])
    for i in range(8):
        matrix[8][size - 8 + i] = bool(bits[7 - i])
    matrix[size - 8][8] = True


def _mask_condition(mask_id, r, c):
    if mask_id == 0:
        return (r + c) % 2 == 0
    if mask_id == 1:
        return r % 2 == 0
    if mask_id == 2:
        return c % 3 == 0
    if mask_id == 3:
        return (r + c) % 3 == 0
    if mask_id == 4:
        return (r // 2 + c // 3) % 2 == 0
    if mask_id == 5:
        return ((r * c) % 2 + (r * c) % 3) == 0
    if mask_id == 6:
        return (((r * c) % 2 + (r * c) % 3) % 2) == 0
    return (((r + c) % 2 + (r * c) % 3) % 2) == 0


def _penalty_score(matrix):
    size = len(matrix)
    score = 0

    # ルール1: 同色5連続以上
    for r in range(size):
        run_len = 1
        for c in range(1, size):
            if matrix[r][c] == matrix[r][c - 1]:
                run_len += 1
            else:
                if run_len >= 5:
                    score += 3 + (run_len - 5)
                run_len = 1
        if run_len >= 5:
            score += 3 + (run_len - 5)

    for c in range(size):
        run_len = 1
        for r in range(1, size):
            if matrix[r][c] == matrix[r - 1][c]:
                run_len += 1
            else:
                if run_len >= 5:
                    score += 3 + (run_len - 5)
                run_len = 1
        if run_len >= 5:
            score += 3 + (run_len - 5)

    # ルール2: 2x2 同色ブロック
    for r in range(size - 1):
        for c in range(size - 1):
            v = matrix[r][c]
            if v == matrix[r][c + 1] == matrix[r + 1][c] == matrix[r + 1][c + 1]:
                score += 3

    # ルール4: 暗モジュール比率の偏り
    dark = sum(1 for row in matrix for cell in row if cell)
    ratio = abs((dark * 100 // (size * size)) - 50) // 5
    score += ratio * 10
    return score


def encode_qr_matrix(text):
    """文字列を UTF-8 Byte モードの QR コード 2次元 bool 配列に変換する。"""
    if not isinstance(text, str) or not text:
        raise ValueError("QRコードの対象文字列が空です")
    payload = text.encode("utf-8")
    _version, size, data_cap, ec_per_block, num_blocks, align_centers = _select_spec(len(payload))
    data_cw = _encode_data_codewords(payload, data_cap)
    full_cw = _interleave_blocks(data_cw, ec_per_block, num_blocks)

    base_matrix, is_func = _place_function_patterns(size, align_centers)
    _place_data_bits(base_matrix, is_func, full_cw)

    best_matrix = None
    best_score = None
    for mask_id in range(8):
        cand = [row[:] for row in base_matrix]
        for r in range(size):
            for c in range(size):
                if not is_func[r][c] and _mask_condition(mask_id, r, c):
                    cand[r][c] = not cand[r][c]
        _apply_format_info(cand, mask_id)
        sc = _penalty_score(cand)
        if best_score is None or sc < best_score:
            best_score = sc
            best_matrix = cand

    return best_matrix


def render_qr_svg(text, border=4, size=220):
    """文字列からローカル完結の QR コード SVG 文字列を生成する。"""
    matrix = encode_qr_matrix(text)
    dim = len(matrix) + border * 2
    path_parts = []
    for r, row in enumerate(matrix):
        for c, cell in enumerate(row):
            if cell:
                path_parts.append(f"M{c + border},{r + border}h1v1h-1z")
    path_d = "".join(path_parts)
    label = _xml_escape(text)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {dim} {dim}" '
        f'width="{int(size)}" height="{int(size)}" role="img" aria-label="QRコード: {label}" '
        f'shape-rendering="crispEdges">'
        f'<rect width="100%" height="100%" fill="#ffffff"/>'
        f'<path d="{path_d}" fill="#000000"/>'
        f'</svg>'
    )
