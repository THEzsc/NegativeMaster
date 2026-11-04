/* Browser workbench: shared engine operations, bounded previews and explicit scopes. */
(() => {
  const M=window.NMDevelopModel,panel=$('panel'),rail=$('negative-rail');
  const sectionOf=id=>$(id).closest('details.sec');
  function section(title,id){const d=document.createElement('details');d.className='sec';d.id=id;d.innerHTML=`<summary>${title}</summary><div class="bd"></div>`;panel.append(d);return d;}
  function button(label,id,fn,parent){const b=document.createElement('button');b.type='button';b.id=id;b.textContent=label;b.onclick=fn;parent.append(b);return b;}
  function moveControl(id,to){const x=$(id);to.append(x.previousElementSibling,x);}
  const basic=sectionOf('exposure'),white=sectionOf('temp'),crop=sectionOf('fmts');
  basic.querySelector('summary').textContent='基本';crop.querySelector('summary').textContent='裁剪与旋转';crop.open=false;
  for(const id of ['contrast','vibrance']){const control=$(id),label=control.previousElementSibling, before=$(id==='contrast'?'highlights':'saturation').previousElementSibling;before.before(label,control);}
  basic.querySelector('.bd').prepend(...white.querySelector('.bd').children);white.remove();
  const detail=sectionOf('sharpen'),effects=section('效果','effects');moveControl('vignette',effects.querySelector('.bd'));detail.querySelector('summary').textContent='细节';
  sectionOf('hslh').querySelector('summary').textContent='颜色混合 · HSL';
  sectionOf('curve').querySelector('summary').textContent='色调曲线';
  sectionOf('black_pct').querySelector('summary').textContent='反转与色阶';
  sectionOf('resetdefault').querySelector('summary').textContent='输入';
  const sync=section('同步调整','selective-sync');sync.querySelector('.bd').innerHTML='<div id="sync-groups"></div><label class="row">范围<select id="sync-scope"><option value="selected">所选照片</option><option value="roll">当前整卷</option></select></label><button id="sync-apply">同步所选项目</button>';
  $('applyroll').remove();$('wbroll').remove();
  const cropTools=document.createElement('div');cropTools.className='btnrow';cropTools.append($('autocrop'),$('cropref').parentElement);crop.querySelector('.bd').prepend(cropTools);
  crop.querySelector('.bd').append(document.querySelector('#rotpad .rotgroup'));
  button('整卷自动裁剪','roll-crop',()=>analyzeRoll('crop'),crop.querySelector('.bd'));
  const order=[sectionOf('hist'),crop,basic,sectionOf('curve'),sectionOf('hslh'),detail,effects,$('workflow-assistant'),sectionOf('black_pct'),sectionOf('pbase'),sectionOf('ref'),...panel.querySelectorAll('details.sec')];
  const unique=[...new Set(order)],exp=sectionOf('export'),input=sectionOf('resetdefault');
  for(const d of unique.filter(d=>d!==exp&&d!==input&&d!==sync))panel.append(d);
  panel.append(input,sync,exp,$('status'));
  for(const d of panel.querySelectorAll('details.sec')){
    if(d!==basic&&d!==sectionOf('hist'))d.open=false;
    const key='nm.panel.'+d.querySelector('summary').textContent;
    const saved=localStorage.getItem(key);if(saved!==null)d.open=saved==='1';
    d.addEventListener('toggle',()=>{localStorage.setItem(key,d.open?'1':'0');if(d===crop&&loaded){resetView();fitWrap();}});
  }
  // Wrap existing inputs instead of replacing their handlers.
  for(const range of panel.querySelectorAll('input[type=range]')){
    const label=range.previousElementSibling;if(!label?.matches('label.row'))continue;
    const row=document.createElement('div');row.className='compact-adjustment';label.before(row);row.append(label,range);
    range.setAttribute('aria-label',label.textContent.trim());
    range.addEventListener('pointerdown',()=>interactive=true);
    range.addEventListener('input',()=>{interactive=true;clearTimeout(settle);settle=setTimeout(()=>{interactive=false;render();},180);});
    range.addEventListener('change',()=>{interactive=false;clearTimeout(settle);render();});
  }
  $('resetdefault').parentElement.lastChild.textContent='每张从默认参数开始';
  $('helpbtn').title='快捷键与使用说明';$('helpbtn').textContent='帮助';
  const film=$('workflow-assistant');
  $('emulsion').onchange=()=>{
    if(!loaded)return;
    const enabled=$('emulsion').checked,old=typeof P.emulsion_mirrored==='boolean'?P.emulsion_mirrored:['h','v'].includes(P.flip);
    if(old!==enabled)rotateImage(P.rotate%180?'v':'h');
    P.emulsion_mirrored=enabled;render();if($('film-roll').checked)filmApply({emulsion:enabled});
  };
  for(const b of $('modes').children){const original=b.onclick;b.onclick=()=>{original();if($('film-roll').checked)filmApply({mode:P.mode});};}
  const presetChange=$('presel').onchange;
  $('presel').onchange=async e=>{try{await presetChange?.(e);}catch(error){stat(error.message);return;}if($('film-roll').checked&&e.target.value)filmApply({preset:e.target.value});};
  // Crop viewport: show full capture only while editing crop or taking a sample.
  let interactive=false,settle=null,detailTimer=null,detailBusy=false,detailVersion=0,detailShown='',detailURL=null;
  function editing(){return crop.open||pickWB||!!pickS||negOn;}
  function rect(){return editing()?{x0:0,y0:0,x1:1,y1:1}:cropN;}
  function fit(){
    const r=rect(),rw=Math.max(.001,r.x1-r.x0),rh=Math.max(.001,r.y1-r.y0),a=imgAspect()*rw/rh;
    const st=$('stage'),availW=Math.max(100,st.clientWidth-48),availH=Math.max(100,st.clientHeight-125);
    let w=availW,h=w/a;if(h>availH){h=availH;w=h*a;}
    const wr=$('imgwrap'),im=$('img');wr.style.width=w+'px';wr.style.height=h+'px';wr.style.overflow=editing()?'visible':'hidden';
    Object.assign(im.style,{position:'absolute',width:100/rw+'%',height:100/rh+'%',maxWidth:'none',left:-r.x0/rw*100+'%',top:-r.y0/rh*100+'%'});
    $('crop').hidden=!crop.open||negOn;drawCrop();drawWBRect();drawSamples();applyTransform();
  }
  function invalidateDetail(){detailVersion++;detailShown='';clearTimeout(detailTimer);}
  function queueDetail(){
    clearTimeout(detailTimer);if(!loaded||interactive||inflight||negOn||batchBusy)return;
    const r=rect(),side=Math.min(8192,Math.max(...dispWH()),Math.ceil(Math.max($('imgwrap').clientWidth/(r.x1-r.x0),$('imgwrap').clientHeight/(r.y1-r.y0))*Z*(devicePixelRatio||1)/256)*256);
    const signature=curFile+'|'+settingsSig()+'|'+side;if(side<=1500||signature===detailShown||detailBusy)return;
    detailTimer=setTimeout(async()=>{
      const version=detailVersion;detailBusy=true;
      try{
        const response=await fetch('/api/workbench/detail',{method:'POST',headers:HJ,body:JSON.stringify({path:curFile,params:params(),side})});
        if(!response.ok){if(response.status!==429)stat('高清预览暂不可用，可继续调片');return;}
        const blob=await response.blob();if(version!==detailVersion||negOn)return;
        const previous=detailURL;detailURL=URL.createObjectURL(blob);$('img').src=detailURL;detailShown=signature;
        if(previous)URL.revokeObjectURL(previous);
      }catch(e){stat('高清预览失败：'+e.message);}finally{detailBusy=false;if(version!==detailVersion)queueDetail();}
    },220);
  }
  function params(){return {...P,crop_rect:cropRect(),geometry_source:geometrySource};}
  for(const [id,op] of [['rotL','ccw'],['rotR','cw'],['fliph','h'],['flipv','v']])$(id).onclick=()=>rotateImage(op);
  function rotateImage(op){
    P=M.orient(params(),op);cropN=Object.fromEntries(['x0','y0','x1','y1'].map((k,i)=>[k,P.crop_rect[i]]));geometrySource='manual';
    if(['cw','ccw'].includes(op)){orient=orient==='land'?'port':'land';aspect=FMT[curFmt];if(aspect&&orient==='port')aspect=1/aspect;syncFmtPills();}
    refl();drawCrop();render();
  }
  // selection/filmstrip: ordinary click, Cmd/Ctrl toggle, Shift range, arrows.
  let anchor=null,thumbObserver,thumbRunning=false,thumbCancel=false;
  const railOptions=document.createElement('div');railOptions.className='rail-options';railOptions.innerHTML='<label><input type="checkbox" id="raw-only">只显示 RAW</label><button id="rail-position">移到底部</button><button id="warm-thumbs">生成缩略图</button>';
  $('files').before(railOptions);
  let rawExt=new Set(['.arw','.arq','.cr2','.cr3','.nef','.raf','.dng','.rw2']);
  function rows(){return [...document.querySelectorAll('#files .fitem')];}
  function visible(){return rows().filter(r=>r.style.display!=='none');}
  function scope(all=false){const a=visible(),chosen=a.filter(r=>r.querySelector('.fck').checked);return (all||!chosen.length?a:chosen).map(r=>r.dataset.path);}
  const oldFilter=applyFilter;applyFilter=()=>{oldFilter();if($('raw-only').checked)for(const row of rows())if(!rawExt.has('.'+row.dataset.path.split('.').pop().toLowerCase()))row.style.display='none';updateSelection();};
  $('raw-only').onchange=applyFilter;
  function remember(){try{sessionStorage.setItem('nm.develop.session',JSON.stringify({directory:$('dir').value,paths:rows().map(r=>r.dataset.path),selected:rows().filter(r=>r.querySelector('.fck').checked).map(r=>r.dataset.path),file:curFile}));}catch{}}
  const oldFill=fillFiles;fillFiles=(files,edited)=>{oldFill(files,edited);decorate();};
  function updateSelection(){for(const r of rows()){const checked=r.querySelector('.fck').checked;r.classList.toggle('selected',checked);r.setAttribute('aria-selected',String(checked));} }
  function select(row,e){
    const paths=visible().map(r=>r.dataset.path),chosen=rows().filter(r=>r.querySelector('.fck').checked).map(r=>r.dataset.path);
    const next=new Set(M.selection(paths,chosen,anchor,row.dataset.path,e.shiftKey,e.metaKey||e.ctrlKey));
    for(const r of rows())r.querySelector('.fck').checked=next.has(r.dataset.path);
    if(!e.shiftKey)anchor=row.dataset.path;updateSelection();remember();loadFile(row.dataset.path);
  }
  function decorate(){
    thumbObserver?.disconnect();thumbObserver=new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting){const im=entry.target;if(im.dataset.src){im.src=im.dataset.src;delete im.dataset.src;}thumbObserver.unobserve(im);}},{root:$('files'),rootMargin:'150px'});
    $('files').setAttribute('role','listbox');$('files').setAttribute('aria-multiselectable','true');
    for(const row of rows()){
      row.tabIndex=0;row.setAttribute('role','option');row.setAttribute('aria-label',LocalPaths.basename(row.dataset.path));
      const img=document.createElement('img');img.className='rail-thumb';img.alt='';img.dataset.src='/api/workbench/thumb?path='+encodeURIComponent(row.dataset.path);row.prepend(img);thumbObserver.observe(img);
      row.onclick=e=>select(row,e);row.querySelector('.fck').onchange=updateSelection;
      row.onkeydown=e=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();e.stopPropagation();const a=visible(),i=a.indexOf(row),n=a[i+(['ArrowRight','ArrowDown'].includes(e.key)?1:-1)];if(n){select(n,e);n.focus();}}else if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();removeRow(row);}else if(e.key==='Enter'){select(row,e);}};
      row.oncontextmenu=e=>{e.preventDefault();const menu=$('photo-context');menu.replaceChildren();button('从照片栏移除','remove-photo-row',()=>{removeRow(row);menu.close();},menu);menu.showModal();};
    }updateSelection();
  }
  function removeRow(row){if(batchBusy)return;const path=row.dataset.path;row.remove();[...$('fileselect').options].find(o=>o.value===path)?.remove();if(path===curFile){const next=visible()[0];if(next)loadFile(next.dataset.path);else{flushAutosave().catch(e=>stat(e.message));loaded=false;curFile='';$('imgwrap').style.display='none';$('empty').style.display='';}}updateNavButtons();remember();}
  const context=document.createElement('dialog');context.id='photo-context';context.onclick=e=>{if(e.target===context)context.close();};document.body.append(context);
  $('rail-position').onclick=()=>{document.body.classList.toggle('rail-bottom');localStorage.setItem('nm.rail.bottom',String(document.body.classList.contains('rail-bottom')));$('rail-position').textContent=document.body.classList.contains('rail-bottom')?'移到左侧':'移到底部';if(loaded)fit();};
  if(localStorage.getItem('nm.rail.bottom')==='true')$('rail-position').click();
  $('files').addEventListener('wheel',e=>{if(document.body.classList.contains('rail-bottom')&&Math.abs(e.deltaY)>Math.abs(e.deltaX)){e.preventDefault();$('files').scrollLeft+=e.deltaY;}},{passive:false});
  $('selall').addEventListener('click',updateSelection);$('selnone').addEventListener('click',updateSelection);
  $('warm-thumbs').onclick=async()=>{if(thumbRunning){thumbCancel=true;return;}thumbRunning=true;thumbCancel=false;$('warm-thumbs').textContent='停止生成';const paths=scope(true);try{for(let i=0;i<paths.length&&!thumbCancel;i++){const r=await fetch('/api/workbench/thumb?path='+encodeURIComponent(paths[i]));if(!r.ok)throw new Error('缩略图生成失败');await r.blob();stat(`缩略图 ${i+1}/${paths.length}`);}}catch(e){stat(e.message);}finally{thumbRunning=false;$('warm-thumbs').textContent='生成缩略图';}};
  async function api(action,body){const r=await fetch('/api/workbench/'+action,{method:'POST',headers:HJ,body:JSON.stringify(body)});const d=await r.json();if(!r.ok||d.ok===false)throw new Error(d.err||'操作失败');return d;}
  let plan=[],receipts=[],cancel=false;
  const jobs=section('整卷处理','roll-jobs');jobs.querySelector('.bd').innerHTML='<p id="roll-progress" role="status"></p><div id="roll-results"></div><div class="btnrow"><button id="roll-apply" disabled>应用勾选结果</button><button id="roll-stop" disabled>停止</button><button id="roll-undo" disabled>撤销整卷操作</button></div>';panel.insertBefore(jobs,sync);
  function lock(on){batchBusy=on;$('roll-stop').disabled=!on;$('roll-undo').disabled=on||!receipts.length;$('roll-apply').disabled=on||!plan.some(r=>r.patch);for(const node of [rail,$('stage'),...panel.querySelectorAll('details.sec')])if(node!==jobs)node.inert=on;}
  function progress(text){$('roll-progress').textContent=text;stat(text);}
  $('roll-stop').onclick=()=>cancel=true;
  function planRows(){const out=$('roll-results');out.replaceChildren();for(const row of plan){const label=document.createElement('label'),cb=document.createElement('input');cb.type='checkbox';cb.checked=!!row.patch;cb.disabled=!row.patch;cb.onchange=()=>row.include=cb.checked;row.include=cb.checked;label.append(cb,document.createTextNode(LocalPaths.basename(row.path)+' · '+row.note));out.append(label);}$('roll-apply').disabled=!plan.some(r=>r.patch);}
  async function analyzeRoll(kind,paths=scope(true)){
    if(batchBusy||!paths.length)return;jobs.open=true;cancel=false;plan=[];lock(true);$('roll-apply').disabled=true;
    try{await flushAutosave();for(let i=0;i<paths.length&&!cancel;i++){const path=paths[i];progress(`正在分析 ${i+1}/${paths.length}`);try{
      const snap=await api('snapshot',{path}),d=await api('analyze',{path,params:snap.params,kind,reference:$('cropref').checked}),r=d.report;
      const patch=kind==='crop'?(r.status!=='uncertain'&&r.rect?.length===4?{crop_rect:r.rect,level_angle:r.angle,geometry_source:'auto'}:null):M.gammaPatch(r);
      plan.push({path,token:snap.token,patch,note:patch?(kind==='crop'?'裁剪与校平':r.parameter_key+' '+r.recommendation.toFixed(2)):'需手动确认'});
    }catch(e){plan.push({path,note:e.message});}}planRows();progress(`分析完成 ${plan.length}/${paths.length}`);
    }catch(e){progress(e.message);}finally{lock(false);}
  }
  $('analyze-roll').onclick=()=>analyzeRoll('gamma');$('analyze-frame').onclick=()=>analyzeRoll('gamma',curFile?[curFile]:[]);
  async function applyRows(rows){if(batchBusy)return;cancel=false;lock(true);receipts=[];$('roll-apply').disabled=true;let done=0,errors=[];try{await flushAutosave();for(const row of rows){if(cancel)break;try{const d=await api('apply',row);if(d.undo_id)receipts.push(d.undo_id);markEdited(row.path);done++;}catch(e){row.note=e.message;errors.push(LocalPaths.basename(row.path)+': '+e.message);}progress(`已应用 ${done}/${rows.length}`);}if(curFile)await restoreCurrent();if(errors.length)progress(`已应用 ${done}/${rows.length}；`+errors.join('；'));}catch(e){progress(e.message);}finally{lock(false);$('roll-undo').disabled=!receipts.length;plan=[];}}
  $('roll-apply').onclick=()=>applyRows(plan.filter(r=>r.include&&r.patch));
  async function restoreCurrent(){const d=await api('snapshot',{path:curFile});P={...D,...d.params};cropN=d.data.cropN&&Object.keys(d.data.cropN).length?d.data.cropN:{x0:0,y0:0,x1:1,y1:1};geometrySource=d.params.geometry_source||'manual';lastSavedSig=settingsSig();window.NMWorkflow?.loaded();refl();render();}
  $('roll-undo').onclick=async()=>{if(batchBusy)return;lock(true);const pending=[];let count=0;try{for(const id of [...receipts].reverse())try{await api('undo',{undo_id:id});count++;}catch(e){pending.push(id);progress(e.message);}receipts=pending;if(curFile)await restoreCurrent();progress(`已撤销 ${count} 张${pending.length?'；'+pending.length+' 张参数已变化，未覆盖':''}`);}finally{lock(false);$('roll-undo').disabled=!receipts.length;}};
  async function applyScope(kind,extra,paths){if(batchBusy)return;if(!paths.length){stat('先选择照片');return;}jobs.open=true;cancel=false;lock(true);const targets=[];try{await flushAutosave();for(const path of paths){if(cancel)break;const snap=await api('snapshot',{path});targets.push({path,token:snap.token,kind,...extra});}}catch(e){progress(e.message);return;}finally{lock(false);}if(!cancel)await applyRows(targets);}
  function filmApply(extra){return applyScope('film',extra,scope(true));}
  $('sync-apply').onclick=()=>applyScope('sync',{groups:[...$('sync-groups').querySelectorAll('input:checked')].map(n=>n.value),source:params()},$('sync-scope').value==='roll'?scope(true):visible().filter(r=>r.querySelector('.fck').checked).map(r=>r.dataset.path));
  fetch('/api/workbench/catalog').then(r=>r.json()).then(d=>{rawExt=new Set(d.rawExtensions);for(const g of d.groups){const label=document.createElement('label'),c=document.createElement('input');c.type='checkbox';c.value=g.id;c.checked=g.selected;label.append(c,document.createTextNode(g.title));$('sync-groups').append(label);}}).catch(e=>stat(e.message));
  button('导入整卷排版','handoff-sheet',()=>handoff('sheet'),exp.querySelector('.bd'));
  button('添加到胶卷库','handoff-archive',()=>handoff('archive'),exp.querySelector('.bd'));
  async function handoff(mode){try{await flushAutosave();remember();sessionStorage.setItem('nm.'+mode+'.seed',JSON.stringify({paths:scope(true)}));location.href='/'+mode;}catch(e){stat('参数未保存：'+e.message);}}
  window.NMWeb={get interactive(){return interactive;},cropEditing:()=>crop.open,fit,detail:queueDetail,invalidateDetail,cropWidth:()=>rect().x1-rect().x0,loaded(){remember();invalidateDetail();$('emulsion').checked=typeof P.emulsion_mirrored==='boolean'?P.emulsion_mirrored:['h','v'].includes(P.flip);$('input-gamma').value=P.input_gamma||'srgb';},scope,api,lock,remember};
  document.addEventListener('click',e=>{if(['wbpick','pbase','pshadow','phl','negbtn'].includes(e.target.closest('button')?.id))fit();});
  document.querySelector('.app-nav a[href="/archive"]').addEventListener('click',e=>{e.preventDefault();if(!batchBusy)handoff('archive');});
  window.addEventListener('blur',()=>showNeg(false));
  decorate();
})();
