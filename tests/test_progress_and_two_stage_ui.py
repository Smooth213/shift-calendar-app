import json
import os
import shutil
import subprocess
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from tests.dom_harness import JS_LOAD_INDEX_SCRIPT_SNIPPET, load_index_html_with_assets

INDEX_HTML_PATH = os.path.join(PROJECT_ROOT, "index.html")

NODE_TWO_STAGE_HARNESS = r"""
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
    this.attributes = {};
    this.classList = new MockClassList();
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  get className() { return this.classList.toString(); }
  set className(val) { this.classList._syncFromString(val); }
  get innerHTML() { return this._innerHTML; }
  set innerHTML(val) {
    this._innerHTML = val;
    if (val === "") this.children = [];
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
  querySelectorAll(selector) {
    const res = [];
    if (selector === ".shift-check" || selector === ".shift-check:checked") {
      for (const tr of this.children) {
        const m = tr._innerHTML.match(/data-idx="(\d+)"/);
        if (m) {
          const cb = new MockElement("input");
          cb.checked = true;
          cb.dataset.idx = m[1];
          res.push(cb);
        }
      }
      return res;
    }
    if (selector === ".shift-event") {
      return this._eventInputs || [];
    }
    return res;
  }
  querySelector() { return null; }
  getBoundingClientRect() { return { top: 0, left: 0, bottom: 440, right: 800, width: 800, height: 440 }; }
  scrollIntoView() {}
  scrollTo() {}
  click() {}
}

const byId = new Map();
function ensureId(id, tag = "div") {
  if (!byId.has(id)) byId.set(id, new MockElement(tag, id));
  return byId.get(id);
}

[
  ["api-key", "input"], ["target-name", "input"], ["calendar-name", "input"],
  ["defs-container", "div"], ["history-select", "select"], ["btn-load-history", "button"],
  ["btn-delete-history", "button"], ["history-active-info", "div"], ["history-active-text", "span"],
  ["btn-reset-history", "button"], ["history-count-badge", "span"], ["btn-save-cfg", "button"],
  ["drop-zone", "div"], ["file-input", "input"], ["file-preview-bar", "div"],
  ["preview-filename", "span"], ["preview-filesize", "span"], ["preview-thumbnail", "img"],
  ["btn-remove-file", "button"], ["btn-analyze", "button"], ["result-container", "div"],
  ["res-target-name", "strong"], ["btn-toggle-viewer", "button"], ["monthly-metrics-container", "div"],
  ["viewer-wrapper", "div"], ["dewarp-status-badge", "span"], ["zoom-text", "span"],
  ["btn-zoom-in", "button"], ["btn-zoom-out", "button"], ["btn-zoom-fit", "button"],
  ["btn-zoom-reset", "button"], ["viewer-canvas", "div"], ["viewer-stage", "div"],
  ["compare-image", "img"], ["viewer-highlight-box", "div"], ["calendar-body", "div"],
  ["check-all", "input"], ["shifts-tbody", "tbody"], ["footer-count", "div"],
  ["btn-export-ics", "button"], ["btn-register", "button"], ["qr-modal", "div"],
  ["btn-show-qr", "button"], ["btn-close-qr", "button"], ["btn-copy-url", "button"],
  ["mobile-url-input", "input"], ["qr-img", "img"], ["toast", "div"],
  ["check-include-events", "input"], ["analyze-progress-card", "div"],
  ["analyze-progress-phase", "span"], ["analyze-progress-meta", "span"],
  ["analyze-progress-fill", "div"], ["analyze-progress-detail", "div"],
  ["events-status-badge", "span"], ["btn-retry-events", "button"]
].forEach(([id, tag]) => ensureId(id, tag));

ensureId("check-include-events", "input").checked = true;
ensureId("api-key", "input").value = "test-api-key";
ensureId("target-name", "input").value = "皿田";

const stepPills = [1, 2, 3, 4].map(n => {
  const el = new MockElement("span");
  el.classList.add("analyze-step-pill");
  el.dataset.step = String(n);
  return el;
});

const fetchLog = [];
let eventApiShouldFail = false;

const documentMock = {
  documentElement: new MockElement("html"),
  body: new MockElement("body"),
  hidden: false,
  getElementById: (id) => ensureId(id),
  createElement: (tag) => new MockElement(tag),
  addEventListener: () => {},
  querySelectorAll: (sel) => {
    if (sel === ".analyze-step-pill") return stepPills;
    if (sel === ".cal-cell") return ensureId("calendar-body").children;
    if (sel === "#shifts-tbody tr") return ensureId("shifts-tbody").children;
    if (sel === ".shift-check:checked") return ensureId("shifts-tbody").querySelectorAll(".shift-check:checked");
    if (sel === "#shifts-tbody .shift-event") return ensureId("shifts-tbody").children.map(tr => tr._eventInput).filter(Boolean);
    return [];
  }
};

// shifts-tbody に appendChild された tr から .shift-event モック入力を生成
const origAppend = ensureId("shifts-tbody").appendChild.bind(ensureId("shifts-tbody"));
ensureId("shifts-tbody").appendChild = (tr) => {
  const m = tr._innerHTML.match(/data-idx="(\d+)"/);
  if (m) {
    const evIn = new MockElement("input");
    evIn.dataset.idx = m[1];
    evIn.value = "";
    tr._eventInput = evIn;
  }
  return origAppend(tr);
};

const intervals = [];
const sandbox = {
  console,
  document: documentMock,
  window: {
    matchMedia: () => ({ matches: false, addEventListener: () => {} }),
    addEventListener: () => {},
    URL: { createObjectURL: () => "blob:mock", revokeObjectURL: () => {} }
  },
  navigator: { userAgent: "Mac", clipboard: { writeText: async () => {} } },
  localStorage: { _m: {}, getItem(k) { return this._m[k] || null; }, setItem(k, v) { this._m[k] = String(v); } },
  setTimeout: (fn) => 1,
  clearTimeout: () => {},
  setInterval: (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; },
  clearInterval: () => {},
  alert: () => {},
  confirm: () => true,
  fetch: async (url, opts = {}) => {
    fetchLog.push({ url, method: opts.method || "GET" });
    if (url === "/api/config") {
      return { ok: true, json: async () => ({ backend_version: "events_v2", time_definitions: {} }) };
    }
    if (url === "/api/history") {
      return { ok: true, json: async () => ({ history: [] }) };
    }
    if (url === "/api/get_preloaded") {
      return { ok: true, json: async () => ({ has_image: false }) };
    }
    if (url === "/api/analyze_progress") {
      return { ok: true, json: async () => ({ active: true, percent: 55, step: 3, phase: "ステップ 3/4: シフト記号をAIで読み取り中...", detail: "モデル: gemini-flash-lite-latest" }) };
    }
    if (url === "/api/analyze") {
      return {
        ok: true,
        json: async () => ({
          success: true,
          data: {
            target_name: "皿田",
            has_event_candidates: true,
            active_event_cols: [1, 2],
            shifts: [
              { date: "2026-12-01", day_of_week: "火", type: "早B", status: "work", start_time: "06:30", end_time: "15:30", summary: "[早B] (06:30〜15:30)", event: "" },
              { date: "2026-12-02", day_of_week: "水", type: "休", status: "holiday", is_holiday: true, start_time: null, end_time: null, summary: "休み", event: "" }
            ]
          }
        })
      };
    }
    if (url === "/api/analyze_events") {
      if (eventApiShouldFail) {
        return { ok: false, json: async () => ({ error: "HTTP 503 Service Unavailable" }) };
      }
      return {
        ok: true,
        json: async () => ({
          success: true,
          data: {
            events: { "1": "労力奉仕", "2": "誕生会" },
            active_cols: [1, 2],
            extracted_count: 2
          }
        })
      };
    }
    if (url === "/api/history/save") {
      return { ok: true, json: async () => ({ success: true, id: "20261201_000000" }) };
    }
    return { ok: true, json: async () => ({}) };
  }
};

vm.createContext(sandbox);
vm.runInContext(scriptCode + `
  globalThis.__setImage = (b64) => { currentImageBase64 = b64; };
  globalThis.__getShifts = () => analyzedShifts;
  globalThis.__updateProgressUI = updateProgressUI;
`, sandbox);

(async () => {
  sandbox.__setImage("data:image/jpeg;base64,ZmFrZQ==");

  // 1. 通常フロー: Step 1 (/api/analyze) -> Step 2 (/api/analyze_events) が自動で連続実行されること
  await ensureId("btn-analyze").dispatchAsync("click");

  const shiftsAfterNormal = sandbox.__getShifts();
  const calHtmlAfterNormal = ensureId("calendar-body").children.map(c => c.innerHTML).join("\n");
  const progressVisible = ensureId("analyze-progress-card").classList.contains("is-visible");
  const progressWidth = ensureId("analyze-progress-fill").style.width;
  const progressDoneClass = ensureId("analyze-progress-fill").classList.contains("is-done");
  const allStepsDone = stepPills.every(p => p.classList.contains("is-done"));
  const footerTextNormal = ensureId("footer-count").textContent;
  const eventInputVals = ensureId("shifts-tbody").children.map(tr => tr._eventInput.value);

  // 2. Step 2 が失敗したときにシフト結果が残存し、「行事予定のみ再取得」ボタンで復帰できること
  eventApiShouldFail = true;
  await ensureId("btn-analyze").dispatchAsync("click");
  const shiftsAfterEvFail = sandbox.__getShifts();
  const retryBtnVisibleOnFail = ensureId("btn-retry-events").style.display === "inline-flex";
  const retryBtnEnabledOnFail = ensureId("btn-retry-events").disabled === false;

  eventApiShouldFail = false;
  await ensureId("btn-retry-events").dispatchAsync("click");
  const shiftsAfterRetry = sandbox.__getShifts();

  console.log(JSON.stringify({
    calledUrls: fetchLog.map(x => x.url),
    normalEvents: shiftsAfterNormal.map(s => s.event),
    calHasEvent1: calHtmlAfterNormal.includes("cal-day-event-pill") && calHtmlAfterNormal.includes("労力奉仕"),
    calHasEvent2: calHtmlAfterNormal.includes("誕生会"),
    progressVisible,
    progressWidth,
    progressDoneClass,
    allStepsDone,
    footerTextNormal,
    eventInputVals,
    shiftsPreservedOnEventFail: shiftsAfterEvFail.length === 2,
    retryBtnVisibleOnFail,
    retryBtnEnabledOnFail,
    eventsAfterRetry: shiftsAfterRetry.map(s => s.event)
  }));
})().catch(err => {
  console.error(err);
  process.exit(1);
});
"""


