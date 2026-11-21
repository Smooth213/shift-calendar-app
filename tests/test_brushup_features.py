import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import app as shift_app

from tests.dom_harness import JS_LOAD_INDEX_SCRIPT_SNIPPET, load_index_html_with_assets

INDEX_HTML_PATH = os.path.join(PROJECT_ROOT, "index.html")


NODE_BRUSHUP_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
""" + JS_LOAD_INDEX_SCRIPT_SNIPPET + r"""
const htmlPath = process.argv[1];
const scriptCode = loadIndexScriptFromHtml(htmlPath);

class MockClassList {
  constructor() { this.set = new Set(); }
  _syncFromString(str) { this.set = new Set((str || "").split(/\s+/).filter(Boolean)); }
  add(...cls) { cls.forEach(c => { if (c) this.set.add(c); }); }
  remove(...cls) { cls.forEach(c => this.set.delete(c)); }
  toggle(c, force) {
    if (force === undefined) {
      if (this.set.has(c)) { this.set.delete(c); return false; }
      this.set.add(c); return true;
    }
    if (force) { this.set.add(c); return true; }
    this.set.delete(c); return false;
  }
  contains(c) { return this.set.has(c); }
  toString() { return Array.from(this.set).join(" "); }
}

class MockElement {
  constructor(tagName = "div", id = "") {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.type = id === "api-key" ? "password" : "";
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
    this.attributes = {};
    this.classList = new MockClassList();
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(type, fn) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(fn);
  }
  async dispatchAsync(type, eventObj = {}) {
    const ev = Object.assign({ target: this, preventDefault() {}, stopPropagation() {} }, eventObj);
    const list = this.listeners[type] || [];
    for (const fn of list) {
      await fn(ev);
    }
  }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  scrollIntoView() {}
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  getContext() { return { drawImage() {} }; }
  toDataURL() { return "data:image/jpeg;base64,/9j/4AAQSkZJRg=="; }
}

const elements = new Map();
function getEl(id) {
  if (!elements.has(id)) {
    elements.set(id, new MockElement("div", id));
  }
  return elements.get(id);
}

const docListeners = {};
const documentMock = {
  hidden: false,
  documentElement: new MockElement("html"),
  getElementById: (id) => getEl(id),
  createElement: (tag) => new MockElement(tag),
  querySelectorAll: () => [],
  addEventListener: (type, fn) => {
    if (!docListeners[type]) docListeners[type] = [];
    docListeners[type].push(fn);
  },
  async dispatchAsync(type, eventObj = {}) {
    const list = docListeners[type] || [];
    for (const fn of list) {
      await fn(eventObj);
    }
  }
};

let analyzeCalls = 0;
let preloadPayload = {
  has_image: true,
  data: {
    preload_id: "qa_1001",
    auto_analyze: true,
    file_name: "quick_action_shift.jpg",
    file_size: 12345,
    mime_type: "image/jpeg",
    image_base64: "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
  }
};

const fetchMock = async (url, opts) => {
  if (url === "/api/config") {
    return {
      ok: true,
      json: async () => ({
        api_key: "DUMMY_TEST_KEY",
        default_name: "皿田",
        calendar_name: "シフトカレンダー",
        theme: "system",
        time_definitions: { "日": { start: "08:30", end: "17:30" } }
      })
    };
  }
  if (url === "/api/get_preloaded") {
    return { ok: true, json: async () => preloadPayload };
  }
  if (url === "/api/analyze") {
    analyzeCalls += 1;
    // サーバー側と同様に1回消費をシミュレート
    preloadPayload.data.auto_analyze = false;
    return {
      ok: true,
      json: async () => ({
        success: true,
        data: {
          shifts: [{ date: "2026-11-01", shift_type: "日", status: "work", start_time: "08:30", end_time: "17:30", event: "" }],
          has_event_candidates: false
        }
      })
    };
  }
  if (url === "/api/history") {
    return { ok: true, json: async () => ({ history: [] }) };
  }
  if (url === "/api/history/save") {
    return { ok: true, json: async () => ({ success: true, id: "h1" }) };
  }
  if (url === "/api/analyze_progress") {
    return { ok: true, json: async () => ({ active: false, percent: 100, label: "完了", detail: "", step: 4 }) };
  }
  return { ok: true, json: async () => ({ success: true }) };
};

const localStorageStore = {};
const sandbox = {
  document: documentMock,
  window: {
    addEventListener: () => {},
    matchMedia: () => ({ matches: false, addEventListener: () => {} })
  },
  navigator: { clipboard: { writeText: async () => {} } },
  localStorage: {
    getItem: (k) => localStorageStore[k] || null,
    setItem: (k, v) => { localStorageStore[k] = String(v); }
  },
  fetch: fetchMock,
  setInterval: () => 1,
  clearInterval: () => {},
  setTimeout: () => 1,
  clearTimeout: () => {},
  console,
  Date,
  Math,
  JSON,
  Set,
  Map,
  Promise,
  encodeURIComponent,
  Image: class {},
  FileReader: class {}
};

vm.createContext(sandbox);
vm.runInContext(scriptCode, sandbox);

