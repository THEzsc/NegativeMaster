/* Classic trial: explicit active/selected scope and field-level, reversible edits. */
(() => {
  if(!new URLSearchParams(location.search).has('classic'))return;
  const W=window.NMWeb,M=window.NMDevelopModel,panel=$('panel'),copy=x=>JSON.parse(JSON.stringify(x));
  let groups=[],baseline=null,pending=null,timer=null,running=null,suppressed=false,dragging=false,auto=false,clipboard=null,undo=[],redo=[],stop=false;
  const selected=()=>[...document.querySelectorAll('#files .fitem')].filter(r=>r.style.display!=='none'&&r.querySelector('.fck').checked).map(r=>r.dataset.path);
  const targets=()=>selected().filter(p=>p!==curFile);
  const fields=()=>groups.flatMap(g=>g.fields.map(f=>f.id));
  const section=id=>$(id).closest('details.sec');
  const film=$('workflow-assistant'),crop=section('fmts'),hist=section('hist'),exp=section('export');
  film.querySelector('summary').textContent='胶片反转';
  $('film-roll').checked=false;$('film-roll').closest('label').hidden=true;
  const assistant=document.createElement('aside');assistant.id='classic-sidebar';assistant.innerHTML='<details open><summary>预设</summary><div id="classic-presets"></div></details><details open><summary>历史记录</summary><ol id="classic-history"></ol></details>';
  $('stage').before(assistant);
  const preset=$('presel'),save=$('presave'),del=$('predel');
  if(preset){$('classic-presets').append(preset);if($('prename'))$('classic-presets').append($('prename').parentElement);}

  const looks=$('look-grid')?.closest('details');if(looks)assistant.append(looks);
  for(const id of ['black_pct','pbase']){const d=section(id);film.querySelector('.bd').append(...d.querySelector('.bd').children);d.remove();}
  const advanced=section('resetdefault');advanced.querySelector('summary').textContent='高级';
  const ref=section('ref');advanced.querySelector('.bd').append(ref);panel.append(advanced);
  const tools=document.createElement('div');tools.id='classic-tools';tools.innerHTML='<button id="classic-crop">裁剪</button><label><input type="checkbox" id="classic-solo">独显</label><button id="classic-export">导出…</button>';
  hist.after(tools);crop.hidden=true;
  $('classic-crop').onclick=()=>{crop.hidden=!crop.hidden;crop.open=!crop.hidden;W.fit();};
  for(const d of panel.querySelectorAll(':scope>details.sec'))d.addEventListener('toggle',()=>{if(d.open&&$('classic-solo').checked&&d!==hist&&d!==crop)for(const other of panel.querySelectorAll(':scope>details.sec'))if(other!==d&&other!==hist&&other!==crop)other.open=false;});
  const exportDialog=document.createElement('dialog');exportDialog.id='classic-export-dialog';exportDialog.innerHTML='<h2>导出照片</h2><button class="dialog-close">关闭</button>';exportDialog.append(exp);exp.open=true;exportDialog.querySelector('button').onclick=()=>exportDialog.close();document.body.append(exportDialog);$('classic-export').onclick=()=>exportDialog.showModal();
  const oldSync=$('selective-sync');oldSync.hidden=true;
  const bar=document.createElement('div');bar.id='classic-actions';bar.innerHTML='<div><label><input id="classic-auto" type="checkbox">自动同步</label><span id="classic-scope">仅当前照片</span></div><div><button id="classic-copy">复制…</button><button id="classic-paste" disabled>粘贴</button><button id="classic-sync">同步…</button><button id="classic-reset">重置</button><button id="classic-stop" hidden>停止</button></div>';
  panel.append(bar);
  const dialog=document.createElement('dialog');dialog.id='classic-sync-dialog';dialog.innerHTML='<h2 id="classic-dialog-title">同步调整</h2><p id="classic-source"></p><div class="btnrow"><button id="classic-common">常用</button><button id="classic-all">全选</button><button id="classic-none">清空</button></div><div id="classic-fields"></div><footer><button id="classic-cancel">取消</button><button id="classic-confirm" class="acc">同步</button></footer>';document.body.append(dialog);
  let copyMode=false;
  function chosen(){return [...dialog.querySelectorAll('input[data-field]:checked')].map(n=>n.dataset.field);}
  function showDialog(isCopy){if(!loaded||batchBusy)return;copyMode=isCopy;$('classic-dialog-title').textContent=isCopy?'复制调整':'同步调整';$('classic-confirm').textContent=isCopy?'复制':'同步';$('classic-source').textContent=LocalPaths.basename(curFile)+(isCopy?'':` → ${targets().length} 张所选照片`);dialog.showModal();}
  function selectFields(ids){for(const el of dialog.querySelectorAll('input[data-field]'))el.checked=ids.includes(el.dataset.field);groupStates();}
  function groupStates(){for(const group of dialog.querySelectorAll('details')){const all=[...group.querySelectorAll('input[data-field]')],count=all.filter(x=>x.checked).length,cb=group.querySelector('summary input');cb.checked=count===all.length;cb.indeterminate=count>0&&count<all.length;} $('classic-confirm').disabled=!chosen().length||(!copyMode&&!targets().length);}
  $('classic-copy').onclick=()=>showDialog(true);$('classic-sync').onclick=()=>showDialog(false);$('classic-cancel').onclick=()=>dialog.close();
  $('classic-common').onclick=()=>selectFields(groups.filter(g=>g.selected).flatMap(g=>g.fields.map(f=>f.id)));$('classic-all').onclick=()=>selectFields(fields());$('classic-none').onclick=()=>selectFields([]);
  $('classic-confirm').onclick=async()=>{const ids=chosen();dialog.close();await flush();if(copyMode){clipboard={source:copy(W.params()),fields:ids};update();}else await perform(targets(),{fields:ids,source:copy(W.params())},'同步调整');};
  $('classic-paste').onclick=async()=>{await flush();if(clipboard)await perform(auto?[curFile,...targets()]:[curFile],clipboard,'粘贴调整');};
  $('classic-reset').onclick=()=>{if(loaded&&!batchBusy){P=copy(D);cropN={x0:0,y0:0,x1:1,y1:1};geometrySource='manual';refl();render();}};
  $('classic-auto').onchange=async()=>{await flush();auto=$('classic-auto').checked;update();};$('classic-stop').onclick=()=>stop=true;
  function update(){
    $('classic-scope').textContent=auto?`影响 ${loaded?targets().length+1:0} 张`:'仅当前照片';bar.classList.toggle('auto-on',auto);
    for(const id of ['classic-copy','classic-reset','classic-auto'])$(id).disabled=!loaded||!!running||batchBusy;
    $('classic-paste').disabled=!clipboard||!loaded||!!running||batchBusy;$('classic-sync').disabled=!loaded||!targets().length||!!running||batchBusy;
    $('workflow-undo').disabled=(!undo.length&&!pending)||!!running||batchBusy;$('workflow-redo').disabled=!redo.length||!!running||batchBusy;
    const list=$('classic-history');list.replaceChildren();for(const entry of undo.slice(-25).reverse()){const li=document.createElement('li');li.textContent=entry.title;list.append(li);}
  }
  function baselineNow(){baseline=loaded?copy(W.params()):null;update();}
  const oldLoaded=window.NMWorkflow.loaded;
  window.NMWorkflow.loaded=()=>{oldLoaded();baselineNow();};
  function record(){
    if(!loaded||suppressed||batchBusy||!groups.length)return;
    const next=W.params();if(!baseline){baselineNow();return;}
    const changes=M.changedFields(baseline,next,groups);if(!changes.length)return;
    if(!pending)pending={path:curFile,targets:auto?[curFile,...targets()]:[curFile],source:copy(next),fields:new Set(),title:auto?'自动同步':'调整照片'};
    changes.forEach(f=>pending.fields.add(f));pending.source=copy(next);baseline=copy(next);clearTimeout(timer);timer=setTimeout(()=>{if(!dragging)flush().catch(e=>stat(e.message));},450);update();
  }
  window.NMWorkflow.record=record;
  document.addEventListener('pointerdown',e=>{if(panel.contains(e.target)&&e.target.matches('input[type=range]'))dragging=true;});
  document.addEventListener('pointerup',()=>{if(dragging){dragging=false;flush().catch(e=>stat(e.message));}});
  const originalFlush=flushAutosave;
  async function flush(){clearTimeout(timer);if(running)await running;if(!pending)return;const job=pending;pending=null;await perform(job.targets,{source:job.source,fields:[...job.fields]},job.title);}
  flushAutosave=async()=>{await flush();return originalFlush();};
  async function perform(paths,payload,title){
    if(!paths.length)return;stop=false;
    running=(async()=>{W.lock(true);$('classic-stop').hidden=false;update();const ids=[],errors=[];
      try{await originalFlush();for(const path of paths){if(stop)break;try{const snap=await W.api('snapshot',{path});const result=await W.api('apply',{path,token:snap.token,kind:'sync',...payload});if(result.undo_id)ids.push(result.undo_id);markEdited(path);}catch(e){errors.push(LocalPaths.basename(path)+': '+e.message);}stat(`${title} ${ids.length}/${paths.length}`);}
        if(ids.length){undo.push({ids,title:`${title} · ${ids.length} 张`});redo=[];}
        suppressed=true;if(curFile)await W.restoreCurrent();if(errors.length)stat(errors.join('；'));
      }finally{suppressed=false;W.lock(false);$('classic-stop').hidden=true;baselineNow();}
    })();try{await running;}finally{running=null;update();}
  }
  async function history(from,to){await flush();if(batchBusy||!from.length)return;W.lock(true);const entry=from.pop(),inverse=[],failed=[];try{for(const id of [...entry.ids].reverse()){try{const r=await W.api('undo',{undo_id:id});inverse.push(r.undo_id);}catch(e){failed.push(id);stat(e.message);}}if(inverse.length)to.push({ids:inverse,title:entry.title});if(failed.length)from.push({ids:failed.reverse(),title:entry.title});suppressed=true;if(curFile)await W.restoreCurrent();}finally{suppressed=false;W.lock(false);baselineNow();update();}}
  $('workflow-undo').onclick=()=>history(undo,redo);$('workflow-redo').onclick=()=>history(redo,undo);
  // Orientation is an operation on each selected frame, never a copy of its neighbour's crop.
  for(const [id,op] of [['rotL','ccw'],['rotR','cw'],['fliph','h'],['flipv','v']])$(id).onclick=async()=>{await flush();await perform(auto?[curFile,...targets()]:[curFile],{operation:op},'调整方向');};
  $('emulsion').onchange=async()=>{const enabled=$('emulsion').checked;await flush();await perform(auto?[curFile,...targets()]:[curFile],{operation:enabled},'药膜面校正');};
  window.NMClassic={ownsSaving:true,flush,update,addBatch(ids,title){if(ids.length){undo.push({ids:[...ids],title});redo=[];baselineNow();}}};
  document.addEventListener('click',()=>queueMicrotask(update));
  window.addEventListener('beforeunload',e=>{if(pending||running){e.preventDefault();e.returnValue='';flush();}});
  fetch('/api/workbench/catalog').then(r=>r.json()).then(data=>{groups=data.groups;for(const group of groups){const d=document.createElement('details'),summary=document.createElement('summary'),label=document.createElement('label'),all=document.createElement('input');all.type='checkbox';label.append(all,document.createTextNode(group.title));summary.append(label);d.append(summary);const grid=document.createElement('div');grid.className='classic-field-grid';for(const f of group.fields){const l=document.createElement('label'),cb=document.createElement('input');cb.type='checkbox';cb.dataset.field=f.id;cb.checked=group.selected;cb.onchange=groupStates;l.append(cb,document.createTextNode(f.title));grid.append(l);}all.onchange=()=>{for(const cb of grid.querySelectorAll('input'))cb.checked=all.checked;groupStates();};d.append(grid);$('classic-fields').append(d);}groupStates();baselineNow();}).catch(e=>{window.NMClassic.ownsSaving=false;stat('同步设置载入失败：'+e.message);});
  baselineNow();
})();
