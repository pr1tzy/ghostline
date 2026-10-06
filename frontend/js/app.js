/* Ghostline — single-page app */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const api = async (p, o) => {
  const r = await fetch('/api' + p, o);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
  return j;
};
const post = (p, body) => api(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const fmt = ms => { if (!ms || ms <= 0) return '—'; const s = ms / 1000, m = Math.floor(s / 60); return `${m}:${(s - m * 60).toFixed(3).padStart(6, '0')}`; };
const sgn = (v, d = 3) => v == null ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '±') + Math.abs(v).toFixed(d);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const ago = t => { const s = Date.now() / 1000 - t; return s < 3600 ? `${Math.max(1, s / 60 | 0)}m ago` : s < 86400 ? `${s / 3600 | 0}h ago` : `${s / 86400 | 0}d ago`; };
const C = { fg: '#eeeaf6', mute: '#857f99', acc: '#3ef0ff', vio: '#9d6bff', loss: '#ff4f81', gain: '#42f5c8', line: 'rgba(238,234,246,.09)', dim: '#2c2840' };
const ease = 'expo.out';

/* ---------- smooth scroll + scroll skew ---------- */
const lenis = new Lenis({ lerp: 0.09 });
gsap.ticker.add(t => lenis.raf(t * 1000));
gsap.ticker.lagSmoothing(0);

/* ---------- cursor ---------- */
const cur = $('.cursor'), dot = $('.cursor-dot'), ring = $('.cursor-ring'), clabel = $('.cursor-label');
let mx = innerWidth / 2, my = innerHeight / 2, rx = mx, ry = my;
addEventListener('mousemove', e => { mx = e.clientX; my = e.clientY; dot.style.transform = `translate(${mx}px,${my}px)`; });
gsap.ticker.add(() => { rx += (mx - rx) * 0.16; ry += (my - ry) * 0.16; ring.style.transform = `translate(${rx}px,${ry}px)`; });
document.addEventListener('mouseover', e => {
  const h = e.target.closest('[data-hover], a, button, select, input');
  cur.classList.toggle('hover', !!h?.dataset.label);
  cur.classList.toggle('link', !!h && !h.dataset.label);
  clabel.textContent = h?.dataset.label || '';
});

/* ---------- text + motion helpers ---------- */
function split(el) {
  if (el._chars) return el._chars;
  const walk = n => [...n.childNodes].forEach(c => {
    if (c.nodeType === 3) {
      const f = document.createDocumentFragment();
      c.textContent.split(/(\s+)/).forEach(w => {
        if (!w) return;
        if (/^\s+$/.test(w)) return f.append(' ');
        const o = document.createElement('span'); o.className = 'w';
        [...w].forEach(ch => { const s = document.createElement('span'); s.className = 'c'; s.textContent = ch; o.append(s); });
        f.append(o);
      });
      c.replaceWith(f);
    } else if (c.nodeType === 1 && c.tagName !== 'BR') walk(c);
  });
  walk(el);
  return (el._chars = $$('.c', el));
}
function scramble(el, text = el.dataset.count, dur = 900) {
  const t0 = performance.now();
  const tick = now => {
    const p = Math.min((now - t0) / dur, 1), fixed = Math.floor(p * text.length);
    el.textContent = [...text].map((ch, i) => (i < fixed || !/\d/.test(ch) ? ch : (Math.random() * 10) | 0)).join('');
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  setTimeout(() => (el.textContent = text), dur + 120);   // rAF can be throttled in background tabs
}
function enter(view) {
  $$('.split', view).forEach((el, i) => gsap.from(split(el), { yPercent: 115, rotate: 5, duration: 1.3, ease, stagger: 0.022, delay: 0.05 + i * 0.1 }));
  const io = new IntersectionObserver(es => es.forEach(e => {
    if (!e.isIntersecting) return;
    const t = e.target; io.unobserve(t);
    if (t.classList.contains('split-in')) gsap.from(split(t), { yPercent: 115, duration: 1.1, ease, stagger: 0.02 });
    $$('[data-count]', t).forEach(c => scramble(c));
  }), { threshold: 0.1 });
  $$('[data-reveal], .split-in', view).forEach(el => io.observe(el));
  $$('[data-count]', view).filter(c => !c.closest('[data-reveal]')).forEach(c => scramble(c));
  return io;
}
function bind(view) {

}
function toast(msg) {
  const t = $('#toast'); t.textContent = msg;
  gsap.timeline().fromTo(t, { yPercent: 150 }, { yPercent: 0, duration: 0.6, ease }).to(t, { yPercent: 150, duration: 0.5, ease: 'expo.in' }, '+=3');
}
const mix = (a, b, t) => { const p = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16)); const A = p(a), B = p(b); return `rgb(${A.map((v, i) => Math.round(v + (B[i] - v) * t)).join(',')})`; };
function trackPath(x, z, box = 100, pad = 6) {
  const [x0, x1, z0, z1] = [Math.min(...x), Math.max(...x), Math.min(...z), Math.max(...z)];
  const s = (box - 2 * pad) / Math.max(x1 - x0, z1 - z0 || 1);
  const ox = pad + (box - 2 * pad - (x1 - x0) * s) / 2, oz = pad + (box - 2 * pad - (z1 - z0) * s) / 2;
  const T = (a, b) => [ox + (a - x0) * s, oz + (b - z0) * s], P = i => T(x[i], z[i]);
  return { P, T, d: x.map((_, i) => (i ? 'L' : 'M') + P(i).map(v => v.toFixed(1)).join(' ')).join('') };
}
const maps = {};
const getMap = id => (maps[id] ??= api(`/laps/${id}/map`).catch(() => null));

/* ---------- live stream (status pill, toasts, live page) ---------- */
const bus = new Set();
let live = {}, lastLap;
const es = new EventSource('/api/live');
es.onmessage = e => {
  live = JSON.parse(e.data);
  const r = $('#rec');
  r.classList.toggle('on', !!live.recording);
  r.classList.toggle('pit', !!live.connected && !live.recording);
  $('#sigk').textContent = live.recording ? 'On track' : live.connected ? 'In session' : 'Driver';
  $('#sigv').textContent = live.recording ? fmt(live.lap_ms) : live.connected ? 'In the pits' : 'Offline';
  $('.prog', r).style.strokeDashoffset = 94.25 * (1 - (live.recording ? live.pos || 0 : 0));
  const top = live.recent?.[0]?.id;
  if (lastLap !== undefined && top && top !== lastLap) toast(`Lap saved ${fmt(live.recent[0].lap_ms)}${live.recent[0].valid ? '' : ' (cut)'}`);
  lastLap = top ?? null;
  bus.forEach(f => f(live));
};

/* ---------- router + page transitions ---------- */
const wipe = $('.wipe'), wtitle = $('.wipe-title');
const wipeIn = title => { wtitle.textContent = title; return gsap.timeline().set(wipe, { transformOrigin: 'bottom' }).fromTo(wipe, { scaleY: 0 }, { scaleY: 1, duration: 0.65, ease: 'expo.inOut' }).fromTo(wtitle, { yPercent: 60, opacity: 0 }, { yPercent: 0, opacity: 1, duration: 0.5, ease }, '-=.3'); };
const wipeOut = () => gsap.timeline().to(wtitle, { yPercent: -60, opacity: 0, duration: 0.4, ease: 'expo.in' }).set(wipe, { transformOrigin: 'top' }).to(wipe, { scaleY: 0, duration: 0.75, ease: 'expo.inOut' }, '-=.1');
const settle = (tl, ms) => Promise.race([tl, new Promise(r => setTimeout(r, ms))]);   // never hang on a paused animation
const pages = { 404: notFound, '': home, laps: dash, compare, stats: statsPage, session: sessionPage, live: livePage, refs };
const titles = { '': 'Ghostline', laps: 'Laps', compare: 'Delta', stats: 'Stats', session: 'Session', live: 'Live', refs: 'Refs', 404: '404' };
const descs = {   // mirrors PAGES in backend/app.py
  '': 'Sim racing telemetry lab. Every lap against the fastest drivers, corner by corner.',
  laps: 'Every logged lap: mine and the fastest clean ghost laps, by car and track.',
  compare: 'Two laps on one distance grid: delta, speed, inputs and the corners where the time goes.',
  stats: 'Ghost leaderboard with sector times, the ideal lap and lap time progress.',
  session: 'One session lap by lap: consistency, spread and best sectors.',
  live: 'Live timing from the car: deltas, sectors, standings, tyres and fuel.',
  refs: 'Where the reference laps come from: online ghosts and real-world data.',
  404: 'Nothing at this address.' };
function notFound(view) { view.innerHTML = `<section class="empty"><div class="eyebrow">404 / <b>off track</b></div>
  <h1 class="mega split">Wrong<br><em>turn</em></h1><p>Nothing at this address. The link may be old or the lap may have been pruned.</p>
  <div><a class="btn solid" href="/" data-hover><span>Back to the start</span></a> &nbsp; <a class="btn" href="/laps" data-hover><span>All laps</span></a></div></section>`; }
let cleanup = null, io = null, first = true, seq = 0, ADMIN = false, SAMPLES = 0;

