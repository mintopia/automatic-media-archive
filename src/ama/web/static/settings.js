// Settings page: save bar state, secret Replace/Remove, and the leave guard (DESIGN.md "Settings Page").
(function () {
  const open = document.querySelector('.files [aria-current]');
  if (open) open.scrollIntoView({ inline: 'center', block: 'nearest' });
  const form = document.querySelector('form[data-settings]');
  if (!form) return;
  const st = form.querySelector('[data-st]');
  const save = form.querySelector('.setfoot button[type=submit]');
  const undo = form.querySelector('[data-undo]');
  const leave = form.querySelector('[data-leave]');
  const changed = new Set();
  let dirty = form.querySelector('[aria-invalid]') !== null;

  function labelOf(el) {
    const row = el.closest('.sf');
    const lb = row && row.querySelector('.lb label, .lb span');
    return lb ? lb.textContent.trim() : '';
  }
  function markDirty(el) {
    dirty = true;
    if (el) { const l = labelOf(el); if (l) changed.add(l); }
    st.textContent = 'Unsaved changes';
    st.className = 'st dirty';
    save.disabled = false;
    undo.hidden = false;
  }
  form.addEventListener('input', (e) => markDirty(e.target));
  form.addEventListener('change', (e) => markDirty(e.target));
  undo.addEventListener('click', () => { location.href = location.pathname; });

  form.querySelectorAll('.secret').forEach((box) => {
    const ctl = box.parentElement;
    const input = ctl.querySelector('input[type=password]');
    const remove = ctl.querySelector('input[name=remove]');
    const state = box.querySelector('.state');
    box.querySelector('[data-secret-replace]').addEventListener('click', () => {
      box.hidden = true;
      input.hidden = false;
      input.disabled = false;
      remove.disabled = true;
      input.focus();
    });
    box.querySelector('[data-secret-remove]').addEventListener('click', (e) => {
      remove.disabled = false;
      state.textContent = 'Removed when you save';
      e.currentTarget.hidden = true;
      markDirty(box);
    });
  });
  form.querySelectorAll('[data-secret-keep]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const ctl = btn.parentElement;
      const input = ctl.querySelector('input[type=password]');
      input.value = '';
      input.disabled = true;
      input.hidden = true;
      ctl.querySelectorAll('.ferr').forEach((e) => { e.hidden = true; });
      btn.outerHTML = '<span class="saved-kept">The saved one is kept.</span>';
    });
  });

  // Leaving with unsaved changes: Stay, Discard and go, or Save and go.
  let target = null;
  document.querySelectorAll('.files a, .subnav a').forEach((a) => {
    a.addEventListener('click', (e) => {
      if (!dirty || a.getAttribute('aria-current')) return;
      e.preventDefault();
      target = a.getAttribute('href');
      const names = [...changed];
      leave.querySelector('#leave-d').textContent =
        (names.length ? `You changed ${names.join(', ')}. ` : '') +
        `Going to ${a.textContent.trim()} now throws ${names.length === 1 ? 'that change' : 'those changes'} away.`;
      leave.hidden = false;
      leave.focus();
    });
  });
  leave.querySelector('[data-stay]').addEventListener('click', () => { leave.hidden = true; });
  leave.querySelector('[data-discard]').addEventListener('click', () => { dirty = false; location.href = target; });
  leave.querySelector('[data-save-go]').addEventListener('click', () => { form.elements.next.value = target; });
  form.addEventListener('submit', () => { dirty = false; });
  window.addEventListener('beforeunload', (e) => { if (dirty) e.preventDefault(); });
})();
