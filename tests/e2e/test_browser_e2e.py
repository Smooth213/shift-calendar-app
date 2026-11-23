"""実HTTPサーバー＋実ブラウザ（macOS Headless Chrome / CDP）によるスモークE2Eテスト（テストピラミッド頂点）

実行方法:
  python3 -m unittest discover -s tests/e2e -v

特徴:
  - 外部パッケージ追加ゼロ（Python標準ライブラリ + Node.js v24標準WebSocket + macOS Google Chrome）
  - 一時ディレクトリと空きポートを使用し、実 config.json / 実 history / 実Appleカレンダーへ一切触れない
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import app as shift_app
from shift_calendar import calendar_export

CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


_CDP_E2E_RUNNER_JS = r"""
const assert = require("assert");

const browserWsUrl = process.argv[2];
const appBaseUrl = process.argv[3];

class CdpClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.ws = null;
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = new Map();
  }

  connect() {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.wsUrl);
      this.ws = ws;
      ws.addEventListener("open", () => resolve());
      ws.addEventListener("error", (err) => reject(err));
      ws.addEventListener("message", (evt) => {
        const msg = JSON.parse(evt.data);
        if (msg.id && this.pending.has(msg.id)) {
          const { resolve: res, reject: rej } = this.pending.get(msg.id);
          this.pending.delete(msg.id);
          if (msg.error) rej(new Error(`${msg.error.code}: ${msg.error.message}`));
          else res(msg.result);
        } else if (msg.method) {
          const handlers = this.listeners.get(msg.method) || [];
          for (const fn of handlers) fn(msg.params || {});
        }
      });
    });
  }

  on(method, fn) {
    if (!this.listeners.has(method)) this.listeners.set(method, []);
    this.listeners.get(method).push(fn);
  }

  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async evalJs(expression) {
    const res = await this.send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (res.exceptionDetails) {
      const desc =
        (res.exceptionDetails.exception && res.exceptionDetails.exception.description) ||
        res.exceptionDetails.text ||
        "Runtime.evaluate exception";
      throw new Error(desc);
    }
    return res.result ? res.result.value : undefined;
  }

  close() {
    if (this.ws) this.ws.close();
  }
}

async function waitFor(fn, timeoutMs = 8000, intervalMs = 80) {
  const start = Date.now();
  let lastErr = null;
  while (Date.now() - start < timeoutMs) {
    try {
      const val = await fn();
      if (val) return val;
    } catch (e) {
      lastErr = e;
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  if (lastErr) throw lastErr;
  throw new Error(`waitFor timed out after ${timeoutMs}ms`);
}

async function main() {
  const httpBase = browserWsUrl.replace(/^ws:\/\//, "http://").replace(/\/devtools\/browser\/.*$/, "");
  const targetsRes = await fetch(`${httpBase}/json/list`);
  const targets = await targetsRes.json();
  let pageTarget = targets.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
  if (!pageTarget) {
    const created = await fetch(`${httpBase}/json/new?about:blank`, { method: "PUT" });
    pageTarget = await created.json();
  }

  const cdp = new CdpClient(pageTarget.webSocketDebuggerUrl);
  await cdp.connect();

  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];

  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Network.enable");

  cdp.on("Runtime.consoleAPICalled", (p) => {
    if (p.type === "error") {
      const text = (p.args || []).map((a) => a.value || a.description || "").join(" ");
      consoleErrors.push(text);
    }
  });
  cdp.on("Runtime.exceptionThrown", (p) => {
    pageErrors.push(p.exceptionDetails ? p.exceptionDetails.text : "exception");
  });
  cdp.on("Network.responseReceived", (p) => {
    if (p.response && p.response.url && p.response.url.startsWith(appBaseUrl) && p.response.status >= 400) {
      failedRequests.push(`${p.response.status} ${p.response.url}`);
    }
  });

  async function navigateAndWaitReady() {
    await cdp.send("Page.navigate", { url: appBaseUrl });
    await waitFor(async () => {
      return cdp.evalJs(`
        Boolean(
          document.readyState === "complete" &&
          document.getElementById("monthly-calendar-body") &&
          document.querySelectorAll("#monthly-calendar-body .cal-cell").length >= 28 &&
          typeof AppState !== "undefined" &&
          AppState.ui.isConfigLoaded === true
        )
      `);
    }, 10000);
  }

  const results = {};
  async function runCase(name, fn) {
    try {
      await fn();
      results[name] = { ok: true };
    } catch (err) {
      results[name] = { ok: false, error: err && err.stack ? err.stack : String(err) };
    }
  }

  await runCase("initial_load_assets_zero_console_errors_and_tab_switch", async () => {
    await navigateAndWaitReady();
    assert.deepStrictEqual(consoleErrors, [], `Console errors: ${consoleErrors.join("; ")}`);
    assert.deepStrictEqual(pageErrors, [], `Page errors: ${pageErrors.join("; ")}`);
    assert.deepStrictEqual(failedRequests, [], `Failed HTTP requests: ${failedRequests.join("; ")}`);

    // タブ切替: カレンダー -> 勤務表の読み込み -> カレンダー
    await cdp.evalJs(`document.getElementById("tab-btn-import").click();`);
    const importActive = await cdp.evalJs(`
      !document.getElementById("tab-panel-import").classList.contains("is-hidden") &&
      document.getElementById("tab-panel-calendar").classList.contains("is-hidden")
    `);
    assert.strictEqual(importActive, true, "Import tab did not activate");

    await cdp.evalJs(`document.getElementById("tab-btn-calendar").click();`);
    const calActive = await cdp.evalJs(`
      !document.getElementById("tab-panel-calendar").classList.contains("is-hidden") &&
      document.getElementById("tab-panel-import").classList.contains("is-hidden")
    `);
    assert.strictEqual(calActive, true, "Calendar tab did not re-activate");
  });

  await runCase("manual_shift_creation_and_reload_persistence", async () => {
    // 当月の最初の日付セルをクリックし、手動シフト（早A + メモ）を保存
    const targetDate = await cdp.evalJs(`
      (() => {
        const cell = document.querySelector("#monthly-calendar-body .cal-cell:not(.is-outside)[data-date]");
        if (!cell) return null;
        cell.click();
        return cell.dataset.date;
      })()
    `);
    assert.ok(targetDate, "No in-month calendar cell found");

    await waitFor(() => cdp.evalJs(`document.getElementById("monthly-calendar-detail").classList.contains("is-visible")`));

    await cdp.evalJs(`
      (() => {
        const typeSel = document.getElementById("cal-detail-shift-type");
        typeSel.value = "早A";
        typeSel.dispatchEvent(new Event("change", { bubbles: true }));
        const memoEl = document.getElementById("cal-detail-memo-input");
        memoEl.value = "E2E確認メモ";
        const syncCb = document.getElementById("cal-detail-hourly-sync-apple");
        if (syncCb) syncCb.checked = false;
        document.getElementById("btn-cal-save-shift").click();
      })()
    `);

    await waitFor(() =>
      cdp.evalJs(`
        (() => {
          const cell = document.querySelector('#monthly-calendar-body .cal-cell[data-date="${targetDate}"]');
          return Boolean(cell && cell.textContent.includes("早A"));
        })()
      `)
    );

    // ページをリロードしてもサーバー永続化から復元されること
    await navigateAndWaitReady();
    const persisted = await cdp.evalJs(`
      (() => {
        const cell = document.querySelector('#monthly-calendar-body .cal-cell[data-date="${targetDate}"]');
        const shift = AppState.calendar.shiftsByDate["${targetDate}"];
        return Boolean(cell && cell.textContent.includes("早A") && shift && shift.memo === "E2E確認メモ");
      })()
    `);
    assert.strictEqual(persisted, true, "Manual shift did not persist across reload");
  });

  await runCase("settings_modal_and_theme_toggle_applies_real_styles", async () => {
    await cdp.evalJs(`document.getElementById("btn-open-settings").click();`);
    await waitFor(() => cdp.evalJs(`document.getElementById("settings-modal").style.display === "flex"`));

    await cdp.evalJs(`document.querySelector('.segment-btn[data-theme="dark"]').click();`);
    const darkState = await cdp.evalJs(`({
      attr: document.documentElement.getAttribute("data-theme"),
      windowBg: getComputedStyle(document.documentElement).getPropertyValue("--window-bg").trim(),
      systemBg: getComputedStyle(document.documentElement).getPropertyValue("--system-bg").trim()
    })`);

    await cdp.evalJs(`document.querySelector('.segment-btn[data-theme="light"]').click();`);
    const lightState = await cdp.evalJs(`({
      attr: document.documentElement.getAttribute("data-theme"),
      windowBg: getComputedStyle(document.documentElement).getPropertyValue("--window-bg").trim(),
      systemBg: getComputedStyle(document.documentElement).getPropertyValue("--system-bg").trim()
    })`);

    await cdp.evalJs(`document.getElementById("btn-close-settings").click();`);

    assert.strictEqual(darkState.attr, "dark");
    assert.strictEqual(lightState.attr, "light");
    assert.notStrictEqual(darkState.windowBg, lightState.windowBg, "Theme toggle did not change --window-bg");
    assert.notStrictEqual(darkState.systemBg, lightState.systemBg, "Theme toggle did not change --system-bg");
  });

  await runCase("share_calendar_canvas_renders_non_empty_png", async () => {
    const pngInfo = await cdp.evalJs(`
      (() => {
        const canvas = renderMonthlyCalendarCanvas(AppState.calendar.viewYear, AppState.calendar.viewMonth);
        if (!canvas) return null;
        const dataUrl = canvas.toDataURL("image/png");
        return {
          width: canvas.width,
          height: canvas.height,
          prefixOk: dataUrl.startsWith("data:image/png;base64,"),
          length: dataUrl.length,
        };
      })()
    `);
    assert.ok(pngInfo, "renderMonthlyCalendarCanvas returned null");
    assert.strictEqual(pngInfo.prefixOk, true, "Canvas did not produce PNG data URL");
    assert.ok(pngInfo.width >= 800 && pngInfo.height >= 400, `Unexpected canvas size: ${pngInfo.width}x${pngInfo.height}`);
    assert.ok(pngInfo.length > 5000, `PNG data URL unexpectedly small: ${pngInfo.length}`);
  });

  await runCase("mobile_responsive_viewport_no_horizontal_overflow", async () => {
    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: 390,
      height: 844,
      deviceScaleFactor: 2,
      mobile: true,
    });
    await new Promise((r) => setTimeout(r, 150));

    const metrics = await cdp.evalJs(`({
      innerWidth: window.innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      bodyScrollWidth: document.body.scrollWidth
    })`);

    await cdp.send("Emulation.clearDeviceMetricsOverride");

    assert.strictEqual(metrics.innerWidth, 390);
    assert.ok(
      metrics.scrollWidth <= metrics.innerWidth + 2,
      `Horizontal overflow on mobile viewport: scrollWidth=${metrics.scrollWidth} > innerWidth=${metrics.innerWidth}`
    );
  });

  cdp.close();
  process.stdout.write(JSON.stringify(results));
}

