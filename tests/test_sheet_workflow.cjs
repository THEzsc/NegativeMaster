'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const SheetModel = require('../static/sheet_model.js');

// Exercise the shipped event handlers, network requests, and visible DOM state.
// Delayed responses intentionally ignore AbortSignal: a result already in flight
// must still be rejected by the application after selection or source changes.
class Element {
  constructor(tag = 'div', doc) {
    this.tagName = tag.toUpperCase(); this.doc = doc; this.children = [];
    this.dataset = {}; this.style = {}; this.attributes = {}; this.listeners = {};
    this.value = ''; this.textContent = ''; this.hidden = false; this.disabled = false;
    this.className = ''; this.scrollTop = 0; this.clientWidth = 800; this.files = [];
    const classes = new Set();
    this.classList = {
      add: (...names) => names.forEach(name => classes.add(name)),
      remove: (...names) => names.forEach(name => classes.delete(name)),
      contains: name => classes.has(name),
      toggle: (name, force) => {
        const present = force === undefined ? !classes.has(name) : force;
        present ? classes.add(name) : classes.delete(name); return present;
      },
    };
  }
  append(...children) { for (const child of children) { child.parentElement = this; this.children.push(child); } }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  checkValidity() {
    if (this.type !== 'number') return true;
    const number = Number(this.value);
    return this.value === '' || (Number.isFinite(number) && (this.min === undefined || number >= this.min) && (this.max === undefined || number <= this.max));
  }
  addEventListener(name, listener) { (this.listeners[name] ??= []).push(listener); }
  dispatch(name, fields = {}) {
    const event = {type: name, target: this, preventDefault() {}, stopPropagation() {}, ...fields};
    const results = (this.listeners[name] || []).map(listener => listener(event));
    if (this[`on${name}`]) results.push(this[`on${name}`](event));
    return Promise.all(results);
  }
  click() { if (!this.disabled) return this.dispatch('click'); }
  focus() { this.doc.activeElement = this; }
  closest(selector) {
    if (selector === '.frame-item' && this.className.split(' ').includes('frame-item')) return this;
    return this.parentElement?.closest(selector) ?? null;
  }
  querySelector(selector) {
    const all = this.children.flatMap(child => [child, ...child.descendants()]);
    return all.find(child => selector === 'input' ? child.tagName === 'INPUT'
      : selector.startsWith('[data-id=') ? child.dataset.id === selector.match(/"([^"]+)"/)[1]
      : child.tagName.toLowerCase() === selector) ?? null;
  }
  descendants() { return this.children.flatMap(child => [child, ...child.descendants()]); }
  remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this); }
  getContext() {
    return this.context2d ??= {clearRect() {}, translate() {}, rotate() {}, drawImage() {}, fillRect() {}, setLineDash() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}};
  }
  getBoundingClientRect() { return {width: parseFloat(this.style.width) || 600, height: parseFloat(this.style.height) || 400}; }
  setPointerCapture(id) { this.capturedPointer = id; }
  hasPointerCapture(id) { return this.capturedPointer === id; }
  releasePointerCapture(id) { if (this.capturedPointer === id) { this.capturedPointer = null; this.dispatch('lostpointercapture', {pointerId: id}); } }
}

function storage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key)};
}

