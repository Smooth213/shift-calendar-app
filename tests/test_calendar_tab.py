import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import app as shift_app

from tests.dom_harness import JS_LOAD_INDEX_SCRIPT_SNIPPET

INDEX_HTML_PATH = os.path.join(PROJECT_ROOT, "index.html")


def _build_calendar_node_harness(test_body_js):
    return r"""
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
  querySelectorAll: (sel) => {
    if (sel === ".shift-check") {
      return [{ checked: true, dataset: { idx: "0" } }];
    }
    return [];
  },
  addEventListener: (type, fn) => {
    if (!docListeners[type]) docListeners[type] = [];
    docListeners[type].push(fn);
  },
  async dispatchAsync(type, eventObj = {}) {
    const list = docListeners[type] || [];
    for (const fn of list) await fn(eventObj);
  }
};

let calendarFetchCount = 0;
let lastHourlyLeaveRequest = null;
let calendarShiftsData = {
  "2026-10-15": { date: "2026-10-15", day_of_week: "木", type: "早A", status: "work", start_time: "06:00", end_time: "15:00", summary: "[早A] (06:00〜15:00)", history_id: "h_oct", history_title: "2026年10月度", registered_at: "2026-10-01 09:00:00" },
  "2026-11-05": { date: "2026-11-05", day_of_week: "木", type: "有給", status: "paid_leave", is_paid_leave: true, summary: "有給休暇", history_id: "h_nov", history_title: "2026年11月度", registered_at: "2026-11-01 09:00:00" },
  "2026-11-06": { date: "2026-11-06", day_of_week: "金", type: "有給", status: "paid_leave", is_paid_leave: true, summary: "有給休暇", history_id: "h_nov", history_title: "2026年11月度", registered_at: "2026-11-01 09:00:00" },
  "2026-11-07": { date: "2026-11-07", day_of_week: "土", type: "有給", status: "paid_leave", is_paid_leave: true, summary: "有給休暇", history_id: "h_nov", history_title: "2026年11月度", registered_at: "2026-11-01 09:00:00" }
};
let availableMonths = ["2026-10", "2026-11"];
let configResp = {
  api_key: "TEST_KEY",
  default_name: "皿田",
  calendar_name: "シフトカレンダー",
  theme: "light",
  server_version: "2026.11.21.v3",
  paid_leave_start_month: 4,
  paid_leave_start_day: 1,
  paid_leave_annual_days: 20,
  time_definitions: { "早A": { start: "06:00", end: "15:00" }, "日": { start: "08:30", end: "17:30" } }
};

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
      return { ok: true, json: async () => ({ success: true, config: JSON.parse(opts.body) }) };
    }
    if (url === "/api/config") {
      return { ok: true, json: async () => configResp };
    }
    if (url === "/api/calendar_shifts") {
      calendarFetchCount++;
      return {
        ok: true,
        json: async () => ({
          success: true,
          shifts_by_date: calendarShiftsData,
          available_months: availableMonths,
          registered_histories_count: 2
        })
      };
    }
    if (url === "/api/history") {
      return { ok: true, json: async () => ({ history: [] }) };
    }
    if (url === "/api/history/delete") {
      return { ok: true, json: async () => ({ success: true }) };
    }
    if (url === "/api/register") {
      return { ok: true, json: async () => ({ success: true, count: 1, history_id: "h_nov", registered_at: "2026-11-21 14:00:00" }) };
    }
    if (url === "/api/calendar_shifts/hourly_leave" && opts.method === "POST") {
      const req = JSON.parse(opts.body);
      lastHourlyLeaveRequest = req;
      if (calendarShiftsData[req.date]) {
        calendarShiftsData[req.date].hourly_paid_leave = req.hourly_paid_leave;
        calendarShiftsData[req.date].summary = `[早A] (06:00〜15:00)（時間有給${req.hourly_paid_leave}h）`;
      }
      return {
        ok: true,
        json: async () => ({
          success: true,
          shift: calendarShiftsData[req.date] || {},
          apple_calendar_synced: Boolean(req.sync_apple_calendar)
        })
      };
    }
    if (url === "/api/get_preloaded") {
      return { ok: true, json: async () => ({ has_image: false }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
  }
};

vm.createContext(context);
vm.runInContext(scriptMatch[1], context);

(async () => {
  await new Promise(r => setImmediate(r));
  await new Promise(r => setImmediate(r));
""" + test_body_js + r"""
})().catch(err => {
  console.error(err);
  process.exit(1);
});
"""


def _make_mock_handler(path, method="GET", body_dict=None):
    handler = shift_app.RequestHandler.__new__(shift_app.RequestHandler)
    handler.path = path
    raw_body = json.dumps(body_dict).encode("utf-8") if body_dict is not None else b""
    handler.headers = {"Content-Length": str(len(raw_body))}
    handler.rfile = io.BytesIO(raw_body)
    captured = {}

    def _capture_json(data, status=200):
        captured["status"] = status
        captured["data"] = data

    handler._send_json = _capture_json
    handler.send_error = lambda code, msg=None: captured.update({"status": code, "error": msg})
    if method == "GET":
        handler.do_GET()
    else:
        handler.do_POST()
    return captured


