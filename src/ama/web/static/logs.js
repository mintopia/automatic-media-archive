// Logs (DESIGN.md "Logs"): run-list search, Wrap lines, and following a running Step's output.
(() => {
  // Wrap lines: on by default on phones.
  document.querySelectorAll('button[data-wrap]').forEach(b => {
    const log = document.getElementById(b.dataset.wrap);
    if (!log) return;
    const set = on => { log.classList.toggle('wrap', on); b.setAttribute('aria-pressed', String(on)); };
    b.addEventListener('click', () => set(b.getAttribute('aria-pressed') !== 'true'));
    set(matchMedia('(max-width:720px)').matches);
  });

  // Run list: filter the rows shown by every word typed.
  const q = document.getElementById('run-q');
  if (q) q.addEventListener('input', () => {
    const words = q.value.toLowerCase().split(/\s+/).filter(Boolean);
    let shown = 0;
    document.querySelectorAll('.runs .bin').forEach(bin => {
      let n = 0;
      bin.querySelectorAll('a.row.runrow').forEach(r => {
        const hit = words.every(w => r.textContent.toLowerCase().includes(w));
        r.hidden = !hit; n += hit;
      });
      bin.hidden = !n; shown += n;
    });
    const none = document.getElementById('run-none');
    if (none) none.hidden = shown > 0 || !document.querySelector('.runs .bin');
    document.getElementById('run-count').textContent =
      words.length ? `${shown} run${shown === 1 ? '' : 's'} match` : '';
  });

  // A running Step: follow the tail while scrolled to the bottom.
  const follows = [];
  document.querySelectorAll('[data-follow]').forEach(w => {
    const log = w.querySelector('.log'), btn = w.querySelector('.jump');
    const st = w.closest('details').querySelector('[data-follow-state]');
    const f = { log, following: true };
    const sync = () => {
      f.following = log.scrollHeight - log.scrollTop - log.clientHeight < 8;
      btn.hidden = f.following;
      if (st) st.textContent = f.following ? 'Following live output' : 'Scrolled up, not following';
    };
    if (!location.hash) log.scrollTop = log.scrollHeight;
    log.addEventListener('scroll', sync);
    btn.addEventListener('click', () => { log.scrollTop = log.scrollHeight; });
    sync();
    follows.push(f);
  });

  // The live poll says which lines the page already has, and whose state it shows.
  document.addEventListener('htmx:configRequest', e => {
    const el = e.detail.elt;
    if (!el.hasAttribute || !el.hasAttribute('data-run-live')) return;
    e.detail.parameters.sig = el.dataset.sig;
    document.querySelectorAll('.log[data-step]').forEach(log => {
      const times = log.querySelectorAll('a.time');
      const n = times.length ? times[times.length - 1].id.split('-L')[1] : '0';
      e.detail.parameters[`after_${log.dataset.step}`] = n;
    });
  });
  document.addEventListener('htmx:oobAfterSwap', () => {
    follows.forEach(f => { if (f.following) f.log.scrollTop = f.log.scrollHeight; });
  });
})();