function harness({draft, withFrame = false, withUI = false} = {}) {
  const elements = new Map(), documentListeners = {};
  const document = {
    getElementById(id) {
      if (!elements.has(id)) { const el = new Element('div', document); el.id = id; elements.set(id, el); }
      return elements.get(id);
    },
    createElement: tag => new Element(tag, document),
    addEventListener(name, listener) { (documentListeners[name] ??= []).push(listener); },
    querySelectorAll(selector) {
      if (selector === '[data-config]') return [columns];
      if (selector === '.frame-item') return this.getElementById('frame-list').children;
      return [];
    },
    querySelector: selector => ['.inspector-content','.sheet-stage','.sheet-inspector'].includes(selector) ? document.getElementById(selector.slice(1)) : null,
  };
  document.body = new Element('body', document); document.activeElement = document.body;
  const columns = new Element('input', document); columns.type = 'number'; columns.min = 2; columns.max = 12; columns.dataset.config = 'columns';
  document.getElementById('prepare-progress').append(new Element('i', document));
  document.getElementById('empty-sheet').append(new Element('h1', document), new Element('p', document));
  document.getElementById('sheet-preview').hidden = true;
  document.getElementById('export-sheet').firstChild = new Element('span', document);
  const frameArea = new Element('div', document); frameArea.clientWidth = 600; frameArea.clientHeight = 400;
  frameArea.append(document.getElementById('frame-preview-canvas'));
  const windowListeners = {};
  const window = {innerWidth: 1440, addEventListener: (name, listener) => windowListeners[name] = listener};
  const requests = [], objectUrls = [], timers = new Map(), frames = new Map(); let timerId = 0, frameId = 0, clock = 0;
  const localStorage = storage(draft ? {'nm.sheet.draft': JSON.stringify(draft)} : {});
  class BrowserURL extends URL {}
  BrowserURL.createObjectURL = blob => { const url = `blob:${blob.label}`; objectUrls.push(url); return url; };
  BrowserURL.revokeObjectURL = () => {};
  const context = vm.createContext({
    window, document, localStorage, sessionStorage: storage(), SheetModel, AbortController, URL: BrowserURL,
    FormData, Blob, console,
    Image: class { constructor() { this.naturalWidth = 600; this.naturalHeight = 400; } set src(value) { this.source = value; queueMicrotask(() => this.onload?.()); } },
    ResizeObserver: class { observe() {} },
    requestAnimationFrame: callback => { const id = ++frameId; frames.set(id, callback); return id; },
    cancelAnimationFrame: id => frames.delete(id),
    setTimeout: (callback, ms) => { const id = ++timerId; timers.set(id, {callback, at: clock + ms}); return id; },
    clearTimeout: id => timers.delete(id),
    fetch: (url, options = {}) => new Promise((resolve, reject) => {
      requests.push({url, options, body: typeof options.body === 'string' ? JSON.parse(options.body) : options.body, resolve, reject, done: false});
    }),
  });
  vm.runInContext(fs.readFileSync(require.resolve('../static/sheet.js'), 'utf8'), context, {filename: 'sheet.js'});
  if (withFrame) vm.runInContext(fs.readFileSync(require.resolve('../static/sheet_frame.js'), 'utf8'), context, {filename: 'sheet_frame.js'});
  if (withUI) vm.runInContext(fs.readFileSync(require.resolve('../static/sheet_ui.js'), 'utf8'), context, {filename: 'sheet_ui.js'});
  const flush = async () => { await new Promise(resolve => setImmediate(resolve)); };
  function pending(url) { return requests.filter(request => !request.done && request.url === url); }
  function reply(request, data, ok = true) {
    assert.ok(request, 'expected a pending request'); request.done = true;
    request.resolve({ok, status: ok ? 200 : 400, headers: {get: () => 'application/json'}, json: async () => data});
  }
  function image(request, label) {
    assert.ok(request, 'expected a pending preview request'); request.done = true;
    request.resolve({ok: true, headers: {get: name => ({'content-type': 'image/png', 'X-Sheet-Width': '4800', 'X-Sheet-Height': '3200'})[name]}, blob: async () => ({label})});
  }
  async function advance(ms) {
    clock += ms;
    for (const [id, timer] of [...timers]) if (timer.at <= clock) { timers.delete(id); timer.callback(); }
    await flush();
  }
  async function paint() { const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(callback => callback()); await flush(); }
  const ready = (job, paths = ['/roll/a.jpg', '/roll/b.jpg'], extra = {}) => ({
    ok: true, state: 'ready', directory: '/roll', label: 'Test roll', warnings: [],
    items: paths.map((path, id) => ({id, path, name: path.split('/').at(-1), source: 'import', thumb: `/thumb/${job}/${id}`})), ...extra,
  });
  async function load({job = 'initial', paths, warnings = []} = {}) {
    const finished = context.prepare({paths: paths || ['/roll/a.jpg', '/roll/b.jpg']});
    reply(pending('/api/sheet/prepare')[0], {ok: true, job}); await flush();
    reply(pending(`/api/sheet/job/${job}`)[0], ready(job, paths, {warnings})); await flush();
    const request = pending('/api/sheet/preview')[0]; if (request) image(request, job);
    await finished; await flush();
  }
  return {context, window, document, resize: width => { window.innerWidth = width; windowListeners.resize?.(); }, key: fields => { for (const listener of documentListeners.keydown || []) listener({preventDefault() {}, ...fields}); }, el: id => document.getElementById(id), columns, pending, requests, reply, image, flush, advance, paint, ready, load, objectUrls, localStorage,
    start: () => windowListeners.DOMContentLoaded()};
}

