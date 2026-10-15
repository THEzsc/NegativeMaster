'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const state = {stocks: [], statuses: {}, rolls: [], current: null, editing: null, frame: null, sequence: 0, selectionSequence: 0, busy: false};
  const el = (tag, className, value) => { const node = document.createElement(tag); if (className) node.className = className; if (value !== undefined) node.textContent = value; return node; };
  const asset = name => `/api/archive/assets/${encodeURIComponent(name)}`;
  const rollUrl = id => `/api/archive/rolls/${encodeURIComponent(id)}`;
  function status(message, error = false) { $('archive-status').textContent = message; $('archive-status').classList.toggle('error', error); }
  async function api(url, method = 'GET', body) {
    const headers = method === 'GET' ? {} : {'X-NegativeMaster-Archive': '1'};
    if (body && !(body instanceof FormData)) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(body); }
    const response = await fetch(url, {method, headers, body});
    let result;
    try { result = await response.json(); } catch { throw new Error(`服务未能完成请求（${response.status}），请检查本地服务。`); }
    if (!response.ok || result.ok === false) throw new Error(result.error || '操作失败，请重试。');
    return result;
  }
  function wrap(action, errorId) { return async event => { try { if (errorId) $(errorId).textContent = ''; await action(event); } catch (error) { if (errorId) $(errorId).textContent = error.message; status(error.message, true); } }; }
  function stockFor(roll) { return state.stocks.find(stock => stock.id === roll.stock_id); }
  function stockLabel(roll) {
    const stock = stockFor(roll), label = el('div', 'stock-label');
    label.append(el('span', 'label-brand', stock?.brand || 'FILM ARCHIVE'), el('span', 'label-name', roll.stock_name || stock?.name || 'UNTITLED FILM'), el('span', 'label-iso', roll.iso ? `ISO ${roll.iso}` : roll.format || '135'), el('span', 'label-footer', '档案标签 · 非原厂包装'));
    return label;
  }
  function coverNode(roll, small = false) {
    if (!roll.cover) return stockLabel(roll);
    const img = el('img', small ? 'roll-item-cover' : ''); img.src = asset(roll.cover); img.alt = `${roll.title}的封面`; img.loading = 'lazy'; return img;
  }
  function renderList() {
    const list = $('roll-list'); list.replaceChildren();
    if (!state.rolls.length) { list.append(el('p', 'roll-list-empty', '这里还没有胶卷。新建一卷，或试试其他搜索条件。')); return; }
    for (const roll of state.rolls) {
      const button = el('button', 'roll-item'); button.type = 'button'; button.setAttribute('aria-current', String(roll.id === state.current?.id)); button.dataset.rollId = roll.id;
      const copy = el('span', 'roll-item-copy');
      copy.append(el('strong', '', roll.title), el('span', '', [roll.date_start || '日期未记录', roll.place].filter(Boolean).join(' · ')), el('span', 'roll-item-state', `${state.statuses[roll.status]} · ${roll.frame_count} 张`));
      button.append(coverNode(roll, true), copy); button.addEventListener('click', wrap(() => selectRoll(roll.id))); list.append(button);
    }
  }
  async function loadRolls({selectFirst = false} = {}) {
    const sequence = ++state.sequence;
    const params = new URLSearchParams({q: $('archive-search').value, status: $('filter-status').value, year: $('filter-year').value, sort: $('archive-sort').value});
    const result = await api(`/api/archive/rolls?${params}`);
    if (sequence !== state.sequence) return;
    state.rolls = result.rolls;
    const selectedYear = $('filter-year').value;
    $('filter-year').replaceChildren(new Option('全部年份', ''), ...result.years.map(year => new Option(year, year)));
    if (result.years.includes(selectedYear)) $('filter-year').value = selectedYear;
    $('archive-count').textContent = `${result.stats.rolls} 卷 · ${result.stats.frames} 张照片 · ${result.stats.archived} 卷已归档`;
    renderList();
    if (selectFirst && !state.current && state.rolls.length) await selectRoll(state.rolls[0].id);
  }
  async function selectRoll(id) {
    const sequence = ++state.selectionSequence;
    const result = await api(rollUrl(id));
    if (sequence !== state.selectionSequence) return;
    state.current = result.roll; renderDetail(); renderList();
    history.replaceState(null, '', `/archive#${encodeURIComponent(id)}`);
  }
  function addFact(list, title, value) { if (!value) return; list.append(el('dt', '', title), el('dd', '', value)); }
  function externalLink(url, title) {
    try { const parsed = new URL(url); if (!['http:', 'https:'].includes(parsed.protocol)) return null; const a = el('a', '', title); a.href = parsed.href; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a; } catch { return null; }
  }
  function renderDetail() {
    const roll = state.current; $('archive-empty').hidden = !!roll; $('roll-detail').hidden = !roll;
    if (!roll) return;
    const stock = stockFor(roll);
    $('roll-counter').textContent = roll.roll_number || `ARCHIVE / ${roll.id.slice(0, 8).toUpperCase()}`;
    $('detail-cover').replaceChildren(coverNode(roll));
    $('cover-provenance').replaceChildren();
    if (roll.cover) {
      $('cover-provenance').append(el('span', '', roll.cover_credit || '用户上传封面'));
      const source = externalLink(roll.cover_source, '查看封面来源'); if (source) { $('cover-provenance').append(document.createElement('br'), source); }
    } else $('cover-provenance').textContent = '文字档案标签 · 非原厂包装';
    $('roll-stock').textContent = [roll.stock_name || stock?.name || '型号未记录', roll.format, roll.iso ? `ISO ${roll.iso}` : ''].filter(Boolean).join(' / ');
    $('roll-title').textContent = roll.title;
    const dates = roll.date_start ? roll.date_start + (roll.date_end && roll.date_end !== roll.date_start ? ` — ${roll.date_end}` : '') : '拍摄日期未记录';
    $('roll-subtitle').textContent = [dates, roll.place].filter(Boolean).join(' · ');
    $('roll-tags').replaceChildren(el('span', 'roll-tag status', state.statuses[roll.status]), ...roll.tags.map(tag => el('span', 'roll-tag', tag)));
    const facts = $('roll-facts'); facts.replaceChildren();
    addFact(facts, '相机', roll.camera); addFact(facts, '镜头', roll.lens); addFact(facts, '实拍 EI', roll.exposure_index); addFact(facts, '冲洗工艺', roll.process); addFact(facts, '冲洗日期', roll.developed_on); addFact(facts, '实验室', roll.lab); addFact(facts, '冲洗记录', roll.development); addFact(facts, '底片存放', roll.storage);
    $('roll-notes').textContent = roll.notes; $('roll-notes').hidden = !roll.notes;
    $('photo-count').textContent = `${roll.frames.length} 张`;
    const grid = $('frame-grid'); grid.replaceChildren();
    if (!roll.frames.length) grid.append(el('div', 'frame-empty', '照片还没入册。\n关联成片文件夹，为这一卷补上画面。'));
    for (const [index, frame] of roll.frames.entries()) {
      const button = el('button', 'archive-frame'); button.type = 'button'; button.setAttribute('aria-label', `打开第 ${index + 1} 张：${frame.name}`);
      const picture = el('span', 'frame-image');
      if (frame.thumb) { const img = el('img'); img.src = asset(frame.thumb); img.alt = frame.name; img.loading = 'lazy'; picture.append(img); } else picture.textContent = '无预览 · 保留源文件关联';
      const caption = el('span', 'frame-caption'); caption.append(el('span', '', `${String(index + 1).padStart(2, '0')}  ${frame.name}`), el('span', '', '★'.repeat(frame.rating)));
      button.append(picture, caption); if (frame.missing) button.append(el('span', 'frame-missing', '源文件离线 · 预览仍保留')); else if (frame.notes) button.append(el('span', 'frame-missing', '有照片备注'));
      button.addEventListener('click', () => openFrame(frame)); grid.append(button);
    }
    const sources = $('stock-reference-links'); sources.replaceChildren();
    for (const source of stock?.sources || []) { const link = externalLink(source.url, source.title); if (link) sources.append(link); }
    $('stock-description').textContent = stock?.notes || '自定义型号：可在档案备注中补充实物信息与资料来源。';
  }
  async function acceptRoll(result, message) { state.current = result.roll; renderDetail(); await loadRolls(); if (message) status(message); }
  const form = $('roll-form');
  function openEditor(roll = null) {
    state.editing = roll ? structuredClone(roll) : null; form.reset();
    for (const input of form.elements) if (input.name) { let value = roll?.[input.name] ?? ''; if (input.name === 'tags') value = (roll?.tags || []).join('，'); if (!roll && input.name === 'format') value = '135'; if (!roll && input.name === 'status') value = 'planned'; input.value = value; }
    $('editor-title').textContent = roll ? '编辑胶卷资料' : '新建胶卷档案'; $('editor-error').textContent = ''; $('roll-editor').showModal(); form.elements.title.focus();
  }
  $('new-roll').addEventListener('click', () => openEditor()); $('empty-create').addEventListener('click', () => openEditor()); $('edit-roll').addEventListener('click', () => openEditor(state.current));
  $('archive-stock').addEventListener('change', () => {
    const stock = state.stocks.find(s => s.id === $('archive-stock').value); if (!stock) return;
    form.elements.stock_name.value = `${stock.brand} ${stock.name}`; form.elements.iso.value = stock.iso || ''; form.elements.process.value = stock.process || '';
    if (stock.formats?.length && [...form.elements.format.options].some(option => option.value === stock.formats[0])) form.elements.format.value = stock.formats[0];
  });
  form.addEventListener('submit', wrap(async event => {
    event.preventDefault(); const data = Object.fromEntries(new FormData(form));
    data.tags = data.tags.split(/[,，]/).map(t => t.trim()).filter(Boolean); for (const key of ['iso', 'exposure_index']) data[key] = data[key] ? Number(data[key]) : null;
    data.cover_source = state.editing?.cover_source || ''; data.cover_credit = state.editing?.cover_credit || '';
    if (state.editing) data.updated_at = state.editing.updated_at;
    $('save-roll').disabled = true;
    try { const result = await api(state.editing ? rollUrl(state.editing.id) : '/api/archive/rolls', state.editing ? 'PUT' : 'POST', data); $('roll-editor').close(); await acceptRoll(result, '胶卷档案已保存。'); history.replaceState(null, '', `/archive#${result.roll.id}`); }
    finally { $('save-roll').disabled = false; }
  }, 'editor-error'));
  $('delete-roll').addEventListener('click', wrap(async () => {
    const roll = state.current; if (!confirm(`删除「${roll.title}」的档案与照片关联？原始照片不会删除。建议先备份档案。`)) return;
    await api(rollUrl(roll.id), 'DELETE'); state.current = null; renderDetail(); history.replaceState(null, '', '/archive'); await loadRolls({selectFirst: true}); status('档案已删除，原始照片保持不变。');
  }));
  $('add-photos').addEventListener('click', () => { $('photos-error').textContent = ''; $('photos-dialog').showModal(); $('photos-directory').focus(); });
  $('photos-form').addEventListener('submit', wrap(async event => {
    event.preventDefault(); $('link-photos').disabled = true; $('link-photos').textContent = '正在生成预览…';
    try { const result = await api(`${rollUrl(state.current.id)}/frames`, 'POST', {directory: $('photos-directory').value, mode: $('photos-mode').value}); $('photos-dialog').close(); await acceptRoll(result, `已关联 ${result.added} 张照片。` + (result.warnings.length ? ` ${result.warnings.length} 张未生成预览，RAW 或异常图片仅保留路径。` : '原片保持不变。')); }
    finally { $('link-photos').disabled = false; $('link-photos').textContent = '关联照片'; }
  }, 'photos-error'));
  $('relink-photos').addEventListener('click', wrap(async () => { const result = await api(`${rollUrl(state.current.id)}/relink`, 'POST', {directory: $('photos-directory').value}); $('photos-dialog').close(); await acceptRoll(result, `已重连 ${result.linked} 张照片。只有名称唯一且在新目录存在的文件会更新关联。`); }, 'photos-error'));
  $('change-cover').addEventListener('click', () => { $('cover-error').textContent = ''; $('cover-file').value = ''; $('cover-source').value = state.current.cover_source || ''; $('cover-credit').value = state.current.cover_credit || '本人拍摄 / 上传'; $('cover-dialog').showModal(); });
  $('cover-form').addEventListener('submit', wrap(async event => {
    event.preventDefault(); const file = $('cover-file').files[0]; if (!file) throw new Error('请选择封面图片。'); if (file.size > 20 * 1024 * 1024) throw new Error('封面不能超过 20 MB。');
    const data = new FormData(); data.set('file', file); data.set('source', $('cover-source').value); data.set('credit', $('cover-credit').value);
    const result = await api(`${rollUrl(state.current.id)}/cover`, 'POST', data); $('cover-dialog').close(); await acceptRoll(result, '封面已保存，来源信息已记录。');
  }, 'cover-error'));
  $('reset-cover').addEventListener('click', wrap(async () => { const result = await api(`${rollUrl(state.current.id)}/cover`, 'POST', {}); $('cover-dialog').close(); await acceptRoll(result, '已恢复为文字档案标签。'); }, 'cover-error'));
  function openFrame(frame) {
    state.frame = frame; $('frame-title').textContent = frame.name; $('frame-preview').hidden = !frame.thumb; if (frame.thumb) $('frame-preview').src = asset(frame.thumb); else $('frame-preview').removeAttribute('src');
    $('frame-path').textContent = `${frame.path}${frame.missing ? ' · 源文件离线；这份预览不受影响。' : ''}`; $('frame-rating').value = frame.rating; $('frame-notes').value = frame.notes; $('frame-error').textContent = ''; $('frame-cover').disabled = !frame.thumb; $('frame-dialog').showModal();
  }
  $('frame-form').addEventListener('submit', wrap(async event => { event.preventDefault(); const result = await api(`${rollUrl(state.current.id)}/frames/${state.frame.id}`, 'PUT', {rating: Number($('frame-rating').value), notes: $('frame-notes').value}); $('frame-dialog').close(); await acceptRoll(result, '照片评分与备注已保存。'); }, 'frame-error'));
  $('frame-cover').addEventListener('click', wrap(async () => { const result = await api(`${rollUrl(state.current.id)}/cover`, 'POST', {frame_id: state.frame.id}); $('frame-dialog').close(); await acceptRoll(result, '已设为胶卷封面。'); }, 'frame-error'));
  $('frame-remove').addEventListener('click', wrap(async () => { if (!confirm('移除这张照片的档案关联与备注？原始照片不会删除。')) return; const result = await api(`${rollUrl(state.current.id)}/frames/${state.frame.id}`, 'DELETE'); $('frame-dialog').close(); await acceptRoll(result, '已移除关联，原始照片保持不变。'); }, 'frame-error'));
  for (const button of document.querySelectorAll('[data-close]')) button.addEventListener('click', () => $(button.dataset.close).close());
  let searchTimer;
  $('archive-search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(wrap(() => loadRolls()), 180); });
  for (const id of ['filter-status', 'filter-year', 'archive-sort']) $(id).addEventListener('change', wrap(() => loadRolls()));
  $('backup-export').addEventListener('click', wrap(async () => {
    $('backup-export').disabled = true; status('正在打包档案资料、封面与预览…');
    try { const response = await fetch('/api/archive/backup'); if (!response.ok) { const result = await response.json(); throw new Error(result.error || '备份失败。'); } const blob = await response.blob(); const url = URL.createObjectURL(blob); const a = el('a'); a.href = url; a.download = `NegativeMaster-archive-${new Date().toISOString().slice(0, 10)}.zip`; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000); status('备份已下载：包含资料、封面与预览；原始照片请另行备份。'); }
    finally { $('backup-export').disabled = false; }
  }));
  $('backup-import').addEventListener('click', () => $('backup-file').click());
  $('backup-file').addEventListener('change', wrap(async () => {
    const file = $('backup-file').files[0]; $('backup-file').value = ''; if (!file) return;
    if (file.size > 256 * 1024 * 1024) throw new Error('备份不能超过 256 MB。');
    if (!confirm('备份中的胶卷会作为新档案添加，现有资料不会覆盖。重复恢复会产生副本。继续恢复？')) return;
    const data = new FormData(); data.set('file', file); $('backup-import').disabled = true; status('正在校验并恢复档案…');
    try { const result = await api('/api/archive/restore', 'POST', data); await loadRolls(); if (result.ids[0]) await selectRoll(result.ids[0]); status(`已恢复 ${result.imported} 卷档案。原片路径保留；更换设备后可能显示源文件离线。`); }
    finally { $('backup-import').disabled = false; }
  }));
  wrap(async () => {
    const catalog = await api('/api/archive/catalog'); state.stocks = catalog.stocks; state.statuses = catalog.statuses; $('storage-location').textContent = catalog.storage; $('catalog-count').textContent = `${state.stocks.length} 款`;
    $('archive-stock').append(new Option('自定义 / 暂不选择', ''));
    for (const stock of state.stocks) $('archive-stock').append(new Option(`${stock.brand} ${stock.name} · ISO ${stock.iso}`, stock.id));
    for (const [key, label] of Object.entries(state.statuses)) { $('filter-status').append(new Option(label, key)); $('editor-status').append(new Option(label, key)); }
    const id = location.hash.slice(1);
    if (id) { try { await selectRoll(decodeURIComponent(id)); } catch { history.replaceState(null, '', '/archive'); } }
    await loadRolls({selectFirst: true}); status('本地档案已就绪 · 原始照片保持不变');
  })();
})();
