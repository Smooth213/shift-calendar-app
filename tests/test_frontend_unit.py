"""フロントエンド（static/*.js）の純粋関数を対象とした高速単体テスト（テストピラミッド底辺）"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")


_JS_UNIT_SUITE = r"""
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const staticDir = process.argv[2];

function createMinimalUnitSandbox() {
  const store = new Map();
  const noop = () => {};
  const fakeEl = {
    textContent: "",
    className: "",
    style: {},
    dataset: {},
    value: "",
    checked: true,
    classList: { add: noop, remove: noop, toggle: noop, contains: () => false },
    setAttribute: noop,
    addEventListener: noop,
    querySelectorAll: () => [],
    appendChild: noop,
  };
  const sandbox = {
    console,
    Math,
    Date,
    Number,
    String,
    Boolean,
    Array,
    Object,
    RegExp,
    JSON,
    Map,
    Set,
    Error,
    parseInt,
    parseFloat,
    isNaN,
    isFinite,
    setTimeout: () => 0,
    clearTimeout: noop,
    requestAnimationFrame: () => 0,
    cancelAnimationFrame: noop,
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
    },
    window: {
      matchMedia: () => ({ matches: false, addEventListener: noop }),
      addEventListener: noop,
      print: noop,
    },
    document: {
      documentElement: { setAttribute: noop },
      getElementById: () => fakeEl,
      querySelectorAll: () => [],
      createElement: () => ({ ...fakeEl }),
      addEventListener: noop,
    },
    navigator: {},
    fetch: async () => ({ ok: true, json: async () => ({}) }),
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);

  for (const fname of ["state.js", "time_picker.js", "calendar_tab.js", "calendar_canvas.js"]) {
    const code = fs.readFileSync(path.join(staticDir, fname), "utf8");
    vm.runInContext(code, sandbox, { filename: fname });
  }
  vm.runInContext("globalThis.__AppState = AppState;", sandbox);
  return sandbox;
}

const s = createMinimalUnitSandbox();