test('clearing selection cannot be undone by an older preview response', async () => {
  const h = harness(); await h.load();
  const refreshing = h.el('refresh-preview').click();
  await h.flush(); const old = h.pending('/api/sheet/preview')[0];
  await h.el('select-none').click();
  assert.equal(h.el('sheet-preview').hidden, true);
  assert.equal(h.el('export-sheet').disabled, true);
  assert.equal(h.el('export-dimensions').textContent, '尚未选择照片');
  h.image(old, 'obsolete'); await refreshing; await h.flush();
  assert.equal(h.el('sheet-preview').hidden, true);
  assert.equal(h.el('empty-sheet').hidden, false);
  assert.ok(!h.objectUrls.includes('blob:obsolete'));
  assert.equal(h.el('sheet-status').textContent, '尚未选择照片');
});

test('consecutive edits coalesce while an in-flight result cannot publish obsolete settings', async () => {
  const h = harness(); await h.load();
  const refreshing = h.el('refresh-preview').click(); await h.flush();
  const old = h.pending('/api/sheet/preview')[0];
  h.columns.value = '2'; await h.columns.dispatch('input');
  h.columns.value = '4'; await h.columns.dispatch('input');
  await h.advance(220);
  assert.equal(h.pending('/api/sheet/preview').length, 1, 'do not dispatch overlapping render requests');
  h.image(old, 'old-six-columns'); await refreshing; await h.flush();
  assert.ok(!h.objectUrls.includes('blob:old-six-columns'));
  await h.advance(60);
  const latest = h.pending('/api/sheet/preview')[0];
  assert.equal(latest.body.config.columns, 4);
  h.image(latest, 'latest-four-columns'); await h.flush();
  assert.equal(h.el('sheet-preview').src, 'blob:latest-four-columns');
  assert.equal(h.el('sheet-preview').hidden, false);
  assert.equal(h.pending('/api/sheet/preview').length, 0);
});

test('failure from prepare A cannot end prepare B or enable exporting the old roll', async () => {
  const h = harness(); await h.load();
  const preparingA = h.context.prepare({directory: '/roll-a'});
  const requestA = h.pending('/api/sheet/prepare')[0];
  const preparingB = h.context.prepare({directory: '/roll-b'});
  const requestB = h.pending('/api/sheet/prepare')[1];
  requestA.done = true; requestA.reject(new Error('A failed late')); await preparingA;
  assert.equal(h.el('prepare-progress').hidden, false);
  assert.equal(h.el('export-sheet').disabled, true);
  assert.equal(h.el('save-project').disabled, true);
  assert.ok(!h.el('sheet-status').textContent.includes('A failed late'));
  h.reply(requestB, {ok: true, job: 'b'}); await h.flush();
  h.reply(h.pending('/api/sheet/job/b')[0], h.ready('b', ['/roll-b/1.jpg'], {directory: '/roll-b', label: 'B'}));
  await h.flush(); h.image(h.pending('/api/sheet/preview')[0], 'b'); await preparingB;
  assert.equal(h.el('prepare-progress').hidden, true);
  assert.equal(h.el('export-sheet').disabled, false);
  assert.equal(h.el('source-label').textContent, '/roll-b');
  assert.equal(h.el('sheet-preview').src, 'blob:b');
});

test('an expired imported draft reloads its original sources rather than the first startup roll', async () => {
  const draft = {job: 'expired', allSources: ['/upload/b.jpg', '/upload/a.jpg'], sources: ['/upload/a.jpg'],
    activePath: '/upload/a.jpg', backgroundPath: '/upload/a.jpg', directory: '/wrong-fallback-roll', positiveOnly: true,
    frameOptions: {'/upload/a.jpg': {rotation: 90}}, config: {columns: 4}};
  const h = harness({draft}), starting = h.start();
  h.reply(h.pending('/api/sheet/catalog')[0], {ok: true, stocks: []}); await h.flush();
  h.reply(h.pending('/api/sheet/job/expired')[0], {ok: false, error: 'expired'}, false); await h.flush();
  const prepare = h.pending('/api/sheet/prepare')[0];
  assert.deepEqual(prepare.body, {paths: ['/upload/b.jpg', '/upload/a.jpg'], positiveOnly: true});
  assert.equal(h.requests.some(request => request.url === '/api/list'), false);
  h.reply(prepare, {ok: true, job: 'restored'}); await h.flush();
  h.reply(h.pending('/api/sheet/job/restored')[0], h.ready('restored', ['/upload/a.jpg', '/upload/b.jpg'])); await h.flush();
  const preview = h.pending('/api/sheet/preview')[0];
  assert.deepEqual(preview.body.order, [0]);
  assert.deepEqual(preview.body.config.frameOverrides, [{rotation: 90}]);
  h.image(preview, 'restored'); await starting;
  const saved = JSON.parse(h.localStorage.getItem('nm.sheet.draft'));
  assert.deepEqual(saved.allSources, ['/upload/b.jpg', '/upload/a.jpg']);
  assert.deepEqual(saved.sources, ['/upload/a.jpg']);
  assert.equal(saved.backgroundPath, '/upload/a.jpg');
});

