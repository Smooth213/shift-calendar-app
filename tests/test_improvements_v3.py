"""Phase 1〜3 の機能強化（ひとことメモ・未登録日手入力・Undo・読み取り精度可視化・共有出力・アコーディオン内訳＆有給履歴・横断検索）の検証テスト。"""

import io
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
from shift_calendar.calendar_export import build_apple_calendar_script, create_ics
from shift_calendar.gemini_client import evaluate_shift_quality
from shift_calendar.storage import (
    get_registered_calendar_shifts,
    save_history,
    update_history_shift,
    upsert_manual_calendar_shift,
)
from tests.dom_harness import run_node_harness


class _MockRequestHandler(shift_app.RequestHandler):
    def __init__(self, path="/", client_ip="127.0.0.1", headers=None):
        self.path = path
        self.client_address = (client_ip, 54321)
        self.headers = headers or {}
        self.wfile = io.BytesIO()
        self.response_status = None
        self.response_headers = {}

    def send_response(self, code, message=None):
        self.response_status = code

    def send_header(self, keyword, value):
        self.response_headers[keyword] = value

    def end_headers(self):
        pass

    def send_error(self, code, message=None, explain=None):
        self.response_status = code


class TestImprovementsV3(unittest.TestCase):
    def test_memo_exported_to_ics_and_applescript(self):
        shifts = [
            {
                "date": "2026-11-10",
                "type": "早B",
                "status": "work",
                "start_time": "06:30",
                "end_time": "15:30",
                "summary": "[早B] (06:30〜15:30)",
                "memo": "研修あり",
            },
            {
                "date": "2026-11-11",
                "type": "休",
                "status": "holiday",
                "is_holiday": True,
                "summary": "休み",
                "memo": "通院予定",
            },
            {
                "date": "2026-11-12",
                "type": "日",
                "status": "work",
                "start_time": "08:30",
                "end_time": "17:30",
                "summary": "[日] (08:30〜17:30)",
                "memo": "",
            },
        ]
        ics = create_ics(shifts)
        self.assertIn("DESCRIPTION:シフト区分: 早B / メモ: 研修あり", ics)
        self.assertIn("DESCRIPTION:区分: 休 / メモ: 通院予定", ics)
        self.assertIn("DESCRIPTION:シフト区分: 日\r\n", ics)

        script, count = build_apple_calendar_script(shifts)
        self.assertEqual(count, 3)
        self.assertIn('description:"シフト区分: 早B / メモ: 研修あり"', script)
        self.assertIn('description:"区分: 休 / メモ: 通院予定"', script)
        self.assertIn('description:"シフト区分: 日"', script)

    def test_memo_update_and_manual_shift_upsert(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = {
                "target_name": "皿田",
                "paid_leave_hours_per_day": 8,
                "time_definitions": {
                    "早B": {"start": "06:30", "end": "15:30"},
                    "日": {"start": "08:30", "end": "17:30"},
                },
            }
            hist_id = save_history(tmpdir, {
                "title": "2026年11月",
                "registered": True,
                "registered_at": "2026/11/01 10:00",
                "shifts": [
                    {
                        "date": "2026-11-05",
                        "day_of_week": "木",
                        "type": "早B",
                        "status": "work",
                        "start_time": "06:30",
                        "end_time": "15:30",
                        "summary": "[早B] (06:30〜15:30)",
                    }
                ],
            })
            updated = update_history_shift(
                tmpdir, hist_id, "2026-11-05", {"memo": "車通勤"}, lambda: cfg
            )
            self.assertEqual(updated["memo"], "車通勤")

            manual_shift, manual_id = upsert_manual_calendar_shift(
                tmpdir,
                "2026-11-20",
                {"type": "日", "hourly_paid_leave": 2, "event": "面談", "memo": "午後早退"},
                lambda: cfg,
            )
            self.assertEqual(manual_id, "manual_2026_11")
            self.assertEqual(manual_shift["type"], "日")
            self.assertEqual(manual_shift["hourly_paid_leave"], 2.0)
            self.assertEqual(manual_shift["memo"], "午後早退")
            self.assertIn("時間有給2h", manual_shift["summary"])

            reg = get_registered_calendar_shifts(tmpdir)
            self.assertEqual(reg["shifts_by_date"]["2026-11-05"]["memo"], "車通勤")
            self.assertEqual(reg["shifts_by_date"]["2026-11-20"]["memo"], "午後早退")
            self.assertEqual(reg["shifts_by_date"]["2026-11-20"]["history_id"], "manual_2026_11")

    def test_api_calendar_shift_update_supports_manual_creation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(shift_app, "HISTORY_DIR", tmpdir), patch.object(
                shift_app,
                "load_config",
                return_value={
                    "target_name": "皿田",
                    "calendar_name": "シフトカレンダー",
                    "paid_leave_hours_per_day": 8,
                    "time_definitions": {"早A": {"start": "06:00", "end": "15:00"}},
                },
            ):
                handler = _MockRequestHandler(path="/api/calendar_shifts/update")
                body = json.dumps({
                    "history_id": "",
                    "date": "2026-12-03",
                    "type": "早A",
                    "event": "朝礼",
                    "memo": "鍵当番",
                    "sync_apple_calendar": False,
                }).encode("utf-8")
                handler._handle_post_calendar_shift_update(body)
                self.assertEqual(handler.response_status, 200)
                payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
                self.assertTrue(payload["success"])
                self.assertTrue(payload["manual_created"])
                self.assertEqual(payload["history_id"], "manual_2026_12")
                self.assertEqual(payload["shift"]["memo"], "鍵当番")

    def test_evaluate_shift_quality_detects_errors_warnings_and_streaks(self):
        shifts = [
            {"date": f"2026-11-0{d}", "type": "日", "status": "work", "start_time": "08:30", "end_time": "17:30", "confidence": "high"}
            for d in range(1, 7)
        ] + [
            {"date": "2026-11-07", "type": "休", "status": "holiday", "is_holiday": True, "confidence": "low"},
            {"date": "2026-11-08", "type": "謎記号", "status": "work", "start_time": None, "end_time": None, "confidence": "high"},
        ]
        summary = evaluate_shift_quality(shifts)
        self.assertEqual(summary["total"], 8)
        self.assertEqual(summary["error_count"], 1)  # 謎記号
        self.assertEqual(summary["warning_count"], 2)  # 6連勤 + low confidence
        self.assertEqual(summary["review_count"], 3)
        self.assertEqual(shifts[5]["quality_level"], "warning")
        self.assertEqual(shifts[6]["quality_level"], "warning")
        self.assertEqual(shifts[7]["quality_level"], "error")
        self.assertLess(summary["score_percent"], 100)

    def test_frontend_phase1_to_phase3_dom_interactions(self):
        scenario = r"""
        const ctx = createIndexContext(async (url) => {
          if (url === "/api/config") {
            return {
              ok: true,
              json: async () => ({
                target_name: "皿田",
                calendar_name: "シフトカレンダー",
                has_api_key: true,
                time_definitions: {
                  "早B": { start: "06:30", end: "15:30" },
                  "日": { start: "08:30", end: "17:30" }
                }
              })
            };
          }
          if (url === "/api/calendar_shifts") {
            return { ok: true, json: async () => ({ success: true, shifts_by_date: {}, available_months: [] }) };
          }
          return { ok: true, json: async () => ({ success: true, history: [] }) };
        });
        await new Promise(r => setImmediate(r));
        await new Promise(r => setImmediate(r));

        const result = await vm.runInContext(`
          (async function() {
            // --- Phase 2: 読み取り精度プログレスバー＋SVGアイコン＋既存3方向連動 ---
            renderResult({
              target_name: "皿田",
              shifts: [
                { date: "2026-11-01", day_of_week: "日", type: "早B", status: "work", start_time: "06:30", end_time: "15:30", summary: "[早B] (06:30〜15:30)", confidence: "high", memo: "" },
                { date: "2026-11-02", day_of_week: "月", type: "不明X", status: "work", start_time: null, end_time: null, summary: "[不明X]", confidence: "low", memo: "要確認メモ" }
              ]
            });
            const scoreBefore = document.getElementById("quality-score-text").textContent;
            const badgeBefore = document.getElementById("quality-review-badge").textContent;
            const jumpVisible = document.getElementById("btn-jump-next-review").style.display;

            // 次の要確認へ移動で3方向連動（selectedCalendarIdx=1）が動く
            await document.getElementById("btn-jump-next-review").dispatchAsync("click");
            const jumpedIdx = selectedCalendarIdx;

            // --- Phase 1: 調整テーブル編集＋Undo ---
            pushShiftUndoSnapshot();
            analyzedShifts[0].memo = "車通勤";
            const memoAfterEdit = analyzedShifts[0].memo;
            const undoDisabledAfterEdit = document.getElementById("btn-undo-shifts").disabled;

            await document.getElementById("btn-undo-shifts").dispatchAsync("click");
            const memoAfterUndo = analyzedShifts[0].memo;
            const undoDisabledAfterUndo = document.getElementById("btn-undo-shifts").disabled;

            // --- Phase 3 & Phase 1 カレンダータブ: 集計内訳・有給履歴・検索・共有テキスト・未登録日手入力 ---
            AppState.calendar.shiftsByDate = {
              "2026-11-01": { date: "2026-11-01", day_of_week: "日", type: "早B", status: "work", start_time: "06:30", end_time: "15:30", hourly_paid_leave: 1, summary: "[早B] (06:30〜15:30)（時間有給1h）", event: "避難訓練", memo: "担当班", history_id: "h1", history_title: "2026年11月" },
              "2026-11-02": { date: "2026-11-02", day_of_week: "月", type: "有給", status: "paid_leave", is_paid_leave: true, summary: "有給休暇", event: "", memo: "私用", history_id: "h1", history_title: "2026年11月" }
            };
            AppState.calendar.viewYear = 2026;
            AppState.calendar.viewMonth = 11;
            renderMonthlyCalendarView();

            // 月間内訳アコーディオン
            await document.getElementById("btn-cal-monthly-breakdown-toggle").dispatchAsync("click");
            const breakdownOpen = document.getElementById("cal-monthly-breakdown-panel").classList.contains("is-open");
            const workHoursText = document.getElementById("cal-monthly-work-hours").textContent;

            // 有給取得履歴アコーディオン
            await document.getElementById("btn-cal-leave-history-toggle").dispatchAsync("click");
            const leaveHistOpen = document.getElementById("cal-leave-history-panel").classList.contains("is-open");
            const leaveHistCount = document.getElementById("cal-leave-history-list").children.length;

            // 過去履歴キーワード検索
            const searchEl = document.getElementById("cal-search-input");
            searchEl.value = "避難訓練";
            await searchEl.dispatchAsync("input", { target: searchEl });
            const searchOpen = document.getElementById("cal-search-results").classList.contains("is-open");
            const searchMatches = document.getElementById("cal-search-results").children.length;

            // テキスト共有（全日程／休み・有給のみ／早番・遅番のみ）
            const shareAll = buildMonthlyShareText(2026, 11, "all");
            const shareOff = buildMonthlyShareText(2026, 11, "off");
            const shareEarlyLate = buildMonthlyShareText(2026, 11, "early_late");

            // 未登録日（2026-11-03）をクリックして手入力新規モードが開くこと
            AppState.calendar.selectedDate = "2026-11-03";
            renderMonthlyCalendarView();
            const manualBtnText = document.getElementById("btn-cal-save-shift").textContent;
            const manualHistId = document.getElementById("btn-cal-save-shift").dataset.historyId;

            return {
              scoreBefore,
              badgeBefore,
              jumpVisible,
              jumpedIdx,
              memoAfterEdit,
              undoDisabledAfterEdit,
              memoAfterUndo,
              undoDisabledAfterUndo,
              breakdownOpen,
              workHoursText,
              leaveHistOpen,
              leaveHistCount,
              searchOpen,
              searchMatches,
              shareAll,
              shareOff,
              shareEarlyLate,
              manualBtnText,
              manualHistId
            };
          })();
        `, ctx);
        console.log(JSON.stringify(result));
        """
        rc, stdout, stderr = run_node_harness(scenario)
        self.assertEqual(rc, 0, msg=f"Node harness failed:\nSTDOUT:{stdout}\nSTDERR:{stderr}")
        res = json.loads(stdout.strip().splitlines()[-1])
        self.assertEqual(res["scoreBefore"], "50%")
        self.assertIn("エラー 1件", res["badgeBefore"])
        self.assertEqual(res["jumpVisible"], "inline-flex")
        self.assertEqual(res["jumpedIdx"], 1)

        self.assertEqual(res["memoAfterEdit"], "車通勤")
        self.assertFalse(res["undoDisabledAfterEdit"])
        self.assertEqual(res["memoAfterUndo"], "")
        self.assertTrue(res["undoDisabledAfterUndo"])

        self.assertTrue(res["breakdownOpen"])
        self.assertEqual(res["workHoursText"], "8時間")  # 06:30-15:30 (9h) - 時間有給1h = 8h
        self.assertTrue(res["leaveHistOpen"])
        self.assertEqual(res["leaveHistCount"], 2)  # 終日有給 + 時間有給1h
        self.assertTrue(res["searchOpen"])
        self.assertEqual(res["searchMatches"], 1)

        self.assertIn("11/1(日) 早B", res["shareAll"])
        self.assertIn("11/2(月) 有給休暇", res["shareOff"])
        self.assertNotIn("早B", res["shareOff"])
        self.assertIn("早B", res["shareEarlyLate"])
        self.assertNotIn("有給休暇", res["shareEarlyLate"])

        self.assertEqual(res["manualBtnText"], "シフトを追加")
        self.assertEqual(res["manualHistId"], "")

    def test_manual_shift_validation_overwrite_and_legacy_memo_compat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = {
                "target_name": "皿田",
                "paid_leave_hours_per_day": 8,
                "time_definitions": {
                    "早B": {"start": "06:30", "end": "15:30"},
                    "遅A": {"start": "09:00", "end": "18:00"},
                },
            }
            # 異常系: 実在しない日付・不正形式・空区分
            with self.assertRaises(ValueError):
                upsert_manual_calendar_shift(tmpdir, "2026-02-30", {"type": "早B"}, lambda: cfg)
            with self.assertRaises(ValueError):
                upsert_manual_calendar_shift(tmpdir, "2026/11/01", {"type": "早B"}, lambda: cfg)
            with self.assertRaises(ValueError):
                upsert_manual_calendar_shift(tmpdir, "2026-11-25", {"type": ""}, lambda: cfg)

            # APIでも不正日付はHTTP 400
            with patch.object(shift_app, "HISTORY_DIR", tmpdir), patch.object(
                shift_app, "load_config", return_value=cfg
            ):
                handler = _MockRequestHandler(path="/api/calendar_shifts/update")
                body = json.dumps({"history_id": "", "date": "2026-02-30", "type": "早B"}).encode("utf-8")
                handler._handle_post_calendar_shift_update(body)
                self.assertEqual(handler.response_status, 400)

            # 同一日2回保存で重複せず上書きされること
            upsert_manual_calendar_shift(tmpdir, "2026-11-25", {"type": "早B", "memo": "初回"}, lambda: cfg)
            updated, hid = upsert_manual_calendar_shift(
                tmpdir, "2026-11-25", {"type": "遅A", "memo": "変更後"}, lambda: cfg
            )
            self.assertEqual(updated["type"], "遅A")
            self.assertEqual(updated["memo"], "変更後")
            with open(os.path.join(tmpdir, f"{hid}.json"), "r", encoding="utf-8") as f:
                saved_doc = json.load(f)
            self.assertEqual(len(saved_doc["shifts"]), 1)

            # memoフィールドを持たない旧形式履歴JSONの後方互換性
            save_history(tmpdir, {
                "title": "旧履歴",
                "registered": True,
                "registered_at": "2026/10/01 09:00",
                "shifts": [
                    {
                        "date": "2026-10-01",
                        "day_of_week": "木",
                        "type": "早B",
                        "status": "work",
                        "start_time": "06:30",
                        "end_time": "15:30",
                        "summary": "[早B] (06:30〜15:30)",
                    }
                ],
            })
            reg = get_registered_calendar_shifts(tmpdir)
            self.assertIn("2026-10-01", reg["shifts_by_date"])
            self.assertEqual(reg["shifts_by_date"]["2026-10-01"]["memo"], "")

    def test_time_dial_normalization_and_3d_drum_behavior(self):
        scenario = r"""
        const ctx = createIndexContext(async (url) => {
          if (url === "/api/config") {
            return {
              ok: true,
              json: async () => ({
                target_name: "皿田",
                calendar_name: "シフトカレンダー",
                has_api_key: true,
                time_definitions: { "早B": { start: "06:30", end: "15:30" } }
              })
            };
          }
          return { ok: true, json: async () => ({ success: true, shifts_by_date: {}, history: [] }) };
        });
        await new Promise(r => setImmediate(r));
        await new Promise(r => setImmediate(r));

        const result = vm.runInContext(`
          (function() {
            const normCases = {
              digits4: normalizeTimeInputValue("0630"),
              digits3: normalizeTimeInputValue("715"),
              fullwidth: normalizeTimeInputValue("０８：３０"),
              emptyAllowed: normalizeTimeInputValue("", true),
              invalidHour: normalizeTimeInputValue("25:00"),
              invalidMin: normalizeTimeInputValue("12:60"),
              invalidAlpha: normalizeTimeInputValue("abc")
            };

            renderResult({
              target_name: "皿田",
              shifts: [
                { date: "2026-11-01", day_of_week: "日", type: "早B", status: "work", start_time: "06:30", end_time: "15:30", summary: "[早B] (06:30〜15:30)" }
              ]
            });

            // 無効入力欄では開かないこと
            const disabledInput = document.createElement("input");
            disabledInput.disabled = true;
            disabledInput.value = "";
            openTimeDialPopover(disabledInput);
            const displayWhenDisabled = document.getElementById("time-dial-popover").style.display || "";

            // 有効入力欄で開くと時24件・分60件が生成されること
            const activeInput = document.createElement("input");
            activeInput.disabled = false;
            activeInput.dataset = { idx: "0", field: "start_time" };
            activeInput.value = "06:30";
            openTimeDialPopover(activeInput);
            const displayWhenOpen = document.getElementById("time-dial-popover").style.display;
            const hourCount = document.getElementById("time-dial-hours").children.length;
            const minuteCount = document.getElementById("time-dial-minutes").children.length;

            // 直接入力 "0715" を確定すると "07:15" に整形されUndoスタックが積まれる
            activeInput.value = "0715";
            commitTimeFieldInput(activeInput);
            const committedVal = analyzedShifts[0].start_time;
            const inputValAfterCommit = activeInput.value;
            const undoLenAfterCommit = shiftUndoStack.length;

            // 不正値 "99:99" は元値へロールバックされる
            activeInput.value = "99:99";
            commitTimeFieldInput(activeInput);
            const valAfterInvalid = activeInput.value;
            const shiftValAfterInvalid = analyzedShifts[0].start_time;

            closeTimeDialPopover();
            const displayAfterClose = document.getElementById("time-dial-popover").style.display;

            return {
              normCases,
              displayWhenDisabled,
              displayWhenOpen,
              hourCount,
              minuteCount,
              committedVal,
              inputValAfterCommit,
              undoLenAfterCommit,
              valAfterInvalid,
              shiftValAfterInvalid,
              displayAfterClose
            };
          })();
        `, ctx);
        console.log(JSON.stringify(result));
        """
        rc, stdout, stderr = run_node_harness(scenario)
        self.assertEqual(rc, 0, msg=f"Node harness failed:\nSTDOUT:{stdout}\nSTDERR:{stderr}")
        res = json.loads(stdout.strip().splitlines()[-1])
        self.assertEqual(res["normCases"]["digits4"], "06:30")
        self.assertEqual(res["normCases"]["digits3"], "07:15")
        self.assertEqual(res["normCases"]["fullwidth"], "08:30")
        self.assertEqual(res["normCases"]["emptyAllowed"], "")
        self.assertIsNone(res["normCases"]["invalidHour"])
        self.assertIsNone(res["normCases"]["invalidMin"])
        self.assertIsNone(res["normCases"]["invalidAlpha"])
        self.assertNotEqual(res["displayWhenDisabled"], "block")
        self.assertEqual(res["displayWhenOpen"], "block")
        self.assertEqual(res["hourCount"], 24)
        self.assertEqual(res["minuteCount"], 60)
        self.assertEqual(res["committedVal"], "07:15")
        self.assertEqual(res["inputValAfterCommit"], "07:15")
        self.assertEqual(res["undoLenAfterCommit"], 1)
        self.assertEqual(res["valAfterInvalid"], "07:15")
        self.assertEqual(res["shiftValAfterInvalid"], "07:15")
        self.assertEqual(res["displayAfterClose"], "none")

    def test_adjust_table_summary_toggle_and_quality_recovery(self):
        scenario = r"""
        const ctx = createIndexContext(async (url) => {
          if (url === "/api/config") {
            return {
              ok: true,
              json: async () => ({
                target_name: "皿田",
                calendar_name: "シフトカレンダー",
                has_api_key: true,
                time_definitions: { "早B": { start: "06:30", end: "15:30" } }
              })
            };
          }
          return { ok: true, json: async () => ({ success: true, shifts_by_date: {}, history: [] }) };
        });
        await new Promise(r => setImmediate(r));
        await new Promise(r => setImmediate(r));

        const result = await vm.runInContext(`
          (async function() {
            const tableEl = document.getElementById("shifts-adjust-table");
            tableEl.classList.add("hide-summary-col");
            const toggleEl = document.getElementById("toggle-show-summary-col");
            toggleEl.checked = true;
            await toggleEl.dispatchAsync("change");
            const hiddenWhenChecked = tableEl.classList.contains("hide-summary-col");

            toggleEl.checked = false;
            await toggleEl.dispatchAsync("change");
            const hiddenWhenUnchecked = tableEl.classList.contains("hide-summary-col");

            // 不明記号（エラー）を含むシフトを描画 → 手動修正で精度100%へ回復すること
            renderResult({
              target_name: "皿田",
              shifts: [
                { date: "2026-11-01", day_of_week: "日", type: "謎", status: "work", start_time: null, end_time: null, summary: "[謎]", confidence: "low" }
              ]
            });
            const scoreBefore = document.getElementById("quality-score-text").textContent;
            const mockTr = {
              dataset: {},
              classList: new (tableEl.classList.constructor)(),
              querySelector: (sel) => {
                if (sel === ".shift-time-start") return { value: "", disabled: false };
                if (sel === ".shift-time-end") return { value: "", disabled: false };
                if (sel === ".shift-summary") return { value: "" };
                if (sel === ".shift-hourly-leave") return { value: "0", disabled: false };
                return null;
              }
            };
            applyShiftTypeSelection(0, "早B", mockTr);
            const scoreAfter = document.getElementById("quality-score-text").textContent;
            const summaryAfter = analyzedShifts[0].summary;
            const verifiedAfter = Boolean(analyzedShifts[0]._user_verified);

            return { hiddenWhenChecked, hiddenWhenUnchecked, scoreBefore, scoreAfter, summaryAfter, verifiedAfter };
          })();
        `, ctx);
        console.log(JSON.stringify(result));
        """
        rc, stdout, stderr = run_node_harness(scenario)
        self.assertEqual(rc, 0, msg=f"Node harness failed:\nSTDOUT:{stdout}\nSTDERR:{stderr}")
        res = json.loads(stdout.strip().splitlines()[-1])
        self.assertFalse(res["hiddenWhenChecked"])
        self.assertTrue(res["hiddenWhenUnchecked"])
        self.assertEqual(res["scoreBefore"], "0%")
        self.assertEqual(res["scoreAfter"], "100%")
        self.assertEqual(res["summaryAfter"], "[早B] (06:30〜15:30)")
        self.assertTrue(res["verifiedAfter"])

    def test_export_monthly_calendar_png_uses_light_background_and_filename(self):
        scenario = r"""
        const ctx = createIndexContext(async () => ({ ok: true, json: async () => ({ success: true }) }));
        await new Promise(r => setImmediate(r));
        await new Promise(r => setImmediate(r));

        const result = vm.runInContext(`
          (function() {
            const fillColors = [];
            let downloadedName = "";
            let downloadedHref = "";
            let clicked = false;
            const origCreate = document.createElement;
            document.createElement = (tag) => {
              if (tag === "canvas") {
                return {
                  width: 0,
                  height: 0,
                  getContext: () => ({
                    scale() {},
                    set fillStyle(v) { fillColors.push(v); },
                    set strokeStyle(v) {},
                    set lineWidth(v) {},
                    set font(v) {},
                    set textAlign(v) {},
                    fillRect() {},
                    strokeRect() {},
                    fillText() {}
                  }),
                  toDataURL: () => "data:image/png;base64,MOCKPNG"
                };
              }
              if (tag === "a") {
                return {
                  set href(v) { downloadedHref = v; },
                  set download(v) { downloadedName = v; },
                  click() { clicked = true; }
                };
              }
              return origCreate(tag);
            };
            if (!document.body) document.body = { appendChild() {}, removeChild() {} };
            if (!document.body.removeChild) document.body.removeChild = () => {};

            AppState.calendar.shiftsByDate = {
              "2026-11-05": { date: "2026-11-05", type: "早B", status: "work", start_time: "06:30", end_time: "15:30", event: "会議", memo: "資料持参" }
            };
            const ok = exportMonthlyCalendarPng(2026, 11);
            return { ok, firstFill: fillColors[0], downloadedName, downloadedHref, clicked };
          })();
        `, ctx);
        console.log(JSON.stringify(result));
        """
        rc, stdout, stderr = run_node_harness(scenario)
        self.assertEqual(rc, 0, msg=f"Node harness failed:\nSTDOUT:{stdout}\nSTDERR:{stderr}")
        res = json.loads(stdout.strip().splitlines()[-1])
        self.assertTrue(res["ok"])
        self.assertEqual(res["firstFill"], "#ffffff")
        self.assertEqual(res["downloadedName"], "shift_calendar_2026_11.png")
        self.assertTrue(res["downloadedHref"].startswith("data:image/png;base64,"))
        self.assertTrue(res["clicked"])

    def test_search_and_leave_history_jump_plus_css_regression_guards(self):
        scenario = r"""
        const ctx = createIndexContext(async () => ({ ok: true, json: async () => ({ success: true }) }));
        await new Promise(r => setImmediate(r));
        await new Promise(r => setImmediate(r));

        const result = await vm.runInContext(`
          (async function() {
            AppState.calendar.shiftsByDate = {
              "2026-05-10": { date: "2026-05-10", day_of_week: "日", type: "有給", status: "paid_leave", is_paid_leave: true, summary: "有給休暇", event: "", memo: "", history_id: "h5" },
              "2026-08-15": { date: "2026-08-15", day_of_week: "土", type: "早B", status: "work", start_time: "06:30", end_time: "15:30", summary: "[早B]", event: "夏祭り", memo: "浴衣当番", history_id: "h8" }
            };
            AppState.calendar.viewYear = 2026;
            AppState.calendar.viewMonth = 11;
            renderMonthlyCalendarView();

            // 1. 検索結果クリックで別月(2026年8月15日)へジャンプ
            const searchEl = document.getElementById("cal-search-input");
            searchEl.value = "夏祭り";
            await searchEl.dispatchAsync("input", { target: searchEl });
            const firstMatchBtn = document.getElementById("cal-search-results").children[0];
            await firstMatchBtn.dispatchAsync("click");
            const afterSearchJump = {
              y: AppState.calendar.viewYear,
              m: AppState.calendar.viewMonth,
              d: AppState.calendar.selectedDate
            };

            // 2. 年間有給取得履歴クリックで別月(2026年5月10日)へジャンプ
            const leaveBtn = document.getElementById("cal-leave-history-list").children[0];
            await leaveBtn.dispatchAsync("click");
            const afterLeaveJump = {
              y: AppState.calendar.viewYear,
              m: AppState.calendar.viewMonth,
              d: AppState.calendar.selectedDate
            };

            return { afterSearchJump, afterLeaveJump };
          })();
        `, ctx);
        console.log(JSON.stringify(result));
        """
        rc, stdout, stderr = run_node_harness(scenario)
        self.assertEqual(rc, 0, msg=f"Node harness failed:\nSTDOUT:{stdout}\nSTDERR:{stderr}")
        res = json.loads(stdout.strip().splitlines()[-1])
        self.assertEqual(res["afterSearchJump"], {"y": 2026, "m": 8, "d": "2026-08-15"})
        self.assertEqual(res["afterLeaveJump"], {"y": 2026, "m": 5, "d": "2026-05-10"})

        # CSS / HTML 回帰ガード（アコーディオン角丸四角・ダイヤル完了ボタン折り返し防止）
        with open(os.path.join(PROJECT_ROOT, "static", "styles.css"), "r", encoding="utf-8") as f:
            css_text = f.read()
        with open(os.path.join(PROJECT_ROOT, "index.html"), "r", encoding="utf-8") as f:
            html_text = f.read()
        self.assertIn(".cal-accordion-card", css_text)
        self.assertIn("border-radius: var(--radius-card);", css_text)
        self.assertIn('id="btn-time-dial-done"', html_text)
        self.assertIn("white-space: nowrap;", html_text)

    def test_share_output_dropdown_image_copy_print_and_preview_fallback(self):
        scenario = r"""
        const ctx = createIndexContext(async () => ({ ok: true, json: async () => ({ success: true }) }));
        await new Promise(r => setImmediate(r));
        await new Promise(r => setImmediate(r));

        const result = await vm.runInContext(`
          (async function() {
            const origCreate = document.createElement;
            document.createElement = (tag) => {
              if (tag === "canvas") {
                return {
                  width: 0,
                  height: 0,
                  getContext: () => ({
                    scale() {},
                    set fillStyle(v) {},
                    set strokeStyle(v) {},
                    set lineWidth(v) {},
                    set font(v) {},
                    set textAlign(v) {},
                    fillRect() {},
                    strokeRect() {},
                    fillText() {}
                  }),
                  toDataURL: () => "data:image/png;base64,MOCKIMG",
                  toBlob: (cb) => cb({ type: "image/png", size: 8 })
                };
              }
              return origCreate(tag);
            };

            AppState.calendar.shiftsByDate = {
              "2026-11-12": { date: "2026-11-12", type: "早B", status: "work", start_time: "06:30", end_time: "15:30" }
            };
            AppState.calendar.viewYear = 2026;
            AppState.calendar.viewMonth = 11;

            const trigger = document.getElementById("btn-cal-share-menu");
            const popover = document.getElementById("cal-share-menu-popover");
            const nativeShareBtn = document.getElementById("btn-cal-native-share");
            const copyImageBtn = document.getElementById("btn-cal-copy-image");
            const printBtn = document.getElementById("btn-cal-print");
            const previewModal = document.getElementById("cal-image-preview-modal");
            const previewImg = document.getElementById("cal-image-preview-img");
            const closePreviewBtn = document.getElementById("btn-close-image-preview");

            // 1. navigator.share 未定義時の開閉（トグルで閉じる）
            if (typeof navigator === "undefined") globalThis.navigator = {};
            delete navigator.share;
            await trigger.dispatchAsync("click", { stopPropagation() {} });
            const openWithoutNative = popover.classList.contains("is-open");
            const nativeHidden = nativeShareBtn.style.display === "none";
            await trigger.dispatchAsync("click", { stopPropagation() {} });
            const closedByToggle = !popover.classList.contains("is-open");

            // 2. navigator.share あり時の表示
            navigator.share = async () => {};
            await trigger.dispatchAsync("click", { stopPropagation() {} });
            const nativeVisible = nativeShareBtn.style.display === "flex";

            // 3. 画像コピー（クリップボード成功ルート）
            let clipboardItemsWritten = 0;
            globalThis.ClipboardItem = function(map) { this.map = map; };
            navigator.clipboard = {
              write: async (items) => { clipboardItemsWritten = items.length; },
              writeText: async () => {}
            };
            await copyImageBtn.dispatchAsync("click");
            const previewHiddenAfterClip = previewModal.style.display !== "flex";
            const closedAfterCopy = !popover.classList.contains("is-open");

            // 4. 画像コピー（非対応環境 → プレビューモーダルフォールバック）
            delete navigator.clipboard;
            await copyImageBtn.dispatchAsync("click");
            const previewShownFallback = previewModal.style.display === "flex";
            const previewSrc = previewImg.src;
            await closePreviewBtn.dispatchAsync("click");
            const previewClosed = previewModal.style.display === "none";

            // 5. 印刷ボタン
            let printCalled = 0;
            window.print = () => { printCalled++; };
            await printBtn.dispatchAsync("click");

            return {
              openWithoutNative,
              nativeHidden,
              closedByToggle,
              nativeVisible,
              clipboardItemsWritten,
              previewHiddenAfterClip,
              closedAfterCopy,
              previewShownFallback,
              previewSrc,
              previewClosed,
              printCalled
            };
          })();
        `, ctx);
        console.log(JSON.stringify(result));
        """
        rc, stdout, stderr = run_node_harness(scenario)
        self.assertEqual(rc, 0, msg=f"Node harness failed:\nSTDOUT:{stdout}\nSTDERR:{stderr}")
        res = json.loads(stdout.strip().splitlines()[-1])
        self.assertTrue(res["openWithoutNative"])
        self.assertTrue(res["nativeHidden"])
        self.assertTrue(res["closedByToggle"])
        self.assertTrue(res["nativeVisible"])
        self.assertEqual(res["clipboardItemsWritten"], 1)
        self.assertTrue(res["previewHiddenAfterClip"])
        self.assertTrue(res["closedAfterCopy"])
        self.assertTrue(res["previewShownFallback"])
        self.assertEqual(res["previewSrc"], "data:image/png;base64,MOCKIMG")
        self.assertTrue(res["previewClosed"])
        self.assertEqual(res["printCalled"], 1)

        with open(os.path.join(PROJECT_ROOT, "static", "styles.css"), "r", encoding="utf-8") as f:
            css_text = f.read()
        self.assertIn(".cal-share-menu-popover", css_text)
        self.assertIn("@media print", css_text)

    def test_share_menu_edge_cases_outside_click_escape_native_share_and_clipboard_reject(self):
        scenario = r"""
        const ctx = createIndexContext(async () => ({ ok: true, json: async () => ({ success: true }) }));
        await new Promise(r => setImmediate(r));
        await new Promise(r => setImmediate(r));

        const result = await vm.runInContext(`
          (async function() {
            const origCreate = document.createElement;
            document.createElement = (tag) => {
              if (tag === "canvas") {
                return {
                  width: 0,
                  height: 0,
                  getContext: () => ({
                    scale() {},
                    set fillStyle(v) {},
                    set strokeStyle(v) {},
                    set lineWidth(v) {},
                    set font(v) {},
                    set textAlign(v) {},
                    fillRect() {},
                    strokeRect() {},
                    fillText() {}
                  }),
                  toDataURL: () => "data:image/png;base64,MOCKEDGE",
                  toBlob: (cb) => cb({ type: "image/png", size: 8 })
                };
              }
              return origCreate(tag);
            };
            if (typeof navigator === "undefined") globalThis.navigator = {};
            globalThis.ClipboardItem = function(map) { this.map = map; };
            globalThis.File = function(parts, name, opts) {
              this.parts = parts;
              this.name = name;
              this.type = opts && opts.type ? opts.type : "";
            };

            AppState.calendar.shiftsByDate = {
              "2026-11-10": { date: "2026-11-10", day_of_week: "火", type: "早B", status: "work", start_time: "06:30", end_time: "15:30" },
              "2026-11-11": { date: "2026-11-11", day_of_week: "水", type: "休", status: "holiday", is_holiday: true }
            };
            AppState.calendar.viewYear = 2026;
            AppState.calendar.viewMonth = 11;
            AppState.calendar.activeTab = "calendar";

            const trigger = document.getElementById("btn-cal-share-menu");
            const popover = document.getElementById("cal-share-menu-popover");
            const copyTextBtn = document.getElementById("btn-cal-copy-text");
            const copyImageBtn = document.getElementById("btn-cal-copy-image");
            const nativeShareBtn = document.getElementById("btn-cal-native-share");
            const shareModeEl = document.getElementById("cal-share-mode");
            const previewModal = document.getElementById("cal-image-preview-modal");
            const toastEl = document.getElementById("toast");

            // 1a. 外クリックでドロップダウンが閉じる
            await trigger.dispatchAsync("click", { stopPropagation() {} });
            const openedBeforeOutside = popover.classList.contains("is-open");
            const outsideEl = document.createElement("div");
            await document.dispatchAsync("click", { target: outsideEl });
            const closedByOutsideClick = !popover.classList.contains("is-open");

            // 1b. Escape でドロップダウンが閉じる
            await trigger.dispatchAsync("click", { stopPropagation() {} });
            await document.dispatchAsync("keydown", { key: "Escape" });
            const closedMenuByEsc = !popover.classList.contains("is-open");

            // 2. clipboard.write() が Reject した場合にプレビューモーダルへフォールバック
            navigator.clipboard = {
              write: async () => { throw new Error("NotAllowedError"); },
              writeText: async (t) => { copiedText = t; }
            };
            let copiedText = "";
            await copyImageBtn.dispatchAsync("click");
            const previewOpenedOnReject = previewModal.style.display === "flex";

            // 1c. プレビューモーダル表示中は ArrowRight で月移動しない
            await document.dispatchAsync("keydown", { key: "ArrowRight" });
            const monthUnchangedWhileModalOpen = AppState.calendar.viewMonth === 11;

            // 1d. Escape でプレビューモーダルが閉じる
            await document.dispatchAsync("keydown", { key: "Escape" });
            const previewClosedByEsc = previewModal.style.display === "none";

            // 4b. プレビューモーダル背景クリックで閉じる
            await copyImageBtn.dispatchAsync("click");
            await previewModal.dispatchAsync("click", { target: previewModal });
            const previewClosedByOverlay = previewModal.style.display === "none";

            // 4a. メニュー経由「テキストをコピー」がセレクト値(off)に連動しメニューを閉じる
            await trigger.dispatchAsync("click", { stopPropagation() {} });
            shareModeEl.value = "off";
            await copyTextBtn.dispatchAsync("click");
            const menuClosedAfterCopyText = !popover.classList.contains("is-open");

            // 3a. OS共有: ファイル共有対応ルート
            const shareCalls = [];
            navigator.canShare = (arg) => Boolean(arg && arg.files && arg.files.length === 1);
            navigator.share = async (payload) => { shareCalls.push(payload); };
            await nativeShareBtn.dispatchAsync("click");
            const sharedFileName = shareCalls[0] && shareCalls[0].files ? shareCalls[0].files[0].name : "";

            // 3b. OS共有: ファイル共有非対応 → テキスト共有フォールバック
            navigator.canShare = () => false;
            await nativeShareBtn.dispatchAsync("click");
            const sharedFallbackText = shareCalls[1] ? shareCalls[1].text : "";

            // 3c. OS共有: AbortError（ユーザーキャンセル）時はエラートーストを出さない
            toastEl.className = "toast";
            toastEl.textContent = "";
            navigator.share = async () => {
              const err = new Error("User cancelled");
              err.name = "AbortError";
              throw err;
            };
            await nativeShareBtn.dispatchAsync("click");
            const abortToastClass = toastEl.className;
            const abortToastText = toastEl.textContent;

            return {
              openedBeforeOutside,
              closedByOutsideClick,
              closedMenuByEsc,
              previewOpenedOnReject,
              monthUnchangedWhileModalOpen,
              previewClosedByEsc,
              previewClosedByOverlay,
              menuClosedAfterCopyText,
              copiedText,
              sharedFileName,
              sharedFallbackText,
              abortToastClass,
              abortToastText
            };
          })();
        `, ctx);
        console.log(JSON.stringify(result));
        """
        rc, stdout, stderr = run_node_harness(scenario)
        self.assertEqual(rc, 0, msg=f"Node harness failed:\nSTDOUT:{stdout}\nSTDERR:{stderr}")
        res = json.loads(stdout.strip().splitlines()[-1])
        self.assertTrue(res["openedBeforeOutside"])
        self.assertTrue(res["closedByOutsideClick"])
        self.assertTrue(res["closedMenuByEsc"])
        self.assertTrue(res["previewOpenedOnReject"])
        self.assertTrue(res["monthUnchangedWhileModalOpen"])
        self.assertTrue(res["previewClosedByEsc"])
        self.assertTrue(res["previewClosedByOverlay"])
        self.assertTrue(res["menuClosedAfterCopyText"])
        self.assertIn("休み", res["copiedText"])
        self.assertNotIn("早B", res["copiedText"])
        self.assertEqual(res["sharedFileName"], "shift_calendar_2026_11.png")
        self.assertIn("休み", res["sharedFallbackText"])
        self.assertNotIn("error", res["abortToastClass"])
        self.assertEqual(res["abortToastText"], "")


if __name__ == "__main__":
    unittest.main()