(async () => {
  // initConfig() と自動解析（Step 1 + Step 2）の非同期完了を待機
  for (let i = 0; i < 12; i++) {
    await new Promise(r => setImmediate(r));
  }

  const analyzeCallsAfterQuickAction = analyzeCalls;

  // 2回目の checkPreloadedImage()（ハートビート相当）で重複解析されないこと
  await sandbox.checkPreloadedImage();
  await new Promise(r => setImmediate(r));
  const analyzeCallsAfterHeartbeat = analyzeCalls;

  // 設定モーダルを開いて目アイコンでAPIキーを表示→閉じるで自動マスク復帰を確認
  await getEl("btn-open-settings").dispatchAsync("click");
  const modalOpenDisplay = getEl("settings-modal").style.display;
  const typeOnOpen = getEl("api-key").type;

  await getEl("btn-toggle-api-key").dispatchAsync("click");
  const typeAfterToggleShow = getEl("api-key").type;
  const eyeOpenAfterShow = getEl("icon-eye-open").style.display;
  const eyeOffAfterShow = getEl("icon-eye-off").style.display;

  await getEl("btn-close-settings").dispatchAsync("click");
  const modalCloseDisplay = getEl("settings-modal").style.display;
  const typeAfterClose = getEl("api-key").type;

  // auto_analyze: false のプリロード画像では自動解析が走らないこと
  preloadPayload = {
    has_image: true,
    data: {
      preload_id: "qa_1002",
      auto_analyze: false,
      file_name: "manual_or_reloaded.jpg",
      file_size: 22222,
      mime_type: "image/jpeg",
      image_base64: "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
    }
  };
  await sandbox.checkPreloadedImage();
  await new Promise(r => setImmediate(r));
  const analyzeCallsAfterNonAutoPreload = analyzeCalls;

  console.log(JSON.stringify({
    analyzeCallsAfterQuickAction,
    analyzeCallsAfterHeartbeat,
    analyzeCallsAfterNonAutoPreload,
    modalOpenDisplay,
    typeOnOpen,
    typeAfterToggleShow,
    eyeOpenAfterShow,
    eyeOffAfterShow,
    modalCloseDisplay,
    typeAfterClose
  }));
})().catch(err => {
  console.error(err);
  process.exit(1);
});
"""


class TestBrushupFeatures(unittest.TestCase):
    def test_01_holiday_and_google_observance_filter_handles_variants_and_typos(self):
        """国民の祝日・Google標準行事（表記揺れ含む）を除外し、職場イベントは保持すること"""
        excluded_cases = [
            "元日",
            "成人の日",
            "建国記念の日",
            "建国記念日",
            "天皇誕生日",
            "春分の日",
            "昭和の日",
            "憲法記念日",
            "みどりの日",
            "こどもの日",
            "子供の日",
            "海の日",
            "山の日",
            "敬老の日",
            "秋分の日",
            "スポーツの日",
            "体育の日",
            "文化の日",
            "勤労感謝の日",
            "振替休日",
            "国民の休日",
            "銀行休業日",
            "節分",
            "バレンタインデー",
            "バレンタイン",
            "ひな祭り",
            "ひなまつり",
            "母の日",
            "父の日",
            "七夕",
            "ハロウィン",
            "七五三",
            "クリスマスイブ",
            "クリスマス",
            "Xmas",
            "X'mas",
            "Ｘｍａｓ",
            "Christmas",
            "大晦日",
            "大みそか",
            "おおみそか",
        ]
        for label in excluded_cases:
            with self.subTest(excluded=label):
                self.assertEqual(shift_app.clean_event_text_excluding_holidays(label), "")

        kept_cases = [
            ("クリスマス会", "クリスマス会"),
            ("敬老会", "敬老会"),
            ("ひな祭り会", "ひな祭り会"),
            ("節分豆まき", "節分豆まき"),
            ("感謝祭", "感謝祭"),
            ("主任会議", "主任会議"),
            ("忘年会", "忘年会"),
            ("お餅つき", "お餅つき"),
            # 併記された場合は祝日側だけ除外して施設行事を残す
            ("敬老の日・敬老会", "敬老会"),
            ("クリスマス / クリスマス会", "クリスマス会"),
            ("大みそか 忘年会", "忘年会"),
        ]
        for raw, expected in kept_cases:
            with self.subTest(kept=raw):
                self.assertEqual(shift_app.clean_event_text_excluding_holidays(raw), expected)

    def test_02_fetch_column_events_filters_holidays_from_gemini_output(self):
        """Geminiが祝日やXmas・誤字祝日を返しても除外し、スキップ件数と名称を正確に記録すること"""
        fake_response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "events": [
                                {"col": 3, "event": "文化の日", "is_holiday": True},
                                {"col": 10, "event": "主任会議", "is_holiday": False},
                                {"col": 15, "event": "敬老の曰", "is_holiday": True},
                                {"col": 23, "event": "勤労感謝の日", "is_holiday": True},
                                {"col": 25, "event": "X'mas", "is_holiday": True},
                                {"col": 26, "event": "クリスマス会", "is_holiday": False},
                                {"col": 31, "event": "大みそか", "is_holiday": True},
                            ]
                        }, ensure_ascii=False)
                    }]
                }
            }]
        }

        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(fake_response).encode("utf-8")

        skipped_out = []
        with patch("urllib.request.urlopen", return_value=FakeResp()):
            res = shift_app.fetch_column_events_from_gemini(
                "DUMMY_KEY",
                b"\xff\xd8\xff\xd9",
                31,
                active_col_nums=[3, 10, 15, 23, 25, 26, 31],
                skipped_holidays_out=skipped_out,
            )
        self.assertEqual(res, {10: "主任会議", 26: "クリスマス会"})
        self.assertEqual(len(skipped_out), 5)
        self.assertEqual(
            [x["name"] for x in skipped_out],
            ["文化の日", "敬老の曰", "勤労感謝の日", "X'mas", "大みそか"],
        )

    def test_03_settings_modal_structure_and_no_inline_api_key_in_basic_card(self):
        """基本設定・外観モード・APIキーが設定モーダルに統合され、メイン画面の基本設定セクションにはサマリー表示が残ること"""
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn('id="btn-open-settings"', html)
        self.assertNotIn('id="btn-save-cfg"', html)
        self.assertIn('id="settings-modal"', html)
        self.assertIn('id="btn-toggle-api-key"', html)
        self.assertIn('id="icon-eye-open"', html)
        self.assertIn('id="icon-eye-off"', html)

        # 設定モーダル内に基本設定（対象者名・登録先カレンダー）・外観モード・APIキー・シフト区分が存在すること
        modal_start = html.index('id="settings-modal"')
        modal_html = html[modal_start:]
        self.assertIn('id="target-name"', modal_html)
        self.assertIn('id="calendar-name"', modal_html)
        self.assertIn('id="theme-selector"', modal_html)
        self.assertIn('id="api-key"', modal_html)
        self.assertIn('id="settings-defs-list"', modal_html)

        # 基本設定セクション内には現在値サマリーと設定変更ボタンがあり、APIキーがないこと
        basic_start = html.index("<!-- Configuration Section -->")
        history_start = html.index("<!-- History Section")
        basic_html = html[basic_start:history_start]
        self.assertIn('id="basic-summary-target-name"', basic_html)
        self.assertIn('id="basic-summary-calendar-name"', basic_html)
        self.assertIn('id="btn-open-basic-settings"', basic_html)
        self.assertNotIn('id="api-key"', basic_html)

    def test_04_quick_action_auto_analyze_and_api_key_visibility_toggle(self):
        """クイックアクション起動時のみ1回だけ自動解析され、設定モーダルの目アイコン切替が動作すること"""
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node が利用できないためスキップ")

        proc = subprocess.run(
            [node_bin, "-e", NODE_BRUSHUP_HARNESS, INDEX_HTML_PATH],
            capture_output=True,
            text=True,
            check=True,
        )
        result = json.loads(proc.stdout.strip())
        self.assertEqual(result["analyzeCallsAfterQuickAction"], 1)
        self.assertEqual(result["analyzeCallsAfterHeartbeat"], 1)
        self.assertEqual(result["analyzeCallsAfterNonAutoPreload"], 1)
        self.assertEqual(result["modalOpenDisplay"], "flex")
        self.assertEqual(result["typeOnOpen"], "password")
        self.assertEqual(result["typeAfterToggleShow"], "text")
        self.assertEqual(result["eyeOpenAfterShow"], "none")
        self.assertEqual(result["eyeOffAfterShow"], "block")
        self.assertEqual(result["modalCloseDisplay"], "none")
        self.assertEqual(result["typeAfterClose"], "password")

    def test_05_ui_displays_skipped_holiday_count_and_names(self):
        """赤丸部のスキップ件数ボタンが表示され、クリックでアコーディオン一覧が開閉すること"""
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node が利用できないためスキップ")

        harness = NODE_BRUSHUP_HARNESS.replace(
            'has_event_candidates: false',
            'has_event_candidates: true'
        ).replace(
            '  return { ok: true, json: async () => ({ success: true }) };',
            '''  if (url === "/api/analyze_events") {
    return {
      ok: true,
      json: async () => ({
        success: true,
        data: {
          events: { "1": "主任会議" },
          active_cols: [1, 3, 23],
          n_cols: 30,
          extracted_count: 1,
          skipped_holidays_count: 2,
          skipped_holidays: [{ col: 1, name: "文化の日" }, { col: 23, name: "勤労感謝の日" }]
        }
      })
    };
  }
  return { ok: true, json: async () => ({ success: true }) };'''
        ).replace(
            '  console.log(JSON.stringify({',
            '''  const panelOpenInitial = getEl("skipped-holidays-panel").classList.contains("is-open");
  await getEl("btn-skipped-holidays-toggle").dispatchAsync("click");
  const panelOpenAfterClick1 = getEl("skipped-holidays-panel").classList.contains("is-open");
  const ariaAfterClick1 = getEl("btn-skipped-holidays-toggle").getAttribute("aria-expanded");
  await getEl("btn-skipped-holidays-toggle").dispatchAsync("click");
  const panelOpenAfterClick2 = getEl("skipped-holidays-panel").classList.contains("is-open");

  console.log(JSON.stringify({'''
        ).replace(
            '    typeAfterClose\n  }));',
            '''    typeAfterClose,
    badgeText: getEl("events-status-badge").textContent,
    toggleDisplay: getEl("btn-skipped-holidays-toggle").style.display,
    toggleLabel: getEl("skipped-holidays-toggle-label").textContent,
    panelOpenInitial,
    panelOpenAfterClick1,
    ariaAfterClick1,
    panelOpenAfterClick2,
    skippedListHtml: getEl("skipped-holidays-list").innerHTML,
    progressDetail: getEl("analyze-progress-detail").textContent
  }));'''
        )

        proc = subprocess.run(
            [node_bin, "-e", harness, INDEX_HTML_PATH],
            capture_output=True,
            text=True,
            check=True,
        )
        result = json.loads(proc.stdout.strip())
        self.assertEqual(result["badgeText"], "行事予定 1件を反映済み")
        self.assertEqual(result["toggleDisplay"], "inline-flex")
        self.assertEqual(result["toggleLabel"], "日本の祝日・Googleカレンダー標準行事スキップ 2件")
        self.assertFalse(result["panelOpenInitial"])
        self.assertTrue(result["panelOpenAfterClick1"])
        self.assertEqual(result["ariaAfterClick1"], "true")
        self.assertFalse(result["panelOpenAfterClick2"])
        self.assertIn("11/1", result["skippedListHtml"])
        self.assertIn("文化の日", result["skippedListHtml"])
        self.assertIn("勤労感謝の日", result["skippedListHtml"])
        self.assertIn("祝日等 2件スキップ", result["progressDetail"])

    def test_06_settings_modal_escape_overlay_and_save_remasks_api_key(self):
        """設定モーダルのEscape・背景クリック・保存して閉じるでモーダルが閉じAPIキーが再マスクされること"""
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node が利用できないためスキップ")

        harness = NODE_BRUSHUP_HARNESS.replace(
            'let analyzeCalls = 0;',
            'let analyzeCalls = 0;\nlet configPostCalls = 0;\nlet lastSavedConfig = null;'
        ).replace(
            '  if (url === "/api/config") {',
            '''  if (url === "/api/config" && opts && opts.method === "POST") {
    configPostCalls += 1;
    lastSavedConfig = JSON.parse(opts.body);
    return { ok: true, json: async () => ({ success: true }) };
  }
  if (url === "/api/config") {'''
        ).replace(
            '  console.log(JSON.stringify({',
            '''  // Escapeキーで閉じて再マスク
  await getEl("btn-open-settings").dispatchAsync("click");
  await getEl("btn-toggle-api-key").dispatchAsync("click");
  const typeBeforeEsc = getEl("api-key").type;
  await documentMock.dispatchAsync("keydown", { key: "Escape" });
  const displayAfterEsc = getEl("settings-modal").style.display;
  const typeAfterEsc = getEl("api-key").type;

  // オーバーレイ背景クリックで閉じて再マスク
  await getEl("btn-open-settings").dispatchAsync("click");
  await getEl("btn-toggle-api-key").dispatchAsync("click");
  await getEl("settings-modal").dispatchAsync("click", { target: getEl("settings-modal") });
  const displayAfterOverlay = getEl("settings-modal").style.display;
  const typeAfterOverlay = getEl("api-key").type;

  // 「保存して閉じる」でPOST /api/configされ、閉じて再マスク
  await getEl("btn-open-settings").dispatchAsync("click");
  await getEl("btn-toggle-api-key").dispatchAsync("click");
  getEl("api-key").value = "NEW_API_KEY_999";
  await getEl("btn-save-settings-modal").dispatchAsync("click");
  const displayAfterSave = getEl("settings-modal").style.display;
  const typeAfterSave = getEl("api-key").type;

  console.log(JSON.stringify({'''
        ).replace(
            '    typeAfterClose\n  }));',
            '''    typeAfterClose,
    typeBeforeEsc,
    displayAfterEsc,
    typeAfterEsc,
    displayAfterOverlay,
    typeAfterOverlay,
    configPostCalls,
    savedApiKey: lastSavedConfig ? lastSavedConfig.api_key : null,
    displayAfterSave,
    typeAfterSave
  }));'''
        )

        proc = subprocess.run(
            [node_bin, "-e", harness, INDEX_HTML_PATH],
            capture_output=True,
            text=True,
            check=True,
        )
        result = json.loads(proc.stdout.strip())
        self.assertEqual(result["typeBeforeEsc"], "text")
        self.assertEqual(result["displayAfterEsc"], "none")
        self.assertEqual(result["typeAfterEsc"], "password")
        self.assertEqual(result["displayAfterOverlay"], "none")
        self.assertEqual(result["typeAfterOverlay"], "password")
        self.assertEqual(result["configPostCalls"], 1)
        self.assertEqual(result["savedApiKey"], "NEW_API_KEY_999")
        self.assertEqual(result["displayAfterSave"], "none")
        self.assertEqual(result["typeAfterSave"], "password")

    def test_07_quick_action_without_api_key_and_outdated_server_auto_shutdown(self):
        """APIキー未設定時は自動解析せず、実ブラウザで旧サーバー検知時は/api/shutdownを自動送信すること"""
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node が利用できないためスキップ")

        # (A) APIキー未設定時のクイックアクション起動
        harness_no_key = NODE_BRUSHUP_HARNESS.replace(
            'api_key: "DUMMY_TEST_KEY",',
            'api_key: "",'
        ).replace(
            'const analyzeCallsAfterQuickAction = analyzeCalls;',
            'const analyzeCallsAfterQuickAction = analyzeCalls;\n  const toastAfterQuickAction = getEl("toast").textContent;'
        ).replace(
            '    typeAfterClose\n  }));',
            '''    typeAfterClose,
    toastAfterQuickAction
  }));'''
        )
        proc_a = subprocess.run(
            [node_bin, "-e", harness_no_key, INDEX_HTML_PATH],
            capture_output=True,
            text=True,
            check=True,
        )
        res_a = json.loads(proc_a.stdout.strip())
        self.assertEqual(res_a["analyzeCallsAfterQuickAction"], 0)
        self.assertIn("Gemini APIキー", res_a["toastAfterQuickAction"])

        # (B) 実ブラウザ(http:)で server_version 未搭載の旧サーバーを検知 -> /api/shutdown 送信 & 自動解析停止
        harness_outdated = NODE_BRUSHUP_HARNESS.replace(
            'let analyzeCalls = 0;',
            'let analyzeCalls = 0;\nlet shutdownCalls = 0;'
        ).replace(
            '  window: {',
            '  window: {\n    location: { protocol: "http:", host: "localhost:8765" },'
        ).replace(
            '  if (url === "/api/history") {',
            '''  if (url === "/api/shutdown" && opts && opts.method === "POST") {
    shutdownCalls += 1;
    return { ok: true, json: async () => ({ success: true }) };
  }
  if (url === "/api/history") {'''
        ).replace(
            '    typeAfterClose\n  }));',
            '''    typeAfterClose,
    shutdownCalls
  }));'''
        )
        proc_b = subprocess.run(
            [node_bin, "-e", harness_outdated, INDEX_HTML_PATH],
            capture_output=True,
            text=True,
            check=True,
        )
        res_b = json.loads(proc_b.stdout.strip())
        self.assertEqual(res_b["shutdownCalls"], 1)
        self.assertEqual(res_b["analyzeCallsAfterQuickAction"], 0)

    def test_08_ocr_typo_normalization_and_analyze_events_only_skip_metadata(self):
        """縦書きOCR誤字（曰→日）を除外でき、analyze_events_onlyがスキップ件数・名称を返すこと"""
        for typo in ("大晦曰", "敬老の曰", "建国記念の曰", "文化の曰", "元曰"):
            with self.subTest(typo=typo):
                kept, skipped = shift_app.split_event_and_skipped_holidays(typo)
                self.assertEqual(kept, "")
                self.assertEqual(skipped, [typo])

        fake_grid = {"n_cols": 36, "grid_x": [i * 30 for i in range(37)], "grid_y": [0, 20, 40, 200]}

        def fake_fetch(api_key, strip_bytes, n_cols, active_col_nums=None, active_spans=None, skipped_holidays_out=None):
            if isinstance(skipped_holidays_out, list):
                skipped_holidays_out.extend([
                    {"col": 27, "name": "Xmas"},
                    {"col": 33, "name": "大晦日"},
                    {"col": 34, "name": "元旦"},
                ])
            return {31: "仕事納め"}

        import numpy as np
        dummy_img = np.full((220, 1100, 3), 255, dtype=np.uint8)
        import cv2
        _, jpg = cv2.imencode(".jpg", dummy_img)
        raw_bytes = jpg.tobytes()

        with patch.object(shift_app, "dewarp_table_image", return_value=(raw_bytes, None)), \
             patch.object(shift_app, "detect_table_grid", return_value=fake_grid), \
             patch.object(shift_app, "detect_active_event_spans", return_value=[(26, 26), (30, 30), (32, 32), (33, 33)]), \
             patch.object(shift_app, "build_labeled_event_strip", return_value=raw_bytes), \
             patch.object(shift_app, "fetch_column_events_from_gemini", side_effect=fake_fetch):
            out = shift_app.analyze_events_only("DUMMY_KEY", raw_bytes)

        self.assertEqual(out["events"], {"31": "仕事納め"})
        self.assertEqual(out["extracted_count"], 1)
        self.assertEqual(out["skipped_holidays_count"], 3)
        self.assertEqual([h["name"] for h in out["skipped_holidays"]], ["Xmas", "大晦日", "元旦"])
        self.assertIn("3 件スキップ", shift_app.ANALYZE_PROGRESS["detail"])

    def test_09_ui_skipped_holidays_zero_case_and_holiday_only_case(self):
        """スキップ0件時もis-zeroボタンが表示され、祝日のみスキップ時はAPI混雑誤表示にならないこと"""
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node が利用できないためスキップ")

        # (A) 職場行事1件・スキップ0件
        harness_zero = NODE_BRUSHUP_HARNESS.replace(
            'has_event_candidates: false',
            'has_event_candidates: true'
        ).replace(
            '  return { ok: true, json: async () => ({ success: true }) };',
            '''  if (url === "/api/analyze_events") {
    return {
      ok: true,
      json: async () => ({
        success: true,
        data: {
          events: { "1": "主任会議" },
          active_cols: [1],
          n_cols: 30,
          extracted_count: 1,
          skipped_holidays_count: 0,
          skipped_holidays: []
        }
      })
    };
  }
  return { ok: true, json: async () => ({ success: true }) };'''
        ).replace(
            '    typeAfterClose\n  }));',
            '''    typeAfterClose,
    toggleDisplay: getEl("btn-skipped-holidays-toggle").style.display,
    toggleIsZero: getEl("btn-skipped-holidays-toggle").classList.contains("is-zero"),
    toggleLabel: getEl("skipped-holidays-toggle-label").textContent,
    skippedListHtml: getEl("skipped-holidays-list").innerHTML
  }));'''
        )
        proc_zero = subprocess.run(
            [node_bin, "-e", harness_zero, INDEX_HTML_PATH],
            capture_output=True,
            text=True,
            check=True,
        )
        res_zero = json.loads(proc_zero.stdout.strip())
        self.assertEqual(res_zero["toggleDisplay"], "inline-flex")
        self.assertTrue(res_zero["toggleIsZero"])
        self.assertEqual(res_zero["toggleLabel"], "日本の祝日・Googleカレンダー標準行事スキップ 0件")
        self.assertIn("スキップされた項目はありません", res_zero["skippedListHtml"])

        # (B) 職場行事0件・祝日スキップ2件（API混雑エラーに誤認しないこと）
        harness_hol_only = NODE_BRUSHUP_HARNESS.replace(
            'has_event_candidates: false',
            'has_event_candidates: true'
        ).replace(
            '  return { ok: true, json: async () => ({ success: true }) };',
            '''  if (url === "/api/analyze_events") {
    return {
      ok: true,
      json: async () => ({
        success: true,
        data: {
          events: {},
          active_cols: [3, 23],
          n_cols: 30,
          extracted_count: 0,
          skipped_holidays_count: 2,
          skipped_holidays: [{ col: 3, name: "文化の日" }, { col: 23, name: "勤労感謝の日" }]
        }
      })
    };
  }
  return { ok: true, json: async () => ({ success: true }) };'''
        ).replace(
            '    typeAfterClose\n  }));',
            '''    typeAfterClose,
    badgeText: getEl("events-status-badge").textContent,
    toggleIsZero: getEl("btn-skipped-holidays-toggle").classList.contains("is-zero"),
    toggleLabel: getEl("skipped-holidays-toggle-label").textContent,
    progressDetail: getEl("analyze-progress-detail").textContent
  }));'''
        )
        proc_hol = subprocess.run(
            [node_bin, "-e", harness_hol_only, INDEX_HTML_PATH],
            capture_output=True,
            text=True,
            check=True,
        )
        res_hol = json.loads(proc_hol.stdout.strip())
        self.assertEqual(res_hol["badgeText"], "行事予定: 0件")
        self.assertFalse(res_hol["toggleIsZero"])
        self.assertEqual(res_hol["toggleLabel"], "日本の祝日・Googleカレンダー標準行事スキップ 2件")
        self.assertNotIn("API混雑", res_hol["progressDetail"])
        self.assertIn("2件をスキップしました", res_hol["progressDetail"])

    def test_10_dewarp_status_backend_and_ui_badge(self):
        """水平・垂直補正ステータスが実態に応じて返却・表示され、固定(0.00°)や絵文字がないこと"""
        import cv2
        import numpy as np

        # 1) 不正データ → not_applied
        _, b64_err, st_err = shift_app.dewarp_table_image_with_status(b"invalid-bytes")
        self.assertIsNone(b64_err)
        self.assertEqual(st_err, "not_applied")

        # 2) 合成斜め表画像 → 1回目 applied / 2回目 already_dewarped
        canvas = np.full((1200, 900, 3), 235, dtype=np.uint8)
        table = np.full((420, 620, 3), 255, dtype=np.uint8)
        for y in range(20, 401, 38):
            cv2.line(table, (20, y), (600, y), (20, 20, 20), 2)
        for x in range(20, 601, 40):
            cv2.line(table, (x, 20), (x, 400), (20, 20, 20), 2)
        src_quad = np.array([[0, 0], [619, 0], [619, 419], [0, 419]], dtype=np.float32)
        dst_quad = np.array([[140, 280], [740, 340], [710, 770], [110, 720]], dtype=np.float32)
        M = cv2.getPerspectiveTransform(src_quad, dst_quad)
        warped = cv2.warpPerspective(table, M, (900, 1200), borderMode=cv2.BORDER_CONSTANT, borderValue=(235, 235, 235))
        mask = cv2.warpPerspective(np.full((420, 620), 255, dtype=np.uint8), M, (900, 1200))
        canvas[mask > 0] = warped[mask > 0]
        _, jpg = cv2.imencode(".jpg", canvas)
        raw_bytes = jpg.tobytes()

        out_bytes, out_b64, st_1st = shift_app.dewarp_table_image_with_status(raw_bytes)
        self.assertEqual(st_1st, "applied")
        self.assertIsNotNone(out_b64)

        _, out_b64_2nd, st_2nd = shift_app.dewarp_table_image_with_status(out_bytes)
        self.assertEqual(st_2nd, "already_dewarped")
        self.assertIsNotNone(out_b64_2nd)

        # 既存2要素タプル互換確認
        compat = shift_app.dewarp_table_image(out_bytes)
        self.assertEqual(len(compat), 2)

        # 3) HTMLに(0.00°)や✨のハードコードがないこと
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("0.00°", html)
        self.assertNotIn("✨ 水平・垂直補正", html)

        # 4) UIのupdateDewarpStatusBadgeが全ステータスを正しく切替えること
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node が利用できないためスキップ")
        harness = r"""