class TestCalendarTab(unittest.TestCase):
    def _run_node(self, test_body_js):
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node が見つからないためスキップ")
        harness = _build_calendar_node_harness(test_body_js)
        proc = subprocess.run(
            [node_bin, "-e", harness, INDEX_HTML_PATH],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(proc.returncode, 0, msg=f"Node stderr:\n{proc.stderr}")
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_01_api_calendar_shifts_endpoint_and_config_post_clamping(self):
        """GET /api/calendar_shifts と POST /api/config の有給設定クランプが正しく動作すること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)
            with open(os.path.join(hist_dir, "reg_1.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "id": "reg_1",
                    "title": "2026年11月度",
                    "registered": True,
                    "registered_at": "2026-11-01 10:00:00",
                    "shifts": [
                        {"date": "2026-11-10", "type": "日", "status": "work", "summary": "[日] カスタム登録名"}
                    ],
                    "image_base64": "LARGE_IMAGE"
                }, f)

            with patch.object(shift_app, "HISTORY_DIR", hist_dir), \
                 patch.object(shift_app, "CONFIG_PATH", cfg_path), \
                 patch.object(shift_app, "get_local_ip", return_value="127.0.0.1"):
                # GET /api/calendar_shifts
                get_res = _make_mock_handler("/api/calendar_shifts", method="GET")
                self.assertEqual(get_res["status"], 200)
                self.assertTrue(get_res["data"]["success"])
                self.assertEqual(get_res["data"]["available_months"], ["2026-11"])
                self.assertEqual(
                    get_res["data"]["shifts_by_date"]["2026-11-10"]["summary"],
                    "[日] カスタム登録名",
                )
                self.assertNotIn("image_base64", get_res["data"]["shifts_by_date"]["2026-11-10"])

                # POST /api/config で範囲外値を渡しても安全にクランプされる
                post_res = _make_mock_handler(
                    "/api/config",
                    method="POST",
                    body_dict={
                        "paid_leave_start_month": 99,
                        "paid_leave_start_day": 0,
                        "paid_leave_annual_days": -5,
                    },
                )
                self.assertEqual(post_res["status"], 200)
                self.assertEqual(post_res["data"]["config"]["paid_leave_start_month"], 12)
                self.assertEqual(post_res["data"]["config"]["paid_leave_start_day"], 1)
                self.assertEqual(post_res["data"]["config"]["paid_leave_annual_days"], 0)

    def test_02_month_picker_dots_year_nav_and_jump(self):
        """年月ピッカーでデータあり月ドット表示・年切替・月ジャンプ・Escape閉じが正しく動作すること"""
        res = self._run_node(r"""
  vm.runInContext("calendarViewYear = 2026; calendarViewMonth = 11; renderMonthlyCalendarView();", context);

  // ピッカーを開く
  await getEl("btn-cal-month-picker").dispatchAsync("click");
  const openState = getEl("cal-month-picker-popover").classList.contains("is-open");
  const yearLabel2026 = getEl("cal-picker-year-label").textContent;
  const gridItems = getEl("cal-picker-month-grid").children;
  const octHasDot = gridItems[9].innerHTML.includes("month-picker-dot");
  const novHasDot = gridItems[10].innerHTML.includes("month-picker-dot");
  const decHasDot = gridItems[11].innerHTML.includes("month-picker-dot");

  // 前年へ移動
  await getEl("btn-picker-prev-year").dispatchAsync("click");
  const yearLabel2025 = getEl("cal-picker-year-label").textContent;
  const nov2025HasDot = getEl("cal-picker-month-grid").children[10].innerHTML.includes("month-picker-dot");

  // 翌年（2026）へ戻し、10月をクリックしてジャンプ
  await getEl("btn-picker-next-year").dispatchAsync("click");
  await getEl("cal-picker-month-grid").children[9].dispatchAsync("click");
  const afterJumpLabel = getEl("cal-current-month-label").textContent;
  const closedAfterJump = !getEl("cal-month-picker-popover").classList.contains("is-open");

  // 再度開いて Escape で閉じる
  await getEl("btn-cal-month-picker").dispatchAsync("click");
  await documentMock.dispatchAsync("keydown", { key: "Escape" });
  const closedAfterEsc = !getEl("cal-month-picker-popover").classList.contains("is-open");

  console.log(JSON.stringify({
    openState, yearLabel2026, octHasDot, novHasDot, decHasDot,
    yearLabel2025, nov2025HasDot, afterJumpLabel, closedAfterJump, closedAfterEsc
  }));
""")
        self.assertTrue(res["openState"])
        self.assertEqual(res["yearLabel2026"], "2026年")
        self.assertTrue(res["octHasDot"])
        self.assertTrue(res["novHasDot"])
        self.assertFalse(res["decHasDot"])
        self.assertEqual(res["yearLabel2025"], "2025年")
        self.assertFalse(res["nov2025HasDot"])
        self.assertEqual(res["afterJumpLabel"], "2026年 10月")
        self.assertTrue(res["closedAfterJump"])
        self.assertTrue(res["closedAfterEsc"])

    def test_03_keyboard_nav_guards_and_today_button(self):
        """矢印キーでの月移動、入力欄/モーダル/他タブ時の抑止、今月ボタンが正しく動作すること"""
        res = self._run_node(r"""
  vm.runInContext("calendarViewYear = 2026; calendarViewMonth = 11; renderMonthlyCalendarView();", context);

  // カレンダータブ表示中は ArrowLeft / ArrowRight で移動
  await documentMock.dispatchAsync("keydown", { key: "ArrowLeft" });
  const afterLeft = getEl("cal-current-month-label").textContent;
  await documentMock.dispatchAsync("keydown", { key: "ArrowRight" });
  const afterRight = getEl("cal-current-month-label").textContent;

  // INPUTフォーカス中は移動しない
  documentMock.activeElement = { tagName: "INPUT" };
  await documentMock.dispatchAsync("keydown", { key: "ArrowLeft" });
  const whileInputFocused = getEl("cal-current-month-label").textContent;
  documentMock.activeElement = null;

  // 設定モーダル表示中は移動しない
  getEl("settings-modal").style.display = "flex";
  await documentMock.dispatchAsync("keydown", { key: "ArrowLeft" });
  const whileModalOpen = getEl("cal-current-month-label").textContent;
  getEl("settings-modal").style.display = "none";

  // 読み込みタブ表示中は移動しない
  context.switchMainTab("import");
  await documentMock.dispatchAsync("keydown", { key: "ArrowLeft" });
  const whileImportTab = getEl("cal-current-month-label").textContent;

  // カレンダータブへ戻し、2024年1月へ移動後に「今月」ボタンで今月へ戻る
  context.switchMainTab("calendar");
  vm.runInContext("calendarViewYear = 2024; calendarViewMonth = 1; renderMonthlyCalendarView();", context);
  await getEl("btn-cal-today").dispatchAsync("click");
  const now = new Date();
  const expectedTodayLabel = `${now.getFullYear()}年 ${now.getMonth() + 1}月`;
  const afterTodayClick = getEl("cal-current-month-label").textContent;

  console.log(JSON.stringify({
    afterLeft, afterRight, whileInputFocused, whileModalOpen, whileImportTab,
    expectedTodayLabel, afterTodayClick
  }));
""")
        self.assertEqual(res["afterLeft"], "2026年 10月")
        self.assertEqual(res["afterRight"], "2026年 11月")
        self.assertEqual(res["whileInputFocused"], "2026年 11月")
        self.assertEqual(res["whileModalOpen"], "2026年 11月")
        self.assertEqual(res["whileImportTab"], "2026年 11月")
        self.assertEqual(res["afterTodayClick"], res["expectedTodayLabel"])

    def test_04_annual_paid_leave_edge_cases_and_overage(self):
        """うるう年2/29起算クランプおよび年間有給付与超過時の表示（0日超過N日・is-over・100%）が正しいこと"""
        res = self._run_node(r"""
  // うるう年 / 平年の 2/29 起算検証
  const nonLeap = context.computePaidLeaveFiscalPeriod(2026, 11, 2, 29);
  const leap = context.computePaidLeaveFiscalPeriod(2028, 3, 2, 29);

  // 付与2日に対して 2026年11月に3日有給取得（超過1日）
  vm.runInContext("paidLeaveConfig = { startMonth: 4, startDay: 1, annualDays: 2 }; calendarViewYear = 2026; calendarViewMonth = 11; renderMonthlyCalendarView();", context);
  const overage = {
    used: getEl("cal-annual-leave-used").textContent,
    remaining: getEl("cal-annual-leave-remaining").textContent,
    isOverClass: getEl("cal-annual-leave-progress").classList.contains("is-over"),
    width: getEl("cal-annual-leave-progress").style.width
  };

  console.log(JSON.stringify({ nonLeap, leap, overage }));
""")
        self.assertEqual(res["nonLeap"]["startStr"], "2026-02-28")
        self.assertEqual(res["nonLeap"]["endStr"], "2027-02-27")
        self.assertEqual(res["leap"]["startStr"], "2028-02-29")
        self.assertEqual(res["leap"]["endStr"], "2029-02-27")
        self.assertEqual(res["overage"]["used"], "3日 0時間")
        self.assertEqual(res["overage"]["remaining"], "0日 0時間（超過 1日 0時間）")
        self.assertTrue(res["overage"]["isOverClass"])
        self.assertEqual(res["overage"]["width"], "100%")

    def test_05_empty_month_legend_highlight_detail_close_and_auto_refresh(self):
        """空月バナー遷移・凡例ハイライト維持・詳細閉じる・登録/削除時の自動再取得が動作すること"""
        res = self._run_node(r"""
  // 1) 空月（2026年12月）でバナーが表示され、「勤務表を読み込む」ボタンで読み込みタブへ遷移
  vm.runInContext("calendarViewYear = 2026; calendarViewMonth = 12; renderMonthlyCalendarView();", context);
  const emptyVisibleDec = getEl("monthly-calendar-empty").classList.contains("is-visible");
  await getEl("btn-cal-go-import").dispatchAsync("click");
  const tabAfterEmptyBtn = vm.runInContext("activeMainTab", context);

  // 2) カレンダータブへ戻り、2026年11月で空月バナーが非表示になること
  context.switchMainTab("calendar");
  vm.runInContext("calendarViewYear = 2026; calendarViewMonth = 11; renderMonthlyCalendarView();", context);
  const emptyVisibleNov = getEl("monthly-calendar-empty").classList.contains("is-visible");

  // 3) 凡例ハイライトを設定し、月移動後も状態が維持され、再クリックで解除されること
  const firstLegend = getEl("cal-view-defs-container").children[0];
  await firstLegend.dispatchAsync("click");
  const hlAfterClick = vm.runInContext("calendarHighlightKey", context);
  await getEl("btn-cal-prev-month").dispatchAsync("click");
  const hlAfterMonthShift = vm.runInContext("calendarHighlightKey", context);
  await firstLegend.dispatchAsync("click");
  const hlAfterToggleOff = vm.runInContext("calendarHighlightKey", context);

  // 4) 詳細カードを開いて「閉じる」ボタンで非表示になること
  const octCell = getEl("monthly-calendar-body").children.find(c => c.dataset && c.dataset.date === "2026-10-15");
  await octCell.dispatchAsync("click");
  const detailOpened = getEl("monthly-calendar-detail").classList.contains("is-visible");
  await getEl("btn-cal-close-detail").dispatchAsync("click");
  const detailClosed = !getEl("monthly-calendar-detail").classList.contains("is-visible");

  // 5) 登録完了および履歴削除時に /api/calendar_shifts が自動再取得されること
  const countBefore = calendarFetchCount;
  vm.runInContext('analyzedShifts = [{ date: "2026-11-05", type: "有給", status: "paid_leave" }];', context);
  await getEl("btn-register").dispatchAsync("click");
  const countAfterRegister = calendarFetchCount;

  getEl("history-select").value = "h_nov";
  await getEl("btn-delete-history").dispatchAsync("click");
  const countAfterDelete = calendarFetchCount;

  console.log(JSON.stringify({
    emptyVisibleDec, tabAfterEmptyBtn, emptyVisibleNov,
    hlAfterClick, hlAfterMonthShift, hlAfterToggleOff,
    detailOpened, detailClosed,
    countBefore, countAfterRegister, countAfterDelete
  }));
""")
        self.assertTrue(res["emptyVisibleDec"])
        self.assertEqual(res["tabAfterEmptyBtn"], "import")
        self.assertFalse(res["emptyVisibleNov"])
        self.assertEqual(res["hlAfterClick"], "早A")
        self.assertEqual(res["hlAfterMonthShift"], "早A")
        self.assertIsNone(res["hlAfterToggleOff"])
        self.assertTrue(res["detailOpened"])
        self.assertTrue(res["detailClosed"])
        self.assertEqual(res["countAfterRegister"], res["countBefore"] + 1)
        self.assertEqual(res["countAfterDelete"], res["countAfterRegister"] + 1)

    def test_06_hourly_paid_leave_backend_api_summary_and_apple_sync(self):
        """時間有給APIの0.5時間正規化・summary自動付記/置換/除去・休み日エラー・Appleカレンダー同期・ICS補完を検証"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            hist_dir = os.path.join(tmpdir, "history")
            os.makedirs(hist_dir, exist_ok=True)
            with open(os.path.join(hist_dir, "reg_h1.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "id": "reg_h1",
                    "title": "2026年11月度",
                    "registered": True,
                    "registered_at": "2026-11-01 09:00:00",
                    "shifts": [
                        {"date": "2026-11-10", "type": "日", "status": "work", "start_time": "08:30", "end_time": "17:30", "summary": "[日] (08:30〜17:30)"},
                        {"date": "2026-11-11", "type": "休", "status": "holiday", "is_holiday": True, "summary": "休み"}
                    ]
                }, f)

            with patch.object(shift_app, "HISTORY_DIR", hist_dir), \
                 patch.object(shift_app, "CONFIG_PATH", cfg_path), \
                 patch.object(shift_app, "get_local_ip", return_value="127.0.0.1"), \
                 patch.object(shift_app, "register_to_apple_calendar", return_value=(1, "OK")) as mock_reg:
                # 1) 1.5時間設定＋Appleカレンダー同期ON
                r1 = _make_mock_handler(
                    "/api/calendar_shifts/hourly_leave",
                    method="POST",
                    body_dict={
                        "history_id": "reg_h1",
                        "date": "2026-11-10",
                        "hourly_paid_leave": 1.5,
                        "sync_apple_calendar": True,
                        "calendar_name": "シフトカレンダー"
                    },
                )
                self.assertEqual(r1["status"], 200)
                self.assertTrue(r1["data"]["success"])
                self.assertTrue(r1["data"]["apple_calendar_synced"])
                self.assertEqual(r1["data"]["shift"]["hourly_paid_leave"], 1.5)
                self.assertEqual(r1["data"]["shift"]["summary"], "[日] (08:30〜17:30)（時間有給1.5h）")
                self.assertEqual(mock_reg.call_count, 1)

                # 2) 2.0時間へ変更しても二重付記されず置換される
                r2 = _make_mock_handler(
                    "/api/calendar_shifts/hourly_leave",
                    method="POST",
                    body_dict={
                        "history_id": "reg_h1",
                        "date": "2026-11-10",
                        "hourly_paid_leave": 2.0,
                        "sync_apple_calendar": False
                    },
                )
                self.assertEqual(r2["status"], 200)
                self.assertEqual(r2["data"]["shift"]["summary"], "[日] (08:30〜17:30)（時間有給2h）")

                # 3) 0時間へ戻すと末尾付記が除去される
                r3 = _make_mock_handler(
                    "/api/calendar_shifts/hourly_leave",
                    method="POST",
                    body_dict={
                        "history_id": "reg_h1",
                        "date": "2026-11-10",
                        "hourly_paid_leave": 0,
                        "sync_apple_calendar": False
                    },
                )
                self.assertEqual(r3["status"], 200)
                self.assertEqual(r3["data"]["shift"]["hourly_paid_leave"], 0.0)
                self.assertEqual(r3["data"]["shift"]["summary"], "[日] (08:30〜17:30)")

                # 4) 休みの日には設定できず400エラー
                r4 = _make_mock_handler(
                    "/api/calendar_shifts/hourly_leave",
                    method="POST",
                    body_dict={
                        "history_id": "reg_h1",
                        "date": "2026-11-11",
                        "hourly_paid_leave": 1.0
                    },
                )
                self.assertEqual(r4["status"], 400)

                # 5) build_apple_calendar_script / create_ics が未付記summaryでも安全補完する
                raw_shift = [{
                    "date": "2026-11-10",
                    "type": "日",
                    "status": "work",
                    "start_time": "08:30",
                    "end_time": "17:30",
                    "summary": "[日] (08:30〜17:30)",
                    "hourly_paid_leave": 0.5
                }]
                script_str, _ = shift_app.build_apple_calendar_script(raw_shift)
                self.assertIn("[日] (08:30〜17:30)（時間有給0.5h）", script_str)
                ics_str = shift_app.create_ics(raw_shift)
                self.assertIn("SUMMARY:[日] (08:30〜17:30)（時間有給0.5h）", ics_str)

    def test_07_hourly_paid_leave_ui_8h_conversion_exact_day_and_detail_save(self):
        """8時間換算・0.5時間刻み・使い切り時の「X日 0時間」表記・詳細カードからの時間有給保存を検証"""
        res = self._run_node(r"""
  // ケースA: 終日有給1日 + 時間有給(1.5h + 2.5h + 4h = 8h) = ちょうど 2日 0時間（使い切り表示）
  vm.runInContext(`
    calendarShiftsByDate = {
      "2026-11-01": { date: "2026-11-01", type: "有給", status: "paid_leave", is_paid_leave: true, summary: "有給休暇", history_id: "h1" },
      "2026-11-02": { date: "2026-11-02", type: "日", status: "work", hourly_paid_leave: 1.5, summary: "[日]（時間有給1.5h）", history_id: "h1" },
      "2026-11-03": { date: "2026-11-03", type: "日", status: "work", hourly_paid_leave: 2.5, summary: "[日]（時間有給2.5h）", history_id: "h1" },
      "2026-11-04": { date: "2026-11-04", type: "日", status: "work", hourly_paid_leave: 4.0, summary: "[日]（時間有給4h）", history_id: "h1" }
    };
    paidLeaveConfig = { startMonth: 4, startDay: 1, annualDays: 20, hoursPerDay: 8 };
    calendarViewYear = 2026;
    calendarViewMonth = 11;
    renderMonthlyCalendarView();
  `, context);

  const exactUsedUp = {
    monthlyPaid: getEl("cal-summary-paid-days").textContent,
    annualUsed: getEl("cal-annual-leave-used").textContent,
    annualRemaining: getEl("cal-annual-leave-remaining").textContent
  };

  // ケースB: 終日有給1日 + 時間有給 1.5時間 → 取得 1日 1.5時間 / 残り 18日 6.5時間
  vm.runInContext(`
    calendarShiftsByDate = {
      "2026-11-01": { date: "2026-11-01", type: "有給", status: "paid_leave", is_paid_leave: true, summary: "有給休暇", history_id: "h1" },
      "2026-11-02": { date: "2026-11-02", type: "日", status: "work", hourly_paid_leave: 1.5, summary: "[日]（時間有給1.5h）", history_id: "h1" }
    };
    renderMonthlyCalendarView();
  `, context);

  const fractional = {
    monthlyPaid: getEl("cal-summary-paid-days").textContent,
    annualUsed: getEl("cal-annual-leave-used").textContent,
    annualRemaining: getEl("cal-annual-leave-remaining").textContent
  };

  // ケースC: 終日有給日クリックでは時間有給編集UIが非表示、出勤日クリックでは表示され保存APIが呼ばれる
  const cellPaid = getEl("monthly-calendar-body").children.find(c => c.dataset && c.dataset.date === "2026-11-01");
  await cellPaid.dispatchAsync("click");
  const hourlyBoxOnPaidDay = getEl("cal-detail-hourly-box").classList.contains("is-visible");

  // 元の calendarShiftsData["2026-10-15"]（出勤日）を表示してクリック → 1.5h保存
  vm.runInContext("calendarViewYear = 2026; calendarViewMonth = 10;", context);
  await context.fetchRegisteredCalendarShifts();
  const cellWork = getEl("monthly-calendar-body").children.find(c => c.dataset && c.dataset.date === "2026-10-15");
  await cellWork.dispatchAsync("click");
  const hourlyBoxOnWorkDay = getEl("cal-detail-hourly-box").classList.contains("is-visible");

  getEl("cal-detail-hourly-select").value = "1.5";
  getEl("cal-detail-hourly-sync-apple").checked = true;
  await getEl("btn-cal-save-hourly-leave").dispatchAsync("click");

  console.log(JSON.stringify({
    exactUsedUp,
    fractional,
    hourlyBoxOnPaidDay,
    hourlyBoxOnWorkDay,
    lastHourlyLeaveRequest,
    afterSaveMonthlyPaid: getEl("cal-summary-paid-days").textContent
  }));
""")
        self.assertEqual(res["exactUsedUp"]["monthlyPaid"], "2日 0時間")
        self.assertEqual(res["exactUsedUp"]["annualUsed"], "2日 0時間")
        self.assertEqual(res["exactUsedUp"]["annualRemaining"], "18日 0時間")

        self.assertEqual(res["fractional"]["monthlyPaid"], "1日 1.5時間")
        self.assertEqual(res["fractional"]["annualUsed"], "1日 1.5時間")
        self.assertEqual(res["fractional"]["annualRemaining"], "18日 6.5時間")

        self.assertFalse(res["hourlyBoxOnPaidDay"])
        self.assertTrue(res["hourlyBoxOnWorkDay"])
        self.assertEqual(res["lastHourlyLeaveRequest"]["date"], "2026-10-15")
        self.assertEqual(res["lastHourlyLeaveRequest"]["hourly_paid_leave"], 1.5)
        self.assertTrue(res["lastHourlyLeaveRequest"]["sync_apple_calendar"])
        self.assertEqual(res["afterSaveMonthlyPaid"], "0日 1.5時間")

    def test_08_import_table_hourly_leave_sync_and_reset(self):
        """読み込みタブの調整テーブルで時間有給変更時の登録名・集計・プレビュー連動と休み変更時リセットを検証"""
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
    this._controls = {};
  }
  get className() { return this.classList.toString(); }
  set className(v) { this.classList._syncFromString(v); }
  get innerHTML() { return this._innerHTML; }
  set innerHTML(v) {
    this._innerHTML = String(v || "");
    if (!v) {
      this.children = [];
      this._controls = {};
      return;
    }
    if (this.tagName === "TR" && this._innerHTML.includes("shift-hourly-leave")) {
      const idx = String(this.dataset.idx ?? "0");
      const makeCtrl = (cls, tag, initVal, disabled) => {
        const el = new MockElement(tag);
        el.className = cls;
        el.dataset.idx = idx;
        el.value = initVal;
        el.disabled = disabled;
        el.parentNode = this;
        el.closest = (sel) => (sel === "tr" ? this : null);
        return el;
      };
      const isDisabled = this._innerHTML.includes('class="table-select shift-hourly-leave"') && /shift-hourly-leave[^>]*disabled/.test(this._innerHTML);
      const sumMatch = this._innerHTML.match(/class="input-text shift-summary"[^>]*value="([^"]*)"/);
      this._controls[".shift-select"] = makeCtrl("shift-select", "select", "日", false);
      this._controls[".shift-time-start"] = makeCtrl("shift-time-start", "input", "08:30", isDisabled);
      this._controls[".shift-time-end"] = makeCtrl("shift-time-end", "input", "17:30", isDisabled);
      this._controls[".shift-hourly-leave"] = makeCtrl("shift-hourly-leave", "select", "0", isDisabled);
      this._controls[".shift-summary"] = makeCtrl("shift-summary", "input", sumMatch ? sumMatch[1] : "", false);
      this._controls[".shift-check"] = makeCtrl("shift-check", "input", "", false);
      this._controls[".shift-check"].checked = true;
    }
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
    for (const fn of list) await fn(ev);
  }
  querySelector(sel) {
    return this._controls[sel] || null;
  }
  querySelectorAll(sel) {
    const res = [];
    for (const child of this.children) {
      if (child._controls && child._controls[sel]) res.push(child._controls[sel]);
    }
    return res;
  }
  contains(node) { return node === this || this.children.includes(node); }
  scrollIntoView() {}
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
}

