import json
import os
import re
import shutil
import subprocess
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from tests.dom_harness import JS_LOAD_INDEX_SCRIPT_SNIPPET, load_index_html_with_assets

INDEX_HTML_PATH = os.path.join(PROJECT_ROOT, "index.html")

NODE_TEST_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
""" + JS_LOAD_INDEX_SCRIPT_SNIPPET + r"""
const htmlPath = process.argv[1];
const scriptCode = loadIndexScriptFromHtml(htmlPath);

class MockClassList {
  constructor(el) {
    this.el = el;
    this.set = new Set();
  }
  _syncFromString(str) {
    this.set = new Set((str || "").split(/\s+/).filter(Boolean));
  }
  add(...cls) {
    cls.forEach(c => { if (c) this.set.add(c); });
  }
  remove(...cls) {
    cls.forEach(c => this.set.delete(c));
  }
  toggle(c, force) {
    if (force === undefined) {
      if (this.set.has(c)) { this.set.delete(c); return false; }
      this.set.add(c); return true;
    }
    if (force) { this.set.add(c); return true; }
    this.set.delete(c); return false;
  }
  contains(c) {
    return this.set.has(c);
  }
  toString() {
    return Array.from(this.set).join(" ");
  }
}

class MockElement {
  constructor(tagName = "div", id = "") {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.dataset = {};
    this.style = {};
    this.children = [];
    this.parentNode = null;
    this.listeners = {};
    this.value = "";
    this.textContent = "";
    this._innerHTML = "";
    this.checked = false;
    this.disabled = false;
    this.title = "";
    this.clientWidth = 800;
    this.clientHeight = 440;
    this.naturalWidth = 1000;
    this.naturalHeight = 1000;
    this.complete = true;
    this.offsetHeight = 36;
    this.scrollTop = 0;
    this.scrollCalls = [];
    this.attributes = {};
    this.classList = new MockClassList(this);
    this._rect = { top: 0, left: 0, bottom: 440, right: 800, width: 800, height: 440 };
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getAttribute(name) {
    return this.attributes[name] ?? null;
  }

  get className() {
    return this.classList.toString();
  }
  set className(val) {
    this.classList._syncFromString(val);
  }

  get innerHTML() {
    return this._innerHTML;
  }
  set innerHTML(val) {
    this._innerHTML = val;
    if (val === "") {
      this.children = [];
    }
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  contains(target) {
    if (this === target) return true;
    return this.children.some(c => c.contains(target));
  }

  closest(selector) {
    let cur = this;
    while (cur) {
      if (selector.startsWith(".") && cur.classList.contains(selector.slice(1))) return cur;
      if (cur.tagName.toLowerCase() === selector.toLowerCase()) return cur;
      cur = cur.parentNode;
    }
    return null;
  }

  getBoundingClientRect() {
    return this._rect;
  }

  scrollTo(opts) {
    this.scrollCalls.push(opts);
    if (opts && typeof opts.top === "number") {
      this.scrollTop = opts.top;
    }
  }

  scrollIntoView() {}

  addEventListener(type, fn) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(fn);
  }

  dispatchEvent(type, eventObj = {}) {
    const evt = Object.assign({
      type,
      target: this,
      preventDefault() {},
      stopPropagation() {}
    }, eventObj);
    (this.listeners[type] || []).forEach(fn => fn(evt));
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  querySelectorAll(selector) {
    const results = [];
    const matchNode = (node) => {
      if (selector === ".cal-cell") return node.classList.contains("cal-cell");
      if (selector === ".cal-event-capsule") return node.classList.contains("cal-event-capsule");
      if (selector === ".legend-capsule") return node.classList.contains("legend-capsule");
      if (selector === "#shifts-tbody tr") return node.tagName === "TR" && node.parentNode && node.parentNode.id === "shifts-tbody";
      if (selector === "thead") return node.tagName === "THEAD";
      if (selector.startsWith(".")) return node.classList.contains(selector.slice(1));
      return false;
    };
    const walk = (node) => {
      for (const ch of node.children) {
        if (matchNode(ch)) results.push(ch);
        walk(ch);
      }
    };
    walk(this);
    return results;
  }
}

// 仮想タイマー制御（デバウンス検証用）
let nextTimerId = 1;
const activeTimers = new Map();
function mockSetTimeout(fn, delay = 0) {
  const id = nextTimerId++;
  activeTimers.set(id, { fn, delay });
  return id;
}
function mockClearTimeout(id) {
  activeTimers.delete(id);
}
function flushTimers() {
  const entries = Array.from(activeTimers.entries());
  activeTimers.clear();
  for (const [, t] of entries) {
    t.fn();
  }
}

// 必要DOMツリー構築
const elementsById = new Map();
const rootDoc = new MockElement("body", "root-body");

function ensureElement(id, tag = "div") {
  if (!elementsById.has(id)) {
    const el = new MockElement(tag, id);
    elementsById.set(id, el);
    rootDoc.appendChild(el);
  }
  return elementsById.get(id);
}

// テーブルフレーム構造を構築（scrollTableRowIntoView 検証用）
const tableFrame = new MockElement("div");
tableFrame.classList.add("table-frame");
tableFrame._rect = { top: 100, left: 0, bottom: 420, right: 800, width: 800, height: 320 };
const tableEl = new MockElement("table");
const theadEl = new MockElement("thead");
theadEl.offsetHeight = 32;
const shiftsTbody = new MockElement("tbody", "shifts-tbody");
elementsById.set("shifts-tbody", shiftsTbody);
tableEl.appendChild(theadEl);
tableEl.appendChild(shiftsTbody);
tableFrame.appendChild(tableEl);
rootDoc.appendChild(tableFrame);

const calendarBody = ensureElement("calendar-body", "div");
const viewerWrapper = ensureElement("viewer-wrapper", "div");
const viewerCanvas = ensureElement("viewer-canvas", "div");
viewerCanvas._rect = { top: 0, left: 0, bottom: 440, right: 800, width: 800, height: 440 };
const viewerStage = ensureElement("viewer-stage", "div");
const compareImg = ensureElement("compare-image", "img");
compareImg.naturalWidth = 1000;
compareImg.naturalHeight = 1000;
compareImg.complete = true;
const viewerHighlightBox = ensureElement("viewer-highlight-box", "div");
viewerStage.appendChild(compareImg);
viewerStage.appendChild(viewerHighlightBox);
viewerCanvas.appendChild(viewerStage);
viewerWrapper.appendChild(viewerCanvas);

const windowListeners = {};
const mockWindow = {
  addEventListener(type, fn) {
    if (!windowListeners[type]) windowListeners[type] = [];
    windowListeners[type].push(fn);
  },
  dispatchEvent(type, evt = {}) {
    (windowListeners[type] || []).forEach(fn => fn(evt));
  },
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  localStorage: { getItem: () => null, setItem() {} },
  navigator: { clipboard: { writeText: async () => {} }, sendBeacon: () => true },
  setTimeout: mockSetTimeout,
  clearTimeout: mockClearTimeout,
  location: { href: "http://localhost:8765/", origin: "http://localhost:8765" },
  confirm: () => true
};

const mockDocument = {
  documentElement: new MockElement("html"),
  getElementById(id) {
    return ensureElement(id);
  },
  createElement(tag) {
    return new MockElement(tag);
  },
  querySelector(sel) {
    return rootDoc.querySelector(sel);
  },
  querySelectorAll(sel) {
    return rootDoc.querySelectorAll(sel);
  },
  addEventListener() {}
};

const sandbox = {
  window: mockWindow,
  document: mockDocument,
  localStorage: mockWindow.localStorage,
  navigator: mockWindow.navigator,
  setTimeout: mockSetTimeout,
  clearTimeout: mockClearTimeout,
  setInterval: () => 0,
  clearInterval: () => {},
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  console,
  Math,
  Date,
  Array,
  Object,
  JSON,
  URL,
  Blob: class {},
  FileReader: class {},
  Promise
};

// index.html の実スクリプトをそのまま読み込み実行
vm.runInNewContext(scriptCode, sandbox, { filename: "index.html" });
// 初期ロード時の非同期タイマーをクリア
activeTimers.clear();

// テスト用のシフトデータ（box_2d あり 3件 + box_2d なし 1件）
const sampleShifts = [
  { date: "2026-11-01", day_of_week: "日", type: "早A", status: "work", start_time: "06:00", end_time: "15:00", summary: "[早A] (06:00〜15:00)", box_2d: [100, 100, 200, 200] },
  { date: "2026-11-02", day_of_week: "月", type: "早B", status: "work", start_time: "06:30", end_time: "15:30", summary: "[早B] (06:30〜15:30)", box_2d: [100, 250, 200, 350] },
  { date: "2026-11-03", day_of_week: "火", type: "休", status: "holiday", start_time: null, end_time: null, summary: "休み", box_2d: [100, 400, 200, 500] },
  { date: "2026-11-04", day_of_week: "水", type: "有給", status: "paid_leave", start_time: null, end_time: null, summary: "有給休暇", box_2d: null }
];

sandbox.renderResult({ target_name: "皿田", shifts: sampleShifts });
// renderResult 内で予約される fitViewerToScreen タイマーを消化
flushTimers();

const calCells = calendarBody.querySelectorAll(".cal-cell").filter(c => !c.classList.contains("empty"));
const tableRows = shiftsTbody.querySelectorAll("#shifts-tbody tr");

// 行の表示位置（idx=1 がスクロール枠外の下にある状態を模擬）
tableRows[0]._rect = { top: 140, bottom: 180 };
tableRows[1]._rect = { top: 480, bottom: 520 }; // visibleBottom(420)より下
tableRows[2]._rect = { top: 520, bottom: 560 };
tableRows[3]._rect = { top: 560, bottom: 600 };

function assert(cond, msg) {
  if (!cond) throw new Error("ASSERTION FAILED: " + msg);
}

function getSelectedCalendarIndices() {
  return calCells.filter(c => c.classList.contains("is-selected")).map(c => Number(c.dataset.idx));
}
function getSelectedTableIndices() {
  return tableRows.filter(r => r.classList.contains("is-selected")).map(r => Number(r.dataset.idx));
}

const results = [];

// 1. カレンダーの日付セル(idx=1)をクリック → 3要素連動＋テーブル枠内スクロール
tableFrame.scrollCalls = [];
calCells[1].dispatchEvent("click");
assert(JSON.stringify(getSelectedCalendarIndices()) === "[1]", "カレンダークリックでカレンダーidx=1が選択されること");
assert(JSON.stringify(getSelectedTableIndices()) === "[1]", "カレンダークリックでテーブルidx=1が連動選択されること");
assert(tableFrame.scrollCalls.length === 1, "枠外のテーブル行へ .table-frame 内で自動スクロールされること");
assert(viewerHighlightBox.style.display === "block", "カレンダークリックで元画像ハイライト枠が表示されること");
assert(viewerHighlightBox.style.left === "250px" && viewerHighlightBox.style.top === "100px", "元画像ハイライト枠の座標がidx=1のbox_2dと一致すること");
results.push("case1_calendar_click_sync:OK");

// 2. テーブル行(idx=2)にカーソルを合わせる(mouseenter) → 即座にカレンダー＆テーブル連動、スクロールなし、デバウンス後に画像連動
tableFrame.scrollCalls = [];
tableRows[2].dispatchEvent("mouseenter");
assert(JSON.stringify(getSelectedCalendarIndices()) === "[2]", "テーブルmouseenterで即座にカレンダーidx=2が選択されること");
assert(JSON.stringify(getSelectedTableIndices()) === "[2]", "テーブルmouseenterで即座にテーブルidx=2が選択されること");
assert(tableFrame.scrollCalls.length === 0, "テーブルmouseenter時はテーブルを自動スクロールしないこと");
assert(activeTimers.size >= 1, "テーブルmouseenter時は画像フォーカスがデバウンス予約されること");
flushTimers();
assert(viewerHighlightBox.style.display === "block", "デバウンス後に元画像ハイライト枠が表示されること");
assert(viewerHighlightBox.style.left === "400px" && viewerHighlightBox.style.top === "100px", "デバウンス後に元画像ハイライト枠がidx=2のbox_2dへ移動すること");
results.push("case2_table_hover_sync:OK");

// 3. テーブル行(idx=0)にフォーカス(focusin) → デバウンスなしで即座に3要素連動
tableRows[0].dispatchEvent("focusin");
assert(JSON.stringify(getSelectedCalendarIndices()) === "[0]", "テーブルfocusinでカレンダーidx=0が選択されること");
assert(JSON.stringify(getSelectedTableIndices()) === "[0]", "テーブルfocusinでテーブルidx=0が選択されること");
assert(viewerHighlightBox.style.left === "100px" && viewerHighlightBox.style.top === "100px", "テーブルfocusinで即座に元画像ハイライト枠がidx=0へ移動すること");
results.push("case3_table_focus_immediate_sync:OK");

// 4. 元画像ビューワー上のシフトマス目(idx=1)をクリック → 3要素連動（ドラッグとは区別）
// zoom-reset で scale=1.0, panX=(800-1000)/2 = -100, panY=20 の既知状態にセット
const btnZoomReset = elementsById.get("btn-zoom-reset");
btnZoomReset.dispatchEvent("click");
// btn-zoom-reset: scale=1.0, panX=(800-1000)/2 = -100, panY=20
// idx=1 の中心 imgX=300, imgY=150 -> mouseX = 300*1 + (-100) = 200, mouseY = 150*1 + 20 = 170
tableFrame.scrollCalls = [];
viewerCanvas.dispatchEvent("mousedown", { clientX: 200, clientY: 170 });
mockWindow.dispatchEvent("mouseup", { clientX: 201, clientY: 171, target: viewerCanvas });
assert(JSON.stringify(getSelectedCalendarIndices()) === "[1]", "元画像クリックでカレンダーidx=1が選択されること");
assert(JSON.stringify(getSelectedTableIndices()) === "[1]", "元画像クリックでテーブルidx=1が選択されること");
assert(viewerHighlightBox.style.left === "250px" && viewerHighlightBox.style.top === "100px", "元画像クリックでハイライト枠がidx=1へ移動すること");
assert(tableFrame.scrollCalls.length === 1, "元画像クリックでテーブル枠内スクロールが連動すること");

// ドラッグ(移動距離20px)では選択が変わらないこと
btnZoomReset.dispatchEvent("click");
// idx=2 の中心 imgX=450, imgY=150 -> mouseX=350, mouseY=170 から20pxドラッグ
viewerCanvas.dispatchEvent("mousedown", { clientX: 350, clientY: 170 });
mockWindow.dispatchEvent("mousemove", { clientX: 370, clientY: 170 });
mockWindow.dispatchEvent("mouseup", { clientX: 370, clientY: 170, target: viewerCanvas });
assert(JSON.stringify(getSelectedCalendarIndices()) === "[1]", "元画像ドラッグ操作では選択が切り替わらないこと");
results.push("case4_image_click_and_drag_distinction:OK");

// 5. box_2d が null のシフト(idx=3)を選択 → カレンダー・テーブルは連動し、元画像ハイライト枠は非表示になること
calCells[3].dispatchEvent("click");
assert(JSON.stringify(getSelectedCalendarIndices()) === "[3]", "box_2dなしシフトでカレンダーidx=3が選択されること");
assert(JSON.stringify(getSelectedTableIndices()) === "[3]", "box_2dなしシフトでテーブルidx=3が選択されること");
assert(viewerHighlightBox.style.display === "none", "box_2dなしシフト選択時に前のハイライト枠が消えること");
results.push("case5_missing_box2d_hides_highlight:OK");

// 6. 凡例クリック(toggleHighlight) → 3要素の選択状態と待機中タイマーがすべてクリアされること
tableRows[1].dispatchEvent("mouseenter"); // デバウンスタイマーを予約
sandbox.toggleHighlight("早A");
assert(JSON.stringify(getSelectedCalendarIndices()) === "[]", "凡例クリックでカレンダーの青枠がクリアされること");
assert(JSON.stringify(getSelectedTableIndices()) === "[]", "凡例クリックでテーブルの青枠がクリアされること");
assert(viewerHighlightBox.style.display === "none", "凡例クリックで元画像ハイライト枠が非表示になること");
flushTimers();
assert(viewerHighlightBox.style.display === "none", "凡例クリック後に旧ホバーのデバウンスタイマーで枠が復活しないこと");
results.push("case6_legend_clears_three_way_selection:OK");

console.log(JSON.stringify({ ok: true, results }));
"""


class TestUISyncThreeWay(unittest.TestCase):
    """元画像・カレンダー・シフト調整テーブルの3点連動および青枠スタイル統一を保証するテスト"""

    def test_01_css_selected_background_and_border_match(self):
        """カレンダーとシフト調整テーブルの .is-selected が同一の青枠・薄い青背景定義であること"""
        html = load_index_html_with_assets(INDEX_HTML_PATH)

        cal_match = re.search(r"\.cal-cell\.is-selected\s*\{([^}]*)\}", html)
        tr_match = re.search(r"tbody\s+tr\.is-selected\s*\{([^}]*)\}", html)
        td_match = re.search(r"tbody\s+tr\.is-selected\s+td\s*\{([^}]*)\}", html)

        self.assertIsNotNone(cal_match, ".cal-cell.is-selected のCSS定義が見つかりません")
        self.assertIsNotNone(tr_match, "tbody tr.is-selected のCSS定義が見つかりません")
        self.assertIsNotNone(td_match, "tbody tr.is-selected td のCSS定義が見つかりません")

        expected_bg = "linear-gradient(rgba(10, 132, 255, 0.12), rgba(10, 132, 255, 0.12)), var(--window-bg)"
        self.assertIn(expected_bg, cal_match.group(1), "カレンダー選択背景が var(--window-bg) 下地付き薄い青ではありません")
        self.assertIn(expected_bg, tr_match.group(1), "テーブル選択背景がカレンダーと同一ではありません")
        self.assertIn("var(--accent)", cal_match.group(1), "カレンダー選択枠に var(--accent) が使われていません")
        self.assertIn("var(--accent)", td_match.group(1), "テーブル選択枠に var(--accent) が使われていません")

    @unittest.skipUnless(shutil.which("node") is not None, "Node.js が利用できないためスキップ")
    def test_02_three_way_sync_behaviors(self):
        """実際の index.html スクリプトを実行し、カレンダー・テーブル・元画像の3方向連動を検証する"""
        proc = subprocess.run(
            ["node", "-e", NODE_TEST_HARNESS, INDEX_HTML_PATH],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            f"3点連動テスト失敗:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertTrue(payload.get("ok"))
        self.assertEqual(len(payload.get("results", [])), 6)


if __name__ == "__main__":
    unittest.main()
