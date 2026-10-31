/* Mount Pleasant Zoning Map.
 * Data: data/properties.json  one entry per parcel; each has cases (BOZA or
 *                              planning), each case a timeline of events
 *       data/minutes-text.json minutes text per event, fetched on demand
 */
(function () {
  'use strict';

  const CENTER = [32.8323, -79.8284];
  // Outcome groups: colour, legend label, and which statuses fall in each.
  const GROUPS = [
    { key: 'approved', label: 'Approved / adopted', color: '--approved',
      test: (s) => /^(Approved|Adopted by Council)$/.test(s) },
    { key: 'conditions', label: 'Approved with conditions', color: '--conditions',
      test: (s) => s === 'Approved with conditions' },
    { key: 'denied', label: 'Denied', color: '--denied',
      test: (s) => /^(Denied|Denied by Council)$/.test(s) },
    { key: 'pending', label: 'Pending / recommendation only', color: '--deferred',
      test: (s) => /^(Recommended approval|Recommended denial|Passed first reading|Deferred|No recommendation)$/.test(s) },
    { key: 'withdrawn', label: 'Withdrawn', color: '--withdrawn', test: (s) => s === 'Withdrawn' },
    { key: 'other', label: 'Other / see minutes', color: '--other', test: () => true },
  ];
  const groupOf = (status) => GROUPS.find((g) => g.test(status));
  const colorVar = (status) => `var(${groupOf(status).color})`;
  const BOARD = { boza: 'Zoning Appeals', planning: 'Rezoning & planning' };
  const STATUS_HELP = {
    'Recommended approval': 'The Planning Commission recommended approval. No Town Council decision was found in the minutes.',
    'Recommended denial': 'The Planning Commission recommended denial. No Town Council decision was found in the minutes.',
    'Passed first reading': 'Town Council approved first reading. No later reading was found in the minutes.',
  };
  const GEO_LABEL = {
    'parcel': 'Pin and outline: county parcel record',
    'address point': 'Pin: county address point',
    'address point (TMS in minutes did not match)': 'Pin: county address point (the TMS in the minutes points elsewhere)',
    'street estimate': 'Pin: approximate, estimated along the street',
    'street estimate (TMS in minutes did not match)': 'Pin: approximate, estimated along the street',
    'manual': 'Pin: placed by hand',
  };

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmtDate = (iso) => new Date(iso + 'T12:00:00').toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });

  let props = [];
  const byId = new Map();
  const markers = new Map();
  let texts = null;
  let activeId = null;
  let shown = [];
  let board = '';

  // ---------- Map ----------
  const map = L.map('map', { zoomControl: false }).setView(CENTER, 12);
  L.control.zoom({ position: 'topright' }).addTo(map);
  const streets = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
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
    showCoverageOnHover: false, maxClusterRadius: 40, spiderfyOnMaxZoom: true, disableClusteringAtZoom: 17,
    iconCreateFunction: (c) => {
      const n = c.getChildCount();
      const s = n < 10 ? 32 : n < 50 ? 38 : 46;
      return L.divIcon({ html: `<div>${n}</div>`, className: 'cluster', iconSize: [s, s] });
    },
  });
  map.addLayer(cluster);
  const outline = L.layerGroup().addTo(map);

  $('legend').innerHTML = GROUPS.map((g) =>
    `<div><span class="dot" style="--c:var(${g.color})"></span>${esc(g.label)}</div>`).join('') +
    '<div class="legend-note">Colour = latest case &middot; circle = zoning appeal &middot; diamond = rezoning &amp; planning</div>';

  function pinIcon(p, active, cases) {
    const latest = (cases || p.cases)[0];
    const multi = p.cases.length > 1 ? ' multi' : '';
    const ring = latest.board === 'planning' ? ' planning' : '';
    return L.divIcon({
      className: `pin${multi}${ring}${active ? ' active' : ''}`,
      html: `<span style="--c:${colorVar(latest.status)}"></span>`,
      iconSize: multi ? [22, 22] : [18, 18],
    });
  }

  // ---------- Filtering ----------
  function filters() {
    return {
      q: $('q').value.trim().toLowerCase(),
      board,
      group: $('fDecision').value,
      kind: $('fKind').value,
      year: $('fYear').value,
      inView: $('fInView').checked,
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
      shown.push({ p, cases: cs });
    }
    cluster.clearLayers();
    cluster.addLayers(shown.filter((s) => s.p.lat).map((s) => {
      const m = markers.get(s.p.id);
      m.setIcon(pinIcon(s.p, s.p.id === activeId, s.cases));
      return m;
    }));
    renderList();
    const nc = shown.reduce((a, s) => a + s.cases.length, 0);
    $('count').textContent = `${shown.length} ${shown.length === 1 ? 'property' : 'properties'}, ${nc} ${nc === 1 ? 'case' : 'cases'}`;
  }

  function renderList() {
    const el = $('results');
    if (!shown.length) {
      el.innerHTML = '<li class="empty">No cases match. Clear the search or filters.</li>';
      return;
    }
    el.innerHTML = shown.slice(0, 400).map(({ p, cases }) => {
      const c = cases[0];
      const n = p.cases.length;
      return `<li><button type="button" data-id="${esc(p.id)}">
        <span class="dot" style="--c:${colorVar(c.status)}"></span>
        <span class="addr">${esc(p.address)}${n > 1 ? `<span class="tag">${n} cases</span>` : ''}${p.lat ? '' : '<span class="tag">not on map</span>'}</span>
        <span class="when">${fmtDate(c.date)}</span>
        <span class="line2">${c.case ? esc(c.case) + ' &middot; ' : ''}${esc(c.kind)} &middot; ${esc(c.status)}${c.request ? ' &middot; ' + esc(c.request) : ''}</span>
      </button></li>`;
    }).join('') + (shown.length > 400 ? `<li class="empty">Showing the 400 most recent. Search or filter to narrow.</li>` : '');
  }

  // ---------- Detail ----------
  function setActive(id) {
    const prev = activeId;
    activeId = id;
    for (const pid of [prev, id]) {
      if (pid && markers.has(pid)) {
        const s = shown.find((x) => x.p.id === pid);
        markers.get(pid).setIcon(pinIcon(byId.get(pid), pid === id, s && s.cases));
      }
    }
    outline.clearLayers();
    const p = id && byId.get(id);
    if (p && p.rings) {
      const accent = getComputedStyle(document.documentElement).getPropertyValue('--focus').trim();
      L.polygon(p.rings, { color: accent, weight: 2, fillOpacity: 0.12, interactive: false }).addTo(outline);
    }
  }

  function eventLinks(e) {
    const pdf = e.pdf ? `${e.pdf}#page=${e.page}` : e.town ? `${e.town}#page=${e.page}` : null;
    return `
      <button class="btn small" type="button" data-excerpt="${esc(e.id)}" aria-expanded="false">Minutes</button>
      ${pdf ? `<a class="btn small" href="${esc(pdf)}" target="_blank" rel="noopener">PDF p.${e.page}</a>` : ''}
      ${e.pdf && e.town ? `<a class="btn small" href="${esc(e.town)}" target="_blank" rel="noopener">Town's copy</a>` : ''}`;
  }

  function caseCard(c, term) {
    const help = STATUS_HELP[c.status];
    return `
      <article class="case-card">
        <div class="case-top">
          <span class="case-id">${c.case ? esc(c.case) + ' &middot; ' : ''}${esc(c.kind)}</span>
          <span class="badge" style="--c:${colorVar(c.status)}"><span class="dot"></span>${esc(c.status)}</span>
        </div>
        <div class="board-tag">${esc(BOARD[c.board])}</div>
        ${c.request ? `<p class="request">${highlight(c.request, term)}</p>` : ''}
        ${help ? `<p class="note">${esc(help)}</p>` : ''}
        <ol class="timeline">
          ${c.events.map((e) => `
            <li>
              <div class="tl-head">
                <span class="tl-date">${fmtDate(e.date)}</span>
                <span class="tl-body">${esc(e.body)}${e.ord ? ` &middot; Ord. ${esc(e.ord)}` : ''}</span>
              </div>
              <div class="tl-decision">${esc(e.decision)}${e.item ? ` (${esc(e.item)})` : ''}</div>
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
    setActive(id);
    $('listView').hidden = true;
    $('detailView').hidden = false;
    const term = filters().q;
    const tms = [p.tms, ...(p.other_tms || [])].filter(Boolean);
    $('detail').innerHTML = `
      <h2>${esc(p.address)}</h2>
      ${p.name ? `<p class="aka">${esc(p.name)}</p>` : ''}
      <p class="meta">${tms.length ? `TMS ${tms.map(esc).join(', ')} &middot; ` : ''}${p.acres ? `${p.acres} acres &middot; ` : ''}${p.cases.length} ${p.cases.length === 1 ? 'case' : 'cases'}
        ${p.lat ? ` &middot; <a href="https://www.google.com/maps/search/?api=1&query=${p.lat},${p.lng}" target="_blank" rel="noopener">Google Maps</a>` : ''}
        ${p.geo ? `<br>${esc(GEO_LABEL[p.geo] || p.geo)}` : ''}</p>
      ${p.lat ? '' : '<p class="unmapped-note">This location could not be placed on the map: the minutes give no street number, or the parcel number has since been retired.</p>'}
      ${p.cases.map((c) => caseCard(c, term)).join('')}`;
    $('detail').scrollTop = 0;
    if (fly && p.lat) {
      const sheet = isMobile() ? panel.getBoundingClientRect().height : 0;
      const bounds = p.rings ? L.latLngBounds(p.rings.flat()) : L.latLng(p.lat, p.lng).toBounds(120);
      map.flyToBounds(bounds, { maxZoom: 18, paddingTopLeft: [40, 40], paddingBottomRight: [40, 40 + sheet], duration: 0.6 });
    }
    history.replaceState(null, '', '#' + encodeURIComponent(id));
    expandPanel();
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
    if (!box.hidden) {
      box.hidden = true; btn.setAttribute('aria-expanded', 'false'); btn.textContent = 'Minutes';
      return;
    }
    if (!texts) {
      btn.textContent = 'Loading…';
      try {
        texts = await (await fetch('data/minutes-text.json')).json();
      } catch (e) {
        btn.textContent = 'Could not load. Use the PDF link.';
        return;
      }
    }
    const t = texts[id];
    box.innerHTML = t ? highlight(t, filters().q) : 'No discussion was recorded for this item. See the PDF.';
    box.hidden = false; btn.setAttribute('aria-expanded', 'true'); btn.textContent = 'Hide minutes';
  }

  // ---------- Mobile bottom sheet ----------
  const panel = $('panel');
  const isMobile = () => matchMedia('(max-width: 760px)').matches;
  function expandPanel() { if (isMobile()) panel.classList.remove('collapsed'); }
  document.querySelector('.panel-head').addEventListener('click', () => {
    if (!isMobile()) return;
    if (panel.classList.contains('collapsed')) panel.classList.remove('collapsed');
    else if (panel.classList.contains('expanded')) panel.classList.replace('expanded', 'collapsed');
    else panel.classList.add('expanded');
  });
  map.on('dragstart', () => { if (isMobile() && $('detailView').hidden) panel.classList.add('collapsed'); });

  // ---------- Events ----------
  let t;
  $('q').addEventListener('input', () => { clearTimeout(t); t = setTimeout(apply, 120); });
  ['fDecision', 'fKind', 'fYear', 'fInView'].forEach((id) => $(id).addEventListener('change', apply));
  $('fBoard').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-v]');
    if (!b) return;
    board = b.dataset.v;
    for (const x of $('fBoard').querySelectorAll('button')) x.setAttribute('aria-checked', String(x === b));
    fillKinds();
    apply();
  });
  map.on('moveend', () => { if ($('fInView').checked) apply(); });
  $('results').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-id]');
    if (b) openProperty(b.dataset.id);
  });
  $('detail').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-excerpt]');
    if (b) toggleExcerpt(b);
  });
  $('back').addEventListener('click', closeDetail);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('detailView').hidden) closeDetail();
  });

  function fillKinds() {
    const cur = $('fKind').value;
    const counts = new Map();
    for (const p of props) for (const c of p.cases) if (!board || c.board === board) counts.set(c.kind, (counts.get(c.kind) || 0) + 1);
    const kinds = [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a));
    $('fKind').innerHTML = '<option value="">All</option>' + kinds.map((k) => `<option${k === cur ? ' selected' : ''}>${esc(k)}</option>`).join('');
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
        const m = L.marker([p.lat, p.lng], { icon: pinIcon(p, false), keyboard: true, title: p.address });
        const c = p.cases[0];
        m.bindTooltip(`<b>${esc(p.address)}</b><br>${c.case ? esc(c.case) + ' · ' : ''}${esc(c.kind)} · ${esc(c.status)}${p.cases.length > 1 ? `<br>${p.cases.length} cases` : ''}`, { direction: 'top', offset: [0, -8] });
        m.on('click', () => openProperty(p.id, { fly: false }));
        markers.set(p.id, m);
      }
    }
    $('fDecision').insertAdjacentHTML('beforeend', GROUPS.map((g) => `<option value="${g.key}">${esc(g.label)}</option>`).join(''));
    fillKinds();
    const years = [...new Set(props.flatMap((p) => p.cases.flatMap((c) => c.events.map((e) => e.date.slice(0, 4)))))].sort().reverse();
    $('fYear').insertAdjacentHTML('beforeend', years.map((y) => `<option>${y}</option>`).join(''));
    const nCases = meta.cases.boza + meta.cases.planning;
    $('stats').innerHTML = `<b>${nCases}</b> cases &middot; <b>${meta.properties}</b> properties &middot; ${meta.first.slice(0, 4)}&ndash;${meta.last.slice(0, 4)} &middot; ${meta.mapped} on map`;
    apply();
    const mapped = props.filter((p) => p.lat);
    if (mapped.length) map.fitBounds(L.latLngBounds(mapped.map((p) => [p.lat, p.lng])).pad(0.05), { maxZoom: 14 });
    const hash = decodeURIComponent(location.hash.slice(1));
    if (hash && byId.has(hash)) openProperty(hash);
  }).catch((e) => {
    $('stats').textContent = 'Could not load case data: ' + e.message;
  });
})();