const elements = new Map();
function getEl(id) {
  if (!elements.has(id)) elements.set(id, new MockElement("div", id));
  return elements.get(id);
}

const documentMock = {
  hidden: false,
  activeElement: null,
  documentElement: new MockElement("html"),
  getElementById: (id) => getEl(id),
  createElement: (tag) => new MockElement(tag),
  querySelectorAll: () => [],
  addEventListener: () => {}
};

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
  fetch: async (url) => {
    if (url === "/api/config") {
      return {
        ok: true,
        json: async () => ({
          api_key: "TEST",
          default_name: "皿田",
          calendar_name: "シフトカレンダー",
          theme: "light",
          server_version: "2026.11.21.v3",
          paid_leave_start_month: 4,
          paid_leave_start_day: 1,
          paid_leave_annual_days: 20,
          paid_leave_hours_per_day: 8,
          time_definitions: { "早A": { start: "06:00", end: "15:00" }, "日": { start: "08:30", end: "17:30" } }
        })
      };
    }
    if (url === "/api/calendar_shifts") {
      return { ok: true, json: async () => ({ success: true, shifts_by_date: {}, available_months: [], registered_histories_count: 0 }) };
    }
    if (url === "/api/history") return { ok: true, json: async () => ({ history: [] }) };
    if (url === "/api/get_preloaded") return { ok: true, json: async () => ({ has_image: false }) };
    return { ok: true, json: async () => ({ success: true }) };
  }
};

