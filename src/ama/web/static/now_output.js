// Inline output on Now (DESIGN.md "Logs" > "Inline output on Now"). The rip card and the
// running Encoding row are re-rendered by SSE, so which tails are open (and wrapped) lives
// here and is put back after each swap. While any tail is open, each `logs` event fetches
// its newest lines (/now/output, swapped in out of band). An open tail follows its newest
// line while scrolled to the bottom; scrolled up, it keeps its place until scrolled back down.
(() => {
  const open = new Set();
  const held = new Map(); // tail id -> scrollTop, while scrolled up
  const wrap = new Map(); // tail id -> on (default: on for phones, like Logs)
  const narrow = matchMedia('(max-width:720px)');
  let focused = null;

  const hold = t => {
    if (t.hidden) return;
    if (t.scrollHeight - t.scrollTop - t.clientHeight < 8) held.delete(t.id);
    else held.set(t.id, t.scrollTop);
  };
  const place = t => { t.scrollTop = held.has(t.id) ? held.get(t.id) : t.scrollHeight; };
  const holdAll = () => open.forEach(id => { const t = document.getElementById(id); if (t) hold(t); });

  const apply = (all = false) => {
    const shown = [];
    document.querySelectorAll('button[data-tail]').forEach(b => {
      const id = b.getAttribute('aria-controls');
      const t = document.getElementById(id);
      if (!t) return;
      const on = open.has(id);
      if (on && (t.hidden || all)) shown.push(t);
      t.hidden = !on;
      b.setAttribute('aria-expanded', String(on));
      b.textContent = on ? 'Hide output' : 'Show output';
    });
    document.querySelectorAll('button[data-wrap^="tail-"]').forEach(b => {
      const t = document.getElementById(b.dataset.wrap);
      if (!t) return;
      const on = wrap.has(t.id) ? wrap.get(t.id) : narrow.matches;
      t.toggleAttribute('data-wrapped', on); // not a class: htmx's settle puts classes back
      b.setAttribute('aria-pressed', String(on));
    });
    shown.forEach(place);
    if (focused) {
      const b = document.querySelector(focused);
      if (b) b.focus();
      focused = null;
    }
  };

  document.addEventListener('click', e => {
    const b = e.target.closest('button[data-tail], button[data-wrap^="tail-"]');
    if (!b) return;
    holdAll();
    if (b.hasAttribute('data-tail')) {
      const id = b.getAttribute('aria-controls');
      open.has(id) ? open.delete(id) : (open.add(id), held.delete(id));
    } else {
      const id = b.dataset.wrap;
      wrap.set(id, b.getAttribute('aria-pressed') !== 'true');
    }
    apply(true);
  });

  // An SSE swap replaces the card or row: keep focus on the control that had it.
  document.addEventListener('htmx:sseBeforeMessage', e => {
    holdAll();
    const a = document.activeElement;
    if (!a || !e.target.contains(a) || !a.matches('button[data-tail], button[data-wrap^="tail-"]')) return;
    focused = a.hasAttribute('data-tail')
      ? `button[data-tail][aria-controls="${a.getAttribute('aria-controls')}"]`
      : `button[data-wrap="${a.dataset.wrap}"]`;
  });
  document.addEventListener('htmx:sseMessage', () => apply());

  // The live poll: only while something is open, and only for what is open.
  const ids = () => [...open].filter(id => document.getElementById(id)).map(id => id.slice(5));
  document.addEventListener('htmx:beforeRequest', e => {
    if (e.detail.elt.hasAttribute('data-now-output') && !ids().length) e.preventDefault();
  });
  document.addEventListener('htmx:configRequest', e => {
    if (e.detail.elt.hasAttribute('data-now-output')) e.detail.parameters.steps = ids().join(',');
  });
  const tail = e => { const t = e.detail.target; return t && t.classList && t.classList.contains('tail') ? t : null; };
  document.addEventListener('htmx:oobBeforeSwap', e => { const t = tail(e); if (t) hold(t); });
  document.addEventListener('htmx:oobAfterSwap', e => { const t = tail(e); if (t) place(t); });

  apply();
})();
