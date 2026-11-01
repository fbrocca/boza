/* Mount Pleasant Zoning Map.
 * Data: data/properties.json  one entry per parcel; each has cases (BOZA or
 *                              planning), each case a timeline of events
 *       data/minutes-text.json minutes text per event, fetched on demand
 * UI: shadcn/ui tokens and components (style.css), Airbnb-style list + map.
 */
(function () {
  'use strict';

  const CENTER = [32.8323, -79.8284];
  const GROUPS = [
    { key: 'approved', label: 'Approved / adopted', test: (s) => /^(Approved|Adopted by Council)$/.test(s) },
    { key: 'conditions', label: 'Approved with conditions', test: (s) => s === 'Approved with conditions' },
    { key: 'denied', label: 'Denied', test: (s) => /^(Denied|Denied by Council)$/.test(s) },
    { key: 'pending', label: 'Pending / recommendation only', test: (s) => /^(Recommended approval|Recommended denial|Passed first reading|Deferred|No recommendation)$/.test(s) },
    { key: 'withdrawn', label: 'Withdrawn', test: (s) => s === 'Withdrawn' },
    { key: 'other', label: 'Other / see minutes', test: () => true },
  ];
  const groupOf = (status) => GROUPS.find((g) => g.test(status));
  const tone = (key) => `--c:var(--${key});--cb:var(--${key}-bg)`;
  const statusTone = (s) => tone(groupOf(s).key);
  // Timeline events carry free-text decisions ("First reading: denied").
  const eventTone = (d) => tone(/denied/i.test(d) ? 'denied' : /conditions/i.test(d) ? 'conditions'
    : /approv|adopt/i.test(d) && !/recommend/i.test(d) ? 'approved'
    : /withdr/i.test(d) ? 'withdrawn' : /defer|recommend|pending/i.test(d) ? 'pending' : 'other');
  const BOARD = { boza: 'Zoning Appeals', planning: 'Rezoning & planning' };
  const SHORT = { 'Annexation and zoning': 'Annexation', 'PD / development agreement amendment': 'PD amendment', 'Subdivision plat': 'Plat', 'Special exception': 'Special exc.' };
  const STATUS_HELP = {
    'Recommended approval': 'The Planning Commission recommended approval. No Town Council decision was found in the minutes.',
    'Recommended denial': 'The Planning Commission recommended denial. No Town Council decision was found in the minutes.',
    'Passed first reading': 'Town Council approved first reading. No later reading was found in the minutes.',
  };
  const GEO_LABEL = {
    'parcel': 'Pin and outline from the county parcel record',
    'address point': 'Pin from the county address point',
    'address point (TMS in minutes did not match)': 'Pin from the county address point (the TMS in the minutes points elsewhere)',
    'street estimate': 'Approximate pin, estimated along the street',
    'street estimate (TMS in minutes did not match)': 'Approximate pin, estimated along the street',
    'manual': 'Pin placed by hand',
  };
  const ICON = {
    ext: '<svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"><path d="M7 17 17 7M8 7h9v9" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    doc: '<svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Zm0 0v5h5M9 13h6M9 17h6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    text: '<svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  };

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmtDate = (iso) => new Date(iso + 'T12:00:00').toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  const isMobile = () => matchMedia('(max-width: 760px)').matches;

  let props = [];
  const byId = new Map();
  const markers = new Map();
  let texts = null;
  let activeId = null;
  let shown = [];
  let board = '';

  // ---------- Lot thumbnails: satellite tiles + parcel outline, in one SVG ----------
  const TILE = 256;
  function project(lat, lng, z) {
    const n = TILE * 2 ** z;
    const s = Math.sin(lat * Math.PI / 180);
    return [(lng + 180) / 360 * n, (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n];
  }
  function lotSvg(p, W, H) {
    if (!p.lat) return '';
    let z = 18;
    let cx, cy;
    if (p.rings) {
      const pts = p.rings.flat();
      const xs19 = pts.map((q) => project(q[0], q[1], 19));
      const bw = Math.max(...xs19.map((q) => q[0])) - Math.min(...xs19.map((q) => q[0]));
      const bh = Math.max(...xs19.map((q) => q[1])) - Math.min(...xs19.map((q) => q[1]));
      const scale = Math.max(bw / (W * 0.62), bh / (H * 0.62), 1);
      z = Math.max(13, Math.min(18, 19 - Math.ceil(Math.log2(scale))));  // Esri imagery is complete to z18
      const px = pts.map((q) => project(q[0], q[1], z));
      cx = (Math.max(...px.map((q) => q[0])) + Math.min(...px.map((q) => q[0]))) / 2;
      cy = (Math.max(...px.map((q) => q[1])) + Math.min(...px.map((q) => q[1]))) / 2;
    } else {
      [cx, cy] = project(p.lat, p.lng, z);
    }
    const x0 = cx - W / 2, y0 = cy - H / 2;
    let imgs = '';
    for (let tx = Math.floor(x0 / TILE); tx <= Math.floor((x0 + W) / TILE); tx++) {
      for (let ty = Math.floor(y0 / TILE); ty <= Math.floor((y0 + H) / TILE); ty++) {
        imgs += `<image href="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${ty}/${tx}" x="${tx * TILE}" y="${ty * TILE}" width="${TILE}" height="${TILE}"/>`;
      }
    }
    const shape = p.rings
      ? p.rings.map((r) => `<polygon points="${r.map((q) => project(q[0], q[1], z).map((v) => v.toFixed(1)).join(',')).join(' ')}" fill="rgba(255,255,255,.16)" stroke="#fff" stroke-width="2.5" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>`).join('')
      : `<circle cx="${cx}" cy="${cy}" r="7" fill="#ef4444" stroke="#fff" stroke-width="2.5"/>`;
    return `<svg viewBox="${x0.toFixed(1)} ${y0.toFixed(1)} ${W} ${H}" preserveAspectRatio="xMidYMid slice" role="img" aria-label="Satellite view of ${esc(p.address)}">${imgs}${shape}</svg>`;
  }
  const thumbObserver = 'IntersectionObserver' in window ? new IntersectionObserver((entries) => {
    for (const en of entries) {
      if (!en.isIntersecting) continue;
      const el = en.target;
      thumbObserver.unobserve(el);
      const p = byId.get(el.dataset.thumb);
      if (p) el.insertAdjacentHTML('afterbegin', lotSvg(p, 330, 220));
    }
  }, { rootMargin: '400px 0px' }) : null;
  function thumbHtml(p, extra = '') {
    const ph = p.lat ? '' : '<div class="ph">No map location<br>in the record</div>';
    return `<div class="thumb" data-thumb="${esc(p.id)}">${ph}${extra}</div>`;
  }

  // ---------- Map ----------
  const map = L.map('map', { zoomControl: false }).setView(CENTER, 12);
  L.control.zoom({ position: 'topright' }).addTo(map);
  const streets = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  const satellite = L.layerGroup([
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 20, maxNativeZoom: 19, attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics',
    }),
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 20, maxNativeZoom: 19, opacity: 0.7,
    }),
  ]);
  L.control.layers({ 'Map': streets, 'Satellite': satellite }, null, { position: 'topright' }).addTo(map);
  const cluster = L.markerClusterGroup({
    showCoverageOnHover: false, maxClusterRadius: 45, spiderfyOnMaxZoom: true, disableClusteringAtZoom: 16,
    iconCreateFunction: (c) => {
      const n = c.getChildCount();
      const s = n < 10 ? 30 : n < 50 ? 36 : 44;
      return L.divIcon({ html: `<div>${n}</div>`, className: 'cluster', iconSize: [s, s] });
    },
  });
  map.addLayer(cluster);
  const outline = L.layerGroup().addTo(map);

  // ---------- Draw a boundary (Redfin-style freehand) ----------
  let area = null;         // [[lat, lng], ...] or null
  let areaLayer = null;
  let drawing = false;
  const areaCtl = L.control({ position: 'topleft' });
  areaCtl.onAdd = () => {
    const el = L.DomUtil.create('div', 'area-ctl');
    L.DomEvent.disableClickPropagation(el);
    L.DomEvent.disableScrollPropagation(el);
    return el;
  };
  areaCtl.addTo(map);
  const PENCIL = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  function renderAreaCtl() {
    const el = areaCtl.getContainer();
    if (drawing) {
      el.innerHTML = `<div class="draw-hint card">Drag to draw around an area</div>
        <button class="btn btn-outline btn-sm" type="button" data-area="cancel">Cancel</button>`;
    } else if (area) {
      el.innerHTML = `<button class="btn btn-primary btn-sm" type="button" data-area="remove">✕&nbsp;Remove boundary</button>
        <button class="btn btn-outline btn-sm" type="button" data-area="draw">${PENCIL}Redraw</button>`;
    } else {
      el.innerHTML = `<button class="btn btn-outline btn-sm" type="button" data-area="draw">${PENCIL}Draw</button>`;
    }
  }
  function insideArea(lat, lng, poly) {
    let hit = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [yi, xi] = poly[i], [yj, xj] = poly[j];
      if ((yi > lat) !== (yj > lat) && lng < (xj - xi) * (lat - yi) / (yj - yi) + xi) hit = !hit;
    }
    return hit;
  }
  function areaUrl() {
    const u = new URL(location.href);
    if (area) u.searchParams.set('area', area.map(([a, b]) => `${a.toFixed(5)},${b.toFixed(5)}`).join(';'));
    else u.searchParams.delete('area');
    history.replaceState(null, '', u.pathname + u.search + u.hash);
  }
  function setArea(pts, { fit = true } = {}) {
    if (areaLayer) map.removeLayer(areaLayer);
    area = pts;
    areaLayer = pts ? L.polygon(pts, { color: '#2563eb', weight: 2.5, fillColor: '#2563eb', fillOpacity: 0.08, dashArray: null, interactive: false }).addTo(map) : null;
    if (pts && fit) map.fitBounds(areaLayer.getBounds(), { padding: [40, 40] });
    renderAreaCtl();
    areaUrl();
    if (props.length) apply();
  }
  function startDrawing() {
    if (!$('detailView').hidden) closeDetail();
    map.closePopup();
    drawing = true;
    map.dragging.disable();
    map.doubleClickZoom.disable();
    map.boxZoom.disable();
    map.getContainer().classList.add('drawing');
    renderAreaCtl();
  }
  function stopDrawing() {
    drawing = false;
    map.dragging.enable();
    map.doubleClickZoom.enable();
    map.boxZoom.enable();
    map.getContainer().classList.remove('drawing');
    renderAreaCtl();
  }
  // Freehand stroke with pointer events (mouse, pen and touch).
  (function () {
    const box = map.getContainer();
    let pts = null, line = null, lastPx = null;
    box.addEventListener('pointerdown', (e) => {
      if (!drawing || e.target.closest('.leaflet-control')) return;
      e.preventDefault();
      box.setPointerCapture(e.pointerId);
      const ll = map.mouseEventToLatLng(e);
      pts = [ll];
      lastPx = [e.clientX, e.clientY];
      line = L.polyline(pts, { color: '#2563eb', weight: 3, interactive: false }).addTo(map);
    });
    box.addEventListener('pointermove', (e) => {
      if (!drawing || !pts) return;
      if (Math.hypot(e.clientX - lastPx[0], e.clientY - lastPx[1]) < 4) return;
      lastPx = [e.clientX, e.clientY];
      pts.push(map.mouseEventToLatLng(e));
      line.setLatLngs(pts);
    });
    const finish = () => {
      if (!drawing || !pts) return;
      map.removeLayer(line);
      const raw = pts;
      pts = null; line = null;
      stopDrawing();
      if (raw.length < 3) return;
      // Thin the stroke to at most ~80 vertices so the shareable URL stays short.
      const step = Math.max(1, Math.ceil(raw.length / 80));
      const thin = raw.filter((_, i) => i % step === 0).map((ll) => [ll.lat, ll.lng]);
      if (thin.length >= 3) setArea(thin, { fit: false });
    };
    box.addEventListener('pointerup', finish);
    box.addEventListener('pointercancel', finish);
  })();
  areaCtl.getContainer().addEventListener('click', (e) => {
    const b = e.target.closest('button[data-area]');
    if (!b) return;
    const a = b.dataset.area;
    if (a === 'draw') startDrawing();
    else if (a === 'cancel') stopDrawing();
    else if (a === 'remove') setArea(null);
  });
  renderAreaCtl();

  $('legend').innerHTML = '<summary>Legend</summary><div class="legend-body">' + GROUPS.map((g) =>
    `<div><span class="dot" style="${tone(g.key)}"></span>${esc(g.label)}</div>`).join('') +
    '<div class="legend-note">● zoning appeal &nbsp;◆ rezoning &amp; planning</div></div>';

  function pinIcon(p, cases, state) {
    const c = (cases || p.cases)[0];
    const label = c.case || SHORT[c.kind] || c.kind;
    const extra = p.cases.length > 1 ? ` +${p.cases.length - 1}` : '';
    return L.divIcon({
      className: `pill-marker ${c.board}${state ? ' ' + state : ''}`,
      html: `<span><span class="dot" style="${statusTone(c.status)}"></span>${esc(label)}${extra}</span>`,
      iconSize: [0, 0],
    });
  }
  function markState(id, cls, on) {
    const m = markers.get(id);
    if (!m) return;
    const el = m.getElement();
    if (el) {
      el.classList.toggle(cls, on);
    }
  }

  // ---------- Filtering ----------
  function filters() {
    return {
      q: $('q').value.trim().toLowerCase(), board,
      group: $('fDecision').value, kind: $('fKind').value, year: $('fYear').value, inView: $('fInView').checked,
    };
  }
  function caseMatches(c, f) {
    if (f.board && c.board !== f.board) return false;
    if (f.group && groupOf(c.status).key !== f.group) return false;
    if (f.kind && c.kind !== f.kind) return false;
    if (f.year && !c.events.some((e) => e.date.startsWith(f.year))) return false;
    return true;
  }
  function apply() {
    const f = filters();
    const terms = f.q.split(/\s+/).filter(Boolean);
    const bounds = map.getBounds();
    shown = [];
    for (const p of props) {
      const cs = p.cases.filter((c) => caseMatches(c, f));
      if (!cs.length) continue;
      if (terms.length && !terms.every((t) => p._search.includes(t))) continue;
      if (f.inView && !(p.lat && bounds.contains([p.lat, p.lng]))) continue;
      if (area && !(p.lat && insideArea(p.lat, p.lng, area))) continue;
      shown.push({ p, cases: cs });
    }
    cluster.clearLayers();
    cluster.addLayers(shown.filter((s) => s.p.lat).map((s) => {
      const m = markers.get(s.p.id);
      m.setIcon(pinIcon(s.p, s.cases, s.p.id === activeId ? 'active' : ''));
      return m;
    }));
    for (const id of ['fDecision', 'fKind', 'fYear']) $(id).classList.toggle('on', !!$(id).value);
    $('reset').hidden = !(f.group || f.kind || f.year || f.inView || f.board || f.q || area);
    renderList();
    const nc = shown.reduce((a, s) => a + s.cases.length, 0);
    $('count').textContent = `${shown.length.toLocaleString()} ${shown.length === 1 ? 'property' : 'properties'} · ${nc.toLocaleString()} ${nc === 1 ? 'case' : 'cases'}${area ? ' inside your boundary' : ''}`;
  }

  const LIMIT = 300;
  function renderList() {
    const el = $('results');
    if (!shown.length) {
      el.innerHTML = '<li class="empty">No cases match. Try clearing the search or a filter.</li>';
      return;
    }
    el.innerHTML = shown.slice(0, LIMIT).map(({ p, cases }) => {
      const c = cases[0];
      const n = p.cases.length;
      return `<li><button type="button" class="prop" data-id="${esc(p.id)}">
        ${thumbHtml(p, n > 1 ? `<span class="count">${n} cases</span>` : '')}
        <span class="prop-body">
          <span class="eyebrow"><span>${esc(c.kind)}</span><span>·</span><span>${esc(BOARD[c.board])}</span></span>
          <span class="prop-title">${esc(p.address)}</span>
          ${c.request ? `<span class="prop-req">${esc(c.request)}</span>` : ''}
          <span class="prop-foot">
            <span class="badge" style="${statusTone(c.status)}"><span class="dot"></span>${esc(c.status)}</span>
            <span class="prop-date">${c.case ? `<span class="muted">${esc(c.case)} · </span>` : ''}${fmtDate(c.date)}</span>
          </span>
        </span>
      </button></li>`;
    }).join('') + (shown.length > LIMIT ? `<li class="empty">Showing the ${LIMIT} most recent. Search, filter or zoom the map to narrow.</li>` : '');
    if (thumbObserver) el.querySelectorAll('[data-thumb]').forEach((t) => { if (byId.get(t.dataset.thumb)?.lat) thumbObserver.observe(t); });
  }

  // ---------- Detail ----------
  function setActive(id) {
    if (activeId) markState(activeId, 'active', false);
    activeId = id;
    if (id) markState(id, 'active', true);
    outline.clearLayers();
    const p = id && byId.get(id);
    if (p && p.rings) {
      L.polygon(p.rings, { color: '#09090b', weight: 2.5, fillColor: '#09090b', fillOpacity: 0.1, interactive: false }).addTo(outline);
    }
  }

  function docLinks(e) {
    if (!e.docs) return '';
    const n = {};
    return e.docs.map((d) => {
      const name = d.all ? `${d.t} (whole meeting)` : d.t;
      n[name] = (n[name] || 0) + 1;
      const label = n[name] > 1 ? `${name} ${n[name]}` : name;
      return `<a class="btn btn-outline btn-sm" href="${esc(d.u)}" target="_blank" rel="noopener" title="${esc(d.l)}">${ICON.doc}${esc(label)}</a>`;
    }).join('');
  }
  function eventLinks(e) {
    const pdf = e.pdf ? `${e.pdf}#page=${e.page}` : e.town ? `${e.town}#page=${e.page}` : null;
    return `${docLinks(e)}
      <button class="btn btn-secondary btn-sm" type="button" data-excerpt="${esc(e.id)}" aria-expanded="false">${ICON.text}<span>Minutes</span></button>
      ${pdf ? `<a class="btn btn-ghost btn-sm" href="${esc(pdf)}" target="_blank" rel="noopener">${ICON.ext}PDF p.${e.page}</a>` : ''}
      ${e.pdf && e.town ? `<a class="btn btn-ghost btn-sm" href="${esc(e.town)}" target="_blank" rel="noopener">${ICON.ext}Town's copy</a>` : ''}`;
  }
  function caseCard(c, term) {
    const help = STATUS_HELP[c.status];
    return `
      <article class="card case-card">
        <div class="case-top">
          <div>
            <div class="case-id">${c.case ? `<span class="mono">${esc(c.case)}</span> · ` : ''}${esc(c.kind)}</div>
            <div class="case-sub">${esc(BOARD[c.board])}</div>
          </div>
          <span class="badge" style="${statusTone(c.status)}"><span class="dot"></span>${esc(c.status)}</span>
        </div>
        ${c.request ? `<p class="request">${highlight(c.request, term)}</p>` : ''}
        ${help ? `<p class="note">${esc(help)}</p>` : ''}
        <ol class="timeline">
          ${c.events.map((e) => `
            <li style="${eventTone(e.decision)}">
              <div class="tl-head">
                <span class="tl-body">${esc(e.body)}${e.ord ? ` <span class="muted">· Ord. ${esc(e.ord)}</span>` : ''}</span>
                <span class="tl-date">${fmtDate(e.date)}</span>
              </div>
              <div class="tl-decision">${esc(e.decision)}${e.item ? ` <span class="muted">(${esc(e.item)})</span>` : ''}</div>
              ${e.note ? `<p class="note">${esc(e.note)}</p>` : ''}
              <div class="actions">${eventLinks(e)}</div>
              <div class="excerpt" id="ex-${esc(e.id)}" hidden></div>
            </li>`).join('')}
        </ol>
      </article>`;
  }

  function openProperty(id, { fly = true } = {}) {
    const p = byId.get(id);
    if (!p) return;
    map.closePopup();
    setActive(id);
    $('listView').hidden = true;
    $('detailView').hidden = false;
    document.body.classList.remove('show-map');
    syncMapToggle();
    const term = filters().q;
    const tms = [p.tms, ...(p.other_tms || [])].filter(Boolean);
    $('detail').innerHTML = `
      ${p.lat ? `<div class="detail-hero">${lotSvg(p, 660, 290)}</div>` : ''}
      <h2>${esc(p.address)}</h2>
      ${p.name ? `<p class="aka">${esc(p.name)}</p>` : ''}
      <div class="facts">
        ${tms.map((t) => `<span class="badge badge-outline">TMS ${esc(t)}</span>`).join('')}
        ${p.acres ? `<span class="badge badge-outline">${p.acres} acres</span>` : ''}
        <span class="badge badge-outline">${p.cases.length} ${p.cases.length === 1 ? 'case' : 'cases'}</span>
        ${p.lat ? `<a class="btn btn-ghost btn-sm" href="https://www.google.com/maps/search/?api=1&query=${p.lat},${p.lng}" target="_blank" rel="noopener">${ICON.ext}Google Maps</a>` : ''}
      </div>
      ${p.geo ? `<p class="geo-note">${esc(GEO_LABEL[p.geo] || p.geo)}</p>` : ''}
      ${p.lat ? '' : '<p class="unmapped">This location could not be placed on the map: the minutes give no street number, or the parcel number has since been retired.</p>'}
      ${p.cases.map((c) => caseCard(c, term)).join('')}`;
    $('pane').scrollTop = 0;
    if (fly && p.lat) {
      const bounds = p.rings ? L.latLngBounds(p.rings.flat()) : L.latLng(p.lat, p.lng).toBounds(120);
      map.flyToBounds(bounds, { maxZoom: 18, padding: [60, 60], duration: 0.6 });
    }
    history.replaceState(null, '', '#' + encodeURIComponent(id));
  }
  function closeDetail() {
    setActive(null);
    $('detailView').hidden = true;
    $('listView').hidden = false;
    history.replaceState(null, '', location.pathname + location.search);
  }
  function highlight(text, term) {
    let out = esc(text);
    for (const t of (term || '').split(/\s+/).filter((x) => x.length > 2)) {
      out = out.replace(new RegExp(`(${t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'), '<mark>$1</mark>');
    }
    return out;
  }
  async function toggleExcerpt(btn) {
    const id = btn.dataset.excerpt;
    const box = document.getElementById('ex-' + id);
    const label = btn.querySelector('span');
    if (!box.hidden) {
      box.hidden = true; btn.setAttribute('aria-expanded', 'false'); label.textContent = 'Minutes';
      return;
    }
    if (!texts) {
      label.textContent = 'Loading…';
      try {
        texts = await (await fetch('data/minutes-text.json')).json();
      } catch (e) {
        label.textContent = 'Could not load';
        return;
      }
    }
    const t = texts[id];
    box.innerHTML = t ? highlight(t, filters().q) : 'No discussion was recorded for this item. See the PDF.';
    box.hidden = false; btn.setAttribute('aria-expanded', 'true'); label.textContent = 'Hide minutes';
  }

  // ---------- Map preview card ----------
  function preview(p, latlng) {
    const s = shown.find((x) => x.p.id === p.id);
    const c = (s ? s.cases : p.cases)[0];
    const html = `
      <div class="thumb">${lotSvg(p, 280, 140)}${p.cases.length > 1 ? `<span class="count">${p.cases.length} cases</span>` : ''}</div>
      <div class="preview-body">
        <span class="eyebrow">${esc(c.kind)} · ${esc(BOARD[c.board])}</span>
        <span class="preview-title">${esc(p.address)}</span>
        <span><span class="badge" style="${statusTone(c.status)}"><span class="dot"></span>${esc(c.status)}</span>
          <span class="muted small">&nbsp;${c.case ? esc(c.case) + ' · ' : ''}${fmtDate(c.date)}</span></span>
        <button class="btn btn-primary btn-sm" type="button" data-open="${esc(p.id)}">View case history</button>
      </div>`;
    L.popup({ className: 'preview', offset: [0, -10], maxWidth: 300, autoPanPadding: [40, 40] })
      .setLatLng(latlng).setContent(html).openOn(map);
  }
  map.getContainer().addEventListener('click', (e) => {
    const b = e.target.closest('button[data-open]');
    if (b) openProperty(b.dataset.open, { fly: false });
  });

  // ---------- Mobile list / map toggle ----------
  function syncMapToggle() {
    const on = document.body.classList.contains('show-map');
    $('mapToggle').setAttribute('aria-pressed', String(on));
    $('mapToggle').querySelector('span').textContent = on ? 'List' : 'Map';
  }
  $('mapToggle').addEventListener('click', () => {
    document.body.classList.toggle('show-map');
    syncMapToggle();
    setTimeout(() => map.invalidateSize(), 50);
  });

  // ---------- Events ----------
  let t;
  $('q').addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => { if (!$('detailView').hidden) closeDetail(); apply(); }, 150); });
  ['fDecision', 'fKind', 'fYear', 'fInView'].forEach((id) => $(id).addEventListener('change', apply));
  $('fBoard').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-v]');
    if (!b) return;
    board = b.dataset.v;
    for (const x of $('fBoard').querySelectorAll('button')) x.setAttribute('aria-checked', String(x === b));
    fillKinds();
    apply();
  });
  $('reset').addEventListener('click', () => {
    $('q').value = ''; $('fDecision').value = ''; $('fKind').value = ''; $('fYear').value = ''; $('fInView').checked = false;
    board = '';
    for (const x of $('fBoard').querySelectorAll('button')) x.setAttribute('aria-checked', String(x.dataset.v === ''));
    fillKinds();
    if (area) setArea(null);
    apply();
  });
  map.on('moveend', () => { if ($('fInView').checked) apply(); });
  const results = $('results');
  results.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-id]');
    if (b) openProperty(b.dataset.id);
  });
  results.addEventListener('mouseover', (e) => {
    const b = e.target.closest('button[data-id]');
    if (b && b.dataset.id !== results._hl) {
      if (results._hl) markState(results._hl, 'hl', false);
      results._hl = b.dataset.id;
      markState(b.dataset.id, 'hl', true);
    }
  });
  results.addEventListener('mouseleave', () => { if (results._hl) markState(results._hl, 'hl', false); results._hl = null; });
  $('detail').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-excerpt]');
    if (b) toggleExcerpt(b);
  });
  $('back').addEventListener('click', closeDetail);
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (drawing) stopDrawing();
    else if (!$('detailView').hidden) closeDetail();
  });

  function fillKinds() {
    const cur = $('fKind').value;
    const counts = new Map();
    for (const p of props) for (const c of p.cases) if (!board || c.board === board) counts.set(c.kind, (counts.get(c.kind) || 0) + 1);
    const kinds = [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a));
    $('fKind').innerHTML = '<option value="">Type of case</option>' + kinds.map((k) => `<option${k === cur ? ' selected' : ''}>${esc(k)}</option>`).join('');
  }

  // ---------- Load ----------
  fetch('data/properties.json').then((r) => r.json()).then(({ meta, properties }) => {
    props = properties;
    for (const p of props) {
      byId.set(p.id, p);
      p._search = [p.address, p.name, p.tms, ...(p.other_tms || []),
        ...p.cases.flatMap((c) => [c.case, c.request, c.kind, c.status, ...c.events.map((e) => e.ord)])]
        .filter(Boolean).join(' ').toLowerCase();
      if (p.lat) {
        const m = L.marker([p.lat, p.lng], { icon: pinIcon(p), keyboard: true, title: p.address, riseOnHover: true });
        m.on('click', (e) => { setActive(p.id); preview(p, e.latlng); });
        m.on('mouseover', () => {
          const card = results.querySelector(`button[data-id="${CSS.escape(p.id)}"]`);
          if (card) card.classList.add('hl');
        });
        m.on('mouseout', () => results.querySelectorAll('.prop.hl').forEach((x) => x.classList.remove('hl')));
        markers.set(p.id, m);
      }
    }
    $('fDecision').insertAdjacentHTML('beforeend', GROUPS.map((g) => `<option value="${g.key}">${esc(g.label)}</option>`).join(''));
    fillKinds();
    const years = [...new Set(props.flatMap((p) => p.cases.flatMap((c) => c.events.map((e) => e.date.slice(0, 4)))))].sort().reverse();
    $('fYear').insertAdjacentHTML('beforeend', years.map((y) => `<option>${y}</option>`).join(''));
    const nCases = meta.cases.boza + meta.cases.planning;
    $('stats').textContent = `${nCases.toLocaleString()} cases · ${meta.properties.toLocaleString()} properties · ${meta.first.slice(0, 4)}–${meta.last.slice(0, 4)}`;
    // A boundary shared in the URL: ?area=lat,lng;lat,lng;...
    const shared = (new URLSearchParams(location.search).get('area') || '').split(';')
      .map((s) => s.split(',').map(Number)).filter((q) => q.length === 2 && q.every(Number.isFinite));
    const mapped = props.filter((p) => p.lat);
    if (shared.length >= 3) {
      setArea(shared);
    } else {
      apply();
      if (mapped.length) map.fitBounds(L.latLngBounds(mapped.map((p) => [p.lat, p.lng])).pad(0.05), { maxZoom: 14 });
    }
    const hash = decodeURIComponent(location.hash.slice(1));
    if (hash && byId.has(hash)) openProperty(hash);
  }).catch((e) => {
    $('stats').textContent = 'Could not load case data: ' + e.message;
  });
})();
