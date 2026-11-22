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
          AppState.ui.mobileAccessUrl = data.mobile_url;
          document.getElementById("mobile-url-input").value = AppState.ui.mobileAccessUrl;
          document.getElementById("qr-img").src = `/api/qr.svg?data=${encodeURIComponent(AppState.ui.mobileAccessUrl)}`;
        }
        AppState.analysis.masterTimeDefs = data.time_definitions || {};
        AppState.calendar.paidLeaveConfig = {
          startMonth: clampInt(data.paid_leave_start_month, 4, 1, 12),
          startDay: clampInt(data.paid_leave_start_day, 1, 1, 31),
          annualDays: clampInt(data.paid_leave_annual_days, 20, 0, 365),
          hoursPerDay: clampHalfHour(data.paid_leave_hours_per_day, 8, 1, 24)
        };
        syncPaidLeaveSettingsInputs();
        renderMasterDefs(AppState.analysis.masterTimeDefs);
        renderCalendarViewDefs(AppState.analysis.masterTimeDefs);
        loadHistoryList();
        fetchRegisteredCalendarShifts();
      } catch (e) {
        console.error(e);
      } finally {
        if (isOutdatedServerStopped) return;
        AppState.ui.isConfigLoaded = true;
        if (pendingAutoAnalyzeKey) {
          const keyToRun = pendingAutoAnalyzeKey;
          pendingAutoAnalyzeKey = null;
          triggerAutoAnalyzeFromQuickAction(keyToRun);
        }
        checkPreloadedImage();
      }
    }

    initConfig();

    function renderMasterDefs(defs) {
      renderLegendCapsules("defs-container", defs, AppState.ui.activeHighlightKey, toggleHighlight);
    }

    // 凡例クリックによるハイライト / 解除トグル
    function toggleHighlight(key) {
      if (AppState.ui.activeHighlightKey === key) {
        AppState.ui.activeHighlightKey = null; // 解除
      } else {
        AppState.ui.activeHighlightKey = key; // 設定
      }

      // 個別の日付選択と画像ハイライト枠をクリア
      if (imageFocusTimer) {
        clearTimeout(imageFocusTimer);
        imageFocusTimer = null;
      }
      AppState.ui.selectedCalendarIdx = null;
      document.querySelectorAll(".cal-cell").forEach(c => c.classList.remove("is-selected"));
      document.querySelectorAll("#shifts-tbody tr").forEach(tr => tr.classList.remove("is-selected"));
      const hBox = document.getElementById("viewer-highlight-box");
      if (hBox) hBox.style.display = "none";

      document.querySelectorAll(".legend-capsule").forEach(el => {
        el.classList.toggle("is-active", el.dataset.key === AppState.ui.activeHighlightKey);
      });
      applyHighlightFilter();
    }

    function applyHighlightFilter() {
      // カレンダーピルのハイライト / ディム
      document.querySelectorAll(".cal-event-capsule").forEach(el => {
        const key = el.dataset.key;
        if (!AppState.ui.activeHighlightKey) {
          el.classList.remove("is-highlighted", "is-dimmed");
        } else if (key === AppState.ui.activeHighlightKey) {
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
        if (!AppState.ui.activeHighlightKey) {
          tr.classList.remove("is-highlighted", "is-dimmed");
        } else if (key === AppState.ui.activeHighlightKey) {
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
          if (AppState.history.currentId === id) {
            historyActiveInfo.style.display = "none";
            AppState.history.currentId = null;
            AppState.history.currentMeta = null;
          }
          if (AppState.history.latestId === id) {
            AppState.history.latestId = null;
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
            : `data:${AppState.analysis.mimeType};base64,${latestImageBase64}`;
          AppState.analysis.imageBase64 = imgSrc;
          const compareImg = document.getElementById("compare-image");
          if (compareImg) compareImg.src = imgSrc;
        }
        AppState.analysis.dewarpStatus = latestDewarpStatus;
        updateDewarpStatusBadge(AppState.analysis.dewarpStatus);
        historyActiveInfo.style.display = "none";
        AppState.history.currentId = AppState.history.latestId;
        AppState.history.currentMeta = null;
        showToast("最新の解析結果に戻りました", "normal");
      } else {
        historyActiveInfo.style.display = "none";
        AppState.history.currentId = AppState.history.latestId;
        AppState.history.currentMeta = null;
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
          image_base64: AppState.analysis.imageBase64,
          mime_type: AppState.analysis.mimeType,
          image_name: AppState.analysis.imageName,
          dewarp_status: AppState.analysis.dewarpStatus
        };
        if (options.reuseId && AppState.history.currentId) {
          payload.id = AppState.history.currentId;
        }

        const { data: saved } = await ApiClient.postJson("/api/history/save", payload);
        if (saved && saved.id) {
          AppState.history.currentId = saved.id;
          if (!historyActiveInfo || historyActiveInfo.style.display !== "flex") {
            AppState.history.latestId = saved.id;
          }
        }
        await loadHistoryList();
      } catch (e) {
        console.error("Auto save history error:", e);
      }
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
      if (!preloadKey || autoAnalyzedPreloadKeys.has(preloadKey) || AppState.analysis.isAnalyzing || !AppState.analysis.imageBase64) {
        return;
      }
      if (!AppState.ui.isConfigLoaded) {
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
        AppState.analysis.isCorrectedImageActive = false;
        switchMainTab("import");

        AppState.analysis.imageName = data.file_name;
        AppState.analysis.mimeType = data.mime_type || "image/jpeg";
        if (data.image_base64.startsWith("data:")) {
          AppState.analysis.imageBase64 = data.image_base64;
        } else {
          AppState.analysis.imageBase64 = `data:${AppState.analysis.mimeType};base64,${data.image_base64}`;
        }

        previewFilename.textContent = data.file_name;
        previewFilesize.textContent = `${(data.file_size / 1024).toFixed(1)} KB`;
        const thumb = document.getElementById("preview-thumbnail");
        if (thumb) {
          thumb.src = AppState.analysis.imageBase64;
          thumb.style.display = "block";
        }
        previewBar.style.display = "flex";
        dropZone.style.display = "none";
        btnAnalyze.disabled = false;

        const compareImg = document.getElementById("compare-image");
        if (compareImg) compareImg.src = AppState.analysis.imageBase64;
        AppState.analysis.dewarpStatus = data.dewarp_status || null;
        updateDewarpStatusBadge(AppState.analysis.dewarpStatus);

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
      AppState.analysis.imageName = file.name;
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
          AppState.analysis.imageBase64 = canvas.toDataURL("image/jpeg", 0.95);
          AppState.analysis.mimeType = "image/jpeg";

          document.getElementById("compare-image").src = AppState.analysis.imageBase64;
          const thumb = document.getElementById("preview-thumbnail");
          if (thumb) {
            thumb.src = AppState.analysis.imageBase64;
            thumb.style.display = "block";
          }
          previewBar.style.display = "flex";
          dropZone.style.display = "none";
          btnAnalyze.disabled = false;

          // 自動水平・垂直補正（Phase 1）を即座に適用
          AppState.analysis.dewarpStatus = "processing";
          updateDewarpStatusBadge(AppState.analysis.dewarpStatus);
          ApiClient.postJson("/api/dewarp_preview", { image_base64: AppState.analysis.imageBase64 })
            .then(({ data: res }) => {
              if (res && res.success) {
                const status = res.dewarp_status || (res.corrected_image_base64 ? "applied" : "not_applied");
                if (res.corrected_image_base64 && status !== "not_applied") {
                  AppState.analysis.imageBase64 = res.corrected_image_base64;
                  document.getElementById("compare-image").src = AppState.analysis.imageBase64;
                  if (thumb) thumb.src = AppState.analysis.imageBase64;
                }
                AppState.analysis.dewarpStatus = status;
                updateDewarpStatusBadge(AppState.analysis.dewarpStatus);
              } else {
                AppState.analysis.dewarpStatus = "not_applied";
                updateDewarpStatusBadge(AppState.analysis.dewarpStatus);
              }
            }).catch(() => {
              AppState.analysis.dewarpStatus = "not_applied";
              updateDewarpStatusBadge(AppState.analysis.dewarpStatus);
            });
        };
        img.src = rawData;
      };
      reader.readAsDataURL(file);
    }

    document.getElementById("btn-remove-file").addEventListener("click", () => {
      AppState.analysis.imageBase64 = null;
      AppState.analysis.dewarpStatus = null;
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
      AppState.ui.selectedCalendarIdx = null;
      previewBar.style.display = "none";
      dropZone.style.display = "block";
      btnAnalyze.disabled = true;
      document.getElementById("result-container").style.display = "none";
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
            if (!Number.isNaN(colNum) && colNum >= 1 && AppState.analysis.shifts[colNum - 1] && AppState.analysis.shifts[colNum - 1].date) {
              const rawDate = String(AppState.analysis.shifts[colNum - 1].date);
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
      if (!eventsMap || !AppState.analysis.shifts.length) return 0;
      let applied = 0;
      AppState.analysis.shifts.forEach((s, idx) => {
        const colKey = String(idx + 1);
        if (Object.prototype.hasOwnProperty.call(eventsMap, colKey) && eventsMap[colKey]) {
          s.event = String(eventsMap[colKey]).trim();
          applied++;
        }
      });

      // テーブル入力欄を同期更新
      document.querySelectorAll("#shifts-tbody .shift-event").forEach(input => {
        const idx = parseInt(input.dataset.idx, 10);
        if (!Number.isNaN(idx) && AppState.analysis.shifts[idx]) {
          input.value = AppState.analysis.shifts[idx].event || "";
        }
      });

      renderCalendar(AppState.analysis.shifts);
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
          latestAnalyzedShifts = JSON.parse(JSON.stringify(AppState.analysis.shifts));
          await autoSaveHistory({
            shifts: AppState.analysis.shifts,
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
          AppState.analysis.isCorrectedImageActive = true;
          AppState.analysis.imageBase64 = json.data.corrected_image_base64;
          const compareImg = document.getElementById("compare-image");
          if (compareImg) compareImg.src = json.data.corrected_image_base64;
          const pImg = document.getElementById("preview-thumbnail");
          if (pImg) pImg.src = json.data.corrected_image_base64;
        }
        if (json.data && json.data.dewarp_status) {
          if (!(AppState.analysis.dewarpStatus === "applied" && json.data.dewarp_status === "already_dewarped")) {
            AppState.analysis.dewarpStatus = json.data.dewarp_status;
          }
          updateDewarpStatusBadge(AppState.analysis.dewarpStatus);
        }

        renderResult(json.data);
        latestAnalyzedShifts = JSON.parse(JSON.stringify(json.data.shifts || []));
        latestImageBase64 = AppState.analysis.imageBase64;
        latestDewarpStatus = AppState.analysis.dewarpStatus;

        // Step 2: 続けて下部の縦書き行事予定を独立APIで解析して反映
        if (json.data && json.data.has_event_candidates) {
          showToast("シフト記号を表示しました。続けて行事予定を読み取ります...", "success");
          await runEventAnalysisPhase(apiKey);
          json.data.shifts = AppState.analysis.shifts;
          latestAnalyzedShifts = JSON.parse(JSON.stringify(AppState.analysis.shifts));
        } else {
          updateProgressUI(100, "すべての解析が完了しました", `全 ${AppState.analysis.shifts.length}日分のシフトを抽出しました`, 4, "done");
          if (eventsStatusBadgeEl) eventsStatusBadgeEl.style.display = "none";
          if (btnRetryEventsEl) btnRetryEventsEl.style.display = "inline-flex";
          showToast("解析が完了し、歪み補正済み画像を表示しました", "success");
        }

        await autoSaveHistory(json.data);
      } catch (err) {
        updateProgressUI(100, "解析エラーが発生しました", err.message, 3, "error");
        showToast(`エラー: ${err.message}`, "error");
      } finally {
        AppState.analysis.isAnalyzing = false;
        stopProgressPolling();
        btnAnalyze.disabled = false;
        btnAnalyze.textContent = "シフトを解析";
      }
    }
    btnAnalyze.addEventListener("click", runShiftAnalysis);

    function updateFooterCount() {
      const checkedBoxes = document.querySelectorAll(".shift-check:checked");
      const count = checkedBoxes.length;
      const includeEvents = isIncludeEventsEnabled();
      let eventCount = 0;
      if (includeEvents) {
        checkedBoxes.forEach(cb => {
          const idx = parseInt(cb.dataset.idx, 10);
          const ev = AppState.analysis.shifts[idx] && AppState.analysis.shifts[idx].event ? String(AppState.analysis.shifts[idx].event).trim() : "";
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
      const hpd = clampHalfHour(AppState.calendar.paidLeaveConfig.hoursPerDay, 8, 1, 24);
      const halfPerDay = Math.max(2, Math.round(hpd * 2));
      const months = {};
      AppState.analysis.shifts.forEach(s => {
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
      const defs = AppState.analysis.masterTimeDefs || {};
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
      const curHourlyLeave = isWorkRow ? clampHalfHour(s.hourly_paid_leave, 0, 0, AppState.calendar.paidLeaveConfig.hoursPerDay - 0.5) : 0;
      const hourlyOptionsHtml = buildHourlyLeaveOptionsHtml(curHourlyLeave, AppState.calendar.paidLeaveConfig.hoursPerDay);

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
      if (!Array.isArray(AppState.analysis.shifts) || AppState.analysis.shifts.length === 0) return;
      shiftUndoStack.push(cloneShiftsSnapshot(AppState.analysis.shifts));
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
        AppState.analysis.shifts[idx].type = "休";
        AppState.analysis.shifts[idx].status = "holiday";
        AppState.analysis.shifts[idx].is_holiday = true;
        AppState.analysis.shifts[idx].is_paid_leave = false;
        AppState.analysis.shifts[idx].hourly_paid_leave = 0;
        AppState.analysis.shifts[idx].start_time = null;
        AppState.analysis.shifts[idx].end_time = null;
        AppState.analysis.shifts[idx].summary = "休み";

        inputStart.value = "";
        inputEnd.value = "";
        inputStart.disabled = true;
        inputEnd.disabled = true;
        if (selectHourly) { selectHourly.value = "0"; selectHourly.disabled = true; }
        inputSummary.value = "休み";
      } else if (chosenKey === "㊒") {
        AppState.analysis.shifts[idx].type = "有給";
        AppState.analysis.shifts[idx].status = "paid_leave";
        AppState.analysis.shifts[idx].is_holiday = false;
        AppState.analysis.shifts[idx].is_paid_leave = true;
        AppState.analysis.shifts[idx].hourly_paid_leave = 0;
        AppState.analysis.shifts[idx].start_time = null;
        AppState.analysis.shifts[idx].end_time = null;
        AppState.analysis.shifts[idx].summary = "有給休暇";

        inputStart.value = "";
        inputEnd.value = "";
        inputStart.disabled = true;
        inputEnd.disabled = true;
        if (selectHourly) { selectHourly.value = "0"; selectHourly.disabled = true; }
        inputSummary.value = "有給休暇";
      } else if (matchedOpt && matchedOpt.status === "work") {
        AppState.analysis.shifts[idx].type = chosenKey;
        AppState.analysis.shifts[idx].status = "work";
        AppState.analysis.shifts[idx].is_holiday = false;
        AppState.analysis.shifts[idx].is_paid_leave = false;
        const curH = clampHalfHour(AppState.analysis.shifts[idx].hourly_paid_leave, 0, 0, AppState.calendar.paidLeaveConfig.hoursPerDay - 0.5);

        if (chosenKey !== "その他") {
          AppState.analysis.shifts[idx].start_time = matchedOpt.start;
          AppState.analysis.shifts[idx].end_time = matchedOpt.end;
          AppState.analysis.shifts[idx].summary = applyHourlyLeaveToSummary(`[${chosenKey}] (${matchedOpt.start}〜${matchedOpt.end})`, curH, "work");
          inputStart.value = matchedOpt.start;
          inputEnd.value = matchedOpt.end;
          inputSummary.value = AppState.analysis.shifts[idx].summary;
        } else {
          AppState.analysis.shifts[idx].summary = applyHourlyLeaveToSummary(`[勤務]`, curH, "work");
          inputSummary.value = AppState.analysis.shifts[idx].summary;
        }

        inputStart.disabled = false;
        inputEnd.disabled = false;
        if (selectHourly) selectHourly.disabled = false;
      }

      tr.dataset.key = chosenKey === "㊒" ? "有給" : chosenKey;
      AppState.analysis.shifts[idx]._user_verified = true;
      AppState.analysis.shifts[idx].confidence = "high";
      updateQualitySummaryUI(AppState.analysis.shifts);
      tr.classList.remove("is-quality-warning", "is-quality-error");
      if (AppState.analysis.shifts[idx].quality_level === "error") tr.classList.add("is-quality-error");
      else if (AppState.analysis.shifts[idx].quality_level === "warning") tr.classList.add("is-quality-warning");
      updateMonthlyMetrics();
      renderCalendar(AppState.analysis.shifts);
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
          if (Number.isNaN(idx) || !AppState.analysis.shifts[idx]) return;
          pushShiftUndoSnapshot();
          const hVal = clampHalfHour(e.target.value, 0, 0, AppState.calendar.paidLeaveConfig.hoursPerDay - 0.5);
          AppState.analysis.shifts[idx].hourly_paid_leave = hVal;
          const tr = e.target.closest("tr");
          const inputSummary = tr ? tr.querySelector(".shift-summary") : null;
          const baseSum = inputSummary ? inputSummary.value : (AppState.analysis.shifts[idx].summary || AppState.analysis.shifts[idx].type || "出勤");
          const updatedSum = applyHourlyLeaveToSummary(baseSum, hVal, AppState.analysis.shifts[idx].status || "work");
          AppState.analysis.shifts[idx].summary = updatedSum;
          if (inputSummary) inputSummary.value = updatedSum;
          updateMonthlyMetrics();
          renderCalendar(AppState.analysis.shifts);
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
          if (idx === undefined || Number.isNaN(idx) || !f || !AppState.analysis.shifts[idx]) return;
          if (f === "start_time" || f === "end_time") {
            commitTimeFieldInput(e.target);
            return;
          }
          pushShiftUndoSnapshot();
          AppState.analysis.shifts[idx][f] = e.target.value;
          updateMonthlyMetrics();
          renderCalendar(AppState.analysis.shifts);
          updateFooterCount();
        });
      });
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
      if (!AppState.analysis.shifts || !AppState.analysis.shifts[idx]) return;
      const { scrollTable = true, debounceImage = false } = options;
      const isSameIdx = AppState.ui.selectedCalendarIdx === idx;
      AppState.ui.selectedCalendarIdx = idx;
      const s = AppState.analysis.shifts[idx];

      // 凡例による同種シフト一括ハイライトが有効なら解除
      if (AppState.ui.activeHighlightKey) {
        AppState.ui.activeHighlightKey = null;
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
        cell.className = `cal-cell ${dow === 0 ? "sun" : (dow === 6 ? "sat" : "")} ${AppState.ui.selectedCalendarIdx === idx ? "is-selected" : ""} ${qClass}`.trim();
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

        const hLeaveVal = (s.status === "work") ? clampHalfHour(s.hourly_paid_leave, 0, 0, AppState.calendar.paidLeaveConfig.hoursPerDay - 0.5) : 0;
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
          selected.push(AppState.analysis.shifts[idx]);
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
        const allShifts = AppState.analysis.shifts.length ? analyzedShifts : selected;
        const historyPayload = {
          title: buildHistoryTitle(allShifts),
          target_name: targetName,
          shifts: allShifts,
          image_base64: AppState.analysis.imageBase64,
          mime_type: AppState.analysis.mimeType,
          image_name: AppState.analysis.imageName,
          dewarp_status: AppState.analysis.dewarpStatus
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
          AppState.history.currentId = json.history_id;
          if (!historyActiveInfo || historyActiveInfo.style.display !== "flex") {
            AppState.history.latestId = json.history_id;
          } else if (AppState.history.currentMeta) {
            AppState.history.currentMeta.id = json.history_id;
            AppState.history.currentMeta.registered = true;
            if (json.registered_at) {
              AppState.history.currentMeta.registered_at = json.registered_at;
            }
            updateHistoryActiveBanner(AppState.history.currentMeta);
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

    // Register orchestrator hooks for lower-level modules (no circular imports)
    AppHooks.onShiftTableTimeCommitted = (idx, field, norm) => {
      const shifts = AppState.analysis.shifts;
      if (!shifts || !shifts[idx]) return;
      pushShiftUndoSnapshot();
      shifts[idx][field] = norm;
      updateMonthlyMetrics();
      renderCalendar(shifts);
      updateFooterCount();
    };
    AppHooks.loadHistoryById = loadHistoryById;
    AppHooks.loadHistoryList = loadHistoryList;
    AppHooks.undoShiftEdit = undoShiftEdit;
    AppHooks.selectCalendarDate = selectCalendarDate;
    AppHooks.renderMasterDefs = renderMasterDefs;
    AppHooks.updateMonthlyMetrics = updateMonthlyMetrics;

    bindMonthlyCalendarControls();

    // Initial tab & empty calendar render before fetch completes
    switchMainTab("calendar");
