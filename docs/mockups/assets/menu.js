// Mockup-only: top-bar menu. Opens and closes, Esc returns focus, Theme and New Discs change for this page view.
(function () {
  const btn = document.querySelector('.mbtn[aria-controls]');
  const panel = btn && document.getElementById(btn.getAttribute('aria-controls'));
  if (!panel) return;
  const set = open => { panel.hidden = !open; btn.setAttribute('aria-expanded', open); };
  if (!btn.hasAttribute('onclick')) btn.addEventListener('click', () => set(panel.hidden));
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !panel.hidden) { set(false); btn.focus(); } });
  document.addEventListener('click', e => { if (!panel.hidden && !e.target.closest('.menu')) set(false); });
  const pick = (group, b) => group.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', x === b));
  panel.querySelectorAll('.segs').forEach(group => group.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return; pick(group, b);
    const v = b.textContent.trim();
    if (group.getAttribute('aria-labelledby') === 'm-theme') {
      if (v === 'System') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = v.toLowerCase();
    } else {
      const mark = document.querySelector('.top .paused'); if (mark) mark.hidden = v !== 'Paused';
    }
  }));
  const t = document.documentElement.dataset.theme, tg = panel.querySelector('[aria-labelledby="m-theme"]');
  if (t && tg) tg.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', x.textContent.trim().toLowerCase() === t));
  if (new URLSearchParams(location.search).get('menu') === 'open') set(true);
})();
