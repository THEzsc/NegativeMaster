/* Guided negative conversion. Suggestions are explicit and never applied on load. */
(() => {
  const M=window.NMWorkflowModel;
  const sections=[...document.querySelectorAll('#panel > details.sec')];
  const groups={
    '选择底片':'source','直方图':'all','模式与影调':'tone','曲线':'tone',
    'HSL 分色':'color','白平衡':'color','画幅 / 裁切':'flow','胶片取样':'flow',
    '细节':'color','自动色阶':'flow','参照匹配':'color','预设':'tone',
    '导出':'export','偏好':'export'
  };
  function sectionGroup(section) {
    const title=section.querySelector('summary')?.textContent.trim()||'';
    if(groups[title])return groups[title];
    if(/导出|偏好|载入行为/.test(title))return 'export';
    if(/白平衡|色彩|白点|HSL|细节|锐化|匹配/.test(title))return 'color';
    if(/取样|采样|裁|画幅|色阶|高级/.test(title))return 'flow';
    return 'tone';
  }
  sections.forEach(s=>s.dataset.workflowGroup=sectionGroup(s));
  const rail=document.createElement('aside');rail.id='negative-rail';rail.setAttribute('aria-label','胶卷照片');
  rail.innerHTML='<h2>本卷底片 <span>LOCAL / 本地</span></h2>';
  rail.append(sections[0]);$('stage').before(rail);
  if(innerWidth<1000)document.body.classList.add('rail-hidden');

  const nav=document.createElement('div');nav.id='workflow-tabs';nav.setAttribute('role','tablist');nav.setAttribute('aria-label','调片步骤');
  for(const [id,label] of [['flow','01 转换'],['tone','02 影调'],['color','03 色彩'],['export','04 导出']]){
    const b=document.createElement('button');b.textContent=label;b.type='button';b.dataset.group=id;b.setAttribute('role','tab');
    b.onclick=()=>selectTab(id);nav.append(b);
  }
  $('panel').querySelector('h1').after(nav);
  nav.addEventListener('keydown',e=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
    e.preventDefault();const buttons=[...nav.children],i=buttons.indexOf(document.activeElement);
    const n=e.key==='Home'?0:e.key==='End'?buttons.length-1:(i+(e.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;
    buttons[n].click();buttons[n].focus();
  });
  function selectTab(id){
    for(const b of nav.children){const active=b.dataset.group===id;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;}
    $('panel').querySelectorAll('details.sec').forEach(s=>s.hidden=s.dataset.workflowGroup!=='all'&&s.dataset.workflowGroup!==id);
  }
  const assistant=document.createElement('details');assistant.id='workflow-assistant';assistant.className='sec';assistant.open=true;assistant.dataset.workflowGroup='flow';
  assistant.innerHTML=`<summary>从片框到影调</summary><div class="bd">
    <p class="workflow-intro">先确认片框与片基，再建立同卷的影调基准。每一步都可手动调整。</p>
    <div class="workflow-step"><b>01</b><span>确认输入</span></div>
    <label class="row" for="input-gamma">普通图片的编码</label>
    <select id="input-gamma"><option value="srgb">sRGB · JPEG / 常规扫描图</option><option value="linear">线性 · 扫描仪线性 TIFF</option></select>
    <p class="hint">RAW 自动以线性数据解码。仅在扫描软件明确输出线性文件时选择“线性”。</p>
    <div class="workflow-step"><b>02</b><span>识别片框，校平画面</span></div>
    <button id="workflow-crop" style="width:100%;min-height:38px">检测片框与倾斜</button>
    <p class="hint">保留横竖方向；弱片边会参考同卷已存调整。无法可靠判断时保留当前框。</p>
    <div class="workflow-step"><b>03</b><span>建立影调基准</span></div>
    <div class="workflow-actions"><button id="analyze-frame">分析这一张</button><button id="analyze-roll">分析同卷</button></div>
    <div id="tone-report" role="status" aria-live="polite" hidden></div>
    <p id="workflow-footnote">同卷分析使用勾选照片，未勾选时使用当前可见列表，均匀抽取最多 12 张。建议只用于建立起点，不等同于胶片的实测 gamma。</p>
  </div>`;
  nav.after(assistant);
  const modeRow=$('modes'),engineRow=$('ndtoggle').parentElement,ndControls=$('ndrow');
  const firstStep=assistant.querySelector('.workflow-step');
  firstStep.before(modeRow,engineRow,ndControls);
  sections.find(s=>s.querySelector('summary')?.textContent==='模式与影调').querySelector('summary').textContent='基础影调';
  $('input-gamma').onchange=()=>{P.input_gamma=$('input-gamma').value;render();};
  $('workflow-crop').onclick=()=>$('autocrop').click();

  const looks=document.createElement('details');looks.className='sec';looks.open=true;looks.dataset.workflowGroup='tone';
  looks.innerHTML='<summary>印相风格</summary><div class="bd"><p class="hint">保留 gamma、曝光、裁切和白平衡，只改变下列风格的影调控制。可撤销。</p><div id="look-grid"></div><p id="look-note">选择一个起点，再用下方控制细调。</p></div>';
  assistant.after(looks);
  for(const [key,look] of Object.entries(M.looks)){
    const b=document.createElement('button');b.type='button';b.innerHTML='<span class="look-swatch" aria-hidden="true"></span>';
    const label=document.createElement('span');label.textContent=look.name;b.append(label);b.title=look.note;
    b.onclick=()=>{if(!loaded){stat('先载入一张底片');return;}P=M.patchTone(currentSettings(),key).P;refl();render();$('look-note').textContent=look.note;stat('已应用：'+look.name+' · 可用撤销恢复');};
    $('look-grid').append(b);
  }

  const railButton=document.createElement('button');railButton.id='toggle-negative-rail';railButton.textContent='底片列表';railButton.type='button';
  railButton.setAttribute('aria-controls','negative-rail');
  function syncRail(){railButton.setAttribute('aria-expanded',String(!document.body.classList.contains('rail-hidden')));}
  railButton.onclick=()=>{document.body.classList.toggle('rail-hidden');syncRail();if(loaded)fitWrap();};
  $('stagebar').prepend(railButton);syncRail();
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&innerWidth<1000){document.body.classList.add('rail-hidden');syncRail();}});
  $('empty').innerHTML='让每一卷，回到它的光。<small>打开负片 → 确认片框 → 建立同卷影调 → 导出<br>原始照片保留，调整写入旁边的参数文件。</small><button id="workflow-open" class="acc">打开底片文件夹</button>';
  $('workflow-open').onclick=()=>$('pickdir').click();
  $('status').setAttribute('role','status');$('status').setAttribute('aria-live','polite');

  // Undo is scoped to the current frame. Continuous slider moves are one edit.
  let undo=[],redo=[],baseline=null,historyFile=null,lastEdit=0,restoring=false;
  const history=document.createElement('span');history.id='workflow-history';
  history.innerHTML='<button id="workflow-undo" title="撤销 Ctrl / ⌘ Z" aria-label="撤销调整" disabled>↶</button><button id="workflow-redo" title="重做 Ctrl / ⌘ Shift Z" aria-label="重做调整" disabled>↷</button>';
  $('stagebar').append(history);
  function historyButtons(){$('workflow-undo').disabled=!undo.length;$('workflow-redo').disabled=!redo.length;}
  function record(){
    if(!loaded||restoring)return;
    const now=JSON.stringify(currentSettings());
    if(historyFile!==curFile||baseline===null){historyFile=curFile;undo=[];redo=[];baseline=now;lastEdit=0;historyButtons();return;}
    if(now===baseline)return;
    const time=Date.now();
    if(time-lastEdit>450||!undo.length)undo.push(baseline);
    if(undo.length>60)undo.shift();redo=[];baseline=now;lastEdit=time;historyButtons();
    invalidateReport();
  }
  function restoreHistory(from,to){
    if(!from.length||!loaded)return;to.push(JSON.stringify(currentSettings()));
    const state=JSON.parse(from.pop());restoring=true;
    P=state.P;cropN=state.cropN;curFmt=state.curFmt;orient=state.orient;geometrySource=state.geometrySource||'manual';
    aspect=FMT[curFmt];if(aspect&&orient==='port')aspect=1/aspect;
    baseline=JSON.stringify(currentSettings());lastEdit=0;lastAutoSummary='';
    syncFmtPills();refl();drawCrop();render();restoring=false;historyButtons();invalidateReport();stat('已恢复调整');
  }
  $('workflow-undo').onclick=()=>restoreHistory(undo,redo);$('workflow-redo').onclick=()=>restoreHistory(redo,undo);
  document.addEventListener('keydown',e=>{
    if(!(e.ctrlKey||e.metaKey)||!['z','y'].includes(e.key.toLowerCase())||/INPUT|TEXTAREA|SELECT/.test(e.target.tagName))return;
    e.preventDefault();if(e.shiftKey||e.key.toLowerCase()==='y')$('workflow-redo').click();else $('workflow-undo').click();
  });

  let pending=false,analysis=null,analysisToken=0;
  function currentScope(){return M.selection([...document.querySelectorAll('#files .fitem')].map(el=>({path:el.dataset.path,checked:el.querySelector('.fck').checked,visible:el.style.display!=='none'})),curFile);}
  function fingerprint(){return JSON.stringify({file:curFile,settings:loaded?currentSettings():null});}
  function invalidateReport(){
    if(!analysis)return;analysis=null;
    $('tone-report').querySelectorAll('button').forEach(b=>b.disabled=true);
    const note=$('analysis-stale');if(note)note.hidden=false;
  }
  async function api(url,body){
    const r=await fetch(url,{method:'POST',headers:HJ,body:JSON.stringify(body)});const d=await r.json();
    if(!r.ok||!d.ok)throw new Error(d.err||'请求失败');return d;
  }
  async function analyze(scope){
    if(pending)return;if(!loaded){stat('先载入一张底片，确认转换模式');return;}
    const paths=scope==='frame'?[curFile]:currentScope();if(!paths.length){stat('先选择同卷照片');return;}
    pending=true;analysis=null;const token=++analysisToken,signature=fingerprint();
    $('analyze-frame').disabled=true;$('analyze-roll').disabled=true;
    const target=$('tone-report');target.hidden=false;target.textContent=scope==='frame'?'正在分析当前底片…':'正在抽样分析同卷底片，RAW 解码可能需要一些时间…';
    try{
      const d=await api('/api/workflow/analyze',{paths,current_path:curFile,current:currentSettings()});
      if(token!==analysisToken||signature!==fingerprint()){target.textContent='分析期间照片或参数已改变，请重新分析。';return;}
      const report=scope==='frame'?d.frames[0]:d.report;
      analysis={scope,paths,signature,report};showReport(d,report,scope);
    }catch(e){target.textContent='分析失败：'+e.message;}
    finally{pending=false;$('analyze-frame').disabled=false;$('analyze-roll').disabled=false;}
  }
  function showReport(data,report,scope){
    const target=$('tone-report');target.replaceChildren();
    const heading=document.createElement('h3');heading.textContent=scope==='frame'?'这一张的建议':'同卷统一影调建议';target.append(heading);
    const value=document.createElement('span');value.className='report-value';value.textContent=Number.isFinite(report.recommendation)?report.recommendation.toFixed(2):'—';target.append(value);
    const confidence=document.createElement('span');confidence.className='report-confidence';confidence.textContent=(report.parameter_key==='nd_gamma'?'相纸反差':'亮度 gamma')+' · '+({high:'参考较稳定',medium:'可作起点',low:'谨慎参考',none:'无法建议'}[report.confidence]||'');target.append(confidence);
    const summary=document.createElement('p');summary.textContent=`已分析 ${data.frames.length} / ${data.sampled} 个样本，共 ${data.total} 张。`+(scope==='roll'?` 有效样本 ${report.accepted_count ?? data.frames.length} 张；整卷使用同一个值。`:'');target.append(summary);
    const warnings=document.createElement('ul');for(const w of report.warnings||[]){const li=document.createElement('li');li.textContent=w;warnings.append(li);}if(warnings.children.length)target.append(warnings);
    const details=document.createElement('details'),label=document.createElement('summary');label.textContent='查看分析样本与失败原因';details.append(label);
    const list=document.createElement('ul');
    for(const frame of data.frames){const li=document.createElement('li');li.textContent=frame.name+' · '+(Number.isFinite(frame.recommendation)?frame.recommendation.toFixed(2):'无法建议')+' · '+(frame.warnings||[]).join('；');list.append(li);}
    for(const error of data.errors||[]){const li=document.createElement('li');li.textContent=error.path+'：'+error.error;li.className='report-error';list.append(li);}details.append(list);target.append(details);
    const actions=document.createElement('div');actions.className='workflow-actions';
    const apply=document.createElement('button');apply.textContent='应用到当前帧';apply.disabled=!M.canApply(report);apply.onclick=()=>applySuggestion(false);actions.append(apply);
    if(scope==='roll'){const lock=document.createElement('button');lock.textContent='锁定到本卷 '+analysis.paths.length+' 张';lock.disabled=!M.canApply(report);lock.onclick=()=>applySuggestion(true);actions.append(lock);}
    target.append(actions);
    const stale=document.createElement('p');stale.id='analysis-stale';stale.hidden=true;stale.textContent='参数已变化，请重新分析后应用。';target.append(stale);
  }
  async function applySuggestion(wholeRoll){
    if(!analysis||analysis.signature!==fingerprint()){invalidateReport();stat('照片或参数已变化，请重新分析');return;}
    const selected=analysis,report=selected.report;if(!M.canApply(report))return;
    if(!wholeRoll){P[report.parameter_key]=report.recommendation;refl();render();stat('已应用建议，可撤销或手动微调');return;}
    if(JSON.stringify(currentScope())!==JSON.stringify(selected.paths)){invalidateReport();stat('同卷选择已改变，请重新分析');return;}
    // Persist only this tone parameter. Every frame keeps its own geometry and exposure.
    const target=$('tone-report');target.querySelectorAll('button').forEach(b=>b.disabled=true);
    const fileAtStart=curFile,signature=selected.signature;
    const locked=[$('panel'),$('negative-rail'),$('stagebar'),$('rotpad'),$('imgwrap')];
    locked.forEach(el=>el.inert=true);stat('正在保存整卷影调…');
    try{
      await flushAutosave();
      const d=await api('/api/workflow/roll-gamma',{paths:selected.paths,gamma:report.recommendation,parameter_key:report.parameter_key,current_path:curFile,current:currentSettings()});
      if(curFile===fileAtStart&&fingerprint()===signature&&d.updated.some(p=>p.replaceAll('\\','/').toLowerCase()===curFile.replaceAll('\\','/').toLowerCase())){
        P[report.parameter_key]=report.recommendation;refl();render();
      }
      for(const path of d.updated)markEdited(path);
      const status=document.createElement('p');status.textContent=`已锁定 ${d.updated.length} / ${selected.paths.length} 张，各自曝光、白平衡和裁切保留。`;target.append(status);
      if(d.errors.length){const list=document.createElement('ul');for(const e of d.errors){const li=document.createElement('li');li.textContent=e.path+'：'+e.error;list.append(li);}target.append(list);}
      analysis=null;stat(status.textContent);
    }catch(e){stat('整卷保存失败：'+e.message);target.querySelectorAll('button').forEach(b=>b.disabled=false);}
    finally{locked.forEach(el=>el.inert=false);}
  }
  $('analyze-frame').onclick=()=>analyze('frame');$('analyze-roll').onclick=()=>analyze('roll');
  window.NMWorkflow={record,loaded(){baseline=null;historyFile=null;invalidateReport();record();}};
  selectTab('flow');
})();
