    // =========================================================================
    // QR Modal, Settings Modal, Shift Definitions Editor & Config Persistence
    // =========================================================================
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
      navigator.clipboard.writeText(AppState.ui.mobileAccessUrl).then(() => {
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
        return { defs: AppState.analysis.masterTimeDefs, error: null };
      }
      const rows = Array.from(listEl.children).filter(el => el && (el._defInputs || (el.classList && el.classList.contains("settings-def-row"))));
      if (!rows || rows.length === 0) {
        return { defs: AppState.analysis.masterTimeDefs, error: null };
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
      renderSettingsTimeDefsEditor(AppState.analysis.masterTimeDefs);
      if (settingsModal) settingsModal.style.display = "flex";
    }

    function closeSettingsModal() {
      setApiKeyVisibility(false);
      if (settingsModal) settingsModal.style.display = "none";
    }

    async function saveAppConfig() {
      const plCfg = AppState.calendar.paidLeaveConfig;
      const startMonthEl = document.getElementById("paid-leave-start-month");
      const startDayEl = document.getElementById("paid-leave-start-day");
      const annualDaysEl = document.getElementById("paid-leave-annual-days");
      const hoursPerDayEl = document.getElementById("paid-leave-hours-per-day");
      const startMonth = clampInt(startMonthEl ? startMonthEl.value : plCfg.startMonth, 4, 1, 12);
      const startDay = clampInt(startDayEl ? startDayEl.value : plCfg.startDay, 1, 1, 31);
      const annualDays = clampInt(annualDaysEl ? annualDaysEl.value : plCfg.annualDays, 20, 0, 365);
      const hoursPerDay = clampHalfHour(hoursPerDayEl ? hoursPerDayEl.value : plCfg.hoursPerDay, 8, 1, 24);

      const collectedDefs = collectSettingsTimeDefsFromEditor();
      if (collectedDefs.error) {
        showToast(collectedDefs.error, "error");
        return false;
      }

      const cfg = {
        api_key: document.getElementById("api-key").value.trim(),
        default_name: document.getElementById("target-name").value.trim(),
        calendar_name: document.getElementById("calendar-name").value.trim(),
        theme: AppState.ui.themeMode,
        time_definitions: collectedDefs.defs || AppState.analysis.masterTimeDefs,
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
        const nextDefs = (respJson && respJson.config && respJson.config.time_definitions)
          ? respJson.config.time_definitions
          : cfg.time_definitions;
        AppState.analysis.masterTimeDefs = nextDefs;
        AppState.calendar.paidLeaveConfig = { startMonth, startDay, annualDays, hoursPerDay };
        syncPaidLeaveSettingsInputs();
        syncBasicConfigSummary();
        if (typeof AppHooks.renderMasterDefs === "function") AppHooks.renderMasterDefs(nextDefs);
        renderCalendarViewDefs(nextDefs);
        if (typeof AppHooks.updateMonthlyMetrics === "function") AppHooks.updateMonthlyMetrics();
        renderMonthlyCalendarView();
        showToast("設定を保存しました", "success");
        return true;
      } catch (e) {
        showToast(e && e.message ? e.message : "設定保存に失敗しました", "error");
        return false;
      }
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
          if (typeof AppHooks.loadHistoryList === "function") await AppHooks.loadHistoryList();
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
    const btnSaveCfgEl = document.getElementById("btn-save-cfg");
    if (btnSaveCfgEl) btnSaveCfgEl.addEventListener("click", saveAppConfig);
    if (btnSaveSettingsModal) {
      btnSaveSettingsModal.addEventListener("click", async () => {
        const ok = await saveAppConfig();
        if (ok) closeSettingsModal();
      });
    }
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        if (settingsModal && settingsModal.style.display === "flex") closeSettingsModal();
        if (qrModal && qrModal.style.display === "flex") qrModal.style.display = "none";
      }
    });
