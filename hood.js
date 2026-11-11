/* Neighborhood pages: one page per neighborhood (what's coming up, how requests fared,
 * what development was approved, where, and the latest decisions) and an index with the
 * town-wide development pipeline. Static pages under n/<slug>/ set window.HOOD;
 * hood.html?n=<slug> works too. Rates always carry their sample size and the town figure.
 */
(function () {
  'use strict';
  const { esc, track, meetingActions } = window.MPShared;
  const $ = (id) => document.getElementById(id);
  const slug = window.HOOD || new URLSearchParams(location.search).get('n');
  const fmtDate = (iso) => new Date(iso + 'T12:00:00').toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  const fmtMonth = (iso) => new Date(iso + 'T12:00:00').toLocaleDateString('en-US', { year: 'numeric', month: 'short' });
  const fmtDay = (iso) => new Date(iso + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
  const BOARD = { boza: 'Zoning Appeals', planning: 'Planning', design: 'Design review' };
  const APPROVED = /^(Approved|Approved with conditions|Adopted by Council|Approved by staff|Reversed)$/;
  const DENIED = /^(Denied|Denied by Council)$/;
  const outcome = (s) => (APPROVED.test(s) ? 'approved' : DENIED.test(s) ? 'denied' : 'other');
  const minor = (c) => c.kind === 'Staff approval';
  const pct = (k, n) => (n ? Math.round((100 * k) / n) : null);
  const small = (n) => (n < 8 ? ' <span class="small-n" title="Fewer than 8 cases">few cases</span>' : '');
  const MEASURES = [
    { key: 'v', label: 'Variances approved', test: (c) => c.board === 'boza' && c.kind === 'Variance', ok: (s) => APPROVED.test(s), dec: (s) => APPROVED.test(s) || DENIED.test(s) },
    { key: 'z', label: 'Rezonings adopted', test: (c) => c.board === 'planning' && /Rezoning|Annexation|PD/.test(c.kind), ok: (s) => s === 'Adopted by Council', dec: (s) => /by Council$/.test(s) && s !== 'Passed first reading' },
    { key: 'd', label: 'Design reviews approved', test: (c) => c.board === 'design' && !minor(c), ok: (s) => APPROVED.test(s), dec: (s) => APPROVED.test(s) || DENIED.test(s) },
  ];
  function measure(rows, m) {
    const d = rows.filter((x) => m.test(x.c) && m.dec(x.c.status));
    return { k: d.filter((x) => m.ok(x.c.status)).length, n: d.length };
  }
  /* Development approvals: planning decisions that change what can be built. Counted, not
     summed into acres or units: parcel acreage overstates phased projects, and lot / unit
     counts are stated for only some cases (shown per case where they are). */
  const DEV = [
    { key: 'rezoning', label: 'Rezoning', test: (k) => k === 'Rezoning', color: '#2a78d6' },
    { key: 'annex', label: 'Annexation', test: (k) => /^Annexation/.test(k), color: '#eb6834' },
    { key: 'pd', label: 'PD amendment', test: (k) => /^PD/.test(k), color: '#1baf7a' },
    { key: 'sub', label: 'Subdivision', test: (k) => /Sketch plan|Subdivision plat/.test(k), color: '#eda100' },
  ];
  const devType = (c) => (c.board === 'planning' && /^(Approved|Approved with conditions|Adopted by Council)$/.test(c.status)
    ? DEV.find((d) => d.test(c.kind)) : null);

  const mapEl = (id) => {
    const map = L.map(id, { scrollWheelZoom: false, zoomControl: true, attributionControl: true });
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, className: 'base-quiet', attribution: '© OpenStreetMap' }).addTo(map);
    return map;
  };

  Promise.all([
    fetch('data/properties.json').then((r) => r.json()),
    fetch('data/neighborhoods.json').then((r) => r.json()),
    fetch('data/upcoming.json').then((r) => (r.ok ? r.json() : { meetings: [] })).catch(() => ({ meetings: [] })),
    slug ? fetch('data/neighborhood-shapes.json').then((r) => r.json()).catch(() => ({})) : Promise.resolve({}),
    slug ? fetch('data/faq.json').then((r) => (r.ok ? r.json() : null)).catch(() => null) : Promise.resolve(null),
  ]).then(([{ properties }, nb, up, shapes, faq]) => {
    const rows = [];
    for (const p of properties) for (const c of p.cases) rows.push({ p, c, hood: nb.assign[p.id] });
    const town = Object.fromEntries(MEASURES.map((m) => [m.key, measure(rows, m)]));
    const today = new Date().toISOString().slice(0, 10);
    const meetings = (up.meetings || []).filter((m) => m.date >= today);
    if (!slug) return renderIndex(nb, rows, town);
    const h = nb.hoods.find((x) => x.slug === slug);
    if (!h) { $('hood').innerHTML = '<section class="h-head"><h1>Not found</h1><p><a href="n/">All neighborhoods</a></p></section>'; return; }
    renderHood(h, rows.filter((x) => x.hood === slug), town, meetings, shapes[slug] || [], nb, faq && faq.hoods[slug]);
  }).catch((e) => {
    $('hood').innerHTML = `<section class="h-head"><h1>Couldn't load the data</h1><p class="muted">${esc(e.message)}</p></section>`;
  });

  function inside(lng, lat, rings) {
    let hit = false;
    for (const ring of rings) for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [x0, y0] = ring[i], [x1, y1] = ring[j];
      if ((y0 > lat) !== (y1 > lat) && lng < ((x1 - x0) * (lat - y0)) / (y1 - y0) + x0) hit = !hit;
    }
    return hit;
  }

  // ---------- one neighborhood ----------
  function renderHood(h, rows, town, meetings, rings, nb, raised) {
    document.title = `${h.name} · Mount Pleasant Zoning`;
    const main = rows.filter((x) => !minor(x.c));
    const first = main.reduce((a, x) => ((x.c.first || x.c.date) < a ? (x.c.first || x.c.date) : a), '9999');
    const ids = new Set(rows.map((x) => x.p.id));
    const soon = meetings.map((m) => ({ m, items: m.items.filter((it) => (it.property && ids.has(it.property)) || (it.lat && rings.length && inside(it.lng, it.lat, rings))) }))
      .filter((s) => s.items.length);
    const url = location.href.split('#')[0];
    const tiles = MEASURES.map((m) => {
      const r = measure(rows, m), t = town[m.key];
      if (!r.n) return '';
      return `<div class="h-tile"><span class="h-tile-label">${esc(m.label)}</span><b>${pct(r.k, r.n)}%</b>
        <span class="h-tile-sub">${r.k} of ${r.n}${small(r.n)} · Town ${pct(t.k, t.n)}%</span></div>`;
    }).join('');
    const dev = main.filter((x) => devType(x.c)).sort((a, b) => (b.c.date > a.c.date ? 1 : -1));
    $('hood').innerHTML = `
      <section class="h-head">
        <p class="eyebrow">Neighborhood</p>
        <h1>${esc(h.name)}</h1>
        <p class="h-sub">${main.length} zoning ${main.length === 1 ? 'case' : 'cases'} since ${first.slice(0, 4)}</p>
        <div class="h-share">
          <button class="btn btn-primary btn-sm" type="button" id="shareBtn">Share</button>
          <a class="btn btn-outline btn-sm" href="https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(url)}" target="_blank" rel="noopener" data-track="hood/share-facebook">Facebook</a>
          <span class="muted small" id="shareMsg" aria-live="polite"></span>
        </div>
      </section>

      ${soon.length ? `<section class="h-section h-soon">
        <h2><span class="up-live" aria-hidden="true"></span>Coming up</h2>
        ${soon.map(({ m, items }) => `<div class="up-meet">
          <div class="up-when"><b>${esc(fmtDay(m.date))}${m.time ? ', ' + esc(m.time) : ''}</b><span>${esc(m.label)}</span></div>
          <ul class="h-list">${items.map((it) => `<li><span class="h-li-main">${esc(it.title)}</span>${it.request ? `<span class="h-li-sub">${esc(it.request)}</span>` : ''}</li>`).join('')}</ul>
          ${meetingActions(m, items)}
        </div>`).join('')}
      </section>` : ''}

      ${tiles ? `<section class="h-tiles">${tiles}</section>` : ''}

      ${dev.length ? `<section class="h-section">
        <h2>Development approved</h2>
        <ul class="h-list">${dev.slice(0, 10).map((x) => {
          const t = devType(x.c);
          return `<li><a class="h-li-main" href="./#${encodeURIComponent(x.p.id)}">${esc(x.p.address)}</a>
            <span class="h-li-sub"><i class="sw" style="background:${t.color}"></i>${esc(t.label)}${x.c.units ? ` · ${x.c.units.n} ${esc(x.c.units.what)}` : ''} · ${fmtMonth(x.c.date)}${x.c.case ? ' · ' + esc(x.c.case) : ''}</span></li>`;
        }).join('')}</ul>
        ${dev.length > 10 ? `<p class="h-more muted small">${dev.length - 10} more on the map</p>` : ''}
      </section>` : ''}

      ${raised && raised.topics.length ? `<section class="h-section">
        <h2>What neighbors raise</h2>
        <ul class="h-list">${raised.topics.slice(0, 5).map((t) => `<li>
          <span class="h-li-main">${esc(t.label)} <span class="muted small">· ${t.hearings} ${t.hearings === 1 ? 'hearing' : 'hearings'}</span></span>
          <span class="h-li-sub">${t.examples.slice(0, 2).map((e) => esc(e.q)).join(' · ')}</span>
        </li>`).join('')}</ul>
        <p class="h-note">Concerns residents raised at hearings here, from the minutes. Names are not shown.</p>
      </section>` : ''}

      <section class="h-section">
        <h2>Cases per year</h2>
        ${yearChart(main)}
      </section>

      <section class="h-section">
        <h2>Where</h2>
        <div id="hmap" class="h-map"></div>
      </section>

      <section class="h-section">
        <h2>Latest decisions</h2>
        ${recent(main)}
      </section>

      <p class="h-foot">
        <button type="button" class="linklike" data-report="hood-${esc(h.slug)}" data-report-label="Neighborhood: ${esc(h.name)}">Report an error</button>
        <span>·</span><a href="n/">All neighborhoods</a>
      </p>`;
    $('shareBtn').addEventListener('click', async () => {
      track('hood/share', h.name);
      if (navigator.share) { try { await navigator.share({ title: `Zoning in ${h.name}`, url }); return; } catch (e) { /* cancelled */ } }
      try { await navigator.clipboard.writeText(url); $('shareMsg').textContent = 'Link copied'; } catch (e) { $('shareMsg').textContent = url; }
    });
    drawMap(main, rings);
    track('hood/view', h.name);
  }

  /* Stacked columns by year. keys: [{key,label,color}], value(row) -> key or null. */
  function stackChart(rows, keys, keyOf, label) {
    const y0 = 2017, y1 = new Date().getFullYear();
    const years = [];
    for (let y = y0; y <= y1; y++) {
      const r = rows.filter((x) => +x.c.date.slice(0, 4) === y);
      years.push({ y, v: keys.map((k) => r.filter((x) => keyOf(x) === k.key).length) });
    }
    const max = Math.max(1, ...years.map((v) => v.v.reduce((a, b) => a + b, 0)));
    const W = 640, H = 190, L = 28, B = 164, T = 16;
    const bw = (W - L - 4) / years.length;
    const step = [1, 2, 5, 10, 20, 25, 50, 100].find((s) => max / s <= 5) || 100;
    let out = '';
    for (let g = 0; g <= max; g += step) {
      const y = B - ((B - T) * g) / max;
      out += `<line x1="${L}" x2="${W}" y1="${y}" y2="${y}" class="grid"/><text x="${L - 8}" y="${y + 4}" class="ax" text-anchor="end">${g}</text>`;
    }
    years.forEach((v, i) => {
      const x = L + i * bw + bw * 0.24, w = bw * 0.52;
      let base = B;
      const segs = v.v.map((n, k) => [k, n]).filter(([, n]) => n);
      segs.forEach(([k, n], si) => {
        const hgt = ((B - T) * n) / max;
        const y = base - hgt + (si ? 2 : 0);
        const top = si === segs.length - 1;
        const r = top ? Math.min(4, hgt / 2, w / 2) : 0;
        out += `<path fill="${keys[k].color}" d="M${x},${base} V${y + r} ${r ? `Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r}` : `H${x + w}`} V${base} Z"><title>${v.y}: ${n} ${keys[k].label.toLowerCase()}</title></path>`;
        base = base - hgt;
      });
      const tot = v.v.reduce((a, b) => a + b, 0);
      if (tot) out += `<text x="${x + w / 2}" y="${base - 6}" class="val" text-anchor="middle">${tot}</text>`;
      out += `<text x="${x + w / 2}" y="${B + 16}" class="ax" text-anchor="middle">'${String(v.y).slice(2)}</text>`;
    });
    const legend = keys.map((k) => `<span><i class="sw" style="background:${k.color}"></i>${esc(k.label)}</span>`).join('');
    const table = years.filter((v) => v.v.some(Boolean)).map((v) => `<tr><td>${v.y}</td>${v.v.map((n) => `<td class="n">${n}</td>`).join('')}</tr>`).join('');
    return `<div class="h-legend">${legend}</div>
      <svg class="h-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">${out}</svg>
      <details class="h-table"><summary>Show as table</summary><table><tr><th>Year</th>${keys.map((k) => `<th class="n">${esc(k.label)}</th>`).join('')}</tr>${table}</table></details>`;
  }
  const OUTCOMES = [
    { key: 'approved', label: 'Approved', color: 'var(--approved)' },
    { key: 'denied', label: 'Denied', color: 'var(--denied)' },
    { key: 'other', label: 'Withdrawn or pending', color: '#c7c7cc' },
  ];
  const yearChart = (rows) => stackChart(rows, OUTCOMES, (x) => outcome(x.c.status), 'Cases per year by outcome');

  function recent(rows) {
    const list = [...rows].sort((a, b) => (b.c.date > a.c.date ? 1 : -1)).slice(0, 8);
    if (!list.length) return '<p class="muted">No cases.</p>';
    return `<ul class="h-list">${list.map((x) => `<li>
        <a class="h-li-main" href="./#${encodeURIComponent(x.p.id)}" data-track="hood/open-property">${esc(x.p.address)}</a>
        <span class="h-li-sub"><span class="h-st h-${outcome(x.c.status)}">${esc(x.c.status)}</span> · ${esc(x.c.kind)} · ${fmtDate(x.c.date)}</span>
      </li>`).join('')}</ul>`;
  }

  function drawMap(rows, rings) {
    if (!$('hmap') || !window.L) return;
    const map = mapEl('hmap');
    const pts = [];
    if (rings.length) {
      const poly = L.polygon(rings.map((r) => [r.map(([x, y]) => [y, x])]), { color: '#0071e3', weight: 2, fillOpacity: 0.05 }).addTo(map);
      pts.push(...poly.getLatLngs().flat(2));
    }
    const seen = new Set();
    for (const x of rows) {
      if (!x.p.lat || seen.has(x.p.id)) continue;
      seen.add(x.p.id);
      const o = outcome(x.c.status);
      L.circleMarker([x.p.lat, x.p.lng], { radius: 5, weight: 1.5, color: '#fff', fillOpacity: 1, fillColor: o === 'approved' ? '#248a3d' : o === 'denied' ? '#c9341c' : '#8e8e93' })
        .bindPopup(`<b>${esc(x.p.address)}</b><br>${esc(x.c.kind)} · ${esc(x.c.status)}<br><a href="./#${encodeURIComponent(x.p.id)}">Open</a>`).addTo(map);
      pts.push(L.latLng(x.p.lat, x.p.lng));
    }
    if (pts.length) map.fitBounds(L.latLngBounds(pts), { padding: [24, 24], maxZoom: 17 });
    else map.setView([32.8323, -79.8284], 12);
  }

  // ---------- index ----------
  function renderIndex(nb, rows, town) {
    const list = nb.hoods.filter((h) => h.page);
    const dev = rows.filter((x) => devType(x.c));
    const card = (h) => {
      const r = rows.filter((x) => x.hood === h.slug && !minor(x.c));
      const last = r.reduce((a, x) => (x.c.date > a ? x.c.date : a), '');
      return `<li><a class="h-card" href="n/${esc(h.slug)}/" data-name="${esc(h.name.toLowerCase())}">
        <b>${esc(h.name)}</b>
        <span>${r.length} cases${last ? ' · latest ' + fmtMonth(last) : ''}</span>
      </a></li>`;
    };
    $('hood').innerHTML = `
      <section class="h-head">
        <p class="eyebrow">Mount Pleasant</p>
        <h1>Neighborhoods</h1>
        <p class="h-sub">What's been filed, approved and coming up, in ${list.length} neighborhoods.</p>
      </section>
      <section class="h-tiles">
        ${MEASURES.slice(0, 2).map((m) => `<div class="h-tile"><span class="h-tile-label">${esc(m.label)}</span><b>${pct(town[m.key].k, town[m.key].n)}%</b><span class="h-tile-sub">${town[m.key].k} of ${town[m.key].n}, 2017–2026</span></div>`).join('')}
        <div class="h-tile"><span class="h-tile-label">Development approvals</span><b>${dev.length}</b><span class="h-tile-sub">Rezonings, annexations, PD amendments, subdivisions</span></div>
      </section>
      <section class="h-section">
        <h2>Development approved, by year</h2>
        ${stackChart(dev, DEV, (x) => devType(x.c).key, 'Development approvals per year by type')}
        <p class="h-note">Counts of approvals. Lots and units appear on each case where the minutes state them.</p>
      </section>
      <section class="h-section">
        <h2>Find a neighborhood</h2>
        <input class="input" id="hq" type="search" placeholder="Search" autocomplete="off">
        <ul class="h-index" id="hlist">${list.map(card).join('')}</ul>
      </section>`;
    $('hq').addEventListener('input', (e) => {
      const q = e.target.value.trim().toLowerCase();
      document.querySelectorAll('#hlist li').forEach((li) => { li.hidden = q && !li.firstElementChild.dataset.name.includes(q); });
    });
    track('hood/index', 'Neighborhood index');
  }
})();