async function route() {
  const my = ++seq;
  const [name = '', ...args] = location.pathname.replace(/^\/+|\/+$/g, '').split('/');
  const page = name in pages ? name : '404';
  $$('.nav .roll').forEach(a => a.classList.toggle('on', a.getAttribute('href') === '/' + page));
  if (first) { const s = await api('/state').catch(() => ({})); ADMIN = !!s.admin; SAMPLES = s.samples || 0; document.body.classList.toggle('public', !ADMIN); }
  if (!first) await settle(wipeIn(titles[page]), 900);
  document.title = page ? `${page === '404' ? 'Not found' : page === 'refs' ? 'References' : titles[page]} · Ghostline` : 'Ghostline';
  $('meta[name="description"]').content = descs[page];
  if (my !== seq) return;                       // a newer navigation took over
  cleanup?.(); io?.disconnect(); cleanup = null;
  const view = $('#view'); view.innerHTML = '';
  lenis.scrollTo(0, { immediate: true });
  try { cleanup = await pages[page](view, args); }
  catch (e) { view.innerHTML = `<section class="empty"><div class="eyebrow">Something broke</div><h1 class="big split">Error</h1><p>${esc(e.message)}</p></section>`; }
  if (SAMPLES && page !== '404') view.insertAdjacentHTML('afterbegin', '<div class="sample-note mono">Sample laps (Monza and Spa) so you can look around. They disappear once your own laps start coming in.</div>');
  bind(view);
  first = false;
  await settle(wipeOut(), 1200);
  io = enter(view);
}
const nav = { set to(p) { if (p && p !== location.pathname) { history.pushState(null, '', p); route(); } } };
document.addEventListener('click', e => {   // in-app links: no full page loads
  const a = e.target.closest('a[href^="/"]');
  if (!a || a.target || e.ctrlKey || e.metaKey || e.shiftKey || /^\/(s|og|api)\//.test(a.getAttribute('href'))) return;
  e.preventDefault();
  nav.to = a.getAttribute('href');
});
addEventListener('popstate', route);
if (location.hash.startsWith('#/')) history.replaceState(null, '', location.hash.slice(1));   // old #/ links
route();

/* ---------- shared bits ---------- */
const stat = (k, v) => `<div class="stat"><div class="eyebrow">${k}</div><div class="v" data-count="${esc(v)}">${esc(v)}</div></div>`;
function rowHTML(l, i, isBest, go) {
  const tag = !l.valid ? '<span class="tag dim">Cut</span>' : isBest ? '<span class="tag">Best</span>' : `<span class="tag dim">${esc(l.source_label)}</span>`;
  return `<li class="row" data-go="${go}" data-id="${l.id}" data-hover data-label="Compare" data-reveal>
    <span class="mono">${String(i + 1).padStart(2, '0')}</span>
    <span class="time">${fmt(l.lap_ms)}</span>
    <span class="hide-s"><div class="tall" style="font-size:24px">${esc(l.car_name)}</div><div class="eyebrow">${esc(l.track_name)}</div></span>
    <span class="hide-s"><div>${esc(l.driver || '—')}</div><div class="eyebrow">${esc(l.source_label)} · ${ago(l.created)}</div></span>
    ${tag}<button class="del admin-only" data-del="${l.id}" title="Delete lap">×</button></li>`;
}
function rowEvents(list, view) {
  const pv = $('#preview'), svg = $('svg', pv);
  let on = false, px = 0, py = 0;
  const hide = () => { on = false; gsap.to(pv, { scale: 0, rotate: 0, duration: 0.3, ease: 'expo.in', overwrite: true }); };
  const follow = () => {
    px += (mx - px) * 0.12; py += (my - py) * 0.12; pv.style.left = `${px + 36}px`; pv.style.top = `${py - 100}px`;
    if (on && !on.matches(':hover')) hide();   // left the row by scrolling, clicking or leaving the window
  };
  gsap.ticker.add(follow);
  list.addEventListener('mouseover', async e => {
    const row = e.target.closest('.row[data-id]');
    if (!row || row === on) return;
    on = row;
    gsap.to(pv, { scale: 1, rotate: -4, duration: 0.5, ease, overwrite: true });
    const m = await getMap(row.dataset.id);
    if (on !== row) return;
    svg.innerHTML = m ? `<path d="${trackPath(m.x, m.z).d}Z" fill="none" stroke="#07060d" stroke-width="2.6" stroke-linejoin="round"/>` : '';
    const p = $('path', svg);
    if (p) { const L = p.getTotalLength(); gsap.fromTo(p, { strokeDasharray: L, strokeDashoffset: L }, { strokeDashoffset: 0, duration: 0.9, ease: 'power2.out' }); }
  });
  list.addEventListener('mouseleave', hide);
  document.addEventListener('mouseleave', hide);
  list.addEventListener('click', async e => {
    const del = e.target.closest('[data-del]');
    if (del) {
      e.stopPropagation();
      if (!confirm('Delete this lap for good?')) return;
      await api(`/laps/${del.dataset.del}`, { method: 'DELETE' });
      const row = del.closest('.row');
      gsap.to(row, { height: 0, paddingBlock: 0, opacity: 0, duration: 0.5, ease: 'expo.inOut', onComplete: () => row.remove() });
      return;
    }
    const row = e.target.closest('.row[data-go]');
    if (row && row.dataset.go) nav.to = row.dataset.go;
  });
  return () => { gsap.ticker.remove(follow); document.removeEventListener('mouseleave', hide); hide(); };
}

/* ---------- page: landing ---------- */
const vizEmpty = t => `<div class="viz empty-viz mono">${t}</div>`;
function vizDrive(c) {
  if (!c) return vizEmpty('Drive a clean lap to fill this');
  const W = 600, H = 150, sp = c.a_s.speed, n = sp.length, k = Math.max(1, Math.floor(n / 300)), hi = Math.max(...sp) * 1.05;
  const x = i => (i / (n - 1) * W).toFixed(1), y = v => (H - 34 - v / hi * (H - 44)).toFixed(1);
  const line = sp.filter((_, i) => i % k === 0).map((v, j) => `${j ? 'L' : 'M'}${x(j * k)},${y(v)}`).join('');
  const band = (arr, top, col) => (arr || []).map((v, i) => i % k === 0 && v > 0.05 ? `<rect x="${x(i)}" y="${top}" width="${(k / n * W + .6).toFixed(1)}" height="8" fill="${col}" opacity="${(.25 + v * .75).toFixed(2)}"/>` : '').join('');
  return `<div class="viz"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Speed, throttle and brake over one lap">
    <path d="${line}" fill="none" stroke="${C.fg}" stroke-width="1.6"/>${band(c.a_s.throttle, H - 26, C.gain)}${band(c.a_s.brake, H - 14, C.loss)}</svg>
    <div class="viz-cap mono"><span>Speed / <b style="color:${C.gain}">throttle</b> / <b style="color:${C.loss}">brake</b></span><span>${fmt(c.a.lap_ms)} · ${(c.L / 1000).toFixed(2)} km</span></div></div>`;
}
function vizGhosts(sb) {
  const rows = (sb?.board || []).filter(r => r.kind !== 'ideal').sort((a, b) => a.lap_ms - b.lap_ms);
  if (!rows.some(r => r.kind === 'ghost')) return vizEmpty('Race online with the in-game app on to catch ghosts');
  const p1 = rows[0].lap_ms;
  return `<div class="viz"><table class="viz-board">${rows.map((r, i) => `<tr class="${r.kind === 'me' ? 'me' : ''}"><td class="mono">P${i + 1}</td>
    <td>${r.kind === 'me' ? 'You' : esc(r.driver)}</td><td class="num">${fmt(r.lap_ms)}</td><td class="num mono">${i ? sgn((r.lap_ms - p1) / 1000) : 'fastest'}</td></tr>`).join('')}</table>
    <div class="viz-cap mono"><span>${esc(sb.laps?.[0]?.car_name || '')}</span><span>Cut laps removed</span></div></div>`;
}
function vizDebrief(c) {
  const cs = c?.corners || [];
  if (!cs.length) return vizEmpty('Needs a ghost on the same track');
  const top = Math.max(...cs.map(k => Math.abs(k.loss)), 0.05);
  return `<div class="viz"><div class="viz-bars">${cs.map(k => `<div><span>${esc(k.name)}</span><i><b class="${k.loss > 0 ? 'l' : 'g'}" style="width:${(Math.abs(k.loss) / top * 100).toFixed(1)}%"></b></i>
    <span class="num ${k.loss > 0 ? 'loss' : 'gain'}">${sgn(k.loss)}</span></div>`).join('')}</div>
    <div class="viz-cap mono"><span>Time lost per corner vs ghost</span><span>${sgn(c.total)} s total</span></div></div>`;
}
function vizTracks(ct) {
  if (!ct?.tracks?.length) return vizEmpty('Official tracks show up once Assetto Corsa is found');
  const ts = [...ct.tracks].sort((a, b) => b.laps - a.laps || a.name.localeCompare(b.name));
  return `<div class="viz"><div class="viz-tracks">${ts.map(t => `<span class="${t.laps ? 'on' : ''}">${esc(t.name)}${t.layouts > 1 ? ` <small>×${t.layouts}</small>` : ''}${t.laps ? ` <b>${t.laps} laps</b>` : ''}</span>`).join('')}</div>
    <div class="viz-cap mono"><span>${ts.length} tracks · ${ct.layouts} layouts · ${ct.cars} official cars</span><span><b style="color:${C.acc}">Lit</b> = laps logged</span></div></div>`;
}

async function home(view) {
  const st = await api('/state');
  const g = st.groups[0];
  const c = st.latest_best ? await api(`/compare?a=${st.latest_best}`).catch(() => null) : null;
  const [sb, ct] = await Promise.all([c ? api(`/stats?car=${enc(c.a.car)}&track=${enc(c.a.track)}`).catch(() => null) : null, api('/content').catch(() => null)]);
  const ins = c?.insights || [];
  const gap = g?.ref_best ? sgn((g.best - g.ref_best) / 1000) : '—';
  view.innerHTML = `
  <section class="hero2">
    <svg class="htrack" id="htrack" role="img" aria-label="Track map with a ghost lap replay"></svg>
    <div>
      <div class="eyebrow"><span class="pill-live ${live.recording ? 'on' : ''}" id="hlive"><i></i><span>${live.recording ? 'On track right now' : 'Sim racing telemetry lab'}</span></span></div>
      <h1 class="mega split" style="margin-top:22px">Chase<br>the <em>ghost</em></h1>
      <p class="lede">Every lap I drive in Assetto Corsa, raced against the fastest driver on the same server. Lined up metre by metre, so the lost time gets a name.</p>
      <div class="ctas"><a class="btn solid" href="/compare" data-hover><span>See where the time goes</span></a><a class="btn" href="/live" data-hover><span>Watch live</span></a></div>
    </div>
    ${c ? `<div class="hud"><div><small>${esc(c.track_name)} / me</small><b>${fmt(c.a.lap_ms)}</b></div><div><small>Ghost</small><b class="ghost">${fmt(c.b.lap_ms)}</b></div><div><small>Gap on track</small><b id="hgap">±0.000</b></div></div>` : ''}
    <div class="cue">Scroll</div>
  </section>
  <section>
    <div class="stats" style="margin-top:0">${stat('Laps logged', String(st.total))}${stat('Personal best', fmt(g?.best))}${stat('Ideal lap', fmt(g?.ideal))}${stat('Ghost best', fmt(g?.ref_best))}${stat('Gap to ghost', gap)}</div>
  </section>
  ${ins.length ? `<section>
    <h2 class="big split-in">Where the<br><em>time</em> goes</h2>
    <p class="mono" style="margin-top:14px">${esc(c.track_name)} · ${esc(c.a.car_name)} · latest best vs fastest ghost</p>
    <ol class="fix">${ins.map((s, i) => `<li data-reveal data-hover data-label="Open" data-go="/compare/${c.a.id}/${c.b.id}">
      <span class="n">0${i + 1} / ${String(ins.length).padStart(2, '0')}</span><h3 class="wide">${esc(s.corner)}</h3>
      <span class="l loss">${sgn(s.loss)} s</span>${s.tips.slice(0, 2).map(t => `<p>${esc(t)}</p>`).join('')}</li>`).join('')}</ol>
  </section>` : ''}
  <section>
    <h2 class="big split-in">How it<br><em>works</em></h2>
    <div class="steps">
      <div class="step" data-reveal><div class="no">01</div><div><h3 class="wide">Drive</h3><p>Every lap is recorded at 60 Hz straight from the game: speed, throttle, brake, gear and the exact line. Nothing to start, nothing to export.</p></div>${vizDrive(c)}</div>
      <div class="step" data-reveal><div class="no">02</div><div><h3 class="wide">Catch ghosts</h3><p>An in-game logger captures every other car on the server. Laps that cut the track are thrown out, and only the three fastest drivers stay as ghosts.</p></div>${vizGhosts(sb)}</div>
      <div class="step" data-reveal><div class="no">03</div><div><h3 class="wide">Debrief</h3><p>Laps are lined up metre by metre. Braking points, apex speed and throttle pick-up turn the gap into three things to fix.</p></div>${vizDebrief(c)}</div>
      <div class="step" data-reveal><div class="no">04</div><div><h3 class="wide">Any track</h3><p>Car, track and layout are picked up from the game. Names, lengths and corner names come from the official Assetto Corsa content, so a new combo needs no setup.</p></div>${vizTracks(ct)}</div>
    </div>
  </section>
  <section class="outro"><a href="/laps" class="mega outro-link" data-hover data-label="Open">Every<br><em>lap</em> &rarr;</a></section>`;
  view.addEventListener('click', e => { const r = e.target.closest('[data-go]'); if (r) nav.to = r.dataset.go; });
  const onLive = s => { const h = $('#hlive', view); if (!h) return; h.classList.toggle('on', !!s.recording); h.lastElementChild.textContent = s.recording ? 'On track right now' : 'Sim racing telemetry lab'; };
  bus.add(onLive);
  const stop = c ? raceHero($('#htrack', view), c, $('#hgap', view)) : () => {};
  return () => { stop(); bus.delete(onLive); };
}

function raceHero(svg, c, gapEl) {
  const m = c.map;
  if (!m || !m.ta) return () => {};
  const W = 1000, n = m.x.length, { P, d } = trackPath(m.x, m.z, W, 60);
  svg.setAttribute('viewBox', `0 0 ${W} ${W}`);
  svg.innerHTML = `<path d="${d}Z" class="ht-base"/><path d="${d}Z" class="ht-line"/>
    <polyline class="ht-trail" points=""/>
    <g class="gh"><circle r="12" class="ht-ghost"/><text class="ht-lab" x="20" y="-16" fill="${C.acc}">GHOST</text></g>
    <g class="yo"><circle r="10" class="ht-you"/><text class="ht-lab" x="18" y="30" fill="${C.fg}">ME</text></g>`;
  const line = $('.ht-line', svg), L = line.getTotalLength(), trail = $('.ht-trail', svg), gh = $('.gh', svg), yo = $('.yo', svg);
  gsap.fromTo(line, { strokeDasharray: L, strokeDashoffset: L }, { strokeDashoffset: 0, duration: 2.4, ease: 'power3.inOut', delay: 0.4 });
  gsap.from([gh, yo], { opacity: 0, duration: 0.8, delay: 2.2 });
  const ta = m.ta, tb = m.tb, end = Math.max(ta[n - 1], tb[n - 1]) + 1.5, SPEED = 6;
  const at = (arr, t) => { let lo = 0, hi = n - 1; while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (arr[mid] <= t) lo = mid; else hi = mid - 1; } return lo; };
  const t0 = performance.now();
  let last = -1;
  const tick = () => {
    const t = (((performance.now() - t0) / 1000) * SPEED) % end;
    const ia = at(ta, t), ib = at(tb, t);
    const [ax, ay] = P(ia), [bx, by] = P(ib);
    yo.setAttribute('transform', `translate(${ax.toFixed(1)} ${ay.toFixed(1)})`);
    gh.setAttribute('transform', `translate(${bx.toFixed(1)} ${by.toFixed(1)})`);
    const pts = [];
    for (let i = Math.max(0, ib - 30); i <= ib; i++) pts.push(P(i).map(v => v.toFixed(1)).join(','));
    trail.setAttribute('points', pts.join(' '));
    if (gapEl && ia !== last) {
      last = ia;
      const v = c.delta[Math.min(c.delta.length - 1, Math.round((ia * m.step) / c.step))];
      gapEl.textContent = sgn(v);
      gapEl.className = v > 0 ? 'loss' : 'gain';
    }
  };
  gsap.ticker.add(tick);
  return () => gsap.ticker.remove(tick);
}