const fs = require("fs");
const vm = require("vm");
""" + JS_LOAD_INDEX_SCRIPT_SNIPPET + r"""
const scriptSrc = loadIndexScriptFromHtml(process.argv[1]);
const m = scriptSrc.match(/function updateDewarpStatusBadge\(status\)\s*\{[\s\S]*?\n    \}/);
if (!m) throw new Error("updateDewarpStatusBadge not found");
const badge = {
  className: "",
  textContent: "",
  classList: {
    add(c) { badge.className = (badge.className ? badge.className + " " : "") + c; }
  }
};
const ctx = {
  document: { getElementById: (id) => (id === "dewarp-status-badge" ? badge : null) }
};
vm.runInNewContext(m[0], ctx);
const states = {};
for (const st of ["applied", "already_dewarped", "not_applied", "processing", null]) {
  ctx.updateDewarpStatusBadge(st);
  states[String(st)] = { className: badge.className, text: badge.textContent };
}
console.log(JSON.stringify(states));
"""
        proc = subprocess.run([node_bin, "-e", harness, INDEX_HTML_PATH], capture_output=True, text=True, check=True)
        states = json.loads(proc.stdout.strip())
        self.assertEqual(states["applied"]["text"], "水平・垂直補正 適用済み")
        self.assertIn("is-applied", states["applied"]["className"])
        self.assertEqual(states["already_dewarped"]["text"], "水平・垂直補正 不要（補正済み）")
        self.assertIn("is-already", states["already_dewarped"]["className"])
        self.assertEqual(states["not_applied"]["text"], "水平・垂直補正 未適用")
        self.assertIn("is-not-applied", states["not_applied"]["className"])
        self.assertEqual(states["processing"]["text"], "水平・垂直補正 処理中...")
        self.assertIn("is-processing", states["processing"]["className"])
        self.assertEqual(states["null"]["text"], "")
        self.assertEqual(states["null"]["className"], "dewarp-status-badge")

    def test_11_dewarp_status_badge_e2e_ui_flows(self):
        """実際のindex.html全スクリプトで、初期・プリロード・解析・履歴復元・最新復帰・削除・ファイル選択の全フローで◯部分ステータスが正しく表示・遷移すること"""
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node が利用できないためスキップ")

        e2e_harness = r"""
