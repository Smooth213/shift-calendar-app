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
        get pickerYear() { return calendarPickerYear; },
        set pickerYear(v) { calendarPickerYear = v; },
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
        get dragStartX() { return dragStartX; },
        set dragStartX(v) { dragStartX = v; },
        get dragStartY() { return dragStartY; },
        set dragStartY(v) { dragStartY = v; },
        get dragOriginX() { return dragOriginX; },
        set dragOriginX(v) { dragOriginX = v; },
        get dragOriginY() { return dragOriginY; },
        set dragOriginY(v) { dragOriginY = v; },
      },
      ui: {
        get themeMode() { return currentThemeMode; },
        set themeMode(v) { currentThemeMode = v; },
        get mobileAccessUrl() { return mobileAccessUrl; },
        set mobileAccessUrl(v) { mobileAccessUrl = v; },
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

    const SHIFT_TONE_BY_TYPE = {
      "早A": "early-a",
      "早B": "early-b",
      "早C": "early-c",
      "早D": "early-d",
      "日": "day",
      "遅A": "late-a",
      "遅B": "late-b",
      "遅C": "late-c",
    };

    const SHIFT_TONE_CANVAS_PALETTE = {
      "early-a": { bg: "#ffede3", border: "#f8b494", fg: "#a13a10" },
      "early-b": { bg: "#fff5d6", border: "#f2cb63", fg: "#8c5500" },
      "early-c": { bg: "#eaf8e6", border: "#a3db99", fg: "#24611f" },
      "early-d": { bg: "#e3f4ff", border: "#8ecdf5", fg: "#0b5582" },
      "day":     { bg: "#e8eeff", border: "#a3b8fa", fg: "#1d429e" },
      "late-a":  { bg: "#eeeaff", border: "#bab0f7", fg: "#4332a3" },
      "late-b":  { bg: "#f4e8ff", border: "#d2adf7", fg: "#6d28a8" },
      "late-c":  { bg: "#e6ebf5", border: "#9fb0d1", fg: "#1e3358" },
    };

    const CALENDAR_CANVAS_COLORS = {
      windowBg: "#ffffff",
      headerBg: "#f2f2f6",
      separator: "rgba(0, 0, 0, 0.08)",
      controlBorder: "rgba(0, 0, 0, 0.14)",
      labelPrimary: "#1c1c1e",
      labelSecondary: "#636366",
      labelTertiary: "#8e8e93",
      sun: "#ff453a",
      sat: "#007aff",
      work: { bg: "#fff3e0", border: "#ffcc80", fg: "#b26a00", dot: "#ff9500" },
      holiday: { bg: "#f2f2f7", border: "#d1d1d6", fg: "#48484a", dot: "#8e8e93" },
      paid: { bg: "#ffebee", border: "#ffcdd2", fg: "#c2185b", dot: "#ff2d55" },
      event: { bg: "#e6f7f5", border: "#99e2d9", fg: "#0f6b63" },
      memo: { bg: "rgba(142, 142, 147, 0.12)", fg: "#636366" },
    };

    function parseShiftStartMinutes(timeStr) {
      const m = String(timeStr || "").trim().match(/^(\d{1,2}):(\d{2})$/);
      if (!m) return null;
      const hh = parseInt(m[1], 10);
      const mm = parseInt(m[2], 10);
      if (!Number.isFinite(hh) || !Number.isFinite(mm) || hh < 0 || hh > 23 || mm < 0 || mm > 59) return null;
      return hh * 60 + mm;
    }

    function resolveShiftTone(shiftOrType, startTimeHint = "") {
      if (!shiftOrType) return "";
      if (typeof shiftOrType === "object") {
        if (shiftOrType.status === "holiday" || shiftOrType.is_holiday) return "holiday";
        if (shiftOrType.status === "paid_leave" || shiftOrType.is_paid_leave) return "paid";
        const typeKey = String(shiftOrType.type || "").trim();
        const startHint = shiftOrType.start_time || (masterTimeDefs && masterTimeDefs[typeKey] && masterTimeDefs[typeKey].start) || startTimeHint || "";
        return resolveShiftTone(typeKey, startHint);
      }
      const key = String(shiftOrType || "").trim();
      if (key === "休" || key === "休み") return "holiday";
      if (key === "有給" || key === "有給休暇") return "paid";
      if (SHIFT_TONE_BY_TYPE[key]) return SHIFT_TONE_BY_TYPE[key];

      const effectiveStart = startTimeHint || (masterTimeDefs && masterTimeDefs[key] && masterTimeDefs[key].start) || "";
      const mins = parseShiftStartMinutes(effectiveStart);
      if (mins === null) return "";
      if (mins < 6 * 60 + 15) return "early-a";
      if (mins < 6 * 60 + 45) return "early-b";
      if (mins < 7 * 60 + 30) return "early-c";
      if (mins < 8 * 60 + 15) return "early-d";
      if (mins < 8 * 60 + 45) return "day";
      if (mins < 9 * 60 + 15) return "late-a";
      if (mins < 9 * 60 + 45) return "late-b";
      return "late-c";
    }

    function formatCalendarSummaryLines(summaryLabel) {
      const text = String(summaryLabel || "").trim();
      if (!text) return [];
      let rest = text;
      let hourlyPart = "";

      const hourlyMatch = rest.match(/\s*([（(]時間有給[^）)]*[）)])\s*$/);
      if (hourlyMatch) {
        hourlyPart = hourlyMatch[1];
        rest = rest.slice(0, hourlyMatch.index).trim();
      }

      const lines = [];
      const bracketMatch = rest.match(/^(\[[^\]]+\])\s+(.+)$/);
      if (bracketMatch) {
        lines.push(bracketMatch[1]);
        lines.push(bracketMatch[2].trim());
      } else if (rest) {
        const timeMatch = rest.match(/^(.+?)\s+([（(]\d{1,2}:\d{2}\s*[〜~\-–—]\s*\d{1,2}:\d{2}[）)])$/);
        if (timeMatch) {
          lines.push(timeMatch[1].trim());
          lines.push(timeMatch[2].trim());
        } else {
          lines.push(rest);
        }
      }

      if (hourlyPart) {
        lines.push(hourlyPart);
      }
      return lines;
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

    // =========================================================================
    // Cross-Module Orchestrator Hooks (Prevents Circular Dependencies)
    // =========================================================================
    const AppHooks = {
      onShiftTableTimeCommitted: null,
      loadHistoryById: null,
      loadHistoryList: null,
      undoShiftEdit: null,
      selectCalendarDate: null,
      renderMasterDefs: null,
      updateMonthlyMetrics: null,
    };

    // =========================================================================
    // Shared Pure Utilities & Legend Capsule Renderer
    // =========================================================================
    function pad2(n) {
      return String(n).padStart(2, "0");
    }

    function formatDateYMD(year, month, day) {
      return `${year}-${pad2(month)}-${pad2(day)}`;
    }

    function getDaysInMonth(year, month) {
      return new Date(year, month, 0).getDate();
    }

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

    function renderLegendCapsules(containerId, defs, activeKey, onToggle, extraClass = "") {
      const container = document.getElementById(containerId);
      if (!container) return;
      container.innerHTML = "";
      const baseClass = extraClass ? `legend-capsule ${extraClass}` : "legend-capsule";

      const showToneDot = extraClass === "cal-view-legend";

      Object.keys(defs || {}).forEach(k => {
        const tag = document.createElement("div");
        tag.className = `${baseClass} ${activeKey === k ? "is-active" : ""}`;
        tag.dataset.key = k;
        tag.title = "クリックでカレンダーの該当シフトをハイライト（再クリックで解除）";
        const tone = resolveShiftTone(k, defs[k] ? defs[k].start : "");
        const dotHtml = showToneDot
          ? `<span class="legend-tone-dot"${tone ? ` data-shift-tone="${escapeHtmlText(tone)}"` : ""} aria-hidden="true"></span>`
          : "";
        tag.innerHTML = `${dotHtml}<strong>${escapeHtmlText(k)}</strong> ${escapeHtmlText(defs[k].start)}〜${escapeHtmlText(defs[k].end)}`;
        tag.addEventListener("click", () => onToggle(k));
        container.appendChild(tag);
      });

      const staticEntries = [
        { key: "休", tone: "holiday", title: "クリックでカレンダーの休みをハイライト（再クリックで解除）", label: "終日休み" },
        { key: "有給", tone: "paid", title: "クリックでカレンダーの有給休暇をハイライト（再クリックで解除）", label: "終日有給休暇" },
      ];
      staticEntries.forEach(item => {
        const el = document.createElement("div");
        el.className = `${baseClass} ${activeKey === item.key ? "is-active" : ""}`;
        el.dataset.key = item.key;
        el.title = item.title;
        const dotHtml = showToneDot
          ? `<span class="legend-tone-dot" data-shift-tone="${item.tone}" aria-hidden="true"></span>`
          : "";
        el.innerHTML = `${dotHtml}<strong>${escapeHtmlText(item.key)}</strong> ${escapeHtmlText(item.label)}`;
        el.addEventListener("click", () => onToggle(item.key));
        container.appendChild(el);
      });
    }