/* ---------- page: laps ---------- */
async function dash(view) {
  const [st, laps] = await Promise.all([api('/state'), api('/laps')]);
  if (!laps.length) {
    const a = st.app || {}, r = st.recorder || {};
    view.innerHTML = `<section class="empty"><div class="eyebrow">Ghostline / <b>waiting for data</b></div>
      <h1 class="mega split">No laps<br><em>yet</em></h1>
      <p class="admin-only">Start a session in Assetto Corsa and drive. Every completed lap lands here by itself, no buttons.
      Recorder: <b class="${r.enabled ? 'ok' : 'warn'}">${r.enabled ? (r.connected ? 'connected to AC' : 'on, waiting for AC') : 'off'}</b>.
      In-game app: <b class="${a.active ? 'ok' : 'warn'}">${a.active ? 'installed' : a.ac_path ? 'not active' : 'AC not found'}</b>.</p>
      <div style="display:flex;gap:12px;flex-wrap:wrap" class="admin-only"><a class="btn solid" href="/live" data-hover><span>Go live</span></a><a class="btn" href="/refs" data-hover><span>Get references</span></a></div></section>`;
    return;
  }
  const g = st.groups[0];
  const keys = [...new Map(laps.map(l => [`${l.car}|${l.track}`, `${l.car_name} · ${l.track_name}`])).entries()];
  const best = {};
  laps.forEach(l => { const k = `${l.car}|${l.track}|${l.source}`; if (l.valid && (!best[k] || l.lap_ms < best[k])) best[k] = l.lap_ms; });
  const marq = (st.groups.length ? st.groups : [{ car_name: laps[0].car_name, best: laps[0].lap_ms, track_name: laps[0].track_name }])
    .map(x => `<span class="wide">${esc(x.car_name)} <b>${fmt(x.best)}</b> ${esc(x.track_name)} /</span>`).join('');
  view.innerHTML = `
  <section class="hero">
    <div class="eyebrow">Ghostline / <b>${g ? `${esc(g.car_name)} · ${esc(g.track_name)}` : 'references only so far'}</b></div>
    <h1 class="mega split">Find the<br><em>lost</em> time</h1>
    <div class="stats">${stat('Laps logged', String(st.total))}${stat('Personal best', fmt(g?.best))}${stat('Ideal lap', fmt(g?.ideal))}${stat('Fastest ref', fmt(g?.ref_best))}${stat('Gap to ref', g?.ref_best ? sgn((g.best - g.ref_best) / 1000) : '—')}</div>
  </section>
  <section>
    <div class="laps-head"><h2 class="big split-in">Every<br><em>lap</em></h2>
      <div class="chips"><button class="chip on" data-f="all" data-hover>All</button>${keys.map(([k, v]) => `<button class="chip" data-f="${esc(k)}" data-hover>${esc(v)}</button>`).join('')}</div></div>
    <ol class="rows" id="rows"></ol>
  </section>`;
  const list = $('#rows', view);
  const render = f => {
    const ls = laps.filter(l => f === 'all' || `${l.car}|${l.track}` === f);
    list.innerHTML = ls.map((l, i) => rowHTML(l, i, l.valid && best[`${l.car}|${l.track}|${l.source}`] === l.lap_ms, `/compare/${l.id}`)).join('');
  };
  render('all');
  $('.chips', view).onclick = e => {
    const b = e.target.closest('[data-f]'); if (!b) return;
    $$('.chip', view).forEach(c => c.classList.toggle('on', c === b));
    render(b.dataset.f);
    gsap.from($$('.row', list), { y: 40, opacity: 0, duration: 0.8, ease, stagger: 0.03 });
  };
  return rowEvents(list, view);
}

