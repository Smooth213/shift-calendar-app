import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import app


class TestHistoryRetention(unittest.TestCase):
    """登録済み履歴の保持＋未登録履歴の直近5件制限およびUI区別の検証"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.orig_history_dir = app.HISTORY_DIR
        app.HISTORY_DIR = self.tmpdir.name

    def tearDown(self):
        app.HISTORY_DIR = self.orig_history_dir
        self.tmpdir.cleanup()

    def _sample_shift(self, date_str="2026-12-01", shift_type="早A"):
        return {
            "date": date_str,
            "shift_type": shift_type,
            "start_time": "06:00",
            "end_time": "15:00",
            "event": "",
        }

    def test_01_unregistered_history_pruned_to_latest_five(self):
        """未登録履歴を7件保存すると直近5件のみ残り、古い2件はJSONごと自動削除されること"""
        saved_ids = []
        for i in range(1, 8):
            hid = app.save_history({
                "id": f"20261120_10000{i}",
                "created_at": f"2026-11-20 10:00:0{i}",
                "title": f"2026年11月度_{i}",
                "target_name": "皿田",
                "shifts": [self._sample_shift()],
                "image_base64": "data:image/jpeg;base64,/9j/4AAQ",
            })
            saved_ids.append(hid)

        files = sorted(os.listdir(self.tmpdir.name))
        self.assertEqual(len(files), 5)
        expected = [f"20261120_10000{i}.json" for i in range(3, 8)]
        self.assertEqual(files, expected)

        hist_list = app.get_history_list()
        self.assertEqual(len(hist_list), 5)
        self.assertTrue(all(item["registered"] is False for item in hist_list))

    def test_02_registered_history_never_pruned_and_kept_distinct(self):
        """登録済み履歴は何件あっても削除されず、未登録履歴だけが直近5件に制限されること"""
        # 登録済みを6件作成（古い日付）
        for i in range(1, 7):
            hid = app.save_history({
                "id": f"2026100{i}_090000",
                "created_at": f"2026-10-0{i} 09:00:00",
                "title": f"2026年{i}月度",
                "target_name": "皿田",
                "shifts": [self._sample_shift()],
                "image_base64": "data:image/jpeg;base64,AAA",
            })
            app.mark_history_registered(hid)

        # 未登録を7件追加
        for i in range(1, 8):
            app.save_history({
                "id": f"20261121_11000{i}",
                "created_at": f"2026-11-21 11:00:0{i}",
                "title": f"未登録_{i}",
                "target_name": "皿田",
                "shifts": [self._sample_shift()],
                "image_base64": "data:image/jpeg;base64,BBB",
            })

        hist_list = app.get_history_list()
        registered = [h for h in hist_list if h["registered"]]
        unregistered = [h for h in hist_list if not h["registered"]]

        self.assertEqual(len(registered), 6)
        self.assertEqual(len(unregistered), 5)
        self.assertEqual(len(hist_list), 11)
        self.assertTrue(all(bool(h["registered_at"]) for h in registered))
        self.assertEqual(
            sorted(h["id"] for h in unregistered),
            [f"20261121_11000{i}" for i in range(3, 8)],
        )

    def test_03_mark_history_registered_updates_edited_shifts_and_keeps_image(self):
        """カレンダー登録昇格時に手動修正後のシフトが上書き保存され、元画像も保持されること"""
        hid = app.save_history({
            "id": "20261121_120000",
            "created_at": "2026-11-21 12:00:00",
            "title": "2026年12月度",
            "target_name": "皿田",
            "shifts": [self._sample_shift("2026-12-01", "早A")],
            "image_base64": "data:image/jpeg;base64,ORIGINAL_IMG",
            "mime_type": "image/jpeg",
            "image_name": "shift.jpg",
        })

        updated_id = app.mark_history_registered(
            hid,
            {
                "title": "2026年12月度",
                "target_name": "皿田",
                "shifts": [self._sample_shift("2026-12-01", "遅B")],
            },
        )
        self.assertEqual(updated_id, hid)

        detail = app.get_history_detail(hid)
        self.assertTrue(detail["registered"])
        self.assertTrue(bool(detail["registered_at"]))
        self.assertEqual(detail["shifts"][0]["shift_type"], "遅B")
        self.assertEqual(detail["image_base64"], "data:image/jpeg;base64,ORIGINAL_IMG")

    def test_04_legacy_json_without_registered_flag_pruned_as_unregistered(self):
        """registeredキーを持たない旧形式JSONも未登録扱いで直近5件に整理されること"""
        for i in range(1, 9):
            fname = f"20261119_08000{i}.json"
            with open(os.path.join(self.tmpdir.name, fname), "w", encoding="utf-8") as f:
                json.dump({
                    "id": fname[:-5],
                    "created_at": f"2026-11-19 08:00:0{i}",
                    "title": f"旧履歴_{i}",
                    "shifts": [self._sample_shift()],
                }, f)

        deleted = app.prune_unregistered_history(5)
        self.assertEqual(len(deleted), 3)
        remaining = sorted(os.listdir(self.tmpdir.name))
        self.assertEqual(remaining, [f"20261119_08000{i}.json" for i in range(4, 9)])

    def test_05_ui_groups_registered_and_unregistered_and_promotes_on_register(self):
        """実際のindex.htmlスクリプトで登録済/未登録のグループ分け表示と登録時昇格・ics非昇格を検証"""
        with open(os.path.join(BASE_DIR, "index.html"), "r", encoding="utf-8") as f:
            html = f.read()

        scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, flags=re.S)
        script_code = max(scripts, key=len)

        node_runner = r"""
