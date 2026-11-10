/* Shared by the map and the neighborhood pages: "Report an error", "Add to calendar",
 * and "How to comment". No backend: error reports are recorded as private GoatCounter
 * events (only the site owner sees them); calendar files are built in the browser.
 */
(function () {
  'use strict';
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const LOCATION = 'Town Hall, 100 Ann Edwards Lane, Mount Pleasant, SC 29464';
  const gcReady = () => !!(window.goatcounter && typeof window.goatcounter.count === 'function');
  const track = (path, title) => { try { if (gcReady()) window.goatcounter.count({ path, title: title || path, event: true }); } catch (e) { /* optional */ } };

  // ---------- Report an error ----------
  let dlg;
  function reportDialog() {
    if (dlg) return dlg;
    dlg = document.createElement('dialog');
    dlg.className = 'dialog card report-dlg';
    dlg.innerHTML = `
      <form method="dialog" class="dialog-close"><button class="btn btn-ghost btn-sm" aria-label="Close">✕</button></form>
      <div class="rep-ask">
        <h2>Report an error</h2>
        <p class="muted small rep-about"></p>
        <form class="dialog-form rep-form">
          <label class="label" for="repWhat">What's wrong?</label>
          <select class="input" id="repWhat">
            <option>Wrong outcome</option><option>Wrong address or location</option><option>Case mixed up with another</option>
            <option>Missing case or document</option><option>Wrong neighborhood</option><option>Something else</option>
          </select>
          <label class="label" for="repText">Details <span class="muted">(what it should say, and how you know)</span></label>
          <textarea class="input" id="repText" rows="4" maxlength="600" required placeholder="e.g. The minutes of Oct 26 say this was deferred, not denied."></textarea>
          <p class="hint">Please don't include names, phone numbers or emails. Reports are stored privately and used only to fix the map.</p>
          <button class="btn btn-primary" type="submit">Send report</button>
        </form>
      </div>
      <div class="rep-done" hidden><h2>Thank you</h2><p>Your report was recorded. Corrections usually appear within a few days.</p>
        <form method="dialog"><button class="btn btn-primary" style="width:100%">Close</button></form></div>
      <div class="rep-blocked" hidden><h2>Report not sent</h2><p>Your browser blocked it, usually because of an ad or tracker blocker. Please try again with it paused for this site, or from another browser.</p>
        <form method="dialog"><button class="btn btn-outline" style="width:100%">Close</button></form></div>`;
    document.body.appendChild(dlg);
    dlg.querySelector('.rep-form').addEventListener('submit', (e) => {
      e.preventDefault();
      const ctx = dlg._ctx || {};
      const text = `${dlg.querySelector('#repWhat').value}: ${dlg.querySelector('#repText').value.trim()}`.slice(0, 700);
      const ok = gcReady();
      if (ok) track(`report/${ctx.id || 'page'}`, `${ctx.label || ''} | ${text} | ${location.pathname}${location.hash}`);
      dlg.querySelector('.rep-ask').hidden = true;
      dlg.querySelector(ok ? '.rep-done' : '.rep-blocked').hidden = false;
    });
    return dlg;
  }
  function reportError(ctx) {
    const d = reportDialog();
    d._ctx = ctx;
    d.querySelector('.rep-about').textContent = ctx.label ? `About: ${ctx.label}` : '';
    d.querySelector('.rep-ask').hidden = false;
    d.querySelector('.rep-done').hidden = true;
    d.querySelector('.rep-blocked').hidden = true;
    d.querySelector('#repText').value = '';
    d.showModal();
    track('report/open', 'Opened error report');
  }
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-report]');
    if (b) { e.preventDefault(); reportError({ id: b.dataset.report, label: b.dataset.reportLabel }); }
  });

  // ---------- Add to calendar ----------
  function startOf(m) {
    const t = (m.time || '').match(/(\d{1,2}):(\d{2})\s*([ap])/i);
    if (!t) return null;
    let h = +t[1] % 12; if (/p/i.test(t[3])) h += 12;
    return { h, min: +t[2] };
  }
  const pad = (n) => String(n).padStart(2, '0');
  function calTimes(m) {
    const d = m.date.replace(/-/g, '');
    const s = startOf(m);
    if (!s) { // all-day
      const n = new Date(m.date + 'T12:00:00'); n.setDate(n.getDate() + 1);
      return { allDay: true, start: d, end: `${n.getFullYear()}${pad(n.getMonth() + 1)}${pad(n.getDate())}` };
    }
    const eh = s.h + 2; // agendas don't give an end time; block two hours
    return { allDay: false, start: `${d}T${pad(s.h)}${pad(s.min)}00`, end: `${d}T${pad(eh)}${pad(s.min)}00` };
  }
  function calText(m, items) {
    const list = (items || m.items).slice(0, 12).map((it) => `- ${it.title}${it.request ? ': ' + it.request : ''}`).join('\n');
    const how = m.deadline ? `Written comments by ${m.deadline}${m.email ? ' to ' + m.email : ''}.` : '';
    return `${list}\n\n${how}\nAgenda: ${m.agenda}\nFrom the Mount Pleasant Zoning Map: ${location.origin}${location.pathname.replace(/[^/]*$/, '')}`;
  }
  function googleCal(m, items) {
    const t = calTimes(m);
    const q = new URLSearchParams({ action: 'TEMPLATE', text: `${m.label} meeting`, dates: `${t.start}/${t.end}`,
      details: calText(m, items), location: LOCATION, ctz: 'America/New_York' });
    return 'https://calendar.google.com/calendar/render?' + q.toString();
  }
  function icsFile(m, items) {
    const t = calTimes(m);
    const e = (s) => s.replace(/\\/g, '\\\\').replace(/\n/g, '\\n').replace(/[,;]/g, (c) => '\\' + c);
    const when = t.allDay ? `DTSTART;VALUE=DATE:${t.start}\r\nDTEND;VALUE=DATE:${t.end}`
      : `DTSTART;TZID=America/New_York:${t.start}\r\nDTEND;TZID=America/New_York:${t.end}`;
    const body = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Mount Pleasant Zoning Map//EN', 'BEGIN:VEVENT',
      `UID:${m.body}-${m.date}@mp-zoning-map`, `DTSTAMP:${new Date().toISOString().replace(/[-:]/g, '').slice(0, 15)}Z`, when,
      `SUMMARY:${e(m.label + ' meeting')}`, `LOCATION:${e(LOCATION)}`, `DESCRIPTION:${e(calText(m, items))}`, `URL:${m.agenda}`,
      'END:VEVENT', 'END:VCALENDAR'].join('\r\n');
    return URL.createObjectURL(new Blob([body], { type: 'text/calendar' }));
  }

  // ---------- How to comment ----------
  function commentMailto(m, it) {
    const subject = `Comment on ${it ? it.title.slice(0, 80) : 'agenda'}: ${m.label}, ${m.date}`;
    return `mailto:${m.email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(
      `To the ${m.label},\n\nRegarding ${it ? it.title + (it.address ? ' (' + it.address + ')' : '') : 'the ' + m.date + ' agenda'}:\n\n[Your comment]\n\nName:\nAddress:\n`)}`;
  }
  /* The block shown under each meeting: calendar and comment options, from what the agenda states. */
  function meetingActions(m, items) {
    const id = `${m.body}-${m.date}`;
    const how = [];
    if (m.deadline) how.push(`<li><b>In writing</b> by ${esc(m.deadline)}${m.email ? ` to <a href="${esc(commentMailto(m, items && items.length === 1 ? items[0] : null))}" data-track="upcoming/comment-email">${esc(m.email)}</a> (opens a pre-filled email)` : ': see the agenda for where to send it'}.</li>`);
    if (m.public_comment) how.push(`<li><b>In person</b> at the meeting${m.time ? ` (${esc(m.time)})` : ''}, ${esc(LOCATION.replace(', Mount Pleasant, SC 29464', ''))}, during public comment.</li>`);
    how.push(`<li><b>Read first:</b> the <a href="${esc(m.agenda)}" target="_blank" rel="noopener" data-track="upcoming/agenda">agenda</a>; blue text in it links to applications and staff reports.</li>`);
    return `<div class="up-actions">
      <details class="up-cal"><summary class="btn btn-outline btn-sm" data-track-summary="upcoming/calendar-open">Add to calendar</summary>
        <div class="up-pop">
          <a href="${esc(googleCal(m, items))}" target="_blank" rel="noopener" data-track="upcoming/calendar-google">Google Calendar</a>
          <a href="${icsFile(m, items)}" download="${esc(id)}.ics" data-track="upcoming/calendar-ics">Apple / Outlook (.ics)</a>
        </div></details>
      <details class="up-how"><summary class="btn btn-outline btn-sm" data-track-summary="upcoming/comment-open">How to comment</summary>
        <ul class="up-pop">${how.join('')}</ul></details>
    </div>`;
  }
  document.addEventListener('toggle', (e) => {
    const s = e.target.querySelector && e.target.open && e.target.querySelector(':scope > summary[data-track-summary]');
    if (s) track(s.dataset.trackSummary, s.textContent.trim());
  }, true);
  document.addEventListener('click', (e) => {
    const a = e.target.closest('a[data-track]');
    if (a) track(a.dataset.track, a.textContent.trim());
  });

  window.MPShared = { reportError, meetingActions, track, esc };
})();