const cases = {
  clamp_int_valid_and_clamping() {
    assert.strictEqual(s.clampInt("15", 1, 1, 31), 15);
    assert.strictEqual(s.clampInt(0, 1, 1, 31), 1);
    assert.strictEqual(s.clampInt(99, 1, 1, 31), 31);
    assert.strictEqual(s.clampInt("12.9", 1, 1, 31), 12);
  },
  clamp_int_nan_and_non_numeric_fallback() {
    assert.strictEqual(s.clampInt("abc", 4, 1, 12), 4);
    assert.strictEqual(s.clampInt(null, 4, 1, 12), 4);
    assert.strictEqual(s.clampInt(undefined, 20, 0, 60), 20);
    assert.strictEqual(s.clampInt("", 8, 1, 24), 8);
  },
  clamp_half_hour_snapping_and_bounds() {
    assert.strictEqual(s.clampHalfHour(1.24, 0, 0, 8), 1);
    assert.strictEqual(s.clampHalfHour(1.26, 0, 0, 8), 1.5);
    assert.strictEqual(s.clampHalfHour(1.75, 0, 0, 8), 2);
    assert.strictEqual(s.clampHalfHour(-3, 0, 0, 8), 0);
    assert.strictEqual(s.clampHalfHour(12, 0, 0, 8), 8);
  },
  clamp_half_hour_negative_zero_and_nan() {
    const z = s.clampHalfHour(-0.1, 0, 0, 8);
    assert.strictEqual(Object.is(z, 0), true);
    assert.strictEqual(s.clampHalfHour("invalid", 7.5, 1, 24), 7.5);
    assert.strictEqual(s.clampHalfHour(NaN, 8, 1, 24), 8);
  },
  format_hours_num_integer_and_half() {
    assert.strictEqual(s.formatHoursNum(0), "0");
    assert.strictEqual(s.formatHoursNum(2), "2");
    assert.strictEqual(s.formatHoursNum(2.5), "2.5");
    assert.strictEqual(s.formatHoursNum(2.49), "2.5");
    assert.strictEqual(s.formatHoursNum("3.0"), "3");
  },
  format_paid_leave_days_and_hours_standard_8h() {
    assert.strictEqual(s.formatPaidLeaveDaysAndHours(16, 8), "1日 0時間");
    assert.strictEqual(s.formatPaidLeaveDaysAndHours(19, 8), "1日 1.5時間");
    assert.strictEqual(s.formatPaidLeaveDaysAndHours(35, 8), "2日 1.5時間");
    assert.strictEqual(s.formatPaidLeaveDaysAndHours(-5, 8), "0日 2.5時間");
  },
  format_paid_leave_days_and_hours_custom_hpd_and_zero() {
    assert.strictEqual(s.formatPaidLeaveDaysAndHours(0, 8), "0日 0時間");
    assert.strictEqual(s.formatPaidLeaveDaysAndHours(15, 7.5), "1日 0時間");
    assert.strictEqual(s.formatPaidLeaveDaysAndHours(16, 7.5), "1日 0.5時間");
  },
  apply_hourly_leave_to_summary_append_and_replace() {
    assert.strictEqual(
      s.applyHourlyLeaveToSummary("[日] (08:30〜17:30)", 1.5, "work"),
      "[日] (08:30〜17:30)（時間有給1.5h）"
    );
    assert.strictEqual(
      s.applyHourlyLeaveToSummary("[日] (08:30〜17:30)（時間有給1h）", 2.5, "work"),
      "[日] (08:30〜17:30)（時間有給2.5h）"
    );
    assert.strictEqual(
      s.applyHourlyLeaveToSummary("", 2, "work"),
      "時間有給2h"
    );
  },
  apply_hourly_leave_to_summary_remove_on_zero_or_holiday() {
    assert.strictEqual(
      s.applyHourlyLeaveToSummary("[日] (08:30〜17:30)（時間有給1.5h）", 0, "work"),
      "[日] (08:30〜17:30)"
    );
    assert.strictEqual(
      s.applyHourlyLeaveToSummary("休み (時間有給2h)", 2, "holiday"),
      "休み"
    );
  },
  format_apple_calendar_summary_work_with_hourly_leave() {
    const out = s.formatAppleCalendarShiftSummary(
      { status: "work", type: "早A", start_time: "06:00", end_time: "15:00", hourly_paid_leave: 1.5 },
      8
    );
    assert.strictEqual(out, "[早A] (06:00〜15:00)（時間有給1.5h）");
    const clamped = s.formatAppleCalendarShiftSummary(
      { status: "work", type: "日", start_time: "08:30", end_time: "17:30", hourly_paid_leave: 9.0 },
      8
    );
    assert.strictEqual(clamped, "[日] (08:30〜17:30)（時間有給7.5h）");
  },
  format_apple_calendar_summary_holiday_and_paid_leave() {
    assert.strictEqual(
      s.formatAppleCalendarShiftSummary({ status: "holiday", hourly_paid_leave: 2 }, 8),
      "休み"
    );
    assert.strictEqual(
      s.formatAppleCalendarShiftSummary({ is_paid_leave: true, hourly_paid_leave: 3 }, 8),
      "有給休暇"
    );
  },
  format_apple_calendar_summary_null_and_type_fallback() {
    assert.strictEqual(s.formatAppleCalendarShiftSummary(null), "");
    assert.strictEqual(s.formatAppleCalendarShiftSummary({ status: "work", type: "遅C" }), "遅C");
    assert.strictEqual(s.formatAppleCalendarShiftSummary({ status: "work" }), "出勤");
  },
  parse_shift_start_minutes_valid_boundaries() {
    assert.strictEqual(s.parseShiftStartMinutes("00:00"), 0);
    assert.strictEqual(s.parseShiftStartMinutes("6:30"), 390);
    assert.strictEqual(s.parseShiftStartMinutes("23:59"), 1439);
  },
  parse_shift_start_minutes_invalid_formats() {
    assert.strictEqual(s.parseShiftStartMinutes("24:00"), null);
    assert.strictEqual(s.parseShiftStartMinutes("08:60"), null);
    assert.strictEqual(s.parseShiftStartMinutes("0830"), null);
    assert.strictEqual(s.parseShiftStartMinutes(""), null);
    assert.strictEqual(s.parseShiftStartMinutes(null), null);
  },
  resolve_shift_tone_by_exact_type_and_status() {
    assert.strictEqual(s.resolveShiftTone("早A"), "early-a");
    assert.strictEqual(s.resolveShiftTone("日"), "day");
    assert.strictEqual(s.resolveShiftTone("遅C"), "late-c");
    assert.strictEqual(s.resolveShiftTone("休"), "holiday");
    assert.strictEqual(s.resolveShiftTone("有給休暇"), "paid");
  },
  resolve_shift_tone_by_start_time_boundaries() {
    assert.strictEqual(s.resolveShiftTone("カスタム", "06:14"), "early-a");
    assert.strictEqual(s.resolveShiftTone("カスタム", "06:15"), "early-b");
    assert.strictEqual(s.resolveShiftTone("カスタム", "06:45"), "early-c");
    assert.strictEqual(s.resolveShiftTone("カスタム", "07:30"), "early-d");
    assert.strictEqual(s.resolveShiftTone("カスタム", "08:15"), "day");
    assert.strictEqual(s.resolveShiftTone("カスタム", "08:45"), "late-a");
    assert.strictEqual(s.resolveShiftTone("カスタム", "09:15"), "late-b");
    assert.strictEqual(s.resolveShiftTone("カスタム", "09:45"), "late-c");
  },
  resolve_shift_tone_object_and_unknown_fallback() {
    assert.strictEqual(s.resolveShiftTone({ status: "holiday", type: "早A" }), "holiday");
    assert.strictEqual(s.resolveShiftTone({ is_paid_leave: true, type: "日" }), "paid");
    assert.strictEqual(s.resolveShiftTone({ status: "work", type: "特勤", start_time: "08:30" }), "day");
    assert.strictEqual(s.resolveShiftTone("未知区分", ""), "");
    assert.strictEqual(s.resolveShiftTone(null), "");
  },
  format_calendar_summary_lines_bracket_and_hourly() {
    assert.deepStrictEqual(
      Array.from(s.formatCalendarSummaryLines("[早A] (06:00〜15:00)（時間有給1.5h）")),
      ["[早A]", "(06:00〜15:00)", "（時間有給1.5h）"]
    );
    assert.deepStrictEqual(
      Array.from(s.formatCalendarSummaryLines("特勤 (09:00〜18:00)")),
      ["特勤", "(09:00〜18:00)"]
    );
  },
  format_calendar_summary_lines_plain_and_empty() {
    assert.deepStrictEqual(Array.from(s.formatCalendarSummaryLines("休み")), ["休み"]);
    assert.deepStrictEqual(Array.from(s.formatCalendarSummaryLines("  ")), []);
    assert.deepStrictEqual(Array.from(s.formatCalendarSummaryLines(null)), []);
  },
  build_hourly_leave_options_html_selected_and_max() {
    const html = s.buildHourlyLeaveOptionsHtml(1.5, 8);
    assert.ok(html.includes('<option value="0" >なし (0h)</option>'));
    assert.ok(html.includes('<option value="1.5" selected>1.5時間</option>'));
    assert.ok(html.includes('<option value="7.5" >7.5時間</option>'));
    assert.ok(!html.includes('value="8"'));
  },
  pad2_and_format_date_ymd() {
    assert.strictEqual(s.pad2(0), "00");
    assert.strictEqual(s.pad2(7), "07");
    assert.strictEqual(s.pad2(12), "12");
    assert.strictEqual(s.formatDateYMD(2026, 4, 5), "2026-04-05");
  },
  get_days_in_month_leap_and_common_years() {
    assert.strictEqual(s.getDaysInMonth(2024, 2), 29);
    assert.strictEqual(s.getDaysInMonth(2025, 2), 28);
    assert.strictEqual(s.getDaysInMonth(2026, 4), 30);
    assert.strictEqual(s.getDaysInMonth(2026, 12), 31);
  },
  escape_html_text_special_chars_and_nullish() {
    assert.strictEqual(
      s.escapeHtmlText(`<img src="x" onerror='a&b'>`),
      "&lt;img src=&quot;x&quot; onerror=&#39;a&amp;b&#39;&gt;"
    );
    assert.strictEqual(s.escapeHtmlText(null), "");
    assert.strictEqual(s.escapeHtmlText(undefined), "");
  },
  normalize_time_input_colon_and_fullwidth() {
    assert.strictEqual(s.normalizeTimeInputValue("8:5"), "08:05");
    assert.strictEqual(s.normalizeTimeInputValue("０９：３０"), "09:30");
    assert.strictEqual(s.normalizeTimeInputValue(" 23:59 "), "23:59");
    assert.strictEqual(s.normalizeTimeInputValue("0:0"), "00:00");
  },
  normalize_time_input_3digit_and_4digit() {
    assert.strictEqual(s.normalizeTimeInputValue("830"), "08:30");
    assert.strictEqual(s.normalizeTimeInputValue("0630"), "06:30");
    assert.strictEqual(s.normalizeTimeInputValue("１７３０"), "17:30");
  },
  normalize_time_input_empty_and_out_of_range() {
    assert.strictEqual(s.normalizeTimeInputValue("", true), "");
    assert.strictEqual(s.normalizeTimeInputValue("", false), null);
    assert.strictEqual(s.normalizeTimeInputValue("24:00"), null);
    assert.strictEqual(s.normalizeTimeInputValue("12:60"), null);
    assert.strictEqual(s.normalizeTimeInputValue("12"), null);
    assert.strictEqual(s.normalizeTimeInputValue("abc"), null);
  },
  compute_paid_leave_fiscal_period_before_and_after_start() {
    const before = s.computePaidLeaveFiscalPeriod(2026, 3, 4, 1);
    assert.strictEqual(before.startStr, "2025-04-01");
    assert.strictEqual(before.endStr, "2026-03-31");
    const after = s.computePaidLeaveFiscalPeriod(2026, 4, 4, 1);
    assert.strictEqual(after.startStr, "2026-04-01");
    assert.strictEqual(after.endStr, "2027-03-31");
  },
  compute_paid_leave_fiscal_period_leap_day_clamp() {
    const leap = s.computePaidLeaveFiscalPeriod(2025, 2, 2, 29);
    assert.strictEqual(leap.startStr, "2025-02-28");
    assert.strictEqual(leap.endStr, "2026-02-27");
  },
  compute_paid_leave_fiscal_period_jan_1_start() {
    const jan = s.computePaidLeaveFiscalPeriod(2026, 6, 1, 1);
    assert.strictEqual(jan.startStr, "2026-01-01");
    assert.strictEqual(jan.endStr, "2026-12-31");
  },
  get_shift_item_key_variants() {
    assert.strictEqual(s.getShiftItemKey(null), "その他");
    assert.strictEqual(s.getShiftItemKey({ status: "holiday", type: "日" }), "休");
    assert.strictEqual(s.getShiftItemKey({ is_paid_leave: true }), "有給");
    assert.strictEqual(s.getShiftItemKey({ status: "work", type: "早B" }), "早B");
    assert.strictEqual(s.getShiftItemKey({ status: "work" }), "その他");
  },
  build_monthly_share_text_all_mode() {
    s.__AppState.calendar.paidLeaveConfig = { startMonth: 4, startDay: 1, annualDays: 20, hoursPerDay: 8 };
    s.__AppState.calendar.shiftsByDate = {
      "2026-11-01": { status: "work", type: "早A", start_time: "06:00", end_time: "15:00", hourly_paid_leave: 1.5, event: "朝礼", memo: "鍵当番" },
      "2026-11-02": { status: "holiday" },
      "2026-11-03": { status: "paid_leave" },
      "2026-12-01": { status: "work", type: "日", start_time: "08:30", end_time: "17:30" },
    };
    const text = s.buildMonthlyShareText(2026, 11, "all");
    assert.ok(text.startsWith("2026年11月のシフト（全日程）"));
    assert.ok(text.includes("11/1(日) 早A (06:00〜15:00) [時間有給1.5h] / 行事:朝礼 / メモ:鍵当番"));
    assert.ok(text.includes("11/2(月) 休み"));
    assert.ok(text.includes("11/3(火) 有給休暇"));
    assert.ok(!text.includes("12/1"));
  },
  build_monthly_share_text_off_and_early_late_modes() {
    s.__AppState.calendar.shiftsByDate = {
      "2026-11-01": { status: "work", type: "早A", start_time: "06:00", end_time: "15:00" },
      "2026-11-02": { status: "work", type: "日", start_time: "08:30", end_time: "17:30" },
      "2026-11-03": { status: "work", type: "遅C", start_time: "10:00", end_time: "19:00" },
      "2026-11-04": { status: "holiday" },
    };
    const offText = s.buildMonthlyShareText(2026, 11, "off");
    assert.ok(offText.includes("11/4(水) 休み"));
    assert.ok(!offText.includes("早A"));
    const elText = s.buildMonthlyShareText(2026, 11, "early_late");
    assert.ok(elText.includes("早A"));
    assert.ok(elText.includes("遅C"));
    assert.ok(!elText.includes("11/2"));
    assert.ok(!elText.includes("休み"));
  },
  build_monthly_share_text_empty_month_returns_empty() {
    s.__AppState.calendar.shiftsByDate = {};
    assert.strictEqual(s.buildMonthlyShareText(2026, 11, "all"), "");
  },
  measure_canvas_text_width_with_and_without_measureText() {
    assert.strictEqual(s.measureCanvasTextWidth({ measureText: (t) => ({ width: t.length * 12 }) }, "abc"), 36);
    const approx = s.measureCanvasTextWidth({}, "あa", 10);
    assert.ok(Math.abs(approx - 15.6) < 0.01);
  },
  truncate_canvas_text_fits_and_ellipsis() {
    const ctx = { measureText: (t) => ({ width: t.length * 10 }) };
    assert.strictEqual(s.truncateCanvasText(ctx, "abcdef", 60), "abcdef");
    assert.strictEqual(s.truncateCanvasText(ctx, "abcdefghij", 50), "abcd…");
    assert.strictEqual(s.truncateCanvasText(ctx, "", 50), "");
  },
  truncate_canvas_text_fallback_without_measureText() {
    assert.strictEqual(s.truncateCanvasText({}, "12345", 100, 5), "12345");
    assert.strictEqual(s.truncateCanvasText({}, "123456", 100, 5), "1234…");
  },
};

