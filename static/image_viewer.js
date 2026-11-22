    // =========================================================================
    // Image Viewer Logic (Zoom, Pan, Cell Highlight & Coordinate Hit-Testing)
    // =========================================================================
    const btnToggleViewer = document.getElementById("btn-toggle-viewer");
    const viewerWrapper = document.getElementById("viewer-wrapper");
    const viewerCanvas = document.getElementById("viewer-canvas");
    const viewerStage = document.getElementById("viewer-stage");
    const compareImg = document.getElementById("compare-image");
    const zoomText = document.getElementById("zoom-text");
    const viewerHighlightBox = document.getElementById("viewer-highlight-box");

    function updateViewerTransform() {
      viewerStage.style.transform = `translate(${AppState.viewer.panX}px, ${AppState.viewer.panY}px) scale(${AppState.viewer.scale})`;
      zoomText.textContent = `${Math.round(AppState.viewer.scale * 100)}%`;
    }

    function fitViewerToScreen() {
      if (!compareImg.naturalWidth) return;
      const vWidth = viewerCanvas.clientWidth;
      const vHeight = viewerCanvas.clientHeight;
      const imgWidth = compareImg.naturalWidth;
      const imgHeight = compareImg.naturalHeight;

      const scaleX = vWidth / imgWidth;
      const scaleY = vHeight / imgHeight;
      const nextScale = Math.min(scaleX, scaleY, 1.0);
      AppState.viewer.scale = nextScale;
      AppState.viewer.panX = (vWidth - imgWidth * nextScale) / 2;
      AppState.viewer.panY = (vHeight - imgHeight * nextScale) / 2;
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
        const targetScale = Math.min(Math.max(AppState.viewer.scale, 1.35), 2.5);

        const centerX = xmin + boxW / 2;
        const centerY = ymin + boxH / 2;

        AppState.viewer.panX = cW / 2 - centerX * targetScale;
        AppState.viewer.panY = cH / 2 - centerY * targetScale;
        AppState.viewer.scale = targetScale;

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

      const curScale = AppState.viewer.scale;
      const newScale = Math.min(Math.max(curScale * factor, 0.15), 8.0);
      AppState.viewer.panX = centerX - (centerX - AppState.viewer.panX) * (newScale / curScale);
      AppState.viewer.panY = centerY - (centerY - AppState.viewer.panY) * (newScale / curScale);
      AppState.viewer.scale = newScale;
      updateViewerTransform();
    }

    document.getElementById("btn-zoom-in").addEventListener("click", () => applyZoom(1.3));
    document.getElementById("btn-zoom-out").addEventListener("click", () => applyZoom(0.77));
    document.getElementById("btn-zoom-fit").addEventListener("click", fitViewerToScreen);
    document.getElementById("btn-zoom-reset").addEventListener("click", () => {
      AppState.viewer.scale = 1.0;
      AppState.viewer.panX = (viewerCanvas.clientWidth - compareImg.naturalWidth) / 2;
      AppState.viewer.panY = 20;
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
      const shifts = AppState.analysis.shifts;
      if (!shifts || !shifts.length || !compareImg.naturalWidth || !compareImg.naturalHeight) {
        return -1;
      }
      const imgX = (mouseX - AppState.viewer.panX) / AppState.viewer.scale;
      const imgY = (mouseY - AppState.viewer.panY) / AppState.viewer.scale;
      const nx = (imgX / compareImg.naturalWidth) * 1000;
      const ny = (imgY / compareImg.naturalHeight) * 1000;

      for (let i = 0; i < shifts.length; i++) {
        const b = shifts[i].box_2d;
        if (!b || !Array.isArray(b) || b.length < 4) continue;
        const [ymin, xmin, ymax, xmax] = b;
        if (ny >= ymin && ny <= ymax && nx >= xmin && nx <= xmax) {
          return i;
        }
      }
      return -1;
    }

    viewerCanvas.addEventListener("mousedown", (e) => {
      AppState.viewer.isDragging = true;
      AppState.viewer.dragStartX = e.clientX - AppState.viewer.panX;
      AppState.viewer.dragStartY = e.clientY - AppState.viewer.panY;
      AppState.viewer.dragOriginX = e.clientX;
      AppState.viewer.dragOriginY = e.clientY;
    });

    window.addEventListener("mousemove", (e) => {
      if (!AppState.viewer.isDragging) return;
      AppState.viewer.panX = e.clientX - AppState.viewer.dragStartX;
      AppState.viewer.panY = e.clientY - AppState.viewer.dragStartY;
      updateViewerTransform();
    });

    window.addEventListener("mouseup", (e) => {
      if (!AppState.viewer.isDragging) return;
      AppState.viewer.isDragging = false;
      const moved = Math.hypot(e.clientX - AppState.viewer.dragOriginX, e.clientY - AppState.viewer.dragOriginY);
      if (moved < 5 && viewerCanvas.contains(e.target)) {
        const rect = viewerCanvas.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;
        const hitIdx = findShiftIdxAtViewerPoint(mouseX, mouseY);
        if (hitIdx !== -1 && typeof AppHooks.selectCalendarDate === "function") {
          AppHooks.selectCalendarDate(hitIdx, { scrollTable: true, debounceImage: false });
        }
      }
    });

    viewerCanvas.addEventListener("dblclick", (e) => {
      const rect = viewerCanvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      if (AppState.viewer.scale < 1.5) applyZoom(2.2 / AppState.viewer.scale, mouseX, mouseY);
      else fitViewerToScreen();
    });