/* ---------- page: compare ---------- */
async function compare(view, [a, b]) {
  if (!a) a = (await api('/state')).latest_best ?? (await api('/laps'))[0]?.id;
  if (!a) { view.innerHTML = `<section class="empty"><h1 class="mega split">Nothing<br><em>to compare</em></h1><p>Drive a few laps first.</p></section>`; return; }
  const ideal = String(a).startsWith('i'), lap = ideal ? String(a).slice(1) : String(a), aTok = (ideal ? 'i' : '') + lap;
  const refs = await api(`/references/${lap}`);
  b = b || (ideal ? refs.find(r => r.source !== 'player') || refs[0] : refs[0])?.id;
  if (!b) {
    view.innerHTML = `<section class="empty"><div class="eyebrow">Compare</div><h1 class="mega split">No ref<br><em>yet</em></h1>
      <p>There's no other lap on this track to compare against. Race online with the in-game app on, run an AI race, or import a real-world lap.</p>
      <div><a class="btn solid" href="/refs" data-hover><span>Get a reference</span></a></div></section>`;
    return;
  }
  const c = await api(`/compare?a=${lap}&b=${b}${ideal ? '&ideal=1' : ''}`);
  const A = c.a, B = c.b, tot = c.total;
  const row = (k, x, y, u = '') => `<tr><td>${k}</td><td>${x ?? '—'}${x != null ? u : ''}</td><td style="color:${C.acc}">${y ?? '—'}${y != null ? u : ''}</td></tr>`;
  view.innerHTML = `
  <section>
    <div class="eyebrow">Compare / <b>${esc(c.track_name)}</b> · ${(c.L / 1000).toFixed(2)} km${c.real ? ' · <b class="warn">different car class: shape comparison</b>' : ''}</div>
    <div class="duel">
      <div class="side"><label class="eyebrow">${ideal ? 'Ideal lap (best mini-sectors)' : 'Your lap'}</label><div class="t" data-count="${fmt(A.lap_ms)}">${fmt(A.lap_ms)}</div><div class="sub eyebrow">${ideal ? `${A.sources.length} laps stitched` : esc(A.driver)} · ${esc(A.car_name)}</div>${ideal ? '' : setupHTML(A)}</div>
      <div class="gapnum ${tot > 0 ? 'loss' : 'gain'}" data-count="${sgn(tot)}">${sgn(tot)}</div>
      <div class="side b"><label class="eyebrow">Reference</label><div class="t" data-count="${fmt(B.lap_ms)}">${fmt(B.lap_ms)}</div>
        <select class="refpick" id="refpick">${refs.map(r => `<option value="${r.id}" ${r.id == b ? 'selected' : ''}>${esc(r.tier_label)} · ${esc(r.driver || r.source_label)} · ${fmt(r.lap_ms)}</option>`).join('')}</select></div>
    </div>
    <div class="actions">
      ${A.source === 'player' ? `<a class="chip ${ideal ? '' : 'on'}" href="/compare/${lap}/${b}" data-hover>My lap</a><a class="chip ${ideal ? 'on' : ''}" href="/compare/i${lap}/${b}" data-hover>Ideal lap</a>` : ''}
      ${!ideal && A.source === 'player' ? `<a class="chip" href="/session/${lap}" data-hover>Session view</a>` : ''}
      <a class="chip" href="/stats" data-hover>Leaderboard</a>
      <button class="chip" id="sharebtn" data-hover>Share &#8599;</button>
    </div>
  </section>
  <section>
    <h2 class="big split-in">${c.insights.length ? `${String(c.insights.length).padStart(2, '0')} things<br><em>to fix</em>` : 'Clean<br><em>lap</em>'}</h2>
    <ol class="fix">${c.insights.map((s, i) => `<li data-reveal data-hover data-label="Zoom" data-zoom="${s.start},${s.end}">
      <span class="n">0${i + 1} / ${String(c.insights.length).padStart(2, '0')}</span><h3 class="wide">${esc(s.corner)}</h3>
      <span class="l loss">${sgn(s.loss)} s</span>${s.tips.map(t => `<p>${esc(t)}</p>`).join('')}</li>`).join('')}</ol>
  </section>
  <section class="analysis">
    <div class="mapbox" data-reveal><div class="eyebrow">Where the time goes · click a corner to zoom</div><svg id="map" role="img" aria-label="Track map coloured by time gained and lost per corner"></svg><button class="chip zreset" hidden data-hover>Full track</button>
      <div class="legend mono"><span><i style="background:${C.gain}"></i>gaining</span><span><i style="background:${C.loss}"></i>losing</span>${c.map?.bx ? `<span><i style="background:${C.fg}"></i>my line</span><span><i style="background:${C.acc}"></i>ghost line</span>` : ''}</div></div>
    <div data-reveal><div class="keys mono"><span><i style="background:${C.fg}"></i>You</span><span><i style="background:${C.acc}"></i>Reference</span>${A.est || B.est ? '<span>dotted = estimated pedals</span>' : ''}<span>drag to zoom · double-click resets</span></div>
      <div class="chartbox"><div id="chart"></div><div class="vline"></div></div></div>
  </section>
  <section>
    <h2 class="big split-in">Corner<br>by <em>corner</em></h2>
    <div class="hs">${c.corners.map(k => `<div class="card" data-hover data-label="Zoom" data-zoom="${k.start},${k.end}">
      <span class="mono">${k.apex_d} m</span><h4 class="wide">${esc(k.name)}</h4><div class="l ${k.loss > 0 ? 'loss' : 'gain'}">${sgn(k.loss)} s</div>
      <table><tr><td></td><td>you</td><td style="color:${C.acc}">ref</td></tr>${row('Brake at', k.a.brake, k.b.brake, ' m')}${row('Min speed', k.a.min_speed, k.b.min_speed)}${row('Throttle at', k.a.throttle, k.b.throttle, ' m')}${row('Exit speed', k.a.exit, k.b.exit)}${row('Coasting', k.a.coast, k.b.coast, ' s')}${row('Apex gear', k.a.gear, k.b.gear)}</table></div>`).join('')}</div>
  </section>`;

  $('#refpick', view).onchange = e => (nav.to = `/compare/${aTok}/${e.target.value}`);
  $('#sharebtn', view).onclick = () => shareLink(aTok, b);
  bindSetup(view, A);
  const chart = $('#chart', view), vline = $('.vline', view);
  const mapCtl = drawMap($('#map', view), c, d => sync(d)), setDot = mapCtl.dot;
  drawChart(chart, c);
  function sync(d) {
    setDot(d);
    if (d == null) return (vline.style.opacity = 0);
    const xa = chart._fullLayout?.xaxis;
    if (!xa) return;
    const px = xa.l2p(d) + chart._fullLayout._size.l;
    vline.style.opacity = px >= chart._fullLayout._size.l ? 1 : 0;
    vline.style.transform = `translateX(${px}px)`;
  }
  chart.on('plotly_hover', e => sync(e.points[0].x));
  chart.on('plotly_unhover', () => sync(null));
  view.addEventListener('click', e => {
    const z = e.target.closest('[data-zoom]'); if (!z) return;
    const [s, en] = z.dataset.zoom.split(',').map(Number);
    Plotly.relayout(chart, { 'xaxis.range': [Math.max(0, s - 60), en + 60] });
    mapCtl.zoom(s, en);
    lenis.scrollTo(chart, { offset: -110, duration: 1.4 });
  });
  return () => Plotly.purge(chart);
}