const results = {};
for (const [name, fn] of Object.entries(cases)) {
  try {
    fn();
    results[name] = { ok: true };
  } catch (err) {
    results[name] = { ok: false, error: err && err.stack ? err.stack : String(err) };
  }
}
process.stdout.write(JSON.stringify(results));
"""


class TestFrontendUnit(unittest.TestCase):
    """static/*.js の純粋関数を個別ケースで高速検証するJS単体テスト"""

    _results = {}

    @classmethod
    def setUpClass(cls):
        node_bin = shutil.which("node")
        if not node_bin:
            raise unittest.SkipTest("node が見つからないためフロントエンドJS単体テストをスキップ")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as f:
            f.write(_JS_UNIT_SUITE)
            script_path = f.name
        try:
            proc = subprocess.run(
                [node_bin, script_path, STATIC_DIR],
                capture_output=True,
                text=True,
                timeout=15,
            )
        finally:
            if os.path.exists(script_path):
                os.remove(script_path)

        if proc.returncode != 0:
            raise AssertionError(f"JS unit runner failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
        cls._results = json.loads(proc.stdout)

    def _assert_js_case(self, case_name):
        self.assertIn(case_name, self._results, f"JS case '{case_name}' not found in runner output")
        res = self._results[case_name]
        self.assertTrue(res.get("ok"), f"JS unit case '{case_name}' failed:\n{res.get('error')}")

    def test_01_clamp_int_valid_and_clamping(self):
        self._assert_js_case("clamp_int_valid_and_clamping")

    def test_02_clamp_int_nan_and_non_numeric_fallback(self):
        self._assert_js_case("clamp_int_nan_and_non_numeric_fallback")

    def test_03_clamp_half_hour_snapping_and_bounds(self):
        self._assert_js_case("clamp_half_hour_snapping_and_bounds")

    def test_04_clamp_half_hour_negative_zero_and_nan(self):
        self._assert_js_case("clamp_half_hour_negative_zero_and_nan")

    def test_05_format_hours_num_integer_and_half(self):
        self._assert_js_case("format_hours_num_integer_and_half")

    def test_06_format_paid_leave_days_and_hours_standard_8h(self):
        self._assert_js_case("format_paid_leave_days_and_hours_standard_8h")

    def test_07_format_paid_leave_days_and_hours_custom_hpd_and_zero(self):
        self._assert_js_case("format_paid_leave_days_and_hours_custom_hpd_and_zero")

    def test_08_apply_hourly_leave_to_summary_append_and_replace(self):
        self._assert_js_case("apply_hourly_leave_to_summary_append_and_replace")

    def test_09_apply_hourly_leave_to_summary_remove_on_zero_or_holiday(self):
        self._assert_js_case("apply_hourly_leave_to_summary_remove_on_zero_or_holiday")

    def test_10_format_apple_calendar_summary_work_with_hourly_leave(self):
        self._assert_js_case("format_apple_calendar_summary_work_with_hourly_leave")

    def test_11_format_apple_calendar_summary_holiday_and_paid_leave(self):
        self._assert_js_case("format_apple_calendar_summary_holiday_and_paid_leave")

    def test_12_format_apple_calendar_summary_null_and_type_fallback(self):
        self._assert_js_case("format_apple_calendar_summary_null_and_type_fallback")

    def test_13_parse_shift_start_minutes_valid_boundaries(self):
        self._assert_js_case("parse_shift_start_minutes_valid_boundaries")

    def test_14_parse_shift_start_minutes_invalid_formats(self):
        self._assert_js_case("parse_shift_start_minutes_invalid_formats")

    def test_15_resolve_shift_tone_by_exact_type_and_status(self):
        self._assert_js_case("resolve_shift_tone_by_exact_type_and_status")

    def test_16_resolve_shift_tone_by_start_time_boundaries(self):
        self._assert_js_case("resolve_shift_tone_by_start_time_boundaries")

    def test_17_resolve_shift_tone_object_and_unknown_fallback(self):
        self._assert_js_case("resolve_shift_tone_object_and_unknown_fallback")

    def test_18_format_calendar_summary_lines_bracket_and_hourly(self):
        self._assert_js_case("format_calendar_summary_lines_bracket_and_hourly")

    def test_19_format_calendar_summary_lines_plain_and_empty(self):
        self._assert_js_case("format_calendar_summary_lines_plain_and_empty")

    def test_20_build_hourly_leave_options_html_selected_and_max(self):
        self._assert_js_case("build_hourly_leave_options_html_selected_and_max")

    def test_21_pad2_and_format_date_ymd(self):
        self._assert_js_case("pad2_and_format_date_ymd")

    def test_22_get_days_in_month_leap_and_common_years(self):
        self._assert_js_case("get_days_in_month_leap_and_common_years")

    def test_23_escape_html_text_special_chars_and_nullish(self):
        self._assert_js_case("escape_html_text_special_chars_and_nullish")

    def test_24_normalize_time_input_colon_and_fullwidth(self):
        self._assert_js_case("normalize_time_input_colon_and_fullwidth")

    def test_25_normalize_time_input_3digit_and_4digit(self):
        self._assert_js_case("normalize_time_input_3digit_and_4digit")

    def test_26_normalize_time_input_empty_and_out_of_range(self):
        self._assert_js_case("normalize_time_input_empty_and_out_of_range")

    def test_27_compute_paid_leave_fiscal_period_before_and_after_start(self):
        self._assert_js_case("compute_paid_leave_fiscal_period_before_and_after_start")

    def test_28_compute_paid_leave_fiscal_period_leap_day_clamp(self):
        self._assert_js_case("compute_paid_leave_fiscal_period_leap_day_clamp")

    def test_29_compute_paid_leave_fiscal_period_jan_1_start(self):
        self._assert_js_case("compute_paid_leave_fiscal_period_jan_1_start")

    def test_30_get_shift_item_key_variants(self):
        self._assert_js_case("get_shift_item_key_variants")

    def test_31_build_monthly_share_text_all_mode(self):
        self._assert_js_case("build_monthly_share_text_all_mode")

    def test_32_build_monthly_share_text_off_and_early_late_modes(self):
        self._assert_js_case("build_monthly_share_text_off_and_early_late_modes")

    def test_33_build_monthly_share_text_empty_month_returns_empty(self):
        self._assert_js_case("build_monthly_share_text_empty_month_returns_empty")

    def test_34_measure_canvas_text_width_with_and_without_measureText(self):
        self._assert_js_case("measure_canvas_text_width_with_and_without_measureText")

    def test_35_truncate_canvas_text_fits_and_ellipsis(self):
        self._assert_js_case("truncate_canvas_text_fits_and_ellipsis")

    def test_36_truncate_canvas_text_fallback_without_measureText(self):
        self._assert_js_case("truncate_canvas_text_fallback_without_measureText")


if __name__ == "__main__":
    unittest.main()
