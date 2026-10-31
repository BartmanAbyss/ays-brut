// Whole-show profile recorder. Run it in the page's console (or the browser pane) on
//   http://localhost:8787/champagne.html?gate=1&show=1&master=0&w=1920&h=1080
// with `python dev/profiles/save.py <name>` waiting to receive. It clicks the start box,
// records one row per rendered frame until the show ends, pauses the renderer and POSTs
// the rows to save.py, which writes dev/profiles/<name>.json and .csv.
// gate=1 runs the release's clock (the audio clock); master=0 keeps it silent. Keep the
// page on screen: a hidden page runs at ~2 fps and its GPU timings are inflated.
(async () => {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  let box;
  for (let k = 0; k < 120 && !box; k++) {
    box = [...document.querySelectorAll('div')].find(d => d.textContent === 'click here to start: show + sound');
    if (!box) await wait(500);
  }
  if (!box) throw new Error('no start box: is the URL ?gate=1&show=1?');
  const rows = [];
  let lastFrames = -1, lastWall = 0, t0 = 0, done = false;
  const rec = now => {
    try {
      const p = __probe();
      if (p.frames !== lastFrames) {
        if (!t0) t0 = now;
        const g = p.gpuMs || {};
        rows.push([+(now - t0).toFixed(1), lastWall ? +(now - lastWall).toFixed(2) : 0, +(p.showT || 0).toFixed(3),
                   p.step ?? 0, +(g.sim ?? 0).toFixed(3), +(g.build ?? 0).toFixed(3), +(g.photon ?? 0).toFixed(3),
                   +(g.render ?? 0).toFixed(3), +(g.total ?? 0).toFixed(3), p.parts?.alive ?? 0,
                   +((p.levels || [])[13] ?? 0).toFixed(1)]);
        lastFrames = p.frames; lastWall = now;
      }
    } catch (e) { console.warn('recorder', e); }
    if (!done) requestAnimationFrame(rec);
  };
  requestAnimationFrame(rec);
  box.click();
  // until half a second past the show's end, which the showT slider's range holds
  const lab = [...document.querySelectorAll('.row label')].find(l => l.textContent === 'showT');
  const end = +lab?.nextElementSibling?.max || 97;
  while (!rows.length || rows.at(-1)[2] < end + 0.5) await wait(500);
  done = true;
  __pause();
  const body = JSON.stringify({
    columns: ['wallMs', 'frameMs', 'showT', 'step', 'sim', 'build', 'photon', 'render', 'total', 'alive', 'topLevel'],
    adapter: __probe().adapter, ua: navigator.userAgent,
    width: document.querySelector('canvas').width, height: document.querySelector('canvas').height, rows });
  await fetch('http://127.0.0.1:8799/', { method: 'POST', body, mode: 'no-cors' });
  console.log('profile sent:', rows.length, 'frames');
})();
