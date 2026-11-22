    // =========================================================================
    // Monthly Calendar Share Text & Canvas Image Export
    // =========================================================================
    function buildMonthlyShareText(year, month, mode = "all") {
      const ymPrefix = `${year}-${pad2(month)}`;
      const dowLabels = ["日", "月", "火", "水", "木", "金", "土"];
      const modeLabels = {
        all: "全日程",
        off: "休み・有給のみ",
        early_late: "早番・遅番のみ"
      };
      const shiftsByDate = AppState.calendar.shiftsByDate;
      const dates = Object.keys(shiftsByDate)
        .filter(d => d.startsWith(ymPrefix + "-"))
        .sort();

      const lines = [`${year}年${month}月のシフト（${modeLabels[mode] || "全日程"}）`];
      let matchedCount = 0;

      dates.forEach(dateStr => {
        const s = shiftsByDate[dateStr];
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
          const hLeave = clampHalfHour(s.hourly_paid_leave, 0, 0, AppState.calendar.paidLeaveConfig.hoursPerDay - 0.5);
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

    function traceCanvasRoundedRect(ctx, x, y, w, h, radius) {
      const r = Math.max(0, Math.min(radius, w / 2, h / 2));
      ctx.beginPath();
      ctx.moveTo(x + r, y);
      ctx.lineTo(x + w - r, y);
      ctx.quadraticCurveTo(x + w, y, x + w, y + r);
      ctx.lineTo(x + w, y + h - r);
      ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
      ctx.lineTo(x + r, y + h);
      ctx.quadraticCurveTo(x, y + h, x, y + h - r);
      ctx.lineTo(x, y + r);
      ctx.quadraticCurveTo(x, y, x + r, y);
      ctx.closePath();
    }

    function drawCanvasRoundedRect(ctx, x, y, w, h, radius, fillColor, strokeColor, lineWidth = 1) {
      const canPath = Boolean(
        typeof ctx.beginPath === "function" &&
        typeof ctx.moveTo === "function" &&
        typeof ctx.lineTo === "function" &&
        typeof ctx.quadraticCurveTo === "function" &&
        typeof ctx.closePath === "function"
      );
      if (canPath) {
        traceCanvasRoundedRect(ctx, x, y, w, h, radius);
        if (fillColor && typeof ctx.fill === "function") {
          ctx.fillStyle = fillColor;
          ctx.fill();
        }
        if (strokeColor && typeof ctx.stroke === "function") {
          ctx.strokeStyle = strokeColor;
          ctx.lineWidth = lineWidth;
          ctx.stroke();
        }
        return;
      }
      if (fillColor) {
        ctx.fillStyle = fillColor;
        ctx.fillRect(x, y, w, h);
      }
      if (strokeColor) {
        ctx.strokeStyle = strokeColor;
        ctx.lineWidth = lineWidth;
        ctx.strokeRect(x, y, w, h);
      }
    }

    function drawCanvasCircle(ctx, cx, cy, radius, fillColor) {
      if (typeof ctx.beginPath === "function" && typeof ctx.arc === "function" && typeof ctx.fill === "function") {
        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        ctx.fillStyle = fillColor;
        ctx.fill();
        return;
      }
      ctx.fillStyle = fillColor;
      ctx.fillRect(cx - radius, cy - radius, radius * 2, radius * 2);
    }

    function measureCanvasTextWidth(ctx, text, approxCharWidth = 10) {
      const str = String(text || "");
      if (typeof ctx.measureText === "function") {
        const m = ctx.measureText(str);
        if (m && typeof m.width === "number" && Number.isFinite(m.width)) {
          return m.width;
        }
      }
      let units = 0;
      for (let i = 0; i < str.length; i++) {
        units += str.charCodeAt(i) > 0xff ? 1 : 0.56;
      }
      return units * approxCharWidth;
    }

    function truncateCanvasText(ctx, text, maxWidth, fallbackMaxChars = 14) {
      const str = String(text || "");
      if (!str) return "";
      if (typeof ctx.measureText === "function") {
        if (measureCanvasTextWidth(ctx, str) <= maxWidth) return str;
        const ellipsis = "…";
        let end = str.length;
        while (end > 1 && measureCanvasTextWidth(ctx, str.slice(0, end) + ellipsis) > maxWidth) {
          end--;
        }
        return str.slice(0, end) + ellipsis;
      }
      return str.length > fallbackMaxChars ? str.slice(0, fallbackMaxChars - 1) + "…" : str;
    }

    function drawCanvasMemoIcon(ctx, x, y, color) {
      if (
        typeof ctx.beginPath !== "function" ||
        typeof ctx.moveTo !== "function" ||
        typeof ctx.lineTo !== "function" ||
        typeof ctx.stroke !== "function"
      ) {
        return;
      }
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.1;
      ctx.beginPath();
      ctx.moveTo(x + 1, y);
      ctx.lineTo(x + 6, y);
      ctx.lineTo(x + 8.5, y + 2.5);
      ctx.lineTo(x + 8.5, y + 9.5);
      ctx.lineTo(x + 1, y + 9.5);
      ctx.closePath();
      ctx.moveTo(x + 5.8, y);
      ctx.lineTo(x + 5.8, y + 2.8);
      ctx.lineTo(x + 8.5, y + 2.8);
      ctx.moveTo(x + 2.6, y + 5.2);
      ctx.lineTo(x + 6.8, y + 5.2);
      ctx.moveTo(x + 2.6, y + 7.2);
      ctx.lineTo(x + 5.6, y + 7.2);
      ctx.stroke();
    }

    function computeCalendarCanvasLayout(year, month, hpd) {
      const ymPrefix = `${year}-${pad2(month)}`;
      const firstDayObj = new Date(year, month - 1, 1);
      const startDow = firstDayObj.getDay();
      const daysInCurMonth = getDaysInMonth(year, month);
      const rows = Math.ceil((startDow + daysInCurMonth) / 7);
      const halfPerDay = Math.round(hpd * 2);

      // 月間集計（カレンダータブの集計ロジックと統一）
      const shiftsByDate = AppState.calendar.shiftsByDate;
      let mWork = 0, mHol = 0, mPaidHalfHours = 0, mTotal = 0;
      Object.keys(shiftsByDate).forEach(d => {
        if (!d.startsWith(ymPrefix + "-")) return;
        const s = shiftsByDate[d];
        if (!s) return;
        mTotal++;
        if (s.status === "holiday" || s.is_holiday) {
          mHol++;
        } else if (s.status === "paid_leave" || s.is_paid_leave) {
          mPaidHalfHours += halfPerDay;
        } else {
          mWork++;
          const hLeave = clampHalfHour(s.hourly_paid_leave, 0, 0, hpd - 0.5);
          if (hLeave > 0) mPaidHalfHours += Math.round(hLeave * 2);
        }
      });

      const minCellH = 104;
      const cellPad = 7;
      const itemGap = 4;
      const pillH = 19;
      const headerDateH = 22;
      const slotItems = [];
      const rowHeights = new Array(rows).fill(minCellH);

      for (let slot = 0; slot < rows * 7; slot++) {
        const r = Math.floor(slot / 7);
        const c = slot % 7;
        const dayOffset = slot - startDow + 1;
        const cellDate = new Date(year, month - 1, dayOffset);
        const cy = cellDate.getFullYear();
        const cm = cellDate.getMonth() + 1;
        const cd = cellDate.getDate();
        const isOutside = (cy !== year || cm !== month);
        const dateStr = formatDateYMD(cy, cm, cd);
        const s = shiftsByDate[dateStr] || null;

        let summaryLines = [];
        let hLeaveCell = 0;
        let eventText = "";
        let memoText = "";
        let capsuleH = 0;

        if (s) {
          const isHol = Boolean(s.status === "holiday" || s.is_holiday);
          const isPaid = Boolean(s.status === "paid_leave" || s.is_paid_leave);
          const isWorkShift = !(isHol || isPaid);
          const summaryLabel = formatAppleCalendarShiftSummary(s, hpd);
          summaryLines = formatCalendarSummaryLines(summaryLabel);
          if (summaryLines.length === 0) {
            summaryLines = [isHol ? "休み" : (isPaid ? "有給休暇" : (s.type || "出勤"))];
          }
          capsuleH = 10 + summaryLines.length * 14;
          hLeaveCell = isWorkShift ? clampHalfHour(s.hourly_paid_leave, 0, 0, hpd - 0.5) : 0;
          eventText = s.event ? String(s.event).trim() : "";
          memoText = s.memo ? String(s.memo).trim() : "";

          let neededH = cellPad + headerDateH + capsuleH;
          if (hLeaveCell > 0) neededH += itemGap + pillH;
          if (eventText) neededH += itemGap + pillH;
          if (memoText) neededH += itemGap + pillH;
          neededH += cellPad;
          if (neededH > rowHeights[r]) rowHeights[r] = neededH;
        }

        slotItems.push({ r, c, cy, cm, cd, isOutside, dateStr, s, summaryLines, capsuleH, hLeaveCell, eventText, memoText });
      }

      return {
        rows,
        slotItems,
        rowHeights,
        cellPad,
        itemGap,
        pillH,
        headerDateH,
        metrics: { mWork, mHol, mPaidHalfHours, mTotal },
      };
    }

    function drawCalendarCanvasHeader(ctx, width, pad, year, month, hpd, metrics, fontSans) {
      const colors = CALENDAR_CANVAS_COLORS;
      ctx.textAlign = "left";
      const titleText = `${year}年 ${month}月`;
      ctx.fillStyle = colors.labelPrimary;
      ctx.font = `700 22px ${fontSans}`;
      ctx.fillText(titleText, pad, 44);
      const titleW = measureCanvasTextWidth(ctx, titleText, 18);

      ctx.fillStyle = colors.labelSecondary;
      ctx.font = `500 12px ${fontSans}`;
      ctx.fillText(`(登録 ${metrics.mTotal}日間)`, pad + titleW + 10, 43);

      const mPaidText = formatPaidLeaveDaysAndHours(metrics.mPaidHalfHours, hpd);
      const metricCapsules = [
        { dot: colors.work.dot, label: "出勤: ", value: `${metrics.mWork}日` },
        { dot: colors.holiday.dot, label: "休み: ", value: `${metrics.mHol}日` },
        { dot: colors.paid.dot, label: "有給休暇: ", value: mPaidText },
      ];
      const capH = 26;
      const capY = 24;
      const capGap = 8;
      const capSpecs = metricCapsules.map(item => {
        ctx.font = `500 11.5px ${fontSans}`;
        const lw = measureCanvasTextWidth(ctx, item.label, 9);
        ctx.font = `700 11.5px ${fontSans}`;
        const vw = measureCanvasTextWidth(ctx, item.value, 9);
        const w = 12 + 8 + 6 + lw + vw + 12;
        return { ...item, lw, vw, w };
      });
      const totalCapsW = capSpecs.reduce((sum, s) => sum + s.w, 0) + capGap * (capSpecs.length - 1);
      let capX = width - pad - totalCapsW;
      capSpecs.forEach(item => {
        drawCanvasRoundedRect(ctx, capX, capY, item.w, capH, capH / 2, colors.windowBg, colors.controlBorder, 1);
        drawCanvasCircle(ctx, capX + 15, capY + capH / 2, 4, item.dot);
        ctx.fillStyle = colors.labelPrimary;
        ctx.font = `500 11.5px ${fontSans}`;
        ctx.fillText(item.label, capX + 24, capY + 17);
        ctx.font = `700 11.5px ${fontSans}`;
        ctx.fillText(item.value, capX + 24 + item.lw, capY + 17);
        capX += item.w + capGap;
      });
    }

    function drawCalendarCanvasCell(ctx, item, geom) {
      const colors = CALENDAR_CANVAS_COLORS;
      const { x, y, colW, cellH, cellPad, headerDateH, itemGap, pillH, fontSans, fontMono } = geom;
      const innerW = colW - cellPad * 2;

      ctx.fillStyle = item.isOutside ? colors.headerBg : colors.windowBg;
      ctx.fillRect(x, y, colW, cellH);

      // セル区切り線
      ctx.strokeStyle = colors.separator;
      ctx.lineWidth = 1;
      ctx.strokeRect(x, y, colW, cellH);

      const canAlpha = Boolean(item.isOutside && typeof ctx.save === "function" && typeof ctx.restore === "function");
      if (canAlpha) {
        ctx.save();
        ctx.globalAlpha = 0.52;
      }

      // 日付ヘッダー（左：日付、右：1日または月外なら「X月」）
      ctx.fillStyle = item.c === 0 ? colors.sun : (item.c === 6 ? colors.sat : colors.labelPrimary);
      ctx.font = `600 12px ${fontSans}`;
      ctx.textAlign = "left";
      ctx.fillText(String(item.cd), x + cellPad, y + 18);

      if (item.isOutside || item.cd === 1) {
        ctx.fillStyle = colors.labelTertiary;
        ctx.font = `500 9.5px ${fontSans}`;
        ctx.textAlign = "right";
        ctx.fillText(`${item.cm}月`, x + colW - cellPad, y + 17);
        ctx.textAlign = "left";
      }

      const s = item.s;
      if (s) {
        const isHol = Boolean(s.status === "holiday" || s.is_holiday);
        const isPaid = Boolean(s.status === "paid_leave" || s.is_paid_leave);
        const toneKey = resolveShiftTone(s);
        const toneColors = SHIFT_TONE_CANVAS_PALETTE[toneKey] || null;
        const palette = isHol
          ? colors.holiday
          : (isPaid ? colors.paid : (toneColors || colors.work));

        let cursorY = y + cellPad + headerDateH;

        // シフトカプセル（.cal-event-capsule.is-apple-summary 準拠：角丸10px + 1px枠線）
        drawCanvasRoundedRect(
          ctx, x + cellPad, cursorY, innerW, item.capsuleH, 10, palette.bg, palette.border, 1
        );

        const textMaxW = innerW - 14;
        item.summaryLines.forEach((line, lineIdx) => {
          const isMain = lineIdx === 0;
          const isHourlyLine = !isMain && line.includes("時間有給");
          ctx.fillStyle = palette.fg;
          if (isMain) {
            ctx.font = `700 11.5px ${fontSans}`;
          } else if (isHourlyLine) {
            ctx.font = `600 10px ${fontSans}`;
          } else {
            ctx.font = `500 10px ${fontMono}`;
          }
          const displayLine = truncateCanvasText(ctx, line, textMaxW, 18);
          ctx.fillText(displayLine, x + cellPad + 7, cursorY + 15 + lineIdx * 14);
        });
        cursorY += item.capsuleH + itemGap;

        // 時間有給ピル（.cal-hourly-leave-pill 準拠）
        if (item.hLeaveCell > 0) {
          drawCanvasRoundedRect(
            ctx, x + cellPad, cursorY, innerW, pillH, pillH / 2, colors.paid.bg, colors.paid.border, 1
          );
          ctx.fillStyle = colors.paid.fg;
          ctx.font = `600 10px ${fontSans}`;
          const hLabel = truncateCanvasText(ctx, `時間有給 ${formatHoursNum(item.hLeaveCell)}h`, innerW - 16, 16);
          ctx.fillText(hLabel, x + cellPad + 8, cursorY + 13);
          cursorY += pillH + itemGap;
        }

        // 行事予定ピル（.cal-day-event-pill 準拠）
        if (item.eventText) {
          drawCanvasRoundedRect(
            ctx, x + cellPad, cursorY, innerW, pillH, pillH / 2, colors.event.bg, colors.event.border, 1
          );
          ctx.fillStyle = colors.event.fg;
          ctx.font = `600 10px ${fontSans}`;
          const evLabel = truncateCanvasText(ctx, item.eventText, innerW - 16, 14);
          ctx.fillText(evLabel, x + cellPad + 8, cursorY + 13);
          cursorY += pillH + itemGap;
        }

        // メモインジケーター（.cal-memo-indicator 準拠）
        if (item.memoText) {
          drawCanvasRoundedRect(ctx, x + cellPad, cursorY, innerW, pillH, 6, colors.memo.bg, null, 0);
          drawCanvasMemoIcon(ctx, x + cellPad + 6, cursorY + 4.5, colors.memo.fg);
          ctx.fillStyle = colors.memo.fg;
          ctx.font = `500 10px ${fontSans}`;
          const memoLabel = truncateCanvasText(ctx, item.memoText, innerW - 24, 12);
          ctx.fillText(memoLabel, x + cellPad + 18, cursorY + 13);
        }
      }

      if (canAlpha) {
        ctx.restore();
      }
    }

    function renderMonthlyCalendarCanvas(year, month) {
      const plCfg = AppState.calendar.paidLeaveConfig;
      const hpd = clampHalfHour(plCfg && plCfg.hoursPerDay, 8, 1, 24);
      const colors = CALENDAR_CANVAS_COLORS;
      const fontSans = "-apple-system, BlinkMacSystemFont, 'Hiragino Sans', 'SF Pro Text', sans-serif";
      const fontMono = "ui-monospace, Menlo, Monaco, monospace";

      const layout = computeCalendarCanvasLayout(year, month, hpd);
      const { rows, slotItems, rowHeights, cellPad, itemGap, pillH, headerDateH, metrics } = layout;

      const scale = 2;
      const width = 1080;
      const pad = 24;
      const headerH = 72;
      const dowH = 34;
      const gridWidth = width - pad * 2;
      const colW = gridWidth / 7;
      const gridBodyH = rowHeights.reduce((acc, h) => acc + h, 0);
      const gridTotalH = dowH + gridBodyH;
      const height = headerH + gridTotalH + pad;

      const canvas = document.createElement("canvas");
      canvas.width = width * scale;
      canvas.height = height * scale;
      const ctx = canvas.getContext("2d");
      if (!ctx) return null;
      ctx.scale(scale, scale);

      // 共有用に常にライト背景（白ベース）で描画
      ctx.fillStyle = colors.windowBg;
      ctx.fillRect(0, 0, width, height);

      drawCalendarCanvasHeader(ctx, width, pad, year, month, hpd, metrics, fontSans);

      // カレンダー外枠（.calendar-frame 準拠：角丸14px）
      const gridTop = headerH;
      const frameRadius = 14;
      const canClipFrame = Boolean(
        typeof ctx.save === "function" &&
        typeof ctx.restore === "function" &&
        typeof ctx.clip === "function" &&
        typeof ctx.beginPath === "function" &&
        typeof ctx.quadraticCurveTo === "function"
      );
      if (canClipFrame) {
        ctx.save();
        traceCanvasRoundedRect(ctx, pad, gridTop, gridWidth, gridTotalH, frameRadius);
        ctx.clip();
      }

      // 曜日ヘッダー（.calendar-header-row 準拠）
      const dowNames = ["日", "月", "火", "水", "木", "金", "土"];
      ctx.fillStyle = colors.headerBg;
      ctx.fillRect(pad, gridTop, gridWidth, dowH);

      dowNames.forEach((name, i) => {
        ctx.fillStyle = i === 0 ? colors.sun : (i === 6 ? colors.sat : colors.labelSecondary);
        ctx.font = `600 12px ${fontSans}`;
        ctx.textAlign = "center";
        ctx.fillText(name, pad + i * colW + colW / 2, gridTop + 21);
      });
      ctx.textAlign = "left";

      // 曜日ヘッダー下線
      if (typeof ctx.beginPath === "function" && typeof ctx.moveTo === "function" && typeof ctx.lineTo === "function" && typeof ctx.stroke === "function") {
        ctx.strokeStyle = colors.separator;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(pad, gridTop + dowH);
        ctx.lineTo(pad + gridWidth, gridTop + dowH);
        ctx.stroke();
      }

      // 行ごとの開始Y座標を計算して各セルを描画
      const rowTops = [];
      let curY = gridTop + dowH;
      for (let r = 0; r < rows; r++) {
        rowTops.push(curY);
        curY += rowHeights[r];
      }

      for (let i = 0; i < slotItems.length; i++) {
        const item = slotItems[i];
        drawCalendarCanvasCell(ctx, item, {
          x: pad + item.c * colW,
          y: rowTops[item.r],
          colW,
          cellH: rowHeights[item.r],
          cellPad,
          headerDateH,
          itemGap,
          pillH,
          fontSans,
          fontMono,
        });
      }

      if (canClipFrame) {
        ctx.restore();
      }

      // 外枠の角丸ボーダーを最後に描画
      drawCanvasRoundedRect(ctx, pad, gridTop, gridWidth, gridTotalH, frameRadius, null, colors.separator, 1);

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
