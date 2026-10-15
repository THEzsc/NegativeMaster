'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {selectionInOrder, restoreDraft, cropGeometry} = require('../static/sheet_model.js');

const photos = [
  {id: 11, path: '/a.jpg', name: 'A'},
  {id: 22, path: '/b.jpg', name: 'B'},
  {id: 33, path: '/c.jpg', name: 'C'},
  {id: 44, path: '/d.jpg', name: 'D'},
];

test('selection follows the displayed sequence after deselecting and reselecting a frame', () => {
  const selected = [11, 22, 33];
  selected.splice(selected.indexOf(11), 1);
  selected.push(11);
  assert.deepEqual(selectionInOrder(photos, selected), [11, 22, 33]);
  assert.deepEqual(selectionInOrder([photos[2], photos[0], photos[1]], selected), [33, 11, 22]);
  assert.deepEqual(selectionInOrder(photos, [99, 22, 22]), [22]);
});

test('restore honors allSources, preserves selection, and appends newly discovered photos', () => {
  const draft = {allSources: ['/c.jpg', '/a.jpg', '/b.jpg'], sources: ['/b.jpg', '/c.jpg']};
  const result = restoreDraft(photos, draft);
  assert.deepEqual(result.items.map(item => item.id), [33, 11, 22, 44]);
  assert.deepEqual(result.order, [33, 22]);
  assert.equal(result.active, 33);
  assert.deepEqual(photos.map(item => item.id), [11, 22, 33, 44]);
});

test('legacy source lists preserve their order and explicit empty selection stays empty', () => {
  assert.deepEqual(restoreDraft(photos, {sources: ['/c.jpg', '/a.jpg']}).order, [33, 11]);
  const result = restoreDraft(photos, {allSources: ['/c.jpg', '/a.jpg'], sources: []});
  assert.deepEqual(result.order, []);
  assert.equal(result.active, 33);
  assert.equal(result.backgroundSource, null);
  assert.deepEqual(restoreDraft(photos).order, [11, 22, 33, 44]);
});

test('frame edits, active photo, and background follow paths when item ids change', () => {
  const draft = {
    allSources: ['/c.jpg', '/b.jpg', '/a.jpg'], sources: ['/a.jpg', '/c.jpg'],
    activePath: '/b.jpg', backgroundPath: '/c.jpg',
    config: {background: {sourceIndex: 11}},
    frameOptions: {'/c.jpg': {rotation: 90, label: '31A', crop: {x: .2, y: .8, scale: 2}}},
  };
  const changedIds = photos.map(item => ({...item, id: item.id + 100}));
  const result = restoreDraft(changedIds, draft);
  assert.deepEqual(result.order, [133, 111]);
  assert.equal(result.active, 122);
  assert.equal(result.backgroundSource, 133);
  assert.deepEqual(result.frames[133], draft.frameOptions['/c.jpg']);
  result.frames[133].crop.x = .9;
  assert.equal(draft.frameOptions['/c.jpg'].crop.x, .2);
});

test('background restoration supports custom, valid legacy ids, and missing-path fallback', () => {
  assert.equal(restoreDraft(photos, {config: {background: {sourceIndex: 'custom'}}}).backgroundSource, 'custom');
  assert.equal(restoreDraft(photos, {config: {background: {sourceIndex: 22}}}).backgroundSource, 22);
  assert.equal(restoreDraft(photos, {sources: ['/c.jpg'], backgroundPath: '/gone.jpg', config: {background: {sourceIndex: 99}}}).backgroundSource, 33);
  assert.equal(restoreDraft(photos, {activePath: '/gone.jpg', sources: ['/b.jpg']}).active, 22);
  assert.deepEqual(restoreDraft([], {sources: []}), {items: [], order: [], frames: {}, active: null, backgroundSource: null});
});