test('missing draft sources retain the recoverable draft instead of overwriting it with another roll', async () => {
  const draft = {job: 'expired', allSources: ['/missing/a.jpg'], sources: ['/missing/a.jpg'], directory: '/wrong-roll', positiveOnly: true};
  const h = harness({draft}), starting = h.start();
  h.reply(h.pending('/api/sheet/catalog')[0], {ok: true, stocks: []}); await h.flush();
  h.reply(h.pending('/api/sheet/job/expired')[0], {ok: false, error: 'expired'}, false); await h.flush();
  h.reply(h.pending('/api/sheet/prepare')[0], {ok: false, error: 'source unavailable'}, false); await starting;
  assert.deepEqual(JSON.parse(h.localStorage.getItem('nm.sheet.draft')), draft);
  assert.equal(h.requests.some(request => request.url === '/api/list'), false);
  assert.equal(h.el('export-sheet').disabled, true);
  assert.match(h.el('sheet-status').textContent, /source unavailable/);
});

test('partial recovery also protects an unselected photo and its saved frame edits', async () => {
  const draft = {job: 'expired', allSources: ['/saved/a.jpg', '/saved/b.jpg'], sources: ['/saved/a.jpg'],
    positiveOnly: true, frameOptions: {'/saved/b.jpg': {rotation: 180, crop: {x: .3, y: .7, scale: 2}}}};
  const h = harness({draft}), starting = h.start();
  h.reply(h.pending('/api/sheet/catalog')[0], {ok: true, stocks: []}); await h.flush();
  h.reply(h.pending('/api/sheet/job/expired')[0], {ok: false, error: 'expired'}, false); await h.flush();
  h.reply(h.pending('/api/sheet/prepare')[0], {ok: true, job: 'partial'}); await h.flush();
  h.reply(h.pending('/api/sheet/job/partial')[0], h.ready('partial', ['/saved/a.jpg'], {warnings: ['b.jpg is missing']}));
  await h.flush();
  // Finish an unexpected preview as well, so the failing regression reports data
  // loss instead of hanging when run against the old recovery implementation.
  const unexpectedPreview = h.pending('/api/sheet/preview')[0];
  if (unexpectedPreview) h.image(unexpectedPreview, 'partial');
  await starting;
  assert.deepEqual(JSON.parse(h.localStorage.getItem('nm.sheet.draft')), draft,
    'partial recovery must not overwrite the only copy of missing photos and edits');
  assert.equal(h.el('export-sheet').disabled, true);
  assert.match(h.el('sheet-status').textContent, /1/);
  assert.match(h.el('sheet-status').textContent, /原草稿.*保留/);
});

test('an older ready job cannot publish its warnings after a new prepare begins', async () => {
  const h = harness();
  const preparingA = h.context.prepare({directory: '/roll-a'});
  h.reply(h.pending('/api/sheet/prepare')[0], {ok: true, job: 'a'}); await h.flush();
  h.reply(h.pending('/api/sheet/job/a')[0], h.ready('a', undefined, {warnings: ['old roll warning']})); await h.flush();
  const oldPreview = h.pending('/api/sheet/preview')[0];
  const preparingB = h.context.prepare({directory: '/roll-b'});
  h.image(oldPreview, 'old-a'); await preparingA; await h.flush();
  assert.equal(h.el('prepare-progress').hidden, false);
  assert.ok(!h.el('sheet-status').textContent.includes('old roll warning'));
  h.reply(h.pending('/api/sheet/prepare')[0], {ok: false, error: 'B unavailable'}, false); await preparingB;
});

test('a custom background upload cannot attach itself to a different roll', async () => {
  const h = harness(); await h.load();
  h.el('background-input').files = [Object.assign(new Blob(['image bytes'], {type: 'image/png'}), {name: 'background.png'})];
  const uploading = h.el('background-input').dispatch('change'); await h.flush();
  const background = h.pending('/api/sheet/background')[0];
  const preparingB = h.context.prepare({directory: '/roll-b'});
  h.reply(background, {ok: true}); await uploading;
  assert.equal(h.el('background-file').textContent, '');
  h.reply(h.pending('/api/sheet/prepare')[0], {ok: true, job: 'b'}); await h.flush();
  h.reply(h.pending('/api/sheet/job/b')[0], h.ready('b', ['/roll-b/b.jpg'])); await h.flush();
  const preview = h.pending('/api/sheet/preview')[0];
  assert.notEqual(preview.body.config.background.sourceIndex, 'custom');
  h.image(preview, 'b'); await preparingB;
});

