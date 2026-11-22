    // =========================================================================
    // 2-Tab Navigation & Monthly Registered Calendar View + Annual Paid Leave
    // =========================================================================
    function switchMainTab(tabName) {
      const target = tabName === "import" ? "import" : "calendar";
      AppState.calendar.activeTab = target;

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
      AppState.calendar.highlightKey = (AppState.calendar.highlightKey === key) ? null : key;
      const container = document.getElementById("cal-view-defs-container");
      if (container && container.children) {
        Array.from(container.children).forEach(el => {
          if (el && el.classList && el.dataset) {
            el.classList.toggle("is-active", el.dataset.key === AppState.calendar.highlightKey);
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
        if (!AppState.calendar.highlightKey) {
          el.classList.remove("is-highlighted", "is-dimmed");
        } else if (key === AppState.calendar.highlightKey) {
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
        AppState.calendar.pickerYear = AppState.calendar.viewYear;
        renderMonthPickerGrid();
      }
    }

    function renderMonthPickerGrid() {
      const yearLabel = document.getElementById("cal-picker-year-label");
      const grid = document.getElementById("cal-picker-month-grid");
      if (yearLabel) yearLabel.textContent = `${AppState.calendar.pickerYear}年`;
      if (!grid) return;

      const availableSet = new Set(AppState.calendar.availableMonths || []);
      grid.innerHTML = "";
      for (let m = 1; m <= 12; m++) {
        const ym = `${AppState.calendar.pickerYear}-${pad2(m)}`;
        const btn = document.createElement("button");
        btn.type = "button";
        const isCurrent = (AppState.calendar.pickerYear === AppState.calendar.viewYear && m === AppState.calendar.viewMonth);
        btn.className = `month-picker-item${isCurrent ? " is-current" : ""}`;
        btn.dataset.year = String(AppState.calendar.pickerYear);
        btn.dataset.month = String(m);
        const dotHtml = availableSet.has(ym) ? '<span class="month-picker-dot" title="登録済みシフトあり"></span>' : "";
        btn.innerHTML = `<span>${m}月</span>${dotHtml}`;
        btn.addEventListener("click", () => {
          AppState.calendar.viewYear = AppState.calendar.pickerYear;
          AppState.calendar.viewMonth = m;
          AppState.calendar.selectedDate = null;
          setMonthPickerOpen(false);
          renderMonthlyCalendarView();
        });
        grid.appendChild(btn);
      }
    }

    function shiftCalendarMonth(delta) {
      const dt = new Date(AppState.calendar.viewYear, AppState.calendar.viewMonth - 1 + delta, 1);
      AppState.calendar.viewYear = dt.getFullYear();
      AppState.calendar.viewMonth = dt.getMonth() + 1;
      AppState.calendar.selectedDate = null;
      setMonthPickerOpen(false);
      renderMonthlyCalendarView();
    }

    function buildCalendarShiftTypeOptionsHtml(selectedType) {
      const current = String(selectedType || "").trim();
      const keys = Object.keys(AppState.analysis.masterTimeDefs || {});
      const options = [];
      const seen = new Set();
      keys.forEach(k => {
        seen.add(k);
        const def = AppState.analysis.masterTimeDefs[k];
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

      const shift = AppState.calendar.shiftsByDate[dateStr] || null;
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
        const defaultKeys = Object.keys(AppState.analysis.masterTimeDefs || {});
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
            detailHourlySelect.innerHTML = buildHourlyLeaveOptionsHtml(0, AppState.calendar.paidLeaveConfig.hoursPerDay);
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
      const hLeaveVal = isWorkDay ? clampHalfHour(shift.hourly_paid_leave, 0, 0, AppState.calendar.paidLeaveConfig.hoursPerDay - 0.5) : 0;
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
      const detailTone = resolveShiftTone(shift);
      const detailToneAttr = detailTone ? ` data-shift-tone="${escapeHtmlText(detailTone)}"` : "";
      if (detailBodyEl) {
        detailBodyEl.innerHTML = `
          <span class="cal-event-capsule ${statusClass}"${detailToneAttr} style="flex-direction: row; align-items: center; gap: 8px; padding: 4px 12px;">
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
            detailHourlySelect.innerHTML = buildHourlyLeaveOptionsHtml(hLeaveVal, AppState.calendar.paidLeaveConfig.hoursPerDay);
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
      const matches = Object.keys(AppState.calendar.shiftsByDate)
        .sort()
        .reverse()
        .map(d => AppState.calendar.shiftsByDate[d])
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

      Object.keys(AppState.calendar.shiftsByDate).forEach(dateStr => {
        if (!dateStr.startsWith(ymPrefix + "-")) return;
        const s = AppState.calendar.shiftsByDate[dateStr];
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
        const defOrder = Object.keys(AppState.analysis.masterTimeDefs || {});
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
        AppState.calendar.viewYear,
        AppState.calendar.viewMonth,
        AppState.calendar.paidLeaveConfig.startMonth,
        AppState.calendar.paidLeaveConfig.startDay
      );
      let annualUsedHalfHours = 0;
      const leaveHistoryItems = [];
      Object.keys(AppState.calendar.shiftsByDate).sort().reverse().forEach(dateStr => {
        if (dateStr >= fiscal.startStr && dateStr <= fiscal.endStr) {
          const s = AppState.calendar.shiftsByDate[dateStr];
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
      const annualGrant = clampInt(AppState.calendar.paidLeaveConfig.annualDays, 20, 0, 365);
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
      const isOutside = (cy !== AppState.calendar.viewYear || cm !== AppState.calendar.viewMonth);
      const isToday = (dateStr === todayStr);
      const shift = AppState.calendar.shiftsByDate[dateStr] || null;

      const cell = document.createElement("div");
      const dowClass = dow === 0 ? "sun" : (dow === 6 ? "sat" : "");
      const classes = ["cal-cell"];
      if (dowClass) classes.push(dowClass);
      if (isOutside) classes.push("is-outside-month");
      if (isToday) classes.push("is-today");
      if (AppState.calendar.selectedDate === dateStr) classes.push("is-selected");
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
        const shiftTone = resolveShiftTone(shift);
        const toneAttr = shiftTone ? ` data-shift-tone="${escapeHtmlText(shiftTone)}"` : "";
        const summaryLines = formatCalendarSummaryLines(summaryLabel);
        const summaryLinesHtml = summaryLines.length > 0
          ? summaryLines.map((line, idx) => {
            const lineClass = idx === 0
              ? "cal-summary-line cal-summary-line-main"
              : (line.includes("時間有給")
                ? "cal-summary-line cal-summary-line-hourly"
                : "cal-summary-line cal-summary-line-sub");
            return `<span class="${lineClass}">${escapeHtmlText(line)}</span>`;
          }).join("")
          : escapeHtmlText(summaryLabel);
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
          <div class="cal-event-capsule ${statusClass} is-apple-summary"${toneAttr} data-key="${escapeHtmlText(itemKey)}" title="${escapeHtmlText(summaryLabel)}">
            <div class="cal-capsule-title cal-capsule-summary">${summaryLinesHtml}</div>
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

      const ymPrefix = `${AppState.calendar.viewYear}-${pad2(AppState.calendar.viewMonth)}`;
      if (monthLabelEl) monthLabelEl.textContent = `${AppState.calendar.viewYear}年 ${AppState.calendar.viewMonth}月`;
      if (summaryTitleEl) summaryTitleEl.textContent = `${AppState.calendar.viewYear}年${AppState.calendar.viewMonth}月 集計`;

      const hpd = clampHalfHour(AppState.calendar.paidLeaveConfig.hoursPerDay, 8, 1, 24);
      const mTotal = updateMonthlyCalendarSummaries(ymPrefix, hpd);

      if (!grid) return;
      grid.innerHTML = "";

      const firstDayObj = new Date(AppState.calendar.viewYear, AppState.calendar.viewMonth - 1, 1);
      const startDow = firstDayObj.getDay();
      const daysInCurMonth = getDaysInMonth(AppState.calendar.viewYear, AppState.calendar.viewMonth);
      const totalSlots = Math.ceil((startDow + daysInCurMonth) / 7) * 7;

      const todayObj = new Date();
      const todayStr = formatDateYMD(todayObj.getFullYear(), todayObj.getMonth() + 1, todayObj.getDate());

      for (let slot = 0; slot < totalSlots; slot++) {
        const dayOffset = slot - startDow + 1;
        const cellDate = new Date(AppState.calendar.viewYear, AppState.calendar.viewMonth - 1, dayOffset);
        grid.appendChild(createMonthlyCalendarCell(cellDate, todayStr, hpd));
      }

      if (emptyBanner) {
        if (mTotal === 0) {
          if (emptyText) {
            emptyText.textContent = `${AppState.calendar.viewYear}年${AppState.calendar.viewMonth}月の登録済みシフトはありません。`;
          }
          emptyBanner.classList.add("is-visible");
        } else {
          emptyBanner.classList.remove("is-visible");
        }
      }

      renderSelectedDateDetail(AppState.calendar.selectedDate);
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

    function setCalendarShareMenuOpen(open) {
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
    }

    function bindCalendarNavigationControls() {
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
          AppState.calendar.pickerYear -= 1;
          renderMonthPickerGrid();
        });
      }
      if (btnPickerNextYearEl) {
        btnPickerNextYearEl.addEventListener("click", (e) => {
          if (e && typeof e.stopPropagation === "function") e.stopPropagation();
          AppState.calendar.pickerYear += 1;
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
          if (typeof AppHooks.loadHistoryById === "function") {
            await AppHooks.loadHistoryById(histId, { focusDate: targetDate, switchToImport: true });
          }
        });
      }
    }

    function bindCalendarDetailSaveControls() {
      const btnCalSaveShiftEl = document.getElementById("btn-cal-save-shift");
      const btnCalSaveHourlyLeaveEl = document.getElementById("btn-cal-save-hourly-leave");

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

      const btnUndoShiftsEl = document.getElementById("btn-undo-shifts");
      if (btnUndoShiftsEl) {
        btnUndoShiftsEl.addEventListener("click", () => {
          if (typeof AppHooks.undoShiftEdit === "function") AppHooks.undoShiftEdit();
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
          if (typeof AppHooks.selectCalendarDate === "function") {
            AppHooks.selectCalendarDate(targetIdx, { scrollTable: true, debounceImage: false });
          }
        });
      }
    }

    function bindCalendarAccordionsAndSearch() {
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
    }

    function bindCalendarShareMenuControls() {
      const btnShareMenuEl = document.getElementById("btn-cal-share-menu");
      if (btnShareMenuEl) {
        btnShareMenuEl.addEventListener("click", (e) => {
          if (e && typeof e.stopPropagation === "function") e.stopPropagation();
          const menuPopover = document.getElementById("cal-share-menu-popover");
          const isOpen = Boolean(menuPopover && menuPopover.classList.contains("is-open"));
          setCalendarShareMenuOpen(!isOpen);
        });
      }

      const btnCopyTextEl = document.getElementById("btn-cal-copy-text");
      if (btnCopyTextEl) {
        btnCopyTextEl.addEventListener("click", async () => {
          setCalendarShareMenuOpen(false);
          const modeEl = document.getElementById("cal-share-mode");
          const mode = modeEl ? modeEl.value : "all";
          const text = buildMonthlyShareText(AppState.calendar.viewYear, AppState.calendar.viewMonth, mode);
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
          setCalendarShareMenuOpen(false);
          try {
            const result = await copyMonthlyCalendarImage(AppState.calendar.viewYear, AppState.calendar.viewMonth);
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
          setCalendarShareMenuOpen(false);
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
          setCalendarShareMenuOpen(false);
          const modeEl = document.getElementById("cal-share-mode");
          const mode = modeEl ? modeEl.value : "all";
          try {
            const result = await shareMonthlyCalendarNative(AppState.calendar.viewYear, AppState.calendar.viewMonth, mode);
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
          setCalendarShareMenuOpen(false);
          try {
            const ok = exportMonthlyCalendarPng(AppState.calendar.viewYear, AppState.calendar.viewMonth);
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
    }

    function bindCalendarGlobalShortcutsAndSwipe() {
      const imagePreviewModalEl = document.getElementById("cal-image-preview-modal");

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
            setCalendarShareMenuOpen(false);
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
          setCalendarShareMenuOpen(false);
          closeTimeDialPopover();
          closeCalendarImagePreviewModal();
          return;
        }
        const activeTag = document.activeElement && document.activeElement.tagName ? document.activeElement.tagName.toUpperCase() : "";
        const isEditingInput = (activeTag === "INPUT" || activeTag === "SELECT" || activeTag === "TEXTAREA");
        const imagePreviewOpen = Boolean(imagePreviewModalEl && imagePreviewModalEl.style.display === "flex");
        const settingsModalEl = document.getElementById("settings-modal");
        const qrModalEl = document.getElementById("qr-modal");
        const modalOpen = (settingsModalEl && settingsModalEl.style.display === "flex") || (qrModalEl && qrModalEl.style.display === "flex") || imagePreviewOpen;
        if ((e.metaKey || e.ctrlKey) && !e.shiftKey && String(e.key || "").toLowerCase() === "z") {
          if (AppState.calendar.activeTab === "import" && !isEditingInput && !modalOpen && shiftUndoStack.length > 0) {
            if (typeof e.preventDefault === "function") e.preventDefault();
            if (typeof AppHooks.undoShiftEdit === "function") AppHooks.undoShiftEdit();
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

    // Tab & Calendar Navigation Event Listeners
    function bindMonthlyCalendarControls() {
      bindCalendarNavigationControls();
      bindCalendarDetailSaveControls();
      bindCalendarAccordionsAndSearch();
      bindCalendarShareMenuControls();
      bindCalendarGlobalShortcutsAndSwipe();
    }
