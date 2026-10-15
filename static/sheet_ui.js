/* Progressive UI affordances; photo processing stays in the existing editor. */
(() => {
  const rail = $('frame-rail');
  const toggle = $('toggle-frames');
  const backdrop = $('frame-backdrop');
  const narrow = () => window.innerWidth <= 800;
  const isOpen = () => narrow() && document.body.classList.contains('frames-open');

  function syncRanges() {
    for (const input of document.querySelectorAll('.sheet-mode input[type=range]')) {
      const min = Number(input.min || 0), max = Number(input.max || 100);
      const amount = max > min ? (Number(input.value) - min) / (max - min) * 100 : 0;
      input.style.setProperty('--range-fill', `${Math.min(100, Math.max(0, amount))}%`);
      if (!input.hasAttribute('aria-label')) {
        const label = input.closest('label')?.querySelector('.field-label');
        if (label) input.setAttribute('aria-label', label.firstChild.textContent.trim());
      }
    }
  }

  function syncDrawer() {
    if (!narrow()) document.body.classList.remove('frames-open');
    const open = isOpen();
    const visible = narrow() ? open : !document.body.classList.contains('frames-hidden');
    toggle.setAttribute('aria-expanded', String(visible));
    toggle.setAttribute('aria-label', visible ? '收起照片列表' : '展开照片列表');
    toggle.title = visible ? '收起照片列表' : '展开照片列表';
    $('close-frames').style.display = narrow() ? 'inline-grid' : 'none';
    backdrop.hidden = !open;
    if (open) { rail.setAttribute('role', 'dialog'); rail.setAttribute('aria-modal', 'true'); }
    else { rail.removeAttribute('role'); rail.removeAttribute('aria-modal'); }
    document.querySelector('.sheet-stage').inert = open;
    document.querySelector('.sheet-inspector').inert = open;
  }

  function close(restoreFocus = true) {
    const open = isOpen();
    document.body.classList.remove('frames-open');
    syncDrawer();
    if (open) (restoreFocus ? toggle : $('frame-preview-canvas')).focus({preventScroll:true});
  }

  toggle.onclick = () => {
    if (narrow()) document.body.classList.toggle('frames-open');
    else document.body.classList.toggle('frames-hidden');
    syncDrawer();
    if (isOpen()) (rail.querySelector('.frame-item[data-active=true]') || $('choose-directory')).focus({preventScroll:true});
  };
  $('close-frames').onclick = () => close();
  backdrop.onclick = () => close();
  window.addEventListener('resize', syncDrawer, {passive:true});
  document.addEventListener('input', event => { if (event.target.type === 'range') syncRanges(); });
  document.addEventListener('keydown', event => {
    if (!isOpen()) return;
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (event.key !== 'Tab') return;
    const controls = [...rail.querySelectorAll('button:not([disabled]),input:not([disabled]),[tabindex="0"]')].filter(el => el.offsetParent !== null);
    const first = controls[0], last = controls.at(-1);
    if (!first) return;
    if (!rail.contains(document.activeElement) || (event.shiftKey && document.activeElement === first)) {
      event.preventDefault(); (event.shiftKey ? last : first).focus();
    } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  window.SheetUI = {close, syncDrawer, syncRanges};
  syncDrawer();
  syncRanges();
})();