class TestProgressAndTwoStageUI(unittest.TestCase):
    def test_01_progress_bar_html_and_css_present(self):
        """プログレスバー・4ステップピル・行事再取得ボタンのHTML/CSS定義が存在すること"""
        html = load_index_html_with_assets(INDEX_HTML_PATH)

        required_tokens = [
            'id="analyze-progress-card"',
            'id="analyze-progress-phase"',
            'id="analyze-progress-meta"',
            'id="analyze-progress-fill"',
            'id="analyze-progress-detail"',
            'data-step="1"',
            'data-step="2"',
            'data-step="3"',
            'data-step="4"',
            'id="events-status-badge"',
            'id="btn-retry-events"',
            'id="check-include-events"',
            ".analyze-progress-fill.is-events",
            ".analyze-progress-fill.is-done",
            ".analyze-progress-fill.is-error",
        ]
        for token in required_tokens:
            self.assertIn(token, html, f"index.html に必須要素 {token} が見つかりません")

    def test_02_two_stage_analysis_runs_events_and_updates_progress_bar(self):
        """実際のindex.htmlスクリプトで2段階解析（シフト→行事）とプログレスバー・再取得ボタンが連動すること"""
        node_bin = shutil.which("node")
        self.assertIsNotNone(node_bin, "node コマンドが見つかりません")

        proc = subprocess.run(
            [node_bin, "-e", NODE_TWO_STAGE_HARNESS, INDEX_HTML_PATH],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, f"Node UI テスト失敗:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")

        res = json.loads(proc.stdout.strip().splitlines()[-1])

        # Step 1 (/api/analyze) の直後に Step 2 (/api/analyze_events) が必ず実行されること
        self.assertIn("/api/analyze", res["calledUrls"])
        self.assertIn("/api/analyze_events", res["calledUrls"])
        self.assertLess(res["calledUrls"].index("/api/analyze"), res["calledUrls"].index("/api/analyze_events"))

        # 行事予定がデータ・カレンダー・テーブル入力欄・フッター件数へ反映されること
        self.assertEqual(res["normalEvents"], ["労力奉仕", "誕生会"])
        self.assertTrue(res["calHasEvent1"])
        self.assertTrue(res["calHasEvent2"])
        self.assertEqual(res["eventInputVals"], ["労力奉仕", "誕生会"])
        self.assertIn("＋行事 2件", res["footerTextNormal"])

        # プログレスバーが表示され、100%・完了色・全4ステップ完了になること
        self.assertTrue(res["progressVisible"])
        self.assertEqual(res["progressWidth"], "100%")
        self.assertTrue(res["progressDoneClass"])
        self.assertTrue(res["allStepsDone"])

        # Step 2 失敗時もシフト結果が保持され、「行事予定のみ再取得」で復旧できること
        self.assertTrue(res["shiftsPreservedOnEventFail"])
        self.assertTrue(res["retryBtnVisibleOnFail"])
        self.assertTrue(res["retryBtnEnabledOnFail"])
        self.assertEqual(res["eventsAfterRetry"], ["労力奉仕", "誕生会"])


if __name__ == "__main__":
    unittest.main()
