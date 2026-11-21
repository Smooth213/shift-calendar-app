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

INDEX_HTML_PATH = os.path.join(PROJECT_ROOT, "index.html")


def _build_calendar_node_harness(test_body_js):
    return r"""
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync(process.argv[1], "utf8");
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (!scriptMatch) throw new Error("no script tag");

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

const html = fs.readFileSync(process.argv[1], "utf8");
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (!scriptMatch) throw new Error("no script tag");

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


if __name__ == "__main__":
    unittest.main()