const fs = require("fs");
const vm = require("vm");

const scriptPath = process.argv[2];
const scriptCode = fs.readFileSync(scriptPath, "utf8");

class MockElement {
  constructor(tag, id = "") {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.children = [];
    this.listeners = {};
    this.style = {};
    this.className = "";
    this.textContent = "";
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this.label = "";
    this.dataset = {};
    this.attributes = {};
    this._innerHTML = "";
    this.classList = {
      _set: new Set(),
      add: (...cls) => cls.forEach(c => this.classList._set.add(c)),
      remove: (...cls) => cls.forEach(c => this.classList._set.delete(c)),
      toggle: (c, force) => {
        if (force === undefined) {
          if (this.classList._set.has(c)) this.classList._set.delete(c);
          else this.classList._set.add(c);
        } else if (force) this.classList._set.add(c);
        else this.classList._set.delete(c);
      },
      contains: (c) => this.classList._set.has(c),
    };
  }
  set innerHTML(val) {
    this._innerHTML = String(val);
    this.children = [];
  }
  get innerHTML() { return this._innerHTML; }
  appendChild(child) {
    this.children.push(child);
    return child;
  }
  removeChild(child) {
    this.children = this.children.filter(c => c !== child);
    return child;
  }
  addEventListener(ev, fn) {
    if (!this.listeners[ev]) this.listeners[ev] = [];
    this.listeners[ev].push(fn);
  }
  async dispatchAsync(ev, extra = {}) {
    const fns = this.listeners[ev] || [];
    for (const fn of fns) {
      await fn({ target: this, preventDefault: () => {}, stopPropagation: () => {}, ...extra });
    }
  }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  getBoundingClientRect() { return { width: 100, height: 100, top: 0, left: 0 }; }
  setAttribute(k, v) { this.attributes[k] = v; }
  getAttribute(k) { return this.attributes[k] || null; }
  focus() {}
  select() {}
  click() {}
  scrollIntoView() {}
}

const elMap = new Map();
function getEl(id, tag = "div") {
  if (!elMap.has(id)) {
    const el = new MockElement(tag, id);
    if (id === "target-name") el.value = "皿田";
    if (id === "calendar-name") el.value = "シフトカレンダー";
    if (id === "api-key") el.value = "dummy-key";
    if (id === "include-events-toggle") el.checked = true;
    elMap.set(id, el);
  }
  return elMap.get(id);
}

const documentMock = {
  getElementById: (id) => getEl(id),
  createElement: (tag) => new MockElement(tag),
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  documentElement: new MockElement("html"),
  body: new MockElement("body"),
};

let historyStore = [
  {
    id: "h_reg_1",
    title: "2026年11月度",
    created_at: "2026-11-01 10:00:00",
    registered: true,
    registered_at: "2026-11-01 10:05:00",
    target_name: "皿田",
    shifts_count: 30,
    shifts: [{ date: "2026-11-01", shift_type: "早A", start_time: "06:00", end_time: "15:00", event: "" }],
    image_base64: "data:image/jpeg;base64,REG1",
  },
  {
    id: "h_unreg_1",
    title: "2026年12月度",
    created_at: "2026-11-21 10:30:00",
    registered: false,
    registered_at: "",
    target_name: "皿田",
    shifts_count: 31,
    shifts: [{ date: "2026-12-01", shift_type: "日", start_time: "08:30", end_time: "17:30", event: "" }],
    image_base64: "data:image/jpeg;base64,UNREG1",
  }
];

const registerPayloads = [];
let icsCallCount = 0;

