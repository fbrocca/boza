/* Render the brand mark (icons/favicon.svg) to PNG icons and the social preview image.
   One-off: run when the mark changes, then commit icons/.
     node tools/make_icons.js && python3 tools/make_favicon.py */
const { chromium } = require('playwright');
const fs = require('fs'); const path = require('path');
const dir = path.join(__dirname, '..', 'icons');
const svg = fs.readFileSync(path.join(dir, 'favicon.svg'), 'utf8');
// Home-screen icons: the mark with a margin, so the rounded corners phones apply don't clip it.
const padded = (s) => `<html><body style="margin:0;background:#f5f2ea"><div style="width:${s}px;height:${s}px;display:grid;place-items:center"><div style="width:${s * 0.72}px;height:${s * 0.72}px">${svg.replace('<svg ', '<svg width="100%" height="100%" ')}</div></div></body></html>`;
const og = `<html><head><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,500;6..72,600&family=IBM+Plex+Mono:wght@500&family=Public+Sans:wght@500&display=swap"></head>
<body style="margin:0;width:1200px;height:630px;background:#f5f2ea;color:#191b18;font-family:Newsreader;box-sizing:border-box;padding:64px 80px;display:flex;flex-direction:column;justify-content:space-between;border-top:14px solid #191b18">
<div style="display:flex;align-items:center;gap:22px"><div style="width:76px;height:76px">${svg.replace('<svg ', '<svg width="100%" height="100%" ')}</div>
<div style="font:600 46px Newsreader;letter-spacing:-.01em">The Zoning Record <span style="font:500 18px 'Public Sans';letter-spacing:.12em;color:#74776f;margin-left:12px;vertical-align:middle">MOUNT PLEASANT</span></div></div>
<div style="font:500 76px/1.04 Newsreader;letter-spacing:-.025em;max-width:980px">Every zoning decision in Mount Pleasant, in one place.</div>
<div style="font:500 20px 'IBM Plex Mono';letter-spacing:.06em;color:#2e5b3f;border-top:1px solid #d6cfbd;padding-top:22px">VARIANCES · REZONINGS · HISTORIC AND DESIGN REVIEWS · FROM THE TOWN'S MINUTES</div></body></html>`;
(async () => {
  const b = await chromium.launch(); const p = await b.newPage();
  for (const [name, s] of [['apple-touch-icon.png', 180], ['icon-512.png', 512]]) {
    await p.setViewportSize({ width: s, height: s }); await p.setContent(padded(s)); await p.screenshot({ path: path.join(dir, name) });
  }
  await p.setViewportSize({ width: 1200, height: 630 }); await p.setContent(og); await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(500);
  await p.screenshot({ path: path.join(dir, 'og.png') });
  await b.close();
})();