const fs = require("fs");
const vm = require("vm");
""" + JS_LOAD_INDEX_SCRIPT_SNIPPET + r"""
const scriptMatch = [null, loadIndexScriptFromHtml(process.argv[1])];

class MockClassList {
  constructor(owner) { this.owner = owner; this.set = new Set(); }
  add(...cs) { cs.forEach(c => this.set.add(c)); }
  remove(...cs) { cs.forEach(c => this.set.delete(c)); }
  toggle(c, force) {
    if (force === undefined) {
      if (this.set.has(c)) this.set.delete(c); else this.set.add(c);
    } else if (force) this.set.add(c); else this.set.delete(c);
  }
  contains(c) { return this.set.has(c); }
  resetFromString(str) {
    this.set = new Set(String(str || "").split(/\s+/).filter(Boolean));
  }
  toArray() { return Array.from(this.set); }
}

class MockElement {
  constructor(tag = "div", id = "") {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.style = {};
    this.dataset = {};
    this.children = [];
    this.listeners = {};
    this.textContent = "";
    this.innerHTML = "";
    this.value = "";
    this.type = "text";
    this.disabled = false;
    this.checked = false;
    this.src = "";
    this.title = "";
    this.attributes = {};
    this.classList = new MockClassList(this);
  }
  get className() { return this.classList.toArray().join(" "); }
  set className(v) { this.classList.resetFromString(v); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(type, fn) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(fn);
  }
  async dispatchAsync(type, eventObj = {}) {
    const ev = Object.assign({ target: this, preventDefault() {}, stopPropagation() {} }, eventObj);
    for (const fn of (this.listeners[type] || [])) {
      await fn(ev);
    }
  }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  scrollIntoView() {}
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  getContext() { return { drawImage() {} }; }
  toDataURL() { return "data:image/jpeg;base64,/9j/4AAQSkZJRg=="; }
}

