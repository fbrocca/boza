/* Plan a request: lot lookup, application path, comparable cases, and how to
 * strengthen an application. Everything runs in the browser from public data:
 * Charleston County address + parcel services, Town of Mount Pleasant zoning
 * services, and data/properties.json (cases with facts read from the minutes).
 * Nothing is scored or predicted; every pattern shows its sample size.
 */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmtDate = (iso) => new Date(iso + 'T12:00:00').toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  const track = (name, title) => { try { if (window.goatcounter && window.goatcounter.count) window.goatcounter.count({ path: name, title: title || name, event: true }); } catch (e) { /* analytics optional */ } };

  const COUNTY = 'https://gisccapps.charlestoncounty.org/arcgis/rest/services';
  const TOWN = 'https://maps.tompsc.com/arcgis/rest/services/Parcel_Search_New';
  const BBOX = [32.70, 33.00, -80.00, -79.65];
  const SETBACKS = ['front_setback', 'side_setback', 'rear_setback', 'multiple_setbacks'];
  const LAND = ['lot_shape_or_size', 'trees', 'topography_wetlands_water', 'existing_nonconforming_structure', 'safety'];
  const RELIEF = {
    front_setback: 'front setback', side_setback: 'side setback', rear_setback: 'rear setback', multiple_setbacks: 'several setbacks',
    height: 'height', lot_coverage_or_bar: 'lot coverage / building area ratio', accessory_structure: 'accessory structure',
    porch_or_design_standard: 'porch / design standard', tree_removal_or_protection: 'tree removal / protection', parking: 'parking',
    buffer: 'buffer', dock_or_marsh: 'dock / marsh', signage: 'signage', use: 'use', lot_size_density_subdivision: 'lot size / density',
  };
  const REASON = {
    unreasonable_restriction_or_prohibits_use: 'following the rule would not unreasonably restrict use of the property',
    extraordinary_conditions: 'no extraordinary conditions on the property',
    not_generally_applicable: 'the conditions apply generally to other properties',
    no_substantial_detriment: 'the request would harm neighbours or the area',
    self_created: 'the hardship was self-created',
    neighborhood_opposition: 'neighbour opposition',
    neighborhood_character: 'neighbourhood character',
    tree_protection: 'tree protection',
    comp_plan_inconsistent: 'inconsistent with the Comprehensive Plan',
    traffic_or_infrastructure: 'traffic or infrastructure',
    precedent_concern: 'concern about setting a precedent',
  };

  // ---------- data ----------
  let all = null; // [{p, c, f}]
  async function loadCases() {
    if (all) return all;
    const { properties } = await (await fetch('data/properties.json')).json();
    all = [];
    for (const p of properties) for (const c of p.cases) all.push({ p, c, f: c.facts || {} });
    return all;
  }
  const isVariance = (x) => x.c.board === 'boza' && (x.f.type === 'variance' || (!x.f.type && /^V-/.test(x.c.case || '')));
  const isRezoning = (x) => x.c.board === 'planning' && ['rezoning', 'annexation', 'pd_amendment'].includes(x.f.type);
  const approvedV = (x) => /^Approved/.test(x.c.status);
  const decidedV = (x) => /^(Approved|Approved with conditions|Denied)$/.test(x.c.status);
  const adoptedR = (x) => x.c.status === 'Adopted by Council';
  const decidedR = (x) => /^(Adopted|Denied) by Council$/.test(x.c.status);
  function rate(rows, ok) {
    const n = rows.length, k = rows.filter(ok).length;
    return { k, n, pct: n ? Math.round(100 * k / n) : null, txt: n ? `${k} of ${n} (${Math.round(100 * k / n)}%)` : 'no cases' };
  }
  const smallN = (r) => (r.n < 8 ? '<span class="small-n" title="Few past cases: treat as anecdotal">small sample</span>' : '');
  const median = (a) => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y); const m = Math.floor(s.length / 2); return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  function distM(a, b) {
    const R = 6371000, toR = Math.PI / 180;
    const dLat = (b.lat - a.lat) * toR, dLng = (b.lng - a.lng) * toR;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * toR) * Math.cos(b.lat * toR) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }
  const link = (x, label) => `<a href="./#${encodeURIComponent(x.p.id)}" target="_blank" rel="noopener">${esc(label || x.p.address)}</a>`;

  // ---------- live lookups ----------
  async function arc(url, params) {
    const q = new URLSearchParams({ ...params, f: 'json' });
    const r = await fetch(`${url}?${q}`);
    const d = await r.json();
    if (d.error) throw new Error(d.error.message || 'map service error');
    return d;
  }
  const TMS_RE = /^\s*(\d{3})-?(\d{2})-?(\d{2})-?(\d{3})\s*$/;
  function centroid(rings) {
    const pts = rings.flat();
    return { lat: pts.reduce((a, q) => a + q[0], 0) / pts.length, lng: pts.reduce((a, q) => a + q[1], 0) / pts.length };
  }
  function parcelFrom(f) {
    const pid = f.attributes.PID;
    const rings = (f.geometry.rings || []).map((r) => r.map(([x, y]) => [y, x]));
    return { tms: `${pid.slice(0, 3)}-${pid.slice(3, 5)}-${pid.slice(5, 7)}-${pid.slice(7)}`,
             acres: f.attributes.ACRES_CAL ? Math.round(f.attributes.ACRES_CAL * 1000) / 1000 : null, rings };
  }
  async function parcelBy(params) {
    const d = await arc(`${COUNTY}/ProVal/Parcels/MapServer/0/query`, { outFields: 'PID,ACRES_CAL', outSR: 4326, returnGeometry: true, geometryPrecision: 6, ...params });
    return d.features || [];
  }
  const houseKey = (s) => { const m = String(s).toLowerCase().match(/^\s*(\d+)\s+(?:[nsew]\.?\s+)?([a-z]+)/); return m ? m[1] + ' ' + m[2] : null; };

  /* Find the lot. Order of trust: a TMS typed by the user; a property already in our data with
     the same house number and street (its TMS was verified when the map was built); the county
     address point, falling back to the nearest parcel within 30 m when the point is in the street. */
  async function findLot(input, rows) {
    const t = input.match(TMS_RE);
    if (t) {
      const f = (await parcelBy({ where: `PID='${t.slice(1).join('')}'` }))[0];
      if (!f) return null;
      const par = parcelFrom(f);
      return { address: `TMS ${par.tms}`, ...par, ...centroid(par.rings), source: 'tms' };
    }
    const g = await arc(`${COUNTY}/LOCATORS/AddressStreetCompositeLocator_Pro/GeocodeServer/findAddressCandidates`,
      { SingleLine: `${input}, Mount Pleasant, SC`, outSR: 4326, maxLocations: 5, outFields: 'Addr_type,Score' });
    const cand = (g.candidates || []).find((c) => c.score >= 85 && c.location.y > BBOX[0] && c.location.y < BBOX[1] && c.location.x > BBOX[2] && c.location.x < BBOX[3]);
    const key = houseKey(input);
    const known = key ? [...new Map(rows.filter((x) => x.p.tms && houseKey(x.p.address) === key).map((x) => [x.p.tms, x.p])).values()] : [];
    if (known.length === 1 && known[0].rings) {
      const p = known[0];
      return { address: p.address, tms: p.tms, acres: p.acres, rings: p.rings, ...centroid(p.rings), source: 'known' };
    }
    if (!cand) return null;
    const pt = { lat: cand.location.y, lng: cand.location.x };
    const near = { geometry: `${pt.lng},${pt.lat}`, geometryType: 'esriGeometryPoint', inSR: 4326, spatialRel: 'esriSpatialRelIntersects' };
    let feats = await parcelBy(near);
    let source = 'address';
    if (!feats.length) {
      feats = await parcelBy({ ...near, distance: 30, units: 'esriSRUnit_Meter' });
      source = 'nearest';
    }
    const lot = { address: cand.address.replace(/, MOUNT PLEASANT.*$/i, ''), ...pt, source };
    if (feats.length) {
      const pars = feats.map(parcelFrom).map((q) => ({ ...q, c: centroid(q.rings) }));
      pars.sort((a, b) => distM(pt, a.c) - distM(pt, b.c));
      Object.assign(lot, pars[0], pars[0].c);
      delete lot.c;
    }
    return lot;
  }
  async function zoningOf(lot) {
    const pt = { geometry: `${lot.lng},${lot.lat}`, geometryType: 'esriGeometryPoint', inSR: 4326, spatialRel: 'esriSpatialRelIntersects', returnGeometry: false };
    const [zon, ov, ht, flu] = await Promise.all([
      lot.tms ? arc(`${TOWN}/MPSC_Zoning_New/MapServer/2/query`, { where: `PARCEL_ID='${lot.tms.replace(/-/g, '')}'`, outFields: 'ZONINGVALU,SPLITZONED,LINK', returnGeometry: false }) : { features: [] },
      arc(`${TOWN}/MPSC_Zoning_New/MapServer/0/query`, { ...pt, outFields: 'NAME,LABEL,LINK' }),
      arc(`${TOWN}/MPSC_Height_New/MapServer/0/query`, { ...pt, outFields: 'Height,Notes' }),
      arc(`${TOWN}/MPSC_Land_Use_New/MapServer/3/query`, { ...pt, outFields: 'New_FLU' }),
    ].map((p) => Promise.resolve(p).catch(() => ({ features: [] }))));
    const zs = [...new Set(zon.features.map((f) => f.attributes.ZONINGVALU).filter(Boolean))];
    return {
      zoning: zs, zoning_link: zon.features[0]?.attributes.LINK,
      overlays: ov.features.map((f) => ({ name: f.attributes.NAME, label: f.attributes.LABEL, link: f.attributes.LINK })),
      height: ht.features[0]?.attributes.Height, height_note: ht.features[0]?.attributes.Notes,
      flu: flu.features[0]?.attributes.New_FLU,
    };
  }

  // ---------- thumbnail (same technique as the map) ----------
  function project(lat, lng, z) {
    const n = 256 * 2 ** z, s = Math.sin(lat * Math.PI / 180);
    return [(lng + 180) / 360 * n, (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n];
  }
  function lotSvg(lot, W, H) {
    const z = 18;
    const [cx, cy] = project(lot.lat, lot.lng, z);
    const x0 = cx - W / 2, y0 = cy - H / 2;
    let imgs = '';
    for (let tx = Math.floor(x0 / 256); tx <= Math.floor((x0 + W) / 256); tx++)
      for (let ty = Math.floor(y0 / 256); ty <= Math.floor((y0 + H) / 256); ty++)
        imgs += `<image href="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${ty}/${tx}" x="${tx * 256}" y="${ty * 256}" width="256" height="256"/>`;
    const shape = (lot.rings || []).map((r) => `<polygon points="${r.map((q) => project(q[0], q[1], z).map((v) => v.toFixed(1)).join(',')).join(' ')}" fill="rgba(255,255,255,.16)" stroke="#fff" stroke-width="2.5" vector-effect="non-scaling-stroke"/>`).join('');
    return `<svg viewBox="${x0.toFixed(1)} ${y0.toFixed(1)} ${W} ${H}" preserveAspectRatio="xMidYMid slice">${imgs}${shape}</svg>`;
  }

  // ---------- current code (Chapter 156, effective May 1, 2025) ----------
  let code = null;
  async function loadCode() {
    if (!code) code = await (await fetch('data/code-standards.json')).json();
    return code;
  }
  const RELIEF_KEY = { front_setback: 'front', side_setback: 'side', rear_setback: 'rear', height: 'height', lot_coverage_or_bar: 'coverage', accessory_structure: 'accessory' };
  const ft = (v) => (typeof v === 'number' ? `${v} ft` : esc(v));
  const sf = (v) => `${Math.round(v).toLocaleString('en-US')} sq ft`;
  const sec = (s) => `<span class="muted">§ ${esc(s)}</span>`;

  function codeSection(lot, z, relief, size, std) {
    const raw = z.zoning[0] || '';
    const key = std.aliases[raw] || raw;
    const d = std.districts[key];
    const ov = Object.fromEntries(z.overlays.map((o) => [o.name, o.label || true]));
    const want = RELIEF_KEY[relief];
    const lotSf = lot.acres ? lot.acres * 43560 : null;
    const notes = [];
    if (!d) {
      const msg = std.not_tabulated[key] || std.not_tabulated.default;
      return `<section class="card block">
        <h2>What the current code requires</h2>
        <p>${esc(msg)}</p>
        ${z.height ? `<p class="hint">Building Height Plan Map for this lot: ${esc(z.height)}.</p>` : ''}
      </section>`;
    }
    const row = (k, label, val, s) => `<tr class="${k === want ? 'hl' : ''}"><th>${label}</th><td>${val}</td><td>${s || sec(d.sec)}</td></tr>`;
    const rows = [];
    if (d.lot_area_sf) rows.push(row('lot', 'Minimum lot area', `${sf(d.lot_area_sf)}${lotSf ? ` <span class="muted">(this lot ≈ ${sf(lotSf)})</span>` : ''}`));
    if (d.lot_width) rows.push(row('width', 'Minimum lot width', ft(d.lot_width)));
    rows.push(row('front', 'Front setback', ft(d.front)));
    rows.push(row('side', 'Side setback', `${ft(d.side)}${d.side_combined ? `, ${d.side_combined} ft both sides combined` : ''}${d.side_corner ? `, ${d.side_corner} ft on a corner side` : ''}`));
    rows.push(row('rear', 'Rear setback', ft(d.rear)));
    if (d.coverage_pct) rows.push(row('coverage', 'Building coverage (max)', `${d.coverage_pct}%${lotSf ? ` <span class="muted">(≈ ${sf(lotSf * d.coverage_pct / 100)} here)</span>` : ''}`));
    if (d.coverage_sf) rows.push(row('coverage', 'Building coverage (max)', sf(d.coverage_sf)));
    if (d.gfa_max_sf) rows.push(row('gfa', 'Building floor area (max)', sf(d.gfa_max_sf)));
    rows.push(row('height', 'Height (max)', `${d.height} ft, ${d.height_sfha} ft in a flood zone${z.height ? `<br><span class="muted">Building Height Plan Map for this lot: ${esc(z.height)}. The map governs.</span>` : ''}`));
    if (d.density) rows.push(row('density', 'Density (max)', esc(d.density)));
    const a = std.accessory;
    rows.push(row('accessory', 'Accessory building', `${a.side} ft side, ${a.rear} ft rear, ${a.height} ft tall${d.acc_footprint ? `, ${sf(d.acc_footprint)} footprint` : ', no footprint cap if coverage is met'}`, sec(a.sec)));

    // Overlays that change the numbers above.
    const np = ov['NP-OD'];
    const resi = /^(R-[1-4]|RR|CC|TH|RM|RC-[12])$/.test(key);
    if (np && !resi) {
      notes.push(`<b>Neighborhood Preservation Overlay (${esc(np === true ? 'NP-OD' : np)})</b> ${sec(std.np_od.sec)}: its house-size rules (2½ stories${np === 'Old Mount Pleasant' ? ', building area ratio up to 50% of the lot, max 5,500 sq ft, 40% impervious' : ''}) are written for residential districts. They don't bind this ${esc(key)} lot today, but would apply if it were rezoned residential.`);
    } else if (np) {
      const porch = std.np_od.porch_front[np]?.[key];
      notes.push(`<b>Neighborhood Preservation Overlay (${esc(np === true ? 'NP-OD' : np)})</b> ${sec(std.np_od.sec)}: houses are limited to 2½ stories.${porch ? ` Unenclosed porches, stoops and balconies may come to <b>${porch} ft</b> from the front line; the rest of the house keeps the ${ft(d.front)} setback.` : ''}${np === 'Old Mount Pleasant' ? ` Building area ratio (house plus accessory buildings over 144 sq ft, garage counted) up to 50% of the lot${lotSf ? ` (≈ ${sf(Math.min(5500, Math.max(lotSf * 0.5, ['R-1', 'R-2'].includes(key) ? 2500 : 1800)))} here)` : ''}, never above 5,500 sq ft; impervious surface up to 40%; any part of an accessory building over 18 ft needs 10 ft side and rear setbacks.` : ''} Nonconforming lots here don't get the 20% front setback reduction.`);
    }
    if (ov['OV-HD']) {
      notes.push(`<b>Old Village Historic District</b> ${sec('156.218')}: principal-building setbacks are set by the Historic District Preservation Commission during its review, based on the pattern of historic buildings nearby. <b>For a setback on the house, ask staff whether this goes to the HDPC rather than the Board of Zoning Appeals.</b> Also: 60 ft street frontage, impervious surface up to 40%, building area ratio up to 50%${lotSf ? ` (≈ ${sf(Math.min(5500, Math.max(lotSf * 0.5, 2500)))} here)` : ''} with at least 10% of it porches, max 5,500 sq ft. Accessory buildings: 10 ft side and rear (the HDPC cannot reduce these), at most 29 ft or the height of the house, behind the house.`);
    }

    // Nonconforming lot: up to 20% setback reduction without a variance.
    const small = lotSf && d.lot_area_sf && lotSf < d.lot_area_sf * 0.98;
    const isSetback = ['front', 'side', 'rear'].includes(want) || relief === 'multiple_setbacks';
    if (small) {
      notes.push(`<b>This lot looks smaller than the district minimum</b> (≈ ${sf(lotSf)} vs ${sf(d.lot_area_sf)}, from county GIS acreage). If it is a legal nonconforming lot, its setbacks may be reduced by up to 20% <b>without a variance</b> ${sec('156.1525')}. A variance is needed only beyond that.${ov['NP-OD'] ? ' In the NP-OD the front setback is excluded.' : ''}`);
    }

    // Requested vs required.
    let cmp = '';
    if (isSetback && want && typeof d[want] === 'number' && size.ask && size.unit === 'ft') {
      const reqd = d[want], left = Math.max(0, reqd - size.ask), pct = Math.round(100 * size.ask / reqd);
      cmp = `<div class="callout">You'd build <b>${size.ask} ft</b> into the <b>${reqd} ft</b> ${want} setback, leaving ${left} ft: a ${pct}% reduction.`;
      if (size.req && size.req !== reqd) cmp += ` You entered a ${size.req} ft requirement; the current table says ${reqd} ft. Check which applies (a recorded plat, PD or overlay can differ).`;
      if (small && pct <= std.nonconforming_reduction_pct && !(want === 'front' && ov['NP-OD'])) cmp += ` <b>That's within the 20% a nonconforming lot may use without a variance.</b> Ask the Zoning Administrator before applying.`;
      cmp += '</div>';
    } else if (want === 'height' && size.ask && size.unit === 'ft') {
      cmp = `<div class="callout">You'd exceed the ${d.height} ft limit by <b>${size.ask} ft</b> (${Math.round(100 * size.ask / d.height)}%). In a flood zone the limit is ${d.height_sfha} ft${z.height ? '; check the Building Height Plan Map value above' : ''}.</div>`;
    } else if (want === 'coverage' && size.ask && size.unit === '%' && d.coverage_pct) {
      cmp = `<div class="callout">Coverage limit is ${d.coverage_pct}%. You entered ${size.ask}%${size.req ? ` of a ${size.req}% requirement` : ''}; confirm whether that's the amount over the limit or the total.</div>`;
    }

    return `<section class="card block">
      <h2>What the current code requires</h2>
      <p class="muted">${esc(key)} district, Zoning Code Chapter 156 as rewritten in 2025 (effective May 1, 2025).${z.zoning.length > 1 ? ` This lot is split-zoned (${esc(z.zoning.join(' / '))}); showing ${esc(key)}.` : ''}${d.dwelling ? ` Figures for a ${esc(d.dwelling)}.` : ''}${d.extra ? ' ' + esc(d.extra) : ''}</p>
      ${cmp}
      <table class="code-table"><tbody>${rows.join('')}</tbody></table>
      ${notes.map((n) => `<p class="callout">${n}</p>`).join('')}
      <p class="hint">Transcribed from Chapter 156; the Town's reading governs. After a denial, the same variance or rezoning can't be refiled for 12 months (§ 156.1298, § 156.1163).</p>
    </section>`;
  }

  // ---------- sections ----------
  // ---------- sales: this lot's last sale and recent sales nearby (Charleston County) ----------
  const PARCELMAP = `${COUNTY}/ProVal/ParcelMap/MapServer/0/query`;
  const F = (f) => (f === 'PID' || f === 'ACRES_CAL' ? 'SDE.P_POLY_PARCEL.' : 'SDE.CAMA.') + f;
  const SALE_FIELDS = ['PID', 'PROP_ST_NO', 'PROP_ST_NAME', 'SALE_PRICE', 'DOC_DATE', 'DEED_BOOK_PAGE', 'ACRES_CAL', 'CLASS_CODE', 'APPRAISAL', 'LAND_APPR', 'IMP_APPR'].map(F).join(',');
  const NEAR_M = 400, SINCE_YEARS = 3;
  const flat = (f) => Object.fromEntries(Object.entries(f.attributes).map(([k, v]) => [k.split('.').pop(), typeof v === 'string' ? v.trim() : v]));
  const titleCase = (s) => String(s || '').toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
  const usd = (v) => (v >= 1e6 ? '$' + (Math.round(v / 1e4) / 100) + 'M' : '$' + Math.round(v).toLocaleString('en-US'));
  const isoDay = (ms) => new Date(ms).toISOString().slice(0, 10);
  async function salesNear(lot) {
    if (!lot.tms) return null;
    const pid = lot.tms.replace(/-/g, '');
    const own = (await arc(PARCELMAP, { where: `${F('PID')}='${pid}'`, outFields: SALE_FIELDS, returnGeometry: false })).features.map(flat)[0] || null;
    const fam = own && own.CLASS_CODE ? own.CLASS_CODE[0] : null; // 1 = residential, 5 = commercial, 9 = vacant/other
    const since = new Date(); since.setFullYear(since.getFullYear() - SINCE_YEARS);
    const where = [`${F('SALE_PRICE')} >= 1000`, `${F('DOC_DATE')} >= DATE '${since.toISOString().slice(0, 10)}'`, `${F('PID')} <> '${pid}'`]
      .concat(fam ? [`${F('CLASS_CODE')} LIKE '${fam}%'`] : []).join(' AND ');
    const near = (await arc(PARCELMAP, { where, geometry: `${lot.lng},${lot.lat}`, geometryType: 'esriGeometryPoint', inSR: 4326,
      spatialRel: 'esriSpatialRelIntersects', distance: NEAR_M, units: 'esriSRUnit_Meter', outFields: SALE_FIELDS, returnGeometry: false })).features.map(flat);
    near.sort((a, b) => b.DOC_DATE - a.DOC_DATE);
    return { own, near, fam };
  }
  function salesSection(s) {
    if (!s) return '';
    const o = s.own;
    const ownLine = !o ? '' : (o.SALE_PRICE >= 1000
      ? `This lot last sold for <b>${usd(o.SALE_PRICE)}</b> on ${fmtDate(isoDay(o.DOC_DATE))}${o.DEED_BOOK_PAGE ? ` (deed ${esc(o.DEED_BOOK_PAGE)})` : ''}.`
      : `This lot's last recorded transfer (${o.DOC_DATE ? fmtDate(isoDay(o.DOC_DATE)) : 'date unknown'}) shows no market price.`)
      + (o && o.APPRAISAL ? ` County appraisal: ${usd(o.APPRAISAL)}${o.IMP_APPR ? ` (land ${usd(o.LAND_APPR)})` : ''}.` : '');
    const kind = { 1: 'residential', 5: 'commercial', 9: 'vacant or other' }[s.fam] || 'all';
    const prices = s.near.map((x) => x.SALE_PRICE).sort((a, b) => a - b);
    const med = median(prices);
    return `<section class="card block">
      <h2>What property around here sold for</h2>
      ${ownLine ? `<p>${ownLine}</p>` : ''}
      ${s.near.length ? `<p class="muted">${s.near.length} ${kind} ${s.near.length === 1 ? 'sale' : 'sales'} recorded within ¼ mile in the last ${SINCE_YEARS} years; median <b>${usd(med)}</b>${s.near.length < 8 ? ' <span class="small-n">small sample</span>' : ''}.</p>
      <table class="sales"><tr><th>Address</th><th>Sold</th><th>Date</th><th class="n">Acres</th></tr>
        ${s.near.slice(0, 10).map((x) => `<tr><td>${esc([x.PROP_ST_NO, titleCase(x.PROP_ST_NAME)].filter(Boolean).join(' ') || 'n/a')}</td><td>${usd(x.SALE_PRICE)}</td><td>${fmtDate(isoDay(x.DOC_DATE))}</td><td class="n">${x.ACRES_CAL ? x.ACRES_CAL.toFixed(2) : ''}</td></tr>`).join('')}
      </table>` : `<p class="muted">No ${kind} sales with a recorded price within ¼ mile in the last ${SINCE_YEARS} years.</p>`}
      <p class="hint">Charleston County records: latest recorded sale per parcel; transfers under $1,000 excluded. The appraisal is a tax value, and prices include buildings.</p>
    </section>`;
  }

  function lotSection(lot, z, here, near) {
    const zz = z.zoning.length ? z.zoning.join(' / ') : 'not found';
    const ov = z.overlays.map((o) => `${esc(o.name)}${o.label ? ' (' + esc(o.label) + ')' : ''}`).join(', ') || 'none';
    const hist = here.length
      ? here.map((x) => `<li>${fmtDate(x.c.date)} · ${esc(x.c.case || x.c.kind)} · ${esc(x.c.status)} · ${link(x, 'view')}</li>`).join('')
      : '<li class="muted">No zoning cases recorded on this lot since 2017.</li>';
    return `<section class="card block">
      <h2>Your lot</h2>
      <div class="lot">
        <div class="thumb">${lotSvg(lot, 330, 248)}</div>
        <div>
          <div class="prop-title">${esc(lot.address)}</div>
          <dl class="kv">
            <dt>TMS</dt><dd>${esc(lot.tms || 'not found')}${lot.acres ? ` · ${lot.acres} acres` : ''}</dd>
            <dt>Zoning</dt><dd>${z.zoning_link ? `<a href="${esc(z.zoning_link)}" target="_blank" rel="noopener">${esc(zz)}</a>` : esc(zz)}</dd>
            <dt>Overlays</dt><dd>${ov}</dd>
            <dt>Height limit</dt><dd>${esc(z.height || 'not found')}${z.height_note ? ` <span class="muted">(${esc(z.height_note)})</span>` : ''}</dd>
            <dt>Comprehensive Plan</dt><dd>${esc(z.flu || 'not found')}</dd>
          </dl>
          <p class="hint">${lot.source === 'nearest' ? 'The address point fell outside a lot; this is the nearest parcel. ' : ''}Wrong lot? Search by its TMS.</p>
          <h3>History on this lot</h3><ul>${hist}</ul>
          <p class="hint">${near.length} zoning cases within 500 ft since 2017${near.length ? ` (${near.filter((x) => (x.f.public_opposition || 0) > 0).length} drew recorded opposition)` : ''}.</p>
        </div>
      </div>
    </section>`;
  }

  function pathSection(relief, z, stats) {
    const ov = z.overlays.map((o) => o.name);
    const commercial = z.zoning.some((d) => /^(AB|NC|OP|LI|PI|CC|LO|UC|MU)/i.test(d));
    const extra = [];
    if (ov.includes('OV-HD')) extra.push('This lot is in the <b>Old Village Historic District</b>: exterior changes also need approval (a certificate of appropriateness) from the <b>Historic District Preservation Commission</b>.');
    if (commercial && !ov.includes('OV-HD')) extra.push('For commercial or multi-family projects, the <b>Design Review Board</b> may also review the architecture.');
    if (relief === 'use') {
      return `<section class="card block">
        <h2>Which application you likely need</h2>
        <div class="path"><p><b>A rezoning, not a variance.</b> In South Carolina a Board of Zoning Appeals cannot grant a variance that allows a use the zoning district doesn't permit (S.C. Code § 6-29-800). Changing what the property can be used for takes a rezoning, or a special exception if the district lists the use as one.</p>
        <p>Path: <b>Planning Commission</b> (public hearing, recommendation) → <b>Planning Committee of Council</b> (recommendation) → <b>Town Council</b> (two readings).</p></div>
        <div class="callout${z.flu ? '' : ' warn'}">The Comprehensive Plan designates this lot <b>${esc(z.flu || 'unknown')}</b>. Council adopted ${stats.cpYes.txt} rezonings described as consistent with the plan, and ${stats.cpNo.txt} described as inconsistent ${smallN(stats.cpNo)}.</div>
        ${extra.map((e) => `<p class="callout">${e}</p>`).join('')}
      </section>`;
    }
    if (relief === 'lot_size_density_subdivision') {
      return `<section class="card block">
        <h2>Which application you likely need</h2>
        <div class="path"><p><b>A subdivision (sketch plan / plat) at the Planning Commission.</b> If the new lots fall below the district's minimum size, or the density exceeds what the district allows, you'd also need a <b>variance</b> (Board of Zoning Appeals) or a <b>rezoning</b>.</p></div>
        ${extra.map((e) => `<p class="callout">${e}</p>`).join('')}
      </section>`;
    }
    return `<section class="card block">
      <h2>Which application you likely need</h2>
      <div class="path"><p><b>A variance from the Board of Zoning Appeals.</b> The Board must find all four:</p>
        <ol><li>extraordinary and exceptional conditions on <i>this</i> property;</li><li>these conditions don't generally apply to other properties in the area;</li>
        <li>applying the rule to this property would effectively prohibit or unreasonably restrict its use;</li><li>granting it won't be a substantial detriment to neighbours or the public good.</li></ol></div>
      ${extra.map((e) => `<p class="callout">${e}</p>`).join('')}
    </section>`;
  }

  function pickComparables(rows, lot, z, relief, userPct) {
    const ov = new Set(z.overlays.map((o) => o.name));
    const zz = new Set(z.zoning);
    return rows.map((x) => {
      const pz = x.p.zoning || {};
      let s = x.f.relief === relief ? 10 : 5;
      if ((pz.zoning || []).some((d) => zz.has(d))) s += 3;
      if ((pz.overlays || []).some((o) => ov.has(o.name))) s += 2;
      const d = x.p.lat ? distM(lot, x.p) : 1e9;
      s += d < 800 ? 3 : d < 2000 ? 2 : d < 5000 ? 1 : 0;
      const y = +x.c.date.slice(0, 4);
      s += y >= 2023 ? 2 : y >= 2021 ? 1 : 0;
      if (userPct != null && typeof x.f.magnitude_pct === 'number') s += Math.max(0, 3 - Math.abs(userPct - x.f.magnitude_pct) / 10);
      return { ...x, score: s, dist: d };
    }).sort((a, b) => b.score - a.score);
  }

  function compSection(comps, relief, isUse) {
    const decided = comps.filter(isUse ? decidedR : decidedV);
    const ok = isUse ? adoptedR : approvedV;
    const r = rate(decided, ok);
    const local = decided.filter((x) => x.dist < 2000);
    const rl = rate(local, ok);
    const recent = decided.filter((x) => x.c.date >= '2021');
    const rr = rate(recent, ok);
    const top = comps.slice(0, 8);
    const word = isUse ? 'adopted' : 'approved';
    return `<section class="card block">
      <h2>How comparable requests fared</h2>
      <p class="muted">${isUse ? 'Rezonings, annexations and PD amendments decided by Town Council' : `Variances for ${esc(RELIEF[relief] || relief)}${SETBACKS.includes(relief) ? ' and other setbacks' : ''}`}, 2017–2026.</p>
      <div class="stats">
        <div class="stat"><b>${r.pct ?? '–'}%</b><span>${word}: ${r.txt} ${smallN(r)}</span></div>
        <div class="stat"><b>${rl.pct ?? '–'}%</b><span>within ~1¼ mi: ${rl.txt} ${smallN(rl)}</span></div>
        <div class="stat"><b>${rr.pct ?? '–'}%</b><span>since 2021: ${rr.txt} ${smallN(rr)}</span></div>
      </div>
      ${(() => { const old = decided.filter((x) => x.c.date < '2025-05-01').length; return old ? `<p class="hint">${old} of these ${decided.length} were decided under the pre-2025 code; compare requests to today's rules above.</p>` : ''; })()}
      <h3>Most similar past cases</h3>
      <ul class="comps">${top.map((x) => {
        const docs = (x.c.events || []).flatMap((e) => e.docs || []).filter((d) => !d.all && /Application|Staff report/.test(d.t)).slice(0, 2);
        return `<li>
          <span class="c-title">${link(x)} <span class="muted">· ${esc(x.c.case || x.c.kind)}</span></span>
          <span class="badge" style="--c:var(--${/^(Approved|Adopted|Reversed)/.test(x.c.status) ? 'approved' : /Denied/.test(x.c.status) ? 'denied' : 'withdrawn'});--cb:var(--${/^(Approved|Adopted|Reversed)/.test(x.c.status) ? 'approved' : /Denied/.test(x.c.status) ? 'denied' : 'withdrawn'}-bg)"><span class="dot"></span>${esc(x.c.status)}</span>
          <span class="c-meta">${fmtDate(x.c.date)}${x.f.magnitude ? ' · ' + esc(x.f.magnitude) : ''}${x.f.vote ? ' · vote ' + esc(x.f.vote) : ''}${x.p.zoning?.zoning ? ' · ' + esc(x.p.zoning.zoning.join('/')) : ''}${x.dist < 1e8 ? ` · ${(x.dist / 1609).toFixed(1)} mi away` : ''}</span>
          ${x.f.key_factor ? `<span class="c-sum"><span class="ai-tag">AI summary</span>${esc(x.f.key_factor)}</span>` : ''}
          ${docs.length ? `<span class="c-docs">${docs.map((d) => `<a class="btn btn-outline btn-sm" href="${esc(d.u)}" target="_blank" rel="noopener">${esc(d.t)}</a>`).join('')}</span>` : ''}
        </li>`;
      }).join('')}</ul>
    </section>`;
  }

  function tip(title, body, data, examples) {
    return `<li><div class="t-title">${title}</div><div class="t-body">${body}</div>${data ? `<div class="t-data">${data}</div>` : ''}${examples ? `<div class="t-ex">${examples}</div>` : ''}</li>`;
  }
  const quote = (x) => (x && x.f.evidence && x.f.evidence[0] ? `“${esc(x.f.evidence[0])}” (${link(x, x.c.case || x.p.address)}, ${esc(x.c.status.toLowerCase())})` : '');

  function varianceTips(V, comps, relief, userPct, near) {
    const dec = V.filter(decidedV);
    const land = (x) => (x.f.hardship || []).some((h) => LAND.includes(h));
    const rLand = rate(dec.filter(land), approvedV), rNoLand = rate(dec.filter((x) => !land(x)), approvedV);
    const sc = rate(dec.filter((x) => x.f.self_created_raised === true), approvedV);
    const opp = rate(dec.filter((x) => (x.f.public_opposition || 0) > 0), approvedV), noOpp = rate(dec.filter((x) => x.f.public_opposition === 0), approvedV);
    const flex = rate(dec.filter((x) => x.f.revised_or_reduced === true), approvedV);
    const compDec = comps.filter(decidedV);
    const exLand = compDec.filter((x) => approvedV(x) && land(x)).slice(0, 2);
    const exUR = dec.find((x) => x.c.status === 'Denied' && (x.f.reasons_given || []).includes('unreasonable_restriction_or_prohibits_use') && x.f.evidence);
    const exSC = dec.find((x) => x.c.status === 'Denied' && x.f.self_created_raised && x.f.evidence);
    const tips = [];
    tips.push(tip('Lead with a condition of the land, not of the owner',
      'Strong applications point to something physical and specific to this lot: an odd shape or size, protected trees, water or wetlands, an existing house already over the line, a safety issue. Preferences and plans alone rarely carry the first two findings.',
      `Approved when a land-based reason was argued: ${rLand.txt}; otherwise ${rNoLand.txt}.`,
      exLand.length ? 'Examples: ' + exLand.map((x) => `${link(x)} (${esc(x.f.magnitude || RELIEF[x.f.relief] || '')})`).join(', ') : ''));
    tips.push(tip('Show why a compliant design isn\'t a reasonable option',
      'The most common reason for denial is that following the rule would not unreasonably restrict use of the property. Explain what a code-compliant alternative would mean in practice (a house too small to use, lost access, a tree removed) rather than why the variance is preferable.',
      `Cited in ${dec.filter((x) => x.c.status === 'Denied' && (x.f.reasons_given || []).includes('unreasonable_restriction_or_prohibits_use')).length} of ${dec.filter((x) => x.c.status === 'Denied').length} variance denials.`,
      exUR ? 'From the minutes: ' + quote(exUR) : ''));
    tips.push(tip('Make clear the problem isn\'t self-created',
      'Document what existed before you bought the lot or started work, and why the constraint isn\'t the result of your design choices. Building first and asking later, or designing larger than the lot allows, is usually fatal.',
      `When the board or staff called the hardship self-created: approved ${sc.txt} ${smallN(sc)}.`,
      exSC ? 'From the minutes: ' + quote(exSC) : ''));
    const apPct = compDec.filter(approvedV).map((x) => x.f.magnitude_pct).filter((v) => typeof v === 'number');
    const dnPct = compDec.filter((x) => x.c.status === 'Denied').map((x) => x.f.magnitude_pct).filter((v) => typeof v === 'number');
    if (apPct.length >= 3) {
      const maxAp = Math.max(...apPct);
      const your = userPct != null ? (userPct > maxAp ? ` Your request (${userPct}%) is larger than any approved comparable with a known size; consider whether it can be reduced.` : ` Your request (${userPct}%) is within the range of approved comparables.`) : '';
      tips.push(tip('Ask for as little as possible',
        `Among comparable cases with a known size, approved requests asked for a median of ${median(apPct)}% of the requirement (largest ${maxAp}%)${dnPct.length ? `; denied requests a median of ${median(dnPct)}%` : ''}.${your}`,
        `Sizes known for ${apPct.length} approved and ${dnPct.length} denied comparables ${smallN({ n: apPct.length + dnPct.length })}.`));
    }
    tips.push(tip('Talk to the neighbours before the hearing',
      'Recorded opposition is one of the clearest dividing lines. Share plans with adjoining owners early, address their concerns in the design, and bring written support if they give it.',
      `Approved with any recorded opposition: ${opp.txt}; with none recorded: ${noOpp.txt}.${near.length ? ` Within 500 ft of this lot, ${near.filter((x) => (x.f.public_opposition || 0) > 0).length} of ${near.length} past cases drew opposition.` : ''}`));
    tips.push(tip('Offer conditions and be ready to scale back',
      'Applicants who reduced the request, redesigned, or accepted conditions (tree mitigation, footprint limits, screening) were approved far more often. Go in with a fallback the board can say yes to.',
      `Approved when the applicant revised, reduced or accepted conditions: ${flex.txt}. (Partly reflects boards attaching conditions to approvals.)`));
    const specific = {
      tree_removal_or_protection: ['Bring an arborist\'s report', 'Tree requests split sharply on evidence of the tree\'s health or the risk it poses. A certified arborist\'s report, photos and a mitigation (replanting) offer are the norm in approvals.',
        (() => { const t = dec.filter((x) => x.f.relief === 'tree_removal_or_protection'); const s = (x) => (x.f.hardship || []).some((h) => h === 'safety' || h === 'trees'); return `Tree cases approved with a safety / tree-health argument: ${rate(t.filter(s), approvedV).txt}; without: ${rate(t.filter((x) => !s(x)), approvedV).txt}.`; })()],
      height: ['Tie height to the site', 'Flood elevation requirements, grade changes or matching existing neighbouring heights are the arguments that appear in approvals. Provide elevations showing the comparison.', ''],
      lot_coverage_or_bar: ['Expect a hard case', 'Coverage and building-area-ratio requests are among the least often approved. Show the lot is unusually small or shaped, and consider reducing the footprint before applying.', ''],
      dock_or_marsh: ['Coordinate with state permits', 'Dock and marsh requests are rarely approved by the Board. Check state (SCDES / OCRM) permitting first and show why the standard dock location or length can\'t work.', ''],
      accessory_structure: ['Explain the size and placement', 'Pools, garages and sheds near lot lines are judged on detriment to neighbours. Show screening, drainage and why the location is the only practical one.', ''],
    };
    const sp = specific[relief] || (SETBACKS.includes(relief) ? ['Bring a survey that shows the constraint', 'A current survey showing the lot\'s shape, the existing structure and the exact encroachment lets the board see the condition is the land\'s. Approvals often involve a house already over the line or an angled lot.', ''] : null);
    if (sp) tips.push(tip(sp[0], sp[1], sp[2]));
    const denReasons = {};
    compDec.filter((x) => x.c.status === 'Denied').forEach((x) => (x.f.reasons_given || []).forEach((r) => { if (REASON[r]) denReasons[r] = (denReasons[r] || 0) + 1; }));
    const topR = Object.entries(denReasons).sort((a, b) => b[1] - a[1]).slice(0, 3);
    if (topR.length) tips.push(tip('Pre-empt the reasons comparable requests were denied',
      'Address these head-on in your narrative:', topR.map(([r, n]) => `${esc(REASON[r])} (${n})`).join(' · ')));
    return tips.join('');
  }

  function rezoningTips(R, z, near) {
    const dec = R.filter(decidedR);
    const cpYes = rate(dec.filter((x) => x.f.comp_plan === 'consistent'), adoptedR), cpNo = rate(dec.filter((x) => x.f.comp_plan === 'inconsistent'), adoptedR);
    const opp = rate(dec.filter((x) => (x.f.public_opposition || 0) > 0), adoptedR), noOpp = rate(dec.filter((x) => x.f.public_opposition === 0), adoptedR);
    const den = {};
    dec.filter((x) => !adoptedR(x)).forEach((x) => (x.f.reasons_given || []).forEach((r) => { if (REASON[r]) den[r] = (den[r] || 0) + 1; }));
    const topR = Object.entries(den).sort((a, b) => b[1] - a[1]).slice(0, 4);
    return [
      tip('Start from the Comprehensive Plan', `Show how the requested district fits the plan's designation for this lot (<b>${esc(z.flu || 'unknown')}</b>). If it doesn't, expect that to be the central objection.`,
        `Adopted when described as consistent with the plan: ${cpYes.txt}; inconsistent: ${cpNo.txt} ${smallN(cpNo)}.`),
      tip('Treat the Planning Committee as the decisive audience', 'Council follows the Planning Committee of Council far more often than the Planning Commission when the two disagree. Brief committee members on how the request fits the surrounding area.',
        (() => {
          const rec = (x, re) => (x.c.events || []).some((e) => e.body === 'Planning Committee' && re.test(e.decision));
          const yes = rate(dec.filter((x) => rec(x, /recommended approval/i)), adoptedR), no = rate(dec.filter((x) => rec(x, /recommended denial/i)), adoptedR);
          return `Adopted when the Committee recommended approval: ${yes.txt}; when it recommended denial: ${no.txt} ${smallN(no)}.`;
        })()),
      tip('Answer neighbourhood character and traffic in writing', 'Denied rezonings most often cited the character of the surrounding area. Show the existing uses around the lot and why the change fits them.',
        topR.length ? 'Reasons stated in denials: ' + topR.map(([r, n]) => `${esc(REASON[r])} (${n})`).join(' · ') : ''),
      tip('Bring neighbours along', 'Opposition at the hearings lowers the odds noticeably; support from adjoining owners helps make the case that the change fits.',
        `Adopted with recorded opposition: ${opp.txt}; without: ${noOpp.txt}.${near.length ? ` ${near.length} zoning cases are recorded within 500 ft of this lot.` : ''}`),
      tip('Check whether a narrower request would do', 'If the real issue is a setback, height or lot size rather than the use itself, a variance may be the simpler path.', ''),
    ].join('');
  }

  // ---------- run ----------
  async function run(e) {
    e.preventDefault();
    const addr = $('addr').value.trim(), relief = $('relief').value;
    if (!addr || !relief) return;
    const ask = parseFloat($('sizeAsk').value), req = parseFloat($('sizeReq').value);
    const userPct = $('sizeUnit').value === '%' && ask ? ask : (ask && req ? Math.round(100 * ask / req) : null);
    $('out').innerHTML = '<div class="loading">Looking up the lot and comparing past cases…</div>';
    $('go').disabled = true;
    track('plan/submit', 'Plan: ' + relief);
    try {
      const [rows, std] = await Promise.all([loadCases(), loadCode()]);
      const lot = await findLot(addr, rows);
      if (!lot) {
        $('out').innerHTML = '<div class="card block"><h2>Address not found</h2><p>Try the street number and name only (e.g. "100 Ann Edwards Lane"), or enter the parcel number (TMS, e.g. 532-01-00-147). Only Mount Pleasant properties can be looked up.</p></div>';
        return;
      }
      const [z, sales] = await Promise.all([zoningOf(lot), salesNear(lot).catch(() => null)]);
      const here = rows.filter((x) => lot.tms && x.p.tms === lot.tms);
      const near = rows.filter((x) => x.p.lat && distM(lot, x.p) <= 152 && !(lot.tms && x.p.tms === lot.tms));
      const isUse = relief === 'use';
      const V = rows.filter(isVariance), R = rows.filter(isRezoning);
      const stats = {
        cpYes: rate(R.filter(decidedR).filter((x) => x.f.comp_plan === 'consistent'), adoptedR),
        cpNo: rate(R.filter(decidedR).filter((x) => x.f.comp_plan === 'inconsistent'), adoptedR),
      };
      let pool;
      const notHere = (x) => !(lot.tms && x.p.tms === lot.tms);
      if (isUse || relief === 'lot_size_density_subdivision') pool = R.filter((x) => x.p.lat && notHere(x));
      else pool = V.filter((x) => notHere(x) && (x.f.relief === relief || (SETBACKS.includes(relief) && SETBACKS.includes(x.f.relief))));
      const comps = isUse || relief === 'lot_size_density_subdivision'
        ? pool.map((x) => ({ ...x, dist: distM(lot, x.p), score: 0 })).sort((a, b) => a.dist - b.dist)
        : pickComparables(pool, lot, z, relief, userPct);
      $('out').innerHTML = lotSection(lot, z, here, near) + salesSection(sales) + codeSection(lot, z, relief, { ask, req, unit: $('sizeUnit').value }, std) + pathSection(relief, z, stats) + compSection(comps, relief, isUse || relief === 'lot_size_density_subdivision') +
        `<section class="card block"><h2>How to strengthen your application</h2>
          <p class="muted">Patterns from past cases, with how many cases each rests on. Not a prediction.</p>
          <ol class="tips">${isUse || relief === 'lot_size_density_subdivision' ? rezoningTips(R, z, near) : varianceTips(V, comps, relief, userPct, near)}</ol>
          
        </section>`;
      $('out').scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (err) {
      $('out').innerHTML = `<div class="card block"><h2>Something went wrong</h2><p>${esc(err.message)}. The county or Town map service may be busy; try again in a minute.</p></div>`;
    } finally {
      $('go').disabled = false;
    }
  }
  $('planForm').addEventListener('submit', run);
  const qs = new URLSearchParams(location.search);
  if (qs.get('address')) $('addr').value = qs.get('address');
  track('plan/open', 'Opened Plan a request');
})();
