'use strict';
const $=id=>document.getElementById(id), clone=o=>JSON.parse(JSON.stringify(o));
const defaults={width:4800,columns:6,ratio:'3:2',spacing:38,margin:90,background:{mode:'blur',color:'#d7d2c6',color2:'#65776d',angle:60,blur:34,brightness:.75,sourceIndex:0,opacity:1},strip:{color:'#080808',opacity:1,sprockets:true,edgeText:'',secondaryText:'',edgeColor:'#dda850',fontStyle:'auto',edgeScale:1,edgeTracking:0,leader:true,leaderMode:'auto',leaderCount:3,leaderStyle:'dark',leaderStrength:.75,leaderShape:'cut',separation:'none',separationStrength:.65,separationHoles:true,shadowTone:'black',sprocketStyle:'standard',sprocketRim:'none',edgeGlow:0,leakSoftness:.55,leakSeed:17,leakPhotoCount:0,startNumber:1,reverseNumbers:false,frameGap:12,padding:8,showNumbers:true,showHalfNumbers:true,edgeArrow:'none',fit:'contain'},header:{enabled:true,title:'',roll:'',camera:'',lens:'',date:'',process:'',notes:'',color:'#fffdfa',textColor:'#191a1b',height:180,showStock:true,infoScale:1},frameOverrides:[]};
const state={config:clone(defaults),stocks:[],stockId:'',job:null,items:[],order:[],frames:{},active:null,directory:'',label:'',zoom:1,previewUrl:null,history:[],future:[],preparing:false,exporting:false,prepareSeq:0,previewSeq:0,controller:null,lastCommitted:null,projectPending:null,view:"sheet",previewBusy:false,previewWanted:false};
function status(message,error=false){$('sheet-status').textContent=message;$('sheet-statusbar').classList.toggle('error',error);}
function get(obj,path){return path.split('.').reduce((v,k)=>v?.[k],obj);}
function set(obj,path,value){const parts=path.split('.');let target=obj;for(const part of parts.slice(0,-1)){target[part]??={};target=target[part];}target[parts.at(-1)]=value;}
function snapshot(){return clone({config:state.config,stockId:state.stockId,order:state.order,frames:state.frames,itemOrder:state.items.map(i=>i.id)});}
function commit(before){const next=snapshot();if(before&&JSON.stringify(before)!==JSON.stringify(next)){state.history.push(before);if(state.history.length>40)state.history.shift();state.future=[];}state.lastCommitted=next;updateUndo();saveDraft();}
function transaction(action){const before=snapshot();action();commit(before);syncControls();renderFrames();queuePreview();}
function updateUndo(){$('undo').disabled=state.preparing||!state.history.length;$('redo').disabled=state.preparing||!state.future.length;}
function restore(s){state.config=clone(s.config);state.stockId=s.stockId;state.order=s.order.slice();state.frames=clone(s.frames);if(s.itemOrder)state.items.sort((a,b)=>s.itemOrder.indexOf(a.id)-s.itemOrder.indexOf(b.id));state.lastCommitted=snapshot();syncControls();renderFrames();queuePreview();saveDraft();}
function saveDraft(){
  if(state.preparing||!state.job||!state.items.length)return;
  try{
    const frameOptions={};
    for(const item of state.items)if(state.frames[item.id])frameOptions[item.path]=state.frames[item.id];
    const pathFor=id=>state.items.find(item=>item.id===Number(id))?.path;
    localStorage.setItem('nm.sheet.draft',JSON.stringify({job:state.job,config:state.config,stockId:state.stockId,directory:state.directory,label:state.label,
      allSources:state.items.map(item=>item.path),sources:state.order.map(pathFor).filter(Boolean),frameOptions,
      activePath:pathFor(state.active),backgroundPath:pathFor(state.config.background.sourceIndex),positiveOnly:state.items.every(item=>item.source==='import')}));
  }catch(e){status('浏览器未能保存草稿，请用“保存项目”保留当前排版',true);}
}
async function jsonRequest(url,options={}){const r=await fetch(url,options);let d;try{d=await r.json();}catch(e){throw new Error('服务返回了无效内容，请刷新页面后重试');}if(!r.ok||d.ok===false)throw new Error(d.error||d.err||`请求失败（${r.status}）`);return d;}
const post=(url,body)=>jsonRequest(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
function stock(){return state.stocks.find(s=>s.id===state.stockId)||state.stocks[0]||{};}
function stockOptions(filter=''){const select=$('stock-select');select.replaceChildren();const q=filter.toLowerCase().replace(/柯达/g,'kodak').replace(/富士/g,'fujifilm').replace(/福马/g,'foma').replace(/乐凯/g,'lucky').replace(/伊尔福/g,'ilford').replace(/爱克发/g,'agfa').replace(/凤凰/g,'phoenix');const visible=state.stocks.filter(s=>[s.brand,s.name,s.iso,s.process].join(' ').toLowerCase().includes(q));const groups=new Map();for(const s of visible){if(!groups.has(s.brand)){const g=document.createElement('optgroup');g.label=s.brand;groups.set(s.brand,g);select.append(g);}const o=document.createElement('option');o.value=s.id;o.textContent=`${s.name} · ${s.iso}`;groups.get(s.brand).append(o);}if(!visible.length){const o=document.createElement('option');o.textContent='没有匹配型号';o.disabled=true;select.append(o);}select.value=state.stockId;$('stock-count').textContent=`${state.stocks.length} 款`;}
function stockInfo(){const s=stock();$('stock-summary').textContent=s.name?`${s.brand} / ISO ${s.iso} / ${s.process} / ${(s.formats||[]).join('、')}`:'';const source=$('stock-sources');source.replaceChildren();const intro=document.createElement('p');intro.className='form-note';intro.textContent=s.edge_evidence==='verified'?'边字内容有资料依据，字形与颜色为近似复刻，可自行修改。':'边字与字形为可编辑的近似复刻，实际印字可能随产地与年代变化。';source.append(intro);if(s.notes){const n=document.createElement('p');n.className='form-note';n.textContent=s.notes;source.append(n);}for(const item of s.sources||[]){try{const url=new URL(item.url);if(!['http:','https:'].includes(url.protocol))continue;const a=document.createElement('a');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';a.textContent=item.title||url.hostname;source.append(a);}catch(e){}}}
function applyStock(id){const previous=stock();const s=state.stocks.find(s=>s.id===id);if(!s)return;state.stockId=id;state.config.strip.edgeText=s.edge_text||s.name.toUpperCase();state.config.strip.secondaryText=s.edge_secondary||'';state.config.strip.edgeColor=s.edge_color||'#dda850';state.config.strip.fontStyle='auto';if(!state.config.header.title||state.config.header.title===previous.name)state.config.header.title=s.name;if(!state.config.header.process||state.config.header.process===previous.process)state.config.header.process=s.process;stockInfo();}
function syncControls(){
  for(const el of document.querySelectorAll('[data-config]')){const v=get(state.config,el.dataset.config);if(el.type==='checkbox')el.checked=!!v;else if(document.activeElement!==el)el.value=v??'';}
  for(const out of document.querySelectorAll('[data-output]')){const v=get(state.config,out.dataset.output);out.textContent=out.dataset.format==='percent'?`${Math.round(v*100)}%`:typeof v==='number'?(Number.isInteger(v)?String(v):v.toFixed(2)):String(v??'');out.className='value';}
  stockOptions($('stock-search').value);stockInfo();syncBackground();syncLeader();syncLettering();syncFrameControls();updateUndo();window.SheetUI?.syncRanges();window.SheetColors?.sync();window.SheetFrame?.draw();
}
function syncLeader(){
  const strip=state.config.strip,count=state.order.length,columns=state.config.columns;
  const blanks=strip.leader?(strip.leaderMode==='auto'?(count?((columns-count%columns)%columns||columns):0):strip.leaderCount):0;
  $('leader-settings').hidden=!strip.leader;
  $('leader-count-field').hidden=strip.leaderMode!=='manual';
  const ivory=strip.leaderStyle==='ivory',hasLeak=!['dark','clear'].includes(strip.leaderStyle);
  $('leader-strength-field').hidden=!hasLeak;
  $('leak-settings').hidden=!hasLeak;
  $('sprocket-settings').hidden=!strip.sprockets;
  $('leak-photo-field').hidden=ivory;
  $('leader-strength-label').textContent=ivory?'彩边强度':'曝光强度';
  $('leak-summary').textContent=ivory?(blanks?'浅蜜色片基、细颗粒与末端粉紫／黄色显影边。只作用于片头；可搭配整幅斜切，换纹理会保留当前配色。':'乳白片基只作用于片头，请开启片头空格并设置至少 1 格。'):!blanks&&!strip.leakPhotoCount?'当前没有片头，请增加延伸张数，或开启片头空格。':'0 表示仅片头。漏光沿胶片连续展开，左强右弱，不会在画格间断开；只影响排版导出。';
  const total=count+blanks,last=total%columns||columns;
  $('leader-summary').textContent=count?`${blanks} 格片头 + ${count} 张照片 · ${Math.ceil(total/columns)} 行 · ${last===columns?'末行已满':`末行 ${last} / ${columns} 格`}`:'载入照片后自动计算格数';
}
function syncLettering(){
  const strip=state.config.strip,style=strip.fontStyle==='auto'?(stock().font_style||'condensed'):strip.fontStyle;
  const text=strip.edgeText||stock().edge_text||'FILM 135 / ISO 200',color=strip.edgeColor||'#dda850';
  const arrow=strip.edgeArrow||'none',glow=strip.edgeGlow||0;
  const signature=[style,text,color,arrow,glow].join('|'),img=$('lettering-preview');
  if(img.dataset.signature!==signature){img.dataset.signature=signature;img.src=`/api/sheet/lettering?style=${encodeURIComponent(style)}&text=${encodeURIComponent(text)}&color=${encodeURIComponent(color)}&arrow=${encodeURIComponent(arrow)}&glow=${glow}`;}
  $('lettering-caption').textContent=style.startsWith('citaro')?'Citaro Voor · Jeffrey Visser / CC BY-SA 3.0':({'film-rvp':'RVP · 粗笔、斜切角与柔和曝光边缘','film-phoenix':'Phoenix · 方形连续印字，参考实拍重绘','film-kodak':'Kodak · 粗实字形，以 Barlow 为基础调整','film-cine':'CineStill · 细等宽连印字，参考实拍重绘'}[style])|| (style.startsWith('film-')?'自绘胶片字样 · 曝光印字的近似模拟':'实际导出字形 · 放大查看');
}
function syncBackground(){const mode=state.config.background.mode;for(const el of document.querySelectorAll('[data-bg]'))el.hidden=!el.dataset.bg.split(' ').includes(mode);$('preview-wrap').classList.toggle('transparent',mode==='transparent'||state.config.background.opacity<1);$('separation-strength-field').hidden=state.config.strip.separation==='none';$('separation-holes-field').hidden=state.config.strip.separation==='none'||!state.config.strip.sprockets;$('shadow-tone-field').hidden=!['shadow','lift','paper'].includes(state.config.strip.separation);}
function syncBackgroundOptions(){const sel=$('background-source');sel.replaceChildren();for(const id of state.order){const item=state.items.find(i=>i.id===id);if(!item)continue;const o=document.createElement('option');o.value=String(id);o.textContent=item.name;sel.append(o);}const custom=document.createElement('option');custom.value='custom';custom.textContent='自定义背景照片';custom.disabled=!state.hasBackground;sel.append(custom);if(state.config.background.sourceIndex!=='custom'&&!state.order.includes(Number(state.config.background.sourceIndex)))state.config.background.sourceIndex=state.order[0]??0;sel.value=String(state.config.background.sourceIndex);}
function renderFrames(){
  const list=$('frame-list'),scroll=list.scrollTop,focused=document.activeElement?.closest('.frame-item');
  const focusId=focused?.dataset.id,focusCheckbox=document.activeElement?.type==='checkbox';
  list.replaceChildren();
  for(const item of state.items){
    const selected=state.order.includes(item.id),row=document.createElement('div');
    row.className='frame-item';row.dataset.id=String(item.id);row.dataset.active=String(state.active===item.id);row.draggable=!state.preparing;
    row.setAttribute('role','listitem');row.tabIndex=0;row.setAttribute('aria-label',`${item.name}，${selected?'已选':'未选'}，点击编辑，Alt 加方向键排序`);
    const check=document.createElement('input');check.type='checkbox';check.checked=selected;check.disabled=state.preparing;check.setAttribute('aria-label',`选择 ${item.name}`);
    check.addEventListener('click',e=>e.stopPropagation());check.addEventListener('change',()=>transaction(()=>{
      const ids=new Set(state.order);check.checked?ids.add(item.id):ids.delete(item.id);state.order=SheetModel.selectionInOrder(state.items,[...ids]);
    }));
    const im=document.createElement('img');im.src=item.thumb||`/api/sheet/thumb/${state.job}/${item.id}`;im.alt='';im.loading='lazy';
    const meta=document.createElement('div'),title=document.createElement('span'),origin=document.createElement('span');
    title.className='frame-title';title.textContent=item.name;title.title=item.name;origin.className='frame-source';
    origin.textContent=({export:'已导出成片',saved:'按保存参数生成',import:'导入照片'})[item.source]||'照片';meta.append(title,origin);
    const grip=document.createElement('span');grip.className='frame-grip';grip.textContent=String(state.order.indexOf(item.id)+1||'');row.append(check,im,meta,grip);
    row.addEventListener('click',()=>activateFrame(item.id));
    row.addEventListener('keydown',e=>{
      if(e.target!==row)return;
      if(e.key==='Enter'){e.preventDefault();activateFrame(item.id);}
      if(['ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();const delta=e.key==='ArrowUp'?-1:1;
        if(e.altKey){state.active=item.id;moveFrame(delta);}else{const next=state.items[state.items.indexOf(item)+delta];if(next){activateFrame(next.id);if(window.innerWidth>800)list.querySelector(`[data-id="${next.id}"]`)?.focus();}}
      }
    });
    row.addEventListener('dragstart',e=>{e.dataTransfer.setData('text/plain',String(item.id));e.dataTransfer.effectAllowed='move';});
    row.addEventListener('dragover',e=>{if(state.preparing)return;e.preventDefault();row.classList.add('drag-over');});
    row.addEventListener('dragleave',()=>row.classList.remove('drag-over'));
    row.addEventListener('drop',e=>{
      e.preventDefault();row.classList.remove('drag-over');if(state.preparing)return;
      const from=Number(e.dataTransfer.getData('text/plain'));if(!Number.isInteger(from)||!state.items.some(i=>i.id===from)||from===item.id)return;
      transaction(()=>{const a=state.items.findIndex(i=>i.id===from),b=state.items.findIndex(i=>i.id===item.id);const [moved]=state.items.splice(a,1);state.items.splice(b,0,moved);state.order=SheetModel.selectionInOrder(state.items,state.order);});
    });list.append(row);
  }
  if(!state.items.length){const p=document.createElement('p');p.className='form-note';p.textContent=state.preparing?'正在读取照片…':'选择文件夹或导入照片。';list.append(p);}
  list.scrollTop=scroll;
  if(focusId){const row=list.querySelector(`[data-id="${focusId}"]`);(focusCheckbox?row?.querySelector('input'):row)?.focus({preventScroll:true});}
  $('frame-count').textContent=`${state.order.length} / ${state.items.length}`;
  $('export-sheet').disabled=!state.order.length||state.exporting||state.preparing;$('save-project').disabled=!state.order.length||state.preparing;
  $('view-frame').disabled=!state.items.length||state.preparing;
  for(const id of ['select-all','select-none','reverse-order'])$(id).disabled=state.preparing||!state.items.length;updateUndo();
  syncBackgroundOptions();syncLeader();syncFrameControls();window.SheetFrame?.draw();
}
function activateFrame(id){
  if(state.preparing)return;state.active=id;
  for(const row of document.querySelectorAll('.frame-item'))row.dataset.active=String(Number(row.dataset.id)===id);
  syncFrameControls();window.SheetFrame?.setView('frame');if(window.SheetUI)window.SheetUI.close(false);else document.body.classList.remove('frames-open');saveDraft();
}
function frameConfig(){return state.frames[state.active]||{};}
function frameRotation(f=frameConfig()){
  const item=state.items.find(item=>item.id===state.active);
  return SheetModel.frameRotation(item?.width||0,item?.height||0,f);
}
function syncFrameControls(){
  const item=state.items.find(i=>i.id===state.active),f=frameConfig(),index=state.items.indexOf(item),disabled=!item||state.preparing;
  $('active-frame-name').textContent=item?.name||'未选择';$('frame-label').value=f.label||'';$('frame-fit').value=f.fit||'';
  $('frame-scale').value=f.crop?.scale||1;$('frame-scale-value').textContent=`${Number(f.crop?.scale||1).toFixed(2)}×`;
  $('frame-x').value=f.crop?.x??.5;$('frame-y').value=f.crop?.y??.5;
  $('frame-x-value').textContent=`${Math.round((f.crop?.x??.5)*100)}%`;$('frame-y-value').textContent=`${Math.round((f.crop?.y??.5)*100)}%`;
  for(const id of ['frame-up','frame-down','frame-rotate-left','frame-rotate-right','frame-label','frame-fit','frame-scale','frame-x','frame-y','frame-reset','frame-toggle-selected'])$(id).disabled=disabled;
  $('frame-up').disabled=disabled||index<=0;$('frame-down').disabled=disabled||index===state.items.length-1;
  $('frame-prev').disabled=disabled||index<=0;$('frame-next').disabled=disabled||index===state.items.length-1;
  $('frame-position').textContent=item?`${index+1} / ${state.items.length}`:'未选择';
  $('frame-toggle-selected').textContent=state.order.includes(state.active)?'移出排版':'加入排版';window.SheetUI?.syncRanges();
}
function moveFrame(delta){
  if(state.preparing)return;transaction(()=>{const i=state.items.findIndex(item=>item.id===state.active);if(i<0||i+delta<0||i+delta>=state.items.length)return;
  [state.items[i],state.items[i+delta]]=[state.items[i+delta],state.items[i]];state.order=SheetModel.selectionInOrder(state.items,state.order);});
}
function selectPane(name){
  for(const tab of document.querySelectorAll('[data-pane]')){const active=tab.dataset.pane===name;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;}
  for(const pane of document.querySelectorAll('.inspector-pane'))pane.hidden=pane.id!==`pane-${name}`;
  document.querySelector('.inspector-content').scrollTop=0;
  if(name==='frame')window.SheetFrame?.setView('frame',false);
}
let previewTimer;
function payload(){const config=clone(state.config);config.frameOverrides=state.order.map(id=>clone(state.frames[id]||{}));if(config.background.sourceIndex!=='custom')config.background.sourceIndex=Math.max(0,state.order.indexOf(Number(config.background.sourceIndex)));return {job:state.job,order:state.order.slice(),stockId:state.stockId,config};}
function queuePreview(){
  state.previewSeq++;state.previewWanted=true;clearTimeout(previewTimer);
  if(!state.order.length){state.controller?.abort();state.previewWanted=false;showEmptySelection();return;}
  $('sheet-preview').classList.add('is-pending');previewTimer=setTimeout(renderPreview,220);window.SheetFrame?.draw();
}
function showEmptySelection(){
  $('sheet-preview').hidden=true;$('sheet-preview').classList.remove('is-pending');$('empty-sheet').hidden=state.view==='frame';
  $('empty-sheet').querySelector('h1').textContent='选择要展示的照片';$('empty-sheet').querySelector('p').textContent='在照片列表勾选照片，把它们加入整卷排版。';
  $('preview-size').textContent='';$('export-dimensions').textContent='尚未选择照片';status('尚未选择照片');
}
async function renderPreview(){
  if(!state.job||state.preparing)return;
  if(!state.order.length){showEmptySelection();return;}
  if(state.previewBusy){state.previewWanted=true;return;}
  state.previewBusy=true;state.previewWanted=false;const sequence=state.previewSeq,body=payload(),count=body.order.length;
  const controller=new AbortController();state.controller=controller;$('sheet-preview').classList.add('is-pending');
  try{
    const r=await fetch('/api/sheet/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:controller.signal});
    if(!r.ok||r.headers.get('content-type')?.includes('json')){const d=await r.json();throw new Error(d.error||d.err||'预览失败，请点击刷新预览重试');}
    const outputWidth=Number(r.headers.get('X-Sheet-Width'))||body.config.width,outputHeight=Number(r.headers.get('X-Sheet-Height')),blob=await r.blob();
    if(sequence!==state.previewSeq||body.job!==state.job||state.preparing||!state.order.length)return;
    const url=URL.createObjectURL(blob),old=state.previewUrl;state.previewUrl=url;const im=$('sheet-preview');
    im.onload=()=>{if(sequence!==state.previewSeq)return;const height=outputHeight||Math.round(outputWidth*im.naturalHeight/im.naturalWidth);
      $('preview-size').textContent=`${outputWidth} × ${height} px`;$('export-dimensions').textContent=`${count} 张 · ${outputWidth} × ${height} px`;};
    im.src=url;im.hidden=state.view==='frame';$('empty-sheet').hidden=true;if(old)URL.revokeObjectURL(old);
    $('preview-name').textContent=state.label||'整卷预览';status(`预览已更新 · ${count} 张照片`);syncZoom();
  }catch(e){if(e.name!=='AbortError'&&sequence===state.previewSeq)status(e.message,true);}
  finally{
    state.previewBusy=false;if(sequence===state.previewSeq)$('sheet-preview').classList.remove('is-pending');
    if(state.previewWanted&&!state.preparing&&state.order.length){clearTimeout(previewTimer);previewTimer=setTimeout(renderPreview,60);}
  }
}
function syncZoom(){
  const im=$('sheet-preview'),enlarged=state.zoom>1&&state.view!=='frame';$('preview-wrap').classList.toggle('is-zoomed',enlarged);
  for(const id of ['zoom-in','zoom-out','zoom-fit'])$(id).disabled=state.view==='frame';
  if(!enlarged){im.style.maxWidth='100%';im.style.maxHeight='100%';im.style.width='auto';im.style.height='auto';$('zoom-label').textContent=state.view==='frame'?'单张构图':'全卷';}
  else{im.style.maxWidth='none';im.style.maxHeight='none';im.style.width=`${Math.round(($('preview-wrap').clientWidth-60)*state.zoom)}px`;im.style.height='auto';$('zoom-label').textContent=`${Math.round(state.zoom*100)}%`;}
}
async function prepare(input,project=null){
  const sequence=beginPrepare('正在读取已导出照片与保存的调整…');
  try{const d=await post('/api/sheet/prepare',input);if(sequence===state.prepareSeq)await awaitJob(d.job,sequence,project);}
  catch(e){failPrepare(sequence,e);}
}
function beginPrepare(message){
  const sequence=++state.prepareSeq;state.preparing=true;state.previewSeq++;state.previewWanted=false;clearTimeout(previewTimer);state.controller?.abort();
  $('prepare-progress').hidden=false;$('prepare-progress').querySelector('i').style.width='0%';$('sheet-preview').classList.add('is-pending');
  renderFrames();status(message);return sequence;
}
function failPrepare(sequence,error){
  if(sequence!==state.prepareSeq)return;state.preparing=false;$('prepare-progress').hidden=true;$('sheet-preview').classList.remove('is-pending');renderFrames();
  status(error.message||'读取失败，请重新选择照片或载入项目包',true);
}
async function awaitJob(job,sequence,project){
  for(;;){
    if(sequence!==state.prepareSeq)return;const d=await jsonRequest(`/api/sheet/job/${job}`);if(sequence!==state.prepareSeq)return;
    status(d.message||`正在准备 ${d.done||0}/${d.total||0}`);$('prepare-progress').querySelector('i').style.width=`${Math.round((d.done||0)/Math.max(1,d.total||1)*100)}%`;
    if(d.state==='failed')throw new Error(d.error||d.err||d.message||'照片准备失败');
    if(d.state==='ready'){
      if(project){
        const expected=project.allSources||project.sources||[],available=new Set((d.items||[]).map(item=>item.path));
        const missing=expected.filter(path=>!available.has(path));
        if(missing.length)throw new Error(`缺少 ${missing.length} 张照片，请恢复原文件或重新载入项目包；原草稿已保留`);
      }
      const previousDirectory=state.directory;state.job=job;state.items=d.items||[];state.order=state.items.map(i=>i.id);state.active=state.order[0]??null;
      state.directory=d.directory||'';state.label=project?.label||project?.config?.header?.title||d.label||'整卷预览';state.hasBackground=!!d.hasBackground;
      if(!state.hasBackground)$('background-file').textContent='';state.preparing=false;$('prepare-progress').hidden=true;
      $('source-label').textContent=state.directory||'导入的照片';$('sheet-directory').value=state.directory;
      const counts={export:0,saved:0,import:0};for(const item of state.items)counts[item.source]=(counts[item.source]||0)+1;
      $('source-summary').textContent=`${counts.export} 张成片 · ${counts.saved} 张按参数生成 · ${counts.import} 张导入`;
      if(project){
        state.config=mergeConfig(project.config);state.stockId=state.stocks.some(s=>s.id===project.stockId)?project.stockId:state.stockId;
        const restored=SheetModel.restoreDraft(state.items,project);Object.assign(state,{items:restored.items,order:restored.order,frames:restored.frames,active:restored.active});state.config.background.sourceIndex=restored.backgroundSource;
        if(!state.hasBackground&&state.config.background.sourceIndex==='custom'){state.config.background.sourceIndex=state.order[0]??0;$('background-file').textContent='自定义背景可通过载入项目包恢复';}
      }else{
        state.frames={};const match=guessStock(state.label);
        if(previousDirectory!==state.directory){state.config.header.title=state.label;state.config.header.process='';if(match)applyStock(match.id);else state.config.header.process=stock().process||'';}
        const date=state.label.match(/\d{4}-\d{2}-\d{2}/)?.[0];if(date)state.config.header.date=date;state.config.background.sourceIndex=state.order[0]??0;
      }
      state.history=[];state.future=[];state.lastCommitted=snapshot();syncControls();renderFrames();saveDraft();await renderPreview();
      if(sequence===state.prepareSeq&&d.warnings?.length)status(`已载入 ${state.items.length} 张；${d.warnings.slice(0,2).join('；')}`,true);return;
    }
    await new Promise(resolve=>setTimeout(resolve,400));
  }
}
function mergeConfig(incoming){const c=clone(defaults);if(!incoming||typeof incoming!=='object')return c;for(const key of ['width','columns','ratio','spacing','margin'])if(incoming[key]!==undefined)c[key]=incoming[key];for(const key of ['background','strip','header'])if(incoming[key]&&typeof incoming[key]==='object')Object.assign(c[key],incoming[key]);return c;}
function guessStock(label){const q=label.toLowerCase().replace(/\s/g,'');if(q.includes('福马')||q.includes('foma')){const iso=q.includes('400')?400:q.includes('200')?200:100;return state.stocks.find(s=>s.brand.toLowerCase().includes('foma')&&s.iso===iso&&s.name.toLowerCase().includes('fomapan'));}if(q.includes('乐凯')||q.includes('lucky'))return state.stocks.find(s=>s.name.toLowerCase().includes('shd')&&s.iso===(q.includes('100')?100:400));if(q.includes('gold'))return state.stocks.find(s=>s.id.includes('gold-200'));return null;}
async function pickDirectory(){try{const d=await jsonRequest('/api/pick?mode=dir');if(d.path)prepare({directory:d.path});}catch(e){status(e.message,true);}}
async function uploadPhotos(files){
  if(!files.length)return;const sequence=beginPrepare(`正在导入 ${files.length} 张照片…`);
  try{const form=new FormData();for(const file of files)form.append('files',file);const d=await jsonRequest('/api/sheet/upload',{method:'POST',body:form});if(sequence===state.prepareSeq)await awaitJob(d.job,sequence,null);}
  catch(e){failPrepare(sequence,e);}
}
async function exportSheet(){if(state.exporting||state.preparing||!state.order.length)return;state.exporting=true;$('export-sheet').disabled=true;const label=$('export-sheet').firstChild;label.textContent='正在导出…';try{const body=payload();body.format=$('export-format').value;body.out=$('export-out').value.trim();if((body.config.background.mode==='transparent'||body.config.background.opacity<1)&&body.format==='jpg')status('JPEG 将透明区域合成白色背景');const d=await post('/api/sheet/export',body);for(;;){const r=await jsonRequest(`/api/sheet/export/${d.export}`);status(r.message||'正在生成高清整卷图片…');if(r.state==='failed')throw new Error(r.error||r.err||'导出失败');if(r.state==='ready'){status(`已保存：${r.out}`);$('last-export').hidden=false;$('last-export-path').textContent=r.out;$('download-last-export').href=`/api/sheet/download/${d.export}`;$('download-last-export').download='';const a=document.createElement('a');a.href=`/api/sheet/download/${d.export}`;a.download='';document.body.append(a);a.click();a.remove();break;}await new Promise(resolve=>setTimeout(resolve,500));}}catch(e){status(e.message,true);}finally{state.exporting=false;label.textContent='导出整卷图片';renderFrames();}}
function downloadObject(obj,filename){const url=URL.createObjectURL(new Blob([JSON.stringify(obj,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function savedPresets(){try{return JSON.parse(localStorage.getItem('nm.sheet.presets')||'{}');}catch(e){return {};}}
function presetOptions(){const select=$('saved-preset');select.replaceChildren();const first=document.createElement('option');first.value='';first.textContent='选择版式';select.append(first);for(const name of Object.keys(savedPresets())){const o=document.createElement('option');o.value=name;o.textContent=name;select.append(o);}}
for(const el of document.querySelectorAll('[data-config]')){
  const handler=e=>{
    if(el.dataset.color!==undefined){
      if(e.type!=='change')return;
      const normalized=SheetModel.normalizeHex(el.value);
      if(!normalized){
        el.setAttribute('aria-invalid','true');
        if(e.type==='change'){el.value=get(state.config,el.dataset.config);el.removeAttribute('aria-invalid');status('请输入 #RRGGBB 色值，已保留上次颜色',true);}
        return;
      }
      if(e.type==='change')el.value=normalized;
    }
    if(el.type==='number' &&(el.value.trim()===''||!el.checkValidity())){
      el.setAttribute('aria-invalid','true');
      if(e.type==='change'){el.value=get(state.config,el.dataset.config);el.removeAttribute('aria-invalid');status('请输入允许范围内的数值，已保留上次设置',true);}
      return;
    }
    el.removeAttribute('aria-invalid');
    let value;
    if(el.type==='checkbox')value=el.checked;
    else if(el.dataset.kind==='boolean')value=el.value==='true';
    else if(el.type==='range'||el.type==='number'||['width','columns','spacing','margin','background.angle'].includes(el.dataset.config))value=Number(el.value);
    else if(el.dataset.config==='background.sourceIndex')value=el.value==='custom'?'custom':Number(el.value);
    else value=el.dataset.color!==undefined?SheetModel.normalizeHex(el.value):el.value;
    set(state.config,el.dataset.config,value);if(e.type==='change')commit(state.lastCommitted);syncControls();queuePreview();
  };
  el.addEventListener('input',handler);
  if(el.type==='number')el.addEventListener('blur',()=>{if(el.getAttribute('aria-invalid')==='true')handler({type:'change'});});
  if(el.type!=='checkbox')el.addEventListener('change',handler);else el.addEventListener('change',()=>commit(state.lastCommitted));
}
$('stock-search').addEventListener('input',()=>stockOptions($('stock-search').value));$('stock-select').addEventListener('change',()=>transaction(()=>applyStock($('stock-select').value)));
for(const tab of document.querySelectorAll('[data-pane]')){tab.addEventListener('click',()=>selectPane(tab.dataset.pane));tab.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();const tabs=[...document.querySelectorAll('[data-pane]')];const next=tabs[(tabs.indexOf(tab)+(e.key==='ArrowRight'?1:tabs.length-1))%tabs.length];selectPane(next.dataset.pane);next.focus();});}
$('choose-directory').onclick=pickDirectory;$('empty-open').onclick=pickDirectory;$('import-photos').onclick=()=>$('photo-input').click();$('photo-input').onchange=()=>{uploadPhotos([...$('photo-input').files]);$('photo-input').value='';};$('directory-form').onsubmit=e=>{e.preventDefault();const directory=$('sheet-directory').value.trim();if(directory)prepare({directory});};
$('select-all').onclick=()=>transaction(()=>state.order=state.items.map(i=>i.id));$('select-none').onclick=()=>transaction(()=>state.order=[]);$('reverse-order').onclick=()=>transaction(()=>{state.items.reverse();state.order.reverse();});$('frame-up').onclick=()=>moveFrame(-1);$('frame-down').onclick=()=>moveFrame(1);
function editFrame(action){if(state.active===null||state.preparing)return;transaction(()=>{state.frames[state.active]??={};action(state.frames[state.active]);});}
$('frame-rotate-left').onclick=()=>editFrame(f=>f.rotation=(frameRotation(f)+270)%360);$('frame-rotate-right').onclick=()=>editFrame(f=>f.rotation=(frameRotation(f)+90)%360);$('frame-label').onchange=()=>editFrame(f=>f.label=$('frame-label').value);$('frame-fit').onchange=()=>editFrame(f=>f.fit=$('frame-fit').value||undefined);
for(const [id,key] of [['frame-scale','scale'],['frame-x','x'],['frame-y','y']]){
  $(id).oninput=()=>{if(state.active===null||state.preparing)return;const f=state.frames[state.active]??={};f.crop??={x:.5,y:.5,scale:1};f.crop[key]=Number($(id).value);syncFrameControls();window.SheetFrame?.draw();queuePreview();};
  $(id).onchange=()=>commit(state.lastCommitted);
}
$('frame-reset').onclick=()=>editFrame(f=>{delete f.rotation;delete f.crop;delete f.fit;});
$('frame-toggle-selected').onclick=()=>transaction(()=>{const ids=new Set(state.order);ids.has(state.active)?ids.delete(state.active):ids.add(state.active);state.order=SheetModel.selectionInOrder(state.items,[...ids]);});
$('layout-preset').onchange=()=>transaction(()=>{const choice=$('layout-preset').value;state.config.columns=6;state.config.strip.sprockets=true;state.config.strip.opacity=1;state.config.strip.leader=choice==='film';state.config.header.enabled=true;if(choice==='film'){state.config.background.mode='blur';state.config.strip.color='#080808';state.config.spacing=38;state.config.margin=90;}if(choice==='archive'){state.config.background.mode='solid';state.config.background.color='#f1efea';state.config.strip.color='#1a1511';state.config.strip.edgeColor='#e1b674';state.config.spacing=46;state.config.margin=140;}if(choice==='gallery'){state.config.background.mode='solid';state.config.background.color='#202422';state.config.strip.color='#0c0e0d';state.config.spacing=60;state.config.margin=140;}});
$('custom-background').onclick=()=>{if(!state.job||state.preparing){status('先载入一卷照片',true);return;}$('background-input').click();};
$('background-input').onchange=async()=>{
  const file=$('background-input').files[0];if(!file||state.preparing)return;
  const job=state.job,sequence=state.prepareSeq;
  const current=()=>job===state.job&&sequence===state.prepareSeq;
  try{
    status('正在读取背景照片…');const form=new FormData();form.append('job',job);form.append('file',file);
    await jsonRequest('/api/sheet/background',{method:'POST',body:form});if(!current())return;
    transaction(()=>{state.hasBackground=true;state.config.background.sourceIndex='custom';state.config.background.mode='blur';});$('background-file').textContent=file.name;
  }catch(e){if(current())status(e.message,true);}finally{$('background-input').value='';}
};
$('undo').onclick=()=>{if(!state.history.length)return;state.future.push(snapshot());restore(state.history.pop());};$('redo').onclick=()=>{if(!state.future.length)return;state.history.push(snapshot());restore(state.future.pop());};$('zoom-in').onclick=()=>{state.zoom=Math.min(3,state.zoom+.25);syncZoom();};$('zoom-out').onclick=()=>{state.zoom=Math.max(1,state.zoom-.25);syncZoom();};$('zoom-fit').onclick=()=>{state.zoom=1;syncZoom();};$('refresh-preview').onclick=renderPreview;$('export-sheet').onclick=exportSheet;
document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='z'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){e.preventDefault();(e.shiftKey?$('redo'):$('undo')).click();}});
$('save-project').onclick=async()=>{
  if(state.preparing)return;if(!state.items.length||!state.order.length){status('先选择照片再保存项目',true);return;}
  $('save-project').disabled=true;status('正在打包照片、背景和排版参数…');
  try{
    const r=await fetch('/api/sheet/project/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});
    if(!r.ok){const d=await r.json();throw new Error(d.error||d.err||'项目打包失败');}
    const url=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=url;a.download=`${state.label||'整卷排版'}.nmproject.zip`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);status('项目已打包，包含照片、背景和排版参数');
  }catch(e){status(e.message,true);}finally{$('save-project').disabled=false;}
};
$('load-project').onclick=()=>$('project-input').click();
$('project-input').onchange=async()=>{
  const file=$('project-input').files[0];if(!file)return;let seq=null;
  try{
    if(file.name.toLowerCase().endsWith('.zip')){
      if(file.size>500*1024*1024)throw new Error('项目包超过 500 MB，请选择较小的项目');
      seq=beginPrepare('正在载入项目包…');const form=new FormData();form.append('file',file);
      const d=await jsonRequest('/api/sheet/project/import',{method:'POST',body:form});if(seq===state.prepareSeq)await awaitJob(d.job,seq,d.project);
    }else{
      if(file.size>2*1024*1024)throw new Error('JSON 项目文件过大，请选择排版项目');const p=JSON.parse(await file.text());
      if(p.type!=='NegativeMasterSheet'||p.version!==1||!Array.isArray(p.sources)||!p.sources.length||p.sources.length>240||p.sources.some(v=>typeof v!=='string'))throw new Error('这不是有效的 NegativeMaster 排版项目');await prepare({paths:p.sources},p);
    }
  }catch(e){if(seq===null)status(e.message,true);else failPrepare(seq,e);}finally{$('project-input').value='';}
};
$('save-preset').onclick=()=>{const name=$('preset-name').value.trim();if(!name){status('先填写版式名称',true);return;}const presets=savedPresets();const c=clone(state.config);c.header=Object.assign({},c.header,{title:'',roll:'',camera:'',lens:'',date:'',notes:''});presets[name]={config:c,stockId:state.stockId};try{localStorage.setItem('nm.sheet.presets',JSON.stringify(presets));presetOptions();$('saved-preset').value=name;status(`已保存版式：${name}`);}catch(e){status('浏览器存储已满，请导出项目保存',true);}};$('saved-preset').onchange=()=>{const p=savedPresets()[$('saved-preset').value];if(!p)return;transaction(()=>{const info=clone(state.config.header);state.config=mergeConfig(p.config);for(const k of ['title','roll','camera','lens','date','notes'])state.config.header[k]=info[k];state.stockId=p.stockId;});$('preset-name').value=$('saved-preset').value;};$('delete-preset').onclick=()=>{const name=$('saved-preset').value;if(!name){status('先选择已存版式',true);return;}const p=savedPresets();delete p[name];localStorage.setItem('nm.sheet.presets',JSON.stringify(p));presetOptions();status(`已删除版式：${name}`);};
async function init(){
  try{
    const c=await jsonRequest('/api/sheet/catalog');state.stocks=c.stocks||[];state.stockId=state.stocks.find(s=>s.id==='kodak-gold-200')?.id||state.stocks[0]?.id||'';applyStock(state.stockId);
    let draft=null;try{draft=JSON.parse(localStorage.getItem('nm.sheet.draft')||'null');}catch(e){}
    if(draft){state.directory=draft.directory||'';state.config=mergeConfig(draft.config);if(state.stocks.some(s=>s.id===draft.stockId))state.stockId=draft.stockId;}
    syncControls();presetOptions();selectPane('film');state.lastCommitted=snapshot();
    let seed=null;try{seed=JSON.parse(sessionStorage.getItem('nm.sheet.seed')||'null');sessionStorage.removeItem('nm.sheet.seed');}catch(e){}
    if(seed?.paths?.length){await prepare({paths:seed.paths});return;}
    if(seed?.directory){await prepare({directory:seed.directory});return;}
    if(draft?.job){try{const previous=await jsonRequest(`/api/sheet/job/${draft.job}`);if(previous.state==='ready'){const seq=beginPrepare('正在恢复上次排版…');await awaitJob(draft.job,seq,draft);return;}}catch(e){}}
    const sources=draft?.allSources||draft?.sources;
    if(sources?.length){await prepare({paths:sources,positiveOnly:!!draft.positiveOnly},draft);return;}
    if(draft?.directory){await prepare({directory:draft.directory},draft);return;}
    const listed=await jsonRequest('/api/list');if(listed.dirs?.length)await prepare({directory:listed.dirs[0]});else status('选择胶卷文件夹或导入成片开始');
  }catch(e){status(e.message,true);}
}
window.addEventListener("DOMContentLoaded",init);

$('reroll-leak').onclick=()=>transaction(()=>{state.config.strip.leakSeed=(state.config.strip.leakSeed+7919)%1000000;});