const elements = new Map();
function getEl(id) {
  if (!elements.has(id)) elements.set(id, new MockElement("div", id));
  return elements.get(id);
}

const documentMock = {
  hidden: false,
  documentElement: new MockElement("html"),
  getElementById: (id) => getEl(id),
  createElement: (tag) => new MockElement(tag),
  querySelectorAll: () => [],
  addEventListener: () => {}
};

const savedHistories = [];
let previewResolver = null;
let previewResponseStatus = "not_applied";

const historyRecords = {
  h_already: {
    id: "h_already",
    title: "2026年11月度",
    created_at: "2026-11-20 10:00:00",
    target_name: "皿田",
    image_base64: "data:image/jpeg;base64,/9j/4AAQSkZJRg==",
    mime_type: "image/jpeg",
    dewarp_status: "already_dewarped",
    shifts: [{ date: "2026-11-01", type: "日", status: "work", start_time: "08:30", end_time: "17:30", event: "" }]
  },
  h_not_applied: {
    id: "h_not_applied",
    title: "2026年10月度",
    created_at: "2026-10-20 10:00:00",
    target_name: "皿田",
    image_base64: "data:image/jpeg;base64,/9j/4AAQSkZJRg==",
    mime_type: "image/jpeg",
    dewarp_status: "not_applied",
    shifts: [{ date: "2026-10-01", type: "休", status: "holiday", start_time: "", end_time: "", event: "" }]
  },
  h_legacy: {
    id: "h_legacy",
    title: "2026年9月度",
    created_at: "2026-09-20 10:00:00",
    target_name: "皿田",
    image_base64: "data:image/jpeg;base64,/9j/4AAQSkZJRg==",
    mime_type: "image/jpeg",
    shifts: [{ date: "2026-09-01", type: "日", status: "work", start_time: "08:30", end_time: "17:30", event: "" }]
  }
};

let preloadPayload = { has_image: false };

const fetchMock = async (url, opts = {}) => {
  if (url === "/api/config") {
    return {
      ok: true,
      json: async () => ({
        api_key: "DUMMY_TEST_KEY",
        default_name: "皿田",
        calendar_name: "シフトカレンダー",
        theme: "system",
        time_definitions: { "日": { start: "08:30", end: "17:30" } }
      })
    };
  }
  if (url === "/api/get_preloaded") {
    return { ok: true, json: async () => preloadPayload };
  }
  if (url === "/api/analyze") {
    return {
      ok: true,
      json: async () => ({
        success: true,
        data: {
          shifts: [{ date: "2026-12-01", type: "日", status: "work", start_time: "08:30", end_time: "17:30", event: "" }],
          corrected_image_base64: "data:image/jpeg;base64,/9j/4AAQSkZJRg==",
          dewarp_status: "already_dewarped",
          has_event_candidates: false
        }
      })
    };
  }
  if (url === "/api/history") {
    return { ok: true, json: async () => ({ history: [] }) };
  }
  if (url.startsWith("/api/history/detail?id=")) {
    const id = url.split("id=")[1];
    return { ok: true, json: async () => ({ success: true, data: historyRecords[id] }) };
  }
  if (url === "/api/history/save") {
    savedHistories.push(JSON.parse(opts.body));
    return { ok: true, json: async () => ({ success: true, id: "h_saved" }) };
  }
  if (url === "/api/dewarp_preview") {
    return new Promise((resolve) => {
      previewResolver = () => resolve({
        ok: true,
        json: async () => ({
          success: true,
          corrected_image_base64: "data:image/jpeg;base64,/9j/4AAQSkZJRg==",
          dewarp_status: previewResponseStatus
        })
      });
    });
  }
  if (url === "/api/analyze_progress") {
    return { ok: true, json: async () => ({ active: false, percent: 100, step: 4, phase: "完了", detail: "" }) };
  }
  return { ok: true, json: async () => ({ success: true }) };
};

class MockFileReader {
  readAsDataURL() {
    if (this.onload) this.onload({ target: { result: "data:image/jpeg;base64,/9j/4AAQSkZJRg==" } });
  }
}
class MockImage {
  set src(v) {
    this._src = v;
    this.width = 800;
    this.height = 600;
    if (this.onload) this.onload();
  }
}

const sandbox = {
  console,
  window: {
    location: { origin: "http://localhost:8765" },
    addEventListener: () => {},
    matchMedia: () => ({ matches: false, addEventListener: () => {} })
  },
  document: documentMock,
  localStorage: { _m: {}, getItem(k) { return this._m[k] ?? null; }, setItem(k, v) { this._m[k] = String(v); } },
  navigator: { sendBeacon: () => true },
  fetch: fetchMock,
  FileReader: MockFileReader,
  Image: MockImage,
  setInterval: () => 1,
  clearInterval: () => {},
  setTimeout: () => 1,
  clearTimeout: () => {},
  confirm: () => true,
  URL,
  Blob: class {}
};
sandbox.window.document = documentMock;

function snapshotBadge() {
  const b = getEl("dewarp-status-badge");
  return {
    text: b.textContent,
    classes: b.classList.toArray()
  };
}

vm.runInNewContext(scriptMatch[1], sandbox);

