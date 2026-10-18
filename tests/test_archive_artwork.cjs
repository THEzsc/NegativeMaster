/* Run the shipped artwork interaction against delayed responses, without a browser. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../static/archive.js'), 'utf8');
const code = source.slice(source.indexOf('  function renderArtwork()'), source.indexOf('  async function openArtwork('));
const tick = () => new Promise(resolve => setImmediate(resolve));
function harness() {
  const nodes = new Map(), requests = [], errors = [];
  function node(tag = '') {
    return {tag, children: [], listeners: {}, value: '', classList: {toggle() {}},
      append(...children) {this.children.push(...children);}, replaceChildren(...children) {this.children = children;},
      setAttribute(k, v) {this[k] = v;}, addEventListener(k, fn) {this.listeners[k] = fn;}, focus() {this.focused = true;}};
  }
  const $ = id => {if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id);};
  const state = {current: {id: 'roll-a'}, artworkOpen: true, artworkSaving: false, artworkTab: 'images', artworkLimit: 24,
    artwork: {artworks: ['one', 'two'].map(id => ({id, brand: 'Kodak', name: id, variant: id, width: 200, height: 300}))}};
  vm.runInNewContext(`${code}\nrenderArtwork();`, {state, $, ArtworkModel: {filter: items => items},
    el(tag, cls, text) {const n = node(tag); n.textContent = text; return n;}, externalLink: () => null,
    wrap: fn => async () => {try {await fn();} catch (e) {errors.push(e.message);}}, status() {}, rollUrl: id => id,
    api(url, method, body) {return new Promise((resolve, reject) => requests.push({url, body, resolve, reject}));},
    async acceptRoll(result) {if (state.current.id === result.roll.id) state.current = result.roll;}
  });
  function buttons() {
    const result = []; const walk = n => {if (n.tag === 'button') result.push(n); n.children.forEach(walk);};
    walk($('artwork-grid')); return result;
  }
  return {state, requests, errors, $, buttons};
}
test('only one cover selection is submitted while saving, including stale button events', async () => {
  const h = harness(), [a, b] = h.buttons();
  a.listeners.click(); b.listeners.click();
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].body.artwork_id, 'one');
  assert.ok(h.buttons().every(button => button.disabled));
  h.requests[0].resolve({roll: {id: 'roll-a', cover_artwork: 'one'}}); await tick();
  assert.equal(h.state.current.cover_artwork, 'one');
  assert.equal(h.state.artworkSaving, false);
  assert.equal(h.state.artworkOpen, false);
  assert.equal(h.$('change-cover').focused, true);
});
test('failed cover saves re-enable choices; late responses never switch the selected roll', async () => {
  const h = harness(); h.buttons()[0].listeners.click(); h.requests[0].reject(new Error('offline')); await tick();
  assert.equal(h.state.artworkSaving, false);
  assert.ok(h.buttons().every(button => !button.disabled));
  assert.deepEqual(h.errors, ['offline']);
  h.buttons()[1].listeners.click();
  h.state.current = {id: 'roll-b'};
  h.requests[1].resolve({roll: {id: 'roll-a', cover_artwork: 'two'}}); await tick();
  assert.equal(h.state.current.id, 'roll-b');
  assert.equal(h.state.artworkOpen, true);
  assert.equal(h.$('change-cover').focused, undefined);
});