const abbr = n => { const w = n.split(/\s+/); return (w.length > 1 ? w[0].slice(0, 2) + w.slice(1).map(x => x[0]).join('') : n.slice(0, 3)).toUpperCase(); };
function drawChart(el, c) {
  const narrow = el.clientWidth < 700;
  const x = c.d, rows = [['speed', 'KM/H', 0.34], ['delta', 'GAP S', 0.17], ['throttle', 'THROTTLE', 0.13], ['brake', 'BRAKE', 0.13], ['gear', 'GEAR', 0.11]];
  const traces = [], layout = {
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { family: 'Sligoil', color: C.mute, size: 10 },
    margin: { l: narrow ? 52 : 64, r: 8, t: narrow ? 40 : 26, b: 30 }, showlegend: false, hovermode: 'x unified', dragmode: matchMedia('(pointer: coarse)').matches ? false : 'zoom',
    hoverlabel: { bgcolor: '#07060d', bordercolor: C.acc, font: { color: C.fg, family: 'Sligoil', size: 11 } },
    shapes: c.corners.map(k => ({ type: 'rect', xref: 'x', yref: 'paper', x0: k.b.brake ?? k.apex_d - 60, x1: k.b.throttle ?? k.apex_d + 60, y0: 0, y1: 1, fillcolor: 'rgba(236,231,220,.035)', line: { width: 0 }, layer: 'below' })),
    annotations: c.corners.map((k, i) => ({ x: k.apex_d, y: narrow && i % 2 ? 1.022 : 1, xref: 'x', yref: 'paper', yanchor: 'bottom', text: narrow ? abbr(k.name) : k.name.toUpperCase(), showarrow: false, font: { size: narrow ? 9 : 10, color: C.fg } })),
  };
  let top = 1;
  rows.forEach(([k, label, h], i) => {
    const n = i ? i + 1 : '', xa = 'x' + n, ya = 'y' + n;
    layout['yaxis' + n] = { domain: [top - h, top], title: { text: label, font: { size: 9 }, standoff: 6 }, gridcolor: C.line, zeroline: k === 'delta', zerolinecolor: C.mute, fixedrange: true, tickfont: { size: 9 } };
    layout['xaxis' + n] = { anchor: ya, showticklabels: i === rows.length - 1, ticksuffix: ' m', gridcolor: C.line, zeroline: false, ...(i ? { matches: 'x' } : {}) };
    top -= h + 0.03;
    const base = { x, xaxis: xa, yaxis: ya, type: 'scatter', mode: 'lines' };
    if (k === 'delta') {
      traces.push({ ...base, y: c.delta.map(v => Math.max(v, 0)), line: { width: 0 }, fill: 'tozeroy', fillcolor: 'rgba(255,79,129,.35)', hoverinfo: 'skip' });
      traces.push({ ...base, y: c.delta.map(v => Math.min(v, 0)), line: { width: 0 }, fill: 'tozeroy', fillcolor: 'rgba(66,245,200,.30)', hoverinfo: 'skip' });
      traces.push({ ...base, y: c.delta, line: { color: C.fg, width: 1.4 }, hovertemplate: 'gap %{y:+.3f}s<extra></extra>' });
      return;
    }
    for (const [s, col, nm, est] of [[c.b_s, C.acc, 'ref', c.b.est], [c.a_s, C.fg, 'you', c.a.est]]) {
      if (!s[k]) continue;
      traces.push({ ...base, y: s[k], line: { color: col, width: k === 'speed' ? 1.8 : 1.3, dash: est && (k === 'throttle' || k === 'brake') ? 'dot' : 'solid', shape: k === 'gear' ? 'hv' : 'linear' },
        hovertemplate: `${nm} %{y:.${k === 'speed' ? 0 : k === 'gear' ? 0 : 2}f}<extra></extra>` });
    }
  });
  Plotly.newPlot(el, traces, layout, { displayModeBar: false, responsive: true });
}

function drawMap(svg, c, onHover) {
  const m = c.map, noop = { dot: () => {}, zoom: () => {}, reset: () => {} };
  if (!m) { svg.outerHTML = '<p class="mono">No coordinates in these laps.</p>'; return noop; }
  const W = 1000, { P, T, d } = trackPath(m.x, m.z, W, 50), n = m.x.length;
  svg.setAttribute('viewBox', `0 0 ${W} ${W}`);
  const col = r => { const t = Math.max(-1, Math.min(1, r / 0.02)); return t >= 0 ? mix(C.dim, C.loss, t) : mix(C.dim, C.gain, -t); };
  let segs = '';
  for (let i = 1; i < n; i++) { const [x1, y1] = P(i - 1), [x2, y2] = P(i); segs += `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="${col(m.rate[i])}"/>`; }
  const scale = (svg.clientWidth || 400) / W, narrow = svg.clientWidth < 500, fs = Math.max(20, 11 / scale);   // ~11px labels at any size
  const labels = c.corners.map((k, i) => { const [x, y] = P(Math.min(n - 1, Math.round(k.apex_d / m.step))), left = i % 2;
    return `<g class="lab"><circle cx="${x}" cy="${y}" r="${fs / 4}" fill="${C.fg}"/><text x="${left ? x - fs * .6 : x + fs * .6}" y="${y - fs * .5}" text-anchor="${left ? 'end' : 'start'}" fill="${C.fg}" font-family="Sligoil" font-size="${fs}">${esc(narrow ? abbr(k.name) : k.name.toUpperCase())}</text></g>`; }).join('');
  const [sx, sy] = P(0);
  svg.innerHTML = `<path class="base" d="${d}" fill="none" stroke="#1a1628" stroke-width="16" stroke-linecap="round" stroke-linejoin="round"/>
    <g class="segs" stroke-width="5" stroke-linecap="round" opacity="0">${segs}</g><g class="ovl"></g>
    <rect x="${sx - 4}" y="${sy - 22}" width="8" height="44" fill="${C.fg}"/>${labels}
    <circle class="mdot" r="16" fill="${C.acc}" stroke="#07060d" stroke-width="5" opacity="0"/>`;
  const base = $('.base', svg), L = base.getTotalLength(), mdot = $('.mdot', svg), zbtn = svg.parentElement.querySelector('.zreset');
  gsap.fromTo(base, { strokeDasharray: L, strokeDashoffset: L }, { strokeDashoffset: 0, duration: 2, ease: 'power3.inOut', delay: 0.3, onComplete: () => base.removeAttribute('style') });
  gsap.to($('.segs', svg), { opacity: 1, duration: 1, delay: 1.6 });
  gsap.from($$('.lab', svg), { opacity: 0, scale: 0, transformOrigin: 'center', stagger: 0.08, delay: 1.8, duration: 0.6, ease: 'back.out(3)' });
  let k = 1;
  svg.addEventListener('mousemove', e => {
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(svg.getScreenCTM().inverse());
    let bi = 0, bd = Infinity;
    for (let i = 0; i < n; i++) { const [x, y] = P(i), dd = (x - pt.x) ** 2 + (y - pt.y) ** 2; if (dd < bd) { bd = dd; bi = i; } }
    onHover(bd < 3600 * k * k ? bi * m.step : null);
  });
  svg.addEventListener('mouseleave', () => onHover(null));
  const reset = () => {
    k = 1; svg.classList.remove('zoomed'); $('.ovl', svg).innerHTML = '';
    gsap.to(svg, { attr: { viewBox: `0 0 ${W} ${W}` }, duration: 1, ease: 'expo.inOut' });
    gsap.to(mdot, { attr: { r: 16, 'stroke-width': 5 }, duration: 1 });
    if (zbtn) zbtn.hidden = true;
  };
  if (zbtn) zbtn.onclick = reset;
  return {
    dot: dist => {
      if (dist == null) return gsap.to(mdot, { opacity: 0, duration: 0.2 });
      const [x, y] = P(Math.min(n - 1, Math.max(0, Math.round(dist / m.step))));
      gsap.to(mdot, { attr: { cx: x, cy: y }, opacity: 1, duration: 0.15, overwrite: 'auto' });
    },
    zoom: (s0, e0) => {   // zoom onto one corner and overlay both racing lines
      const i0 = Math.max(0, Math.floor(s0 / m.step)), i1 = Math.min(n - 1, Math.ceil(e0 / m.step)), A = [], B = [];
      for (let i = i0; i <= i1; i++) { A.push(P(i)); if (m.bx) B.push(T(m.bx[i], m.bz[i])); }
      const all = A.concat(B), xs = all.map(p => p[0]), ys = all.map(p => p[1]);
      const size = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), 60) * 1.3;
      const cx = (Math.max(...xs) + Math.min(...xs)) / 2, cy = (Math.max(...ys) + Math.min(...ys)) / 2;
      k = size / W;
      const pl = (pts, cls) => `<polyline class="${cls}" points="${pts.map(p => p.map(v => v.toFixed(1)).join(',')).join(' ')}"/>`;
      $('.ovl', svg).innerHTML = (B.length ? pl(B, 'ov-b') : '') + pl(A, 'ov-a');
      svg.classList.add('zoomed');
      gsap.to(svg, { attr: { viewBox: `${cx - size / 2} ${cy - size / 2} ${size} ${size}` }, duration: 1.1, ease: 'expo.inOut' });
      gsap.to(mdot, { attr: { r: 16 * k, 'stroke-width': 5 * k }, duration: 1.1 });
      if (zbtn) zbtn.hidden = false;
    },
    reset,
  };
}