(async () => {
  await new Promise(r => setImmediate(r));
  await new Promise(r => setImmediate(r));

  // 1) 初期状態（画像未読み込み）
  const sInitial = snapshotBadge();

  // 2) クイックアクション（プリロード: applied）→ 自動解析（サーバーは already_dewarped を返すが applied を維持）
  preloadPayload = {
    has_image: true,
    data: {
      preload_id: "qa_badge_1",
      auto_analyze: true,
      file_name: "shift_photo.jpg",
      file_size: 12345,
      mime_type: "image/jpeg",
      image_base64: "data:image/jpeg;base64,/9j/4AAQSkZJRg==",
      dewarp_status: "applied"
    }
  };
  await sandbox.checkPreloadedImage();
  for (let i = 0; i < 6; i++) await new Promise(r => setImmediate(r));
  const sAfterPreloadAndAnalyze = snapshotBadge();
  const savedDewarpStatus = savedHistories.length > 0 ? savedHistories[savedHistories.length - 1].dewarp_status : null;

  // 3) 履歴読み込み: already_dewarped
  getEl("history-select").value = "h_already";
  await getEl("btn-load-history").dispatchAsync("click");
  const sHistAlready = snapshotBadge();

  // 4) 履歴読み込み: not_applied
  getEl("history-select").value = "h_not_applied";
  await getEl("btn-load-history").dispatchAsync("click");
  const sHistNotApplied = snapshotBadge();

  // 5) 履歴読み込み: 旧履歴（dewarp_status なし → 非表示）
  getEl("history-select").value = "h_legacy";
  await getEl("btn-load-history").dispatchAsync("click");
  const sHistLegacy = snapshotBadge();

  // 6) 最新解析結果へ戻る → applied に復元
  await getEl("btn-reset-history").dispatchAsync("click");
  const sResetToLatest = snapshotBadge();

  // 7) ファイル削除 → 非表示にリセット
  await getEl("btn-remove-file").dispatchAsync("click");
  const sAfterRemove = snapshotBadge();

  // 8) 手動ファイル選択（handleFile）→ processing 中表示 → 完了後 not_applied
  previewResponseStatus = "not_applied";
  sandbox.handleFile({ name: "blank.jpg", size: 2048, type: "image/jpeg" });
  const sFileProcessing = snapshotBadge();
  previewResolver();
  for (let i = 0; i < 4; i++) await new Promise(r => setImmediate(r));
  const sFileNotApplied = snapshotBadge();

  // 9) 手動ファイル選択 → already_dewarped
  previewResponseStatus = "already_dewarped";
  sandbox.handleFile({ name: "already.jpg", size: 2048, type: "image/jpeg" });
  previewResolver();
  for (let i = 0; i < 4; i++) await new Promise(r => setImmediate(r));
  const sFileAlready = snapshotBadge();

  console.log(JSON.stringify({
    sInitial,
    sAfterPreloadAndAnalyze,
    savedDewarpStatus,
    sHistAlready,
    sHistNotApplied,
    sHistLegacy,
    sResetToLatest,
    sAfterRemove,
    sFileProcessing,
    sFileNotApplied,
    sFileAlready
  }));
})().catch(err => {
  console.error(err);
  process.exit(1);
});
"""
        proc = subprocess.run(
            [node_bin, "-e", e2e_harness, INDEX_HTML_PATH],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=f"Node E2E harness failed:\n{proc.stderr}")
        res = json.loads(proc.stdout.strip())

        # 1) 初期状態は非表示（テキスト空・is-*なし）
        self.assertEqual(res["sInitial"]["text"], "")
        self.assertEqual(res["sInitial"]["classes"], [])

        # 2) プリロード(applied)→解析(already_dewarped)でも「適用済み」を維持し履歴にも保存
        self.assertEqual(res["sAfterPreloadAndAnalyze"]["text"], "水平・垂直補正 適用済み")
        self.assertIn("is-applied", res["sAfterPreloadAndAnalyze"]["classes"])
        self.assertEqual(res["savedDewarpStatus"], "applied")

        # 3) 履歴読み込み: already_dewarped
        self.assertEqual(res["sHistAlready"]["text"], "水平・垂直補正 不要（補正済み）")
        self.assertIn("is-already", res["sHistAlready"]["classes"])

        # 4) 履歴読み込み: not_applied
        self.assertEqual(res["sHistNotApplied"]["text"], "水平・垂直補正 未適用")
        self.assertIn("is-not-applied", res["sHistNotApplied"]["classes"])

        # 5) 旧履歴（dewarp_status未記録）: 非表示
        self.assertEqual(res["sHistLegacy"]["text"], "")
        self.assertEqual(res["sHistLegacy"]["classes"], ["dewarp-status-badge"])

        # 6) 最新結果へ戻る: applied 復元
        self.assertEqual(res["sResetToLatest"]["text"], "水平・垂直補正 適用済み")
        self.assertIn("is-applied", res["sResetToLatest"]["classes"])

        # 7) ファイル削除: 非表示にリセット
        self.assertEqual(res["sAfterRemove"]["text"], "")
        self.assertEqual(res["sAfterRemove"]["classes"], ["dewarp-status-badge"])

        # 8) 手動ファイル選択: 処理中 → 未適用
        self.assertEqual(res["sFileProcessing"]["text"], "水平・垂直補正 処理中...")
        self.assertIn("is-processing", res["sFileProcessing"]["classes"])
        self.assertEqual(res["sFileNotApplied"]["text"], "水平・垂直補正 未適用")
        self.assertIn("is-not-applied", res["sFileNotApplied"]["classes"])

        # 9) 手動ファイル選択: 不要（補正済み）
        self.assertEqual(res["sFileAlready"]["text"], "水平・垂直補正 不要（補正済み）")
        self.assertIn("is-already", res["sFileAlready"]["classes"])

        # 10) CSS側でもデフォルト非表示・状態クラス時のみ表示(inline-flex)であることを保証
        html_css = load_index_html_with_assets(INDEX_HTML_PATH)
        self.assertRegex(html_css, r"\.dewarp-status-badge\s*\{[^}]*display:\s*none;")
        for cls in ("is-applied", "is-already", "is-not-applied", "is-processing"):
            self.assertRegex(
                html_css,
                rf"\.dewarp-status-badge\.{cls}\s*\{{[^}}]*display:\s*inline-flex;",
                msg=f".dewarp-status-badge.{cls} に display: inline-flex がありません",
            )

    def test_12_registered_calendar_shifts_merge_and_config_defaults(self):
        """登録済み履歴のみが日付単位で統合され、同日は新しい登録を優先し画像を含まないこと、有給設定のデフォルトが有効なこと"""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(shift_app, "HISTORY_DIR", tmpdir):
                # 1) 未登録履歴（カレンダータブには出てはいけない）
                with open(os.path.join(tmpdir, "unreg_1.json"), "w", encoding="utf-8") as f:
                    json.dump({
                        "id": "unreg_1",
                        "title": "2026年11月度(未登録)",
                        "registered": False,
                        "created_at": "2026-11-20 10:00:00",
                        "shifts": [{"date": "2026-11-05", "type": "遅C", "status": "work"}],
                        "image_base64": "SHOULD_NOT_APPEAR"
                    }, f)

                # 2) 登録済み履歴A（古い方：10/25〜11/02、月またぎ）
                with open(os.path.join(tmpdir, "reg_old.json"), "w", encoding="utf-8") as f:
                    json.dump({
                        "id": "reg_old",
                        "title": "2026年10月度",
                        "registered": True,
                        "registered_at": "2026-10-20 09:00:00",
                        "target_name": "皿田",
                        "shifts": [
                            {"date": "2026-10-31", "type": "早A", "status": "work", "start_time": "06:00", "end_time": "15:00"},
                            {"date": "2026-11-01", "type": "日", "status": "work", "start_time": "08:30", "end_time": "17:30"}
                        ],
                        "image_base64": "SECRET_IMG_A"
                    }, f)

                # 3) 登録済み履歴B（新しい方：11/01が重複し、有給に更新されている）
                with open(os.path.join(tmpdir, "reg_new.json"), "w", encoding="utf-8") as f:
                    json.dump({
                        "id": "reg_new",
                        "title": "2026年11月度",
                        "registered": True,
                        "registered_at": "2026-11-01 12:00:00",
                        "target_name": "皿田",
                        "shifts": [
                            {"date": "2026-11-01", "type": "有給", "status": "paid_leave", "is_paid_leave": True, "summary": "有給休暇"},
                            {"date": "2026-11-02", "type": "休", "status": "holiday", "is_holiday": True, "summary": "休み"}
                        ],
                        "image_base64": "SECRET_IMG_B"
                    }, f)

                # 4) 破損JSON（クラッシュせず無視されること）
                with open(os.path.join(tmpdir, "broken.json"), "w", encoding="utf-8") as f:
                    f.write("{broken json")

                res = shift_app.get_registered_calendar_shifts()
                self.assertTrue(res["success"])
                self.assertEqual(res["registered_histories_count"], 2)
                self.assertEqual(res["available_months"], ["2026-10", "2026-11"])

                by_date = res["shifts_by_date"]
                # 未登録の11/05は含まれない
                self.assertNotIn("2026-11-05", by_date)
                # 月またぎの10/31が含まれる
                self.assertEqual(by_date["2026-10-31"]["type"], "早A")
                self.assertEqual(by_date["2026-10-31"]["history_id"], "reg_old")
                # 同日重複11/01は新しい reg_new が優先される
                self.assertEqual(by_date["2026-11-01"]["status"], "paid_leave")
                self.assertEqual(by_date["2026-11-01"]["history_id"], "reg_new")
                # 軽量化のため image_base64 は含まれない
                for item in by_date.values():
                    self.assertNotIn("image_base64", item)

            # load_config の有給設定デフォルト・クランプ検証
            missing_cfg = os.path.join(tmpdir, "nonexistent_config.json")
            with patch.object(shift_app, "CONFIG_PATH", missing_cfg):
                cfg = shift_app.load_config()
                self.assertEqual(cfg["paid_leave_start_month"], 4)
                self.assertEqual(cfg["paid_leave_start_day"], 1)
                self.assertEqual(cfg["paid_leave_annual_days"], 20)

    def test_13_two_tab_monthly_calendar_and_annual_paid_leave_ui(self):
        """実際のindex.htmlスクリプトで2タブ切替・月間集計・年間有給カウント・設定反映・詳細遷移・クイックアクション自動切替を検証"""
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node が見つからないためスキップ")

        harness = r"""
