// One shared navigation bar, footer and grade dot for every page. Plain DOM, no dependencies.
(function () {
  // Three places for everyone; the rest lives under "For experts" (experts.html).
  const PAGES = [["2050.html", "Your 2050"], ["think.html", "Watch it think"], ["ask.html", "Ask"], ["how.html", "How it's built"]];
  const EXPERT = ["experts.html", "engine3d.html", "index.html", "scoreboard.html", "datacenter.html", "switches.html", "about.html"];
  const here = (location.pathname.split("/").pop() || "2050.html").toLowerCase().replace(/\.html$/, "") + ".html";
  const css = document.createElement("style");
  css.textContent = `
.site-nav{position:sticky;top:0;z-index:50;display:flex;align-items:center;gap:6px;padding:8px 16px;
  background:#0d1015;border-bottom:1px solid #2c2c2a;font:14px system-ui,-apple-system,"Segoe UI",sans-serif}
.site-nav b{color:#e8e6df;font-weight:600;margin-right:10px}
.site-nav a{color:#a9a79f;text-decoration:none;padding:5px 10px;border-radius:6px;white-space:nowrap}
.site-nav a:hover{color:#e8e6df}.site-nav a[aria-current="page"]{color:#04342C;background:#5DCAA5}
.site-nav .x{margin-left:auto;font-size:13px}
.site-foot{padding:14px 16px 28px;font:12px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;color:#8a8880;text-align:center}
.site-foot a{color:inherit;text-decoration:underline}
body.fixed-page .site-nav{position:fixed;left:0;right:0}
body.fixed-page:not(.flat) .site-foot{display:none}
/* the grade dot: green EIA's own code, amber our estimate, grey EIA's published number */
.gd{display:inline-block;width:9px;height:9px;border-radius:50%;vertical-align:1px;margin-left:5px;cursor:help;flex:none}
.gd.match{background:#4FE3B0}.gd.stand{background:#E8A33D}.gd.data{background:#9a978f}
.gd-legend{display:flex;flex-wrap:wrap;gap:4px 14px;font:12px system-ui,-apple-system,"Segoe UI",sans-serif;color:#a9a79f;align-items:center}
.gd-legend .gd{margin:0 5px 0 0}
.gd-tip{position:absolute;z-index:90;background:#0f1419;color:#e8e6df;border:1px solid #3a4351;border-radius:8px;padding:8px 10px;font:12.5px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;box-shadow:0 10px 30px rgba(0,0,0,.5)}
@media(max-width:640px){.site-nav{gap:2px;padding:6px 10px;overflow-x:auto}.site-nav b{display:none}.site-nav a{padding:11px 8px}}`;
  document.head.appendChild(css);
  const nav = document.createElement("nav");
  nav.className = "site-nav";
  nav.setAttribute("aria-label", "Site");
  nav.innerHTML = '<b>NEMS Open</b>' + PAGES.map(([h, t]) => `<a href="${h}"${h === here ? ' aria-current="page"' : ""}>${t}</a>`).join("") +
    `<a class="x" href="experts.html"${EXPERT.includes(here) ? ' aria-current="page"' : ""}>For experts</a>`;
  document.body.insertBefore(nav, document.body.firstChild);
  const foot = document.createElement("footer");
  foot.className = "site-foot";
  foot.innerHTML = 'Built on data and code from the U.S. Energy Information Administration (EIA): the National Energy Modeling System and the Annual Energy Outlook 2026. ' +
    'NEMS Open is an independent project. It is not affiliated with, reviewed by or endorsed by EIA. <a href="about.html">About and credits</a>.';
  document.body.appendChild(foot);
  if (/[?&]how/.test(location.search)) addEventListener("load", () => setTimeout(() => { const h = document.getElementById("how"); if (h) h.scrollIntoView({ block: "start" }); }, 600));

  // Grade dot. kind: "match" (ported from EIA's code and checked against it), anything fitted or our own
  // ("within", "stand") is our estimate, "data"/"reference" is EIA's published number. why goes on hover.
  const WORDS = { match: "EIA's own code, ported and checked against EIA's", stand: "Our estimate (a stand-in fitted to EIA's runs)", data: "EIA's published number" };
  const norm = (g) => (g === "match" ? "match" : g === "data" || g === "reference" || g === "fixed" ? "data" : "stand");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  window.NEMSDot = {
    dot: (grade, why) => { const k = norm(grade); return `<span class="gd ${k}" role="img" aria-label="${esc(WORDS[k])}" title="${esc(WORDS[k] + (why ? ". " + why : ""))}"></span>`; },
    legend: () => `<div class="gd-legend"><span><span class="gd match"></span>EIA's own code</span><span><span class="gd stand"></span>Our estimate</span><span><span class="gd data"></span>EIA's published number</span><span>Hover or tap a dot for the detail.</span></div>`,
  };
  // The part behind an engine piece in a run, from fidelity.json's registry (src/nems_open/ports.json): its port when
  // the run ported it and the port is graded, our own model when the run used the LP, else the stand-in. A module that
  // lands later flips here from data alone: no page names a port.
  const FALLBACK = { residential: "stand:demand_stub", commercial: "stand:demand_stub", industrial: "stand:demand_stub",
    transportation: "stand:demand_stub", electricity: "stand:electricity", "electricity:price": "stand:electricity",
    natural_gas: "stand:natural_gas", oil: "stand:oil", coal: "stand:coal", emissions: "stand:emissions" };
  window.NEMSGrade = {
    part: (fid, module, ported, elec) => {
      const r = fid && fid.registry && fid.registry[module];
      if (!r) return FALLBACK[module] || "stand:demand_stub";
      const on = (ported || []).some((p) => p === module || `port:${p}` === r.port);
      if (r.port && on && fid.parts[r.port]) return r.port;
      if (r.own && elec === "lp" && fid.parts[r.own]) return r.own;
      return r.fallback;
    },
  };
  // Touch screens have no hover: a tap on a dot shows its detail in a small card; a tap elsewhere closes it.
  let tip = null;
  document.addEventListener("click", (e) => {
    const d = e.target.closest && e.target.closest(".gd[title]");
    if (tip) { tip.remove(); tip = null; }
    if (!d) return;
    e.stopPropagation();
    const r = d.getBoundingClientRect();
    tip = document.createElement("div"); tip.className = "gd-tip"; tip.textContent = d.getAttribute("title");
    document.body.appendChild(tip);
    const w = Math.min(300, innerWidth - 20);
    tip.style.width = `${w}px`;
    tip.style.left = `${Math.max(10, Math.min(innerWidth - w - 10, r.left + scrollX - w / 2))}px`;
    tip.style.top = `${r.bottom + scrollY + 8}px`;
  }, true);
})();