/* ---------- page: stats (leaderboard + progress) ---------- */
const enc = encodeURIComponent;
const who = r => r.kind === 'me' ? 'Me' : r.kind === 'ideal' ? 'Ideal lap' : r.driver;
async function statsPage(view, [key]) {
  const st = await api('/state');
  if (!st.groups.length) { view.innerHTML = `<section class="empty"><h1 class="mega split">No stats<br><em>yet</em></h1><p>Drive a few laps first.</p></section>`; return; }
  const g = (key && st.groups.find(x => `${x.car}|${x.track}` === decodeURIComponent(key))) || st.groups[0];
  const s = await api(`/stats?car=${enc(g.car)}&track=${enc(g.track)}`);
  const p1 = s.board[0]?.lap_ms, ghost1 = s.board.find(r => r.kind === 'ghost');
  const go = r => r.kind === 'ghost' ? `/compare/${s.best_id}/${r.id}` : r.kind === 'ideal' ? `/compare/i${s.best_id}${ghost1 ? '/' + ghost1.id : ''}` : `/compare/${s.best_id}`;
  view.innerHTML = `
  <section>
    <div class="eyebrow">Stats / <b>${esc(g.car_name)} · ${esc(g.track_name)}</b></div>
    <h1 class="mega split" style="margin-top:20px">The<br><em>board</em></h1>
    ${st.groups.length > 1 ? `<div class="chips" style="margin-top:28px">${st.groups.map(x => `<a class="chip ${x === g ? 'on' : ''}" href="/stats/${enc(x.car + '|' + x.track)}" data-hover>${esc(x.car_name)} · ${esc(x.track_name)}</a>`).join('')}</div>` : ''}
    <div class="stats">${stat('Personal best', fmt(g.best))}${stat('Ideal lap', fmt(s.ideal_ms))}${stat('Ghost best', fmt(s.ghost_best))}${stat('Sessions', String(s.sessions.length))}${stat('Laps', String(s.laps.length))}</div>
  </section>
  <section>
    <h2 class="big split-in">Ghost<br><em>leaderboard</em></h2>
    <div class="board" data-reveal><table>
      <tr><th>Pos</th><th>Driver</th><th>Lap</th><th>Gap</th><th>S1</th><th>S2</th><th>S3</th></tr>
      ${s.board.map((r, i) => `<tr class="k-${r.kind}" data-go="${go(r)}" data-hover data-label="Compare">
        <td class="mono">${String(i + 1).padStart(2, '0')}</td><td><b>${esc(who(r))}</b>${r.kind === 'ghost' ? `<span class="mono"> ${esc(r.source_label || r.source)}</span>` : ''}</td>
        <td class="num">${fmt(r.lap_ms)}</td><td class="num">${i ? sgn((r.lap_ms - p1) / 1000) : '—'}</td>
        ${r.sectors.map((x, k) => `<td class="num ${x === s.best_sectors[k] ? 'pb' : ''}">${x.toFixed(3)}</td>`).join('')}</tr>`).join('')}
    </table></div>
    <p class="mono" style="margin-top:14px">Violet = fastest sector on the board. Tap a row to compare it.</p>
  </section>
  <section>
    <h2 class="big split-in">Pro<em>gress</em></h2>
    <div id="prog" data-reveal></div>
    <div class="sess">${s.sessions.map(x => `<a class="scard" href="/session/${x.id}" data-reveal data-hover data-label="Open">
      <span class="mono">${new Date(x.start * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}</span>
      <b class="num">${fmt(x.best)}</b>
      <span class="mono">${x.valid}/${x.n} clean laps · avg ${fmt(x.avg)} · ± ${x.spread == null ? '—' : (x.spread / 1000).toFixed(2) + ' s'}</span></a>`).join('')}</div>
  </section>`;
  view.addEventListener('click', e => { const r = e.target.closest('tr[data-go]'); if (r) nav.to = r.dataset.go; });
  const L = s.laps, el = $('#prog', view);
  if (L.length) {
    const xs = L.map((_, i) => i + 1), ys = L.map(l => l.lap_ms / 1000), v = L.map(l => l.valid);
    let pb = Infinity; const pbs = L.map(l => (l.valid && l.lap_ms < pb ? (pb = l.lap_ms) : pb) / 1000);
    const lo = Math.min(...ys, (s.ghost_best || 1e9) / 1000) - 0.5, hi = Math.min(Math.max(...ys), Math.min(...ys) * 1.07) + 0.5;
    const ticks = []; for (let t = Math.ceil(lo); t <= hi; t++) ticks.push(t);
    const hline = (y, col, dash, name) => y ? { x: [1, L.length], y: [y / 1000, y / 1000], mode: 'lines', line: { color: col, dash, width: 1.5 }, name, hovertemplate: `${name} ${fmt(y)}<extra></extra>` } : null;
    Plotly.newPlot(el, [
      hline(s.ghost_best, C.acc, 'dash', 'Ghost'), hline(s.ideal_ms, C.vio, 'dot', 'Ideal'),
      { x: xs, y: pbs, mode: 'lines', line: { color: C.fg, width: 2, shape: 'hv' }, name: 'PB', hoverinfo: 'skip' },
      { x: xs, y: ys, mode: 'markers', marker: { size: 9, color: v.map(ok => ok ? C.vio : 'rgba(0,0,0,0)'), line: { color: v.map(ok => ok ? C.vio : C.mute), width: 1.5 } },
        text: L.map(l => fmt(l.lap_ms) + (l.valid ? '' : ' (cut)')), hovertemplate: 'Lap %{x}: %{text}<extra></extra>' },
    ].filter(Boolean), {
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { family: 'Sligoil', color: C.mute, size: 10 }, showlegend: false,
      margin: { l: 64, r: 10, t: 10, b: 36 }, hovermode: 'closest', dragmode: false,
      hoverlabel: { bgcolor: '#07060d', bordercolor: C.vio, font: { color: C.fg, family: 'Sligoil' } },
      xaxis: { title: { text: 'LAP #', font: { size: 9 } }, gridcolor: C.line, zeroline: false },
      yaxis: { range: [hi, lo], tickvals: ticks, ticktext: ticks.map(t => fmt(t * 1000).slice(0, -4)), gridcolor: C.line, zeroline: false },
    }, { displayModeBar: false, responsive: true });
  }
  return () => Plotly.purge(el);
}

/* ---------- page: session ---------- */
async function sessionPage(view, [id]) {
  const s = await api(`/session/${+id}`);
  const valid = s.laps.filter(l => l.valid), maxStd = Math.max(...s.corners.map(c => c.std), 0.001);
  const order = [...s.corners].sort((a, b) => b.std - a.std);
  view.innerHTML = `
  <section>
    <div class="eyebrow">Session / <b>${esc(s.car_name)} · ${esc(s.track_name)}</b> · ${new Date(s.start * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}</div>
    <h1 class="mega split" style="margin-top:20px">Lap by<br><em>lap</em></h1>
    <div class="stats">${stat('Best', fmt(s.best))}${stat('Average', fmt(s.avg))}${stat('Spread', s.spread == null ? '—' : '± ' + (s.spread / 1000).toFixed(2) + ' s')}${stat('Clean laps', `${s.valid}/${s.n}`)}</div>
  </section>
  <section>
    <h2 class="big split-in">Least<br><em>consistent</em></h2>
    <div class="vary">${order.map(c => `<div class="vrow" data-reveal><span class="wide">${esc(c.name)}</span>
      <div class="vbar"><i style="width:${(c.std / maxStd) * 100}%"></i></div><span class="num">± ${c.std.toFixed(3)} s</span>
      <span class="mono">${c.best.toFixed(2)} → ${c.worst.toFixed(2)}</span></div>`).join('')}</div>
  </section>
  <section>
    <div class="keys mono"><span><i style="background:${C.acc}"></i>Best lap</span><span><i style="background:rgba(238,234,246,.4)"></i>Other laps</span></div>
    <div id="sspeed" data-reveal></div>
    <div class="board heat" data-reveal style="margin-top:40px"><table>
      <tr><th>Lap</th><th>Time</th>${s.corners.map(c => `<th>${esc(c.name)}</th>`).join('')}</tr>
      ${s.laps.map((l, i) => `<tr data-go="/compare/${l.id}" data-hover data-label="Compare" class="${l.valid ? '' : 'cut'}"><td class="mono">${String(i + 1).padStart(2, '0')}</td>
        <td class="num">${fmt(l.lap_ms)}${l.valid ? '' : ' <span class="mono">cut</span>'}</td>
        ${l.corner_times.map((t, k) => { const c = s.corners[k], f = c.worst > c.best ? (t - c.best) / (c.worst - c.best) : 0;
          return `<td class="num" style="background:${mix(C.gain, C.loss, Math.max(0, Math.min(1, f))).replace('rgb(', 'rgba(').replace(')', ',.18)')}">${t.toFixed(2)}</td>`; }).join('')}</tr>`).join('')}
    </table></div>
  </section>`;
  view.addEventListener('click', e => { const r = e.target.closest('tr[data-go]'); if (r) nav.to = r.dataset.go; });
  const el = $('#sspeed', view);
  Plotly.newPlot(el, s.laps.filter(l => l.valid).map(l => ({ x: s.d, y: l.speed, mode: 'lines', hovertemplate: `${fmt(l.lap_ms)} %{y:.0f} km/h<extra></extra>`,
    line: { width: l.id === s.best_id ? 2.2 : 1, color: l.id === s.best_id ? C.acc : 'rgba(238,234,246,.28)' } })), {
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { family: 'Sligoil', color: C.mute, size: 10 }, showlegend: false,
    margin: { l: 50, r: 10, t: 10, b: 30 }, hovermode: 'closest', dragmode: matchMedia('(pointer: coarse)').matches ? false : 'zoom',
    hoverlabel: { bgcolor: '#07060d', bordercolor: C.acc, font: { color: C.fg, family: 'Sligoil' } },
    xaxis: { ticksuffix: ' m', gridcolor: C.line, zeroline: false }, yaxis: { title: { text: 'KM/H', font: { size: 9 } }, gridcolor: C.line, zeroline: false },
    shapes: s.corners.map(c => ({ type: 'line', xref: 'x', yref: 'paper', x0: c.start, x1: c.start, y0: 0, y1: 1, line: { color: C.line, width: 1 } })),
  }, { displayModeBar: false, responsive: true });
  return () => Plotly.purge(el);
}

/* ---------- compare extras: share + setup notes ---------- */
async function shareLink(aTok, b) {
  const url = `${location.origin}/s/${aTok}/${b}`;
  try {
    if (navigator.share && matchMedia('(pointer: coarse)').matches) await navigator.share({ title: 'Ghostline', url });
    else { await navigator.clipboard.writeText(url); toast('Link copied'); }
  } catch { toast(url); }
}
function setupHTML(A) {
  const s = A.setup || {}, keys = ['setup', 'tyres', 'fuel', 'conditions', 'notes'];
  const chips = keys.filter(k => s[k]).map(k => `<span class="chip">${k}: ${esc(s[k])}</span>`).join('');
  return `<div class="setup">${chips}${A.source === 'player' && A.id ? `<button class="chip admin-only" id="editsetup" data-hover>${chips ? 'Edit setup' : '+ Add setup notes'}</button>` : ''}</div>
    <form class="form setupform" id="setupform" hidden>${keys.map(k => `<input name="${k}" maxlength="80" placeholder="${k[0].toUpperCase() + k.slice(1)}" value="${esc(s[k] || '')}">`).join('')}
    <button class="btn" type="submit" data-hover><span>Save</span></button></form>`;
}
function bindSetup(view, A) {
  const b = $('#editsetup', view), f = $('#setupform', view);
  if (!b || !f) return;
  b.onclick = () => { f.hidden = !f.hidden; };
  f.onsubmit = async e => {
    e.preventDefault();
    try { await api(`/laps/${A.id}/note`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(new FormData(f))) }); toast('Setup saved'); route(); }
    catch (err) { toast(err.message); }
  };
}