const fs = require("fs");
const vm = require("vm");
""" + JS_LOAD_INDEX_SCRIPT_SNIPPET + r"""
const scriptMatch = [null, loadIndexScriptFromHtml(process.argv[1])];

class MockClassList {
  constructor() { this.set = new Set(); }
  _syncFromString(str) { this.set = new Set((str || "").split(/\s+/).filter(Boolean)); }
  add(...cls) { cls.forEach(c => { if (c) this.set.add(c); }); }
  remove(...cls) { cls.forEach(c => this.set.delete(c)); }
  toggle(c, force) {
    if (force === undefined) {
      if (this.set.has(c)) { this.set.delete(c); return false; }
      this.set.add(c); return true;
    }
    if (force) { this.set.add(c); return true; }
    this.set.delete(c); return false;
  }
  contains(c) { return this.set.has(c); }
  toString() { return Array.from(this.set).join(" "); }
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
    this.attributes = {};
    this.classList = new MockClassList();
  }
  get className() { return this.classList.toString(); }
  set className(v) { this.classList._syncFromString(v); }
  get innerHTML() { return this._innerHTML; }
  set innerHTML(v) { this._innerHTML = String(v || ""); if (!v) this.children = []; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(type, fn) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(fn);
  }
  async dispatchAsync(type, eventObj = {}) {
    const ev = Object.assign({ target: this, preventDefault() {}, stopPropagation() {} }, eventObj);
    const list = this.listeners[type] || [];
    for (const fn of list) await fn(ev);
  }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  contains(node) { return node === this || this.children.includes(node); }
  scrollIntoView() {}
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
}

const elements = new Map();
function getEl(id) {
  if (!elements.has(id)) elements.set(id, new MockElement("div", id));
  return elements.get(id);
}

const docListeners = {};
const documentMock = {
  hidden: false,
  activeElement: null,
  documentElement: new MockElement("html"),
  getElementById: (id) => getEl(id),
  createElement: (tag) => new MockElement(tag),
  querySelectorAll: () => [],
  addEventListener: (type, fn) => {
    if (!docListeners[type]) docListeners[type] = [];
    docListeners[type].push(fn);
  },
  async dispatchAsync(type, eventObj = {}) {
    const list = docListeners[type] || [];
    for (const fn of list) await fn(eventObj);
  }
};

let savedConfigPayload = null;
const calendarShiftsData = {
  "2026-03-10": { date: "2026-03-10", day_of_week: "火", type: "有給", status: "paid_leave", is_paid_leave: true, history_id: "h_202603", history_title: "2026年3月度", registered_at: "2026-03-01 10:00:00" },
  "2026-05-08": { date: "2026-05-08", day_of_week: "金", type: "有給", status: "paid_leave", is_paid_leave: true, history_id: "h_202605", history_title: "2026年5月度", registered_at: "2026-05-01 10:00:00" },
  "2026-11-02": { date: "2026-11-02", day_of_week: "月", type: "早A", status: "work", start_time: "06:00", end_time: "15:00", history_id: "h_202611", history_title: "2026年11月度", registered_at: "2026-11-01 09:00:00" },
  "2026-11-03": { date: "2026-11-03", day_of_week: "火", type: "休", status: "holiday", is_holiday: true, history_id: "h_202611", history_title: "2026年11月度", registered_at: "2026-11-01 09:00:00" },
  "2026-11-12": { date: "2026-11-12", day_of_week: "木", type: "有給", status: "paid_leave", is_paid_leave: true, summary: "有給休暇（私用カスタム）", history_id: "h_202611", history_title: "2026年11月度", registered_at: "2026-11-01 09:00:00" }
};

let preloadResponse = { has_image: false };

const context = {
  console,
  document: documentMock,
  window: {
    location: { protocol: "http:" },
    matchMedia: () => ({ matches: false, addEventListener() {} }),
    addEventListener() {},
    URL: { createObjectURL: () => "", revokeObjectURL() {} }
  },
  navigator: { userAgent: "Mac", clipboard: { writeText: async () => {} } },
  localStorage: { _d: {}, getItem(k) { return this._d[k] ?? null; }, setItem(k, v) { this._d[k] = String(v); } },
  setTimeout: () => 1,
  clearTimeout: () => {},
  setInterval: () => 1,
  clearInterval: () => {},
  confirm: () => true,
  Date,
  fetch: async (url, opts = {}) => {
    if (url === "/api/config" && opts.method === "POST") {
      savedConfigPayload = JSON.parse(opts.body);
      return { ok: true, json: async () => ({ success: true, config: savedConfigPayload }) };
    }
    if (url === "/api/config") {
      return {
        ok: true,
        json: async () => ({
          api_key: "TEST_KEY",
          default_name: "皿田",
          calendar_name: "シフトカレンダー",
          theme: "light",
          server_version: "2026.11.21.v3",
          paid_leave_start_month: 4,
          paid_leave_start_day: 1,
          paid_leave_annual_days: 20,
          time_definitions: { "早A": { start: "06:00", end: "15:00" } }
        })
      };
    }
    if (url === "/api/calendar_shifts") {
      return {
        ok: true,
        json: async () => ({
          success: true,
          shifts_by_date: calendarShiftsData,
          available_months: ["2026-03", "2026-05", "2026-11"],
          registered_histories_count: 3
        })
      };
    }
    if (url === "/api/history") {
      return { ok: true, json: async () => ({ history: [] }) };
    }
    if (url === "/api/history/detail?id=h_202611") {
      return {
        ok: true,
        json: async () => ({
          success: true,
          data: {
            id: "h_202611",
            title: "2026年11月度",
            registered: true,
            registered_at: "2026-11-01 09:00:00",
            target_name: "皿田",
            shifts: [calendarShiftsData["2026-11-02"], calendarShiftsData["2026-11-03"], calendarShiftsData["2026-11-12"]]
          }
        })
      };
    }
    if (url === "/api/get_preloaded") {
      return { ok: true, json: async () => preloadResponse };
    }
    return { ok: true, json: async () => ({ success: true }) };
  }
};

vm.createContext(context);
vm.runInContext(scriptMatch[1], context);

