/* The Zoning Record landing page: live docket, numbers and parcel drawing. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const track = (path, title) => { try { if (window.goatcounter && window.goatcounter.count) window.goatcounter.count({ path, title: title || path, event: true }); } catch (e) { /* optional */ } };
  const fmt = (n) => Number(n).toLocaleString('en-US');
  const today = new Date(); const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

  // Search: hand the query to the map, which opens the property when there's one match.
  $('search').addEventListener('submit', (e) => {
    e.preventDefault();
    const q = $('q').value.trim();
    track('landing/search', 'Landing search');
    location.href = q ? `map/?q=${encodeURIComponent(q)}` : 'map/';
  });
  document.addEventListener('click', (e) => {
    const a = e.target.closest('[data-door]');
    if (a) track('landing/door-' + a.dataset.door, 'Landing: ' + a.textContent.trim());
  });

  // Docket: zoning items on agendas posted for meetings that haven't happened yet.
  fetch('data/upcoming.json').then((r) => r.json()).then((d) => {
    if (d.updated) $('updated').textContent = 'Updated ' + new Date(d.updated + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }) + " · from the Town's own minutes";
    const meets = (d.meetings || []).filter((m) => m.date >= iso);
    const items = meets.flatMap((m) => m.items.map((it) => ({ m, it })));
    $('dockN').textContent = items.length ? `${items.length} ${items.length === 1 ? 'item' : 'items'}` : '';
    if (!items.length) {
      $('dockList').innerHTML = '<li class="d-empty">No zoning agendas are posted yet. The Town posts them about a week before each meeting; <a href="feeds/meetings.ics">add the calendar</a> to get them automatically.</li>';
      return;
    }
    const shown = items.slice(0, 6);
    $('dockList').innerHTML = shown.map(({ m, it }) => {
      const day = new Date(m.date + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
      const href = it.property ? `map/#${encodeURIComponent(it.property)}` : m.agenda;
      const req = it.request && it.request.length > 120 ? it.request.slice(0, 117).replace(/\s+\S*$/, '') + '…' : it.request;
      return `<li><span class="d-date">${esc(day)}<br><span>${esc(m.time || '')}</span></span>
        <span><span class="d-board">${esc(m.label)}</span><a class="d-title" href="${esc(href)}"${it.property ? '' : ' rel="noopener"'}>${esc(it.title)}</a>${req ? `<span class="d-req">${esc(req)}</span>` : ''}</span></li>`;
    }).join('') + (items.length > shown.length ? `<li class="d-empty">And ${items.length - shown.length} more on the map.</li>` : '');
  }).catch(() => { $('dockList').innerHTML = '<li class="d-empty">The docket could not be loaded. <a href="map/">Open the map</a>.</li>'; });

  // Numbers and drawing, written at deploy (tools/landing_data.py).
  fetch('data/summary.json').then((r) => r.json()).then((s) => {
    if (s.decisions) $('nDecisions').textContent = fmt(s.decisions);
    if (s.neighborhoods) $('nHoods').textContent = fmt(s.neighborhoods);
    if (s.questions) $('nQuestions').textContent = fmt(s.questions);
  }).catch(() => {});
  fetch('plat.svg').then((r) => (r.ok ? r.text() : '')).then((svg) => {
    if (!svg) return;
    $('plat').innerHTML = svg;
    const n = $('plat').querySelectorAll('path').length;
    if (!$('plat').querySelector('path.soon')) document.querySelector('.cap-soon').remove();
    $('platCap').firstChild.textContent = `Fig. 1 · The Old Village and Coleman Boulevard. Each of these ${fmt(n)} outlines is a lot that went before a Town board`;
  }).catch(() => {});
})();
