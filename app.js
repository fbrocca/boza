/* Zoning Appeals Map: Mount Pleasant BOZA cases on a map.
 * Data: data/properties.json (one entry per parcel, built by tools/build_data.py)
 *       data/minutes-text.json (minutes excerpt per hearing, fetched on demand)
 */
(function () {
  'use strict';

  const CENTER = [32.8323, -79.8284];
  const COLORS = {
    'Approved': '--approved',
    'Approved with conditions': '--conditions',
    'Denied': '--denied',
    'Deferred': '--deferred',
    'Withdrawn': '--withdrawn',
  };
  const MAIN = Object.keys(COLORS);
  const colorVar = (d) => `var(${COLORS[d] || '--other'})`;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmtDate = (iso) => new Date(iso + 'T12:00:00').toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });

  let props = [];
  let byId = new Map();
  let markers = new Map();
  let texts = null;
  let activeId = null;
  let shown = [];

  // ---------- Map ----------
  const map = L.map('map', { zoomControl: false, preferCanvas: false }).setView(CENTER, 12);
  L.control.zoom({ position: 'topright' }).addTo(map);
  const streets = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  const satellite = L.layerGroup([
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 20, maxNativeZoom: 19,
      attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics',
    }),
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 20, maxNativeZoom: 19, opacity: 0.7,
    }),
  ]);
  L.control.layers({ 'Map': streets, 'Satellite': satellite }, null, { position: 'topright' }).addTo(map);
  const cluster = L.markerClusterGroup({
    showCoverageOnHover: false, maxClusterRadius: 40, spiderfyOnMaxZoom: true,
    disableClusteringAtZoom: 17,
    iconCreateFunction: (c) => {
      const n = c.getChildCount();
      const s = n < 10 ? 32 : n < 50 ? 38 : 46;
      return L.divIcon({ html: `<div>${n}</div>`, className: 'cluster', iconSize: [s, s] });
    },
  });
  map.addLayer(cluster);
  const outline = L.layerGroup().addTo(map);
  const GEO_LABEL = {
    'parcel': 'Pin and outline: county parcel record',
    'address point': 'Pin: county address point',
    'address point (TMS in minutes did not match)': 'Pin: county address point (the TMS in the minutes points elsewhere)',
    'street estimate': 'Pin: approximate, estimated along the street',
    'street estimate (TMS in minutes did not match)': 'Pin: approximate, estimated along the street',
    'manual': 'Pin: placed by hand',
  };

  $('legend').innerHTML = [...MAIN, 'Other / see minutes'].map((d) =>
    `<div><span class="dot" style="--c:${colorVar(d)}"></span>${esc(d)}</div>`).join('') +
    '<div style="margin-top:2px;color:var(--muted)">Colour = latest decision</div>';

  function pinIcon(p, active) {
    const multi = p.hearings.length > 1 ? ' multi' : '';
    return L.divIcon({
      className: `pin${multi}${active ? ' active' : ''}`,
      html: `<span style="--c:${colorVar(p.hearings[0].decision)}"></span>`,
      iconSize: multi ? [22, 22] : [18, 18],
    });
  }

  // ---------- Filtering ----------
  function hearingMatches(h, f) {
    if (f.decision === 'other' ? MAIN.includes(h.decision) : f.decision && h.decision !== f.decision) return false;
    if (f.kind && h.kind !== f.kind) return false;
    if (f.year && !h.date.startsWith(f.year)) return false;
    return true;
  }

  function currentFilters() {
    return {
      q: $('q').value.trim().toLowerCase(),
      decision: $('fDecision').value,
      kind: $('fKind').value,
      year: $('fYear').value,
      inView: $('fInView').checked,
    };
  }

  function apply() {
    const f = currentFilters();
    const terms = f.q.split(/\s+/).filter(Boolean);
    const bounds = map.getBounds();
    shown = props.filter((p) => {
      const hs = p.hearings.filter((h) => hearingMatches(h, f));
      if (!hs.length) return false;
      if (terms.length && !terms.every((t) => p._search.includes(t))) return false;
      if (f.inView && !(p.lat && bounds.contains([p.lat, p.lng]))) return false;
      return true;
    });
    const visible = new Set(shown.map((p) => p.id));
    cluster.clearLayers();
    cluster.addLayers(shown.filter((p) => p.lat).map((p) => markers.get(p.id)));
    renderList();
    const nh = shown.reduce((a, p) => a + p.hearings.filter((h) => hearingMatches(h, f)).length, 0);
    $('count').textContent = `${shown.length} ${shown.length === 1 ? 'property' : 'properties'}, ${nh} hearings`;
    if (activeId && !visible.has(activeId)) setActive(null);
  }

  function renderList() {
    const el = $('results');
    if (!shown.length) {
      el.innerHTML = '<li class="empty">No cases match. Clear the search or filters.</li>';
      return;
    }
    el.innerHTML = shown.map((p) => {
      const h = p.hearings[0];
      const n = p.hearings.length;
      return `<li><button type="button" data-id="${esc(p.id)}">
        <span class="dot" style="--c:${colorVar(h.decision)}"></span>
        <span class="addr">${esc(p.address || p.tms || 'Unknown location')}${n > 1 ? `<span class="tag">${n} hearings</span>` : ''}${p.lat ? '' : '<span class="tag">not on map</span>'}</span>
        <span class="when">${fmtDate(h.date)}</span>
        <span class="line2">${esc(h.case)} &middot; ${esc(h.decision === 'Unknown' ? 'See minutes' : h.decision)}${h.request ? ` &middot; ${esc(h.request)}` : ''}</span>
      </button></li>`;
    }).join('');
  }

  // ---------- Detail ----------
  function setActive(id) {
    if (activeId && markers.has(activeId)) markers.get(activeId).setIcon(pinIcon(byId.get(activeId), false));
    activeId = id;
    outline.clearLayers();
    if (id && markers.has(id)) markers.get(id).setIcon(pinIcon(byId.get(id), true));
    const p = id && byId.get(id);
    if (p && p.rings) {
      const accent = getComputedStyle(document.documentElement).getPropertyValue('--focus').trim();
      L.polygon(p.rings, { color: accent, weight: 2, fillOpacity: 0.12, interactive: false }).addTo(outline);
    }
  }

  function openProperty(id, { fly = true } = {}) {
    const p = byId.get(id);
    if (!p) return;
    setActive(id);
    $('listView').hidden = true;
    $('detailView').hidden = false;
    const f = currentFilters();
    const term = f.q;
    $('detail').innerHTML = `
      <h2>${esc(p.address || 'Unknown location')}</h2>
      <p class="meta">${p.tms ? `TMS ${esc(p.tms)} &middot; ` : ''}${p.acres ? `${p.acres} acres &middot; ` : ''}${p.hearings.length} ${p.hearings.length === 1 ? 'hearing' : 'hearings'}
        ${p.lat ? ` &middot; <a href="https://www.google.com/maps/search/?api=1&query=${p.lat},${p.lng}" target="_blank" rel="noopener">Open in Google Maps</a>` : ''}
        ${p.geo ? `<br>${esc(GEO_LABEL[p.geo] || p.geo)}` : ''}</p>
      ${p.lat ? '' : '<p class="unmapped-note">This location could not be placed on the map: the minutes give no street number, or the parcel number has since been retired. The case details below are complete.</p>'}
      ${p.hearings.map((h) => `
        <article class="hearing">
          <div class="hearing-top">
            <span class="hearing-date">${fmtDate(h.date)}</span>
            <span class="badge" style="--c:${colorVar(h.decision)}"><span class="dot"></span>${esc(h.decision === 'Unknown' ? 'See minutes' : h.decision)}</span>
          </div>
          <div class="case">Case ${esc(h.case)} &middot; ${esc(h.kind)}${h.item !== 'hearing' ? ` &middot; ${esc(h.item)}` : ''}</div>
          ${h.request ? `<p class="request">${highlight(h.request, term)}</p>` : ''}
          ${h.note ? `<p class="note">${esc(h.note)}</p>` : ''}
          <div class="actions">
            <button class="btn primary" type="button" data-excerpt="${esc(h.id)}" aria-expanded="false">Read the minutes</button>
            <a class="btn" href="${esc(h.pdf)}#page=${h.page}" target="_blank" rel="noopener">PDF, page ${h.page}</a>
            ${h.town ? `<a class="btn" href="${esc(h.town)}" target="_blank" rel="noopener">Town's copy</a>` : ''}
          </div>
          <div class="excerpt" id="ex-${esc(h.id)}" hidden></div>
        </article>`).join('')}`;
    $('detail').scrollTop = 0;
    if (fly && p.lat) {
      // On phones the bottom sheet covers the lower half of the map: frame the lot above it.
      const sheet = isMobile() ? panel.getBoundingClientRect().height : 0;
      const bounds = p.rings ? L.latLngBounds(p.rings.flat()) : L.latLng(p.lat, p.lng).toBounds(120);
      map.flyToBounds(bounds, {
        maxZoom: 18, paddingTopLeft: [40, 40], paddingBottomRight: [40, 40 + sheet], duration: 0.6,
      });
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
    if (!term) return out;
    for (const t of term.split(/\s+/).filter((x) => x.length > 2)) {
      out = out.replace(new RegExp(`(${t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'), '<mark>$1</mark>');
    }
    return out;
  }

  async function toggleExcerpt(btn) {
    const id = btn.dataset.excerpt;
    const box = document.getElementById('ex-' + id);
    if (!box.hidden) {
      box.hidden = true; btn.setAttribute('aria-expanded', 'false'); btn.textContent = 'Read the minutes';
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
    box.innerHTML = t ? highlight(t, currentFilters().q) : 'No discussion was recorded for this item. See the PDF.';
    box.hidden = false; btn.setAttribute('aria-expanded', 'true'); btn.textContent = 'Hide the minutes';
  }

  // ---------- Mobile bottom sheet ----------
  const panel = $('panel');
  const isMobile = () => matchMedia('(max-width: 760px)').matches;
  function expandPanel() { if (isMobile()) { panel.classList.remove('collapsed'); } }
  document.querySelector('.panel-head').addEventListener('click', () => {
    if (!isMobile()) return;
    if (panel.classList.contains('collapsed')) panel.classList.remove('collapsed');
    else if (panel.classList.contains('expanded')) panel.classList.replace('expanded', 'collapsed');
    else panel.classList.add('expanded');
  });
  map.on('movestart', () => { if (isMobile() && $('detailView').hidden) panel.classList.add('collapsed'); });

  // ---------- Events ----------
  let t;
  $('q').addEventListener('input', () => { clearTimeout(t); t = setTimeout(apply, 120); });
  ['fDecision', 'fKind', 'fYear', 'fInView'].forEach((id) => $(id).addEventListener('change', apply));
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

  // ---------- Load ----------
  fetch('data/properties.json').then((r) => r.json()).then(({ meta, properties }) => {
    props = properties;
    for (const p of props) {
      byId.set(p.id, p);
      p._search = [p.address, p.tms, ...p.hearings.flatMap((h) => [h.case, h.request, h.kind, h.decision])]
        .join(' ').toLowerCase();
      if (p.lat) {
        const m = L.marker([p.lat, p.lng], { icon: pinIcon(p, false), keyboard: true, title: p.address });
        m.bindTooltip(`<b>${esc(p.address)}</b><br>${p.hearings.length} ${p.hearings.length === 1 ? 'hearing' : 'hearings'}, latest ${fmtDate(p.hearings[0].date)}`, { direction: 'top', offset: [0, -8] });
        m.on('click', () => openProperty(p.id, { fly: false }));
        markers.set(p.id, m);
      }
    }
    const years = [...new Set(props.flatMap((p) => p.hearings.map((h) => h.date.slice(0, 4))))].sort().reverse();
    $('fYear').insertAdjacentHTML('beforeend', years.map((y) => `<option>${y}</option>`).join(''));
    $('stats').innerHTML = `<b>${meta.hearings}</b> hearings &middot; <b>${meta.properties}</b> properties &middot; ${meta.first.slice(0, 4)}&ndash;${meta.last.slice(0, 4)}` +
      (meta.mapped < meta.properties ? ` &middot; ${meta.mapped} on map` : '');
    apply();
    const mapped = props.filter((p) => p.lat);
    if (mapped.length) map.fitBounds(L.latLngBounds(mapped.map((p) => [p.lat, p.lng])).pad(0.05), { maxZoom: 14 });
    const hash = decodeURIComponent(location.hash.slice(1));
    if (hash && byId.has(hash)) openProperty(hash);
  }).catch((e) => {
    $('stats').textContent = 'Could not load case data: ' + e.message;
  });
})();
