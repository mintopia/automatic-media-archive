// Inline output on Now (DESIGN.md "Logs" > "Inline output on Now"). The rip card and the
// running Encoding row are re-rendered by SSE, so which tails are open (and wrapped) lives
// here and is put back after each swap. While any tail is open, each `logs` event fetches
// its newest lines (/now/output, swapped in out of band).
(() => {
  const open = new Set();
  const wrap = new Map(); // tail id -> on (default: on for phones, like Logs)
  const narrow = matchMedia('(max-width:720px)');
  let focused = null;

  const apply = () => {
    document.querySelectorAll('button[data-tail]').forEach(b => {
      const id = b.getAttribute('aria-controls');
      const t = document.getElementById(id);
      if (!t) return;
      const on = open.has(id);
      t.hidden = !on;
      b.setAttribute('aria-expanded', String(on));
      b.textContent = on ? 'Hide output' : 'Show output';
      if (on) t.scrollTop = t.scrollHeight;
    });
    document.querySelectorAll('button[data-wrap^="tail-"]').forEach(b => {
      const t = document.getElementById(b.dataset.wrap);
      if (!t) return;
      const on = wrap.has(t.id) ? wrap.get(t.id) : narrow.matches;
      t.toggleAttribute('data-wrapped', on); // not a class: htmx's settle puts classes back
      b.setAttribute('aria-pressed', String(on));
    });
    if (focused) {
      const b = document.querySelector(focused);
      if (b) b.focus();
      focused = null;
    }
  };

  document.addEventListener('click', e => {
    const b = e.target.closest('button[data-tail], button[data-wrap^="tail-"]');
    if (!b) return;
    if (b.hasAttribute('data-tail')) {
      const id = b.getAttribute('aria-controls');
      open.has(id) ? open.delete(id) : open.add(id);
    } else {
      const id = b.dataset.wrap;
      wrap.set(id, b.getAttribute('aria-pressed') !== 'true');
    }
    apply();
  });

  // An SSE swap replaces the card or row: keep focus on the control that had it.
  document.addEventListener('htmx:sseBeforeMessage', e => {
    const a = document.activeElement;
    if (!a || !e.target.contains(a) || !a.matches('button[data-tail], button[data-wrap^="tail-"]')) return;
    focused = a.hasAttribute('data-tail')
      ? `button[data-tail][aria-controls="${a.getAttribute('aria-controls')}"]`
      : `button[data-wrap="${a.dataset.wrap}"]`;
  });
  document.addEventListener('htmx:sseMessage', apply);

  // The live poll: only while something is open, and only for what is open.
  const ids = () => [...open].filter(id => document.getElementById(id)).map(id => id.slice(5));
  document.addEventListener('htmx:beforeRequest', e => {
    if (e.detail.elt.hasAttribute('data-now-output') && !ids().length) e.preventDefault();
  });
  document.addEventListener('htmx:configRequest', e => {
    if (e.detail.elt.hasAttribute('data-now-output')) e.detail.parameters.steps = ids().join(',');
  });
  document.addEventListener('htmx:oobAfterSwap', e => {
    const t = e.detail.target;
    if (t && t.classList && t.classList.contains('tail')) t.scrollTop = t.scrollHeight;
  });

  apply();
})();