async function openZoomedFrame() {
  const h = harness({withFrame: true}); await h.load();
  await h.el('frame-list').children[0].click(); await h.paint(); await h.paint();
  h.el('frame-scale').value = '2'; await h.el('frame-scale').dispatch('input'); await h.el('frame-scale').dispatch('change'); await h.paint();
  assert.equal(h.el('frame-preview-canvas').classList.contains('can-pan'), true);
  return h;
}

test('several pointer moves make one undoable composition change', async () => {
  const h = await openZoomedFrame(), canvas = h.el('frame-preview-canvas');
  const before = h.el('frame-x').value;
  await canvas.dispatch('pointerdown', {pointerId: 4, isPrimary: true, button: 0, clientX: 300, clientY: 200});
  for (const x of [325, 350, 375]) await canvas.dispatch('pointermove', {pointerId: 4, clientX: x, clientY: 200});
  assert.ok(Number(h.el('frame-x').value) < Number(before), 'dragging right should move the crop center left');
  await canvas.dispatch('pointerup', {pointerId: 4});
  assert.equal(canvas.hasPointerCapture(4), false);
  assert.equal(canvas.classList.contains('is-dragging'), false);
  const changed = JSON.parse(h.localStorage.getItem('nm.sheet.draft')).frameOptions['/roll/a.jpg'].crop;
  assert.ok(changed.x < .5);
  await h.el('undo').click();
  assert.equal(Number(h.el('frame-x').value), .5);
  assert.equal(Number(h.el('frame-scale').value), 2, 'one undo reverts the whole gesture, retaining the previous zoom');
  await h.el('undo').click();
  assert.equal(Number(h.el('frame-scale').value), 1, 'no hidden intermediate drag steps remain in history');
});

test('pointer cancellation ends the gesture and later movement cannot change the frame', async () => {
  const h = await openZoomedFrame(), canvas = h.el('frame-preview-canvas');
  await canvas.dispatch('pointerdown', {pointerId: 8, isPrimary: true, button: 0, clientX: 300, clientY: 200});
  await canvas.dispatch('pointermove', {pointerId: 8, clientX: 350, clientY: 225});
  const canceledX = h.el('frame-x').value;
  await canvas.dispatch('pointercancel', {pointerId: 8});
  await canvas.dispatch('pointermove', {pointerId: 8, clientX: 550, clientY: 300});
  assert.equal(h.el('frame-x').value, canceledX);
  assert.equal(canvas.hasPointerCapture(8), false);
  assert.equal(canvas.classList.contains('is-dragging'), false);
  await h.el('undo').click();
  assert.equal(Number(h.el('frame-x').value), .5);
  assert.equal(Number(h.el('frame-y').value), .5);
  assert.equal(Number(h.el('frame-scale').value), 2);
});


test('a collapsed desktop rail can open as a narrow drawer and Escape restores the workbench', async () => {
  const h = harness({withUI: true});
  await h.el('toggle-frames').click();
  assert.equal(h.document.body.classList.contains('frames-hidden'), true);
  h.resize(390);
  await h.el('toggle-frames').click();
  assert.equal(h.el('frame-rail').attributes['aria-modal'], 'true');
  assert.equal(h.el('sheet-stage').inert, true);
  assert.equal(h.el('frame-backdrop').hidden, false);
  h.key({key:'Escape'});
  assert.equal(h.el('sheet-stage').inert, false);
  assert.equal(h.el('frame-backdrop').hidden, true);
  assert.equal(h.document.activeElement, h.el('toggle-frames'));
  assert.equal(h.el('toggle-frames').attributes['aria-expanded'], 'false');
});

test('resizing an open drawer to desktop releases modal state and keeps the photo rail available', async () => {
  const h = harness({withUI:true});h.resize(390);
  await h.el('toggle-frames').click();
  assert.equal(h.el('sheet-inspector').inert, true);
  h.resize(1440);
  assert.equal(h.document.body.classList.contains('frames-open'), false);
  assert.equal(h.el('sheet-inspector').inert, false);
  assert.equal(h.el('frame-rail').attributes['aria-modal'], undefined);
  assert.equal(h.el('toggle-frames').attributes['aria-expanded'], 'true');
  assert.equal(h.el('frame-backdrop').hidden, true);
});