vm.createContext(context);
vm.runInContext(scriptMatch[1], context);

(async () => {
  await new Promise(r => setImmediate(r));
  await new Promise(r => setImmediate(r));

  context.renderResult({
    target_name: "皿田",
    shifts: [
      { date: "2026-11-10", day_of_week: "火", type: "日", status: "work", start_time: "08:30", end_time: "17:30", summary: "[日] (08:30〜17:30)" },
      { date: "2026-11-11", day_of_week: "水", type: "休", status: "holiday", is_holiday: true, summary: "休み" }
    ]
  });

  const rows = getEl("shifts-tbody").children;
  const workRow = rows[0];
  const holRow = rows[1];
  const workHourlyDisabledInitially = workRow.querySelector(".shift-hourly-leave").disabled;
  const holHourlyDisabledInitially = holRow.querySelector(".shift-hourly-leave").disabled;

  // 1) 出勤行の時間有給を 1.5時間 に変更
  const selHourly = workRow.querySelector(".shift-hourly-leave");
  selHourly.value = "1.5";
  await selHourly.dispatchAsync("change");

  const afterSetHourly = {
    hourlyVal: vm.runInContext("analyzedShifts[0].hourly_paid_leave", context),
    summaryModel: vm.runInContext("analyzedShifts[0].summary", context),
    summaryInput: workRow.querySelector(".shift-summary").value,
    metricsHtml: getEl("monthly-metrics-container").children.map(c => c.innerHTML).join("\n"),
    calBodyHtml: getEl("calendar-body").children.map(c => c.innerHTML).join("\n")
  };

  // 2) 同じ行のシフト区分を別の出勤（早A）へ変更しても時間有給1.5hが維持・再付記される
  const selShift = workRow.querySelector(".shift-select");
  selShift.value = "早A";
  await selShift.dispatchAsync("change");

  const afterChangeToEarlyA = {
    hourlyVal: vm.runInContext("analyzedShifts[0].hourly_paid_leave", context),
    summaryModel: vm.runInContext("analyzedShifts[0].summary", context),
    summaryInput: workRow.querySelector(".shift-summary").value
  };

  // 3) 同じ行を「休」へ変更すると時間有給が0へリセットされセレクトもdisabledになる
  selShift.value = "休";
  await selShift.dispatchAsync("change");

  const afterChangeToHoliday = {
    hourlyVal: vm.runInContext("analyzedShifts[0].hourly_paid_leave", context),
    summaryModel: vm.runInContext("analyzedShifts[0].summary", context),
    summaryInput: workRow.querySelector(".shift-summary").value,
    hourlySelectValue: selHourly.value,
    hourlySelectDisabled: selHourly.disabled,
    metricsHtml: getEl("monthly-metrics-container").children.map(c => c.innerHTML).join("\n")
  };

  console.log(JSON.stringify({
    workHourlyDisabledInitially,
    holHourlyDisabledInitially,
    afterSetHourly,
    afterChangeToEarlyA,
    afterChangeToHoliday
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

        self.assertFalse(res["workHourlyDisabledInitially"])
        self.assertTrue(res["holHourlyDisabledInitially"])

        self.assertEqual(res["afterSetHourly"]["hourlyVal"], 1.5)
        self.assertEqual(res["afterSetHourly"]["summaryModel"], "[日] (08:30〜17:30)（時間有給1.5h）")
        self.assertEqual(res["afterSetHourly"]["summaryInput"], "[日] (08:30〜17:30)（時間有給1.5h）")
        self.assertIn("0日 1.5時間", res["afterSetHourly"]["metricsHtml"])
        self.assertIn("時間有給 1.5h", res["afterSetHourly"]["calBodyHtml"])

        self.assertEqual(res["afterChangeToEarlyA"]["hourlyVal"], 1.5)
        self.assertEqual(res["afterChangeToEarlyA"]["summaryModel"], "[早A] (06:00〜15:00)（時間有給1.5h）")
        self.assertEqual(res["afterChangeToEarlyA"]["summaryInput"], "[早A] (06:00〜15:00)（時間有給1.5h）")

        self.assertEqual(res["afterChangeToHoliday"]["hourlyVal"], 0)
        self.assertEqual(res["afterChangeToHoliday"]["summaryModel"], "休み")
        self.assertEqual(res["afterChangeToHoliday"]["summaryInput"], "休み")
        self.assertEqual(res["afterChangeToHoliday"]["hourlySelectValue"], "0")
        self.assertTrue(res["afterChangeToHoliday"]["hourlySelectDisabled"])
        self.assertIn("0日 0時間", res["afterChangeToHoliday"]["metricsHtml"])

    def test_09_monthly_calendar_displays_apple_calendar_summary(self):
        """カレンダータブのシフト表示がAppleカレンダー登録名と一致し、区分カラーと時間有給別バッジが維持されること"""
        res = self._run_node(r"""
  vm.runInContext(`
    calendarShiftsByDate = {
      "2026-11-01": { date: "2026-11-01", type: "早A", status: "work", start_time: "06:00", end_time: "15:00", summary: "[早A] (06:00〜15:00)", history_id: "h1" },
      "2026-11-02": { date: "2026-11-02", type: "日", status: "work", start_time: "08:30", end_time: "17:30", summary: "[日] (08:30〜17:30)", hourly_paid_leave: 1.5, history_id: "h1" },
      "2026-11-03": { date: "2026-11-03", type: "休", status: "holiday", is_holiday: true, summary: "休み", history_id: "h1" },
      "2026-11-04": { date: "2026-11-04", type: "有給", status: "paid_leave", is_paid_leave: true, summary: "有給休暇", history_id: "h1" },
      "2026-11-05": { date: "2026-11-05", type: "早B", status: "work", start_time: "06:30", end_time: "15:30", summary: "[早B] 研修", history_id: "h1" },
      "2026-11-06": { date: "2026-11-06", type: "早C", status: "work", start_time: "07:00", end_time: "16:00", history_id: "h1" }
    };
    paidLeaveConfig = { startMonth: 4, startDay: 1, annualDays: 20, hoursPerDay: 8 };
    calendarViewYear = 2026;
    calendarViewMonth = 11;
    renderMonthlyCalendarView();
  `, context);

  const cells = getEl("monthly-calendar-body").children;
  const htmlByDate = {};
  for (const d of ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]) {
    const c = cells.find(x => x.dataset && x.dataset.date === d);
    htmlByDate[d] = c ? c.innerHTML : "";
  }
  console.log(JSON.stringify(htmlByDate));
""")
        # 1) 通常出勤: Appleカレンダー登録名表示・workクラス・data-key維持・重複時刻行なし
        self.assertIn("cal-event-capsule work is-apple-summary", res["2026-11-01"])
        self.assertIn('data-key="早A"', res["2026-11-01"])
        self.assertIn("[早A] (06:00〜15:00)", res["2026-11-01"])
        self.assertNotIn("cal-capsule-time", res["2026-11-01"])

        # 2) 時間有給あり出勤: 登録名に（時間有給1.5h）付記＋別バッジも維持
        self.assertIn("[日] (08:30〜17:30)（時間有給1.5h）", res["2026-11-02"])
        self.assertIn("時間有給 1.5h", res["2026-11-02"])
        self.assertIn("cal-hourly-leave-pill", res["2026-11-02"])

        # 3) 休み・有給休暇: 区分クラス維持・「終日」行なし
        self.assertIn("cal-event-capsule holiday is-apple-summary", res["2026-11-03"])
        self.assertIn(">休み<", res["2026-11-03"])
        self.assertNotIn("終日", res["2026-11-03"])

        self.assertIn("cal-event-capsule paid is-apple-summary", res["2026-11-04"])
        self.assertIn(">有給休暇<", res["2026-11-04"])
        self.assertNotIn("終日", res["2026-11-04"])

        # 4) カスタム登録名
        self.assertIn("[早B] 研修", res["2026-11-05"])

        # 5) summary未設定時のフォールバック
        self.assertIn("[早C] (07:00〜16:00)", res["2026-11-06"])

    def test_10_calendar_shift_tones_and_multiline_summary(self):
        """カレンダータブのシフト記号別時間帯カラーと改行表示（[記号]/(時間)/（時間有給Xh））を検証"""
        res = self._run_node(r"""
  vm.runInContext(`
    masterTimeDefs = {
      "早A": { start: "06:00", end: "15:00" },
      "早B": { start: "06:30", end: "15:30" },
      "早C": { start: "07:00", end: "16:00" },
      "早D": { start: "08:00", end: "17:00" },
      "日":  { start: "08:30", end: "17:30" },
      "遅A": { start: "09:00", end: "18:00" },
      "遅B": { start: "09:30", end: "18:30" },
      "遅C": { start: "10:00", end: "19:00" }
    };
    renderCalendarViewDefs(masterTimeDefs);
    calendarShiftsByDate = {
      "2026-11-01": { date: "2026-11-01", type: "早A", status: "work", start_time: "06:00", end_time: "15:00", summary: "[早A] (06:00〜15:00)", hourly_paid_leave: 1.5, history_id: "h1" },
      "2026-11-02": { date: "2026-11-02", type: "早B", status: "work", start_time: "06:30", end_time: "15:30", summary: "[早B] (06:30〜15:30)", history_id: "h1" },
      "2026-11-03": { date: "2026-11-03", type: "早C", status: "work", start_time: "07:00", end_time: "16:00", summary: "[早C] (07:00〜16:00)", history_id: "h1" },
      "2026-11-04": { date: "2026-11-04", type: "早D", status: "work", start_time: "08:00", end_time: "17:00", summary: "[早D] (08:00〜17:00)", history_id: "h1" },
      "2026-11-05": { date: "2026-11-05", type: "日",  status: "work", start_time: "08:30", end_time: "17:30", summary: "[日] (08:30〜17:30)", history_id: "h1" },
      "2026-11-06": { date: "2026-11-06", type: "遅A", status: "work", start_time: "09:00", end_time: "18:00", summary: "[遅A] (09:00〜18:00)", history_id: "h1" },
      "2026-11-07": { date: "2026-11-07", type: "遅B", status: "work", start_time: "09:30", end_time: "18:30", summary: "[遅B] (09:30〜18:30)", history_id: "h1" },
      "2026-11-08": { date: "2026-11-08", type: "遅C", status: "work", start_time: "10:00", end_time: "19:00", summary: "[遅C] (10:00〜19:00)", history_id: "h1" },
      "2026-11-09": { date: "2026-11-09", type: "カスタム早", status: "work", start_time: "06:00", end_time: "15:00", summary: "[カスタム早] (06:00〜15:00)", history_id: "h1" },
      "2026-11-10": { date: "2026-11-10", type: "カスタム遅", status: "work", start_time: "11:00", end_time: "20:00", summary: "[カスタム遅] (11:00〜20:00)", history_id: "h1" }
    };
    paidLeaveConfig = { startMonth: 4, startDay: 1, annualDays: 20, hoursPerDay: 8 };
    calendarViewYear = 2026;
    calendarViewMonth = 11;
    renderMonthlyCalendarView();
  `, context);

  const cells = getEl("monthly-calendar-body").children;
  const htmlByDate = {};
  for (let d = 1; d <= 10; d++) {
    const key = "2026-11-" + String(d).padStart(2, "0");
    const c = cells.find(x => x.dataset && x.dataset.date === key);
    htmlByDate[key] = c ? c.innerHTML : "";
  }

  // 詳細カードのトーン確認
  const day1 = cells.find(x => x.dataset && x.dataset.date === "2026-11-01");
  await day1.dispatchAsync("click");
  const detailHtml = getEl("cal-detail-body").innerHTML;

  // 凡例のカラードット確認
  const legendHtml = getEl("cal-view-defs-container").children.map(el => el.innerHTML);

  console.log(JSON.stringify({
    htmlByDate,
    detailHtml,
    legendHtml,
    lines3: context.formatCalendarSummaryLines("[早A] (06:00〜15:00)（時間有給1.5h）"),
    lines2: context.formatCalendarSummaryLines("[早A] (06:00〜15:00)"),
    lines1: context.formatCalendarSummaryLines("休み")
  }));
""")
        expected_tones = {
            "2026-11-01": "early-a",
            "2026-11-02": "early-b",
            "2026-11-03": "early-c",
            "2026-11-04": "early-d",
            "2026-11-05": "day",
            "2026-11-06": "late-a",
            "2026-11-07": "late-b",
            "2026-11-08": "late-c",
            "2026-11-09": "early-a",
            "2026-11-10": "late-c",
        }
        for date_key, tone in expected_tones.items():
            self.assertIn(f'data-shift-tone="{tone}"', res["htmlByDate"][date_key])

        # 3行改行のHTML構造検証: [早A] / (06:00〜15:00) / （時間有給1.5h）
        self.assertEqual(res["lines3"], ["[早A]", "(06:00〜15:00)", "（時間有給1.5h）"])
        self.assertEqual(res["lines2"], ["[早A]", "(06:00〜15:00)"])
        self.assertEqual(res["lines1"], ["休み"])

        day1_html = res["htmlByDate"]["2026-11-01"]
        self.assertIn('<span class="cal-summary-line cal-summary-line-main">[早A]</span>', day1_html)
        self.assertIn('<span class="cal-summary-line cal-summary-line-sub">(06:00〜15:00)</span>', day1_html)
        self.assertIn('<span class="cal-summary-line cal-summary-line-hourly">（時間有給1.5h）</span>', day1_html)

        # 詳細カード・凡例にもトーンが反映されていること
        self.assertIn('data-shift-tone="early-a"', res["detailHtml"])
        self.assertTrue(any('legend-tone-dot" data-shift-tone="early-a"' in h for h in res["legendHtml"]))
        self.assertTrue(any('legend-tone-dot" data-shift-tone="late-c"' in h for h in res["legendHtml"]))

        # CSSに8トーンすべてのライト/ダーク変数とセレクタが定義されていること
        css_path = os.path.join(PROJECT_ROOT, "static", "styles.css")
        with open(css_path, "r", encoding="utf-8") as f:
            css_text = f.read()
        for tone in ["early-a", "early-b", "early-c", "early-d", "day", "late-a", "late-b", "late-c"]:
            self.assertGreaterEqual(css_text.count(f"--shift-tone-{tone}-bg:"), 2)
            self.assertIn(f'.cal-event-capsule.work[data-shift-tone="{tone}"]', css_text)

    def test_11_calendar_tone_edge_cases_multiline_escape_canvas_and_legend_scope(self):
        """改行バリエーション/XSSエスケープ・Canvas色分け・時刻境界/不正値フォールバック・凡例ドット範囲を検証"""
        res = self._run_node(r"""
  // 1) formatCalendarSummaryLines のバリエーション
  const lineCases = {
    noTimeHourly: context.formatCalendarSummaryLines("[日]（時間有給1.5h）"),
    customHourly: context.formatCalendarSummaryLines("[早B] 研修（時間有給2h）"),
    halfWidthHourly: context.formatCalendarSummaryLines("[早A] (06:00〜15:00)(時間有給1h)"),
    noBracketTime: context.formatCalendarSummaryLines("早A (06:00〜15:00)"),
    emptyStr: context.formatCalendarSummaryLines(""),
    nullVal: context.formatCalendarSummaryLines(null)
  };

  // 3) resolveShiftTone の境界値・masterTimeDefs補完・不正値フォールバック
  vm.runInContext(`
    masterTimeDefs = {
      "早A": { start: "06:00", end: "15:00" },
      "日":  { start: "08:30", end: "17:30" },
      "遅C": { start: "10:00", end: "19:00" },
      "特勤": { start: "09:30", end: "18:30" }
    };
  `, context);

  const boundaryCases = {
    "06:14": context.resolveShiftTone("X", "06:14"),
    "06:15": context.resolveShiftTone("X", "06:15"),
    "06:44": context.resolveShiftTone("X", "06:44"),
    "06:45": context.resolveShiftTone("X", "06:45"),
    "07:29": context.resolveShiftTone("X", "07:29"),
    "07:30": context.resolveShiftTone("X", "07:30"),
    "08:14": context.resolveShiftTone("X", "08:14"),
    "08:15": context.resolveShiftTone("X", "08:15"),
    "08:44": context.resolveShiftTone("X", "08:44"),
    "08:45": context.resolveShiftTone("X", "08:45"),
    "09:14": context.resolveShiftTone("X", "09:14"),
    "09:15": context.resolveShiftTone("X", "09:15"),
    "09:44": context.resolveShiftTone("X", "09:44"),
    "09:45": context.resolveShiftTone("X", "09:45"),
    fromMasterDef: context.resolveShiftTone({ type: "特勤", status: "work" }),
    invalidEmpty: context.resolveShiftTone("未知", ""),
    invalidRange: context.resolveShiftTone("未知", "25:99"),
    invalidText: context.resolveShiftTone("未知", "invalid"),
    nullInput: context.resolveShiftTone(null),
    holidayObj: context.resolveShiftTone({ type: "休", status: "holiday", is_holiday: true }),
    paidObj: context.resolveShiftTone({ type: "有給", status: "paid_leave", is_paid_leave: true })
  };

  // XSSエスケープ＆不明時刻セルの描画検証
  vm.runInContext(`
    calendarShiftsByDate = {
      "2026-11-01": { date: "2026-11-01", type: "早A", status: "work", start_time: "06:00", end_time: "15:00", summary: "[早A] <script>alert(1)</script>&test", history_id: "h1" },
      "2026-11-02": { date: "2026-11-02", type: "日", status: "work", start_time: "08:30", end_time: "17:30", summary: "[日] (08:30〜17:30)", hourly_paid_leave: 2, event: "避難訓練", memo: "印鑑持参", history_id: "h1" },
      "2026-11-03": { date: "2026-11-03", type: "遅C", status: "work", start_time: "10:00", end_time: "19:00", summary: "[遅C] (10:00〜19:00)", history_id: "h1" },
      "2026-11-04": { date: "2026-11-04", type: "休", status: "holiday", is_holiday: true, summary: "休み", history_id: "h1" },
      "2026-11-05": { date: "2026-11-05", type: "有給", status: "paid_leave", is_paid_leave: true, summary: "有給休暇", history_id: "h1" },
      "2026-11-06": { date: "2026-11-06", type: "未定義", status: "work", summary: "[未定義] 特別", history_id: "h1" }
    };
    calendarViewYear = 2026;
    calendarViewMonth = 11;
    renderMonthlyCalendarView();
  `, context);

  const cells = getEl("monthly-calendar-body").children;
  const xssCellHtml = cells.find(c => c.dataset && c.dataset.date === "2026-11-01").innerHTML;
  const unknownToneCellHtml = cells.find(c => c.dataset && c.dataset.date === "2026-11-06").innerHTML;

  // 2) renderMonthlyCalendarCanvas のカレンダータブ準拠描画検証
  const rectFills = [];
  const strokeColors = [];
  const textDraws = [];
  let roundedPathCount = 0;
  let arcCount = 0;
  const origCreateElement = documentMock.createElement;
  documentMock.createElement = (tag) => {
    if (String(tag).toLowerCase() === "canvas") {
      const ctx = {
        fillStyle: "",
        strokeStyle: "",
        lineWidth: 1,
        font: "",
        textAlign: "left",
        globalAlpha: 1,
        scale() {},
        save() {},
        restore() {},
        clip() {},
        beginPath() {},
        moveTo() {},
        lineTo() {},
        quadraticCurveTo() { roundedPathCount++; },
        closePath() {},
        arc() { arcCount++; },
        fill() { rectFills.push({ color: this.fillStyle }); },
        stroke() { strokeColors.push(this.strokeStyle); },
        fillRect(x, y, w, h) { rectFills.push({ color: this.fillStyle, x, y, w, h }); },
        strokeRect() { strokeColors.push(this.strokeStyle); },
        fillText(text) { textDraws.push({ text: String(text), color: this.fillStyle }); }
      };
      return { width: 0, height: 0, getContext: () => ctx, toDataURL: () => "data:image/png;base64," };
    }
    return origCreateElement(tag);
  };
  context.renderMonthlyCalendarCanvas(2026, 11);
  documentMock.createElement = origCreateElement;

  // 4) 凡例ドットの影響範囲分離（カレンダータブあり / 読み込みタブなし）
  vm.runInContext(`
    renderCalendarViewDefs(masterTimeDefs);
    renderMasterDefs(masterTimeDefs);
  `, context);
  const calLegendHtml = getEl("cal-view-defs-container").children.map(el => el.innerHTML);
  const importLegendHtml = getEl("defs-container").children.map(el => el.innerHTML);

  console.log(JSON.stringify({
    lineCases,
    boundaryCases,
    xssCellHtml,
    unknownToneCellHtml,
    rectFillColors: rectFills.map(r => r.color),
    strokeColors,
    roundedPathCount,
    arcCount,
    textDraws,
    calLegendHtml,
    importLegendHtml
  }));
""")
        # 1) 改行バリエーション & XSSエスケープ
        self.assertEqual(res["lineCases"]["noTimeHourly"], ["[日]", "（時間有給1.5h）"])
        self.assertEqual(res["lineCases"]["customHourly"], ["[早B]", "研修", "（時間有給2h）"])
        self.assertEqual(res["lineCases"]["halfWidthHourly"], ["[早A]", "(06:00〜15:00)", "(時間有給1h)"])
        self.assertEqual(res["lineCases"]["noBracketTime"], ["早A", "(06:00〜15:00)"])
        self.assertEqual(res["lineCases"]["emptyStr"], [])
        self.assertEqual(res["lineCases"]["nullVal"], [])
        self.assertNotIn("<script>", res["xssCellHtml"])
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;&amp;test", res["xssCellHtml"])

        # 2) Canvas 描画がカレンダータブ（ライトモード）と同一パレット・角丸カプセル・ピルで描画されること
        rect_colors = set(res["rectFillColors"])
        for expected_bg in [
            "#ffede3",  # 早A
            "#e8eeff",  # 日
            "#e6ebf5",  # 遅C
            "#f2f2f7",  # 休み（--shift-holiday-bg）
            "#ffebee",  # 有給・時間有給ピル（--shift-paid-bg）
            "#fff3e0",  # 未定義出勤（--shift-work-bg）
            "#e6f7f5",  # 行事予定ピル（--event-badge-bg）
            "rgba(142, 142, 147, 0.12)",  # メモインジケーター
        ]:
            self.assertIn(expected_bg, rect_colors)
        stroke_set = set(res["strokeColors"])
        for expected_border in ["#f8b494", "#a3b8fa", "#9fb0d1", "#d1d1d6", "#ffcdd2", "#ffcc80", "#99e2d9"]:
            self.assertIn(expected_border, stroke_set)
        self.assertGreater(res["roundedPathCount"], 0)
        self.assertGreaterEqual(res["arcCount"], 3)  # メトリクスカプセルの色ドット3種

        text_color_map = {d["text"]: d["color"] for d in res["textDraws"]}
        self.assertEqual(text_color_map.get("[早A]"), "#a13a10")
        self.assertEqual(text_color_map.get("[日]"), "#1d429e")
        self.assertEqual(text_color_map.get("(08:30〜17:30)"), "#1d429e")
        self.assertEqual(text_color_map.get("[遅C]"), "#1e3358")
        self.assertEqual(text_color_map.get("休み"), "#48484a")
        self.assertEqual(text_color_map.get("有給休暇"), "#c2185b")
        self.assertEqual(text_color_map.get("[未定義]"), "#b26a00")
        self.assertEqual(text_color_map.get("時間有給 2h"), "#c2185b")
        self.assertEqual(text_color_map.get("避難訓練"), "#0f6b63")
        self.assertEqual(text_color_map.get("印鑑持参"), "#636366")

        # 3) 時刻境界値・補完・不正値フォールバック
        expected_boundaries = {
            "06:14": "early-a", "06:15": "early-b",
            "06:44": "early-b", "06:45": "early-c",
            "07:29": "early-c", "07:30": "early-d",
            "08:14": "early-d", "08:15": "day",
            "08:44": "day",     "08:45": "late-a",
            "09:14": "late-a",  "09:15": "late-b",
            "09:44": "late-b",  "09:45": "late-c",
            "fromMasterDef": "late-b",
            "invalidEmpty": "",
            "invalidRange": "",
            "invalidText": "",
            "nullInput": "",
            "holidayObj": "holiday",
            "paidObj": "paid",
        }
        for k, expected in expected_boundaries.items():
            self.assertEqual(res["boundaryCases"][k], expected, msg=f"key={k}")
        self.assertNotIn("data-shift-tone=", res["unknownToneCellHtml"])

        # 4) 凡例ドットの影響範囲分離
        self.assertTrue(any('data-shift-tone="holiday"' in h for h in res["calLegendHtml"]))
        self.assertTrue(any('data-shift-tone="paid"' in h for h in res["calLegendHtml"]))
        self.assertFalse(any("legend-tone-dot" in h for h in res["importLegendHtml"]))

    def test_12_share_canvas_palette_sync_summary_height_outside_and_truncation(self):
        """共有CanvasのCSS色同期・ヘッダー集計/月外除外・行高さ動的拡張・空月・月外半透明・長文省略を検証"""
        import re

        # 1) static/styles.css の :root（ライトモード）CSS変数を抽出
        styles_path = os.path.join(PROJECT_ROOT, "static", "styles.css")
        with open(styles_path, "r", encoding="utf-8") as f:
            css_text = f.read()
        root_match = re.search(r":root\s*\{([^}]*)\}", css_text, re.DOTALL)
        self.assertIsNotNone(root_match, ":root ブロックが見つかりません")
        css_vars = {}
        for m in re.finditer(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", root_match.group(1)):
            css_vars[m.group(1).strip()] = m.group(2).strip()

        res = self._run_node(r"""
  // 1) JS側のパレット定義を取得
  const palettes = vm.runInContext(`({
    tonePalette: SHIFT_TONE_CANVAS_PALETTE,
    canvasColors: CALENDAR_CANVAS_COLORS
  })`, context);

  function createTrackingCanvasFactory(withMeasureText) {
    const records = [];
    const origCreate = documentMock.createElement;
    documentMock.createElement = (tag) => {
      if (String(tag).toLowerCase() === "canvas") {
        const alphaStack = [];
        let saveCount = 0;
        let restoreCount = 0;
        const textDraws = [];
        const ctx = {
          fillStyle: "",
          strokeStyle: "",
          lineWidth: 1,
          font: "",
          textAlign: "left",
          globalAlpha: 1,
          scale() {},
          save() { saveCount++; alphaStack.push(this.globalAlpha); },
          restore() { restoreCount++; if (alphaStack.length > 0) this.globalAlpha = alphaStack.pop(); },
          clip() {},
          beginPath() {},
          moveTo() {},
          lineTo() {},
          quadraticCurveTo() {},
          closePath() {},
          arc() {},
          fill() {},
          stroke() {},
          fillRect() {},
          strokeRect() {},
          fillText(text) {
            textDraws.push({ text: String(text), color: this.fillStyle, alpha: this.globalAlpha });
          }
        };
        if (withMeasureText) {
          ctx.measureText = (str) => ({ width: String(str || "").length * 10 });
        }
        const canvasObj = {
          width: 0,
          height: 0,
          getContext: () => ctx,
          toDataURL: () => "data:image/png;base64,",
          _meta: () => ({ saveCount, restoreCount, finalAlpha: ctx.globalAlpha, textDraws })
        };
        records.push(canvasObj);
        return canvasObj;
      }
      return origCreate(tag);
    };
    return {
      records,
      restore: () => { documentMock.createElement = origCreate; }
    };
  }

  // 2) 空月（2026年12月：シフト0件）の描画
  vm.runInContext(`calendarShiftsByDate = {};`, context);
  let factory = createTrackingCanvasFactory(true);
  const emptyCanvas = context.renderMonthlyCalendarCanvas(2026, 12);
  factory.restore();
  const emptyMeta = emptyCanvas._meta();

  // 3) 当月＋月外混在・時間有給合算・密セル（3行サマリー＋時間有給＋行事＋メモ）＋長文テキスト
  const longEvent = "とても長い職場全体会議および防災訓練のお知らせテスト";
  const longMemo = "これはセル幅を確実に超過する非常に長いひとことメモの検証文字列です";
  vm.runInContext(`
    paidLeaveConfig.hoursPerDay = 8;
    calendarShiftsByDate = {
      "2026-11-30": { date: "2026-11-30", type: "早A", status: "work", start_time: "06:00", end_time: "15:00", summary: "[早A] (06:00〜15:00)", history_id: "h0" },
      "2026-12-01": { date: "2026-12-01", type: "日", status: "work", start_time: "08:30", end_time: "17:30", summary: "[日] (08:30〜17:30) （時間有給2h）", hourly_paid_leave: 2, event: ${JSON.stringify(longEvent)}, memo: ${JSON.stringify(longMemo)}, history_id: "h1" },
      "2026-12-02": { date: "2026-12-02", type: "遅B", status: "work", start_time: "09:30", end_time: "18:30", summary: "[遅B] (09:30〜18:30)", history_id: "h1" },
      "2026-12-03": { date: "2026-12-03", type: "休", status: "holiday", is_holiday: true, summary: "休み", history_id: "h1" },
      "2026-12-04": { date: "2026-12-04", type: "有給", status: "paid_leave", is_paid_leave: true, summary: "有給休暇", history_id: "h1" },
      "2027-01-01": { date: "2027-01-01", type: "有給", status: "paid_leave", is_paid_leave: true, summary: "有給休暇", history_id: "h2" }
    };
  `, context);

  factory = createTrackingCanvasFactory(true);
  const denseCanvas = context.renderMonthlyCalendarCanvas(2026, 12);
  factory.restore();
  const denseMeta = denseCanvas._meta();

  // 4) truncateCanvasText の measureText あり／なし単体検証
  const truncResults = vm.runInContext(`({
    withMeasureShort: truncateCanvasText({ measureText: (s) => ({ width: s.length * 10 }) }, "短い", 100, 10),
    withMeasureLong: truncateCanvasText({ measureText: (s) => ({ width: s.length * 10 }) }, "あいうえおかきくけこさしすせそ", 60, 10),
    fallbackShort: truncateCanvasText({}, "短い", 60, 6),
    fallbackLong: truncateCanvasText({}, "あいうえおかきくけこ", 60, 6)
  })`, context);

  console.log(JSON.stringify({
    palettes,
    emptyHeight: emptyCanvas.height,
    denseHeight: denseCanvas.height,
    emptyTexts: emptyMeta.textDraws.map(d => d.text),
    denseMeta,
    truncResults
  }));
""")

        # 1) CSS変数とCanvasパレットの完全一致検証（ドリフト防止）
        tone_palette = res["palettes"]["tonePalette"]
        canvas_colors = res["palettes"]["canvasColors"]
        for tone in ["early-a", "early-b", "early-c", "early-d", "day", "late-a", "late-b", "late-c"]:
            self.assertEqual(tone_palette[tone]["bg"], css_vars[f"--shift-tone-{tone}-bg"], msg=f"{tone} bg")
            self.assertEqual(tone_palette[tone]["border"], css_vars[f"--shift-tone-{tone}-border"], msg=f"{tone} border")
            self.assertEqual(tone_palette[tone]["fg"], css_vars[f"--shift-tone-{tone}-text"], msg=f"{tone} fg")

        for status_key in ["work", "holiday", "paid"]:
            self.assertEqual(canvas_colors[status_key]["bg"], css_vars[f"--shift-{status_key}-bg"])
            self.assertEqual(canvas_colors[status_key]["border"], css_vars[f"--shift-{status_key}-border"])
            self.assertEqual(canvas_colors[status_key]["fg"], css_vars[f"--shift-{status_key}-text"])
            self.assertEqual(canvas_colors[status_key]["dot"], css_vars[f"--shift-{status_key}-dot"])

        self.assertEqual(canvas_colors["event"]["bg"], css_vars["--event-badge-bg"])
        self.assertEqual(canvas_colors["event"]["border"], css_vars["--event-badge-border"])
        self.assertEqual(canvas_colors["event"]["fg"], css_vars["--event-badge-text"])
        self.assertEqual(canvas_colors["windowBg"], css_vars["--window-bg"])
        self.assertEqual(canvas_colors["headerBg"], css_vars["--header-bg"])
        self.assertEqual(canvas_colors["separator"], css_vars["--separator"])
        self.assertEqual(canvas_colors["controlBorder"], css_vars["--control-border"])
        self.assertEqual(canvas_colors["labelPrimary"], css_vars["--label-primary"])
        self.assertEqual(canvas_colors["labelSecondary"], css_vars["--label-secondary"])
        self.assertEqual(canvas_colors["labelTertiary"], css_vars["--label-tertiary"])
        self.assertEqual(canvas_colors["sat"], css_vars["--accent"])

        # 2) 空月と密月の高さ比較（行高さ動的拡張＆空月の安全描画）
        self.assertGreater(res["denseHeight"], res["emptyHeight"])
        self.assertIn("(登録 0日間)", res["emptyTexts"])
        self.assertIn("0日", res["emptyTexts"])

        # 3) ヘッダー集計カプセル（当月のみ集計・月外2026-11-30と2027-01-01を除外・時間有給合算）
        dense_texts = [d["text"] for d in res["denseMeta"]["textDraws"]]
        self.assertIn("(登録 4日間)", dense_texts)
        self.assertIn("2日", dense_texts)       # 出勤: 12/1, 12/2（11/30は月外なので除外）
        self.assertIn("1日", dense_texts)       # 休み: 12/3
        self.assertIn("1日 2時間", dense_texts)  # 有給休暇: 12/4(1日) + 12/1(時間有給2h)、1/1は月外なので除外

        # 4) 当月外セルの半透明描画（globalAlpha=0.52）とsave/restore対称性＆月表記
        self.assertEqual(res["denseMeta"]["saveCount"], res["denseMeta"]["restoreCount"])
        self.assertEqual(res["denseMeta"]["finalAlpha"], 1)
        alpha_by_text = {}
        for d in res["denseMeta"]["textDraws"]:
            alpha_by_text.setdefault(d["text"], []).append(d["alpha"])
        self.assertIn(0.52, alpha_by_text.get("[早A]", []))   # 11/30（月外）は半透明
        self.assertIn(1, alpha_by_text.get("[日]", []))       # 12/1（当月）は不透明
        self.assertIn("11月", dense_texts)
        self.assertIn("12月", dense_texts)
        self.assertIn("1月", dense_texts)

        # 5) 長文テキストの省略（measureTextあり／なし両方）
        tr = res["truncResults"]
        self.assertEqual(tr["withMeasureShort"], "短い")
        self.assertTrue(tr["withMeasureLong"].endswith("…"))
        self.assertLessEqual(len(tr["withMeasureLong"]) * 10, 60)
        self.assertEqual(tr["fallbackShort"], "短い")
        self.assertEqual(tr["fallbackLong"], "あいうえお…")
        # 実際の描画結果でも長文行事・メモが省略されて描画されていること
        self.assertTrue(any(t.startswith("とても長い") and t.endswith("…") for t in dense_texts))
        self.assertTrue(any(t.startswith("これはセル幅") and t.endswith("…") for t in dense_texts))


if __name__ == "__main__":
    unittest.main()