test('cover crops landscape and portrait sources to the target aspect ratio', () => {
  assert.deepEqual(cropGeometry(600, 400, 300, 300, 'cover'), {sx: 100, sy: 0, sw: 400, sh: 400, dx: 0, dy: 0, dw: 300, dh: 300});
  assert.deepEqual(cropGeometry(400, 600, 300, 200, 'cover'), {sx: 0, sy: (600 - 400 / 1.5) / 2, sw: 400, sh: 400 / 1.5, dx: 0, dy: 0, dw: 300, dh: 200});
});

test('cover zoom and edge centers never sample outside the source', () => {
  assert.deepEqual(cropGeometry(600, 400, 300, 200, 'cover', 2, 0, 1), {sx: 0, sy: 200, sw: 300, sh: 200, dx: 0, dy: 0, dw: 300, dh: 200});
  for (const fit of ['cover', 'contain']) {
    for (const x of [0, .5, 1]) for (const y of [0, .5, 1]) {
      const g = cropGeometry(603, 401, 301, 203, fit, 3, x, y);
      assert.ok(g.sx >= 0 && g.sy >= 0);
      assert.ok(g.sx + g.sw <= 603 && g.sy + g.sh <= 401);
      assert.ok(g.dx >= 0 && g.dy >= 0 && g.dx + g.dw <= 301 && g.dy + g.dh <= 203);
    }
  }
});

test('contain preserves the photo ratio and centers the remaining empty area', () => {
  assert.deepEqual(cropGeometry(600, 400, 300, 300, 'contain'), {sx: 0, sy: 0, sw: 600, sh: 400, dx: 0, dy: 50, dw: 300, dh: 200});
  assert.deepEqual(cropGeometry(400, 600, 300, 200, 'contain'), {sx: 0, sy: 0, sw: 400, sh: 600, dx: 83, dy: 0, dw: 133, dh: 200});
  assert.deepEqual(cropGeometry(600, 400, 300, 300, 'contain', 2, 1, 0), {sx: 300, sy: 0, sw: 300, sh: 200, dx: 0, dy: 50, dw: 300, dh: 200});
});

test('contain matches Pillow half-even crop and resize rounding', () => {
  assert.deepEqual(cropGeometry(603, 401, 301, 203, 'contain', 3), {sx: 201, sy: 134, sw: 201, sh: 133, dx: 0, dy: 2, dw: 301, dh: 199});
  assert.deepEqual(cropGeometry(5, 5, 10, 10, 'contain', 1, .5, .5), {sx: 0, sy: 0, sw: 5, sh: 5, dx: 0, dy: 0, dw: 10, dh: 10});
  assert.deepEqual(cropGeometry(10, 6, 10, 10, 'contain', 2, .5, .5), {sx: 2, sy: 2, sw: 6, sh: 2, dx: 0, dy: 3, dw: 10, dh: 3});
});

test('invalid crop parameters fail rather than create non-finite canvas geometry', () => {
  assert.throws(() => cropGeometry(0, 400, 300, 200), RangeError);
  assert.throws(() => cropGeometry(600, 400, Infinity, 200), RangeError);
  assert.throws(() => cropGeometry(600, 400, 300, 200, 'cover', 0), RangeError);
  assert.throws(() => cropGeometry(600, 400, 300, 200, 'cover', 2, -1), RangeError);
  assert.throws(() => cropGeometry(600, 400, 300, 200, 'stretch'), RangeError);
});

test('the same standalone module exposes the browser global without CommonJS', () => {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(require.resolve('../static/sheet_model.js'), 'utf8'), context);
  assert.equal(typeof context.SheetModel.selectionInOrder, 'function');
  assert.equal(typeof context.SheetModel.restoreDraft, 'function');
  assert.equal(typeof context.SheetModel.cropGeometry, 'function');
});

test('portrait frames default sideways while explicit zero and other rotations win', () => {
  const {frameRotation} = require('../static/sheet_model.js');
  assert.equal(frameRotation(400,600),90);
  assert.equal(frameRotation(600,400),0);
  assert.equal(frameRotation(400,400),0);
  assert.equal(frameRotation(400,600,{rotation:0}),0);
  assert.equal(frameRotation(400,600,{rotation:270}),270);
});
