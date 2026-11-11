// One shared navigation bar and footer for every page. Plain DOM, no dependencies.
(function () {
  const PAGES = [
    ["2050.html", "Your 2050"],
    ["engine3d.html", "Engine"],
    ["index.html", "Policy demo"],
    ["scoreboard.html", "Scoreboard"],
    ["datacenter.html", "Data centers"],
    ["switches.html", "Switches"],
    ["index.html?how", "How it works"],
    ["about.html", "About"],
  ];
  const here = (location.pathname.split("/").pop() || "2050.html").toLowerCase();
  const css = document.createElement("style");
  css.textContent = `
.site-nav{position:sticky;top:0;z-index:50;display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding:8px 16px;
  background:#0d1015;border-bottom:1px solid #2c2c2a;font:14px system-ui,-apple-system,"Segoe UI",sans-serif}
.site-nav b{color:#e8e6df;font-weight:600;margin-right:10px}
.site-nav a{color:#a9a79f;text-decoration:none;padding:5px 9px;border-radius:6px;white-space:nowrap}
.site-nav a:hover{color:#e8e6df}.site-nav a[aria-current="page"]{color:#04342C;background:#5DCAA5}
.site-foot{padding:14px 16px 28px;font:12px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;color:#8a8880;text-align:center}
.site-foot a{color:inherit;text-decoration:underline}
body.fixed-page .site-nav{position:fixed;left:0;right:0}
body.fixed-page:not(.flat) .site-foot{display:none}
@media(max-width:640px){.site-nav{gap:2px;padding:6px 10px;overflow-x:auto;flex-wrap:nowrap}.site-nav b{display:none}}`;
  document.head.appendChild(css);
  const nav = document.createElement("nav");
  nav.className = "site-nav";
  nav.setAttribute("aria-label", "Site");
  nav.innerHTML = '<b>NEMS Open</b>' + PAGES.map(([h, t]) =>
    `<a href="${h}"${h.split("#")[0] === here && !h.includes("#") ? ' aria-current="page"' : ""}>${t}</a>`).join("");
  document.body.insertBefore(nav, document.body.firstChild);
  const foot = document.createElement("footer");
  foot.className = "site-foot";
  foot.innerHTML = 'Built on data and code from the U.S. Energy Information Administration (EIA): the National Energy Modeling System and the Annual Energy Outlook 2026. ' +
    'NEMS Open is an independent project. It is not affiliated with, reviewed by or endorsed by EIA. <a href="about.html">About and credits</a>.';
  document.body.appendChild(foot);
  if (/[?&]how/.test(location.search)) addEventListener("load", () => setTimeout(() => { const h = document.getElementById("how"); if (h) h.scrollIntoView({ block: "start" }); }, 600));
})();