/* ---------- page: live (built for a second monitor; stacks on small screens) ---------- */
const fmtS = ms => ms == null ? '—' : (ms / 1000).toFixed(3);
const fmtLeft = ms => { if (ms == null) return '—'; const s = Math.max(0, ms / 1000 | 0); return `${s / 60 | 0}:${String(s % 60).padStart(2, '0')}`; };
const tyreCol = t => t == null ? C.mute : t < 65 ? C.acc : t > 108 ? C.loss : C.gain;
async function livePage(view) {
  const corners = ['FL', 'FR', 'RL', 'RR'];
  view.innerHTML = `<section class="lv">
    <div class="lv-top" id="ltop"></div>
    <div class="rpm" id="rpm">${'<i></i>'.repeat(18)}</div>
    <div class="lv-grid">
      <div class="lv-a">
        <div class="mono">Current lap</div>
        <div class="clock" id="clock">—</div>
        <div class="trio">
          <div><small>Predicted</small><b id="pred">—</b></div><div><small>Last</small><b id="last">—</b></div>
          <div><small>My PB</small><b id="pb">—</b></div><div><small>Ghost</small><b id="gh" style="color:${C.acc}">—</b></div>
        </div>
        <div class="dlabel mono">Gap to my PB</div><div class="dbar"><div class="fill" id="f-pb"></div><div class="mid"></div><span id="d-pb">—</span></div>
        <div class="dlabel mono">Gap to ghost</div><div class="dbar"><div class="fill" id="f-gh"></div><div class="mid"></div><span id="d-gh">—</span></div>
        <div class="sectors" id="sect"></div>
        <div class="cflash" id="cflash"><span class="mono">Last corner</span><b id="cf-name">—</b><span id="cf-pb"></span><span id="cf-gh"></span></div>
      </div>
      <div class="lv-b"><svg id="lmap" viewBox="0 0 1000 1000" role="img" aria-label="Live track map with every car"></svg><div class="legend"><span><i style="background:${C.fg}"></i>me</span><span><i style="background:${C.acc}"></i>ghost</span><span><i style="background:${C.mute}"></i>others</span></div></div>
      <div class="lv-c"><div class="mono" id="stitle">Standings</div><div class="board stand"><table id="stand"></table></div></div>
    </div>
    <div class="lv-bot">
      <div class="blk"><small>Speed</small><b id="spd" class="big-n">0</b><small>Gear</small><b id="gear" class="big-n">N</b>
        <div class="pedals"><div class="pedal"><div id="pthr" style="background:${C.gain}"></div></div><div class="pedal"><div id="pbrk" style="background:${C.loss}"></div></div></div></div>
      <div class="blk"><small>Tyres · core °C / psi / wear</small><div class="tyres">${corners.map((c, i) => `<div class="ty" id="ty${i}"><small>${c}</small><b>—</b><span>—</span></div>`).join('')}</div></div>
      <div class="blk"><small>Brakes °C</small><div class="tyres">${corners.map((c, i) => `<div class="ty" id="br${i}"><small>${c}</small><b>—</b></div>`).join('')}</div></div>
      <div class="blk"><small>Fuel</small><b id="fuel" class="big-n">—</b><span id="fuelx" class="mono">—</span></div>
      <div class="blk"><small>Car</small><div class="kv" id="car"></div></div>
      <div class="blk admin-only"><small>Recorder</small><button class="btn" id="rtoggle" data-hover><span></span></button><ol class="mini" id="lrecent"></ol></div>
    </div>
  </section>`;
  const el = id => $('#' + id, view);
  const segs = $$('#rpm i', view);
  let mapRef, P = null, n = 0, cfAt = 0, standKey = '', topKey = '', recentKey = '';
  const bar = (fill, lab, d) => {
    const w = d == null ? 0 : Math.min(Math.abs(d), 2) * 25;
    el(lab).textContent = d == null ? '—' : sgn(d);
    el(lab).className = d > 0 ? 'loss' : d < 0 ? 'gain' : '';
    Object.assign(el(fill).style, { width: `${w}%`, left: d > 0 ? '50%' : `${50 - w}%`, background: d > 0 ? C.loss : C.gain });
  };
  const upd = s => {
    // top status strip
    const tags = [
      [s.connected ? s.session || 'Session' : (s.enabled ? 'Waiting for AC' : 'Recorder off'), ''],
      s.position ? [`P${s.position}${s.num_cars ? ' / ' + s.num_cars : ''}`, 'hi'] : null,
      s.laps_total ? [`Lap ${Math.min(s.laps_done + 1, s.laps_total)} / ${s.laps_total}`, ''] : s.connected ? [`Lap ${s.laps_done + 1}`, ''] : null,
      s.time_left ? [`${fmtLeft(s.time_left)} left`, ''] : null,
      s.flag ? [`${s.flag} flag`, `flag-${s.flag.toLowerCase()}`] : null,
      s.penalty ? [`Penalty ${s.penalty}s`, 'bad'] : null,
      s.recording ? (s.valid ? ['Lap valid', 'good'] : ['Lap invalid', 'bad']) : null,
      s.in_pit ? [s.limiter ? 'Pit lane · limiter' : 'Pit lane', 'warn'] : null,
      s.car_name ? [`${s.car_name} · ${s.track_name || s.track}`, 'dim'] : null,
      s.connected && s.supported === false ? ['Mod content: not recorded', 'warn'] : null,
    ].filter(Boolean);
    const tk = JSON.stringify(tags);
    if (tk !== topKey) { topKey = tk; el('ltop').innerHTML = tags.map(([t, c]) => `<span class="tag2 ${c}">${esc(t)}</span>`).join(''); }
    // rpm lights
    const r = s.max_rpm && s.rpm ? s.rpm / s.max_rpm : 0, lit = Math.round(r * 1.12 * segs.length - segs.length * 0.12);
    segs.forEach((g, i) => { g.className = i < lit ? (i < 10 ? 'g' : i < 15 ? 'a' : 'r') : ''; });
    el('rpm').classList.toggle('flash', r > 0.97);
    // timing
    el('clock').textContent = s.recording ? fmt(s.lap_ms) : s.connected ? (s.in_pit ? 'IN PITS' : 'OUT LAP') : 'NO SIGNAL';
    el('clock').classList.toggle('bad', s.recording && !s.valid);
    el('pred').textContent = fmt(s.predicted_ms); el('last').textContent = fmt(s.last_ms); el('pb').textContent = fmt(s.pb_ms); el('gh').textContent = fmt(s.ghost_ms);
    bar('f-pb', 'd-pb', s.delta_pb); bar('f-gh', 'd-gh', s.delta_ghost);
    const best = s.best_sectors || [], cur = s.sectors || [], lastS = s.last_sectors || [];
    const nS = Math.max(3, best.length);
    el('sect').innerHTML = Array.from({ length: nS }, (_, k) => {
      const v = cur[k], pv = lastS[k], b = best[k];
      const cls = v == null ? '' : v <= b ? 'pb' : v - b < 150 ? 'ok' : 'slow';
      return `<div class="sec ${cls}"><small>S${k + 1}</small><b>${v == null ? '—' : fmtS(v)}</b><span class="mono">last ${fmtS(pv)} · best ${fmtS(b)}</span></div>`;
    }).join('');
    const lc = s.last_corner;
    if (lc && lc.at !== cfAt) {
      cfAt = lc.at;
      el('cf-name').textContent = lc.name;
      el('cf-pb').innerHTML = lc.vs_pb == null ? '' : `<b class="${lc.vs_pb > 0 ? 'loss' : 'gain'}">${sgn(lc.vs_pb)}</b> vs PB`;
      el('cf-gh').innerHTML = lc.vs_ghost == null ? '' : `<b class="${lc.vs_ghost > 0 ? 'loss' : 'gain'}">${sgn(lc.vs_ghost)}</b> vs ghost`;
      gsap.fromTo(el('cflash'), { backgroundColor: lc.vs_pb > 0 ? 'rgba(255,79,129,.35)' : 'rgba(66,245,200,.30)' }, { backgroundColor: 'rgba(0,0,0,0)', duration: 3, ease: 'power2.out' });
    }
    // car
    el('spd').textContent = s.speed ?? 0;
    el('gear').textContent = s.gear == null ? '—' : s.gear < 0 ? 'R' : s.gear === 0 ? 'N' : s.gear;
    el('pthr').style.height = `${(s.throttle || 0) * 100}%`; el('pbrk').style.height = `${(s.brake || 0) * 100}%`;
    corners.forEach((_, i) => {
      const t = s.tyre_core?.[i], ty = el('ty' + i);
      ty.querySelector('b').textContent = t == null ? '—' : Math.round(t); ty.querySelector('b').style.color = tyreCol(t);
      ty.querySelector('span').textContent = s.tyre_press ? `${s.tyre_press[i].toFixed(1)} · ${s.tyre_wear ? s.tyre_wear[i].toFixed(1) + '%' : '—'}` : '—';
      el('br' + i).querySelector('b').textContent = s.brake_temp ? Math.round(s.brake_temp[i]) : '—';
    });
    el('fuel').textContent = s.fuel == null ? '—' : `${s.fuel.toFixed(1)} L`;
    el('fuelx').textContent = s.fuel_per_lap ? `${s.fuel_per_lap} L/lap · ${s.fuel_laps} laps${s.laps_total ? ' · ' + Math.max(0, s.laps_total - s.laps_done) + ' to go' : ''}` : 'per-lap use after 1 full lap';
    const kv = [['Bias', s.bias == null ? '—' : `${(s.bias * 100).toFixed(1)}%`], ['TC', s.tc ? 'active' : '—'], ['ABS', s.abs ? 'active' : '—'],
      ['Air / road', s.air == null ? '—' : `${s.air}° / ${s.road}°`], ['Grip', s.grip == null ? '—' : `${(s.grip * 100).toFixed(1)}%`], ['Damage', s.damage ? s.damage : 'none']];
    el('car').innerHTML = kv.map(([k, v]) => `<span>${k}</span><b>${esc(v)}</b>`).join('');
    // standings
    const st = s.standings;
    const sk = JSON.stringify(st?.map(c => [c.pos, c.name, c.gap, c.last, c.best, c.pit]));
    if (sk !== standKey) {
      standKey = sk;
      el('stitle').textContent = st ? (s.session === 'Race' ? 'Race order · gap to me' : 'Timing · best laps') : 'Standings need the RaceLogger in-game app';
      el('stand').innerHTML = st ? `<tr><th>P</th><th>Driver</th><th>Gap</th><th>Last</th><th>Best</th></tr>` + st.map(c => `<tr class="${c.me ? 'me' : ''}">
        <td class="num">${c.pos}</td><td>${esc(c.me ? 'You' : c.name)}${c.pit ? ' <span class="mono">pit</span>' : ''}</td>
        <td class="num ${c.gap > 0 ? 'gain' : c.gap < 0 ? 'loss' : ''}">${c.me ? '—' : c.gap == null ? '' : sgn(c.gap, s.session === 'Race' ? 1 : 3)}</td>
        <td class="num">${fmt(c.last)}</td><td class="num">${fmt(c.best)}</td></tr>`).join('') : '';
    }
    // map: me, ghost, everyone else
    if (s.ref_id && s.ref_id !== mapRef) {
      mapRef = s.ref_id;
      getMap(s.ref_id).then(m => {
        if (!m) return;
        const t = trackPath(m.x, m.z, 1000, 50); P = t.P; n = m.x.length;
        el('lmap').innerHTML = `<path d="${t.d}Z" fill="none" stroke="#1e1b27" stroke-width="22" stroke-linejoin="round"/><path d="${t.d}Z" fill="none" stroke="rgba(239,236,244,.25)" stroke-width="2"/><g id="others"></g>
          <circle id="gdot" r="14" fill="${C.acc}" opacity="0"/><circle id="ldot" r="16" fill="${C.fg}" stroke="#0b0a0f" stroke-width="4"/>`;
      });
    }
    if (P) {
      const at = f => P(Math.min(n - 1, Math.max(0, Math.floor(f * (n - 1)))));
      const put = (id, f) => { const d = $('#' + id, view); if (!d) return; if (f == null) return d.setAttribute('opacity', 0); const [x, y] = at(f); d.setAttribute('cx', x); d.setAttribute('cy', y); d.setAttribute('opacity', 1); };
      put('ldot', s.pos); put('gdot', s.ghost_pos);
      const o = $('#others', view);
      if (o && st) o.innerHTML = st.filter(c => !c.me).map(c => { const [x, y] = at(c.spline); return `<g><circle cx="${x}" cy="${y}" r="9" fill="${C.mute}"/><text x="${x + 12}" y="${y - 10}" fill="${C.mute}" font-family="Sligoil" font-size="22">${c.pos}</text></g>`; }).join('');
    }
    // recorder
    el('rtoggle').firstChild.textContent = s.enabled ? 'Pause recorder' : 'Start recorder';
    const rk = JSON.stringify(s.recent || []);
    if (rk !== recentKey) { recentKey = rk; el('lrecent').innerHTML = (s.recent || []).map(l => `<li><a href="/compare/${l.id}">${fmt(l.lap_ms)}</a>${l.valid ? '' : ' <span class="mono">cut</span>'}</li>`).join(''); }
  };
  bus.add(upd); upd(live);
  el('rtoggle').onclick = () => post('/recorder', { on: !live.enabled });
  return () => bus.delete(upd);
}

