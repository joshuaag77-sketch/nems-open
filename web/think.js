// "Watch the model think": the convergence loop of run_model.run, replayed beat by beat from recorded passes.
// Data: data/think/manifest.json, meta.json and one file per scenario (scripts/think_runs.py); grades from
// data/fidelity.json. Every number shown is one the model handed between modules at that step. Values change
// by rolling from one recorded number to the next, never through numbers the model did not produce. Particle
// density shows how big a step's change was (log scale) and carries no number of its own.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fmt = (v, d = 0) => Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ---- modules, layout, edges ---------------------------------------------------------------------
  const DEMAND = ["residential", "commercial", "industrial", "transportation"];
  const SUPPLY = ["electricity", "natural_gas", "coal", "oil"];
  const MODS = {
    residential: { name: "Homes", key: "qtsrs" }, commercial: { name: "Businesses", key: "qtscm" },
    industrial: { name: "Industry", key: "qtsin" }, transportation: { name: "Vehicles", key: "qtstr" },
    electricity: { name: "Electricity", key: "pelrs", what: "power price paid by homes" },
    natural_gas: { name: "Natural gas", key: "pngrs", what: "gas price paid by homes" },
    coal: { name: "Coal", key: "pclel", what: "coal price at power plants" },
    oil: { name: "Oil and refining", key: "pmgtr", what: "gasoline price" },
  };
  // Demand on one side, supply on the other; quantities travel on one trunk, prices come back on another.
  const LAYOUTS = {
    wide: { flow: "h", demand: { xs: [0.2, 0.2, 0.2, 0.2], ys: [0.17, 0.39, 0.61, 0.83], side: "left" },
      supply: { xs: [0.8, 0.8, 0.8, 0.8], ys: [0.17, 0.39, 0.61, 0.83], side: "right" },
      q: [[0.38, 0.35], [0.62, 0.35]], p: [[0.62, 0.65], [0.38, 0.65]], bulge: [-1, 0] },
    tall: { flow: "v", demand: { xs: [0.13, 0.38, 0.62, 0.87], ys: [0.21, 0.21, 0.21, 0.21], side: "above" },
      supply: { xs: [0.13, 0.38, 0.62, 0.87], ys: [0.52, 0.52, 0.52, 0.52], side: "below" },
      q: [[0.43, 0.32], [0.43, 0.43]], p: [[0.57, 0.43], [0.57, 0.32]], bulge: [0, -1] },
  };
  // [from, to, recorded key, "q" quantity or "p" price]
  const EDGES = [
    ["residential", "electricity", "qelrs", "q"], ["residential", "natural_gas", "qngrs", "q"], ["residential", "oil", "qtprs", "q"],
    ["commercial", "electricity", "qelcm", "q"], ["commercial", "natural_gas", "qngcm", "q"], ["commercial", "oil", "qtpcm", "q"],
    ["industrial", "electricity", "qelin", "q"], ["industrial", "natural_gas", "qngin", "q"], ["industrial", "oil", "qtpin", "q"],
    ["transportation", "electricity", "qeltr", "q"], ["transportation", "oil", "qmgtr", "q"],
    ["electricity", "residential", "pelrs", "p"], ["electricity", "commercial", "pelcm", "p"], ["electricity", "industrial", "pelin", "p"], ["electricity", "transportation", "peltr", "p"],
    ["natural_gas", "residential", "pngrs", "p"], ["natural_gas", "commercial", "pngcm", "p"], ["natural_gas", "industrial", "pngin", "p"],
    ["oil", "residential", "ptprs", "p"], ["oil", "commercial", "ptpcm", "p"], ["oil", "industrial", "ptpin", "p"], ["oil", "transportation", "pmgtr", "p"],
    // inside supply: power plants burn gas, coal and oil, and pay for them
    ["electricity", "natural_gas", "qngel", "qi"], ["electricity", "coal", "qclel", "qi"], ["electricity", "oil", "qtpel", "qi"],
    ["natural_gas", "electricity", "pngel", "pi"], ["coal", "electricity", "pclel", "pi"],
  ];
  const COL = { q: [87, 199, 255], p: [255, 181, 71] };
  const colOf = (t) => COL[t[0]];
  const SHORT = { carbon_price: (v) => `Carbon $${v}/t`, ev_2035: (v) => `EVs ${Math.round(v * 100)}% of new cars`, load_growth: (v) => `+${fmt(v)} TWh of load`,
    building_code: (v) => `Codes ${Math.round(v * 100)}% tighter`, appliance_standard: (v) => `Appliances ${Math.round(v * 100)}% better`,
    coal_retirement: (v) => `${Math.round(v * 100)}% of coal closed`, renewable_cost: (v) => (v < 0 ? "Cheap wind and solar" : "Pricey wind and solar"),
    gas_supply: (v) => (v > 0 ? "Plentiful gas" : "Scarce gas"), oil_price: (v) => `Oil at ${v}x`, nuclear: (v) => `Nuclear at ${v}x` };

  // ---- state --------------------------------------------------------------------------------------
  const S = { meta: null, man: null, fid: null, sc: null, cache: {}, year: 2035, beats: [], pos: 0, playing: false, lapse: false, token: 0 };
  const idx = (k) => S.meta.keys.indexOf(k);
  const eiaAt = (k, y) => S.meta.eia[k][y - S.meta.years[0]];
  const carbon = () => (S.sc && S.sc.levers && S.sc.levers.carbon_price) || 0;
  const isPrice = (k) => S.meta.vars[k].kind === "p";
  const carbonNote = (k) => (carbon() && isPrice(k) ? `incl. $${carbon()}/t carbon` : "");

  // ---- grades -------------------------------------------------------------------------------------
  const RANK = { match: 3, within: 2, stand: 1 };
  function modGrade(m) {
    const ported = (S.sc && S.sc.ported) || [];
    const part = ["residential", "commercial", "transportation"].includes(m) ? (ported.includes(m) ? `port:${m}` : "stand:demand_stub")
      : m === "industrial" ? "stand:demand_stub" : m === "emissions" ? "stand:emissions"
      : { electricity: "stand:electricity", natural_gas: "stand:natural_gas", oil: "stand:oil", coal: "stand:coal" }[m];
    const p = S.fid.parts[part];
    return { grade: p.grade, label: p.grade === "match" ? "matches EIA" : p.label, why: `${p.name}: ${p.summary}` };
  }
  function keyGrade(key) {
    const mods = key === "co2" ? [...DEMAND, ...SUPPLY, "emissions"] : [S.meta.vars[key].module];
    let w = null;
    for (const m of mods) { const g = modGrade(m); if (!w || RANK[g.grade] < RANK[w.grade]) w = g; }
    return w;
  }
  const badge = (g) => `<span class="g g-${g.grade}" title="${esc(g.why)}">${esc(g.label)}</span>`;

  // ---- geometry -----------------------------------------------------------------------------------
  const cv = $("cv"), ctx = cv.getContext("2d");
  const G = { w: 0, h: 0, dpr: 1, L: null, pos: {}, R: 22, paths: new Map(), trunks: {}, parts: [], heat: new Map(), nodeHeat: {}, rings: [] };
  function layout() {
    G.w = $("stage").clientWidth; G.h = $("stage").clientHeight; G.dpr = Math.min(2, window.devicePixelRatio || 1);
    if (!G.w || !G.h) return;
    cv.width = Math.round(G.w * G.dpr); cv.height = Math.round(G.h * G.dpr);
    G.L = LAYOUTS[G.w < 640 || G.h > G.w * 1.05 ? "tall" : "wide"];
    G.R = Math.max(13, Math.min(24, Math.min(G.w, G.h) * 0.04));
    DEMAND.forEach((m, i) => (G.pos[m] = [G.L.demand.xs[i] * G.w, G.L.demand.ys[i] * G.h]));
    SUPPLY.forEach((m, i) => (G.pos[m] = [G.L.supply.xs[i] * G.w, G.L.supply.ys[i] * G.h]));
    const P = (a) => [a[0] * G.w, a[1] * G.h];
    G.trunks = { q: [P(G.L.q[0]), P(G.L.q[1])], p: [P(G.L.p[0]), P(G.L.p[1])] };
    G.paths = new Map(EDGES.map((e) => [e, buildPath(e)]));
    for (const k in bodies) delete bodies[k];
    placeLabels();
    if (S.beats.length) apply(S.pos, false);
  }
  const quad = (a, c, b, n) => Array.from({ length: n + 1 }, (_, i) => { const t = i / n, u = 1 - t; return [u * u * a[0] + 2 * u * t * c[0] + t * t * b[0], u * u * a[1] + 2 * u * t * c[1] + t * t * b[1]]; });
  function buildPath(e) {
    const a = G.pos[e[0]], b = G.pos[e[1]], h = G.L.flow === "h";
    let pts;
    if (e[3] === "qi" || e[3] === "pi") {   // between supply modules: a short arc off the column
      const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], k = (e[3] === "qi" ? 1 : 1.9) * Math.min(G.w, G.h) * 0.045;
      pts = quad(a, [mid[0] + G.L.bulge[0] * k, mid[1] + G.L.bulge[1] * k], b, 24);
    } else {
      const [A, B] = G.trunks[e[3]];
      const c1 = h ? [A[0], a[1]] : [a[0], A[1]], c2 = h ? [B[0], b[1]] : [b[0], B[1]];
      pts = [...quad(a, c1, A, 18), ...quad(A, [(A[0] + B[0]) / 2, (A[1] + B[1]) / 2], B, 10).slice(1), ...quad(B, c2, b, 18).slice(1)];
    }
    const len = [0];
    for (let i = 1; i < pts.length; i++) len.push(len[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
    return { pts, len, total: len[len.length - 1] };
  }
  function along(p, t) {
    const d = t * p.total; let lo = 0, hi = p.len.length - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (p.len[m] < d) lo = m; else hi = m; }
    const f = (d - p.len[lo]) / ((p.len[hi] - p.len[lo]) || 1);
    return [p.pts[lo][0] + f * (p.pts[hi][0] - p.pts[lo][0]), p.pts[lo][1] + f * (p.pts[hi][1] - p.pts[lo][1])];
  }

  // ---- sprites ------------------------------------------------------------------------------------
  const glow = (() => {
    const c = document.createElement("canvas"); c.width = c.height = 64;
    const g = c.getContext("2d"), r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(0.22, "rgba(255,255,255,.6)"); r.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = r; g.fillRect(0, 0, 64, 64); return c;
  })();
  const tints = {};
  function tint(rgb) {
    const k = rgb.join(",");
    if (tints[k]) return tints[k];
    const c = document.createElement("canvas"); c.width = c.height = 64;
    const g = c.getContext("2d"); g.drawImage(glow, 0, 0); g.globalCompositeOperation = "source-in"; g.fillStyle = `rgb(${k})`; g.fillRect(0, 0, 64, 64);
    return (tints[k] = c);
  }
  const bodies = {};
  function body(grade) {
    const key = `${grade}:${G.R}:${G.dpr}`;
    if (bodies[key]) return bodies[key];
    const R = G.R, size = Math.ceil((2 * R + 6) * G.dpr), c = document.createElement("canvas"); c.width = c.height = size;
    const g = c.getContext("2d"); g.scale(G.dpr, G.dpr); const x = size / G.dpr / 2;
    g.beginPath(); g.arc(x, x, R, 0, 6.2832);
    if (grade === "match") {
      const rg = g.createRadialGradient(x - R * 0.3, x - R * 0.3, R * 0.1, x, x, R);
      rg.addColorStop(0, "#9ef7d8"); rg.addColorStop(1, "#11916a"); g.fillStyle = rg; g.fill(); g.strokeStyle = "#d4fff1"; g.lineWidth = 1.5; g.stroke();
    } else {
      g.fillStyle = "#120f0a"; g.fill(); g.setLineDash([5, 4]); g.strokeStyle = "#E8A33D"; g.lineWidth = 2; g.stroke();
    }
    return (bodies[key] = c);
  }

  // ---- drawing ------------------------------------------------------------------------------------
  function strokePath(c, pts, from = 0, to = pts.length) {
    c.beginPath(); c.moveTo(pts[from][0], pts[from][1]);
    for (let i = from + 1; i < to; i++) c.lineTo(pts[i][0], pts[i][1]);
    c.stroke();
  }
  function draw(now) {
    const c = ctx;
    c.setTransform(G.dpr, 0, 0, G.dpr, 0, 0);
    c.clearRect(0, 0, G.w, G.h);
    if (!G.L) return;
    c.lineCap = "round"; c.lineJoin = "round";
    // trunks: one road each way, as bright as the busiest edge on it
    for (const t of ["q", "p"]) {
      let h = 0; for (const [e, v] of G.heat) if (e[3] === t) h = Math.max(h, v);
      const [A, B] = G.trunks[t];
      c.strokeStyle = `rgba(${COL[t].join(",")},${0.08 + 0.5 * h})`; c.lineWidth = 3 + 7 * h;
      c.beginPath(); c.moveTo(A[0], A[1]); c.lineTo(B[0], B[1]); c.stroke();
    }
    // branches
    for (const [e, p] of G.paths) {
      const h = G.heat.get(e) || 0;
      c.strokeStyle = `rgba(${colOf(e[3]).join(",")},${0.06 + 0.6 * h})`; c.lineWidth = 1 + 2.5 * h;
      if (e[3].length === 2) strokePath(c, p.pts);
      else { strokePath(c, p.pts, 0, 19); strokePath(c, p.pts, p.pts.length - 19); }
    }
    // particles, glow on particles only
    c.globalCompositeOperation = "lighter";
    G.parts = G.parts.filter((q) => now < q.t0 + q.dur);
    for (const q of G.parts) {
      const t = (now - q.t0) / q.dur; if (t < 0) continue;
      const img = tint(colOf(q.type)), fade = Math.sin(Math.PI * Math.min(1, t));
      for (let k = 0; k < 2; k++) {
        const tt = t - k * 0.03; if (tt < 0) break;
        const [x, y] = along(q.path, tt), s = q.size * (1 - 0.3 * k);
        c.globalAlpha = q.alpha * fade * (1 - 0.45 * k);
        c.drawImage(img, x - s / 2, y - s / 2, s, s);
      }
    }
    // node glow when something reached it this beat
    for (const m in G.pos) {
      const h = G.nodeHeat[m] || 0; if (h < 0.02) continue;
      const [x, y] = G.pos[m], s = G.R * (3 + 2.5 * h);
      c.globalAlpha = 0.25 + 0.55 * h; c.drawImage(tint(modGrade(m).grade === "match" ? [79, 227, 176] : [232, 163, 61]), x - s / 2, y - s / 2, s, s);
    }
    G.rings = G.rings.filter((r) => now < r.t0 + r.dur);
    for (const r of G.rings) {
      const t = (now - r.t0) / r.dur; if (t < 0) continue;
      const [x, y] = G.pos[r.m];
      c.globalAlpha = (1 - t) * r.a; c.strokeStyle = `rgb(${r.col.join(",")})`; c.lineWidth = 3 * (1 - t) + 0.5;
      c.beginPath(); c.arc(x, y, G.R + t * r.grow, 0, 6.2832); c.stroke();
    }
    c.globalAlpha = 1; c.globalCompositeOperation = "source-over";
    for (const m in G.pos) {
      const b = body(modGrade(m).grade), s = b.width / G.dpr, [x, y] = G.pos[m];
      c.drawImage(b, x - s / 2, y - s / 2, s, s);
    }
  }
  window.__think = { drawMs: 0, parts: 0 };   // draw cost, smoothed, for checking the 60 fps budget
  function loop(now) {
    const t = performance.now(); draw(now);
    window.__think.drawMs = 0.9 * window.__think.drawMs + 0.1 * (performance.now() - t); window.__think.parts = G.parts.length;
    requestAnimationFrame(loop);
  }

  // ---- labels (HTML: crisp text, no glow) ---------------------------------------------------------
  function placeLabels() {
    const box = $("labels"); box.innerHTML = "";
    for (const m of [...DEMAND, ...SUPPLY]) {
      const side = DEMAND.includes(m) ? G.L.demand.side : G.L.supply.side, [x, y] = G.pos[m], R = G.R;
      const el = document.createElement("div"); el.className = `lab ${side}`; el.dataset.m = m;
      const g = S.fid && S.sc ? modGrade(m) : { grade: "stand", why: "" };
      el.innerHTML = `<span class="nm">${MODS[m].name}</span><span class="bd ${g.grade === "match" ? "match" : "stand"}" title="${esc(g.why)}">${g.grade === "match" ? "PORTED" : "STAND-IN"}</span>` +
        `<span class="val" title="${esc(MODS[m].what || "all energy used, US")}"><span></span></span><span class="vs"></span><span class="note"></span>`;
      if (side === "left") Object.assign(el.style, { right: `${G.w - (x - R - 10)}px`, top: `${y}px`, transform: "translateY(-50%)" });
      if (side === "right") Object.assign(el.style, { left: `${x + R + 10}px`, top: `${y}px`, transform: "translateY(-50%)" });
      if (side === "above") Object.assign(el.style, { left: `${x}px`, bottom: `${G.h - (y - R - 6)}px`, transform: "translateX(-50%)" });
      if (side === "below") Object.assign(el.style, { left: `${x}px`, top: `${y + R + 6}px`, transform: "translateX(-50%)" });
      box.appendChild(el);
    }
  }
  function roll(holder, text, animate) {
    const cur = holder.querySelector("span:not(.out)");
    if (cur && cur.textContent === text) return;
    if (!animate || REDUCED || !cur || !cur.textContent) { holder.innerHTML = `<span>${esc(text)}</span>`; return; }
    cur.classList.add("out"); setTimeout(() => cur.remove(), 520);
    const n = document.createElement("span"); n.className = "in"; n.textContent = text; holder.appendChild(n);
    void n.offsetWidth; setTimeout(() => n.classList.remove("in"), 16);   // a timer, not animation frames: hidden tabs skip frames
  }
  function valueText(key, v) {
    const u = S.meta.vars[key].unit;
    if (u === "quads") return `${fmt(v, 2)} quads`;
    if (u === "Mt") return `${fmt(v)} Mt`;
    if (u === "$/gal") return `$${fmt(v, 2)}/gal`;
    if (u === "$/MMBtu") return `$${fmt(v, 2)}/MMBtu`;
    return `${fmt(v, 1)} ${u}`;
  }
  const rel = (a, b) => (Math.abs(b) > 1e-9 ? (a - b) / Math.abs(b) : 0);
  const pct = (r) => `${r >= 0 ? "+" : "-"}${fmt(Math.abs(r * 100), Math.abs(r) < 0.001 ? 2 : Math.abs(r) < 0.1 ? 1 : 0)}%`;
  function paintLabels(vals, active, animate) {
    for (const el of $("labels").children) {
      const m = el.dataset.m, key = MODS[m].key, v = vals[idx(key)], e = eiaAt(key, S.year), r = rel(v, e);
      roll(el.querySelector(".val"), valueText(key, v), animate);
      const vs = el.querySelector(".vs");
      vs.textContent = Math.abs(r) < 0.0005 ? "same as EIA" : `${pct(r)} vs EIA`;
      vs.className = `vs ${Math.abs(r) < 0.0005 ? "" : r > 0 ? "up" : "dn"}`;
      el.querySelector(".note").textContent = carbonNote(key) && G.L.flow === "v" ? "incl. carbon" : carbonNote(key);
      el.classList.toggle("dim", !!active && !active.has(m));
    }
  }

  // ---- the timeline: shock, every recorded step, settled ------------------------------------------
  function build(y) {
    const raw = S.sc.steps.filter((s) => s.y === y);
    const cyc = Math.max(...raw.map((s) => s.c)), keys = S.meta.keys;
    const eia = keys.map((k) => eiaAt(k, y));
    let prev = eia, co2 = eia[idx("co2")];
    const beats = [{ type: "shock", vals: eia, co2, co2src: "eia" }];
    raw.filter((s) => s.c === cyc).forEach((s, n) => {
      const cur = s.v.map((v, i) => (v === null ? prev[i] : v));
      if (s.s === "s") co2 = cur[idx("co2")];
      // what moved at this step, against what the modules saw before it (EIA's own values before the first)
      const moved = [];
      keys.forEach((k, i) => {
        if (k === "co2" && s.s === "d") return;
        const r = rel(cur[i], prev[i]);
        if (Math.abs(r) > 1e-7) moved.push([k, r]);
      });
      moved.sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
      beats.push({ type: "step", st: s, first: n === 0, vals: cur, prev, moved, co2, co2src: s.s === "s" ? "run" : beats[beats.length - 1].co2src });
      prev = cur;
    });
    const last = beats[beats.length - 1];
    beats.push({ type: "settle", vals: last.vals, co2: last.co2, co2src: "run", st: last.st });
    return beats;
  }
  const mag = (r) => Math.min(1, Math.log10(1 + Math.abs(r) * 1e4) / 4);   // 0.01% faint, 100% full
  function sayStep(b, short) {
    const s = b.st, top = b.moved.filter(([k]) => k !== "co2").slice(0, short ? 2 : 3);
    const items = top.map(([k, r]) => {
      const v = S.meta.vars[k], cn = carbonNote(k);
      return `${esc(v.label)} <span class="${r > 0 ? "up" : "dn"}">${pct(r)}</span>${cn ? ` <small>(${cn})</small>` : ""}`;
    });
    const co2m = b.moved.find(([k]) => k === "co2");
    if (co2m && s.s === "s") items.push(`US CO2 <span class="${co2m[1] > 0 ? "up" : "dn"}">${pct(co2m[1])}</span>`);
    const against = b.first ? "vs EIA" : s.s === "d" ? "vs last pass" : "vs the prices they saw";
    const head = s.s === "d" ? (b.first ? `Demand answers EIA's ${S.year} prices with the levers in` : "Demand answers the new prices")
      : (s.i === 1 ? "Supply prices that demand" : "Supply re-prices");
    return items.length ? `<b>${head}</b> (${against}): ${items.join(", ")}.` : `<b>${head}</b>: nothing moved more than 0.00001%.`;
  }
  function narrate(b) {
    if (b.type === "shock") {
      const lev = Object.entries(S.sc.levers || {}), where = (S.sc.entered || []).map((m) => (MODS[m] || { name: m }).name);
      return lev.length ? `<b>${S.year}.</b> ${esc(lev.map(([k, v]) => (SHORT[k] ? SHORT[k](v) : k)).join(" · "))} enters at <b>${esc(where.join(", "))}</b>.`
        : `<b>${S.year}, no shock.</b> The loop at EIA's own settings. Watch how little moves.`;
    }
    if (b.type === "step") return sayStep(b);
    const s = b.st, r = rel(b.co2, eiaAt("co2", S.year));
    return (s.ok ? `<b>Agreed after ${s.i} passes.</b> The last pass moved prices at most ${pct(s.dp).slice(1)}, inside EIA's tolerance. `
      : `<b>Stopped after ${s.i} passes</b> without passing EIA's test (last price change ${pct(s.dp).slice(1)}); NEMS moves on the same way. `) +
      `US CO2 ${fmt(b.co2)} Mt, <span class="${r > 0 ? "up" : "dn"}">${pct(r)}</span> vs EIA.`;
  }
  function headline(b) {
    if (b.type === "shock") return `<span class="tag shock">Shock</span>${esc(S.sc.label)} <span>${esc(S.year)}</span>`;
    if (b.type === "settle") return `<span class="tag settle">Settled</span>${esc(S.sc.label)} <span>${S.year}, after ${b.st.i} passes</span>`;
    return `<span class="tag pass">Pass ${b.st.i} · ${b.st.s === "d" ? "demand" : "supply"}</span>${b.st.s === "d" ? "Quantities go to supply" : "Prices go back to demand"} <span>${S.year}</span>`;
  }

  // ---- applying a beat ----------------------------------------------------------------------------
  function apply(i, animate, quick) {
    const b = S.beats[i]; if (!b) return;
    S.pos = i; $("scrub").value = i;
    G.heat = new Map(); G.nodeHeat = {};
    let active = null;
    if (b.type === "step") {
      active = new Set();
      const isDemandStep = b.st.s === "d";
      for (const e of EDGES) {
        const r = rel(b.vals[idx(e[2])], b.prev[idx(e[2])]);
        if (Math.abs(r) < 1e-7) continue;
        const demandKey = e[3] === "q";   // demand steps move what demand uses; supply steps move prices and power-plant fuel
        if (isDemandStep !== demandKey) continue;
        const m = mag(r);
        G.heat.set(e, m); active.add(e[0]); active.add(e[1]);
        G.nodeHeat[e[1]] = Math.max(G.nodeHeat[e[1]] || 0, m);
        if (animate && !REDUCED) spawn(e, m, quick ? 380 : 2000, quick);
      }
    } else if (b.type === "shock" && animate && !REDUCED) {
      for (const m of S.sc.entered || []) if (G.pos[m]) for (let n = 0; n < 3; n++)
        G.rings.push({ m, t0: performance.now() + n * 300, dur: 1600, grow: Math.min(G.w, G.h) * 0.2, a: 0.9, col: [255, 107, 107] });
      for (const m of S.sc.entered || []) G.nodeHeat[m] = 1;
    } else if (b.type === "settle" && animate && !REDUCED && !quick) {
      for (const m in G.pos) G.rings.push({ m, t0: performance.now(), dur: 1500, grow: 34, a: 0.55, col: [79, 227, 176] });
    }
    paintLabels(b.vals, active, animate);
    paintCO2box(b, animate);
    if (!quick) {
      $("headline").innerHTML = headline(b);
      const say = $("say"); say.innerHTML = narrate(b); if (animate) { say.classList.remove("fresh"); void say.offsetWidth; say.classList.add("fresh"); }
      paintTicker();
    } else {
      $("headline").innerHTML = `<span class="tag pass">Time-lapse</span>${esc(S.sc.label)} <span>${S.year}, pass ${b.st ? b.st.i : ""}</span>`;
    }
    $("pass").textContent = b.type === "step" ? `${S.year}, pass ${b.st.i} ${b.st.s === "d" ? "demand" : "supply"}` : `${S.year}`;
    paintConv();
  }
  function spawn(e, m, dur, quick) {
    const path = G.paths.get(e), now = performance.now(), room = Math.max(0, 650 - G.parts.length);
    const n = Math.min(room, Math.round((quick ? 1 : 3) + (quick ? 8 : 30) * m));
    for (let k = 0; k < n; k++) G.parts.push({ path, type: e[3], t0: now + Math.random() * dur * 0.5, dur: Math.max(300, dur * (0.5 + 0.15 * Math.random())),
      size: 6 + 10 * m * Math.random() + 3, alpha: 0.35 + 0.6 * m });
  }
  // The hero number: US energy CO2 as the loop has it at this step, EIA's own figure as a ghost beside it.
  function paintCO2box(b, animate) {
    const box = $("co2box");
    if (!box.firstChild) box.innerHTML = `<div class="k"></div><div class="row"><div class="n"><span></span></div><div class="ghost"></div></div><div class="u">million tons a year</div><div class="d"></div>`;
    const e = eiaAt("co2", S.year), r = rel(b.co2, e);
    box.querySelector(".k").textContent = `US energy CO2, ${S.year}`;
    roll(box.querySelector(".n"), fmt(b.co2), animate);
    box.querySelector(".ghost").innerHTML = `EIA<br>${fmt(e)}`;
    box.querySelector(".d").innerHTML = b.co2src === "eia" ? "EIA's number, before the loop runs" :
      `<span class="${Math.abs(r) < 0.0005 ? "" : r > 0 ? "up" : "dn"}">${Math.abs(r) < 0.0005 ? "same as EIA" : `${pct(r)} vs EIA`}</span> ${badge(keyGrade("co2"))}`;
  }
  function paintTicker() {
    const items = S.beats.slice(0, S.pos + 1).map((b, i) => {
      const cls = b.type === "shock" ? "shock" : b.type === "settle" ? "ok" : b.st.s === "d" ? "q" : "p";
      const tag = b.type === "step" ? `<b>Pass ${b.st.i}, ${b.st.s === "d" ? "demand" : "supply"}.</b> ` : "";
      return `<li class="${cls}${i === S.pos ? " now" : ""}">${tag}${b.type === "step" ? sayStep(b, true) : narrate(b)}</li>`;
    });
    items.reverse();
    const keep = 3, older = items.slice(keep);
    $("ticker").innerHTML = items.slice(0, keep).join("") + (older.length ?
      `<li class="older"><details${S.histOpen ? " open" : ""}><summary>${older.length} earlier step${older.length > 1 ? "s" : ""}</summary><ol class="ticker">${older.join("")}</ol></details></li>` : "");
    const d = $("ticker").querySelector("details");
    if (d) d.addEventListener("toggle", () => { S.histOpen = d.open; });
  }
  function paintConv() {
    const steps = S.beats.filter((b) => b.type === "step");
    $("conv").innerHTML = steps.map((b, k) => {
      const big = b.moved[0] ? Math.abs(b.moved[0][1]) : 0, i = S.beats.indexOf(b);
      const h = Math.max(2, 34 * mag(big));
      return `<i class="${b.st.s}${i === S.pos ? " on" : i < S.pos ? " done" : ""}" data-i="${i}" style="height:${h}px" ` +
        `title="Pass ${b.st.i} ${b.st.s === "d" ? "demand" : "supply"}: largest change ${pct(big).slice(1)} (${esc(b.moved[0] ? S.meta.vars[b.moved[0][0]].label : "none")})"></i>`;
    }).join("");
  }

  // ---- settled panel and CO2 by year --------------------------------------------------------------
  const SETTLED = [["co2", "US energy CO2"], ["pelrs", "Power price, homes"], ["pngrs", "Gas price, homes"], ["pmgtr", "Gasoline"],
    ["qtsrs", "Homes, all energy"], ["qtstr", "Vehicles, all energy"]];
  function paintSettled() {
    const y = S.year, b = S.beats[S.beats.length - 1], v = (k) => b.vals[idx(k)];
    $("set-year").textContent = y;
    $("settled").innerHTML = SETTLED.map(([k, label]) => {
      const x = v(k), e = eiaAt(k, y), r = rel(x, e), cn = carbonNote(k);
      return `<div class="st"><div class="k">${label}</div><div class="v">${valueText(k, x).replace(/ (quads|Mt)$/, " <small>$1</small>")}</div>` +
        `<div class="d">${Math.abs(r) < 0.0005 ? "same as EIA" : `${pct(r)} vs EIA (${valueText(k, e)})`}</div>${cn ? `<div class="c">${cn}</div>` : ""}${badge(keyGrade(k))}</div>`;
    }).join("");
    // The stand-in's power price: say plainly how little of a carbon price it passes through.
    const t = $("truth");
    if (carbon()) {
      const dg = v("pngel") - eiaAt("pngel", y), dp = v("pelrs") - eiaAt("pelrs", y);
      t.hidden = false;
      t.innerHTML = `<b>Stand-in limit, power price.</b> The electricity stand-in adds carbon only at the power sector's average CO2 per kWh, and its fitted price curve barely follows fuel costs (elasticity 0.001 to the gas price). ` +
        `Here gas for power plants rose $${fmt(dg, 2)}/MMBtu (incl. carbon). For scale: if gas-fired plants set the price, that alone would add about ${fmt((dg * 6.4) / 10, 1)}¢/kWh at a 6,400 Btu/kWh heat rate (our assumption); ` +
        `the stand-in moved the home power price ${dp >= 0 ? "+" : ""}${fmt(dp, 1)}¢. EIA's own electricity model is not ported yet.`;
    } else t.hidden = true;
  }
  function paintCO2(upTo) {
    const svg = $("co2"), W = svg.clientWidth || 300, H = svg.clientHeight || 110, [y0, y1] = S.meta.years, ys = [];
    for (let y = y0; y <= y1; y++) ys.push(y);
    const mine = ys.map((y) => { const st = S.sc.steps.filter((s) => s.y === y && s.s === "s"); return st.length ? st[st.length - 1].v[idx("co2")] : null; });
    const eia = ys.map((y) => eiaAt("co2", y)), all = [...eia, ...mine.filter((v) => v !== null)];
    const lo = Math.min(...all) * 0.97, hi = Math.max(...all) * 1.02;
    const X = (y) => 32 + ((y - y0) / (y1 - y0)) * (W - 40), Y = (v) => 8 + (1 - (v - lo) / (hi - lo)) * (H - 26);
    const line = (arr, lim) => arr.map((v, i) => (v === null || ys[i] > lim ? null : `${X(ys[i])},${Y(v)}`)).filter(Boolean).join(" ");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.innerHTML = `<polyline points="${line(eia, y1)}" fill="none" stroke="#8a8880" stroke-dasharray="4 3" stroke-width="1.4"/>` +
      `<polyline points="${line(mine, upTo || y1)}" fill="none" stroke="#4FE3B0" stroke-width="2.2"/>` +
      `<line x1="${X(upTo || S.year)}" x2="${X(upTo || S.year)}" y1="6" y2="${H - 16}" stroke="rgba(255,255,255,.2)"/>` +
      `<text x="0" y="${Y(hi) + 8}">${fmt(hi)}</text><text x="0" y="${Y(lo)}">${fmt(lo)}</text>` +
      `<text x="${X(y0)}" y="${H - 2}" text-anchor="middle">${y0}</text><text x="${X(y1)}" y="${H - 2}" text-anchor="end">${y1}</text>` +
      `<text x="${W - 4}" y="14" text-anchor="end" style="fill:#4FE3B0">this run</text><text x="${W - 4}" y="26" text-anchor="end">EIA, dashed</text>`;
    $("co2-grade").innerHTML = badge(keyGrade("co2"));
  }

  // ---- transport ----------------------------------------------------------------------------------
  const BEAT = { shock: 2800, step: 2400, settle: 2600 };
  const wait = (ms, token) => new Promise((ok) => setTimeout(() => ok(token === S.token), ms));
  async function play() {
    if (S.playing) { pause(); return; }
    const token = ++S.token; S.playing = true; buttons();
    if (S.pos >= S.beats.length - 1) S.pos = -1;
    for (let i = S.pos + 1; i < S.beats.length; i++) {
      apply(i, true);
      if (!(await wait(BEAT[S.beats[i].type] * (REDUCED ? 1.15 : 1), token))) return false;
    }
    S.playing = false; buttons();
    return true;
  }
  function pause() { S.token++; S.playing = false; S.lapse = false; finale(false); buttons(); }
  function go(i, animate) { pause(); apply(Math.max(0, Math.min(S.beats.length - 1, i)), animate); }
  async function lapse() {
    if (S.lapse) { pause(); return; }
    pause(); const token = ++S.token; S.lapse = true; buttons();
    let prev = null, passes = 0;
    for (let y = S.meta.years[0]; y <= S.meta.years[1]; y++) {
      setYear(y, false);
      const b = S.beats[S.beats.length - 1];
      passes += b.st.i;
      yearBeat(b, prev);
      paintCO2(y);
      prev = b.vals;
      if (!(await wait(REDUCED ? 900 : 600, token))) return;
    }
    S.lapse = false; S.pos = S.beats.length - 1; buttons();
    finale(true, passes);
  }
  // A year in the time-lapse: where the loop settled, with each edge lit by how much its value moved
  // since the year before (both recorded, settled values).
  function yearBeat(b, prev) {
    G.heat = new Map(); G.nodeHeat = {};
    if (prev) for (const e of EDGES) {
      const r = rel(b.vals[idx(e[2])], prev[idx(e[2])]);
      if (Math.abs(r) < 1e-6) continue;
      const m = mag(r); G.heat.set(e, m); G.nodeHeat[e[1]] = Math.max(G.nodeHeat[e[1]] || 0, m * 0.6);
      if (!REDUCED) spawn(e, m, 560, true);
    }
    paintLabels(b.vals, null, true); paintCO2box(b, true);
    const r = rel(b.co2, eiaAt("co2", S.year));
    $("headline").innerHTML = `<span class="tag pass">Time-lapse</span>${esc(S.sc.label)} <span>${S.year}, settled after ${b.st.i} passes</span>`;
    $("say").innerHTML = `<b>${S.year}.</b> US CO2 ${fmt(b.co2)} Mt, <span class="${r > 0 ? "up" : "dn"}">${pct(r)}</span> vs EIA. Edges show what moved since ${S.year - 1}.`;
    $("pass").textContent = `${S.year}`;
    $("scrub").value = S.beats.length - 1;
  }
  function finale(on, passes) {
    const f = $("finale");
    if (!on) { f.hidden = true; return; }
    const y = S.meta.years[1], b = S.beats[S.beats.length - 1], e = eiaAt("co2", y), r = rel(b.co2, e);
    f.innerHTML = `<div class="f-y">${y}</div><div class="f-s">${esc(S.sc.label)}</div>` +
      `<div class="f-n">${fmt(b.co2)}<small> Mt CO2</small></div>` +
      `<div class="f-d"><span class="${Math.abs(r) < 0.0005 ? "" : r > 0 ? "up" : "dn"}">${Math.abs(r) < 0.0005 ? "the same as" : pct(r) + " vs"}</span> EIA's reference (${fmt(e)} Mt)</div>` +
      `<div class="f-f">${fmt(passes)} passes of the real loop, 2027 to 2050, every one recorded. ${badge(keyGrade("co2"))}</div>` +
      `<button class="btn ghost small" type="button" id="finale-x">Close</button>`;
    f.hidden = false;
    $("finale-x").addEventListener("click", () => (f.hidden = true));
    $("say").innerHTML = `<b>${y}, settled.</b> Every year's loop agreed; the line beside the stage is each year's settled CO2.`;
  }
  function buttons() {
    $("play").textContent = S.playing ? "Pause" : S.pos >= S.beats.length - 1 ? "Replay" : "Play";
    $("lapse").textContent = S.lapse ? "Stop" : "Time-lapse";
  }
  function setYear(y, show = true) {
    S.year = y; $("year").value = y; $("year-out").textContent = y;
    S.beats = build(y); $("scrub").max = S.beats.length - 1;
    paintSettled(); if (!S.lapse) paintCO2(); links(); writeHash();
    if (show) apply(S.beats.length - 1, false);
    buttons();
  }

  // ---- scenarios, links, legend -------------------------------------------------------------------
  function pulse(fromEl, mods) {
    if (REDUCED || !fromEl || !mods.length || !G.L) return Promise.resolve();
    const a = fromEl.getBoundingClientRect(), st = $("stage").getBoundingClientRect();
    const x0 = a.left + a.width / 2, y0 = a.top + a.height / 2;
    return Promise.all(mods.filter((m) => G.pos[m]).map((m, k) => new Promise((ok) => {
      const [nx, ny] = G.pos[m], x1 = st.left + nx, y1 = st.top + ny;
      const dot = document.createElement("div"); dot.className = "spark"; document.body.appendChild(dot);
      dot.style.left = `${x0}px`; dot.style.top = `${y0}px`;
      const lift = Math.min(y0, y1) - 60;   // an arc, not a straight line
      const anim = dot.animate([
        { transform: "translate(-50%,-50%) scale(.6)", opacity: 0 },
        { transform: `translate(calc(-50% + ${(x1 - x0) * 0.45}px), calc(-50% + ${lift - y0}px)) scale(1.3)`, opacity: 1, offset: 0.45 },
        { transform: `translate(calc(-50% + ${x1 - x0}px), calc(-50% + ${y1 - y0}px)) scale(.8)`, opacity: 1 },
      ], { duration: 1150, delay: k * 90, easing: "cubic-bezier(.45,0,.2,1)", fill: "forwards" });
      let done = false;
      const land = () => {
        if (done) return; done = true;
        dot.remove();
        for (let n = 0; n < 2; n++) G.rings.push({ m, t0: performance.now() + n * 220, dur: 1200, grow: Math.min(G.w, G.h) * 0.16, a: 0.95, col: [255, 107, 107] });
        G.nodeHeat[m] = 1; ok();
      };
      anim.onfinish = land;
      setTimeout(land, 1150 + k * 90 + 250);   // a background tab may never finish the animation; the story goes on
    })));
  }

  async function pick(id, autoplay, fromEl) {
    pause();
    if (!S.cache[id]) S.cache[id] = await fetch(`data/think/${id}.json`).then((r) => r.json());
    S.sc = S.cache[id];
    for (const b of document.querySelectorAll(".chip")) b.setAttribute("aria-pressed", String(b.dataset.id === id));
    $("lever").value = S.sc.kind === "lever" ? id : "";
    placeLabels(); legend();
    setYear(S.year, !autoplay);
    if (autoplay) {
      apply(0, false);
      const token = S.token;
      $("stage").scrollIntoView({ block: "nearest", behavior: REDUCED ? "auto" : "smooth" });
      await pulse(fromEl || document.querySelector(`.chip[data-id="${id}"]`) || $("lever"), S.sc.entered || []);
      if (token !== S.token) return;
      S.pos = -1;
      // the year, pass by pass; then the finale: every year to 2050
      if (!(await play())) return;
      if (await wait(1400, S.token)) lapse();
    }
  }
  function links() {
    const lev = S.sc.levers || {}, story = { reference: "eia", fast: "fast", ai: "ai", gas: "gas", nuke: "nuke" }[S.sc.id];
    $("to2050").href = `2050.html#${[...Object.entries(lev).map(([k, v]) => `${k}=${v}`), `y=${S.year}`, ...(story ? [`s=${story}`] : [])].join("&")}`;
    $("toEngine").href = `engine3d.html#a=yours&y=${S.year}&yours=${encodeURIComponent(Object.entries(lev).map(([k, v]) => `${k}:${v}`).join(","))}`;
  }
  function legend() {
    const p = (S.sc.ported || []).map((m) => MODS[m].name).join(", ");
    $("legend").innerHTML = `<span><i style="background:rgb(${COL.q})"></i>quantities, demand to supply</span>` +
      `<span><i style="background:rgb(${COL.p})"></i>prices, supply to demand</span>` +
      `<span>Solid green: ported from EIA's code${p ? ` (${p})` : ""}. Dashed amber: stand-in fitted to EIA's runs.</span>` +
      `<span>Particle density: how big that step's change was (log scale). Numbers are the model's.</span>` +
      (S.sc.fast ? `<span style="color:#E8A33D">Trial file: every sector ran on the stub.</span>` : "");
  }
  function writeHash() { history.replaceState(null, "", `#s=${S.sc.id}&y=${S.year}`); }

  async function main() {
    const [meta, man, fid] = await Promise.all(["data/think/meta.json", "data/think/manifest.json", "data/fidelity.json"].map((u) => fetch(u).then((r) => r.json())));
    Object.assign(S, { meta, man, fid });
    const stories = man.scenarios.filter((s) => s.kind === "story"), levers = man.scenarios.filter((s) => s.kind === "lever");
    $("stories").innerHTML = stories.map((s) => `<button class="chip" type="button" data-id="${s.id}" aria-pressed="false" title="${esc(s.desc)}">${esc(s.label)}</button>`).join("");
    $("lever").innerHTML = `<option value="">${levers.length ? "Choose a lever" : "Lever runs still computing"}</option>` + levers.map((s) => `<option value="${s.id}">${esc(s.label)}</option>`).join("");
    $("stories").addEventListener("click", (e) => { const b = e.target.closest(".chip"); if (b) pick(b.dataset.id, !REDUCED, b); });
    $("lever").addEventListener("change", (e) => { if (e.target.value) pick(e.target.value, !REDUCED, e.target); });
    $("year").addEventListener("input", (e) => { pause(); setYear(+e.target.value); });
    $("play").addEventListener("click", play);
    $("back").addEventListener("click", () => go(S.pos - 1, false));
    $("fwd").addEventListener("click", () => go(S.pos + 1, true));
    $("scrub").addEventListener("input", (e) => go(+e.target.value, false));
    $("conv").addEventListener("click", (e) => { const b = e.target.closest("[data-i]"); if (b) go(+b.dataset.i, true); });
    $("lapse").addEventListener("click", lapse);
    addEventListener("keydown", (e) => {
      if (e.target.matches("input,select")) return;
      if (e.key === " ") { e.preventDefault(); play(); } else if (e.key === "ArrowRight") go(S.pos + 1, true); else if (e.key === "ArrowLeft") go(S.pos - 1, false);
    });
    $("about").textContent = `${meta.about} Ported modules run EIA's own logic in Python, checked against EIA's code; stand-ins are fitted to EIA's published runs. ` +
      `Delivered prices include the carbon price when there is one. ${REDUCED ? "Reduced motion is on: no particles, the same numbers. " : ""}Space plays or pauses; arrow keys step.`;
    new ResizeObserver(() => layout()).observe($("stage"));
    layout();
    requestAnimationFrame(loop);
    const q = new URLSearchParams(location.hash.slice(1)), y = +q.get("y");
    if (y >= meta.years[0] && y <= meta.years[1]) S.year = y;
    const want = man.scenarios.find((s) => s.id === q.get("s")) || man.scenarios.find((s) => s.id === "fast") || man.scenarios[0];
    await pick(want.id, !REDUCED);   // the hero: play the chosen year once on arrival, unless less motion was asked for
  }
  addEventListener("DOMContentLoaded", () => main().catch((e) => {
    console.error(e);
    $("say").textContent = `The recorded runs did not load (${e.message}). Serve the web folder and run scripts/think_runs.py.`;
  }));
})();
