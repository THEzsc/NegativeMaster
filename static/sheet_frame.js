/* A responsive composition view over the same positive pixels and crop model. */
(() => {
  const canvas = $('frame-preview-canvas');
  const area = canvas.parentElement;
  const images = new Map();
  let raf = 0;
  let geometry = null;
  let drag = null;
  let rotated = null;

  function setView(view, switchPane = true) {
    finishDrag();
    if (view === 'frame' && (!state.items.length || state.preparing)) return;
    state.view = view;
    document.querySelector('.sheet-stage').dataset.view = view;
    $('view-sheet').setAttribute('aria-pressed', String(view === 'sheet'));
    $('view-frame').setAttribute('aria-pressed', String(view === 'frame'));
    $('frame-view').hidden = view !== 'frame';
    $('sheet-preview').hidden = view === 'frame' || !state.previewUrl || !state.order.length;
    $('empty-sheet').hidden = view === 'frame' || (!!state.previewUrl && !!state.order.length);
    if (view === 'frame' && switchPane) selectPane('frame');
    syncZoom();
    draw();
  }

  function loadImage(item) {
    const key = `${state.job}/${item.id}`;
    if (images.has(key)) return images.get(key);
    const image = new Image();
    const entry = { image, ready: false, failed: false };
    images.set(key, entry);
    if (images.size > 8) images.delete(images.keys().next().value);
    image.onload = () => { entry.ready = true; draw(); };
    image.onerror = () => { entry.failed = true; draw(); };
    image.src = item.thumb || `/api/sheet/thumb/${state.job}/${item.id}`;
    return entry;
  }

  function draw() {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(paint);
  }

  function paint() {
    if (state.view !== 'frame') return;
    const item = state.items.find(item => item.id === state.active);
    if (!item) return;
    const entry = loadImage(item);
    $('frame-loading').hidden = entry.ready;
    $('frame-loading').textContent = entry.failed ? '照片读取失败，请重新载入这一卷' : '正在读取照片…';
    if (!entry.ready) {
      canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
      geometry = null;
      return;
    }
    const f = frameConfig();
    const rotation = (SheetModel.frameRotation(item.width || entry.image.naturalWidth,
      item.height || entry.image.naturalHeight, f) % 360 + 360) % 360;
    const key = `${state.job}/${item.id}/${rotation}`;
    if (rotated?.key !== key) {
      const image = entry.image;
      const swap = rotation === 90 || rotation === 270;
      const surface = document.createElement('canvas');
      surface.width = swap ? image.naturalHeight : image.naturalWidth;
      surface.height = swap ? image.naturalWidth : image.naturalHeight;
      const ctx = surface.getContext('2d');
      ctx.translate(surface.width / 2, surface.height / 2);
      ctx.rotate(rotation * Math.PI / 180);
      ctx.drawImage(image, -image.naturalWidth / 2, -image.naturalHeight / 2);
      rotated = { key, surface };
    }
    const aspect = { '3:2': 1.5, '4:3': 4 / 3, '1:1': 1, original: 1.5 }[state.config.ratio] || 1.5;
    canvas.width = 1200;
    canvas.height = Math.round(1200 / aspect);
    const displayWidth = Math.max(1, Math.min(area.clientWidth, area.clientHeight * aspect));
    canvas.style.width = `${displayWidth}px`;
    canvas.style.height = `${displayWidth / aspect}px`;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = state.config.strip.color;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    // Strip padding is specified at the renderer's logical 2400 px sheet width.
    const aperture = (2400 - 2 * state.config.margin) / state.config.columns - state.config.strip.frameGap;
    const padding = Math.max(0, Math.round(1200 * state.config.strip.padding / aperture));
    const fit = f.fit || (state.config.ratio === 'original' ? 'contain' : state.config.strip.fit);
    const crop = f.crop || { x: .5, y: .5, scale: 1 };
    geometry = SheetModel.cropGeometry(rotated.surface.width, rotated.surface.height,
      Math.max(1, canvas.width - padding * 2), Math.max(1, canvas.height - padding * 2),
      fit, crop.scale || 1, crop.x ?? .5, crop.y ?? .5);
    ctx.imageSmoothingQuality = 'high';
    const g = geometry;
    ctx.drawImage(rotated.surface, g.sx, g.sy, g.sw, g.sh, g.dx + padding, g.dy + padding, g.dw, g.dh);
    if ($('frame-grid').checked) {
      ctx.strokeStyle = 'rgba(255,255,255,.5)';
      ctx.lineWidth = Math.max(1, 1200 / displayWidth);
      ctx.setLineDash([5 * ctx.lineWidth, 5 * ctx.lineWidth]);
      for (const n of [1, 2]) {
        ctx.beginPath();ctx.moveTo(canvas.width * n / 3, 0);ctx.lineTo(canvas.width * n / 3, canvas.height);ctx.stroke();
        ctx.beginPath();ctx.moveTo(0, canvas.height * n / 3);ctx.lineTo(canvas.width, canvas.height * n / 3);ctx.stroke();
      }
    }
    const canPan = g.sw < rotated.surface.width - 1 || g.sh < rotated.surface.height - 1;
    canvas.classList.toggle('can-pan', canPan);
    canvas.setAttribute('aria-label', `${item.name}，旋转 ${rotation} 度，放大 ${Number(crop.scale || 1).toFixed(2)} 倍`);
    const orientationHint = f.rotation == null && rotation === 90 ? '竖构图已默认横放，可用左转 / 右转调整。' : '';
    $('frame-edit-hint').textContent = orientationHint + (canPan ? '在画面上拖动构图，或用下方滑块精调。参考线不会导出。' : '放大或选择“铺满窗口”后，可在画面上拖动构图。');
  }

  function step(delta) {
    const index = state.items.findIndex(item => item.id === state.active);
    const next = state.items[index + delta];
    if (next) activateFrame(next.id);
  }

  function finishDrag(event) {
    if (!drag || (event?.pointerId !== undefined && event.pointerId !== drag.pointer)) return;
    const ended = drag;drag = null;
    canvas.classList.remove('is-dragging');
    if (canvas.hasPointerCapture(ended.pointer)) canvas.releasePointerCapture(ended.pointer);
    if (state.job === ended.job && state.active === ended.active) commit(ended.before);
  }
  canvas.addEventListener('pointerdown', event => {
    if (drag || !event.isPrimary || event.button !== 0 || state.preparing || !geometry || !canvas.classList.contains('can-pan')) return;
    event.preventDefault();
    const crop = frameConfig().crop || { x: .5, y: .5, scale: 1 };
    drag = { pointer: event.pointerId, x: event.clientX, y: event.clientY, cx: crop.x ?? .5, cy: crop.y ?? .5,
      before: snapshot(), job: state.job, active: state.active, geometry: { ...geometry }, rect: canvas.getBoundingClientRect() };
    canvas.setPointerCapture(event.pointerId);canvas.classList.add('is-dragging');
  });
  canvas.addEventListener('pointermove', event => {
    if (!drag || drag.pointer !== event.pointerId) return;
    if (state.preparing || state.job !== drag.job || state.active !== drag.active) { finishDrag(); return; }
    const g = drag.geometry;
    const f = state.frames[state.active] ??= {};
    f.crop ??= { x: .5, y: .5, scale: 1 };
    f.crop.x = Math.max(0, Math.min(1, drag.cx - (event.clientX - drag.x) / drag.rect.width * canvas.width / g.dw * g.sw / rotated.surface.width));
    f.crop.y = Math.max(0, Math.min(1, drag.cy - (event.clientY - drag.y) / drag.rect.height * canvas.height / g.dh * g.sh / rotated.surface.height));
    syncFrameControls();draw();queuePreview();
  });
  for (const event of ['pointerup', 'pointercancel', 'lostpointercapture']) canvas.addEventListener(event, finishDrag);
  window.addEventListener('blur', () => finishDrag());
  new ResizeObserver(draw).observe(area);
  $('view-sheet').onclick = () => setView('sheet');
  $('view-frame').onclick = () => setView('frame');
  $('frame-prev').onclick = () => step(-1);
  $('frame-next').onclick = () => step(1);
  $('frame-grid').onchange = draw;
  window.SheetFrame = { draw, setView };
})();
