(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SheetModel = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function selectionInOrder(items, selectedIds) {
    const selected = new Set(selectedIds);
    return items.filter(item => selected.has(item.id)).map(item => item.id);
  }

  function copy(value) {
    if (Array.isArray(value)) return value.map(copy);
    if (value && typeof value === 'object') {
      return Object.fromEntries(Object.entries(value).map(([key, entry]) => [key, copy(entry)]));
    }
    return value;
  }

  function restoreDraft(items, draft = {}) {
    const selectedPaths = Array.isArray(draft.sources) ? draft.sources : items.map(item => item.path);
    const savedOrder = Array.isArray(draft.allSources) ? draft.allSources : selectedPaths;
    const rank = new Map();
    savedOrder.forEach((path, index) => { if (!rank.has(path)) rank.set(path, index); });
    const sorted = items.slice().sort((a, b) => (rank.get(a.path) ?? Infinity) - (rank.get(b.path) ?? Infinity));
    const selected = new Set(selectedPaths);
    const order = sorted.filter(item => selected.has(item.path)).map(item => item.id);
    const byPath = new Map(sorted.map(item => [item.path, item]));
    const frames = {};
    for (const item of sorted) {
      if (draft.frameOptions && Object.prototype.hasOwnProperty.call(draft.frameOptions, item.path)) {
        frames[item.id] = copy(draft.frameOptions[item.path]);
      }
    }
    const active = byPath.get(draft.activePath)?.id ?? order[0] ?? sorted[0]?.id ?? null;
    const legacyBackground = draft.config?.background?.sourceIndex;
    let backgroundSource;
    if (legacyBackground === 'custom' || draft.backgroundPath === 'custom') backgroundSource = 'custom';
    else if (byPath.has(draft.backgroundPath)) backgroundSource = byPath.get(draft.backgroundPath).id;
    else {
      const oldId = typeof legacyBackground === 'number' ? legacyBackground : NaN;
      backgroundSource = sorted.some(item => item.id === oldId) ? oldId : order[0] ?? null;
    }
    return {items: sorted, order, frames, active, backgroundSource};
  }

  function numberInRange(value, name, min, max = Infinity) {
    const number = Number(value);
    if (!Number.isFinite(number) || number < min || number > max) throw new RangeError(`${name} is out of range`);
    return number;
  }

  // Pillow uses Python's round(), which rounds exact halves to the even integer.
  function roundEven(value) {
    const lower = Math.floor(value), fraction = value - lower;
    return fraction === .5 ? lower + lower % 2 : Math.round(value);
  }

  function normalizeHex(value) {
    const text=String(value).trim().replace(/^#/, '');
    if (/^[0-9a-f]{3}$/i.test(text)) return '#'+[...text].map(ch=>ch+ch).join('').toLowerCase();
    return /^[0-9a-f]{6}$/i.test(text) ? '#'+text.toLowerCase() : null;
  }

  function frameRotation(width, height, override = {}) {
    return override.rotation ?? (height > width ? 90 : 0);
  }

  function cropGeometry(sourceWidth, sourceHeight, targetWidth, targetHeight, fit = 'cover', zoom = 1, cx = .5, cy = .5) {
    const sw = numberInRange(sourceWidth, 'source width', Number.MIN_VALUE);
    const sh = numberInRange(sourceHeight, 'source height', Number.MIN_VALUE);
    const tw = numberInRange(targetWidth, 'target width', 1);
    const th = numberInRange(targetHeight, 'target height', 1);
    zoom = numberInRange(zoom, 'zoom', 1, 8);
    cx = numberInRange(cx, 'center x', 0, 1);
    cy = numberInRange(cy, 'center y', 0, 1);
    if (fit !== 'cover' && fit !== 'contain') throw new RangeError('fit must be cover or contain');

    const ratio = tw / th;
    let width = sw, height = sh;
    if (fit === 'cover') {
      if (sw / sh > ratio) width = sh * ratio;
      else height = sw / ratio;
    }
    width /= zoom;
    height /= zoom;
    let sx = Math.min(Math.max(0, cx * sw - width / 2), sw - width);
    let sy = Math.min(Math.max(0, cy * sh - height / 2), sh - height);
    if (fit === 'cover') return {sx, sy, sw: width, sh: height, dx: 0, dy: 0, dw: tw, dh: th};

    const right = roundEven(sx + width), bottom = roundEven(sy + height);
    sx = roundEven(sx);
    sy = roundEven(sy);
    width = right - sx;
    height = bottom - sy;
    if (width <= 0 || height <= 0) throw new RangeError('zoom leaves no source pixels');
    let dw = tw, dh = th;
    if (width / height > ratio) dh = roundEven(height / width * tw);
    else if (width / height < ratio) dw = roundEven(width / height * th);
    if (dw <= 0 || dh <= 0) throw new RangeError('target is too small for the source ratio');
    return {sx, sy, sw: width, sh: height, dx: Math.floor((tw - dw) / 2), dy: Math.floor((th - dh) / 2), dw, dh};
  }

  return Object.freeze({selectionInOrder, restoreDraft, normalizeHex, frameRotation, cropGeometry});
});
