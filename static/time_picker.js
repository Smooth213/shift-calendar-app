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
      const shifts = AppState.analysis.shifts;
      if (Number.isNaN(idx) || !field || !shifts || !shifts[idx]) return;
      const prevVal = String(shifts[idx][field] || "");
      const norm = normalizeTimeInputValue(inputEl.value, true);
      if (norm === null) {
        inputEl.value = prevVal;
        return;
      }
      inputEl.value = norm;
      if (norm === prevVal) return;
      if (typeof AppHooks.onShiftTableTimeCommitted === "function") {
        AppHooks.onShiftTableTimeCommitted(idx, field, norm);
      } else {
        shifts[idx][field] = norm;
      }
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