/* ---------- page: references ---------- */
async function refs(view) {
  const [st, laps] = await Promise.all([api('/state'), api('/laps')]);
  const a = st.app || {}, rl = laps.filter(l => l.source !== 'player'), mine = st.latest_best;
  const appState = !a.ac_path ? '<span class="warn">Assetto Corsa not found</span>' : a.active ? '<span class="ok">Installed and active</span>' : a.installed ? '<span class="warn">Installed, not active</span>' : '<span class="warn">Not installed</span>';
  view.innerHTML = `<section>
    <div class="eyebrow">References / <b>${rl.length} laps</b></div>
    <h1 class="mega split">Chase<br><em>faster</em></h1>
    <div class="panels">
      <div class="panel" data-reveal><span class="mono">01</span><h3 class="wide">Online<br>drivers</h3>
        <p>The RaceLogger in-game app records every other car on the server: speed, line and gear. Their laps show up here by themselves. Pedals are estimated from how hard they slow down and speed up.</p>
        <div class="mono admin-only">${appState}</div><code class="admin-only">${esc(a.logs)}</code>
        <p>Not running online? Content Manager → Settings → Assetto Corsa → Apps → tick RaceLogger. Some servers block custom apps.</p>
        <div class="admin-only"><button class="btn" id="inst" data-hover><span>${a.installed ? 'Reinstall' : 'Install'} app</span></button></div></div>
      <div class="panel admin-only" data-reveal><span class="mono">02</span><h3 class="wide">Real<br>world</h3>
        <p>Pull a real F1 lap from FastF1 open data. It's a different class, so it's compared by shape: braking zones, apex speed vs top speed, throttle pick-up.</p>
        <form class="form" id="f1"><input name="year" value="2024" placeholder="Year"><input name="gp" value="Monza" placeholder="Grand Prix"><input name="session" value="Q" placeholder="Session"><input name="driver" placeholder="Driver code (blank = pole)"></form>
        <div><button class="btn" id="f1go" data-hover><span>Import lap</span></button></div></div>
      <div class="panel" data-reveal><span class="mono">03</span><h3 class="wide">AI &amp;<br>files</h3>
        <p>AI baseline: run an offline race against 100% AI with the app on and their laps are saved as AI references.</p>
        <p class="admin-only">Or drop CSVs (columns t, pos, speed + optional x, z, throttle, brake, gear, with <code># car= / # track= / # driver=</code> header lines) into:</p><code class="admin-only">${esc(a.inbox)}</code></div>
    </div>
    <h2 class="big split-in">Reference<br><em>laps</em></h2>
    <ol class="rows" id="rrows" style="margin-top:40px">${rl.map((l, i) => rowHTML(l, i, false, mine ? `/compare/${mine}/${l.id}` : '')).join('') || '<li class="mono" style="padding:20px 0">None yet.</li>'}</ol>
  </section>`;
  $('#inst', view).onclick = async () => { try { await post('/install-app', {}); toast('App installed'); route(); } catch (e) { toast(e.message); } };
  $('#f1go', view).onclick = async e => {
    const btn = e.currentTarget, f = Object.fromEntries(new FormData($('#f1', view)));
    btn.firstElementChild.innerHTML = '<span class="spin">/</span> Downloading telemetry';
    try { const r = await post('/import/f1', { ...f, year: +f.year }); toast(r.duplicate ? 'Already imported' : 'Lap imported'); route(); }
    catch (err) { toast(err.message); btn.firstElementChild.textContent = 'Import lap'; }
  };
  return rowEvents($('#rrows', view), view);
}