(async () => {
  await new Promise(r => setImmediate(r));
  await new Promise(r => setImmediate(r));

  // 1) 通常起動はカレンダータブ、フッター非表示
  const initialTab = {
    activeMainTab: vm.runInContext("activeMainTab", context),
    calHidden: getEl("tab-panel-calendar").classList.contains("is-hidden"),
    impHidden: getEl("tab-panel-import").classList.contains("is-hidden"),
    footerHidden: getEl("window-footer").classList.contains("is-hidden")
  };

  // 2) 2026年11月を表示して月間集計＆年間有給（2026/4/1〜2027/3/31）を確認
  vm.runInContext("calendarViewYear = 2026; calendarViewMonth = 11; renderMonthlyCalendarView();", context);

  const novState = {
    monthLabel: getEl("cal-current-month-label").textContent,
    work: getEl("cal-summary-work-days").textContent,
    holiday: getEl("cal-summary-holiday-days").textContent,
    paid: getEl("cal-summary-paid-days").textContent,
    annualPeriod: getEl("cal-annual-leave-period").textContent,
    annualUsed: getEl("cal-annual-leave-used").textContent,
    annualRemaining: getEl("cal-annual-leave-remaining").textContent,
    annualTotal: getEl("cal-annual-leave-total").textContent
  };

  // 3) 前月・次月ボタン移動の確認
  await getEl("btn-cal-prev-month").dispatchAsync("click");
  const prevMonthLabel = getEl("cal-current-month-label").textContent;
  await getEl("btn-cal-next-month").dispatchAsync("click");
  const backNovLabel = getEl("cal-current-month-label").textContent;

  // 4) 2026年3月（前年度 2025/4/1〜2026/3/31）へ移動して年間有給が1日になることを確認
  vm.runInContext("calendarViewYear = 2026; calendarViewMonth = 3; renderMonthlyCalendarView();", context);
  const marAnnual = {
    period: getEl("cal-annual-leave-period").textContent,
    used: getEl("cal-annual-leave-used").textContent,
    remaining: getEl("cal-annual-leave-remaining").textContent
  };

  // 5) 2026年11月に戻し、設定モーダルで起算日を 10/1・年間15日 に変更して保存
  vm.runInContext("calendarViewYear = 2026; calendarViewMonth = 11; renderMonthlyCalendarView();", context);
  getEl("paid-leave-start-month").value = "10";
  getEl("paid-leave-start-day").value = "1";
  getEl("paid-leave-annual-days").value = "15";
  await getEl("btn-save-settings-modal").dispatchAsync("click");
  const afterConfigSave = {
    savedConfigPayload,
    period: getEl("cal-annual-leave-period").textContent,
    used: getEl("cal-annual-leave-used").textContent,
    remaining: getEl("cal-annual-leave-remaining").textContent,
    total: getEl("cal-annual-leave-total").textContent
  };

  // 6) 日付詳細から「元画像・調整画面を開く」で読み込みタブへ遷移
  const novCells = getEl("monthly-calendar-body").children;
  const cellNov12 = novCells.find(c => c.dataset && c.dataset.date === "2026-11-12");
  await cellNov12.dispatchAsync("click");
  const detailVisible = getEl("monthly-calendar-detail").classList.contains("is-visible");
  const detailBodyHtml = getEl("cal-detail-body").innerHTML;
  await getEl("btn-cal-open-history").dispatchAsync("click");
  const afterOpenHistory = {
    activeMainTab: vm.runInContext("activeMainTab", context),
    impHidden: getEl("tab-panel-import").classList.contains("is-hidden"),
    footerHidden: getEl("window-footer").classList.contains("is-hidden"),
    currentHistoryId: vm.runInContext("currentHistoryId", context)
  };

  // 7) カレンダータブへ戻したあと、クイックアクション画像受信で自動で読み込みタブへ切替
  context.switchMainTab("calendar");
  context.handlePreloadedImageData({
    preload_id: "qa_tab_test",
    auto_analyze: false,
    file_name: "qa.jpg",
    file_size: 2048,
    mime_type: "image/jpeg",
    image_base64: "/9j/4AAQSkZJRg=="
  });
  const afterQuickAction = {
    activeMainTab: vm.runInContext("activeMainTab", context),
    impHidden: getEl("tab-panel-import").classList.contains("is-hidden")
  };

  console.log(JSON.stringify({
    initialTab,
    novState,
    prevMonthLabel,
    backNovLabel,
    marAnnual,
    afterConfigSave,
    detailVisible,
    detailBodyHtml,
    afterOpenHistory,
    afterQuickAction
  }));
})().catch(err => {
  console.error(err);
  process.exit(1);
});
"""
        proc = subprocess.run(
            [node_bin, "-e", harness, INDEX_HTML_PATH],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(proc.returncode, 0, msg=f"Node stderr:\n{proc.stderr}")
        res = json.loads(proc.stdout.strip().splitlines()[-1])

        # 1) 初期タブ
        self.assertEqual(res["initialTab"]["activeMainTab"], "calendar")
        self.assertFalse(res["initialTab"]["calHidden"])
        self.assertTrue(res["initialTab"]["impHidden"])
        self.assertTrue(res["initialTab"]["footerHidden"])

        # 2) 2026年11月の月間集計＋年間有給（2026/4/1〜2027/3/31 は 5/8 と 11/12 の2日0時間）
        self.assertEqual(res["novState"]["monthLabel"], "2026年 11月")
        self.assertEqual(res["novState"]["work"], "1日")
        self.assertEqual(res["novState"]["holiday"], "1日")
        self.assertEqual(res["novState"]["paid"], "1日 0時間")
        self.assertEqual(res["novState"]["annualPeriod"], "(2026/4/1 〜 2027/3/31)")
        self.assertEqual(res["novState"]["annualUsed"], "2日 0時間")
        self.assertEqual(res["novState"]["annualRemaining"], "18日 0時間")
        self.assertEqual(res["novState"]["annualTotal"], "20日")

        # 3) 前月・次月ナビゲーション
        self.assertEqual(res["prevMonthLabel"], "2026年 10月")
        self.assertEqual(res["backNovLabel"], "2026年 11月")

        # 4) 2026年3月（前年度 2025/4/1〜2026/3/31 は 3/10 の1日0時間のみ）
        self.assertEqual(res["marAnnual"]["period"], "(2025/4/1 〜 2026/3/31)")
        self.assertEqual(res["marAnnual"]["used"], "1日 0時間")
        self.assertEqual(res["marAnnual"]["remaining"], "19日 0時間")

        # 5) 設定変更（10/1起算・15日付与 → 2026/10/1〜2027/9/30 は 11/12 の1日0時間のみ、残り14日0時間）
        self.assertEqual(res["afterConfigSave"]["savedConfigPayload"]["paid_leave_start_month"], 10)
        self.assertEqual(res["afterConfigSave"]["savedConfigPayload"]["paid_leave_start_day"], 1)
        self.assertEqual(res["afterConfigSave"]["savedConfigPayload"]["paid_leave_annual_days"], 15)
        self.assertEqual(res["afterConfigSave"]["period"], "(2026/10/1 〜 2027/9/30)")
        self.assertEqual(res["afterConfigSave"]["used"], "1日 0時間")
        self.assertEqual(res["afterConfigSave"]["remaining"], "14日 0時間")
        self.assertEqual(res["afterConfigSave"]["total"], "15日")

        # 6) 日付詳細 → カレンダー登録名表示＆元画像・調整画面を開く
        self.assertTrue(res["detailVisible"])
        self.assertIn("カレンダー登録名:", res["detailBodyHtml"])
        self.assertIn("有給休暇（私用カスタム）", res["detailBodyHtml"])
        self.assertEqual(res["afterOpenHistory"]["activeMainTab"], "import")
        self.assertFalse(res["afterOpenHistory"]["impHidden"])
        self.assertFalse(res["afterOpenHistory"]["footerHidden"])
        self.assertEqual(res["afterOpenHistory"]["currentHistoryId"], "h_202611")

        # 7) クイックアクション受信時の自動タブ切替
        self.assertEqual(res["afterQuickAction"]["activeMainTab"], "import")
        self.assertFalse(res["afterQuickAction"]["impHidden"])


if __name__ == "__main__":
    unittest.main()
