    // =========================================================================
    // Application State (Consolidated by Domain + Backward-Compatible Bindings)
    // =========================================================================
    // 1) Analysis & Shift Extraction State
    let currentImageBase64 = null;
    let currentMimeType = "image/jpeg";
    let currentImageName = "IMG_8626.JPG";
    let analyzedShifts = [];
    let masterTimeDefs = {};
    let latestAnalyzedShifts = []; // 最新の解析結果退避用
    let latestImageBase64 = null;
    let currentDewarpStatus = null; // "applied" | "already_dewarped" | "not_applied" | "processing" | null
    let latestDewarpStatus = null;
    let isAnalyzing = false;
    let pendingAutoAnalyzeKey = null;
    let lastLoadedPreloadKey = null;
    let isCorrectedImageActive = false;
    let analyzeStartTs = 0;
    let progressPollTimer = null;

    // 2) History State
    let currentHistoryId = null;
    let latestHistoryId = null;
    let currentHistoryMeta = null;

    // 3) 2-Tab & Monthly Calendar View State
    let activeMainTab = "calendar";
    let calendarShiftsByDate = {};
    let calendarAvailableMonths = [];
    const _initToday = new Date();
    let calendarViewYear = _initToday.getFullYear();
    let calendarViewMonth = _initToday.getMonth() + 1;
    let calendarPickerYear = calendarViewYear;
    let calendarSelectedDate = null;
    let calendarHighlightKey = null;
    let paidLeaveConfig = { startMonth: 4, startDay: 1, annualDays: 20, hoursPerDay: 8 };

    // 4) Image Viewer State
    let scale = 1;
    let panX = 0;
    let panY = 0;
    let isDragging = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let dragOriginX = 0;
    let dragOriginY = 0;

    // 5) UI / Theme / Config Runtime State
    let currentThemeMode = localStorage.getItem("shift_app_theme") || "system";
    let mobileAccessUrl = "";
    let isConfigLoaded = false;
    let hasServerApiKey = false;
    let isOutdatedServerStopped = false;
    let activeHighlightKey = null;
    let selectedCalendarIdx = null;
    let imageFocusTimer = null;

    // Structured Domain State Facade (two-way synced with legacy bindings)
    const AppState = {
      analysis: {
        get imageBase64() { return currentImageBase64; },
        set imageBase64(v) { currentImageBase64 = v; },
        get mimeType() { return currentMimeType; },
        set mimeType(v) { currentMimeType = v; },
        get imageName() { return currentImageName; },
        set imageName(v) { currentImageName = v; },
        get shifts() { return analyzedShifts; },
        set shifts(v) { analyzedShifts = v; },
        get masterTimeDefs() { return masterTimeDefs; },
        set masterTimeDefs(v) { masterTimeDefs = v; },
        get dewarpStatus() { return currentDewarpStatus; },
        set dewarpStatus(v) { currentDewarpStatus = v; },
        get isAnalyzing() { return isAnalyzing; },
        set isAnalyzing(v) { isAnalyzing = v; },
        get isCorrectedImageActive() { return isCorrectedImageActive; },
        set isCorrectedImageActive(v) { isCorrectedImageActive = v; },
      },
      history: {
        get currentId() { return currentHistoryId; },
        set currentId(v) { currentHistoryId = v; },
        get latestId() { return latestHistoryId; },
        set latestId(v) { latestHistoryId = v; },
        get currentMeta() { return currentHistoryMeta; },
        set currentMeta(v) { currentHistoryMeta = v; },
      },
      calendar: {
        get activeTab() { return activeMainTab; },
        set activeTab(v) { activeMainTab = v; },
        get shiftsByDate() { return calendarShiftsByDate; },
        set shiftsByDate(v) { calendarShiftsByDate = v; },
        get availableMonths() { return calendarAvailableMonths; },
        set availableMonths(v) { calendarAvailableMonths = v; },
        get viewYear() { return calendarViewYear; },
        set viewYear(v) { calendarViewYear = v; },
        get viewMonth() { return calendarViewMonth; },
        set viewMonth(v) { calendarViewMonth = v; },
        get selectedDate() { return calendarSelectedDate; },
        set selectedDate(v) { calendarSelectedDate = v; },
        get highlightKey() { return calendarHighlightKey; },
        set highlightKey(v) { calendarHighlightKey = v; },
        get paidLeaveConfig() { return paidLeaveConfig; },
        set paidLeaveConfig(v) { paidLeaveConfig = v; },
      },
      viewer: {
        get scale() { return scale; },
        set scale(v) { scale = v; },
        get panX() { return panX; },
        set panX(v) { panX = v; },
        get panY() { return panY; },
        set panY(v) { panY = v; },
        get isDragging() { return isDragging; },
        set isDragging(v) { isDragging = v; },
      },
      ui: {
        get themeMode() { return currentThemeMode; },
        set themeMode(v) { currentThemeMode = v; },
        get isConfigLoaded() { return isConfigLoaded; },
        set isConfigLoaded(v) { isConfigLoaded = v; },
        get hasServerApiKey() { return hasServerApiKey; },
        set hasServerApiKey(v) { hasServerApiKey = Boolean(v); },
        get activeHighlightKey() { return activeHighlightKey; },
        set activeHighlightKey(v) { activeHighlightKey = v; },
        get selectedCalendarIdx() { return selectedCalendarIdx; },
        set selectedCalendarIdx(v) { selectedCalendarIdx = v; },
      },
      snapshot() {
        return {
          analysis: {
            hasImage: Boolean(currentImageBase64),
            shiftsCount: Array.isArray(analyzedShifts) ? analyzedShifts.length : 0,
            isAnalyzing,
            dewarpStatus: currentDewarpStatus,
          },
          history: {
            currentId: currentHistoryId,
            latestId: latestHistoryId,
          },
          calendar: {
            activeTab: activeMainTab,
            viewYear: calendarViewYear,
            viewMonth: calendarViewMonth,
            selectedDate: calendarSelectedDate,
          },
          viewer: { scale, panX, panY, isDragging },
          ui: { themeMode: currentThemeMode, isConfigLoaded, activeHighlightKey },
        };
      },
    };

    // Shared JSON / Binary API Client Helper (all backend requests go through here)
    const ApiClient = {
      async getRaw(url) {
        return fetch(url);
      },
      async getJson(url) {
        const res = await fetch(url);
        return res && typeof res.json === "function" ? res.json() : null;
      },
      async getJsonWithRes(url) {
        const res = await fetch(url);
        const data = res && typeof res.json === "function" ? await res.json() : null;
        return { res, data };
      },
      async postJson(url, payload) {
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = res && typeof res.json === "function" ? await res.json() : null;
        return { res, data };
      },
      async postEmpty(url) {
        return fetch(url, { method: "POST" });
      },
      async postBlob(url, payload) {
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        return { res, blob: await res.blob() };
      },
    };

    function clampInt(val, defaultVal, minVal, maxVal) {
      const n = parseInt(val, 10);
      if (Number.isNaN(n)) return defaultVal;
      return Math.max(minVal, Math.min(maxVal, n));
    }

    function clampHalfHour(val, defaultVal, minVal, maxVal) {
      const n = parseFloat(val);
      if (Number.isNaN(n)) return defaultVal;
      const snapped = Math.round(n * 2) / 2;
      const clamped = Math.max(minVal, Math.min(maxVal, snapped));
      return clamped === 0 ? 0 : clamped;
    }

    function formatHoursNum(hours) {
      const h = clampHalfHour(hours, 0, 0, 10000);
      return Number.isInteger(h) ? String(h) : h.toFixed(1);
    }

    function formatPaidLeaveDaysAndHours(totalHalfHours, hoursPerDay) {
      const hpd = clampHalfHour(hoursPerDay, 8, 1, 24);
      const halfPerDay = Math.max(2, Math.round(hpd * 2));
      const absHalf = Math.max(0, Math.round(Math.abs(totalHalfHours || 0)));
      const days = Math.floor(absHalf / halfPerDay);
      const remHalf = absHalf % halfPerDay;
      const remHoursStr = formatHoursNum(remHalf / 2);
      return `${days}日 ${remHoursStr}時間`;
    }

    function applyHourlyLeaveToSummary(summary, hours, status = "work") {
      const base = String(summary || "")
        .replace(/\s*[（(]時間有給\s*[0-9]+(?:\.[0-9]+)?h[)）]\s*$/, "")
        .trim();
      const h = clampHalfHour(hours, 0, 0, 23.5);
      if (status === "work" && h > 0) {
        const hStr = formatHoursNum(h);
        return base ? `${base}（時間有給${hStr}h）` : `時間有給${hStr}h`;
      }
      return base;
    }

    function formatAppleCalendarShiftSummary(shift, hoursPerDay = 8) {
      if (!shift) return "";
      const isHoliday = Boolean(shift.status === "holiday" || shift.is_holiday);
      const isPaidLeave = Boolean(shift.status === "paid_leave" || shift.is_paid_leave);
      const isAllDay = isHoliday || isPaidLeave;
      let rawSummary = shift.summary ? String(shift.summary).trim() : "";
      if (!rawSummary) {
        if (isHoliday) {
          rawSummary = "休み";
        } else if (isPaidLeave) {
          rawSummary = "有給休暇";
        } else if (shift.start_time && shift.end_time) {
          rawSummary = `[${shift.type || "出勤"}] (${shift.start_time}〜${shift.end_time})`;
        } else {
          rawSummary = shift.type || "出勤";
        }
      }
      if (!isAllDay) {
        const hpd = clampHalfHour(hoursPerDay, 8, 1, 24);
        const hLeave = clampHalfHour(shift.hourly_paid_leave, 0, 0, Math.max(0, hpd - 0.5));
        if (hLeave > 0) {
          rawSummary = applyHourlyLeaveToSummary(rawSummary, hLeave, "work");
        }
      }
      return rawSummary;
    }

    function buildHourlyLeaveOptionsHtml(selectedVal, hoursPerDay) {
      const hpd = clampHalfHour(hoursPerDay, 8, 1, 24);
      const maxHalf = Math.max(1, Math.round(hpd * 2) - 1);
      const sel = clampHalfHour(selectedVal, 0, 0, maxHalf / 2);
      let html = `<option value="0" ${sel === 0 ? "selected" : ""}>なし (0h)</option>`;
      for (let hh = 1; hh <= maxHalf; hh++) {
        const val = hh / 2;
        const label = `${formatHoursNum(val)}時間`;
        html += `<option value="${val}" ${sel === val ? "selected" : ""}>${label}</option>`;
      }
      return html;
    }

    function syncPaidLeaveSettingsInputs() {
      const sm = document.getElementById("paid-leave-start-month");
      const sd = document.getElementById("paid-leave-start-day");
      const ad = document.getElementById("paid-leave-annual-days");
      const hpd = document.getElementById("paid-leave-hours-per-day");
      if (sm) sm.value = String(paidLeaveConfig.startMonth);
      if (sd) sd.value = String(paidLeaveConfig.startDay);
      if (ad) ad.value = String(paidLeaveConfig.annualDays);
      if (hpd) hpd.value = String(paidLeaveConfig.hoursPerDay);
    }

    function updateDewarpStatusBadge(status) {
      const badge = document.getElementById("dewarp-status-badge");
      if (!badge) return;
      badge.className = "dewarp-status-badge";
      if (status === "applied") {
        badge.classList.add("is-applied");
        badge.textContent = "水平・垂直補正 適用済み";
      } else if (status === "already_dewarped") {
        badge.classList.add("is-already");
        badge.textContent = "水平・垂直補正 不要（補正済み）";
      } else if (status === "not_applied") {
        badge.classList.add("is-not-applied");
        badge.textContent = "水平・垂直補正 未適用";
      } else if (status === "processing") {
        badge.classList.add("is-processing");
        badge.textContent = "水平・垂直補正 処理中...";
      } else {
        badge.textContent = "";
      }
    }

    // Theme Management (state consolidated at top of <script>)

    function applyTheme(mode) {
      currentThemeMode = mode;
      localStorage.setItem("shift_app_theme", mode);

      document.querySelectorAll(".segment-btn[data-theme]").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.theme === mode);
      });

      if (mode === "system") {
        const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        document.documentElement.setAttribute("data-theme", isDark ? "dark" : "light");
      } else {
        document.documentElement.setAttribute("data-theme", mode);
      }
    }

    // OS Preference Change Listener
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
      if (currentThemeMode === "system") {
        document.documentElement.setAttribute("data-theme", e.matches ? "dark" : "light");
      }
    });

    // Theme Selector Buttons
    document.querySelectorAll(".segment-btn[data-theme]").forEach(btn => {
      btn.addEventListener("click", () => {
        applyTheme(btn.dataset.theme);
      });
    });

    // Initialize Theme immediately
    applyTheme(currentThemeMode);

    const toast = document.getElementById("toast");
    function showToast(msg, type = "normal") {
      toast.textContent = msg;
      toast.className = `toast ${type}`;
      toast.style.display = "block";
      setTimeout(() => { toast.style.display = "none"; }, 3500);
    }

    // Heartbeat for auto termination on close
    async function sendHeartbeat() {
      try {
        await ApiClient.getRaw("/api/heartbeat");
        checkPreloadedImage();
      } catch (e) { }
    }
    setInterval(sendHeartbeat, 2000);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) {
        sendHeartbeat();
        checkPreloadedImage();
      }
    });
    window.addEventListener("focus", () => {
      sendHeartbeat();
      checkPreloadedImage();
    });
    window.addEventListener("pageshow", checkPreloadedImage);

    // Initial rapid checks to catch preload right after launch
    setTimeout(checkPreloadedImage, 300);
    setTimeout(checkPreloadedImage, 800);
    setTimeout(checkPreloadedImage, 1500);

    // Load initial config (runtime state consolidated at top of <script>)
    const autoAnalyzedPreloadKeys = new Set();

    async function initConfig() {
      try {
        const data = await ApiClient.getJson("/api/config");
        const isRealBrowserHttp = Boolean(window && window.location && /^https?:/.test(window.location.protocol || ""));
        if (isRealBrowserHttp && !data.server_version) {
          isOutdatedServerStopped = true;
          try {
            await ApiClient.postEmpty("/api/shutdown");
          } catch (e) { }
          updateProgressUI(
            100,
            "古いバックグラウンドサーバーを停止しました",
            "更新前の古いサーバープロセスが残留していたため自動停止しました。もう一度クイックアクション（または launch.command）を実行してください。",
            4,
            "error"
          );
          showToast("古いバックグラウンドサーバーを停止しました。もう一度クイックアクションを実行してください", "error");
          return;
        }
        AppState.ui.hasServerApiKey = Boolean(data.has_api_key || (data.api_key && String(data.api_key).trim()));
        if (data.api_key) document.getElementById("api-key").value = data.api_key;
        if (data.default_name) document.getElementById("target-name").value = data.default_name;
        if (data.calendar_name) document.getElementById("calendar-name").value = data.calendar_name;
        syncBasicConfigSummary();
        if (data.theme) {
          applyTheme(localStorage.getItem("shift_app_theme") || data.theme);
        }
        if (data.mobile_url) {
          mobileAccessUrl = data.mobile_url;
          document.getElementById("mobile-url-input").value = mobileAccessUrl;
          document.getElementById("qr-img").src = `/api/qr.svg?data=${encodeURIComponent(mobileAccessUrl)}`;
        }
        masterTimeDefs = data.time_definitions || {};
        paidLeaveConfig = {
          startMonth: clampInt(data.paid_leave_start_month, 4, 1, 12),
          startDay: clampInt(data.paid_leave_start_day, 1, 1, 31),
          annualDays: clampInt(data.paid_leave_annual_days, 20, 0, 365),
          hoursPerDay: clampHalfHour(data.paid_leave_hours_per_day, 8, 1, 24)
        };
        syncPaidLeaveSettingsInputs();
        renderMasterDefs(masterTimeDefs);
        renderCalendarViewDefs(masterTimeDefs);
        loadHistoryList();
        fetchRegisteredCalendarShifts();
      } catch (e) {
        console.error(e);
      } finally {
        if (isOutdatedServerStopped) return;
        isConfigLoaded = true;
        if (pendingAutoAnalyzeKey) {
          const keyToRun = pendingAutoAnalyzeKey;
          pendingAutoAnalyzeKey = null;
          triggerAutoAnalyzeFromQuickAction(keyToRun);
        }
        checkPreloadedImage();
      }
    }

    // QR Modal Controls
    const qrModal = document.getElementById("qr-modal");
    document.getElementById("btn-show-qr").addEventListener("click", () => {
      qrModal.style.display = "flex";
    });
    document.getElementById("btn-close-qr").addEventListener("click", () => {
      qrModal.style.display = "none";
    });
    qrModal.addEventListener("click", (e) => {
      if (e.target === qrModal) qrModal.style.display = "none";
    });
    document.getElementById("btn-copy-url").addEventListener("click", () => {
      navigator.clipboard.writeText(mobileAccessUrl).then(() => {
        showToast("URLをコピーしました", "success");
      });
    });

    // Settings Modal Controls (外観モード・Gemini APIキー)
    const settingsModal = document.getElementById("settings-modal");
    const btnOpenSettings = document.getElementById("btn-open-settings");
    const btnCloseSettings = document.getElementById("btn-close-settings");
    const btnSaveSettingsModal = document.getElementById("btn-save-settings-modal");
    const apiKeyInputEl = document.getElementById("api-key");
    const btnToggleApiKey = document.getElementById("btn-toggle-api-key");
    const iconEyeOpen = document.getElementById("icon-eye-open");
    const iconEyeOff = document.getElementById("icon-eye-off");

    function setApiKeyVisibility(visible) {
      if (!apiKeyInputEl) return;
      apiKeyInputEl.type = visible ? "text" : "password";
      if (iconEyeOpen) iconEyeOpen.style.display = visible ? "none" : "block";
      if (iconEyeOff) iconEyeOff.style.display = visible ? "block" : "none";
      if (btnToggleApiKey) {
        btnToggleApiKey.setAttribute("aria-pressed", visible ? "true" : "false");
        btnToggleApiKey.setAttribute("aria-label", visible ? "APIキーを隠す" : "APIキーを表示");
        btnToggleApiKey.title = visible ? "APIキーを隠す" : "APIキーを表示";
      }
    }

    const DEFAULT_TIME_DEFS_PRESET = {
      "早A": { start: "06:00", end: "15:00" },
      "早B": { start: "06:30", end: "15:30" },
      "早C": { start: "07:00", end: "16:00" },
      "早D": { start: "08:00", end: "17:00" },
      "日":  { start: "08:30", end: "17:30" },
      "遅A": { start: "09:00", end: "18:00" },
      "遅B": { start: "09:30", end: "18:30" },
      "遅C": { start: "10:00", end: "19:00" }
    };

    function syncBasicConfigSummary() {
      const targetEl = document.getElementById("target-name");
      const calEl = document.getElementById("calendar-name");
      const sumTarget = document.getElementById("basic-summary-target-name");
      const sumCal = document.getElementById("basic-summary-calendar-name");
      if (sumTarget) sumTarget.textContent = (targetEl && targetEl.value.trim()) || "皿田";
      if (sumCal) sumCal.textContent = (calEl && calEl.value.trim()) || "シフトカレンダー";
    }

    function createSettingsDefRow(keyVal = "", startVal = "08:30", endVal = "17:30") {
      const row = document.createElement("div");
      row.className = "settings-def-row";

      const keyInput = document.createElement("input");
      keyInput.type = "text";
      keyInput.className = "input-text settings-def-key";
      keyInput.value = String(keyVal || "");
      keyInput.placeholder = "区分名";
      keyInput.maxLength = 20;
      keyInput.setAttribute("aria-label", "シフト区分名");

      const startInput = document.createElement("input");
      startInput.type = "time";
      startInput.className = "input-text settings-def-time settings-def-start";
      startInput.value = String(startVal || "08:30");
      startInput.setAttribute("aria-label", "開始時刻");

      const sep = document.createElement("span");
      sep.className = "settings-unit";
      sep.textContent = "〜";

      const endInput = document.createElement("input");
      endInput.type = "time";
      endInput.className = "input-text settings-def-time settings-def-end";
      endInput.value = String(endVal || "17:30");
      endInput.setAttribute("aria-label", "終了時刻");

      const rmBtn = document.createElement("button");
      rmBtn.type = "button";
      rmBtn.className = "btn settings-def-remove";
      rmBtn.textContent = "削除";
      rmBtn.setAttribute("aria-label", "区分を削除");
      rmBtn.addEventListener("click", () => {
        if (row.parentNode) {
          if (typeof row.parentNode.removeChild === "function") {
            row.parentNode.removeChild(row);
          } else if (Array.isArray(row.parentNode.children)) {
            const idx = row.parentNode.children.indexOf(row);
            if (idx >= 0) row.parentNode.children.splice(idx, 1);
          }
        }
      });

      row.appendChild(keyInput);
      row.appendChild(startInput);
      row.appendChild(sep);
      row.appendChild(endInput);
      row.appendChild(rmBtn);
      row._defInputs = { keyInput, startInput, endInput, rmBtn };
      return row;
    }

    function renderSettingsTimeDefsEditor(defs) {
      const listEl = document.getElementById("settings-defs-list");
      if (!listEl) return;
      listEl.innerHTML = "";
      if (Array.isArray(listEl.children)) listEl.children.length = 0;
      const entries = Object.entries(defs || {});
      entries.forEach(([k, v]) => {
        const startVal = (v && v.start) ? v.start : "08:30";
        const endVal = (v && v.end) ? v.end : "17:30";
        listEl.appendChild(createSettingsDefRow(k, startVal, endVal));
      });
    }

    function collectSettingsTimeDefsFromEditor() {
      const listEl = document.getElementById("settings-defs-list");
      if (!listEl || !listEl.children || listEl.children.length === 0) {
        return { defs: masterTimeDefs, error: null };
      }
      const rows = Array.from(listEl.children).filter(el => el && (el._defInputs || (el.classList && el.classList.contains("settings-def-row"))));
      if (!rows || rows.length === 0) {
        return { defs: masterTimeDefs, error: null };
      }
      const result = {};
      const hhmmRe = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
      for (const row of rows) {
        const keyInput = row._defInputs ? row._defInputs.keyInput : (row.querySelector ? row.querySelector(".settings-def-key") : null);
        const startInput = row._defInputs ? row._defInputs.startInput : (row.querySelector ? row.querySelector(".settings-def-start") : null);
        const endInput = row._defInputs ? row._defInputs.endInput : (row.querySelector ? row.querySelector(".settings-def-end") : null);
        const key = (keyInput ? keyInput.value : "").trim();
        const start = (startInput ? startInput.value : "").trim();
        const end = (endInput ? endInput.value : "").trim();
        if (!key) return { defs: null, error: "シフト区分名が空の行があります" };
        if (["休", "休み", "有給", "有給休暇"].includes(key)) {
          return { defs: null, error: `シフト区分名「${key}」は予約語のため使用できません` };
        }
        if (Object.prototype.hasOwnProperty.call(result, key)) {
          return { defs: null, error: `シフト区分名「${key}」が重複しています` };
        }
        if (!hhmmRe.test(start) || !hhmmRe.test(end)) {
          return { defs: null, error: `シフト区分「${key}」の時刻は HH:MM 形式で入力してください` };
        }
        result[key] = { start, end };
      }
      if (Object.keys(result).length === 0) {
        return { defs: null, error: "シフト区分は1件以上登録してください" };
      }
      return { defs: result, error: null };
    }

    function openSettingsModal() {
      setApiKeyVisibility(false);
      renderSettingsTimeDefsEditor(masterTimeDefs);
      if (settingsModal) settingsModal.style.display = "flex";
    }

    function closeSettingsModal() {
      setApiKeyVisibility(false);
      if (settingsModal) settingsModal.style.display = "none";
    }

    if (btnOpenSettings) btnOpenSettings.addEventListener("click", openSettingsModal);
    const btnOpenBasicSettings = document.getElementById("btn-open-basic-settings");
    if (btnOpenBasicSettings) btnOpenBasicSettings.addEventListener("click", openSettingsModal);
    const btnAddShiftDef = document.getElementById("btn-add-shift-def");
    if (btnAddShiftDef) {
      btnAddShiftDef.addEventListener("click", () => {
        const listEl = document.getElementById("settings-defs-list");
        if (listEl) listEl.appendChild(createSettingsDefRow("", "08:30", "17:30"));
      });
    }
    const btnResetShiftDefs = document.getElementById("btn-reset-shift-defs");
    if (btnResetShiftDefs) {
      btnResetShiftDefs.addEventListener("click", () => {
        renderSettingsTimeDefsEditor(DEFAULT_TIME_DEFS_PRESET);
        showToast("標準のシフト区分を反映しました（「保存して閉じる」で確定）", "success");
      });
    }
    const btnRestoreHistory = document.getElementById("btn-restore-history");
    const restoreZipInput = document.getElementById("restore-zip-input");
    if (btnRestoreHistory && restoreZipInput) {
      btnRestoreHistory.addEventListener("click", () => restoreZipInput.click());
      restoreZipInput.addEventListener("change", async (e) => {
        const files = e && e.target && e.target.files ? e.target.files : [];
        if (!files.length) return;
        const file = files[0];
        btnRestoreHistory.disabled = true;
        btnRestoreHistory.textContent = "復元中...";
        try {
          const dataUrl = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result || ""));
            reader.onerror = () => reject(new Error("ZIPファイルの読み込みに失敗しました"));
            reader.readAsDataURL(file);
          });
          const { res, data: json } = await ApiClient.postJson("/api/history/restore", {
            zip_base64: dataUrl,
            overwrite: false
          });
          if (!res.ok || !json.success) {
            throw new Error((json && json.error) || "履歴の復元に失敗しました");
          }
          await loadHistoryList();
          await fetchRegisteredCalendarShifts();
          showToast(
            `復元完了: 追加 ${json.imported_histories || 0}件 / 既存スキップ ${json.skipped_histories || 0}件`,
            "success"
          );
        } catch (err) {
          showToast(`復元エラー: ${err.message}`, "error");
        } finally {
          btnRestoreHistory.disabled = false;
          btnRestoreHistory.textContent = "ZIPから復元";
          restoreZipInput.value = "";
        }
      });
    }
    if (btnCloseSettings) btnCloseSettings.addEventListener("click", closeSettingsModal);
    if (settingsModal) {
      settingsModal.addEventListener("click", (e) => {
        if (e.target === settingsModal) closeSettingsModal();
      });
    }
    if (btnToggleApiKey) {
      btnToggleApiKey.addEventListener("click", () => {
        const isCurrentlyVisible = apiKeyInputEl && apiKeyInputEl.type === "text";
        setApiKeyVisibility(!isCurrentlyVisible);
      });
    }
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        if (settingsModal && settingsModal.style.display === "flex") closeSettingsModal();
        if (qrModal && qrModal.style.display === "flex") qrModal.style.display = "none";
      }
    });

    initConfig();

    function renderLegendCapsules(containerId, defs, activeKey, onToggle, extraClass = "") {
      const container = document.getElementById(containerId);
      if (!container) return;
      container.innerHTML = "";
      const baseClass = extraClass ? `legend-capsule ${extraClass}` : "legend-capsule";

      Object.keys(defs || {}).forEach(k => {
        const tag = document.createElement("div");
        tag.className = `${baseClass} ${activeKey === k ? "is-active" : ""}`;
        tag.dataset.key = k;
        tag.title = "クリックでカレンダーの該当シフトをハイライト（再クリックで解除）";
        tag.innerHTML = `<strong>${escapeHtmlText(k)}</strong> ${escapeHtmlText(defs[k].start)}〜${escapeHtmlText(defs[k].end)}`;
        tag.addEventListener("click", () => onToggle(k));
        container.appendChild(tag);
      });

      const staticEntries = [
        { key: "休", title: "クリックでカレンダーの休みをハイライト（再クリックで解除）", label: "終日休み" },
        { key: "有給", title: "クリックでカレンダーの有給休暇をハイライト（再クリックで解除）", label: "終日有給休暇" },
      ];
      staticEntries.forEach(item => {
        const el = document.createElement("div");
        el.className = `${baseClass} ${activeKey === item.key ? "is-active" : ""}`;
        el.dataset.key = item.key;
        el.title = item.title;
        el.innerHTML = `<strong>${escapeHtmlText(item.key)}</strong> ${escapeHtmlText(item.label)}`;
        el.addEventListener("click", () => onToggle(item.key));
        container.appendChild(el);
      });
    }

    function renderMasterDefs(defs) {
      renderLegendCapsules("defs-container", defs, AppState.ui.activeHighlightKey, toggleHighlight);
    }

    // 凡例クリックによるハイライト / 解除トグル
    function toggleHighlight(key) {
      if (activeHighlightKey === key) {
        activeHighlightKey = null; // 解除
      } else {
        activeHighlightKey = key; // 設定
      }

      // 個別の日付選択と画像ハイライト枠をクリア
      if (imageFocusTimer) {
        clearTimeout(imageFocusTimer);
        imageFocusTimer = null;
      }
      selectedCalendarIdx = null;
      document.querySelectorAll(".cal-cell").forEach(c => c.classList.remove("is-selected"));
      document.querySelectorAll("#shifts-tbody tr").forEach(tr => tr.classList.remove("is-selected"));
      const hBox = document.getElementById("viewer-highlight-box");
      if (hBox) hBox.style.display = "none";

      document.querySelectorAll(".legend-capsule").forEach(el => {
        el.classList.toggle("is-active", el.dataset.key === activeHighlightKey);
      });
      applyHighlightFilter();
    }

    function applyHighlightFilter() {
      // カレンダーピルのハイライト / ディム
      document.querySelectorAll(".cal-event-capsule").forEach(el => {
        const key = el.dataset.key;
        if (!activeHighlightKey) {
          el.classList.remove("is-highlighted", "is-dimmed");
        } else if (key === activeHighlightKey) {
          el.classList.add("is-highlighted");
          el.classList.remove("is-dimmed");
        } else {
          el.classList.remove("is-highlighted");
          el.classList.add("is-dimmed");
        }
      });

      // テーブル行のハイライト / ディム
      document.querySelectorAll("#shifts-tbody tr").forEach(tr => {
        const key = tr.dataset.key;
        if (!activeHighlightKey) {
          tr.classList.remove("is-highlighted", "is-dimmed");
        } else if (key === activeHighlightKey) {
          tr.classList.add("is-highlighted");
          tr.classList.remove("is-dimmed");
        } else {
          tr.classList.remove("is-highlighted");
          tr.classList.add("is-dimmed");
        }
      });
    }

    // History Management
    const historySelect = document.getElementById("history-select");
    const btnLoadHistory = document.getElementById("btn-load-history");
    const btnDeleteHistory = document.getElementById("btn-delete-history");
    const historyActiveInfo = document.getElementById("history-active-info");
    const historyActiveText = document.getElementById("history-active-text");
    const btnResetHistory = document.getElementById("btn-reset-history");
    const historyCountBadge = document.getElementById("history-count-badge");

    function buildHistoryTitle(shifts) {
      let title = "シフト";
      if (Array.isArray(shifts) && shifts.length > 0) {
        const mCounts = {};
        shifts.forEach(s => {
          if (s && s.date) {
            const ym = s.date.substring(0, 7);
            mCounts[ym] = (mCounts[ym] || 0) + 1;
          }
        });
        const keys = Object.keys(mCounts);
        if (keys.length > 0) {
          const mainYm = keys.sort((a, b) => mCounts[b] - mCounts[a])[0];
          const [y, m] = mainYm.split("-");
          if (y && m) title = `${y}年${parseInt(m, 10)}月度`;
        }
      }
      return title;
    }

    function updateHistoryActiveBanner(hist) {
      if (!hist || !historyActiveText) return;
      if (hist.registered) {
        const ts = hist.registered_at || hist.created_at || "";
        historyActiveText.textContent = `【登録済み履歴】${hist.title} を表示中（${ts} 登録）`;
      } else {
        historyActiveText.textContent = `【未登録履歴】${hist.title} を表示中（${hist.created_at || ""} 解析保存）`;
      }
    }

    async function loadHistoryList() {
      try {
        const json = await ApiClient.getJson("/api/history");
        const list = json.history || [];
        const registeredList = list.filter(i => Boolean(i.registered));
        const unregisteredList = list.filter(i => !i.registered);

        if (list.length === 0) {
          historyCountBadge.textContent = "0件";
        } else {
          historyCountBadge.textContent = `登録済 ${registeredList.length}件 / 未登録 ${unregisteredList.length}件`;
        }

        const curVal = historySelect.value;
        historySelect.innerHTML = '<option value="">過去のシフトを選択してください...</option>';

        const appendGroup = (label, items, prefix) => {
          if (!items.length) return;
          const group = document.createElement("optgroup");
          group.label = label;
          items.forEach(item => {
            const opt = document.createElement("option");
            opt.value = item.id;
            const ts = item.registered ? (item.registered_at || item.created_at) : item.created_at;
            opt.textContent = `[${prefix}] ${item.title} (${item.shifts_count}日間 - ${ts})`;
            group.appendChild(opt);
          });
          historySelect.appendChild(group);
        };

        appendGroup("登録済み", registeredList, "登録済");
        appendGroup("未登録（直近5件）", unregisteredList, "未登録");

        if (curVal && list.some(i => i.id === curVal)) {
          historySelect.value = curVal;
          btnLoadHistory.disabled = false;
          btnDeleteHistory.disabled = false;
        } else {
          btnLoadHistory.disabled = true;
          btnDeleteHistory.disabled = true;
        }
      } catch (e) {
        console.error("Failed to load history list:", e);
      }
    }

    historySelect.addEventListener("change", () => {
      const hasVal = Boolean(historySelect.value);
      btnLoadHistory.disabled = !hasVal;
      btnDeleteHistory.disabled = !hasVal;
    });

    function applyHistoryImageToViewer(hist) {
      if (hist.image_base64) {
        AppState.analysis.mimeType = hist.mime_type || "image/jpeg";
        const imgSrc = hist.image_base64.startsWith("data:")
          ? hist.image_base64
          : `data:${AppState.analysis.mimeType};base64,${hist.image_base64}`;
        AppState.analysis.imageBase64 = imgSrc;
        const compareImg = document.getElementById("compare-image");
        if (compareImg) compareImg.src = imgSrc;
        const previewThumb = document.getElementById("preview-thumbnail");
        if (previewThumb) {
          previewThumb.src = imgSrc;
          previewThumb.style.display = "block";
        }
        const btnToggle = document.getElementById("btn-toggle-viewer");
        if (btnToggle) btnToggle.style.display = "inline-flex";
      }
      AppState.analysis.dewarpStatus = hist.dewarp_status || null;
      updateDewarpStatusBadge(AppState.analysis.dewarpStatus);
    }

    async function loadHistoryById(id, options = {}) {
      if (!id) return false;
      const { focusDate = null, switchToImport = false } = options;
      try {
        if (btnLoadHistory) {
          btnLoadHistory.disabled = true;
          btnLoadHistory.textContent = "読み込み中...";
        }
        const json = await ApiClient.getJson(`/api/history/detail?id=${id}`);
        if (!json.success || !json.data) throw new Error("データの取得に失敗しました");

        const hist = json.data;
        AppState.history.currentId = hist.id;
        AppState.history.currentMeta = {
          id: hist.id,
          title: hist.title || "シフト",
          registered: Boolean(hist.registered),
          registered_at: hist.registered_at || "",
          created_at: hist.created_at || ""
        };
        if (historySelect) historySelect.value = hist.id;
        if (btnDeleteHistory) btnDeleteHistory.disabled = false;

        // 元画像をビューワーにセット
        applyHistoryImageToViewer(hist);

        if (switchToImport) {
          switchMainTab("import");
        }

        renderResult({
          shifts: hist.shifts,
          target_name: hist.target_name || "皿田"
        });
        if (btnRetryEventsEl) {
          btnRetryEventsEl.style.display = "inline-flex";
          btnRetryEventsEl.disabled = false;
        }

        if (focusDate && Array.isArray(AppState.analysis.shifts)) {
          const targetIdx = AppState.analysis.shifts.findIndex(s => s && s.date === focusDate);
          if (targetIdx !== -1) {
            selectCalendarDate(targetIdx, { scrollTable: true, debounceImage: false });
          }
        }

        historyActiveInfo.style.display = "flex";
        updateHistoryActiveBanner(AppState.history.currentMeta);
        showToast(`履歴「${hist.title}」を読み込みました`, "success");
        return true;
      } catch (e) {
        showToast(`読み込みエラー: ${e.message}`, "error");
        return false;
      } finally {
        if (btnLoadHistory) {
          btnLoadHistory.disabled = false;
          btnLoadHistory.textContent = "閲覧・読み込む";
        }
      }
    }

    btnLoadHistory.addEventListener("click", async () => {
      const id = historySelect.value;
      if (!id) return;
      await loadHistoryById(id);
    });

    btnDeleteHistory.addEventListener("click", async () => {
      const id = historySelect.value;
      if (!id) return;
      if (!confirm("選択したシフト履歴を削除してもよろしいですか？")) return;

      try {
        const { data: json } = await ApiClient.postJson("/api/history/delete", { id });
        if (json.success) {
          showToast("履歴を削除しました", "success");
          await loadHistoryList();
          await fetchRegisteredCalendarShifts();
          if (currentHistoryId === id) {
            historyActiveInfo.style.display = "none";
            currentHistoryId = null;
            currentHistoryMeta = null;
          }
          if (latestHistoryId === id) {
            latestHistoryId = null;
          }
        } else {
          throw new Error("削除に失敗しました");
        }
      } catch (e) {
        showToast(`削除エラー: ${e.message}`, "error");
      }
    });

    btnResetHistory.addEventListener("click", () => {
      if (latestAnalyzedShifts.length > 0) {
        renderResult({ shifts: latestAnalyzedShifts, target_name: document.getElementById("target-name").value.trim() });
        if (latestImageBase64) {
          const imgSrc = latestImageBase64.startsWith("data:")
            ? latestImageBase64
            : `data:${currentMimeType};base64,${latestImageBase64}`;
          currentImageBase64 = imgSrc;
          const compareImg = document.getElementById("compare-image");
          if (compareImg) compareImg.src = imgSrc;
        }
        currentDewarpStatus = latestDewarpStatus;
        updateDewarpStatusBadge(currentDewarpStatus);
        historyActiveInfo.style.display = "none";
        currentHistoryId = latestHistoryId;
        currentHistoryMeta = null;
        showToast("最新の解析結果に戻りました", "normal");
      } else {
        historyActiveInfo.style.display = "none";
        currentHistoryId = latestHistoryId;
        currentHistoryMeta = null;
      }
    });

    async function autoSaveHistory(data, options = {}) {
      try {
        const shifts = data.shifts || [];
        const title = buildHistoryTitle(shifts);
        const payload = {
          title,
          target_name: data.target_name || "皿田",
          shifts,
          image_base64: currentImageBase64,
          mime_type: currentMimeType,
          image_name: currentImageName,
          dewarp_status: currentDewarpStatus
        };
        if (options.reuseId && currentHistoryId) {
          payload.id = currentHistoryId;
        }

        const { data: saved } = await ApiClient.postJson("/api/history/save", payload);
        if (saved && saved.id) {
          currentHistoryId = saved.id;
          if (!historyActiveInfo || historyActiveInfo.style.display !== "flex") {
            latestHistoryId = saved.id;
          }
        }
        await loadHistoryList();
      } catch (e) {
        console.error("Auto save history error:", e);
      }
    }

    // Save config
    async function saveAppConfig() {
      const startMonthEl = document.getElementById("paid-leave-start-month");
      const startDayEl = document.getElementById("paid-leave-start-day");
      const annualDaysEl = document.getElementById("paid-leave-annual-days");
      const hoursPerDayEl = document.getElementById("paid-leave-hours-per-day");
      const startMonth = clampInt(startMonthEl ? startMonthEl.value : paidLeaveConfig.startMonth, 4, 1, 12);
      const startDay = clampInt(startDayEl ? startDayEl.value : paidLeaveConfig.startDay, 1, 1, 31);
      const annualDays = clampInt(annualDaysEl ? annualDaysEl.value : paidLeaveConfig.annualDays, 20, 0, 365);
      const hoursPerDay = clampHalfHour(hoursPerDayEl ? hoursPerDayEl.value : paidLeaveConfig.hoursPerDay, 8, 1, 24);

      const collectedDefs = collectSettingsTimeDefsFromEditor();
      if (collectedDefs.error) {
        showToast(collectedDefs.error, "error");
        return false;
      }

      const cfg = {
        api_key: document.getElementById("api-key").value.trim(),
        default_name: document.getElementById("target-name").value.trim(),
        calendar_name: document.getElementById("calendar-name").value.trim(),
        theme: currentThemeMode,
        time_definitions: collectedDefs.defs || masterTimeDefs,
        paid_leave_start_month: startMonth,
        paid_leave_start_day: startDay,
        paid_leave_annual_days: annualDays,
        paid_leave_hours_per_day: hoursPerDay
      };
      try {
        const { res, data: respJson } = await ApiClient.postJson("/api/config", cfg);
        if (res && !res.ok) {
          throw new Error((respJson && respJson.error) || "設定保存に失敗しました");
        }
        if (cfg.api_key) AppState.ui.hasServerApiKey = true;
        masterTimeDefs = (respJson && respJson.config && respJson.config.time_definitions)
          ? respJson.config.time_definitions
          : cfg.time_definitions;
        paidLeaveConfig = { startMonth, startDay, annualDays, hoursPerDay };
        syncPaidLeaveSettingsInputs();
        syncBasicConfigSummary();
        renderMasterDefs(masterTimeDefs);
        renderCalendarViewDefs(masterTimeDefs);
        updateMonthlyMetrics();
        renderMonthlyCalendarView();
        showToast("設定を保存しました", "success");
        return true;
      } catch (e) {
        showToast(e && e.message ? e.message : "設定保存に失敗しました", "error");
        return false;
      }
    }
    const btnSaveCfgEl = document.getElementById("btn-save-cfg");
    if (btnSaveCfgEl) btnSaveCfgEl.addEventListener("click", saveAppConfig);
    if (btnSaveSettingsModal) {
      btnSaveSettingsModal.addEventListener("click", async () => {
        const ok = await saveAppConfig();
        if (ok) closeSettingsModal();
      });
    }

    // File Drop & Selection
    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");
    const previewBar = document.getElementById("file-preview-bar");
    const previewFilename = document.getElementById("preview-filename");
    const previewFilesize = document.getElementById("preview-filesize");
    const btnAnalyze = document.getElementById("btn-analyze");

    dropZone.addEventListener("click", () => fileInput.click());
    dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("dragover"); });
    dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
    dropZone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropZone.classList.remove("dragover");
      if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
    });

    fileInput.addEventListener("change", (e) => {
      if (e.target.files.length) handleFile(e.target.files[0]);
    });

    function triggerAutoAnalyzeFromQuickAction(preloadKey) {
      if (!preloadKey || autoAnalyzedPreloadKeys.has(preloadKey) || isAnalyzing || !currentImageBase64) {
        return;
      }
      if (!isConfigLoaded) {
        pendingAutoAnalyzeKey = preloadKey;
        return;
      }
      autoAnalyzedPreloadKeys.add(preloadKey);
      const apiKey = (document.getElementById("api-key").value || "").trim();
      if (!apiKey) {
        showToast("設定からGemini APIキーを入力するとクイックアクション時に自動解析されます", "error");
        return;
      }
      showToast("クイックアクションから自動解析を開始します...", "success");
      runShiftAnalysis();
    }

    function handlePreloadedImageData(data) {
      try {
        const preloadKey = data.preload_id || `${data.file_name}_${data.file_size}`;
        if (preloadKey === lastLoadedPreloadKey) {
          // すでに同一画像がロード済みの場合は上書きをスキップ（2秒ごとのハートビートによる上書き防止）
          return;
        }
        lastLoadedPreloadKey = preloadKey;
        isCorrectedImageActive = false;
        switchMainTab("import");

        currentImageName = data.file_name;
        currentMimeType = data.mime_type || "image/jpeg";
        if (data.image_base64.startsWith("data:")) {
          currentImageBase64 = data.image_base64;
        } else {
          currentImageBase64 = `data:${currentMimeType};base64,${data.image_base64}`;
        }

        previewFilename.textContent = data.file_name;
        previewFilesize.textContent = `${(data.file_size / 1024).toFixed(1)} KB`;
        const thumb = document.getElementById("preview-thumbnail");
        if (thumb) {
          thumb.src = currentImageBase64;
          thumb.style.display = "block";
        }
        previewBar.style.display = "flex";
        dropZone.style.display = "none";
        btnAnalyze.disabled = false;

        const compareImg = document.getElementById("compare-image");
        if (compareImg) compareImg.src = currentImageBase64;
        currentDewarpStatus = data.dewarp_status || null;
        updateDewarpStatusBadge(currentDewarpStatus);

        const btnViewer = document.getElementById("btn-toggle-viewer");
        if (btnViewer) btnViewer.style.display = "inline-flex";

        if (data.auto_analyze) {
          triggerAutoAnalyzeFromQuickAction(preloadKey);
        } else {
          showToast(`画像を読み込みました: ${data.file_name}`, "success");
        }
      } catch (err) {
        console.error("handlePreloadedImageData error:", err);
      }
    }

    async function checkPreloadedImage() {
      try {
        const json = await ApiClient.getJson("/api/get_preloaded");
        if (json && json.has_image && json.data) {
          handlePreloadedImageData(json.data);
        }
      } catch (e) { }
    }

    function handleFile(file) {
      if (!file.type.startsWith("image/")) {
        showToast("画像ファイル（JPG, PNGなど）を選択してください", "error");
        return;
      }
      currentImageName = file.name;
      previewFilename.textContent = file.name;
      previewFilesize.textContent = `${(file.size / 1024).toFixed(1)} KB`;

      const reader = new FileReader();
      reader.onload = (e) => {
        const rawData = e.target.result;
        const img = new Image();
        img.onload = () => {
          const maxDim = 3600;
          let w = img.width;
          let h = img.height;
          if (w > maxDim || h > maxDim) {
            if (w > h) { h = Math.round((h * maxDim) / w); w = maxDim; }
            else { w = Math.round((w * maxDim) / h); h = maxDim; }
          }
          const canvas = document.createElement("canvas");
          canvas.width = w;
          canvas.height = h;
          const ctx = canvas.getContext("2d");
          ctx.drawImage(img, 0, 0, w, h);
          currentImageBase64 = canvas.toDataURL("image/jpeg", 0.95);
          currentMimeType = "image/jpeg";

          document.getElementById("compare-image").src = currentImageBase64;
          const thumb = document.getElementById("preview-thumbnail");
          if (thumb) {
            thumb.src = currentImageBase64;
            thumb.style.display = "block";
          }
          previewBar.style.display = "flex";
          dropZone.style.display = "none";
          btnAnalyze.disabled = false;

          // 自動水平・垂直補正（Phase 1）を即座に適用
          currentDewarpStatus = "processing";
          updateDewarpStatusBadge(currentDewarpStatus);
          ApiClient.postJson("/api/dewarp_preview", { image_base64: currentImageBase64 })
            .then(({ data: res }) => {
              if (res && res.success) {
                const status = res.dewarp_status || (res.corrected_image_base64 ? "applied" : "not_applied");
                if (res.corrected_image_base64 && status !== "not_applied") {
                  currentImageBase64 = res.corrected_image_base64;
                  document.getElementById("compare-image").src = currentImageBase64;
                  if (thumb) thumb.src = currentImageBase64;
                }
                currentDewarpStatus = status;
                updateDewarpStatusBadge(currentDewarpStatus);
              } else {
                currentDewarpStatus = "not_applied";
                updateDewarpStatusBadge(currentDewarpStatus);
              }
            }).catch(() => {
              currentDewarpStatus = "not_applied";
              updateDewarpStatusBadge(currentDewarpStatus);
            });
        };
        img.src = rawData;
      };
      reader.readAsDataURL(file);
    }

    document.getElementById("btn-remove-file").addEventListener("click", () => {
      currentImageBase64 = null;
      currentDewarpStatus = null;
      updateDewarpStatusBadge(null);
      fileInput.value = "";
      const thumb = document.getElementById("preview-thumbnail");
      if (thumb) {
        thumb.src = "";
        thumb.style.display = "none";
      }
      if (imageFocusTimer) {
        clearTimeout(imageFocusTimer);
        imageFocusTimer = null;
      }
      const hBox = document.getElementById("viewer-highlight-box");
      if (hBox) hBox.style.display = "none";
      selectedCalendarIdx = null;
      previewBar.style.display = "none";
      dropZone.style.display = "block";
      btnAnalyze.disabled = true;
      document.getElementById("result-container").style.display = "none";
    });

    // Image Viewer Logic
    const btnToggleViewer = document.getElementById("btn-toggle-viewer");
    const viewerWrapper = document.getElementById("viewer-wrapper");
    const viewerCanvas = document.getElementById("viewer-canvas");
    const viewerStage = document.getElementById("viewer-stage");
    const compareImg = document.getElementById("compare-image");
    const zoomText = document.getElementById("zoom-text");
    const viewerHighlightBox = document.getElementById("viewer-highlight-box");

    function updateViewerTransform() {
      viewerStage.style.transform = `translate(${panX}px, ${panY}px) scale(${scale})`;
      zoomText.textContent = `${Math.round(scale * 100)}%`;
    }

    function fitViewerToScreen() {
      if (!compareImg.naturalWidth) return;
      const vWidth = viewerCanvas.clientWidth;
      const vHeight = viewerCanvas.clientHeight;
      const imgWidth = compareImg.naturalWidth;
      const imgHeight = compareImg.naturalHeight;

      const scaleX = vWidth / imgWidth;
      const scaleY = vHeight / imgHeight;
      scale = Math.min(scaleX, scaleY, 1.0);

      panX = (vWidth - imgWidth * scale) / 2;
      panY = (vHeight - imgHeight * scale) / 2;
      updateViewerTransform();
    }

    function openViewer(fit = false) {
      viewerWrapper.style.display = "block";
      btnToggleViewer.textContent = "元画像を閉じる";
      if (fit) setTimeout(fitViewerToScreen, 50);
    }

    compareImg.addEventListener("load", () => {
      if (viewerWrapper.style.display === "block") {
        setTimeout(fitViewerToScreen, 30);
      }
    });

    btnToggleViewer.addEventListener("click", () => {
      const isVisible = viewerWrapper.style.display === "block";
      viewerWrapper.style.display = isVisible ? "none" : "block";
      btnToggleViewer.textContent = isVisible ? "元画像を表示" : "元画像を閉じる";
      if (!isVisible) setTimeout(fitViewerToScreen, 40);
    });

    function focusImageRegion(box2d) {
      if (!box2d || box2d.length < 4) return;
      openViewer(false);

      const doFocus = () => {
        const imgW = compareImg.naturalWidth;
        const imgH = compareImg.naturalHeight;
        if (!imgW || !imgH) return;

        const ymin = (box2d[0] / 1000) * imgH;
        const xmin = (box2d[1] / 1000) * imgW;
        const ymax = (box2d[2] / 1000) * imgH;
        const xmax = (box2d[3] / 1000) * imgW;

        const boxW = Math.max(xmax - xmin, 16);
        const boxH = Math.max(ymax - ymin, 16);

        // ハイライト枠をセット
        viewerHighlightBox.style.left = `${xmin}px`;
        viewerHighlightBox.style.top = `${ymin}px`;
        viewerHighlightBox.style.width = `${boxW}px`;
        viewerHighlightBox.style.height = `${boxH}px`;
        viewerHighlightBox.style.display = "block";

        // マス目が中央に来るようパン＆ズーム
        const cW = viewerCanvas.clientWidth;
        const cH = viewerCanvas.clientHeight;
        const targetScale = Math.min(Math.max(scale, 1.35), 2.5);

        const centerX = xmin + boxW / 2;
        const centerY = ymin + boxH / 2;

        panX = cW / 2 - centerX * targetScale;
        panY = cH / 2 - centerY * targetScale;
        scale = targetScale;

        viewerStage.style.transition = "transform 0.4s cubic-bezier(0.2, 0.9, 0.3, 1)";
        updateViewerTransform();
        setTimeout(() => {
          viewerStage.style.transition = "";
        }, 420);
      };

      if (compareImg.complete && compareImg.naturalWidth) {
        doFocus();
      } else {
        compareImg.onload = doFocus;
      }
    }

    function applyZoom(factor, centerX, centerY) {
      viewerStage.style.transition = "";
      if (centerX === undefined) centerX = viewerCanvas.clientWidth / 2;
      if (centerY === undefined) centerY = viewerCanvas.clientHeight / 2;

      const newScale = Math.min(Math.max(scale * factor, 0.15), 8.0);
      panX = centerX - (centerX - panX) * (newScale / scale);
      panY = centerY - (centerY - panY) * (newScale / scale);
      scale = newScale;
      updateViewerTransform();
    }

    document.getElementById("btn-zoom-in").addEventListener("click", () => applyZoom(1.3));
    document.getElementById("btn-zoom-out").addEventListener("click", () => applyZoom(0.77));
    document.getElementById("btn-zoom-fit").addEventListener("click", fitViewerToScreen);
    document.getElementById("btn-zoom-reset").addEventListener("click", () => {
      scale = 1.0;
      panX = (viewerCanvas.clientWidth - compareImg.naturalWidth) / 2;
      panY = 20;
      updateViewerTransform();
    });

    viewerCanvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      const rect = viewerCanvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      const factor = e.ctrlKey ? Math.exp(-e.deltaY * 0.015) : (e.deltaY < 0 ? 1.15 : 0.87);
      applyZoom(factor, mouseX, mouseY);
    }, { passive: false });

    function findShiftIdxAtViewerPoint(mouseX, mouseY) {
      if (!analyzedShifts || !analyzedShifts.length || !compareImg.naturalWidth || !compareImg.naturalHeight) {
        return -1;
      }
      const imgX = (mouseX - panX) / scale;
      const imgY = (mouseY - panY) / scale;
      const nx = (imgX / compareImg.naturalWidth) * 1000;
      const ny = (imgY / compareImg.naturalHeight) * 1000;

      for (let i = 0; i < analyzedShifts.length; i++) {
        const b = analyzedShifts[i].box_2d;
        if (!b || !Array.isArray(b) || b.length < 4) continue;
        const [ymin, xmin, ymax, xmax] = b;
        if (ny >= ymin && ny <= ymax && nx >= xmin && nx <= xmax) {
          return i;
        }
      }
      return -1;
    }

    viewerCanvas.addEventListener("mousedown", (e) => {
      isDragging = true;
      dragStartX = e.clientX - panX;
      dragStartY = e.clientY - panY;
      dragOriginX = e.clientX;
      dragOriginY = e.clientY;
    });

    window.addEventListener("mousemove", (e) => {
      if (!isDragging) return;
      panX = e.clientX - dragStartX;
      panY = e.clientY - dragStartY;
      updateViewerTransform();
    });

    window.addEventListener("mouseup", (e) => {
      if (!isDragging) return;
      isDragging = false;
      const moved = Math.hypot(e.clientX - dragOriginX, e.clientY - dragOriginY);
      if (moved < 5 && viewerCanvas.contains(e.target)) {
        const rect = viewerCanvas.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;
        const hitIdx = findShiftIdxAtViewerPoint(mouseX, mouseY);
        if (hitIdx !== -1) {
          selectCalendarDate(hitIdx, { scrollTable: true, debounceImage: false });
        }
      }
    });

    viewerCanvas.addEventListener("dblclick", (e) => {
      const rect = viewerCanvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      if (scale < 1.5) applyZoom(2.2 / scale, mouseX, mouseY);
      else fitViewerToScreen();
    });

    // Analyze Progress Bar Controls
    const progressCardEl = document.getElementById("analyze-progress-card");
    const progressPhaseEl = document.getElementById("analyze-progress-phase");
    const progressMetaEl = document.getElementById("analyze-progress-meta");
    const progressFillEl = document.getElementById("analyze-progress-fill");
    const progressDetailEl = document.getElementById("analyze-progress-detail");
    const eventsStatusBadgeEl = document.getElementById("events-status-badge");
    const btnRetryEventsEl = document.getElementById("btn-retry-events");
    const btnSkippedHolidaysToggleEl = document.getElementById("btn-skipped-holidays-toggle");
    const skippedHolidaysToggleLabelEl = document.getElementById("skipped-holidays-toggle-label");
    const skippedHolidaysPanelEl = document.getElementById("skipped-holidays-panel");
    const skippedHolidaysListEl = document.getElementById("skipped-holidays-list");

    function setSkippedHolidaysPanelOpen(open) {
      if (btnSkippedHolidaysToggleEl) {
        btnSkippedHolidaysToggleEl.classList.toggle("is-open", open);
        btnSkippedHolidaysToggleEl.setAttribute("aria-expanded", open ? "true" : "false");
      }
      if (skippedHolidaysPanelEl) {
        skippedHolidaysPanelEl.classList.toggle("is-open", open);
      }
    }

    if (btnSkippedHolidaysToggleEl) {
      btnSkippedHolidaysToggleEl.addEventListener("click", () => {
        const isOpen = skippedHolidaysPanelEl && skippedHolidaysPanelEl.classList.contains("is-open");
        setSkippedHolidaysPanelOpen(!isOpen);
      });
    }

    function renderSkippedHolidaysAccordion(skippedHolidays, showWhenZero = false) {
      const list = Array.isArray(skippedHolidays) ? skippedHolidays.filter(h => h && h.name) : [];
      setSkippedHolidaysPanelOpen(false);
      if (!list.length && !showWhenZero) {
        if (btnSkippedHolidaysToggleEl) {
          btnSkippedHolidaysToggleEl.style.display = "none";
          btnSkippedHolidaysToggleEl.classList.remove("is-zero");
        }
        if (skippedHolidaysListEl) skippedHolidaysListEl.innerHTML = "";
        return;
      }
      if (skippedHolidaysToggleLabelEl) {
        skippedHolidaysToggleLabelEl.textContent = `日本の祝日・Googleカレンダー標準行事スキップ ${list.length}件`;
      }
      if (btnSkippedHolidaysToggleEl) {
        btnSkippedHolidaysToggleEl.style.display = "inline-flex";
        btnSkippedHolidaysToggleEl.classList.toggle("is-zero", list.length === 0);
      }
      if (skippedHolidaysListEl) {
        if (!list.length) {
          skippedHolidaysListEl.innerHTML = `<span class="skipped-holiday-date">今回の勤務表では、日本の祝日・Googleカレンダー標準行事と重複してスキップされた項目はありません。</span>`;
        } else {
          skippedHolidaysListEl.innerHTML = list.map(item => {
            const colNum = Number(item.col);
            let dateLabel = "";
            if (!Number.isNaN(colNum) && colNum >= 1 && analyzedShifts[colNum - 1] && analyzedShifts[colNum - 1].date) {
              const rawDate = String(analyzedShifts[colNum - 1].date);
              const parts = rawDate.split("-");
              dateLabel = parts.length === 3 ? `${parseInt(parts[1], 10)}/${parseInt(parts[2], 10)}` : rawDate;
            }
            const dateHtml = dateLabel ? `<span class="skipped-holiday-date">${escapeHtmlText(dateLabel)}</span>` : "";
            return `<span class="skipped-holiday-chip">${dateHtml}<span>${escapeHtmlText(item.name)}</span></span>`;
          }).join("");
        }
      }
    }

    function updateProgressUI(percent, phase, detail = "", step = 1, state = "running") {
      if (!progressCardEl) return;
      progressCardEl.classList.add("is-visible");
      const pct = Math.max(0, Math.min(100, Math.round(percent || 0)));
      const elapsedSec = analyzeStartTs ? Math.max(0, Math.floor((Date.now() - analyzeStartTs) / 1000)) : 0;

      if (progressPhaseEl) progressPhaseEl.textContent = phase || "解析中...";
      if (progressMetaEl) progressMetaEl.textContent = `${pct}% (${elapsedSec}秒)`;
      if (progressDetailEl) progressDetailEl.textContent = detail || "";

      if (progressFillEl) {
        progressFillEl.style.width = `${pct}%`;
        progressFillEl.classList.remove("is-events", "is-done", "is-error");
        if (state === "done") progressFillEl.classList.add("is-done");
        else if (state === "error") progressFillEl.classList.add("is-error");
        else if (step >= 4) progressFillEl.classList.add("is-events");
      }

      document.querySelectorAll(".analyze-step-pill").forEach(pill => {
        const sNum = parseInt(pill.dataset.step, 10);
        pill.classList.remove("is-active", "is-done");
        if (state === "done") {
          pill.classList.add("is-done");
        } else if (sNum < step) {
          pill.classList.add("is-done");
        } else if (sNum === step && state !== "error") {
          pill.classList.add("is-active");
        }
      });
    }

    function startProgressPolling() {
      stopProgressPolling();
      progressPollTimer = setInterval(async () => {
        try {
          const { res: r, data: p } = await ApiClient.getJsonWithRes("/api/analyze_progress");
          if (!r || !r.ok) return;
          if (p && p.active) {
            updateProgressUI(p.percent, p.phase, p.detail, p.step || 1, "running");
          }
        } catch (e) { }
      }, 500);
    }

    function stopProgressPolling() {
      if (progressPollTimer) {
        clearInterval(progressPollTimer);
        progressPollTimer = null;
      }
    }

    function applyExtractedEventsToUI(eventsMap) {
      if (!eventsMap || !analyzedShifts.length) return 0;
      let applied = 0;
      analyzedShifts.forEach((s, idx) => {
        const colKey = String(idx + 1);
        if (Object.prototype.hasOwnProperty.call(eventsMap, colKey) && eventsMap[colKey]) {
          s.event = String(eventsMap[colKey]).trim();
          applied++;
        }
      });

      // テーブル入力欄を同期更新
      document.querySelectorAll("#shifts-tbody .shift-event").forEach(input => {
        const idx = parseInt(input.dataset.idx, 10);
        if (!Number.isNaN(idx) && analyzedShifts[idx]) {
          input.value = analyzedShifts[idx].event || "";
        }
      });

      renderCalendar(analyzedShifts);
      updateFooterCount();
      return applied;
    }

    async function applyEventAnalysisResultUI(evData, applied) {
      const hasSkipMeta = Object.prototype.hasOwnProperty.call(evData, "skipped_holidays_count");
      const skippedHolidays = Array.isArray(evData.skipped_holidays) ? evData.skipped_holidays : [];
      const skippedCount = Number(evData.skipped_holidays_count || skippedHolidays.length || 0);
      const skippedNames = skippedHolidays.map(h => (h && h.name ? String(h.name) : "")).filter(Boolean);
      const skippedSummary = skippedCount > 0 ? `（祝日等 ${skippedCount}件スキップ）` : "";
      const skippedDetail = skippedNames.length > 0 ? `［除外: ${skippedNames.join("、")}］` : "";

      renderSkippedHolidaysAccordion(skippedHolidays, true);
      if (!hasSkipMeta && skippedHolidaysListEl) {
        skippedHolidaysListEl.innerHTML = `<span class="skipped-holiday-date">古いバックグラウンドサーバーが稼働していたため自動停止しました。もう一度クイックアクション（または launch.command）を実行してください。</span>`;
        setSkippedHolidaysPanelOpen(true);
        try {
          await ApiClient.postEmpty("/api/shutdown");
        } catch (e) { }
      }

      if (eventsStatusBadgeEl) {
        eventsStatusBadgeEl.title = skippedNames.length > 0
          ? `日本の祝日・標準行事と重複するため除外: ${skippedNames.join("、")}`
          : "";
      }

      if (applied > 0) {
        updateProgressUI(
          100,
          "すべての解析が完了しました",
          `シフト ${AppState.analysis.shifts.length}日分 ＋ 行事予定 ${applied}件を抽出しました${skippedSummary}${skippedDetail}`,
          4,
          "done"
        );
        if (eventsStatusBadgeEl) eventsStatusBadgeEl.textContent = `行事予定 ${applied}件を反映済み`;
        showToast(`行事予定を ${applied}件読み取りました${skippedSummary}`, "success");
      } else if (skippedCount > 0) {
        updateProgressUI(
          100,
          "すべての解析が完了しました",
          `日本の祝日・標準行事 ${skippedCount}件をスキップしました（職場行事 0件）${skippedDetail}`,
          4,
          "done"
        );
        if (eventsStatusBadgeEl) eventsStatusBadgeEl.textContent = `行事予定: 0件`;
        showToast(`日本の祝日・標準行事 ${skippedCount}件をスキップしました`, "success");
      } else {
        const candCount = Array.isArray(evData.active_cols) ? evData.active_cols.length : 0;
        const detailMsg = candCount > 0
          ? "API混雑のため行事予定を取得できませんでした（「行事予定のみ再取得」で再試行できます）"
          : "行事予定の記載はありませんでした";
        updateProgressUI(100, "シフト解析完了（行事予定 0件）", detailMsg, 4, "done");
        if (eventsStatusBadgeEl) eventsStatusBadgeEl.textContent = candCount > 0 ? "行事予定: 未取得（再取得可）" : "行事予定: なし";
      }
      if (btnRetryEventsEl) {
        btnRetryEventsEl.style.display = "inline-flex";
        btnRetryEventsEl.disabled = false;
      }
    }

    async function runEventAnalysisPhase(apiKey) {
      if (!AppState.analysis.imageBase64 || !AppState.analysis.shifts.length) return 0;
      if (eventsStatusBadgeEl) {
        eventsStatusBadgeEl.style.display = "inline-flex";
        eventsStatusBadgeEl.textContent = "ステップ 4/4: 行事予定を読み取り中...";
      }
      if (btnRetryEventsEl) {
        btnRetryEventsEl.disabled = true;
      }
      updateProgressUI(80, "ステップ 4/4: 下部の縦書き行事予定を読み取り中...", "シフト記号の表示は完了しました。続けて行事予定を抽出しています", 4, "running");

      try {
        const { res: evRes, data: evJson } = await ApiClient.postJson("/api/analyze_events", {
          image_base64: AppState.analysis.imageBase64,
          api_key: apiKey
        });
        if (!evRes.ok || evJson.error) {
          throw new Error(evJson.error || "行事予定の読み取りに失敗しました");
        }
        const evData = evJson.data || {};
        const applied = applyExtractedEventsToUI(evData.events || {});
        await applyEventAnalysisResultUI(evData, applied);
        return applied;
      } catch (evErr) {
        updateProgressUI(100, "シフト解析完了（行事予定エラー）", `${evErr.message}（「行事予定のみ再取得」で再試行できます）`, 4, "done");
        if (eventsStatusBadgeEl) eventsStatusBadgeEl.textContent = "行事予定: 取得失敗（再取得可）";
        if (btnRetryEventsEl) {
          btnRetryEventsEl.style.display = "inline-flex";
          btnRetryEventsEl.disabled = false;
        }
        showToast(`行事予定の読み取りに失敗しました: ${evErr.message}`, "error");
        return 0;
      }
    }

    if (btnRetryEventsEl) {
      btnRetryEventsEl.addEventListener("click", async () => {
        const apiKey = document.getElementById("api-key").value.trim();
        if (!apiKey && !AppState.ui.hasServerApiKey) { showToast("Gemini APIキーを入力してください", "error"); return; }
        analyzeStartTs = Date.now();
        startProgressPolling();
        try {
          await runEventAnalysisPhase(apiKey);
          latestAnalyzedShifts = JSON.parse(JSON.stringify(analyzedShifts));
          await autoSaveHistory({
            shifts: analyzedShifts,
            target_name: document.getElementById("target-name").value.trim() || "皿田"
          }, { reuseId: true });
        } finally {
          stopProgressPolling();
        }
      });
    }

    // Analyze Action (2段階分離: Step 1 シフト記号 → Step 2 下部の縦書き行事予定)
    async function runShiftAnalysis() {
      if (AppState.analysis.isAnalyzing) return;
      const apiKey = document.getElementById("api-key").value.trim();
      const targetName = document.getElementById("target-name").value.trim();

      if (!apiKey && !AppState.ui.hasServerApiKey) { showToast("設定からGemini APIキーを入力してください", "error"); return; }
      if (!AppState.analysis.imageBase64) { showToast("画像を選択してください", "error"); return; }

      AppState.analysis.isAnalyzing = true;
      renderSkippedHolidaysAccordion([]);
      btnAnalyze.disabled = true;
      btnAnalyze.textContent = "解析中...";
      analyzeStartTs = Date.now();
      updateProgressUI(5, "ステップ 1/4: 画像をサーバーへ送信中...", "歪み補正と罫線解析を準備しています", 1, "running");
      startProgressPolling();

      try {
        // Step 1: シフト記号の解析のみを実行して即座に結果表示
        const { res, data: json } = await ApiClient.postJson("/api/analyze", {
          image_base64: AppState.analysis.imageBase64,
          mime_type: AppState.analysis.mimeType,
          target_name: targetName,
          api_key: apiKey,
          time_definitions: AppState.analysis.masterTimeDefs
        });

        if (!res.ok || json.error) throw new Error(json.error || "解析に失敗しました");

        // 【Phase 1】たわみ・歪み補正済み画像があればビュアーとサムネイルを更新
        if (json.data && json.data.corrected_image_base64) {
          isCorrectedImageActive = true;
          currentImageBase64 = json.data.corrected_image_base64;
          const compareImg = document.getElementById("compare-image");
          if (compareImg) compareImg.src = json.data.corrected_image_base64;
          const pImg = document.getElementById("preview-thumbnail");
          if (pImg) pImg.src = json.data.corrected_image_base64;
        }
        if (json.data && json.data.dewarp_status) {
          if (!(currentDewarpStatus === "applied" && json.data.dewarp_status === "already_dewarped")) {
            currentDewarpStatus = json.data.dewarp_status;
          }
          updateDewarpStatusBadge(currentDewarpStatus);
        }

        renderResult(json.data);
        latestAnalyzedShifts = JSON.parse(JSON.stringify(json.data.shifts || []));
        latestImageBase64 = currentImageBase64;
        latestDewarpStatus = currentDewarpStatus;

        // Step 2: 続けて下部の縦書き行事予定を独立APIで解析して反映
        if (json.data && json.data.has_event_candidates) {
          showToast("シフト記号を表示しました。続けて行事予定を読み取ります...", "success");
          await runEventAnalysisPhase(apiKey);
          json.data.shifts = analyzedShifts;
          latestAnalyzedShifts = JSON.parse(JSON.stringify(analyzedShifts));
        } else {
          updateProgressUI(100, "すべての解析が完了しました", `全 ${analyzedShifts.length}日分のシフトを抽出しました`, 4, "done");
          if (eventsStatusBadgeEl) eventsStatusBadgeEl.style.display = "none";
          if (btnRetryEventsEl) btnRetryEventsEl.style.display = "inline-flex";
          showToast("解析が完了し、歪み補正済み画像を表示しました", "success");
        }

        await autoSaveHistory(json.data);
      } catch (err) {
        updateProgressUI(100, "解析エラーが発生しました", err.message, 3, "error");
        showToast(`エラー: ${err.message}`, "error");
      } finally {
        isAnalyzing = false;
        stopProgressPolling();
        btnAnalyze.disabled = false;
        btnAnalyze.textContent = "シフトを解析";
      }
    }
    btnAnalyze.addEventListener("click", runShiftAnalysis);

    function escapeHtmlText(str) {
      return String(str == null ? "" : str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function isIncludeEventsEnabled() {
      const cb = document.getElementById("check-include-events");
      return cb ? cb.checked : true;
    }

    function updateFooterCount() {
      const checkedBoxes = document.querySelectorAll(".shift-check:checked");
      const count = checkedBoxes.length;
      const includeEvents = isIncludeEventsEnabled();
      let eventCount = 0;
      if (includeEvents) {
        checkedBoxes.forEach(cb => {
          const idx = parseInt(cb.dataset.idx, 10);
          const ev = analyzedShifts[idx] && analyzedShifts[idx].event ? String(analyzedShifts[idx].event).trim() : "";
          if (ev) eventCount++;
        });
      }
      const eventSuffix = eventCount > 0 ? `（＋行事 ${eventCount}件）` : "";
      document.getElementById("footer-count").textContent = `登録対象: ${count}件${eventSuffix}`;
    }

    const checkIncludeEventsEl = document.getElementById("check-include-events");
    if (checkIncludeEventsEl) {
      checkIncludeEventsEl.addEventListener("change", updateFooterCount);
    }

    // Shift options definition
    const shiftOptions = [
      { key: "早A", label: "早A (06:00〜15:00)", start: "06:00", end: "15:00", status: "work" },
      { key: "早B", label: "早B (06:30〜15:30)", start: "06:30", end: "15:30", status: "work" },
      { key: "早C", label: "早C (07:00〜16:00)", start: "07:00", end: "16:00", status: "work" },
      { key: "早D", label: "早D (08:00〜17:00)", start: "08:00", end: "17:00", status: "work" },
      { key: "日", label: "日 (08:30〜17:30)", start: "08:30", end: "17:30", status: "work" },
      { key: "遅A", label: "遅A (09:00〜18:00)", start: "09:00", end: "18:00", status: "work" },
      { key: "遅B", label: "遅B (09:30〜18:30)", start: "09:30", end: "18:30", status: "work" },
      { key: "遅C", label: "遅C (10:00〜19:00)", start: "10:00", end: "19:00", status: "work" },
      { key: "休", label: "休 (終日休み)", start: "", end: "", status: "holiday" },
      { key: "㊒", label: "有給 (終日有給休暇)", start: "", end: "", status: "paid_leave" },
      { key: "その他", label: "その他 (直接入力)", start: "", end: "", status: "work" }
    ];

    // 月単位での出勤・休み・有給日数の動的集計
    function updateMonthlyMetrics() {
      const hpd = clampHalfHour(paidLeaveConfig.hoursPerDay, 8, 1, 24);
      const halfPerDay = Math.max(2, Math.round(hpd * 2));
      const months = {};
      analyzedShifts.forEach(s => {
        if (!s.date) return;
        const ym = s.date.substring(0, 7); // "YYYY-MM"
        if (!months[ym]) {
          const parts = ym.split("-");
          months[ym] = {
            ym: ym,
            label: `${parseInt(parts[0], 10)}年${parseInt(parts[1], 10)}月`,
            work: 0,
            holiday: 0,
            paidHalfHours: 0,
            total: 0
          };
        }
        months[ym].total++;
        if (s.status === "work") {
          months[ym].work++;
          const hLeave = clampHalfHour(s.hourly_paid_leave, 0, 0, hpd - 0.5);
          months[ym].paidHalfHours += Math.round(hLeave * 2);
        } else if (s.status === "holiday") {
          months[ym].holiday++;
        } else if (s.status === "paid_leave") {
          months[ym].paidHalfHours += halfPerDay;
        }
      });

      const sortedKeys = Object.keys(months).sort();

      // 最も日数が多い月をメイン月として判定
      let mainKey = "";
      let maxCount = -1;
      sortedKeys.forEach(k => {
        if (months[k].total > maxCount) {
          maxCount = months[k].total;
          mainKey = k;
        }
      });

      const container = document.getElementById("monthly-metrics-container");
      container.innerHTML = "";

      sortedKeys.forEach(k => {
        const m = months[k];
        const isMain = k === mainKey;
        const card = document.createElement("div");
        card.className = `month-card ${isMain ? "main-month" : ""}`;

        const badgeText = isMain ? '<span style="font-size:10px; color:var(--accent); font-weight:600; padding: 1px 6px; background: rgba(0,122,255,0.1); border-radius: 9999px;">対象月</span>' : '';

        card.innerHTML = `
          <div class="month-title-capsule">
            <span>${m.label}</span>
            ${badgeText}
            <span style="font-size:11px; color:var(--label-secondary); font-weight:normal;">(計${m.total}日間)</span>
          </div>
          <div class="month-badges">
            <div class="metric-capsule">
              <span class="metric-dot work"></span>
              <span>出勤: <strong>${m.work}日</strong></span>
            </div>
            <div class="metric-capsule">
              <span class="metric-dot holiday"></span>
              <span>休み: <strong>${m.holiday}日</strong></span>
            </div>
            <div class="metric-capsule">
              <span class="metric-dot paid"></span>
              <span>有給休暇: <strong>${formatPaidLeaveDaysAndHours(m.paidHalfHours, hpd)}</strong></span>
            </div>
          </div>
        `;
        container.appendChild(card);
      });
    }

    function evaluateShiftQualityClient(shifts) {
      const list = Array.isArray(shifts) ? shifts : [];
      if (!list.length) {
        return { scorePercent: 100, total: 0, okCount: 0, warningCount: 0, errorCount: 0, reviewCount: 0, reviewIndices: [] };
      }
      const defs = masterTimeDefs || {};
      const dateCounts = {};
      list.forEach(s => {
        const d = String((s && s.date) || "").trim();
        if (d) dateCounts[d] = (dateCounts[d] || 0) + 1;
      });
      let consecutiveWork = 0;
      let okCount = 0;
      let warningCount = 0;
      let errorCount = 0;
      let scoreSum = 0;
      const reviewIndices = [];

      list.forEach((s, idx) => {
        if (!s) return;
        const reasons = [];
        let level = "ok";
        const dateStr = String(s.date || "").trim();
        if (!/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
          level = "error";
          reasons.push("日付形式が不正です");
        } else if ((dateCounts[dateStr] || 0) > 1) {
          level = "error";
          reasons.push("同一日付が重複しています");
        }
        const status = String(s.status || "work");
        const stType = String(s.type || "").trim();
        const isWork = status === "work" && !s.is_holiday && !s.is_paid_leave;
        if (isWork) {
          consecutiveWork += 1;
          if (!stType) {
            level = "error";
            reasons.push("シフト記号が空です");
          } else if (!defs[stType] && (!s.start_time || !s.end_time)) {
            level = "error";
            reasons.push(`未定義のシフト記号です (${stType})`);
          } else if (!s.start_time || !s.end_time) {
            if (level !== "error") level = "warning";
            reasons.push("開始・終了時刻が未設定です");
          }
          if (consecutiveWork >= 6 && !s._user_verified) {
            if (level !== "error") level = "warning";
            reasons.push(`${consecutiveWork}連勤になっています（要確認）`);
          }
        } else {
          consecutiveWork = 0;
        }
        const conf = String(s.confidence || "high").trim().toLowerCase();
        if (!s._user_verified) {
          if (conf === "low") {
            if (level !== "error") level = "warning";
            reasons.push("AI読み取り確信度が低いセルです");
          } else if (conf === "medium") {
            if (level !== "error") level = "warning";
            reasons.push("AI読み取り確信度が中程度です");
          }
        }
        s.quality_level = level;
        s.quality_reasons = reasons;
        if (level === "error") {
          errorCount += 1;
          reviewIndices.push(idx);
        } else if (level === "warning") {
          warningCount += 1;
          scoreSum += 0.6;
          reviewIndices.push(idx);
        } else {
          okCount += 1;
          scoreSum += 1.0;
        }
      });
      const total = okCount + warningCount + errorCount;
      const scorePercent = total > 0 ? Math.max(0, Math.min(100, Math.round((scoreSum / total) * 100))) : 100;
      return {
        scorePercent,
        total,
        okCount,
        warningCount,
        errorCount,
        reviewCount: warningCount + errorCount,
        reviewIndices
      };
    }

    function renderQualityIconSvg(level, reasons) {
      const lv = level === "error" ? "error" : (level === "warning" ? "warning" : "ok");
      const reasonText = Array.isArray(reasons) && reasons.length
        ? reasons.join(" / ")
        : "読み取り正常";
      if (lv === "error") {
        return `<span class="quality-icon is-error" title="${escapeHtmlText(reasonText)}" aria-label="${escapeHtmlText(reasonText)}"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg></span>`;
      }
      if (lv === "warning") {
        return `<span class="quality-icon is-warning" title="${escapeHtmlText(reasonText)}" aria-label="${escapeHtmlText(reasonText)}"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg></span>`;
      }
      return `<span class="quality-icon is-ok" title="${escapeHtmlText(reasonText)}" aria-label="${escapeHtmlText(reasonText)}"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"></polyline></svg></span>`;
    }

    let currentReviewIndices = [];
    let currentReviewCursor = -1;

    function updateQualitySummaryUI(shifts) {
      const card = document.getElementById("quality-summary-card");
      const scoreEl = document.getElementById("quality-score-text");
      const badgeEl = document.getElementById("quality-review-badge");
      const fillEl = document.getElementById("quality-progress-fill");
      const btnJump = document.getElementById("btn-jump-next-review");
      const list = Array.isArray(shifts) ? shifts : [];
      const q = evaluateShiftQualityClient(list);
      currentReviewIndices = q.reviewIndices;
      if (currentReviewCursor >= currentReviewIndices.length) currentReviewCursor = -1;

      if (!card) return q;
      if (!list.length) {
        card.style.display = "none";
        return q;
      }
      card.style.display = "flex";
      if (scoreEl) scoreEl.textContent = `${q.scorePercent}%`;
      if (badgeEl) {
        badgeEl.classList.remove("is-ok", "is-warning", "is-error");
        if (q.errorCount > 0) {
          badgeEl.classList.add("is-error");
          badgeEl.textContent = `要確認 ${q.reviewCount}件（エラー ${q.errorCount}件）`;
        } else if (q.warningCount > 0) {
          badgeEl.classList.add("is-warning");
          badgeEl.textContent = `要確認 ${q.reviewCount}件`;
        } else {
          badgeEl.classList.add("is-ok");
          badgeEl.textContent = "すべて正常";
        }
      }
      if (fillEl) {
        fillEl.style.width = `${q.scorePercent}%`;
        fillEl.classList.remove("is-high", "is-mid", "is-low");
        if (q.errorCount > 0 || q.scorePercent < 75) fillEl.classList.add("is-low");
        else if (q.warningCount > 0 || q.scorePercent < 95) fillEl.classList.add("is-mid");
        else fillEl.classList.add("is-high");
      }
      if (btnJump) {
        btnJump.style.display = q.reviewCount > 0 ? "inline-flex" : "none";
      }
      return q;
    }

    function createShiftTableRow(s, idx) {
      const tr = document.createElement("tr");

      let currentKey = s.type;
      if (s.status === "holiday") currentKey = "休";
      else if (s.status === "paid_leave") currentKey = "有給";
      else if (!shiftOptions.some(opt => opt.key === currentKey)) currentKey = "その他";

      tr.dataset.key = currentKey;
      tr.dataset.idx = idx;
      if (AppState.ui.selectedCalendarIdx === idx) tr.classList.add("is-selected");
      if (s.quality_level === "error") tr.classList.add("is-quality-error");
      else if (s.quality_level === "warning") tr.classList.add("is-quality-warning");

      tr.addEventListener("mouseenter", () => {
        selectCalendarDate(idx, { scrollTable: false, debounceImage: true });
      });
      tr.addEventListener("click", () => {
        selectCalendarDate(idx, { scrollTable: false, debounceImage: false });
      });
      tr.addEventListener("focusin", () => {
        selectCalendarDate(idx, { scrollTable: false, debounceImage: false });
      });

      const selectOptionsHtml = shiftOptions
        .map(opt => `<option value="${escapeHtmlText(opt.key)}" ${opt.key === currentKey ? "selected" : ""}>${escapeHtmlText(opt.label)}</option>`)
        .join("");

      const dayColor = s.day_of_week === "土" ? "color:var(--accent);font-weight:600;" : (s.day_of_week === "日" ? "color:#ff453a;font-weight:600;" : "color:var(--label-secondary);");
      const dateParts = String(s.date || "").split("-");
      const shortDateLabel = dateParts.length === 3
        ? `${parseInt(dateParts[1], 10)}/${parseInt(dateParts[2], 10)}`
        : String(s.date || "");
      const dowLabel = s.day_of_week ? `(${s.day_of_week})` : "";
      const isWorkRow = s.status === "work";
      const curHourlyLeave = isWorkRow ? clampHalfHour(s.hourly_paid_leave, 0, 0, paidLeaveConfig.hoursPerDay - 0.5) : 0;
      const hourlyOptionsHtml = buildHourlyLeaveOptionsHtml(curHourlyLeave, paidLeaveConfig.hoursPerDay);

      tr.innerHTML = `
        <td style="text-align: center;">
          <input type="checkbox" class="shift-check" data-idx="${idx}" checked>
        </td>
        <td class="shift-date-cell" title="${escapeHtmlText(s.date || "")}">
          <span style="display: inline-flex; align-items: center; gap: 4px;">
            ${renderQualityIconSvg(s.quality_level, s.quality_reasons)}
            <strong>${escapeHtmlText(shortDateLabel)}</strong>
            <span style="${dayColor}">${escapeHtmlText(dowLabel)}</span>
          </span>
        </td>
        <td>
          <select class="table-select shift-select" style="width: 100%;" data-idx="${idx}">
            ${selectOptionsHtml}
          </select>
        </td>
        <td>
          <div class="shift-time-pair">
            <input type="text" inputmode="numeric" maxlength="5" placeholder="--:--" autocomplete="off" class="input-text shift-time-input shift-time-start" value="${escapeHtmlText(s.start_time || "")}" data-idx="${idx}" data-field="start_time" ${s.status !== "work" ? "disabled" : ""}>
            <span class="shift-time-sep">〜</span>
            <input type="text" inputmode="numeric" maxlength="5" placeholder="--:--" autocomplete="off" class="input-text shift-time-input shift-time-end" value="${escapeHtmlText(s.end_time || "")}" data-idx="${idx}" data-field="end_time" ${s.status !== "work" ? "disabled" : ""}>
          </div>
        </td>
        <td>
          <select class="table-select shift-hourly-leave" style="height: 26px; font-size: 11px; width: 100%;" data-idx="${idx}" ${!isWorkRow ? "disabled" : ""}>
            ${hourlyOptionsHtml}
          </select>
        </td>
        <td class="col-summary">
          <input type="text" class="input-text shift-summary" style="height: 26px; width: 100%;" value="${escapeHtmlText(s.summary || "")}" data-idx="${idx}" data-field="summary">
        </td>
        <td>
          <input type="text" class="input-text shift-event" style="height: 26px; width: 100%;" value="${escapeHtmlText(s.event || "")}" data-idx="${idx}" data-field="event" placeholder="なし">
        </td>
        <td>
          <input type="text" class="input-text shift-memo" style="height: 26px; width: 100%;" value="${escapeHtmlText(s.memo || "")}" data-idx="${idx}" data-field="memo" placeholder="メモ">
        </td>
      `;
      return tr;
    }

    const MAX_SHIFT_UNDO_STACK = 30;
    let shiftUndoStack = [];

    function cloneShiftsSnapshot(shifts) {
      return (Array.isArray(shifts) ? shifts : []).map(item => Object.assign({}, item));
    }

    function updateShiftUndoButton() {
      const btnUndo = document.getElementById("btn-undo-shifts");
      if (btnUndo) {
        btnUndo.disabled = shiftUndoStack.length === 0;
      }
    }

    function pushShiftUndoSnapshot() {
      if (!Array.isArray(analyzedShifts) || analyzedShifts.length === 0) return;
      shiftUndoStack.push(cloneShiftsSnapshot(analyzedShifts));
      if (shiftUndoStack.length > MAX_SHIFT_UNDO_STACK) {
        shiftUndoStack.shift();
      }
      updateShiftUndoButton();
    }

    function undoShiftEdit() {
      if (shiftUndoStack.length === 0) return false;
      const prev = shiftUndoStack.pop();
      AppState.analysis.shifts = prev;
      updateShiftUndoButton();
      updateQualitySummaryUI(AppState.analysis.shifts);

      const tbody = document.getElementById("shifts-tbody");
      if (tbody) {
        tbody.innerHTML = "";
        AppState.analysis.shifts.forEach((s, idx) => {
          tbody.appendChild(createShiftTableRow(s, idx));
        });
        bindShiftTableEvents(tbody);
      }
      updateMonthlyMetrics();
      renderCalendar(AppState.analysis.shifts);
      applyHighlightFilter();
      updateFooterCount();
      showToast("直前の変更を元に戻しました");
      return true;
    }

    function applyShiftTypeSelection(idx, chosenKey, tr) {
      const inputStart = tr.querySelector(".shift-time-start");
      const inputEnd = tr.querySelector(".shift-time-end");
      const inputSummary = tr.querySelector(".shift-summary");
      const selectHourly = tr.querySelector(".shift-hourly-leave");
      const matchedOpt = shiftOptions.find(o => o.key === chosenKey);

      if (chosenKey === "休") {
        analyzedShifts[idx].type = "休";
        analyzedShifts[idx].status = "holiday";
        analyzedShifts[idx].is_holiday = true;
        analyzedShifts[idx].is_paid_leave = false;
        analyzedShifts[idx].hourly_paid_leave = 0;
        analyzedShifts[idx].start_time = null;
        analyzedShifts[idx].end_time = null;
        analyzedShifts[idx].summary = "休み";

        inputStart.value = "";
        inputEnd.value = "";
        inputStart.disabled = true;
        inputEnd.disabled = true;
        if (selectHourly) { selectHourly.value = "0"; selectHourly.disabled = true; }
        inputSummary.value = "休み";
      } else if (chosenKey === "㊒") {
        analyzedShifts[idx].type = "有給";
        analyzedShifts[idx].status = "paid_leave";
        analyzedShifts[idx].is_holiday = false;
        analyzedShifts[idx].is_paid_leave = true;
        analyzedShifts[idx].hourly_paid_leave = 0;
        analyzedShifts[idx].start_time = null;
        analyzedShifts[idx].end_time = null;
        analyzedShifts[idx].summary = "有給休暇";

        inputStart.value = "";
        inputEnd.value = "";
        inputStart.disabled = true;
        inputEnd.disabled = true;
        if (selectHourly) { selectHourly.value = "0"; selectHourly.disabled = true; }
        inputSummary.value = "有給休暇";
      } else if (matchedOpt && matchedOpt.status === "work") {
        analyzedShifts[idx].type = chosenKey;
        analyzedShifts[idx].status = "work";
        analyzedShifts[idx].is_holiday = false;
        analyzedShifts[idx].is_paid_leave = false;
        const curH = clampHalfHour(analyzedShifts[idx].hourly_paid_leave, 0, 0, paidLeaveConfig.hoursPerDay - 0.5);

        if (chosenKey !== "その他") {
          analyzedShifts[idx].start_time = matchedOpt.start;
          analyzedShifts[idx].end_time = matchedOpt.end;
          analyzedShifts[idx].summary = applyHourlyLeaveToSummary(`[${chosenKey}] (${matchedOpt.start}〜${matchedOpt.end})`, curH, "work");
          inputStart.value = matchedOpt.start;
          inputEnd.value = matchedOpt.end;
          inputSummary.value = analyzedShifts[idx].summary;
        } else {
          analyzedShifts[idx].summary = applyHourlyLeaveToSummary(`[勤務]`, curH, "work");
          inputSummary.value = analyzedShifts[idx].summary;
        }

        inputStart.disabled = false;
        inputEnd.disabled = false;
        if (selectHourly) selectHourly.disabled = false;
      }

      tr.dataset.key = chosenKey === "㊒" ? "有給" : chosenKey;
      analyzedShifts[idx]._user_verified = true;
      analyzedShifts[idx].confidence = "high";
      updateQualitySummaryUI(analyzedShifts);
      tr.classList.remove("is-quality-warning", "is-quality-error");
      if (analyzedShifts[idx].quality_level === "error") tr.classList.add("is-quality-error");
      else if (analyzedShifts[idx].quality_level === "warning") tr.classList.add("is-quality-warning");
      updateMonthlyMetrics();
      renderCalendar(analyzedShifts);
      applyHighlightFilter();
    }

    function bindShiftTableEvents(tbody) {
      tbody.querySelectorAll(".shift-check").forEach(cb => cb.addEventListener("change", updateFooterCount));

      tbody.querySelectorAll(".shift-select").forEach(sel => {
        sel.addEventListener("change", (e) => {
          const idx = parseInt(e.target.dataset.idx, 10);
          const tr = e.target.closest("tr");
          pushShiftUndoSnapshot();
          applyShiftTypeSelection(idx, e.target.value, tr);
        });
      });

      tbody.querySelectorAll(".shift-hourly-leave").forEach(sel => {
        sel.addEventListener("change", (e) => {
          const idx = parseInt(e.target.dataset.idx, 10);
          if (Number.isNaN(idx) || !analyzedShifts[idx]) return;
          pushShiftUndoSnapshot();
          const hVal = clampHalfHour(e.target.value, 0, 0, paidLeaveConfig.hoursPerDay - 0.5);
          analyzedShifts[idx].hourly_paid_leave = hVal;
          const tr = e.target.closest("tr");
          const inputSummary = tr ? tr.querySelector(".shift-summary") : null;
          const baseSum = inputSummary ? inputSummary.value : (analyzedShifts[idx].summary || analyzedShifts[idx].type || "出勤");
          const updatedSum = applyHourlyLeaveToSummary(baseSum, hVal, analyzedShifts[idx].status || "work");
          analyzedShifts[idx].summary = updatedSum;
          if (inputSummary) inputSummary.value = updatedSum;
          updateMonthlyMetrics();
          renderCalendar(analyzedShifts);
          applyHighlightFilter();
        });
      });

      tbody.querySelectorAll("input[data-field]").forEach(input => {
        const field = input.dataset ? input.dataset.field : "";
        const isTimeField = (field === "start_time" || field === "end_time");

        if (isTimeField) {
          input.addEventListener("focus", () => {
            if (!input.disabled) openTimeDialPopover(input);
          });
          input.addEventListener("click", (e) => {
            if (e && typeof e.stopPropagation === "function") e.stopPropagation();
            if (!input.disabled) openTimeDialPopover(input);
          });
          input.addEventListener("input", () => {
            const norm = normalizeTimeInputValue(input.value, false);
            if (norm) syncTimeDialWheelHighlight(norm);
          });
          input.addEventListener("keydown", (e) => {
            if (!e) return;
            if (e.key === "Enter") {
              if (typeof e.preventDefault === "function") e.preventDefault();
              commitTimeFieldInput(input);
              closeTimeDialPopover();
              if (typeof input.blur === "function") input.blur();
            } else if (e.key === "Escape") {
              closeTimeDialPopover();
            } else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
              if (typeof e.preventDefault === "function") e.preventDefault();
              const base = normalizeTimeInputValue(input.value, true) || "08:30";
              const mins = parseTimeToMinutes(base);
              if (mins !== null) {
                const delta = e.key === "ArrowUp" ? 5 : -5;
                const nextMins = (mins + delta + 1440) % 1440;
                const hh = String(Math.floor(nextMins / 60)).padStart(2, "0");
                const mm = String(nextMins % 60).padStart(2, "0");
                input.value = `${hh}:${mm}`;
                commitTimeFieldInput(input);
                syncTimeDialWheelHighlight(input.value, true);
              }
            }
          });
        }

        input.addEventListener("change", (e) => {
          const idx = parseInt(e.target.dataset.idx, 10);
          const f = e.target.dataset.field;
          if (idx === undefined || Number.isNaN(idx) || !f || !analyzedShifts[idx]) return;
          if (f === "start_time" || f === "end_time") {
            commitTimeFieldInput(e.target);
            return;
          }
          pushShiftUndoSnapshot();
          analyzedShifts[idx][f] = e.target.value;
          updateMonthlyMetrics();
          renderCalendar(analyzedShifts);
          updateFooterCount();
        });
      });
    }

    // --- iPhoneアラーム風 3Dドラムロール タイムピッカー ---
    let activeTimeDialInput = null;
    let timeDialHour = 8;
    let timeDialMinute = 30;
    let timeDialInitialized = false;
    let hourDrumCtrl = null;
    let minuteDrumCtrl = null;

    function normalizeTimeInputValue(raw, allowEmpty = true) {
      const s = String(raw || "").trim().normalize("NFKC");
      if (!s) return allowEmpty ? "" : null;
      const digitsOnly = s.replace(/[^\d]/g, "");
      let hh = null;
      let mm = null;
      if (s.includes(":")) {
        const m = s.match(/^(\d{1,2}):(\d{1,2})$/);
        if (!m) return null;
        hh = parseInt(m[1], 10);
        mm = parseInt(m[2], 10);
      } else if (digitsOnly.length === 4) {
        hh = parseInt(digitsOnly.slice(0, 2), 10);
        mm = parseInt(digitsOnly.slice(2, 4), 10);
      } else if (digitsOnly.length === 3) {
        hh = parseInt(digitsOnly.slice(0, 1), 10);
        mm = parseInt(digitsOnly.slice(1, 3), 10);
      } else {
        return null;
      }
      if (Number.isNaN(hh) || Number.isNaN(mm) || hh < 0 || hh > 23 || mm < 0 || mm > 59) return null;
      return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
    }

    function commitTimeFieldInput(inputEl) {
      if (!inputEl || !inputEl.dataset) return;
      const idx = parseInt(inputEl.dataset.idx, 10);
      const field = inputEl.dataset.field;
      if (Number.isNaN(idx) || !field || !analyzedShifts[idx]) return;
      const prevVal = String(analyzedShifts[idx][field] || "");
      const norm = normalizeTimeInputValue(inputEl.value, true);
      if (norm === null) {
        inputEl.value = prevVal;
        return;
      }
      inputEl.value = norm;
      if (norm === prevVal) return;
      pushShiftUndoSnapshot();
      analyzedShifts[idx][field] = norm;
      updateMonthlyMetrics();
      renderCalendar(analyzedShifts);
      updateFooterCount();
    }

    function createIosDrumWheel(containerEl, count, onSelectValue) {
      const STEP_PX = 34;
      const RADIUS = 88;
      const ANGLE_STEP = 23;
      const VISIBLE_RANGE = 3.6;

      let pos = 0;
      let isDragging = false;
      let dragStartY = 0;
      let dragStartPos = 0;
      let dragMoved = 0;
      let lastY = 0;
      let lastTs = 0;
      let velocity = 0; // items per ms
      let animRaf = null;
      let wheelSnapTimer = null;

      containerEl.innerHTML = "";
      const itemEls = [];
      for (let i = 0; i < count; i++) {
        const div = document.createElement("div");
        div.className = "time-dial-drum-item";
        div.dataset.val = String(i);
        div.textContent = String(i).padStart(2, "0");
        div.addEventListener("click", (e) => {
          if (e && typeof e.stopPropagation === "function") e.stopPropagation();
          if (dragMoved > 5) return;
          const curIdx = ((Math.round(pos) % count) + count) % count;
          let delta = i - curIdx;
          if (delta > count / 2) delta -= count;
          if (delta < -count / 2) delta += count;
          animateTo(Math.round(pos) + delta);
        });
        containerEl.appendChild(div);
        itemEls.push(div);
      }

      const normMod = (v) => ((v % count) + count) % count;

      function render() {
        const rounded = Math.round(pos);
        const selectedVal = normMod(rounded);
        for (let i = 0; i < count; i++) {
          let offset = i - normMod(pos);
          if (offset > count / 2) offset -= count;
          if (offset < -count / 2) offset += count;

          const el = itemEls[i];
          if (Math.abs(offset) > VISIBLE_RANGE) {
            el.style.display = "none";
            continue;
          }
          el.style.display = "block";
          const angle = offset * -ANGLE_STEP;
          const rad = (offset * ANGLE_STEP * Math.PI) / 180;
          const y = Math.sin(rad) * RADIUS;
          const scale = Math.max(0.75, 1 - Math.abs(offset) * 0.065);
          const opacity = Math.max(0, 1 - Math.abs(offset) * 0.25);
          el.style.transform = `translate3d(0, ${y.toFixed(2)}px, 0) rotateX(${angle.toFixed(1)}deg) scale(${scale.toFixed(3)})`;
          el.style.opacity = opacity.toFixed(3);
          el.classList.toggle("is-selected", i === selectedVal);
        }
      }

      function stopAnim() {
        if (animRaf !== null && typeof cancelAnimationFrame === "function") {
          cancelAnimationFrame(animRaf);
        }
        animRaf = null;
      }

      function animateTo(targetPos) {
        stopAnim();
        const startPos = pos;
        const diff = targetPos - startPos;
        if (Math.abs(diff) < 0.001 || typeof requestAnimationFrame !== "function") {
          pos = targetPos;
          render();
          onSelectValue(normMod(Math.round(pos)));
          return;
        }
        const duration = Math.min(260, Math.max(120, Math.abs(diff) * 45));
        const startTime = Date.now();
        const step = () => {
          const t = Math.min(1, (Date.now() - startTime) / duration);
          const eased = 1 - Math.pow(1 - t, 3);
          pos = startPos + diff * eased;
          render();
          if (t < 1) {
            animRaf = requestAnimationFrame(step);
          } else {
            pos = targetPos;
            animRaf = null;
            render();
            onSelectValue(normMod(Math.round(pos)));
          }
        };
        animRaf = requestAnimationFrame(step);
      }

      function startInertia() {
        stopAnim();
        if (Math.abs(velocity) < 0.002 || typeof requestAnimationFrame !== "function") {
          animateTo(Math.round(pos));
          return;
        }
        // 慣性で進む予測位置を最寄り整数へ吸着
        const projected = Math.round(pos + velocity * 160);
        animateTo(projected);
      }

      const onDragStart = (clientY) => {
        stopAnim();
        if (wheelSnapTimer) clearTimeout(wheelSnapTimer);
        isDragging = true;
        dragStartY = clientY;
        dragStartPos = pos;
        dragMoved = 0;
        lastY = clientY;
        lastTs = Date.now();
        velocity = 0;
      };

      const onDragMove = (clientY) => {
        if (!isDragging) return;
        const dy = clientY - dragStartY;
        dragMoved = Math.max(dragMoved, Math.abs(dy));
        pos = dragStartPos - dy / STEP_PX;
        const now = Date.now();
        const dt = now - lastTs;
        if (dt > 0) {
          velocity = -(clientY - lastY) / STEP_PX / dt;
          lastY = clientY;
          lastTs = now;
        }
        render();
      };

      const onDragEnd = () => {
        if (!isDragging) return;
        isDragging = false;
        startInertia();
      };

      containerEl.addEventListener("mousedown", (e) => {
        if (!e) return;
        if (typeof e.preventDefault === "function") e.preventDefault();
        onDragStart(e.clientY);
      });
      window.addEventListener("mousemove", (e) => {
        if (isDragging && e) onDragMove(e.clientY);
      });
      window.addEventListener("mouseup", () => {
        if (isDragging) onDragEnd();
      });

      containerEl.addEventListener("touchstart", (e) => {
        if (e && e.touches && e.touches.length === 1) {
          onDragStart(e.touches[0].clientY);
        }
      }, { passive: true });
      containerEl.addEventListener("touchmove", (e) => {
        if (isDragging && e && e.touches && e.touches.length === 1) {
          if (typeof e.preventDefault === "function") e.preventDefault();
          onDragMove(e.touches[0].clientY);
        }
      }, { passive: false });
      containerEl.addEventListener("touchend", () => {
        if (isDragging) onDragEnd();
      }, { passive: true });

      containerEl.addEventListener("wheel", (e) => {
        if (!e) return;
        if (typeof e.preventDefault === "function") e.preventDefault();
        stopAnim();
        pos += (e.deltaY || 0) / 36;
        render();
        if (wheelSnapTimer) clearTimeout(wheelSnapTimer);
        wheelSnapTimer = setTimeout(() => {
          animateTo(Math.round(pos));
        }, 90);
      }, { passive: false });

      render();
      return {
        setValue(val, animate = false) {
          const target = normMod(val);
          const curIdx = normMod(Math.round(pos));
          let delta = target - curIdx;
          if (delta > count / 2) delta -= count;
          if (delta < -count / 2) delta += count;
          const nextPos = Math.round(pos) + delta;
          if (animate) {
            animateTo(nextPos);
          } else {
            stopAnim();
            pos = nextPos;
            render();
          }
        }
      };
    }

    function syncTimeDialWheelHighlight(hhmm, animate = false) {
      const norm = normalizeTimeInputValue(hhmm, false);
      if (!norm) return;
      const parts = norm.split(":");
      timeDialHour = parseInt(parts[0], 10);
      timeDialMinute = parseInt(parts[1], 10);
      if (hourDrumCtrl) hourDrumCtrl.setValue(timeDialHour, animate);
      if (minuteDrumCtrl) minuteDrumCtrl.setValue(timeDialMinute, animate);
    }

    function applyTimeDialToActiveInput() {
      if (!activeTimeDialInput || activeTimeDialInput.disabled) return;
      const formatted = `${String(timeDialHour).padStart(2, "0")}:${String(timeDialMinute).padStart(2, "0")}`;
      activeTimeDialInput.value = formatted;
      commitTimeFieldInput(activeTimeDialInput);
    }

    function initTimeDialWheels() {
      if (timeDialInitialized) return;
      const hEl = document.getElementById("time-dial-hours");
      const mEl = document.getElementById("time-dial-minutes");
      const popover = document.getElementById("time-dial-popover");
      const btnDone = document.getElementById("btn-time-dial-done");
      if (!hEl || !mEl || !popover) return;
      timeDialInitialized = true;

      hourDrumCtrl = createIosDrumWheel(hEl, 24, (h) => {
        timeDialHour = h;
        applyTimeDialToActiveInput();
      });
      minuteDrumCtrl = createIosDrumWheel(mEl, 60, (m) => {
        timeDialMinute = m;
        applyTimeDialToActiveInput();
      });

      popover.addEventListener("mousedown", (e) => {
        if (e && typeof e.preventDefault === "function") e.preventDefault();
      });
      if (btnDone) {
        btnDone.addEventListener("click", (e) => {
          if (e && typeof e.stopPropagation === "function") e.stopPropagation();
          if (activeTimeDialInput) commitTimeFieldInput(activeTimeDialInput);
          closeTimeDialPopover();
        });
      }
    }

    function openTimeDialPopover(inputEl) {
      const popover = document.getElementById("time-dial-popover");
      if (!popover || !inputEl || inputEl.disabled) return;
      initTimeDialWheels();
      activeTimeDialInput = inputEl;

      const cur = normalizeTimeInputValue(inputEl.value, false) || "08:30";
      popover.style.display = "block";

      if (typeof inputEl.getBoundingClientRect === "function") {
        const rect = inputEl.getBoundingClientRect();
        const popW = 214;
        const popH = 228;
        const winW = window.innerWidth || 1280;
        const winH = window.innerHeight || 800;
        let left = rect.left + (rect.width - popW) / 2;
        left = Math.max(12, Math.min(winW - popW - 12, left));
        let top = rect.bottom + 6;
        if (top + popH > winH - 12) {
          top = Math.max(12, rect.top - popH - 6);
        }
        popover.style.left = `${Math.round(left)}px`;
        popover.style.top = `${Math.round(top)}px`;
      }

      syncTimeDialWheelHighlight(cur, false);
    }

    function closeTimeDialPopover() {
      const popover = document.getElementById("time-dial-popover");
      if (popover) popover.style.display = "none";
      activeTimeDialInput = null;
    }

    function renderResult(data) {
      AppState.analysis.shifts = data.shifts || [];
      AppState.ui.selectedCalendarIdx = null;
      shiftUndoStack = [];
      updateShiftUndoButton();
      if (viewerHighlightBox) viewerHighlightBox.style.display = "none";
      document.getElementById("res-target-name").textContent = data.target_name || "皿田";

      updateQualitySummaryUI(AppState.analysis.shifts);
      updateMonthlyMetrics();
      renderCalendar(AppState.analysis.shifts);

      const tbody = document.getElementById("shifts-tbody");
      tbody.innerHTML = "";
      AppState.analysis.shifts.forEach((s, idx) => {
        tbody.appendChild(createShiftTableRow(s, idx));
      });
      bindShiftTableEvents(tbody);

      updateFooterCount();
      applyHighlightFilter();
      document.getElementById("result-container").style.display = "flex";
      openViewer(true);
      document.getElementById("result-container").scrollIntoView({ behavior: "smooth" });
    }

    function scrollTableRowIntoView(tr) {
      if (!tr) return;
      const frame = tr.closest(".table-frame");
      if (!frame) return;
      const thead = frame.querySelector("thead");
      const headerHeight = thead ? thead.offsetHeight : 0;
      const frameRect = frame.getBoundingClientRect();
      const rowRect = tr.getBoundingClientRect();
      const visibleTop = frameRect.top + headerHeight;
      const visibleBottom = frameRect.bottom;

      if (rowRect.top < visibleTop) {
        frame.scrollTo({
          top: frame.scrollTop - (visibleTop - rowRect.top) - 4,
          behavior: "smooth"
        });
      } else if (rowRect.bottom > visibleBottom) {
        frame.scrollTo({
          top: frame.scrollTop + (rowRect.bottom - visibleBottom) + 4,
          behavior: "smooth"
        });
      }
    }

    function selectCalendarDate(idx, options = {}) {
      if (!analyzedShifts || !analyzedShifts[idx]) return;
      const { scrollTable = true, debounceImage = false } = options;
      const isSameIdx = selectedCalendarIdx === idx;
      selectedCalendarIdx = idx;
      const s = analyzedShifts[idx];

      // 凡例による同種シフト一括ハイライトが有効なら解除
      if (activeHighlightKey) {
        activeHighlightKey = null;
        document.querySelectorAll(".legend-capsule").forEach(el => el.classList.remove("is-active"));
        applyHighlightFilter();
      }

      // カレンダーの選択リングを更新
      document.querySelectorAll(".cal-cell").forEach(c => {
        c.classList.toggle("is-selected", c.dataset.idx == idx);
      });

      // シフト調整テーブルの選択リングを更新
      let selectedRow = null;
      document.querySelectorAll("#shifts-tbody tr").forEach(tr => {
        const matched = tr.dataset.idx == idx;
        tr.classList.toggle("is-selected", matched);
        if (matched) selectedRow = tr;
      });

      if (scrollTable && selectedRow) {
        scrollTableRowIntoView(selectedRow);
      }

      // 同一日付の再選択（ホバー等）で不要な画像アニメーションを再発火させない
      if (isSameIdx && debounceImage) return;

      // 元画像の該当セルをハイライト＆中央へパン移動
      if (imageFocusTimer) {
        clearTimeout(imageFocusTimer);
        imageFocusTimer = null;
      }

      const runImageFocus = () => {
        if (s.box_2d && Array.isArray(s.box_2d) && s.box_2d.length === 4) {
          focusImageRegion(s.box_2d);
        } else {
          if (viewerHighlightBox) viewerHighlightBox.style.display = "none";
          openViewer(false);
        }
      };

      if (debounceImage) {
        imageFocusTimer = setTimeout(runImageFocus, 80);
      } else {
        runImageFocus();
      }
    }

    function renderCalendar(shifts) {
      const grid = document.getElementById("calendar-body");
      grid.innerHTML = "";
      if (!shifts.length) return;

      const firstDateObj = new Date(shifts[0].date);
      const startDayOfWeek = firstDateObj.getDay();

      for (let i = 0; i < startDayOfWeek; i++) {
        const emptyCell = document.createElement("div");
        emptyCell.className = "cal-cell empty";
        grid.appendChild(emptyCell);
      }

      shifts.forEach((s, idx) => {
        const dt = new Date(s.date);
        const dayNum = dt.getDate();
        const dow = dt.getDay();

        const cell = document.createElement("div");
        const qClass = s.quality_level === "error" ? "is-quality-error" : (s.quality_level === "warning" ? "is-quality-warning" : "");
        cell.className = `cal-cell ${dow === 0 ? "sun" : (dow === 6 ? "sat" : "")} ${selectedCalendarIdx === idx ? "is-selected" : ""} ${qClass}`.trim();
        cell.dataset.idx = idx;
        cell.title = "クリックで元画像・調整テーブルの対応箇所を表示";
        cell.style.cursor = "pointer";
        cell.addEventListener("click", () => {
          selectCalendarDate(idx);
        });

        let statusClass = "work";
        let titleLabel = s.type || "出勤";
        let timeLabel = s.start_time && s.end_time ? `${s.start_time}〜${s.end_time}` : "";
        let itemKey = s.type || "その他";

        if (s.status === "holiday") {
          statusClass = "holiday";
          titleLabel = "休み";
          timeLabel = "終日";
          itemKey = "休";
        } else if (s.status === "paid_leave") {
          statusClass = "paid";
          titleLabel = "有給休暇";
          timeLabel = "終日";
          itemKey = "有給";
        }

        const hLeaveVal = (s.status === "work") ? clampHalfHour(s.hourly_paid_leave, 0, 0, paidLeaveConfig.hoursPerDay - 0.5) : 0;
        const hourlyBadgeHtml = hLeaveVal > 0
          ? `<div class="cal-hourly-leave-pill" title="時間有給: ${formatHoursNum(hLeaveVal)}時間">時間有給 ${formatHoursNum(hLeaveVal)}h</div>`
          : "";
        const eventText = s.event ? String(s.event).trim() : "";
        const eventBadgeHtml = eventText
          ? `<div class="cal-day-event-pill" title="行事予定: ${escapeHtmlText(eventText)}">${escapeHtmlText(eventText)}</div>`
          : "";

        cell.innerHTML = `
          <div class="cal-cell-header">
            <span style="display: inline-flex; align-items: center; gap: 3px;">
              <span>${dayNum}</span>
              ${renderQualityIconSvg(s.quality_level, s.quality_reasons)}
            </span>
            <span style="font-size: 9px; color: var(--label-tertiary);">${dt.getMonth() + 1}月</span>
          </div>
          <div class="cal-event-capsule ${statusClass}" data-key="${escapeHtmlText(itemKey)}">
            <div class="cal-capsule-title">${escapeHtmlText(titleLabel)}</div>
            <div class="cal-capsule-time">${escapeHtmlText(timeLabel)}</div>
          </div>
          ${hourlyBadgeHtml}
          ${eventBadgeHtml}
        `;
        grid.appendChild(cell);
      });

      const totalCells = startDayOfWeek + shifts.length;
      const remainder = totalCells % 7;
      if (remainder !== 0) {
        for (let i = 0; i < 7 - remainder; i++) {
          const emptyCell = document.createElement("div");
          emptyCell.className = "cal-cell empty";
          grid.appendChild(emptyCell);
        }
      }

      applyHighlightFilter();
    }

    // Check all
    document.getElementById("check-all").addEventListener("change", (e) => {
      const checked = e.target.checked;
      document.querySelectorAll(".shift-check").forEach(cb => cb.checked = checked);
      updateFooterCount();
    });

    function getSelectedShifts() {
      const selected = [];
      document.querySelectorAll(".shift-check").forEach(cb => {
        if (cb.checked) {
          const idx = parseInt(cb.dataset.idx, 10);
          selected.push(analyzedShifts[idx]);
        }
      });
      return selected;
    }

    function buildRegisterConfirmMessage(selected, calName, includeEvents) {
      const dates = (selected || [])
        .map(s => String((s && s.date) || "").trim())
        .filter(Boolean)
        .sort();
      const rangeText = dates.length
        ? (dates[0] === dates[dates.length - 1] ? dates[0] : `${dates[0]} 〜 ${dates[dates.length - 1]}`)
        : "-";
      const eventCount = includeEvents
        ? (selected || []).filter(s => String((s && s.event) || "").trim()).length
        : 0;
      const lines = [
        `Appleカレンダー「${calName}」へ登録します。`,
        `・対象期間: ${rangeText}`,
        `・シフト件数: ${(selected || []).length}件` + (eventCount > 0 ? `（＋行事予定 ${eventCount}件）` : ""),
        "※ 対象カレンダー内の同日の既存予定は上書き削除されます。"
      ];
      if (calName !== "シフトカレンダー") {
        lines.push(`【注意】標準カレンダー名「シフトカレンダー」以外（${calName}）が指定されています。同日の他予定が消えないかご確認ください。`);
      }
      lines.push("このまま登録してもよろしいですか？");
      return lines.join("\n");
    }

    // Apple Calendar Registration
    const btnRegister = document.getElementById("btn-register");
    btnRegister.addEventListener("click", async () => {
      const selected = getSelectedShifts();
      if (!selected.length) {
        showToast("登録対象のシフトを選択してください", "error");
        return;
      }

      const calName = document.getElementById("calendar-name").value.trim() || "シフトカレンダー";
      const includeEvents = isIncludeEventsEnabled();
      if (typeof confirm === "function") {
        const confirmMsg = buildRegisterConfirmMessage(selected, calName, includeEvents);
        if (!confirm(confirmMsg)) {
          return;
        }
      }

      btnRegister.disabled = true;
      btnRegister.textContent = "登録中...";

      try {
        const targetName = document.getElementById("target-name").value.trim() || "皿田";
        const allShifts = analyzedShifts.length ? analyzedShifts : selected;
        const historyPayload = {
          title: buildHistoryTitle(allShifts),
          target_name: targetName,
          shifts: allShifts,
          image_base64: currentImageBase64,
          mime_type: currentMimeType,
          image_name: currentImageName,
          dewarp_status: currentDewarpStatus
        };
        const { res, data: json } = await ApiClient.postJson("/api/register", {
          shifts: selected,
          calendar_name: calName,
          include_events: includeEvents,
          history_id: AppState.history.currentId,
          history_payload: historyPayload
        });

        if (!res.ok || json.error) throw new Error(json.error || "登録に失敗しました");

        if (json.history_id) {
          currentHistoryId = json.history_id;
          if (!historyActiveInfo || historyActiveInfo.style.display !== "flex") {
            latestHistoryId = json.history_id;
          } else if (currentHistoryMeta) {
            currentHistoryMeta.id = json.history_id;
            currentHistoryMeta.registered = true;
            if (json.registered_at) {
              currentHistoryMeta.registered_at = json.registered_at;
            }
            updateHistoryActiveBanner(currentHistoryMeta);
          }
        }
        await loadHistoryList();
        await fetchRegisteredCalendarShifts();

        showToast(`「${calName}」に${json.count}件登録しました（iCloud同期でiPhoneにも反映されます）`, "success");
      } catch (err) {
        if (err.message && err.message.includes("Failed to fetch")) {
          showToast("サーバーとの通信が切断されました。アプリを再起動してください", "error");
        } else {
          showToast(`登録エラー: ${err.message}`, "error");
        }
      } finally {
        btnRegister.disabled = false;
        btnRegister.textContent = "Appleカレンダーに登録";
      }
    });

    // ICS Download
    document.getElementById("btn-export-ics").addEventListener("click", async () => {
      const selected = getSelectedShifts();
      if (!selected.length) {
        showToast("対象のシフトを選択してください", "error");
        return;
      }

      try {
        const calName = document.getElementById("calendar-name").value.trim() || "シフトカレンダー";
        const { blob } = await ApiClient.postBlob("/api/export_ics", {
          shifts: selected,
          calendar_name: calName,
          include_events: isIncludeEventsEnabled()
        });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `shifts_${document.getElementById("res-year-month").textContent || "schedule"}.ics`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        if (/iPhone|iPad|iPod/.test(navigator.userAgent)) {
          showToast("icsを保存しました。ファイルを開くと直接カレンダーに追加できます", "success");
        } else {
          showToast("icsファイルを保存しました", "success");
        }
      } catch (err) {
        showToast(`エクスポートエラー: ${err.message}`, "error");
      }
    });

    // =========================================================================
    // 2-Tab Navigation & Monthly Registered Calendar View + Annual Paid Leave
    // =========================================================================
    function switchMainTab(tabName) {
      const target = tabName === "import" ? "import" : "calendar";
      activeMainTab = target;

      const btnCal = document.getElementById("tab-btn-calendar");
      const btnImp = document.getElementById("tab-btn-import");
      const panelCal = document.getElementById("tab-panel-calendar");
      const panelImp = document.getElementById("tab-panel-import");
      const footerEl = document.getElementById("window-footer");

      if (btnCal) {
        btnCal.classList.toggle("active", target === "calendar");
        btnCal.setAttribute("aria-selected", target === "calendar" ? "true" : "false");
      }
      if (btnImp) {
        btnImp.classList.toggle("active", target === "import");
        btnImp.setAttribute("aria-selected", target === "import" ? "true" : "false");
      }
      if (panelCal) panelCal.classList.toggle("is-hidden", target !== "calendar");
      if (panelImp) panelImp.classList.toggle("is-hidden", target !== "import");
      if (footerEl) footerEl.classList.toggle("is-hidden", target !== "import");

      if (target === "calendar") {
        setMonthPickerOpen(false);
        renderMonthlyCalendarView();
      }
    }

    function pad2(n) {
      return String(n).padStart(2, "0");
    }

    function formatDateYMD(year, month, day) {
      return `${year}-${pad2(month)}-${pad2(day)}`;
    }

    function getDaysInMonth(year, month) {
      return new Date(year, month, 0).getDate();
    }

    function computePaidLeaveFiscalPeriod(viewYear, viewMonth, startMonth, startDay) {
      const sm = clampInt(startMonth, 4, 1, 12);
      const sd = clampInt(startDay, 1, 1, 31);
      const refLastDay = getDaysInMonth(viewYear, viewMonth);
      const refDate = new Date(viewYear, viewMonth - 1, refLastDay);

      const thisYearStartDay = Math.min(sd, getDaysInMonth(viewYear, sm));
      const thisYearStart = new Date(viewYear, sm - 1, thisYearStartDay);

      const startYear = refDate >= thisYearStart ? viewYear : viewYear - 1;
      const actualStartDay = Math.min(sd, getDaysInMonth(startYear, sm));
      const periodStart = new Date(startYear, sm - 1, actualStartDay);

      const nextYear = startYear + 1;
      const nextStartDay = Math.min(sd, getDaysInMonth(nextYear, sm));
      const nextPeriodStart = new Date(nextYear, sm - 1, nextStartDay);
      const periodEnd = new Date(nextPeriodStart.getTime() - 86400000);

      return {
        startStr: formatDateYMD(periodStart.getFullYear(), periodStart.getMonth() + 1, periodStart.getDate()),
        endStr: formatDateYMD(periodEnd.getFullYear(), periodEnd.getMonth() + 1, periodEnd.getDate()),
        label: `${periodStart.getFullYear()}/${periodStart.getMonth() + 1}/${periodStart.getDate()} 〜 ${periodEnd.getFullYear()}/${periodEnd.getMonth() + 1}/${periodEnd.getDate()}`
      };
    }

    function getShiftItemKey(s) {
      if (!s) return "その他";
      if (s.status === "holiday" || s.is_holiday) return "休";
      if (s.status === "paid_leave" || s.is_paid_leave) return "有給";
      return s.type || "その他";
    }

    function renderCalendarViewDefs(defs) {
      renderLegendCapsules(
        "cal-view-defs-container",
        defs,
        AppState.calendar.highlightKey,
        toggleCalendarViewHighlight,
        "cal-view-legend"
      );
    }

    function toggleCalendarViewHighlight(key) {
      calendarHighlightKey = (calendarHighlightKey === key) ? null : key;
      const container = document.getElementById("cal-view-defs-container");
      if (container && container.children) {
        Array.from(container.children).forEach(el => {
          if (el && el.classList && el.dataset) {
            el.classList.toggle("is-active", el.dataset.key === calendarHighlightKey);
          }
        });
      }
      applyCalendarViewHighlightFilter();
    }

    function applyCalendarViewHighlightFilter() {
      const grid = document.getElementById("monthly-calendar-body");
      if (!grid || typeof grid.querySelectorAll !== "function") return;
      grid.querySelectorAll(".cal-event-capsule").forEach(el => {
        const key = el.dataset ? el.dataset.key : "";
        if (!calendarHighlightKey) {
          el.classList.remove("is-highlighted", "is-dimmed");
        } else if (key === calendarHighlightKey) {
          el.classList.add("is-highlighted");
          el.classList.remove("is-dimmed");
        } else {
          el.classList.remove("is-highlighted");
          el.classList.add("is-dimmed");
        }
      });
    }

    function setMonthPickerOpen(open) {
      const popover = document.getElementById("cal-month-picker-popover");
      const trigger = document.getElementById("btn-cal-month-picker");
      if (popover) popover.classList.toggle("is-open", open);
      if (trigger) trigger.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) {
        calendarPickerYear = calendarViewYear;
        renderMonthPickerGrid();
      }
    }

    function renderMonthPickerGrid() {
      const yearLabel = document.getElementById("cal-picker-year-label");
      const grid = document.getElementById("cal-picker-month-grid");
      if (yearLabel) yearLabel.textContent = `${calendarPickerYear}年`;
      if (!grid) return;

      const availableSet = new Set(calendarAvailableMonths || []);
      grid.innerHTML = "";
      for (let m = 1; m <= 12; m++) {
        const ym = `${calendarPickerYear}-${pad2(m)}`;
        const btn = document.createElement("button");
        btn.type = "button";
        const isCurrent = (calendarPickerYear === calendarViewYear && m === calendarViewMonth);
        btn.className = `month-picker-item${isCurrent ? " is-current" : ""}`;
        btn.dataset.year = String(calendarPickerYear);
        btn.dataset.month = String(m);
        const dotHtml = availableSet.has(ym) ? '<span class="month-picker-dot" title="登録済みシフトあり"></span>' : "";
        btn.innerHTML = `<span>${m}月</span>${dotHtml}`;
        btn.addEventListener("click", () => {
          calendarViewYear = calendarPickerYear;
          calendarViewMonth = m;
          calendarSelectedDate = null;
          setMonthPickerOpen(false);
          renderMonthlyCalendarView();
        });
        grid.appendChild(btn);
      }
    }

    function shiftCalendarMonth(delta) {
      const dt = new Date(calendarViewYear, calendarViewMonth - 1 + delta, 1);
      calendarViewYear = dt.getFullYear();
      calendarViewMonth = dt.getMonth() + 1;
      calendarSelectedDate = null;
      setMonthPickerOpen(false);
      renderMonthlyCalendarView();
    }

    function buildCalendarShiftTypeOptionsHtml(selectedType) {
      const current = String(selectedType || "").trim();
      const keys = Object.keys(masterTimeDefs || {});
      const options = [];
      const seen = new Set();
      keys.forEach(k => {
        seen.add(k);
        const def = masterTimeDefs[k];
        const label = def && def.start && def.end ? `${k} (${def.start}〜${def.end})` : k;
        const sel = k === current ? " selected" : "";
        options.push(`<option value="${escapeHtmlText(k)}"${sel}>${escapeHtmlText(label)}</option>`);
      });
      if (current && !seen.has(current) && !["休", "休み", "有給", "有給休暇"].includes(current)) {
        options.push(`<option value="${escapeHtmlText(current)}" selected>${escapeHtmlText(current)}</option>`);
      }
      const isHolSel = (current === "休" || current === "休み") ? " selected" : "";
      const isPaidSel = (current === "有給" || current === "有給休暇") ? " selected" : "";
      options.push(`<option value="休"${isHolSel}>休（終日休み）</option>`);
      options.push(`<option value="有給"${isPaidSel}>有給（終日有給休暇）</option>`);
      return options.join("");
    }

    function renderSelectedDateDetail(dateStr) {
      const detailCard = document.getElementById("monthly-calendar-detail");
      const detailDateEl = document.getElementById("cal-detail-date");
      const detailBodyEl = document.getElementById("cal-detail-body");
      const detailMetaEl = document.getElementById("cal-detail-meta");
      const detailShiftEditBox = document.getElementById("cal-detail-shift-edit-box");
      const detailShiftEditLabel = document.getElementById("cal-detail-shift-edit-label");
      const detailShiftTypeEl = document.getElementById("cal-detail-shift-type");
      const detailEventInputEl = document.getElementById("cal-detail-event-input");
      const detailMemoInputEl = document.getElementById("cal-detail-memo-input");
      const btnSaveShift = document.getElementById("btn-cal-save-shift");
      const detailHourlyBox = document.getElementById("cal-detail-hourly-box");
      const detailHourlySelect = document.getElementById("cal-detail-hourly-select");
      const btnSaveHourly = document.getElementById("btn-cal-save-hourly-leave");
      const btnOpenHist = document.getElementById("btn-cal-open-history");
      if (!detailCard) return;

      if (!dateStr) {
        detailCard.classList.remove("is-visible");
        if (detailShiftEditBox) detailShiftEditBox.classList.remove("is-visible");
        if (detailHourlyBox) detailHourlyBox.classList.remove("is-visible");
        return;
      }

      const shift = calendarShiftsByDate[dateStr] || null;
      const parts = dateStr.split("-");
      const dt = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
      const dowLabels = ["日", "月", "火", "水", "木", "金", "土"];
      const dow = (shift && shift.day_of_week) || dowLabels[dt.getDay()];

      if (detailDateEl) {
        detailDateEl.textContent = `${parseInt(parts[0], 10)}年${parseInt(parts[1], 10)}月${parseInt(parts[2], 10)}日（${dow}）`;
      }

      if (!shift) {
        // 未登録日：手入力新規登録モード
        if (detailBodyEl) {
          detailBodyEl.innerHTML = `
            <span class="metric-capsule" style="color: var(--label-secondary);">未登録の日付（手入力でシフトを追加できます）</span>
          `;
        }
        const defaultKeys = Object.keys(masterTimeDefs || {});
        const defaultType = defaultKeys.includes("日") ? "日" : (defaultKeys[0] || "休");
        if (detailShiftEditBox) {
          if (detailShiftEditLabel) detailShiftEditLabel.textContent = "シフト追加:";
          if (detailShiftTypeEl) {
            detailShiftTypeEl.innerHTML = buildCalendarShiftTypeOptionsHtml(defaultType);
            detailShiftTypeEl.value = defaultType;
          }
          if (detailEventInputEl) detailEventInputEl.value = "";
          if (detailMemoInputEl) detailMemoInputEl.value = "";
          if (btnSaveShift) {
            btnSaveShift.dataset.historyId = "";
            btnSaveShift.dataset.date = dateStr;
            btnSaveShift.textContent = "シフトを追加";
          }
          detailShiftEditBox.classList.add("is-visible");
        }
        if (detailHourlyBox) {
          if (detailHourlySelect) {
            detailHourlySelect.innerHTML = buildHourlyLeaveOptionsHtml(0, paidLeaveConfig.hoursPerDay);
            detailHourlySelect.value = "0";
          }
          if (btnSaveHourly) {
            btnSaveHourly.dataset.historyId = "";
            btnSaveHourly.dataset.date = dateStr;
            btnSaveHourly.style.display = "none";
          }
          detailHourlyBox.classList.add("is-visible");
        }
        if (detailMetaEl) {
          detailMetaEl.textContent = "手入力で追加するとカレンダータブに保存され、必要に応じてAppleカレンダーへも同期されます。";
        }
        if (btnOpenHist) {
          btnOpenHist.dataset.historyId = "";
          btnOpenHist.dataset.date = dateStr;
          btnOpenHist.style.display = "none";
        }
        detailCard.classList.add("is-visible");
        return;
      }

      let statusClass = "work";
      let titleLabel = shift.type || "出勤";
      let timeLabel = shift.start_time && shift.end_time ? `${shift.start_time}〜${shift.end_time}` : "";
      const isHoliday = (shift.status === "holiday" || shift.is_holiday);
      const isPaidLeave = (shift.status === "paid_leave" || shift.is_paid_leave);
      if (isHoliday) {
        statusClass = "holiday";
        titleLabel = "休み";
        timeLabel = "終日";
      } else if (isPaidLeave) {
        statusClass = "paid";
        titleLabel = "有給休暇";
        timeLabel = "終日";
      }

      const isWorkDay = (!isHoliday && !isPaidLeave);
      const hLeaveVal = isWorkDay ? clampHalfHour(shift.hourly_paid_leave, 0, 0, paidLeaveConfig.hoursPerDay - 0.5) : 0;
      const hourlyPillHtml = hLeaveVal > 0
        ? `<span class="cal-hourly-leave-pill">時間有給 ${formatHoursNum(hLeaveVal)}h</span>`
        : "";
      const summaryText = shift.summary ? String(shift.summary).trim() : "";
      const summaryHtml = summaryText
        ? `<span class="metric-capsule" id="cal-detail-summary"><span style="color: var(--label-secondary);">カレンダー登録名:</span><strong>${escapeHtmlText(summaryText)}</strong></span>`
        : "";
      const eventHtml = shift.event
        ? `<span class="cal-day-event-pill">行事予定: ${escapeHtmlText(shift.event)}</span>`
        : "";
      const memoText = shift.memo ? String(shift.memo).trim() : "";
      const memoHtml = memoText
        ? `<span class="cal-memo-pill" id="cal-detail-memo-pill">メモ: ${escapeHtmlText(memoText)}</span>`
        : "";
      if (detailBodyEl) {
        detailBodyEl.innerHTML = `
          <span class="cal-event-capsule ${statusClass}" style="flex-direction: row; align-items: center; gap: 8px; padding: 4px 12px;">
            <strong>${escapeHtmlText(titleLabel)}</strong>
            <span class="cal-capsule-time">${escapeHtmlText(timeLabel)}</span>
          </span>
          ${hourlyPillHtml}
          ${summaryHtml}
          ${eventHtml}
          ${memoHtml}
        `;
      }
      if (detailShiftEditBox) {
        if (shift.history_id) {
          const currentShiftType = isHoliday ? "休" : (isPaidLeave ? "有給" : (shift.type || ""));
          if (detailShiftEditLabel) detailShiftEditLabel.textContent = "シフト修正:";
          if (detailShiftTypeEl) {
            detailShiftTypeEl.innerHTML = buildCalendarShiftTypeOptionsHtml(currentShiftType);
            detailShiftTypeEl.value = currentShiftType;
          }
          if (detailEventInputEl) {
            detailEventInputEl.value = shift.event ? String(shift.event) : "";
          }
          if (detailMemoInputEl) {
            detailMemoInputEl.value = memoText;
          }
          if (btnSaveShift) {
            btnSaveShift.dataset.historyId = shift.history_id;
            btnSaveShift.dataset.date = dateStr;
            btnSaveShift.textContent = "シフトを保存";
          }
          detailShiftEditBox.classList.add("is-visible");
        } else {
          detailShiftEditBox.classList.remove("is-visible");
        }
      }
      if (detailHourlyBox) {
        if (isWorkDay && shift.history_id) {
          if (detailHourlySelect) {
            detailHourlySelect.innerHTML = buildHourlyLeaveOptionsHtml(hLeaveVal, paidLeaveConfig.hoursPerDay);
            detailHourlySelect.value = String(hLeaveVal);
          }
          if (btnSaveHourly) {
            btnSaveHourly.dataset.historyId = shift.history_id;
            btnSaveHourly.dataset.date = dateStr;
            btnSaveHourly.style.display = "inline-flex";
          }
          detailHourlyBox.classList.add("is-visible");
        } else {
          detailHourlyBox.classList.remove("is-visible");
        }
      }
      if (detailMetaEl) {
        const regText = shift.registered_at ? `（${shift.registered_at} 登録）` : "";
        detailMetaEl.textContent = `登録元履歴: ${shift.history_title || "シフト"} ${regText}`;
      }
      if (btnOpenHist) {
        btnOpenHist.dataset.historyId = shift.history_id || "";
        btnOpenHist.dataset.date = dateStr;
        btnOpenHist.style.display = shift.history_id ? "inline-flex" : "none";
      }
      detailCard.classList.add("is-visible");
    }

    function parseTimeToMinutes(hhmm) {
      const m = String(hhmm || "").trim().match(/^(\d{1,2}):(\d{2})$/);
      if (!m) return null;
      const hh = parseInt(m[1], 10);
      const mm = parseInt(m[2], 10);
      if (hh < 0 || hh > 23 || mm < 0 || mm > 59) return null;
      return hh * 60 + mm;
    }

    function jumpToCalendarDate(dateStr) {
      if (!dateStr || !/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) return;
      const parts = dateStr.split("-");
      AppState.calendar.viewYear = parseInt(parts[0], 10);
      AppState.calendar.viewMonth = parseInt(parts[1], 10);
      AppState.calendar.selectedDate = dateStr;
      setMonthPickerOpen(false);
      renderMonthlyCalendarView();
    }

    function buildMonthlyShareText(year, month, mode = "all") {
      const ymPrefix = `${year}-${pad2(month)}`;
      const dowLabels = ["日", "月", "火", "水", "木", "金", "土"];
      const modeLabels = {
        all: "全日程",
        off: "休み・有給のみ",
        early_late: "早番・遅番のみ"
      };
      const dates = Object.keys(calendarShiftsByDate)
        .filter(d => d.startsWith(ymPrefix + "-"))
        .sort();

      const lines = [`${year}年${month}月のシフト（${modeLabels[mode] || "全日程"}）`];
      let matchedCount = 0;

      dates.forEach(dateStr => {
        const s = calendarShiftsByDate[dateStr];
        if (!s) return;
        const isHol = Boolean(s.status === "holiday" || s.is_holiday);
        const isPaid = Boolean(s.status === "paid_leave" || s.is_paid_leave);
        const typeStr = String(s.type || "").trim();

        if (mode === "off" && !(isHol || isPaid)) return;
        if (mode === "early_late") {
          const isEarlyOrLate = !isHol && !isPaid && (typeStr.startsWith("早") || typeStr.startsWith("遅"));
          if (!isEarlyOrLate) return;
        }

        const parts = dateStr.split("-");
        const dt = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
        const dow = s.day_of_week || dowLabels[dt.getDay()];
        const mdLabel = `${parseInt(parts[1], 10)}/${parseInt(parts[2], 10)}(${dow})`;

        let body = "";
        if (isHol) {
          body = "休み";
        } else if (isPaid) {
          body = "有給休暇";
        } else {
          const timeStr = s.start_time && s.end_time ? ` (${s.start_time}〜${s.end_time})` : "";
          const hLeave = clampHalfHour(s.hourly_paid_leave, 0, 0, paidLeaveConfig.hoursPerDay - 0.5);
          const hStr = hLeave > 0 ? ` [時間有給${formatHoursNum(hLeave)}h]` : "";
          body = `${typeStr || "出勤"}${timeStr}${hStr}`;
        }
        const extras = [];
        if (s.event) extras.push(`行事:${String(s.event).trim()}`);
        if (s.memo) extras.push(`メモ:${String(s.memo).trim()}`);
        const extraStr = extras.length ? ` / ${extras.join(" / ")}` : "";

        lines.push(`${mdLabel} ${body}${extraStr}`);
        matchedCount++;
      });

      if (matchedCount === 0) {
        return "";
      }
      return lines.join("\n");
    }

    async function copyTextToClipboard(text) {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        await navigator.clipboard.writeText(text);
        return true;
      }
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = typeof document.execCommand === "function" ? document.execCommand("copy") : false;
      document.body.removeChild(ta);
      return ok;
    }

    function renderMonthlyCalendarCanvas(year, month) {
      const ymPrefix = `${year}-${pad2(month)}`;
      const firstDayObj = new Date(year, month - 1, 1);
      const startDow = firstDayObj.getDay();
      const daysInCurMonth = getDaysInMonth(year, month);
      const rows = Math.ceil((startDow + daysInCurMonth) / 7);

      const scale = 2;
      const width = 1080;
      const headerH = 92;
      const dowH = 34;
      const cellH = 112;
      const pad = 24;
      const height = headerH + dowH + rows * cellH + pad;
      const colW = (width - pad * 2) / 7;

      const canvas = document.createElement("canvas");
      canvas.width = width * scale;
      canvas.height = height * scale;
      const ctx = canvas.getContext("2d");
      if (!ctx) return null;
      ctx.scale(scale, scale);

      // 共有用に常にライト背景（白ベース）で描画
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, width, height);

      // ヘッダータイトル
      ctx.fillStyle = "#1d1d1f";
      ctx.font = "700 26px -apple-system, BlinkMacSystemFont, 'Hiragino Sans', sans-serif";
      ctx.fillText(`${year}年 ${month}月 シフトカレンダー`, pad, 44);

      // 月間集計サマリー
      let mWork = 0, mHol = 0, mPaid = 0;
      Object.keys(calendarShiftsByDate).forEach(d => {
        if (!d.startsWith(ymPrefix + "-")) return;
        const s = calendarShiftsByDate[d];
        if (!s) return;
        if (s.status === "holiday" || s.is_holiday) mHol++;
        else if (s.status === "paid_leave" || s.is_paid_leave) mPaid++;
        else mWork++;
      });
      ctx.fillStyle = "#6e6e73";
      ctx.font = "500 14px -apple-system, BlinkMacSystemFont, 'Hiragino Sans', sans-serif";
      ctx.fillText(`出勤: ${mWork}日   休み: ${mHol}日   有給: ${mPaid}日`, pad, 72);

      // 曜日ヘッダー
      const dowNames = ["日", "月", "火", "水", "木", "金", "土"];
      const gridTop = headerH;
      ctx.fillStyle = "#f5f5f7";
      ctx.fillRect(pad, gridTop, width - pad * 2, dowH);
      ctx.strokeStyle = "#d2d2d7";
      ctx.lineWidth = 1;
      ctx.strokeRect(pad, gridTop, width - pad * 2, dowH + rows * cellH);

      dowNames.forEach((name, i) => {
        ctx.fillStyle = i === 0 ? "#d70015" : (i === 6 ? "#0071e3" : "#1d1d1f");
        ctx.font = "600 13px -apple-system, BlinkMacSystemFont, 'Hiragino Sans', sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(name, pad + i * colW + colW / 2, gridTop + 22);
      });
      ctx.textAlign = "left";

      // グリッド＆各日付セル
      for (let slot = 0; slot < rows * 7; slot++) {
        const r = Math.floor(slot / 7);
        const c = slot % 7;
        const x = pad + c * colW;
        const y = gridTop + dowH + r * cellH;
        const dayOffset = slot - startDow + 1;
        const cellDate = new Date(year, month - 1, dayOffset);
        const cy = cellDate.getFullYear();
        const cm = cellDate.getMonth() + 1;
        const cd = cellDate.getDate();
        const isOutside = (cy !== year || cm !== month);
        const dateStr = formatDateYMD(cy, cm, cd);
        const s = calendarShiftsByDate[dateStr];

        ctx.fillStyle = isOutside ? "#fafafa" : "#ffffff";
        ctx.fillRect(x, y, colW, cellH);
        ctx.strokeStyle = "#e5e5ea";
        ctx.strokeRect(x, y, colW, cellH);

        ctx.fillStyle = isOutside ? "#aeaeb2" : (c === 0 ? "#d70015" : (c === 6 ? "#0071e3" : "#1d1d1f"));
        ctx.font = "600 13px -apple-system, BlinkMacSystemFont, 'Hiragino Sans', sans-serif";
        ctx.fillText(String(cd), x + 8, y + 20);

        if (s && !isOutside) {
          const isHol = Boolean(s.status === "holiday" || s.is_holiday);
          const isPaid = Boolean(s.status === "paid_leave" || s.is_paid_leave);
          const bg = isHol ? "#e5e5ea" : (isPaid ? "#ffd6e7" : "#ffe8cc");
          const fg = isHol ? "#3a3a3c" : (isPaid ? "#9e1c52" : "#9a4b00");
          const label = isHol ? "休み" : (isPaid ? "有給休暇" : (s.type || "出勤"));
          const sub = isHol || isPaid ? "終日" : (s.start_time && s.end_time ? `${s.start_time}〜${s.end_time}` : "");

          ctx.fillStyle = bg;
          ctx.fillRect(x + 6, y + 28, colW - 12, 36);
          ctx.fillStyle = fg;
          ctx.font = "700 13px -apple-system, BlinkMacSystemFont, 'Hiragino Sans', sans-serif";
          ctx.fillText(label.slice(0, 10), x + 11, y + 44);
          if (sub) {
            ctx.font = "500 10px -apple-system, BlinkMacSystemFont, 'Hiragino Sans', sans-serif";
            ctx.fillText(sub.slice(0, 14), x + 11, y + 58);
          }

          let extraY = y + 78;
          if (s.event) {
            ctx.fillStyle = "#0071e3";
            ctx.font = "500 10px -apple-system, BlinkMacSystemFont, 'Hiragino Sans', sans-serif";
            ctx.fillText(String(s.event).trim().slice(0, 12), x + 8, extraY);
            extraY += 14;
          }
          if (s.memo) {
            ctx.fillStyle = "#6e6e73";
            ctx.font = "500 10px -apple-system, BlinkMacSystemFont, 'Hiragino Sans', sans-serif";
            ctx.fillText(String(s.memo).trim().slice(0, 12), x + 8, extraY);
          }
        }
      }

      return canvas;
    }

    function canvasToPngBlob(canvas) {
      return new Promise((resolve, reject) => {
        if (canvas && typeof canvas.toBlob === "function") {
          canvas.toBlob((blob) => {
            if (blob) resolve(blob);
            else reject(new Error("PNGデータの生成に失敗しました"));
          }, "image/png");
          return;
        }
        try {
          const dataUrl = canvas.toDataURL("image/png");
          const commaIdx = dataUrl.indexOf(",");
          const bstr = atob(commaIdx >= 0 ? dataUrl.slice(commaIdx + 1) : dataUrl);
          const u8 = new Uint8Array(bstr.length);
          for (let i = 0; i < bstr.length; i++) u8[i] = bstr.charCodeAt(i);
          resolve(new Blob([u8], { type: "image/png" }));
        } catch (e) {
          reject(e);
        }
      });
    }

    function openCalendarImagePreviewModal(dataUrl, title) {
      const modal = document.getElementById("cal-image-preview-modal");
      const img = document.getElementById("cal-image-preview-img");
      const titleEl = document.getElementById("cal-image-preview-title");
      if (!modal || !img) return false;
      img.src = dataUrl;
      if (titleEl && title) titleEl.textContent = title;
      modal.style.display = "flex";
      return true;
    }

    function closeCalendarImagePreviewModal() {
      const modal = document.getElementById("cal-image-preview-modal");
      if (modal) modal.style.display = "none";
    }

    async function copyMonthlyCalendarImage(year, month) {
      const canvas = renderMonthlyCalendarCanvas(year, month);
      if (!canvas) throw new Error("カレンダー画像の生成に失敗しました");
      const title = `${year}年${month}月 シフトカレンダー`;
      const canWriteImage = Boolean(
        typeof navigator !== "undefined" &&
        navigator.clipboard &&
        typeof navigator.clipboard.write === "function" &&
        typeof ClipboardItem === "function"
      );
      if (canWriteImage) {
        try {
          const blob = await canvasToPngBlob(canvas);
          await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
          return { mode: "clipboard" };
        } catch (err) {
          // 権限・HTTP制限等で直接コピーできない場合は保存せずプレビューへフォールバック
        }
      }
      const dataUrl = canvas.toDataURL("image/png");
      openCalendarImagePreviewModal(dataUrl, title);
      return { mode: "preview" };
    }

    async function shareMonthlyCalendarNative(year, month, mode = "all") {
      if (typeof navigator === "undefined" || typeof navigator.share !== "function") {
        throw new Error("このブラウザではOS共有メニューを利用できません");
      }
      const title = `${year}年${month}月 シフトカレンダー`;
      const canvas = renderMonthlyCalendarCanvas(year, month);
      if (canvas && typeof File === "function") {
        try {
          const blob = await canvasToPngBlob(canvas);
          const file = new File([blob], `shift_calendar_${year}_${pad2(month)}.png`, { type: "image/png" });
          if (typeof navigator.canShare === "function" && navigator.canShare({ files: [file] })) {
            await navigator.share({ title, files: [file] });
            return { mode: "file" };
          }
        } catch (err) {
          if (err && err.name === "AbortError") return { mode: "cancelled" };
        }
      }
      const text = buildMonthlyShareText(year, month, mode);
      if (!text) {
        throw new Error("共有対象のシフトがありません");
      }
      try {
        await navigator.share({ title, text });
        return { mode: "text" };
      } catch (err) {
        if (err && err.name === "AbortError") return { mode: "cancelled" };
        throw err;
      }
    }

    function exportMonthlyCalendarPng(year, month) {
      const canvas = renderMonthlyCalendarCanvas(year, month);
      if (!canvas) return false;
      const dataUrl = canvas.toDataURL("image/png");
      const a = document.createElement("a");
      a.href = dataUrl;
      a.download = `shift_calendar_${year}_${pad2(month)}.png`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      return true;
    }

    function renderCalendarSearchResults(query) {
      const container = document.getElementById("cal-search-results");
      const btnClear = document.getElementById("btn-cal-search-clear");
      const raw = String(query || "").trim();
      if (btnClear) btnClear.style.display = raw ? "inline-flex" : "none";
      if (!container) return;

      if (!raw) {
        container.classList.remove("is-open");
        container.innerHTML = "";
        return;
      }

      const qNorm = raw.normalize("NFKC").toLowerCase();
      const matches = Object.keys(calendarShiftsByDate)
        .sort()
        .reverse()
        .map(d => calendarShiftsByDate[d])
        .filter(s => {
          if (!s) return false;
          const hay = [s.date, s.type, s.summary, s.event, s.memo]
            .map(v => String(v || "").normalize("NFKC").toLowerCase())
            .join(" ");
          return hay.includes(qNorm);
        })
        .slice(0, 30);

      container.innerHTML = "";
      if (!matches.length) {
        container.innerHTML = `<div style="font-size: 12px; color: var(--label-secondary); padding: 4px 8px;">「${escapeHtmlText(raw)}」に一致する履歴はありません。</div>`;
        container.classList.add("is-open");
        return;
      }

      matches.forEach(s => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "cal-search-item";
        const typeText = s.status === "holiday" || s.is_holiday ? "休み" : (s.status === "paid_leave" || s.is_paid_leave ? "有給休暇" : (s.type || "出勤"));
        const detailParts = [typeText];
        if (s.event) detailParts.push(`行事: ${s.event}`);
        if (s.memo) detailParts.push(`メモ: ${s.memo}`);
        btn.innerHTML = `
          <span><strong>${escapeHtmlText(s.date)}</strong>（${escapeHtmlText(s.day_of_week || "")}）</span>
          <span style="color: var(--label-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtmlText(detailParts.join(" / "))}</span>
        `;
        btn.addEventListener("click", () => {
          jumpToCalendarDate(s.date);
        });
        container.appendChild(btn);
      });
      container.classList.add("is-open");
    }

    function updateMonthlyCalendarSummaries(ymPrefix, hpd) {
      const summaryTotalEl = document.getElementById("cal-summary-total-days");
      const summaryWorkEl = document.getElementById("cal-summary-work-days");
      const summaryHolEl = document.getElementById("cal-summary-holiday-days");
      const summaryPaidEl = document.getElementById("cal-summary-paid-days");

      const annualPeriodEl = document.getElementById("cal-annual-leave-period");
      const annualUsedEl = document.getElementById("cal-annual-leave-used");
      const annualRemEl = document.getElementById("cal-annual-leave-remaining");
      const annualTotalEl = document.getElementById("cal-annual-leave-total");
      const annualProgressEl = document.getElementById("cal-annual-leave-progress");

      const halfPerDay = Math.max(2, Math.round(hpd * 2));
      let mWork = 0;
      let mHoliday = 0;
      let mPaidHalfHours = 0;
      let mTotal = 0;
      let mWorkMinutes = 0;
      const typeCounts = {};

      Object.keys(calendarShiftsByDate).forEach(dateStr => {
        if (!dateStr.startsWith(ymPrefix + "-")) return;
        const s = calendarShiftsByDate[dateStr];
        if (!s) return;
        mTotal++;
        if (s.status === "holiday" || s.is_holiday) {
          mHoliday++;
          typeCounts["休"] = (typeCounts["休"] || 0) + 1;
        } else if (s.status === "paid_leave" || s.is_paid_leave) {
          mPaidHalfHours += halfPerDay;
          typeCounts["有給"] = (typeCounts["有給"] || 0) + 1;
        } else {
          mWork++;
          const tKey = String(s.type || "出勤").trim() || "出勤";
          typeCounts[tKey] = (typeCounts[tKey] || 0) + 1;
          const hLeave = clampHalfHour(s.hourly_paid_leave, 0, 0, hpd - 0.5);
          mPaidHalfHours += Math.round(hLeave * 2);
          const stMin = parseTimeToMinutes(s.start_time);
          const enMin = parseTimeToMinutes(s.end_time);
          if (stMin !== null && enMin !== null && enMin > stMin) {
            mWorkMinutes += Math.max(0, (enMin - stMin) - Math.round(hLeave * 60));
          }
        }
      });

      if (summaryTotalEl) summaryTotalEl.textContent = `(登録 ${mTotal}日間)`;
      if (summaryWorkEl) summaryWorkEl.textContent = `${mWork}日`;
      if (summaryHolEl) summaryHolEl.textContent = `${mHoliday}日`;
      if (summaryPaidEl) summaryPaidEl.textContent = formatPaidLeaveDaysAndHours(mPaidHalfHours, hpd);

      const workHoursEl = document.getElementById("cal-monthly-work-hours");
      const breakdownListEl = document.getElementById("cal-monthly-breakdown-list");
      if (workHoursEl) {
        const hrs = Math.round((mWorkMinutes / 60) * 10) / 10;
        workHoursEl.textContent = `${Number.isInteger(hrs) ? hrs : hrs.toFixed(1)}時間`;
      }
      if (breakdownListEl) {
        breakdownListEl.innerHTML = "";
        const defOrder = Object.keys(masterTimeDefs || {});
        const orderedKeys = Object.keys(typeCounts).sort((a, b) => {
          const ia = defOrder.indexOf(a);
          const ib = defOrder.indexOf(b);
          if (ia !== -1 && ib !== -1) return ia - ib;
          if (ia !== -1) return -1;
          if (ib !== -1) return 1;
          return a.localeCompare(b, "ja");
        });
        if (!orderedKeys.length) {
          breakdownListEl.innerHTML = `<span style="font-size: 12px; color: var(--label-secondary);">この月の登録シフトはありません。</span>`;
        } else {
          orderedKeys.forEach(k => {
            const cap = document.createElement("span");
            cap.className = "metric-capsule";
            cap.innerHTML = `<span>${escapeHtmlText(k)}: <strong>${typeCounts[k]}回</strong></span>`;
            breakdownListEl.appendChild(cap);
          });
        }
      }

      const fiscal = computePaidLeaveFiscalPeriod(
        calendarViewYear,
        calendarViewMonth,
        paidLeaveConfig.startMonth,
        paidLeaveConfig.startDay
      );
      let annualUsedHalfHours = 0;
      const leaveHistoryItems = [];
      Object.keys(calendarShiftsByDate).sort().reverse().forEach(dateStr => {
        if (dateStr >= fiscal.startStr && dateStr <= fiscal.endStr) {
          const s = calendarShiftsByDate[dateStr];
          if (!s) return;
          if (s.status === "paid_leave" || s.is_paid_leave) {
            annualUsedHalfHours += halfPerDay;
            leaveHistoryItems.push({ date: dateStr, dow: s.day_of_week || "", label: "終日有給 (1日)" });
          } else if (!(s.status === "holiday" || s.is_holiday)) {
            const hLeave = clampHalfHour(s.hourly_paid_leave, 0, 0, hpd - 0.5);
            if (hLeave > 0) {
              annualUsedHalfHours += Math.round(hLeave * 2);
              leaveHistoryItems.push({ date: dateStr, dow: s.day_of_week || "", label: `時間有給 ${formatHoursNum(hLeave)}h (${s.type || "出勤"})` });
            }
          }
        }
      });

      const leaveHistoryListEl = document.getElementById("cal-leave-history-list");
      if (leaveHistoryListEl) {
        leaveHistoryListEl.innerHTML = "";
        if (!leaveHistoryItems.length) {
          leaveHistoryListEl.innerHTML = `<div style="font-size: 12px; color: var(--label-secondary); padding: 4px 6px;">この期間内の有給取得履歴はありません。</div>`;
        } else {
          leaveHistoryItems.forEach(item => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "cal-leave-history-item";
            btn.innerHTML = `<span><strong>${escapeHtmlText(item.date)}</strong>${item.dow ? `（${escapeHtmlText(item.dow)}）` : ""}</span><span style="color: var(--label-secondary);">${escapeHtmlText(item.label)}</span>`;
            btn.addEventListener("click", () => {
              jumpToCalendarDate(item.date);
            });
            leaveHistoryListEl.appendChild(btn);
          });
        }
      }
      const annualGrant = clampInt(paidLeaveConfig.annualDays, 20, 0, 365);
      const annualGrantHalfHours = annualGrant * halfPerDay;
      const remainingHalfHours = annualGrantHalfHours - annualUsedHalfHours;
      const isOver = remainingHalfHours < 0;
      const pct = annualGrantHalfHours > 0
        ? Math.min(100, Math.round((annualUsedHalfHours / annualGrantHalfHours) * 100))
        : (annualUsedHalfHours > 0 ? 100 : 0);

      if (annualPeriodEl) annualPeriodEl.textContent = `(${fiscal.label})`;
      if (annualUsedEl) annualUsedEl.textContent = formatPaidLeaveDaysAndHours(annualUsedHalfHours, hpd);
      if (annualRemEl) {
        annualRemEl.textContent = isOver
          ? `0日 0時間（超過 ${formatPaidLeaveDaysAndHours(Math.abs(remainingHalfHours), hpd)}）`
          : formatPaidLeaveDaysAndHours(remainingHalfHours, hpd);
        annualRemEl.style.color = isOver ? "#ff453a" : "";
      }
      if (annualTotalEl) annualTotalEl.textContent = `${annualGrant}日`;
      if (annualProgressEl) {
        annualProgressEl.style.width = `${pct}%`;
        annualProgressEl.classList.toggle("is-over", isOver);
      }
      return mTotal;
    }

    function createMonthlyCalendarCell(cellDate, todayStr, hpd) {
      const cy = cellDate.getFullYear();
      const cm = cellDate.getMonth() + 1;
      const cd = cellDate.getDate();
      const dow = cellDate.getDay();
      const dateStr = formatDateYMD(cy, cm, cd);
      const isOutside = (cy !== calendarViewYear || cm !== calendarViewMonth);
      const isToday = (dateStr === todayStr);
      const shift = calendarShiftsByDate[dateStr] || null;

      const cell = document.createElement("div");
      const dowClass = dow === 0 ? "sun" : (dow === 6 ? "sat" : "");
      const classes = ["cal-cell"];
      if (dowClass) classes.push(dowClass);
      if (isOutside) classes.push("is-outside-month");
      if (isToday) classes.push("is-today");
      if (calendarSelectedDate === dateStr) classes.push("is-selected");
      cell.className = classes.join(" ");
      cell.dataset.date = dateStr;

      const dayNumHtml = isToday
        ? `<span class="cal-today-badge">${cd}</span>`
        : `<span>${cd}</span>`;
      const monthSubHtml = (isOutside || cd === 1)
        ? `<span style="font-size: 9px; color: var(--label-tertiary);">${cm}月</span>`
        : "";

      let bodyHtml = "";
      if (shift) {
        let statusClass = "work";
        const itemKey = getShiftItemKey(shift);
        if (shift.status === "holiday" || shift.is_holiday) {
          statusClass = "holiday";
        } else if (shift.status === "paid_leave" || shift.is_paid_leave) {
          statusClass = "paid";
        }
        const summaryLabel = formatAppleCalendarShiftSummary(shift, hpd);
        const isWorkShift = !(shift.status === "holiday" || shift.is_holiday || shift.status === "paid_leave" || shift.is_paid_leave);
        const hLeaveCell = isWorkShift ? clampHalfHour(shift.hourly_paid_leave, 0, 0, hpd - 0.5) : 0;
        const hourlyBadgeHtml = hLeaveCell > 0
          ? `<div class="cal-hourly-leave-pill" title="時間有給: ${formatHoursNum(hLeaveCell)}時間">時間有給 ${formatHoursNum(hLeaveCell)}h</div>`
          : "";
        const eventText = shift.event ? String(shift.event).trim() : "";
        const eventBadgeHtml = eventText
          ? `<div class="cal-day-event-pill" title="行事予定: ${escapeHtmlText(eventText)}">${escapeHtmlText(eventText)}</div>`
          : "";
        const memoText = shift.memo ? String(shift.memo).trim() : "";
        const memoBadgeHtml = memoText
          ? `<div class="cal-memo-indicator" title="メモ: ${escapeHtmlText(memoText)}"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="8" y1="13" x2="16" y2="13"></line><line x1="8" y1="17" x2="13" y2="17"></line></svg><span>${escapeHtmlText(memoText)}</span></div>`
          : "";
        bodyHtml = `
          <div class="cal-event-capsule ${statusClass} is-apple-summary" data-key="${escapeHtmlText(itemKey)}" title="${escapeHtmlText(summaryLabel)}">
            <div class="cal-capsule-title cal-capsule-summary">${escapeHtmlText(summaryLabel)}</div>
          </div>
          ${hourlyBadgeHtml}
          ${eventBadgeHtml}
          ${memoBadgeHtml}
        `;
        cell.style.cursor = "pointer";
        cell.title = "クリックして詳細・元画像を開く";
        cell.addEventListener("click", () => {
          AppState.calendar.selectedDate = dateStr;
          renderMonthlyCalendarView();
        });
      } else if (isOutside) {
        cell.style.cursor = "pointer";
        cell.addEventListener("click", () => {
          AppState.calendar.viewYear = cy;
          AppState.calendar.viewMonth = cm;
          AppState.calendar.selectedDate = null;
          renderMonthlyCalendarView();
        });
      } else {
        cell.classList.add("is-unregistered-clickable");
        cell.style.cursor = "pointer";
        cell.title = "クリックしてシフトを手入力追加";
        cell.addEventListener("click", () => {
          AppState.calendar.selectedDate = dateStr;
          renderMonthlyCalendarView();
        });
      }

      cell.innerHTML = `
        <div class="cal-cell-header">
          ${dayNumHtml}
          ${monthSubHtml}
        </div>
        ${bodyHtml}
      `;
      return cell;
    }

    function renderMonthlyCalendarView() {
      const monthLabelEl = document.getElementById("cal-current-month-label");
      const summaryTitleEl = document.getElementById("cal-summary-month-title");
      const grid = document.getElementById("monthly-calendar-body");
      const emptyBanner = document.getElementById("monthly-calendar-empty");
      const emptyText = document.getElementById("monthly-calendar-empty-text");

      const ymPrefix = `${calendarViewYear}-${pad2(calendarViewMonth)}`;
      if (monthLabelEl) monthLabelEl.textContent = `${calendarViewYear}年 ${calendarViewMonth}月`;
      if (summaryTitleEl) summaryTitleEl.textContent = `${calendarViewYear}年${calendarViewMonth}月 集計`;

      const hpd = clampHalfHour(paidLeaveConfig.hoursPerDay, 8, 1, 24);
      const mTotal = updateMonthlyCalendarSummaries(ymPrefix, hpd);

      if (!grid) return;
      grid.innerHTML = "";

      const firstDayObj = new Date(calendarViewYear, calendarViewMonth - 1, 1);
      const startDow = firstDayObj.getDay();
      const daysInCurMonth = getDaysInMonth(calendarViewYear, calendarViewMonth);
      const totalSlots = Math.ceil((startDow + daysInCurMonth) / 7) * 7;

      const todayObj = new Date();
      const todayStr = formatDateYMD(todayObj.getFullYear(), todayObj.getMonth() + 1, todayObj.getDate());

      for (let slot = 0; slot < totalSlots; slot++) {
        const dayOffset = slot - startDow + 1;
        const cellDate = new Date(calendarViewYear, calendarViewMonth - 1, dayOffset);
        grid.appendChild(createMonthlyCalendarCell(cellDate, todayStr, hpd));
      }

      if (emptyBanner) {
        if (mTotal === 0) {
          if (emptyText) {
            emptyText.textContent = `${calendarViewYear}年${calendarViewMonth}月の登録済みシフトはありません。`;
          }
          emptyBanner.classList.add("is-visible");
        } else {
          emptyBanner.classList.remove("is-visible");
        }
      }

      renderSelectedDateDetail(calendarSelectedDate);
      applyCalendarViewHighlightFilter();
    }

    async function fetchRegisteredCalendarShifts() {
      try {
        const { res, data: json } = await ApiClient.getJsonWithRes("/api/calendar_shifts");
        if (!res || !res.ok) return;
        if (json && json.success) {
          AppState.calendar.shiftsByDate = json.shifts_by_date || {};
          AppState.calendar.availableMonths = Array.isArray(json.available_months) ? json.available_months : [];
          renderMonthlyCalendarView();
        }
      } catch (e) {
        console.error("Failed to fetch registered calendar shifts:", e);
      }
    }

    // Tab & Calendar Navigation Event Listeners
    function bindMonthlyCalendarControls() {
      const tabBtnCalendarEl = document.getElementById("tab-btn-calendar");
      const tabBtnImportEl = document.getElementById("tab-btn-import");
      if (tabBtnCalendarEl) tabBtnCalendarEl.addEventListener("click", () => switchMainTab("calendar"));
      if (tabBtnImportEl) tabBtnImportEl.addEventListener("click", () => switchMainTab("import"));

      const btnCalPrevMonthEl = document.getElementById("btn-cal-prev-month");
      const btnCalNextMonthEl = document.getElementById("btn-cal-next-month");
      const btnCalTodayEl = document.getElementById("btn-cal-today");
      const btnCalMonthPickerEl = document.getElementById("btn-cal-month-picker");
      const btnPickerPrevYearEl = document.getElementById("btn-picker-prev-year");
      const btnPickerNextYearEl = document.getElementById("btn-picker-next-year");
      const btnCalGoImportEl = document.getElementById("btn-cal-go-import");
      const btnCalOpenLeaveSettingsEl = document.getElementById("btn-cal-open-leave-settings");
      const btnCalOpenHistoryEl = document.getElementById("btn-cal-open-history");
      const btnCalCloseDetailEl = document.getElementById("btn-cal-close-detail");
      const btnCalSaveShiftEl = document.getElementById("btn-cal-save-shift");
      const btnCalSaveHourlyLeaveEl = document.getElementById("btn-cal-save-hourly-leave");

      if (btnCalPrevMonthEl) btnCalPrevMonthEl.addEventListener("click", () => shiftCalendarMonth(-1));
      if (btnCalNextMonthEl) btnCalNextMonthEl.addEventListener("click", () => shiftCalendarMonth(1));
      if (btnCalTodayEl) {
        btnCalTodayEl.addEventListener("click", () => {
          const now = new Date();
          AppState.calendar.viewYear = now.getFullYear();
          AppState.calendar.viewMonth = now.getMonth() + 1;
          AppState.calendar.selectedDate = null;
          setMonthPickerOpen(false);
          renderMonthlyCalendarView();
        });
      }
      if (btnCalMonthPickerEl) {
        btnCalMonthPickerEl.addEventListener("click", (e) => {
          if (e && typeof e.stopPropagation === "function") e.stopPropagation();
          const popover = document.getElementById("cal-month-picker-popover");
          const isOpen = popover && popover.classList.contains("is-open");
          setMonthPickerOpen(!isOpen);
        });
      }
      if (btnPickerPrevYearEl) {
        btnPickerPrevYearEl.addEventListener("click", (e) => {
          if (e && typeof e.stopPropagation === "function") e.stopPropagation();
          calendarPickerYear -= 1;
          renderMonthPickerGrid();
        });
      }
      if (btnPickerNextYearEl) {
        btnPickerNextYearEl.addEventListener("click", (e) => {
          if (e && typeof e.stopPropagation === "function") e.stopPropagation();
          calendarPickerYear += 1;
          renderMonthPickerGrid();
        });
      }
      if (btnCalGoImportEl) btnCalGoImportEl.addEventListener("click", () => switchMainTab("import"));
      if (btnCalOpenLeaveSettingsEl) btnCalOpenLeaveSettingsEl.addEventListener("click", openSettingsModal);
      if (btnCalCloseDetailEl) {
        btnCalCloseDetailEl.addEventListener("click", () => {
          AppState.calendar.selectedDate = null;
          renderMonthlyCalendarView();
        });
      }
      if (btnCalOpenHistoryEl) {
        btnCalOpenHistoryEl.addEventListener("click", async () => {
          const histId = btnCalOpenHistoryEl.dataset ? btnCalOpenHistoryEl.dataset.historyId : "";
          const targetDate = btnCalOpenHistoryEl.dataset ? btnCalOpenHistoryEl.dataset.date : null;
          if (!histId) return;
          await loadHistoryById(histId, { focusDate: targetDate, switchToImport: true });
        });
      }
      if (btnCalSaveShiftEl) {
        btnCalSaveShiftEl.addEventListener("click", async () => {
          const histId = btnCalSaveShiftEl.dataset ? (btnCalSaveShiftEl.dataset.historyId || "") : "";
          const targetDate = btnCalSaveShiftEl.dataset ? btnCalSaveShiftEl.dataset.date : "";
          if (!targetDate) return;
          const typeEl = document.getElementById("cal-detail-shift-type");
          const eventEl = document.getElementById("cal-detail-event-input");
          const memoEl = document.getElementById("cal-detail-memo-input");
          const hourlyEl = document.getElementById("cal-detail-hourly-select");
          const syncEl = document.getElementById("cal-detail-hourly-sync-apple");
          const newType = typeEl ? String(typeEl.value || "").trim() : "";
          const newEvent = eventEl ? String(eventEl.value || "").trim() : "";
          const newMemo = memoEl ? String(memoEl.value || "").trim() : "";
          const syncApple = syncEl ? Boolean(syncEl.checked) : true;
          const calNameEl = document.getElementById("calendar-name");
          const calName = (calNameEl && calNameEl.value ? calNameEl.value.trim() : "") || "シフトカレンダー";

          const payload = {
            history_id: histId,
            date: targetDate,
            type: newType,
            event: newEvent,
            memo: newMemo,
            sync_apple_calendar: syncApple,
            calendar_name: calName,
            include_events: isIncludeEventsEnabled()
          };
          if (!histId && hourlyEl) {
            payload.hourly_paid_leave = clampHalfHour(hourlyEl.value, 0, 0, AppState.calendar.paidLeaveConfig.hoursPerDay - 0.5);
          }

          btnCalSaveShiftEl.disabled = true;
          btnCalSaveShiftEl.textContent = "保存中...";
          try {
            const { res, data: json } = await ApiClient.postJson("/api/calendar_shifts/update", payload);
            if (!res.ok || !json.success) {
              throw new Error(json.error || "シフトの保存に失敗しました");
            }
            await fetchRegisteredCalendarShifts();
            const isManualNew = Boolean(json.manual_created);
            const msg = json.apple_calendar_synced
              ? (isManualNew ? "シフトを手入力追加し、Appleカレンダーへ反映しました" : "シフトを更新し、Appleカレンダーへ反映しました")
              : (isManualNew ? "シフトを手入力追加しました" : "シフトを更新しました");
            showToast(msg, "success");
          } catch (e) {
            showToast(`保存エラー: ${e.message}`, "error");
          } finally {
            btnCalSaveShiftEl.disabled = false;
            btnCalSaveShiftEl.textContent = histId ? "シフトを保存" : "シフトを追加";
          }
        });
      }

      const btnUndoShiftsEl = document.getElementById("btn-undo-shifts");
      if (btnUndoShiftsEl) {
        btnUndoShiftsEl.addEventListener("click", () => {
          undoShiftEdit();
        });
      }

      const toggleShowSummaryColEl = document.getElementById("toggle-show-summary-col");
      if (toggleShowSummaryColEl) {
        toggleShowSummaryColEl.addEventListener("change", () => {
          const tableEl = document.getElementById("shifts-adjust-table");
          if (tableEl) {
            tableEl.classList.toggle("hide-summary-col", !toggleShowSummaryColEl.checked);
          }
        });
      }

      const btnJumpNextReviewEl = document.getElementById("btn-jump-next-review");
      if (btnJumpNextReviewEl) {
        btnJumpNextReviewEl.addEventListener("click", () => {
          if (!currentReviewIndices.length) return;
          currentReviewCursor = (currentReviewCursor + 1) % currentReviewIndices.length;
          const targetIdx = currentReviewIndices[currentReviewCursor];
          selectCalendarDate(targetIdx, { scrollTable: true, debounceImage: false });
        });
      }

      // Phase 3: 月間内訳アコーディオン・年間有給取得履歴アコーディオン・検索・共有出力
      const toggleMonthlyBreakdown = () => {
        const panel = document.getElementById("cal-monthly-breakdown-panel");
        const header = document.getElementById("cal-monthly-summary-header");
        const btn = document.getElementById("btn-cal-monthly-breakdown-toggle");
        if (!panel) return;
        const nextOpen = !panel.classList.contains("is-open");
        panel.classList.toggle("is-open", nextOpen);
        if (header) header.setAttribute("aria-expanded", nextOpen ? "true" : "false");
        if (btn) btn.setAttribute("aria-expanded", nextOpen ? "true" : "false");
      };
      const monthlyHeaderEl = document.getElementById("cal-monthly-summary-header");
      const monthlyToggleBtn = document.getElementById("btn-cal-monthly-breakdown-toggle");
      if (monthlyHeaderEl) {
        monthlyHeaderEl.addEventListener("click", toggleMonthlyBreakdown);
        monthlyHeaderEl.addEventListener("keydown", (e) => {
          if (e && (e.key === "Enter" || e.key === " ")) {
            if (typeof e.preventDefault === "function") e.preventDefault();
            toggleMonthlyBreakdown();
          }
        });
      }
      if (monthlyToggleBtn) {
        monthlyToggleBtn.addEventListener("click", (e) => {
          if (e && typeof e.stopPropagation === "function") e.stopPropagation();
          toggleMonthlyBreakdown();
        });
      }

      const leaveHistToggleBtn = document.getElementById("btn-cal-leave-history-toggle");
      if (leaveHistToggleBtn) {
        leaveHistToggleBtn.addEventListener("click", () => {
          const panel = document.getElementById("cal-leave-history-panel");
          if (!panel) return;
          const nextOpen = !panel.classList.contains("is-open");
          panel.classList.toggle("is-open", nextOpen);
          leaveHistToggleBtn.setAttribute("aria-expanded", nextOpen ? "true" : "false");
        });
      }

      const searchInputEl = document.getElementById("cal-search-input");
      const searchClearBtn = document.getElementById("btn-cal-search-clear");
      if (searchInputEl) {
        searchInputEl.addEventListener("input", (e) => {
          renderCalendarSearchResults(e && e.target ? e.target.value : "");
        });
      }
      if (searchClearBtn) {
        searchClearBtn.addEventListener("click", () => {
          if (searchInputEl) searchInputEl.value = "";
          renderCalendarSearchResults("");
        });
      }

      const setShareMenuOpen = (open) => {
        const menuPopover = document.getElementById("cal-share-menu-popover");
        const menuTrigger = document.getElementById("btn-cal-share-menu");
        const nativeShareBtn = document.getElementById("btn-cal-native-share");
        if (nativeShareBtn) {
          const canNativeShare = typeof navigator !== "undefined" && typeof navigator.share === "function";
          nativeShareBtn.style.display = canNativeShare ? "flex" : "none";
        }
        if (menuPopover) menuPopover.classList.toggle("is-open", Boolean(open));
        if (menuTrigger) {
          menuTrigger.classList.toggle("is-open", Boolean(open));
          menuTrigger.setAttribute("aria-expanded", open ? "true" : "false");
        }
      };

      const btnShareMenuEl = document.getElementById("btn-cal-share-menu");
      if (btnShareMenuEl) {
        btnShareMenuEl.addEventListener("click", (e) => {
          if (e && typeof e.stopPropagation === "function") e.stopPropagation();
          const menuPopover = document.getElementById("cal-share-menu-popover");
          const isOpen = Boolean(menuPopover && menuPopover.classList.contains("is-open"));
          setShareMenuOpen(!isOpen);
        });
      }

      const btnCopyTextEl = document.getElementById("btn-cal-copy-text");
      if (btnCopyTextEl) {
        btnCopyTextEl.addEventListener("click", async () => {
          setShareMenuOpen(false);
          const modeEl = document.getElementById("cal-share-mode");
          const mode = modeEl ? modeEl.value : "all";
          const text = buildMonthlyShareText(calendarViewYear, calendarViewMonth, mode);
          if (!text) {
            showToast("コピー対象のシフトがありません", "error");
            return;
          }
          try {
            await copyTextToClipboard(text);
            showToast("シフト一覧をクリップボードにコピーしました", "success");
          } catch (e) {
            showToast("クリップボードへのコピーに失敗しました", "error");
          }
        });
      }

      const btnCopyImageEl = document.getElementById("btn-cal-copy-image");
      if (btnCopyImageEl) {
        btnCopyImageEl.addEventListener("click", async () => {
          setShareMenuOpen(false);
          try {
            const result = await copyMonthlyCalendarImage(calendarViewYear, calendarViewMonth);
            if (result && result.mode === "clipboard") {
              showToast("カレンダー画像をクリップボードにコピーしました（保存なし）", "success");
            } else {
              showToast("画像を長押しまたは右クリックしてコピー・共有できます", "info");
            }
          } catch (e) {
            showToast(`画像コピーエラー: ${e.message}`, "error");
          }
        });
      }

      const btnPrintEl = document.getElementById("btn-cal-print");
      if (btnPrintEl) {
        btnPrintEl.addEventListener("click", () => {
          setShareMenuOpen(false);
          if (typeof window !== "undefined" && typeof window.print === "function") {
            window.print();
          } else {
            showToast("この環境では印刷機能を呼び出せません", "error");
          }
        });
      }

      const btnNativeShareEl = document.getElementById("btn-cal-native-share");
      if (btnNativeShareEl) {
        btnNativeShareEl.addEventListener("click", async () => {
          setShareMenuOpen(false);
          const modeEl = document.getElementById("cal-share-mode");
          const mode = modeEl ? modeEl.value : "all";
          try {
            const result = await shareMonthlyCalendarNative(calendarViewYear, calendarViewMonth, mode);
            if (result && result.mode !== "cancelled") {
              showToast("共有メニューを開きました", "success");
            }
          } catch (e) {
            showToast(`共有エラー: ${e.message}`, "error");
          }
        });
      }

      const btnExportPngEl = document.getElementById("btn-cal-export-png");
      if (btnExportPngEl) {
        btnExportPngEl.addEventListener("click", () => {
          setShareMenuOpen(false);
          try {
            const ok = exportMonthlyCalendarPng(calendarViewYear, calendarViewMonth);
            if (ok) showToast("月間カレンダー画像を保存しました", "success");
          } catch (e) {
            showToast(`PNG保存エラー: ${e.message}`, "error");
          }
        });
      }

      const imagePreviewModalEl = document.getElementById("cal-image-preview-modal");
      const btnCloseImagePreviewEl = document.getElementById("btn-close-image-preview");
      if (btnCloseImagePreviewEl) {
        btnCloseImagePreviewEl.addEventListener("click", () => {
          closeCalendarImagePreviewModal();
        });
      }
      if (imagePreviewModalEl) {
        imagePreviewModalEl.addEventListener("click", (e) => {
          if (e && e.target === imagePreviewModalEl) {
            closeCalendarImagePreviewModal();
          }
        });
      }
      if (btnCalSaveHourlyLeaveEl) {
        btnCalSaveHourlyLeaveEl.addEventListener("click", async () => {
          const histId = btnCalSaveHourlyLeaveEl.dataset ? btnCalSaveHourlyLeaveEl.dataset.historyId : "";
          const targetDate = btnCalSaveHourlyLeaveEl.dataset ? btnCalSaveHourlyLeaveEl.dataset.date : "";
          if (!histId || !targetDate) return;
          const selEl = document.getElementById("cal-detail-hourly-select");
          const syncEl = document.getElementById("cal-detail-hourly-sync-apple");
          const hours = clampHalfHour(selEl ? selEl.value : 0, 0, 0, AppState.calendar.paidLeaveConfig.hoursPerDay - 0.5);
          const syncApple = syncEl ? Boolean(syncEl.checked) : true;
          const calNameEl = document.getElementById("calendar-name");
          const calName = (calNameEl && calNameEl.value ? calNameEl.value.trim() : "") || "シフトカレンダー";

          btnCalSaveHourlyLeaveEl.disabled = true;
          btnCalSaveHourlyLeaveEl.textContent = "保存中...";
          try {
            const { res, data: json } = await ApiClient.postJson("/api/calendar_shifts/hourly_leave", {
              history_id: histId,
              date: targetDate,
              hourly_paid_leave: hours,
              sync_apple_calendar: syncApple,
              calendar_name: calName,
              include_events: isIncludeEventsEnabled()
            });
            if (!res.ok || !json.success) {
              throw new Error(json.error || "時間有給の保存に失敗しました");
            }
            await fetchRegisteredCalendarShifts();
            const msg = json.apple_calendar_synced
              ? "時間有給を保存し、Appleカレンダーへ反映しました"
              : "時間有給を保存しました";
            showToast(msg, "success");
          } catch (e) {
            showToast(`保存エラー: ${e.message}`, "error");
          } finally {
            btnCalSaveHourlyLeaveEl.disabled = false;
            btnCalSaveHourlyLeaveEl.textContent = "時間有給を保存";
          }
        });
      }

      // Close month picker, share menu & time dial on outside click / Escape, and ArrowLeft/Right navigation
      document.addEventListener("click", (e) => {
        const target = e ? e.target : null;
        const timeDial = document.getElementById("time-dial-popover");
        if (timeDial && timeDial.style.display === "block") {
          const inDial = timeDial.contains && target && timeDial.contains(target);
          const isTargetInput = activeTimeDialInput && target === activeTimeDialInput;
          if (!inDial && !isTargetInput) {
            if (activeTimeDialInput) commitTimeFieldInput(activeTimeDialInput);
            closeTimeDialPopover();
          }
        }
        const shareMenuPopover = document.getElementById("cal-share-menu-popover");
        const shareMenuTrigger = document.getElementById("btn-cal-share-menu");
        if (shareMenuPopover && shareMenuPopover.classList.contains("is-open")) {
          const inShareMenu = shareMenuPopover.contains && target && shareMenuPopover.contains(target);
          const inShareTrigger = shareMenuTrigger && shareMenuTrigger.contains && target && shareMenuTrigger.contains(target);
          if (!inShareMenu && !inShareTrigger) {
            setShareMenuOpen(false);
          }
        }
        const popover = document.getElementById("cal-month-picker-popover");
        const trigger = document.getElementById("btn-cal-month-picker");
        if (!popover || !popover.classList.contains("is-open")) return;
        const inPopover = popover.contains && target && popover.contains(target);
        const inTrigger = trigger && trigger.contains && target && trigger.contains(target);
        if (!inPopover && !inTrigger) {
          setMonthPickerOpen(false);
        }
      });

      document.addEventListener("keydown", (e) => {
        if (!e) return;
        if (e.key === "Escape") {
          setMonthPickerOpen(false);
          setShareMenuOpen(false);
          closeTimeDialPopover();
          closeCalendarImagePreviewModal();
          return;
        }
        const activeTag = document.activeElement && document.activeElement.tagName ? document.activeElement.tagName.toUpperCase() : "";
        const isEditingInput = (activeTag === "INPUT" || activeTag === "SELECT" || activeTag === "TEXTAREA");
        const imagePreviewOpen = Boolean(imagePreviewModalEl && imagePreviewModalEl.style.display === "flex");
        const modalOpen = (settingsModal && settingsModal.style.display === "flex") || (qrModal && qrModal.style.display === "flex") || imagePreviewOpen;
        if ((e.metaKey || e.ctrlKey) && !e.shiftKey && String(e.key || "").toLowerCase() === "z") {
          if (AppState.calendar.activeTab === "import" && !isEditingInput && !modalOpen && shiftUndoStack.length > 0) {
            if (typeof e.preventDefault === "function") e.preventDefault();
            undoShiftEdit();
            return;
          }
        }
        if (AppState.calendar.activeTab !== "calendar") return;
        if (modalOpen) return;
        if (isEditingInput) return;
        if (e.key === "ArrowLeft") shiftCalendarMonth(-1);
        else if (e.key === "ArrowRight") shiftCalendarMonth(1);
      });

      // Touch swipe for mobile month navigation
      const monthlyCalendarFrameEl = document.getElementById("monthly-calendar-frame");
      if (monthlyCalendarFrameEl) {
        let touchStartX = null;
        let touchStartY = null;
        monthlyCalendarFrameEl.addEventListener("touchstart", (e) => {
          if (e && e.touches && e.touches.length === 1) {
            touchStartX = e.touches[0].clientX;
            touchStartY = e.touches[0].clientY;
          }
        }, { passive: true });
        monthlyCalendarFrameEl.addEventListener("touchend", (e) => {
          if (touchStartX === null || !e || !e.changedTouches || !e.changedTouches.length) return;
          const dx = e.changedTouches[0].clientX - touchStartX;
          const dy = e.changedTouches[0].clientY - touchStartY;
          touchStartX = null;
          touchStartY = null;
          if (Math.abs(dx) > 55 && Math.abs(dx) > Math.abs(dy) * 1.4) {
            shiftCalendarMonth(dx < 0 ? 1 : -1);
          }
        }, { passive: true });
      }
    }

    bindMonthlyCalendarControls();

    // Initial tab & empty calendar render before fetch completes
    switchMainTab("calendar");
