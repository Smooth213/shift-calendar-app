"""フロントエンド（index.html）検証用の共通 Node.js DOM ハーネス基盤"""
import os
import re
import shutil
import subprocess
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_HTML_PATH = os.path.join(PROJECT_ROOT, "index.html")


JS_LOAD_INDEX_SCRIPT_SNIPPET = r"""
function loadIndexScriptFromHtml(htmlPath) {
  const pathMod = require("path");
  const baseDir = pathMod.dirname(pathMod.resolve(htmlPath));
  const html = fs.readFileSync(htmlPath, "utf8");
  const chunks = [];
  const re = /<script(?:\s+[^>]*?src=["']([^"']+)["'][^>]*)?>([\s\S]*?)<\/script>/gi;
  let m;
  while ((m = re.exec(html)) !== null) {
    const src = (m[1] || "").trim();
    const inlineBody = m[2] || "";
    if (src) {
      const rel = src.replace(/^\/+/, "");
      const fullPath = pathMod.join(baseDir, rel);
      chunks.push(fs.readFileSync(fullPath, "utf8"));
    } else if (inlineBody.trim()) {
      chunks.push(inlineBody);
    }
  }
  if (!chunks.length) throw new Error("index.html 内に <script> タグが見つかりません");
  return chunks.join("\n;\n");
}
"""


def extract_index_script(html_path=INDEX_HTML_PATH):
    """index.html 内の外部 <script src="/static/..."> およびインライン <script> を出現順に結合して返す。"""
    base_dir = os.path.dirname(os.path.abspath(html_path))
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    chunks = []
    pattern = re.compile(r'<script(?:\s+[^>]*?src=["\']([^"\']+)["\'][^>]*)?>([\s\S]*?)</script>', re.IGNORECASE)
    for m in pattern.finditer(html):
        src = (m.group(1) or "").strip()
        inline_body = m.group(2) or ""
        if src:
            rel = src.lstrip("/")
            full_path = os.path.join(base_dir, rel)
            with open(full_path, "r", encoding="utf-8") as sf:
                chunks.append(sf.read())
        elif inline_body.strip():
            chunks.append(inline_body)
    if not chunks:
        raise ValueError("index.html 内に <script> タグが見つかりません")
    return "\n;\n".join(chunks)


def load_index_html_with_assets(html_path=INDEX_HTML_PATH):
    """index.html と参照されているローカルCSSファイルの内容を結合して返す。"""
    base_dir = os.path.dirname(os.path.abspath(html_path))
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    css_chunks = []
    for m in re.finditer(r'<link[^>]+rel=["\']stylesheet["\'][^>]+href=["\']([^"\']+)["\']', html, re.IGNORECASE):
        href = m.group(1).strip()
        if href.startswith("/"):
            css_path = os.path.join(base_dir, href.lstrip("/"))
            if os.path.isfile(css_path):
                with open(css_path, "r", encoding="utf-8") as cf:
                    css_chunks.append(cf.read())
    if css_chunks:
        return html + "\n/* === EXTERNAL CSS === */\n" + "\n".join(css_chunks)
    return html


def check_index_js_syntax(html_path=INDEX_HTML_PATH):
    """Node.js の --check で index.html 内の JS 構文エラーを検査する。"""
    node_bin = shutil.which("node")
    if not node_bin:
        raise RuntimeError("node が見つかりません")
    script_src = extract_index_script(html_path)
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as tf:
        tf.write(script_src)
        tmp_path = tf.name
    try:
        proc = subprocess.run([node_bin, "--check", tmp_path], capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


BASE_DOM_HARNESS_JS = r"""
const fs = require("fs");
const vm = require("vm");

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

function createIndexContext(fetchImpl) {
  const elements = new Map();
  function getEl(id) {
    if (!elements.has(id)) elements.set(id, new MockElement("div", id));
    return elements.get(id);
  }
  const storage = new Map();
  const docEl = new MockElement("html");
  const doc = {
    documentElement: docEl,
    hidden: false,
    getElementById: getEl,
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: (tag) => new MockElement(tag),
    addEventListener: () => {},
  };
  const win = {
    location: { protocol: "http:", hostname: "localhost", port: "8765" },
    matchMedia: () => ({ matches: false, addEventListener: () => {} }),
    addEventListener: () => {},
    innerWidth: 1280,
    innerHeight: 800,
  };
  const ctx = vm.createContext({
    console,
    Date,
    Math,
    JSON,
    Set,
    Map,
    Array,
    Object,
    String,
    Number,
    Boolean,
    RegExp,
    Error,
    Promise,
    URLSearchParams,
    document: doc,
    window: win,
    localStorage: {
      getItem: (k) => (storage.has(k) ? storage.get(k) : null),
      setItem: (k, v) => storage.set(k, String(v)),
      removeItem: (k) => storage.delete(k),
    },
    fetch: fetchImpl || (async () => ({ ok: true, json: async () => ({}) })),
    setTimeout: () => 0,
    clearTimeout: () => {},
    setInterval: () => 0,
    clearInterval: () => {},
    alert: () => {},
    confirm: () => true,
    getEl,
  });
  const scriptCode = loadIndexScriptFromHtml(process.argv[1]);
  vm.runInContext(scriptCode, ctx);
  return ctx;
}
""" + JS_LOAD_INDEX_SCRIPT_SNIPPET


def run_node_harness(test_body_js, html_path=INDEX_HTML_PATH):
    """共通DOMハーネス上で test_body_js を実行し、(returncode, stdout, stderr) を返す。"""
    node_bin = shutil.which("node")
    if not node_bin:
        raise RuntimeError("node が見つかりません")
    full_js = BASE_DOM_HARNESS_JS + "\n(async () => {\n" + test_body_js + "\n})().catch(e => { console.error(e); process.exit(1); });\n"
    proc = subprocess.run([node_bin, "-e", full_js, html_path], capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr
