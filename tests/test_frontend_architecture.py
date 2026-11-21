import json
import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.dom_harness import check_index_js_syntax, run_node_harness


class TestPhase3BFrontendArchitecture(unittest.TestCase):
    def test_01_index_html_js_syntax_is_valid(self):
        """index.html 内の <script> に構文エラーがないこと"""
        rc, out, err = check_index_js_syntax()
        self.assertEqual(rc, 0, msg=f"JS syntax error: {err}\n{out}")

    def test_02_app_state_domains_are_two_way_synced_and_snapshot_works(self):
        """AppState の5ドメインが既存状態変数と双方向同期し、snapshot() が全ドメインを返すこと"""
        test_js = r"""
        const ctx = createIndexContext();
        const result = vm.runInContext(`
          AppState.viewer.scale = 2.5;
          AppState.viewer.panX = 120;
          calendarViewYear = 2027;
          calendarViewMonth = 3;
          AppState.history.currentId = "hist_abc";
          AppState.analysis.isAnalyzing = true;
          AppState.ui.activeHighlightKey = "早A";
          JSON.stringify({
            legacyScale: scale,
            legacyPanX: panX,
            stateYear: AppState.calendar.viewYear,
            stateMonth: AppState.calendar.viewMonth,
            legacyHistId: currentHistoryId,
            legacyAnalyzing: isAnalyzing,
            legacyHighlight: activeHighlightKey,
            snap: AppState.snapshot(),
          });
        `, ctx);
        console.log(result);
        """
        rc, out, err = run_node_harness(test_js)
        self.assertEqual(rc, 0, msg=f"Node harness failed: {err}")
        data = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(data["legacyScale"], 2.5)
        self.assertEqual(data["legacyPanX"], 120)
        self.assertEqual(data["stateYear"], 2027)
        self.assertEqual(data["stateMonth"], 3)
        self.assertEqual(data["legacyHistId"], "hist_abc")
        self.assertTrue(data["legacyAnalyzing"])
        self.assertEqual(data["legacyHighlight"], "早A")
        self.assertEqual(data["snap"]["viewer"]["scale"], 2.5)
        self.assertEqual(data["snap"]["history"]["currentId"], "hist_abc")
        self.assertEqual(data["snap"]["calendar"]["viewYear"], 2027)
        self.assertEqual(data["snap"]["ui"]["activeHighlightKey"], "早A")

    def test_03_api_client_get_and_post_json_work(self):
        """ApiClient.getJson / postJson が期待通りのリクエスト形式で fetch を呼ぶこと"""
        test_js = r"""
        const calls = [];
        const ctx = createIndexContext(async (url, opts) => {
          calls.push({ url, opts: opts || null });
          return { ok: true, json: async () => ({ echoedUrl: url, ok: true }) };
        });
        const out = await vm.runInContext(`
          (async () => {
            const g = await ApiClient.getJson("/api/heartbeat");
            const p = await ApiClient.postJson("/api/config", { theme: "dark" });
            return { g, pData: p.data };
          })()
        `, ctx);
        console.log(JSON.stringify({ out, calls }));
        """
        rc, out, err = run_node_harness(test_js)
        self.assertEqual(rc, 0, msg=f"Node harness failed: {err}")
        payload = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(payload["out"]["g"]["echoedUrl"], "/api/heartbeat")
        self.assertEqual(payload["out"]["pData"]["echoedUrl"], "/api/config")
        post_call = [c for c in payload["calls"] if c["url"] == "/api/config"][-1]
        self.assertEqual(post_call["opts"]["method"], "POST")
        self.assertEqual(json.loads(post_call["opts"]["body"]), {"theme": "dark"})

    def test_04_no_direct_fetch_outside_api_client(self):
        """index.html 内の全API通信が ApiClient 経由に統一されており、外部に直接 fetch() が残っていないこと"""
        import re
        from tests.dom_harness import extract_index_script

        script = extract_index_script()
        api_client_block = re.search(r"const ApiClient\s*=\s*\{[\s\S]*?\n    \};", script)
        self.assertIsNotNone(api_client_block, "ApiClient 定義が見つかりません")
        outside = script[:api_client_block.start()] + script[api_client_block.end():]
        direct_fetches = re.findall(r"\bfetch\s*\(", outside)
        self.assertEqual(direct_fetches, [], msg=f"ApiClient 外に直接 fetch() が残っています: {len(direct_fetches)}件")

    def test_05_legend_renderer_escapes_html_special_chars(self):
        """renderMasterDefs が特殊文字を含む区分名をエスケープして描画すること"""
        test_js = r"""
        const ctx = createIndexContext();
        const html = vm.runInContext(`
          renderMasterDefs({ '<img src=x>': { start: '08:00', end: '17:00' } });
          const cont = document.getElementById("defs-container");
          cont.children.map(c => c.innerHTML).join("|");
        `, ctx);
        console.log(JSON.stringify({ html }));
        """
        rc, out, err = run_node_harness(test_js)
        self.assertEqual(rc, 0, msg=f"Node harness failed: {err}")
        payload = json.loads(out.strip().splitlines()[-1])
        self.assertIn("&lt;img src=x&gt;", payload["html"])
        self.assertNotIn("<img src=x>", payload["html"])


if __name__ == "__main__":
    unittest.main()