main().catch((err) => {
  process.stderr.write((err && err.stack) || String(err));
  process.exit(1);
});
"""


class TestBrowserE2E(unittest.TestCase):
    """実サーバー＋実Chrome（Headless CDP）によるスモークE2Eテスト"""

    _results = {}
    _tmpdir = None
    _server = None
    _server_thread = None
    _chrome_proc = None
    _patches = []

    @classmethod
    def setUpClass(cls):
        node_bin = shutil.which("node")
        if not node_bin:
            raise unittest.SkipTest("node が見つからないためブラウザE2Eテストをスキップ")
        if not os.path.exists(CHROME_BIN):
            raise unittest.SkipTest("Google Chrome が見つからないためブラウザE2Eテストをスキップ")

        cls._tmpdir = tempfile.TemporaryDirectory(prefix="shift_cal_e2e_")
        tmp_root = cls._tmpdir.name
        tmp_config_path = os.path.join(tmp_root, "config.json")
        tmp_history_dir = os.path.join(tmp_root, "history")
        tmp_images_dir = os.path.join(tmp_root, "history_images")
        tmp_chrome_profile = os.path.join(tmp_root, "chrome_profile")
        os.makedirs(tmp_history_dir, exist_ok=True)
        os.makedirs(tmp_images_dir, exist_ok=True)
        os.makedirs(tmp_chrome_profile, exist_ok=True)

        # 実 config.json / 実 history / 実Appleカレンダーを完全に隔離
        cls._patches = [
            patch.object(shift_app, "CONFIG_PATH", tmp_config_path),
            patch.object(shift_app, "HISTORY_DIR", tmp_history_dir),
            patch.object(calendar_export, "register_to_apple_calendar", return_value=(1, "mocked")),
            patch.object(shift_app, "register_to_apple_calendar", return_value=(1, "mocked")),
        ]
        for p in cls._patches:
            p.start()

        try:
            cls._server = ThreadingHTTPServer(("127.0.0.1", 0), shift_app.RequestHandler)
        except OSError as exc:
            cls._cleanup_resources()
            raise unittest.SkipTest(f"ローカルポートバインドが制限されているためE2Eをスキップ: {exc}")

        port = cls._server.server_address[1]
        cls._server_thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._server_thread.start()
        app_base_url = f"http://127.0.0.1:{port}/"

        # Headless Chrome 起動（空きデバッグポート）
        chrome_cmd = [
            CHROME_BIN,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-networking",
            "--window-size=1280,900",
            "--remote-debugging-port=0",
            f"--user-data-dir={tmp_chrome_profile}",
            "about:blank",
        ]
        try:
            cls._chrome_proc = subprocess.Popen(
                chrome_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            cls._cleanup_resources()
            raise unittest.SkipTest(f"Headless Chrome 起動失敗のためE2Eをスキップ: {exc}")

        ws_url = None
        stderr_lines = []
        deadline = time.time() + 15.0
        while time.time() < deadline:
            line = cls._chrome_proc.stderr.readline()
            if not line:
                if cls._chrome_proc.poll() is not None:
                    break
                time.sleep(0.05)
                continue
            stderr_lines.append(line.strip())
            m = re.search(r"DevTools listening on (ws://\S+)", line)
            if m:
                ws_url = m.group(1)
                break

        if not ws_url:
            cls._cleanup_resources()
            raise AssertionError(f"Chrome DevTools WebSocket URL の取得に失敗しました:\n" + "\n".join(stderr_lines[-20:]))

        runner_path = os.path.join(tmp_root, "cdp_e2e_runner.js")
        with open(runner_path, "w", encoding="utf-8") as f:
            f.write(_CDP_E2E_RUNNER_JS)

        proc = subprocess.run(
            [node_bin, runner_path, ws_url, app_base_url],
            capture_output=True,
            text=True,
            timeout=45,
        )
        if proc.returncode != 0:
            cls._cleanup_resources()
            raise AssertionError(
                f"Browser E2E runner failed (exit={proc.returncode}):\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
            )
        cls._results = json.loads(proc.stdout)

    @classmethod
    def _cleanup_resources(cls):
        if cls._chrome_proc is not None:
            try:
                cls._chrome_proc.terminate()
                cls._chrome_proc.wait(timeout=5)
            except Exception:
                try:
                    cls._chrome_proc.kill()
                except Exception:
                    pass
            try:
                if cls._chrome_proc.stderr:
                    cls._chrome_proc.stderr.close()
            except Exception:
                pass
            cls._chrome_proc = None
        if cls._server is not None:
            try:
                cls._server.shutdown()
                cls._server.server_close()
            except Exception:
                pass
            cls._server = None
        for p in reversed(cls._patches):
            try:
                p.stop()
            except Exception:
                pass
        cls._patches = []
        if cls._tmpdir is not None:
            try:
                cls._tmpdir.cleanup()
            except Exception:
                pass
            cls._tmpdir = None

    @classmethod
    def tearDownClass(cls):
        cls._cleanup_resources()

    def _assert_e2e_case(self, case_name):
        self.assertIn(case_name, self._results, f"E2E case '{case_name}' not found")
        res = self._results[case_name]
        self.assertTrue(res.get("ok"), f"E2E case '{case_name}' failed:\n{res.get('error')}")

    def test_01_initial_load_assets_zero_console_errors_and_tab_switch(self):
        self._assert_e2e_case("initial_load_assets_zero_console_errors_and_tab_switch")

    def test_02_manual_shift_creation_and_reload_persistence(self):
        self._assert_e2e_case("manual_shift_creation_and_reload_persistence")

    def test_03_settings_modal_and_theme_toggle_applies_real_styles(self):
        self._assert_e2e_case("settings_modal_and_theme_toggle_applies_real_styles")

    def test_04_share_calendar_canvas_renders_non_empty_png(self):
        self._assert_e2e_case("share_calendar_canvas_renders_non_empty_png")

    def test_05_mobile_responsive_viewport_no_horizontal_overflow(self):
        self._assert_e2e_case("mobile_responsive_viewport_no_horizontal_overflow")


if __name__ == "__main__":
    unittest.main()