const fetchMock = async (url, opts = {}) => {
  if (url === "/api/config") {
    return { ok: true, json: async () => ({ api_key: "dummy-key", default_name: "皿田", calendar_name: "シフトカレンダー", theme: "system", time_definitions: {} }) };
  }
  if (url === "/api/preload") {
    return { ok: true, json: async () => ({ has_image: false }) };
  }
  if (url === "/api/history") {
    return {
      ok: true,
      json: async () => ({
        history: historyStore.map(h => ({
          id: h.id,
          title: h.title,
          created_at: h.created_at,
          registered: h.registered,
          registered_at: h.registered_at,
          target_name: h.target_name,
          shifts_count: h.shifts_count,
          has_image: Boolean(h.image_base64),
          image_name: ""
        }))
      })
    };
  }
  if (url.startsWith("/api/history/detail?id=")) {
    const id = url.split("id=")[1];
    const found = historyStore.find(h => h.id === id);
    return { ok: true, json: async () => ({ success: true, data: found }) };
  }
  if (url === "/api/register") {
    const body = JSON.parse(opts.body);
    registerPayloads.push(body);
    const target = historyStore.find(h => h.id === body.history_id);
    if (target) {
      target.registered = true;
      target.registered_at = "2026-11-21 11:15:00";
    }
    return {
      ok: true,
      json: async () => ({
        success: true,
        count: body.shifts.length,
        message: "ok",
        history_id: body.history_id,
        registered_at: "2026-11-21 11:15:00"
      })
    };
  }
  if (url === "/api/export_ics") {
    icsCallCount += 1;
    return { ok: true, blob: async () => ({}) };
  }
  return { ok: true, json: async () => ({ success: true }) };
};

const sandbox = {
  document: documentMock,
  window: {
    addEventListener: () => {},
    matchMedia: () => ({ matches: false, addEventListener: () => {} }),
    URL: { createObjectURL: () => "blob:mock", revokeObjectURL: () => {} },
    location: { protocol: "http:", hostname: "127.0.0.1", port: "8765" },
  },
  navigator: { userAgent: "Mozilla/5.0 (Macintosh)", sendBeacon: () => true },
  localStorage: { getItem: () => null, setItem: () => {} },
  fetch: fetchMock,
  console,
  setTimeout,
  clearTimeout,
  setInterval: () => 1,
  clearInterval: () => {},
  confirm: () => true,
  Image: class {},
  FileReader: class {},
};
sandbox.globalThis = sandbox;

vm.createContext(sandbox);
vm.runInContext(scriptCode + `
  globalThis.__loadHistoryList = loadHistoryList;
  globalThis.__getSelectedShifts = () => analyzedShifts;
  globalThis.__overrideGetSelected = () => {
    getSelectedShifts = () => analyzedShifts;
  };
`, sandbox);

