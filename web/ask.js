// Ask the model (ask.html): a question goes to POST api/ask, which runs the policy agent. Two places serve it: the
// local server (scripts/serve_2050.py, ANTHROPIC_API_KEY set) and the hosted function (site/api/ask.py, with per-visitor
// and daily limits). api/health says which ("hosted": true) and whether it can answer now.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const EXAMPLES = [
    "What does a $50 carbon price do to US energy CO2 in 2040?",
    "How much less petroleum would transportation use in 2040 if 90% of new cars are EVs by 2035?",
    "If data centers add 600 TWh a year by 2050, what happens to electricity prices?",
    "What does a $100 carbon price do to a household's energy bill in 2040?",
  ];
  const ASK_TIMEOUT_MS = 75000;
  const S = { checked: false, server: false, key: false, hosted: false, asking: false };

  function paint() {
    const note = $("ask-note"), off = !S.checked || !S.server || !S.key;
    $("ask-q").disabled = off || S.asking; $("ask-go").disabled = off || S.asking;
    for (const b of document.querySelectorAll("#ask-ex button")) b.disabled = off || S.asking;
    if (!S.checked) note.textContent = "";
    else if (S.hosted && !S.key) note.textContent = "Questions are switched off on this copy of the site right now. The levers in Your 2050 still work.";
    else if (!S.server) note.innerHTML = "Asking needs the model running on your own computer: <code>python scripts/serve_2050.py</code> with ANTHROPIC_API_KEY set, then open this page from it. This copy of the site cannot answer questions.";
    else if (!S.key) note.innerHTML = "The local server has no ANTHROPIC_API_KEY, so it cannot answer. Set it and restart <code>python scripts/serve_2050.py</code>.";
    else if (!S.asking) note.textContent = "Answers use only numbers the model produced, each with where it came from. Policies start in 2027 and cover the whole US.";
  }
  // Model text made safe first (escaped), then **bold**, lists and paragraphs, then [n] marks as links.
  function md(text) {
    const inline = (s) => esc(s).replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>").replace(/\[(\d+)\]/g, '<sup><a href="#src-$1">[$1]</a></sup>');
    return String(text).split(/\n{2,}/).map((blk) => {
      const lines = blk.split("\n");
      if (lines.every((l) => /^\s*[-*]\s+/.test(l))) return "<ul>" + lines.map((l) => `<li>${inline(l.replace(/^\s*[-*]\s+/, ""))}</li>`).join("") + "</ul>";
      if (lines.every((l) => /^\s*\d+[.)]\s+/.test(l))) return "<ol>" + lines.map((l) => `<li>${inline(l.replace(/^\s*\d+[.)]\s+/, ""))}</li>`).join("") + "</ol>";
      return `<p>${inline(blk.replace(/^#{1,6}\s+/, "")).replace(/\n/g, "<br>")}</p>`;
    }).join("");
  }
  const dot = (g, why) => (window.NEMSDot ? NEMSDot.dot(g === "setting" ? "data" : g, why) : "");
  function show(a) {
    const out = $("ask-out"); out.hidden = false;
    if (a.error && !a.body) { out.innerHTML = `<p class="err">${esc(a.message || "The server could not answer.")}</p>`; return; }
    let h = "";
    if (a.apply && Object.keys(a.apply).length) {
      const hash = Object.entries(a.apply).map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");
      h += `<p class="chip">The answer uses these settings. <a href="2050.html#${hash}">See them in Your 2050</a></p>`;
    }
    h += `<div class="body">${md(a.body)}`;
    if (a.outside && a.outside.length) h += `<p class="outside"><b>Not from the model:</b> ${a.outside.map(esc).join(" ")}</p>`;
    h += "</div>";
    if (a.sources && a.sources.length)
      h += `<details class="src"><summary>Where each number comes from (${a.sources.length})</summary><ul>${a.sources.map((s) =>
        `<li id="src-${s.markers[0]}">${dot(s.grade, s.grade_label)}<span>${esc(s.line)}</span></li>`).join("")}</ul></details>`;
    if (a.basis) h += `<p class="basis">${esc(a.basis)}</p>`;
    out.innerHTML = h;
    out.onclick = (e) => {   // a [n] mark opens the source list at that line
      const l = e.target.closest('a[href^="#src-"]'); if (!l) return;
      e.preventDefault(); const box = out.querySelector(".src"); if (box) box.open = true;
      const li = out.querySelector(l.getAttribute("href")); if (li) li.scrollIntoView({ block: "nearest" });
    };
  }
  async function ask(q) {
    q = q.trim(); if (!q || S.asking) return;
    $("ask-q").value = q; S.asking = true; paint();
    const out = $("ask-out"), t0 = Date.now(); out.hidden = false;
    const tick = () => { out.innerHTML = `<p class="fine"><span class="spin"></span>Working on it: ${Math.round((Date.now() - t0) / 1000)} s. The model runs scenarios and checks every number, usually under a minute.</p>`; };
    tick(); const timer = setInterval(tick, 1000);
    const ctl = new AbortController(), to = setTimeout(() => ctl.abort(), ASK_TIMEOUT_MS);
    let a;
    try {
      const res = await fetch("api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q }), signal: ctl.signal });
      try { a = await res.json(); } catch (e) { a = { error: "bad_reply", message: "The server sent something the page could not read." }; }
      if (!res.ok) a = { error: a.error || "failed", message: a.message || "The server could not answer." };
    } catch (e) {
      a = { error: "network", message: e.name === "AbortError" ? "That took too long, so the page stopped waiting. Try a simpler question." : S.hosted ? "The site did not respond. Try again in a minute." : "The local server did not respond. Is scripts/serve_2050.py still running?" };
    }
    clearTimeout(to); clearInterval(timer); S.asking = false;
    show(a); paint();
  }
  async function check() {
    try {
      const h = await Promise.race([fetch("api/health", { cache: "no-store" }), new Promise((_, no) => setTimeout(() => no(new Error("timeout")), 2500))]);
      const j = await h.json();
      S.server = h.ok && j.ok === true; S.key = S.server && j.ask === true; S.hosted = S.server && j.hosted === true;
    } catch (e) { S.server = false; S.key = false; }
    S.checked = true; paint();
  }
  addEventListener("DOMContentLoaded", () => {
    $("ask-ex").innerHTML = EXAMPLES.map((q) => `<button type="button">${esc(q)}</button>`).join("");
    $("ask-ex").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) ask(b.textContent); });
    $("ask-form").addEventListener("submit", (e) => { e.preventDefault(); ask($("ask-q").value); });
    const q = new URLSearchParams(location.search).get("q");
    if (q) $("ask-q").value = q;
    $("legend").innerHTML = window.NEMSDot ? NEMSDot.legend() : "";
    paint(); check();
  });
})();
