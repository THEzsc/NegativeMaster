/* Color recommendations are part of the editor, with explicit hex entry. */
(() => {
  const palettes={
    background:[['暖纸','#e8e1d3'],['冷雾','#c3ced0'],['鼠尾草','#a4b1a0'],['灰蓝','#697d8b'],['焦糖','#98704f'],['炭灰','#292b2b'],['夜蓝','#1e3039'],['豆沙','#916c69']],
    film:[['胶片黑','#080808'],['暖黑','#1a1511'],['石墨','#343637'],['蓝黑','#15232a'],['墨绿','#172721'],['深褐','#39251e']],
    edge:[['琥珀','#dda850'],['金黄','#edbd63'],['乳白','#eee6d8'],['珊瑚','#df8c6b'],['浅绿','#bdd0a5'],['雾蓝','#bacbd6']],
    paper:[['档案白','#fffdfa'],['暖纸','#e8e1d3'],['冷白','#edf1f2'],['浅绿','#dce3d8'],['浅杏','#eddbca'],['炭黑','#202122']],
    ink:[['墨黑','#191a1b'],['深褐','#49352b'],['墨绿','#243b32'],['夜蓝','#243d4d'],['砖红','#803d2f'],['乳白','#fffdfa']],
  };
  const fields=[...document.querySelectorAll('[data-color-field]')];
  for(const field of fields){
    const key=field.dataset.colorField,group=field.querySelector('.color-swatches');
    for(const [name,color] of palettes[field.dataset.palette]||[]){
      const button=document.createElement('button');button.type='button';button.className='color-swatch';button.dataset.color=color;
      button.style.setProperty('--swatch',color);button.setAttribute('aria-label',`${field.querySelector('.field-label').textContent}：${name} ${color}`);
      const chip=document.createElement('span');chip.className='swatch-chip';chip.setAttribute('aria-hidden','true');
      const label=document.createElement('span');label.textContent=name;button.append(chip,label);
      button.onclick=()=>transaction(()=>set(state.config,key,color));group.append(button);
    }
  }
  const pairs=[['雾蓝暖纸','#697d8b','#e8e1d3'],['鼠尾草米白','#a4b1a0','#fffdfa'],['夜蓝焦糖','#1e3039','#98704f'],['炭灰豆沙','#292b2b','#916c69']];
  for(const [name,a,b] of pairs){
    const button=document.createElement('button');button.type='button';button.className='palette-pair';button.dataset.colors=`${a}|${b}`;
    const swatch=document.createElement('span');swatch.className='pair-chip';swatch.style.background=`linear-gradient(90deg,${a} 50%,${b} 50%)`;swatch.setAttribute('aria-hidden','true');
    const label=document.createElement('span');label.textContent=name;button.append(swatch,label);
    button.onclick=()=>transaction(()=>Object.assign(state.config.background,{mode:'gradient',color:a,color2:b}));$('background-palettes').append(button);
  }
  function sync(){
    for(const field of fields){
      const color=get(state.config,field.dataset.colorField)?.toLowerCase();
      field.querySelector('.color-current').style.background=color||'transparent';
      for(const button of field.querySelectorAll('.color-swatch'))button.setAttribute('aria-pressed',String(button.dataset.color===color));
    }
    const bg=state.config.background;
    for(const button of document.querySelectorAll('.palette-pair'))button.setAttribute('aria-pressed',String(bg.mode==='gradient'&&button.dataset.colors===`${bg.color}|${bg.color2}`));
  }
  window.SheetColors={sync};sync();
})();
