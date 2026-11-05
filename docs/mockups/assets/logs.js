// Mockup-only: wrap toggle for logs (on by default on phones) and the run-list filter.
document.querySelectorAll('button[data-wrap]').forEach(b => {
  const log = document.getElementById(b.dataset.wrap);
  const set = on => { log.classList.toggle('wrap', on); b.setAttribute('aria-pressed', on); };
  b.addEventListener('click', () => set(b.getAttribute('aria-pressed') !== 'true'));
  set(matchMedia('(max-width:720px)').matches);
});
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
  document.getElementById('run-none').hidden = shown > 0;
  document.getElementById('run-count').textContent = words.length ? `${shown} run${shown === 1 ? '' : 's'} match` : '';
});