(async () => {
  await sandbox.__loadHistoryList();

  const select = getEl("history-select");
  const badgeBefore = getEl("history-count-badge").textContent;
  const groupsBefore = select.children.map(g => ({
    tag: g.tagName,
    label: g.label,
    options: g.children.map(o => ({ value: o.value, text: o.textContent }))
  }));

  // 未登録履歴を読み込む
  select.value = "h_unreg_1";
  await getEl("btn-load-history").dispatchAsync("click");
  const activeTextUnreg = getEl("history-active-text").textContent;

  // getSelectedShifts をモックDOM向けにバイパス
  sandbox.__overrideGetSelected();

  // 1) .ics 出力しても登録済みに変わらないこと
  await getEl("btn-export-ics").dispatchAsync("click");
  const registeredAfterIcs = historyStore.find(h => h.id === "h_unreg_1").registered;

  // 2) Appleカレンダー登録を押すと登録済みに昇格し、UIが即更新されること
  await getEl("btn-register").dispatchAsync("click");
  const badgeAfter = getEl("history-count-badge").textContent;
  const activeTextReg = getEl("history-active-text").textContent;
  const groupsAfter = select.children.map(g => ({
    tag: g.tagName,
    label: g.label,
    options: g.children.map(o => ({ value: o.value, text: o.textContent }))
  }));

  console.log(JSON.stringify({
    badgeBefore,
    groupsBefore,
    activeTextUnreg,
    icsCallCount,
    registeredAfterIcs,
    registerPayloadsCount: registerPayloads.length,
    sentHistoryId: registerPayloads[0] && registerPayloads[0].history_id,
    badgeAfter,
    activeTextReg,
    groupsAfter
  }));
})();
"""
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as sf:
            sf.write(script_code)
            script_path = sf.name
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as rf:
            rf.write(node_runner)
            runner_path = rf.name

        try:
            proc = subprocess.run(
                ["node", runner_path, script_path],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode != 0:
                self.fail(f"Node runner failed (code={proc.returncode}):\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
            result = json.loads(proc.stdout.strip().splitlines()[-1])
        finally:
            os.remove(script_path)
            os.remove(runner_path)

        # 初期状態: 登録済1件 / 未登録1件、optgroupで2グループに分かれる
        self.assertEqual(result["badgeBefore"], "登録済 1件 / 未登録 1件")
        self.assertEqual(len(result["groupsBefore"]), 2)
        self.assertEqual(result["groupsBefore"][0]["tag"], "OPTGROUP")
        self.assertEqual(result["groupsBefore"][0]["label"], "登録済み")
        self.assertIn("[登録済]", result["groupsBefore"][0]["options"][0]["text"])
        self.assertEqual(result["groupsBefore"][1]["label"], "未登録（直近5件）")
        self.assertIn("[未登録]", result["groupsBefore"][1]["options"][0]["text"])

        # 未登録履歴読み込みバナー
        self.assertIn("【未登録履歴】", result["activeTextUnreg"])

        # .ics 出力では登録済みに昇格しない
        self.assertEqual(result["icsCallCount"], 1)
        self.assertFalse(result["registeredAfterIcs"])

        # カレンダー登録成功で登録済みに昇格し、UIが即更新される
        self.assertEqual(result["registerPayloadsCount"], 1)
        self.assertEqual(result["sentHistoryId"], "h_unreg_1")
        self.assertEqual(result["badgeAfter"], "登録済 2件 / 未登録 0件")
        self.assertIn("【登録済み履歴】", result["activeTextReg"])
        self.assertEqual(len(result["groupsAfter"]), 1)
        self.assertEqual(result["groupsAfter"][0]["label"], "登録済み")
        self.assertEqual(len(result["groupsAfter"][0]["options"]), 2)

    def _invoke_post(self, path, payload):
        """ソケットを使わずに RequestHandler.do_POST をインメモリで実行する"""
        raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        handler = app.RequestHandler.__new__(app.RequestHandler)
        handler.path = path
        handler.headers = {"Content-Length": str(len(raw_body))}
        handler.rfile = io.BytesIO(raw_body)
        handler.wfile = io.BytesIO()
        captured = {"status": None, "headers": {}, "json": None}

        def fake_send_json(data, status=200):
            captured["status"] = status
            captured["json"] = data

        def fake_send_response(code, message=None):
            captured["status"] = code

        def fake_send_header(k, v):
            captured["headers"][k] = v

        handler._send_json = fake_send_json
        handler.send_response = fake_send_response
        handler.send_header = fake_send_header
        handler.end_headers = lambda: None

        handler.do_POST()
        captured["raw_body"] = handler.wfile.getvalue()
        return captured

    def test_06_api_register_endpoint_promotes_history_and_failure_does_not(self):
        """/api/register が成功時のみ履歴を登録済みに昇格し、失敗時は未登録のまま維持すること"""
        hid = app.save_history({
            "id": "20261121_130000",
            "created_at": "2026-11-21 13:00:00",
            "title": "2026年12月度",
            "target_name": "皿田",
            "shifts": [self._sample_shift("2026-12-01", "早A")],
            "image_base64": "data:image/jpeg;base64,REG_TEST_IMG",
        })

        # 1) Appleカレンダー登録が失敗した場合は HTTP 500 となり未登録のまま
        with patch.object(app, "register_to_apple_calendar", side_effect=RuntimeError("Calendar error")):
            with patch("traceback.print_exc"):
                res_err = self._invoke_post("/api/register", {
                    "shifts": [self._sample_shift("2026-12-01", "遅C")],
                    "calendar_name": "シフトカレンダー",
                    "history_id": hid,
                    "history_payload": {
                        "title": "2026年12月度",
                        "target_name": "皿田",
                        "shifts": [self._sample_shift("2026-12-01", "遅C")],
                    },
                })
        self.assertEqual(res_err["status"], 500)
        detail_after_err = app.get_history_detail(hid)
        self.assertFalse(detail_after_err["registered"])
        self.assertEqual(detail_after_err["shifts"][0]["shift_type"], "早A")

        # 2) Appleカレンダー登録が成功した場合は登録済みへ昇格し修正シフト・画像が保持される
        with patch.object(app, "register_to_apple_calendar", return_value=(1, "ok")):
            res_ok = self._invoke_post("/api/register", {
                "shifts": [self._sample_shift("2026-12-01", "遅C")],
                "calendar_name": "シフトカレンダー",
                "history_id": hid,
                "history_payload": {
                    "title": "2026年12月度",
                    "target_name": "皿田",
                    "shifts": [self._sample_shift("2026-12-01", "遅C")],
                },
            })
        self.assertEqual(res_ok["status"], 200)
        self.assertTrue(res_ok["json"]["success"])
        self.assertEqual(res_ok["json"]["history_id"], hid)
        self.assertTrue(bool(res_ok["json"]["registered_at"]))

        detail_after_ok = app.get_history_detail(hid)
        self.assertTrue(detail_after_ok["registered"])
        self.assertEqual(detail_after_ok["registered_at"], res_ok["json"]["registered_at"])
        self.assertEqual(detail_after_ok["shifts"][0]["shift_type"], "遅C")
        self.assertEqual(detail_after_ok["image_base64"], "data:image/jpeg;base64,REG_TEST_IMG")

    def test_07_api_export_ics_endpoint_does_not_promote_history(self):
        """/api/export_ics を実行しても未登録履歴が登録済みへ昇格しないこと"""
        hid = app.save_history({
            "id": "20261121_131000",
            "created_at": "2026-11-21 13:10:00",
            "title": "2026年12月度",
            "target_name": "皿田",
            "shifts": [self._sample_shift("2026-12-02", "日")],
            "image_base64": "data:image/jpeg;base64,ICS_IMG",
        })

        res = self._invoke_post("/api/export_ics", {
            "shifts": [self._sample_shift("2026-12-02", "日")],
            "calendar_name": "シフトカレンダー",
            "include_events": True,
        })
        self.assertEqual(res["status"], 200)
        self.assertIn(b"BEGIN:VCALENDAR", res["raw_body"])

        detail = app.get_history_detail(hid)
        self.assertFalse(detail["registered"])
        self.assertEqual(detail["registered_at"], "")

    def test_08_corrupted_json_skipped_safely_and_same_second_id_no_collision(self):
        """破損JSONがあってもクラッシュせず誤削除しないこと、同一秒連続保存でID衝突しないこと"""
        broken_path = os.path.join(self.tmpdir.name, "broken.json")
        with open(broken_path, "w", encoding="utf-8") as f:
            f.write("{invalid json")

        # 同一秒を固定して7回新規保存（ID未指定）
        with patch("app.time.strftime", return_value="20261121_140000"):
            created_ids = []
            for i in range(7):
                hid = app.save_history({
                    "created_at": f"2026-11-21 14:00:0{i}",
                    "title": f"連続_{i}",
                    "shifts": [self._sample_shift()],
                })
                created_ids.append(hid)

        # 5件連続保存まではすべて別IDで衝突上書きしないこと
        self.assertEqual(len(set(created_ids[:5])), 5)
        # 破損JSONは誤削除されず残ること
        self.assertTrue(os.path.exists(broken_path))
        # 正常な未登録履歴は直近5件（連続_2〜連続_6）のみが上書きされずに残ること
        hist_list = app.get_history_list()
        self.assertEqual(len(hist_list), 5)
        self.assertEqual(
            sorted(h["title"] for h in hist_list),
            [f"連続_{i}" for i in range(2, 7)],
        )

    def test_09_reuse_id_update_preserves_registered_status_and_image(self):
        """登録済み履歴を同一IDで上書き更新（行事再取得など）しても登録済み状態と元画像が維持されること"""
        hid = app.save_history({
            "id": "20261121_150000",
            "created_at": "2026-11-21 15:00:00",
            "title": "2026年12月度",
            "target_name": "皿田",
            "shifts": [self._sample_shift("2026-12-03", "早B")],
            "image_base64": "data:image/jpeg;base64,KEEP_ME",
            "mime_type": "image/jpeg",
            "image_name": "dec.jpg",
        })
        app.mark_history_registered(hid)
        before_reg_at = app.get_history_detail(hid)["registered_at"]

        # 行事再取得のような同一ID上書き（registeredキーもimage_base64も未指定）
        updated_shift = self._sample_shift("2026-12-03", "早B")
        updated_shift["event"] = "主任会議"
        app.save_history({
            "id": hid,
            "title": "2026年12月度",
            "target_name": "皿田",
            "shifts": [updated_shift],
        })

        after = app.get_history_detail(hid)
        self.assertTrue(after["registered"])
        self.assertEqual(after["registered_at"], before_reg_at)
        self.assertEqual(after["image_base64"], "data:image/jpeg;base64,KEEP_ME")
        self.assertEqual(after["shifts"][0]["event"], "主任会議")
        self.assertEqual(len(app.get_history_list()), 1)


if __name__ == "__main__":
    unittest.main()
