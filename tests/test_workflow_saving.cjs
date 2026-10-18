/* Exercise the real browser autosave/load code with delayed network responses. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'gui.py'), 'utf8');
const settingsCode = source.match(/function currentSettings\(\)\{[\s\S]*?\n\}/)?.[0];
const savingCode = source.match(/let lastSavedSig=null,[\s\S]*?(?=\n\$\("savepar"\))/)?.[0];
const loadingCode = source.match(/let loadSequence=0;[\s\S]*?(?=\nfunction saveSettings\()/)?.[0];
const workflowSource = fs.readFileSync(path.join(__dirname, '..', 'static', 'workflow.js'), 'utf8');
const applyingCode = workflowSource.match(/async function applySuggestion\(wholeRoll\)\{[\s\S]*?(?=\n  \$\('analyze-frame'\))/)?.[0];
assert.ok(settingsCode && savingCode && loadingCode && applyingCode, 'production workflow blocks must be found');
const tick = () => new Promise(resolve => setImmediate(resolve));

function harness() {
  const requests = [], timers = new Map(), statuses = [], edited = [], nodes = new Map();
  let timerId = 0;
  const context = vm.createContext({
    Promise, Map, JSON, Object, Error, console, encodeURIComponent,
    LocalPaths:require('../static/local_paths.js'),
    fetch(url, options) {
      let resolve, reject;
      const promise = new Promise((a, b) => { resolve = a; reject = b; });
      requests.push({url, body:options?.body ? JSON.parse(options.body) : null,
        resolve(data={ok:true}, ok=true) { resolve({ok, json:async()=>data}); }, reject});
      return promise;
    },
    setTimeout(fn) { const id = ++timerId; timers.set(id, fn); return id; },
    clearTimeout(id) { timers.delete(id); },
    stat(text) { statuses.push(text); }, markEdited(name) { edited.push(name); },
    $(id) { if (!nodes.has(id)) nodes.set(id, {style:{}, checked:false, querySelectorAll:()=>[], append(){}}); return nodes.get(id); },
    document:{querySelectorAll:()=>[], createElement:()=>({append(){}})},
    updateNavButtons(){}, resetView(){}, syncFmtPills(){}, refl(){}, drawCrop(){}, applyFormat(){},
    window:{NMWorkflow:{loaded(){}}}
  });
  const run = code => vm.runInContext(code, context);
  run(`let curFile='A.png',P={gamma:1,raw_denoise:false},cropN={x0:0,y0:0,x1:1,y1:1},
    curFmt='free',orient='land',geometrySource='manual',lastAutoSummary='',
    batchBusy=false,loaded=true,rdirty=false,fullW=0,fullH=0,aspect=null;
    const HJ={'Content-Type':'application/json'},D={gamma:1.8,flip:'h'};
    function dclone(value){return JSON.parse(JSON.stringify(value));}
    let rendered=[];function render(){if(loaded){rendered.push({path:curFile,gamma:P.gamma});autosaveXml();}}
    ${settingsCode}\n${savingCode}\n${loadingCode}
    lastSavedSig=settingsSig();`);
  return {run, requests, timers, statuses, edited, nodes,
    async timer() { const active=[...timers.values()]; timers.clear(); active.forEach(fn=>fn()); await tick(); },
    async answer(index, data={ok:true}, ok=true) { requests[index].resolve(data,ok); await tick(); }};
}

test('debounce captures latest edits and original source even after globals change', async () => {
  const h=harness();
  h.run('P.gamma=1.5;autosaveXml();P.gamma=2;autosaveXml();');
  assert.equal(h.timers.size,1);
  h.run("curFile='B.png';P.gamma=9;");
  await h.timer();
  assert.equal(h.requests.length,1);
  assert.equal(h.requests[0].body.path,'A.png');
  assert.equal(h.requests[0].body.data.P.gamma,2);
  await h.answer(0);
  assert.equal(h.requests[1].url,'/api/settings');
  assert.equal(h.requests[1].body.path,'A.png');
  assert.equal(h.requests[1].body.data.P.gamma,2);
  await h.answer(1);
  assert.deepEqual(h.edited,['A.png']);
  assert.equal(JSON.parse(h.run('lastSavedSig')).P.gamma,1);
});

test('queued writes cannot finish out of order and flush waits for both stores', async () => {
  const h=harness();
  h.run('P.gamma=2;autosaveXml();');
  let firstDone=false, secondDone=false;
  const first=h.run('flushAutosave()').then(()=>{firstDone=true;});
  await tick();
  h.run('P.gamma=2.4;autosaveXml();');
  const second=h.run('flushAutosave()').then(()=>{secondDone=true;});
  await tick();
  assert.equal(h.requests.length,1);
  await h.answer(0);
  assert.equal(firstDone,false);
  assert.equal(h.requests.length,2);
  await h.answer(1);
  assert.equal(firstDone,true);
  assert.equal(secondDone,false);
  assert.equal(h.requests[2].body.data.P.gamma,2.4);
  await h.answer(2);await h.answer(3);
  await Promise.all([first,second]);
  assert.equal(secondDone,true);
  assert.equal(JSON.parse(h.run('lastSavedSig')).P.gamma,2.4);
});

test('undo before a debounced save persists the restored state', async () => {
  const h=harness();
  h.run('P.gamma=2;autosaveXml();P.gamma=1;autosaveXml();');
  await h.timer();
  assert.equal(h.requests[0].body.data.P.gamma,1);
  await h.answer(0);await h.answer(1);
  assert.equal(JSON.parse(h.run('lastSavedSig')).P.gamma,1);
});

test('undo while a prior write is in flight queues a compensating saved state', async () => {
  const h=harness();
  h.run('P.gamma=2;autosaveXml();');
  const first=h.run('flushAutosave()');await tick();
  h.run('P.gamma=1;autosaveXml();');
  const restored=h.run('flushAutosave()');
  await h.answer(0);await h.answer(1);
  assert.equal(h.requests[2].body.data.P.gamma,1);
  await h.answer(2);await h.answer(3);
  await Promise.all([first,restored]);
  assert.equal(JSON.parse(h.run('lastSavedSig')).P.gamma,1);
});

test('flush with no pending debounce still waits for an in-flight save', async () => {
  const h=harness();
  h.run('P.gamma=2;autosaveXml();');
  const first=h.run('flushAutosave()');await tick();
  let finished=false;
  const barrier=h.run('flushAutosave()').then(()=>{finished=true;});
  await tick();assert.equal(finished,false);
  await h.answer(0);assert.equal(finished,false);
  await h.answer(1);await Promise.all([first,barrier]);
  assert.equal(finished,true);
  assert.equal(h.requests.length,2);
});

test('failed save rejects the barrier without marking saved and a later edit can retry', async () => {
  const h=harness();
  h.run('P.gamma=2;autosaveXml();');
  const failed=assert.rejects(h.run('flushAutosave()'),/disk full/);await tick();
  await h.answer(0,{ok:false,err:'disk full'},false);await failed;
  assert.deepEqual(h.edited,[]);
  assert.equal(JSON.parse(h.run('lastSavedSig')).P.gamma,1);
  h.run('autosaveXml();');
  const retry=h.run('flushAutosave()');await tick();
  await h.answer(1);await h.answer(2);await retry;
  assert.equal(JSON.parse(h.run('lastSavedSig')).P.gamma,2);
});

test('loading waits for pending edits and keeps rendering off until target settings restore', async () => {
  const h=harness();
  h.run('P.gamma=2;autosaveXml();loadFile("B.png");');await tick();
  assert.equal(h.run('loaded'),false);
  assert.equal(h.requests[0].url,'/api/sidecar');
  assert.equal(h.requests[0].body.path,'A.png');
  assert.equal(h.requests.some(r=>r.url==='/api/load'),false);
  await h.answer(0);await h.answer(1);
  assert.equal(h.requests[2].url,'/api/load');
  await h.answer(2,{ok:true,w:800,h:600,name:'B.png'});
  assert.equal(h.run('curFile'),'B.png');
  assert.equal(h.run('loaded'),false);
  h.run('render();');assert.equal(h.run('rendered.length'),0);
  await h.answer(3,{ok:true,data:{P:{gamma:1.3},cropN:{x0:.1,y0:.1,x1:.9,y1:.9},curFmt:'free',orient:'land'}});
  assert.equal(h.run('loaded'),true);
  assert.equal(h.run('P.gamma'),1.3);
  assert.equal(h.run('rendered.length'),1);
  assert.equal(h.run('rendered[0].path'),'B.png');
  assert.equal(h.run('pendingSave'),null);
});

test('failed old-frame save cancels loading and retains original editing context', async () => {
  const h=harness();
  h.run('P.gamma=2;autosaveXml();');
  const loading=h.run('loadFile("B.png")');await tick();
  await h.answer(0,{ok:false,err:'read-only folder'},false);await loading;
  assert.equal(h.run('loaded'),true);
  assert.equal(h.run('curFile'),'A.png');
  assert.equal(h.run('P.gamma'),2);
  assert.equal(h.requests.length,1);
});

test('roll gamma waits for current edits even when the current photo is excluded from the roll', async () => {
  const h=harness();
  h.run(`const M={canApply:()=>true};
    function fingerprint(){return 'snapshot';}function currentScope(){return ['B.png'];}
    function invalidateReport(){};
    let analysis={signature:'snapshot',paths:['B.png'],report:{recommendation:1.7,parameter_key:'gamma'}};
    async function api(url,body){return (await fetch(url,{body:JSON.stringify(body)})).json();}
    ${applyingCode}
    P.gamma=2;autosaveXml();`);
  const applying=h.run('applySuggestion(true)');await tick();
  assert.equal(h.nodes.get('panel').inert,true);
  assert.equal(h.requests.length,1);
  assert.equal(h.requests[0].body.path,'A.png');
  await h.answer(0);
  assert.equal(h.requests.length,2);
  assert.equal(h.requests[1].url,'/api/settings');
  await h.answer(1);
  assert.equal(h.requests[2].url,'/api/workflow/roll-gamma');
  assert.deepEqual(h.requests[2].body.paths,['B.png']);
  assert.equal(h.requests[2].body.current.P.gamma,2);
  await h.answer(2,{ok:true,updated:['B.png'],errors:[],gamma:1.7});await applying;
  assert.equal(h.run('P.gamma'),2);
  assert.equal(JSON.parse(h.run('lastSavedSig')).P.gamma,2);
  assert.equal(h.nodes.get('panel').inert,false);
  assert.deepEqual(h.edited,['A.png','B.png']);
});
