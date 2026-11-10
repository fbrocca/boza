/* Neighborhood pages: a dashboard per neighborhood (what's been filed, what's coming up,
 * what was decided) and an index of all neighborhoods. Static pages under n/<slug>/ set
 * window.HOOD; hood.html?n=<slug> works too. Counts, not just rates: most neighborhoods
 * have few cases, so every rate shows its sample size and the town-wide figure.
 */
(function () {
  'use strict';
  const { esc, track, meetingActions } = window.MPShared;
  const $ = (id) => document.getElementById(id);
  const slug = window.HOOD || new URLSearchParams(location.search).get('n');
  const fmtDate = (iso) => new Date(iso + 'T12:00:00').toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  const fmtDay = (iso) => new Date(iso + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
  const BOARD = { boza: 'Zoning Appeals', planning: 'Rezoning & planning', design: 'Design review' };
  const APPROVED = /^(Approved|Approved with conditions|Adopted by Council|Approved by staff|Reversed)$/;
  const DENIED = /^(Denied|Denied by Council)$/;
  const outcome = (s) => (APPROVED.test(s) ? 'approved' : DENIED.test(s) ? 'denied' : 'other');
  const minor = (c) => c.kind === 'Staff approval';
  const pct = (k, n) => (n ? Math.round((100 * k) / n) : null);
  const small = (n) => (n < 8 ? ' <span class="small-n" title="Few cases: treat as anecdotal">small sample</span>' : '');
  /* The three measures that mean something per board, with the cases they count. */
  const MEASURES = [
    { key: 'v', label: 'Variances approved', test: (c) => c.board === 'boza' && c.kind === 'Variance', ok: (s) => APPROVED.test(s), dec: (s) => APPROVED.test(s) || DENIED.test(s) },
    { key: 'z', label: 'Rezonings adopted', test: (c) => c.board === 'planning' && /Rezoning|Annexation|PD/.test(c.kind), ok: (s) => s === 'Adopted by Council', dec: (s) => /by Council$/.test(s) && s !== 'Passed first reading' },
    { key: 'd', label: 'Design reviews approved', test: (c) => c.board === 'design' && !minor(c), ok: (s) => APPROVED.test(s), dec: (s) => APPROVED.test(s) || DENIED.test(s) },
  ];
  function measure(rows, m) {
    const d = rows.filter((x) => m.test(x.c) && m.dec(x.c.status));
    return { k: d.filter((x) => m.ok(x.c.status)).length, n: d.length };
  }

  Promise.all([
    fetch('data/properties.json').then((r) => r.json()),
    fetch('data/neighborhoods.json').then((r) => r.json()),
    fetch('data/upcoming.json').then((r) => (r.ok ? r.json() : { meetings: [] })).catch(() => ({ meetings: [] })),
    slug ? fetch('data/neighborhood-shapes.json').then((r) => r.json()).catch(() => ({})) : Promise.resolve({}),
  ]).then(([{ properties }, nb, up, shapes]) => {
    const rows = [];
    for (const p of properties) for (const c of p.cases) rows.push({ p, c, hood: nb.assign[p.id] });
    const town = Object.fromEntries(MEASURES.map((m) => [m.key, measure(rows, m)]));
    const today = new Date().toISOString().slice(0, 10);
    const meetings = (up.meetings || []).filter((m) => m.date >= today);
    if (!slug) return renderIndex(nb, rows, town);
    const h = nb.hoods.find((x) => x.slug === slug);
    if (!h) { $('hood').innerHTML = '<div class="card block"><h1>Neighborhood not found</h1><p><a href="n/">See all neighborhoods</a>.</p></div>'; return; }
    renderHood(h, rows.filter((x) => x.hood === slug), town, meetings, shapes[slug] || [], nb);
  }).catch((e) => {
    $('hood').innerHTML = `<div class="card block"><h1>Could not load the data</h1><p>${esc(e.message)}</p></div>`;
  });

  // ---------- one neighborhood ----------
  function inside(lng, lat, rings) {
    let hit = false;
    for (const ring of rings) for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [x0, y0] = ring[i], [x1, y1] = ring[j];
      if ((y0 > lat) !== (y1 > lat) && lng < ((x1 - x0) * (lat - y0)) / (y1 - y0) + x0) hit = !hit;
    }
    return hit;
  }

  function renderHood(h, rows, town, meetings, rings, nb) {
    document.title = `${h.name}: zoning cases · Mount Pleasant`;
    const main = rows.filter((x) => !minor(x.c));
    const nMinor = rows.length - main.length;
    const first = main.reduce((a, x) => (x.c.first || x.c.date) < a ? (x.c.first || x.c.date) : a, '9999');
    // Coming up: items on posted agendas for properties here, or pinned inside the boundary
    const ids = new Set(rows.map((x) => x.p.id));
    const soon = meetings.map((m) => ({ m, items: m.items.filter((it) => (it.property && ids.has(it.property)) || (it.lat && rings.length && inside(it.lng, it.lat, rings))) }))
      .filter((s) => s.items.length);
    const url = location.href.split('#')[0];
    const tiles = MEASURES.map((m) => {
      const r = measure(rows, m), t = town[m.key];
      if (!r.n) return '';
      return `<div class="h-tile"><b>${pct(r.k, r.n)}%</b><span>${esc(m.label)}: ${r.k} of ${r.n}${small(r.n)}</span><span class="muted">Town-wide: ${pct(t.k, t.n)}%</span></div>`;
    }).join('');
    $('hood').innerHTML = `
      <section class="h-head">
        <p class="eyebrow">Neighborhood</p>
        <h1>${esc(h.name)}</h1>
        <p class="muted">${main.length} zoning ${main.length === 1 ? 'case' : 'cases'} on ${h.props} ${h.props === 1 ? 'property' : 'properties'} since ${first.slice(0, 4)}${nMinor ? `, plus ${nMinor} minor staff approvals` : ''}. Boundary: ${esc(h.source || '')}.</p>
        <div class="h-share">
          <button class="btn btn-primary btn-sm" type="button" id="shareBtn">Share this page</button>
          <a class="btn btn-outline btn-sm" href="https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(url)}" target="_blank" rel="noopener" data-track="hood/share-facebook">Facebook</a>
          <a class="btn btn-outline btn-sm" href="mailto:?subject=${encodeURIComponent(`Zoning cases in ${h.name}`)}&body=${encodeURIComponent(url)}" data-track="hood/share-email">Email</a>
          <span class="muted small" id="shareMsg" aria-live="polite"></span>
        </div>
      </section>

      ${soon.length ? `<section class="card block h-soon">
        <h2><span class="up-live" aria-hidden="true"></span>Coming up here</h2>
        ${soon.map(({ m, items }) => `<div class="up-meet">
          <div class="up-when"><b>${esc(fmtDay(m.date))}${m.time ? ', ' + esc(m.time) : ''}</b><span class="muted">${esc(m.label)}</span></div>
          <ul class="h-soon-items">${items.map((it) => `<li><span class="up-kind">${esc(it.kind || 'Item')}</span> <b>${esc(it.title)}</b>${it.request ? `<br><span class="muted small">${esc(it.request)}</span>` : ''}</li>`).join('')}</ul>
          ${meetingActions(m, items)}
        </div>`).join('')}
      </section>` : ''}

      ${tiles ? `<section class="h-tiles">${tiles}</section>` : ''}

      <section class="card block">
        <h2>Cases per year</h2>
        <p class="muted small">By final outcome. Minor staff approvals (roof, windows, paint) are not counted.</p>
        ${yearChart(main)}
      </section>

      <div class="h-grid">
        <section class="card block">
          <h2>By type of case</h2>
          ${typeTable(main)}
        </section>
        <section class="card block h-mapcard">
          <h2>Where</h2>
          <div id="hmap" class="h-map"></div>
        </section>
      </div>

      <section class="card block">
        <h2>Recent decisions</h2>
        ${recent(main)}
        <p class="report-row">Something wrong on this page? <button type="button" class="linklike" data-report="hood-${esc(h.slug)}" data-report-label="Neighborhood: ${esc(h.name)}">Report an error</button></p>
      </section>
      <p class="muted small">Other neighborhoods: ${nb.hoods.filter((x) => x.page && x.slug !== h.slug).slice(0, 12).map((x) => `<a href="n/${esc(x.slug)}/">${esc(x.name)}</a>`).join(' · ')} · <a href="n/">all</a></p>`;
    $('shareBtn').addEventListener('click', async () => {
      track('hood/share', h.name);
      if (navigator.share) { try { await navigator.share({ title: `Zoning cases in ${h.name}`, url }); return; } catch (e) { /* cancelled */ } }
      try { await navigator.clipboard.writeText(url); $('shareMsg').textContent = 'Link copied'; } catch (e) { $('shareMsg').textContent = url; }
    });
    drawMap(main, rings);
    track('hood/view', h.name);
  }

  function yearChart(rows) {
    const y0 = 2017, y1 = new Date().getFullYear();
    const years = [];
    for (let y = y0; y <= y1; y++) {
      const r = rows.filter((x) => +x.c.date.slice(0, 4) === y);
      years.push({ y, approved: r.filter((x) => outcome(x.c.status) === 'approved').length, denied: r.filter((x) => outcome(x.c.status) === 'denied').length, other: r.filter((x) => outcome(x.c.status) === 'other').length });
    }
    const max = Math.max(1, ...years.map((v) => v.approved + v.denied + v.other));
    const W = 640, H = 200, L = 30, B = 170, T = 14;
    const bw = (W - L - 8) / years.length;
    const step = max <= 5 ? 1 : max <= 12 ? 2 : max <= 30 ? 5 : max <= 60 ? 10 : 25;
    let out = '';
    for (let g = 0; g <= max; g += step) {
      const y = B - ((B - T) * g) / max;
      out += `<line x1="${L}" x2="${W - 4}" y1="${y}" y2="${y}" class="grid"/><text x="${L - 6}" y="${y + 4}" class="ax" text-anchor="end">${g}</text>`;
    }
    years.forEach((v, i) => {
      const x = L + i * bw + bw * 0.2, w = bw * 0.6;
      let base = B;
      const segs = [['approved', v.approved], ['denied', v.denied], ['other', v.other]].filter(([, n]) => n);
      segs.forEach(([k, n], si) => {
        const hgt = ((B - T) * n) / max;
        const top = si === segs.length - 1;
        const y = base - hgt;
        const r = top ? Math.min(4, hgt, w / 2) : 0;
        const gap = si ? 2 : 0; // surface gap between stacked segments
        out += `<path class="seg ${k}" d="M${x},${base - gap} V${y + r} ${r ? `Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r}` : `H${x + w}`} V${base - gap} Z"><title>${v.y}: ${n} ${k === 'other' ? 'withdrawn, pending or other' : k}</title></path>`;
        base = y;
      });
      const tot = v.approved + v.denied + v.other;
      if (tot) out += `<text x="${x + w / 2}" y="${base - 5}" class="val" text-anchor="middle">${tot}</text>`;
      out += `<text x="${x + w / 2}" y="${B + 15}" class="ax" text-anchor="middle">'${String(v.y).slice(2)}</text>`;
    });
    const legend = [['approved', 'Approved / adopted'], ['denied', 'Denied'], ['other', 'Withdrawn, pending or other']]
      .map(([k, l]) => `<span><i class="sw ${k}"></i>${l}</span>`).join('');
    const table = years.filter((v) => v.approved + v.denied + v.other).map((v) => `<tr><td>${v.y}</td><td>${v.approved}</td><td>${v.denied}</td><td>${v.other}</td></tr>`).join('');
    return `<div class="h-legend">${legend}</div>
      <svg class="h-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Cases per year by outcome">${out}</svg>
      <details class="h-table"><summary>Show as table</summary><table><tr><th>Year</th><th>Approved</th><th>Denied</th><th>Other</th></tr>${table}</table></details>`;
  }

  function typeTable(rows) {
    const by = new Map();
    for (const x of rows) {
      const k = x.c.kind;
      const v = by.get(k) || { board: x.c.board, n: 0, approved: 0, denied: 0 };
      v.n++; v[outcome(x.c.status)] = (v[outcome(x.c.status)] || 0) + 1;
      by.set(k, v);
    }
    const list = [...by.entries()].sort((a, b) => b[1].n - a[1].n);
    if (!list.length) return '<p class="muted">No cases.</p>';
    return `<table class="h-types"><tr><th>Type</th><th class="n">Cases</th><th class="n">Approved</th><th class="n">Denied</th></tr>
      ${list.map(([k, v]) => `<tr><td>${esc(k)} <span class="muted small">· ${esc(BOARD[v.board])}</span></td><td class="n">${v.n}</td><td class="n">${v.approved || 0}</td><td class="n">${v.denied || 0}</td></tr>`).join('')}</table>`;
  }

  function recent(rows) {
    const list = [...rows].sort((a, b) => (b.c.date > a.c.date ? 1 : -1)).slice(0, 12);
    if (!list.length) return '<p class="muted">No cases.</p>';
    return `<ul class="h-recent">${list.map((x) => `<li>
        <a href="./#${encodeURIComponent(x.p.id)}" data-track="hood/open-property"><b>${esc(x.p.address)}</b></a>
        <span class="muted small">${esc(x.c.kind)} · ${esc(BOARD[x.c.board])}${x.c.case ? ' · ' + esc(x.c.case) : ''}</span>
        <span class="badge h-${outcome(x.c.status)}"><span class="dot"></span>${esc(x.c.status)}</span>
        <span class="muted small h-date">${fmtDate(x.c.date)}</span>
        ${x.c.request ? `<span class="small h-req">${esc(x.c.request)}</span>` : ''}
      </li>`).join('')}</ul>`;
  }

  function drawMap(rows, rings) {
    const el = $('hmap');
    if (!el || !window.L) return;
    const map = L.map(el, { scrollWheelZoom: false, attributionControl: true });
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap' }).addTo(map);
    const pts = [];
    if (rings.length) {
      const poly = L.polygon(rings.map((r) => [r.map(([x, y]) => [y, x])]), { color: '#2563eb', weight: 2, fillOpacity: 0.06 }).addTo(map);
      pts.push(...poly.getLatLngs().flat(2));
    }
    const seen = new Set();
    for (const x of rows) {
      if (!x.p.lat || seen.has(x.p.id)) continue;
      seen.add(x.p.id);
      const o = outcome(x.c.status);
      L.circleMarker([x.p.lat, x.p.lng], { radius: 6, weight: 2, color: '#fff', fillOpacity: 1, fillColor: o === 'approved' ? '#16a34a' : o === 'denied' ? '#dc2626' : '#71717a' })
        .bindPopup(`<b>${esc(x.p.address)}</b><br>${esc(x.c.kind)} · ${esc(x.c.status)}<br><a href="./#${encodeURIComponent(x.p.id)}">Case history</a>`).addTo(map);
      pts.push(L.latLng(x.p.lat, x.p.lng));
    }
    if (pts.length) map.fitBounds(L.latLngBounds(pts), { padding: [20, 20], maxZoom: 17 });
    else map.setView([32.8323, -79.8284], 12);
  }

  // ---------- index of neighborhoods ----------
  function renderIndex(nb, rows, town) {
    const list = nb.hoods.filter((h) => h.page);
    const other = nb.hoods.filter((h) => !h.page);
    const card = (h) => {
      const r = rows.filter((x) => x.hood === h.slug && !minor(x.c));
      const v = measure(r, MEASURES[0]);
      const last = r.reduce((a, x) => (x.c.date > a ? x.c.date : a), '');
      return `<li><a class="h-card" href="n/${esc(h.slug)}/" data-name="${esc(h.name.toLowerCase())}">
        <b>${esc(h.name)}</b>
        <span class="muted small">${r.length} cases · ${h.props} properties${last ? ' · latest ' + fmtDate(last) : ''}</span>
        ${v.n ? `<span class="small">Variances approved: ${v.k} of ${v.n}</span>` : ''}
      </a></li>`;
    };
    $('hood').innerHTML = `
      <section class="h-head">
        <p class="eyebrow">Mount Pleasant, SC</p>
        <h1>Zoning by neighborhood</h1>
        <p class="muted">What's been filed, what's coming up and what was decided since 2017, for ${list.length} neighborhoods. Town-wide: ${pct(town.v.k, town.v.n)}% of variances approved, ${pct(town.z.k, town.z.n)}% of rezonings adopted.</p>
        <input class="input" id="hq" type="search" placeholder="Find a neighborhood" autocomplete="off">
      </section>
      <ul class="h-index" id="hlist">${list.map(card).join('')}</ul>
      <p class="muted small">Smaller areas (fewer than 3 cases): ${other.filter((h) => h.slug !== 'other-areas').map((h) => esc(h.name)).join(', ')}. Cases outside any mapped neighborhood: ${(nb.hoods.find((h) => h.slug === 'other-areas') || { cases: 0 }).cases}.</p>`;
    $('hq').addEventListener('input', (e) => {
      const q = e.target.value.trim().toLowerCase();
      document.querySelectorAll('#hlist li').forEach((li) => { li.hidden = q && !li.firstElementChild.dataset.name.includes(q); });
    });
    track('hood/index', 'Neighborhood index');
  }
})();
