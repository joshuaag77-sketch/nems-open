// "Watch the model think": the convergence loop of run_model.run, replayed from recorded passes.
// Data: data/think/manifest.json, meta.json and one file per scenario (scripts/think_runs.py), grades from
// data/fidelity.json. Every number drawn is one the model handed between modules at that step; particle
// density shows how big that step's change was (log scale) and carries no number of its own.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fmt = (v, d = 0) => Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ---- the modules and what passes between them ---------------------------------------------------
  const MODS = {
    economy: { name: "Economy", side: "fixed", key: null },
    residential: { name: "Homes", side: "demand", key: "qtsrs" },
    commercial: { name: "Businesses", side: "demand", key: "qtscm" },
    industrial: { name: "Industry", side: "demand", key: "qtsin" },
    transportation: { name: "Vehicles", side: "demand", key: "qtstr" },
    electricity: { name: "Electricity", side: "supply", key: "pelrs" },
    natural_gas: { name: "Natural gas", side: "supply", key: "pngrs" },
    oil: { name: "Oil and refining", side: "supply", key: "pmgtr" },
    coal: { name: "Coal", side: "supply", key: "pclel" },
    emissions: { name: "CO2", side: "out", key: "co2" },
  };
  const LAYOUT = {   // [x, y] on the stage, wide and tall
    wide: { economy: [0.5, 0.1], residential: [0.15, 0.24], commercial: [0.12, 0.47], industrial: [0.15, 0.7], transportation: [0.3, 0.87],
      electricity: [0.85, 0.24], natural_gas: [0.88, 0.47], oil: [0.85, 0.7], coal: [0.7, 0.87], emissions: [0.5, 0.6] },
    tall: { economy: [0.5, 0.06], residential: [0.21, 0.2], commercial: [0.21, 0.4], industrial: [0.21, 0.6], transportation: [0.21, 0.8],
      electricity: [0.79, 0.2], natural_gas: [0.79, 0.4], oil: [0.79, 0.6], coal: [0.79, 0.8], emissions: [0.5, 0.93] },
  };
  // [from, to, recorded key, "q" quantity or "p" price]
  const EDGES = [
    ["residential", "electricity", "qelrs", "q"], ["residential", "natural_gas", "qngrs", "q"], ["residential", "oil", "qtprs", "q"],
    ["commercial", "electricity", "qelcm", "q"], ["commercial", "natural_gas", "qngcm", "q"], ["commercial", "oil", "qtpcm", "q"],
    ["industrial", "electricity", "qelin", "q"], ["industrial", "natural_gas", "qngin", "q"], ["industrial", "oil", "qtpin", "q"],
    ["transportation", "electricity", "qeltr", "q"], ["transportation", "oil", "qmgtr", "q"],
    ["electricity", "natural_gas", "qngel", "q"], ["electricity", "coal", "qclel", "q"], ["electricity", "oil", "qtpel", "q"],
    ["electricity", "residential", "pelrs", "p"], ["electricity", "commercial", "pelcm", "p"], ["electricity", "industrial", "pelin", "p"], ["electricity", "transportation", "peltr", "p"],
    ["natural_gas", "residential", "pngrs", "p"], ["natural_gas", "commercial", "pngcm", "p"], ["natural_gas", "industrial", "pngin", "p"], ["natural_gas", "electricity", "pngel", "p"],
    ["oil", "residential", "ptprs", "p"], ["oil", "commercial", "ptpcm", "p"], ["oil", "industrial", "ptpin", "p"], ["oil", "transportation", "pmgtr", "p"],
    ["coal", "electricity", "pclel", "p"],
    ["electricity", "emissions", "co2", "c"], ["natural_gas", "emissions", "co2", "c"], ["oil", "emissions", "co2", "c"], ["coal", "emissions", "co2", "c"],
  ];
  const STATIC_EDGES = [["economy", "residential"], ["economy", "commercial"], ["economy", "industrial"], ["economy", "transportation"]];
  const COL = { q: [87, 199, 255], p: [255, 181, 71], c: [255, 107, 107] };
  const LEVER_NAMES = { carbon_price: (v) => `carbon price $${v} a ton`, ev_2035: (v) => `EV sales ${Math.round(v * 100)}% of new cars in 2035`,
    load_growth: (v) => `${fmt(v)} TWh of new load by 2050`, building_code: (v) => `building codes ${Math.round(v * 100)}% tighter`,
    appliance_standard: (v) => `appliances ${Math.round(v * 100)}% better`, coal_retirement: (v) => `${Math.round(v * 100)}% of coal closed by 2035`,
    renewable_cost: (v) => (v < 0 ? "EIA's low wind and solar cost case" : "EIA's high wind and solar cost case"),
    gas_supply: (v) => (v > 0 ? "EIA's plentiful gas case" : "EIA's scarce gas case"), oil_price: (v) => `oil at ${v} x EIA's price`,
    nuclear: (v) => `nuclear at ${v} x EIA's output` };

  const SHORT = { carbon_price: (v) => `Carbon $${v}/t`, ev_2035: (v) => `EVs ${Math.round(v * 100)}%`, load_growth: (v) => `+${fmt(v)} TWh load`,
    building_code: (v) => `Codes +${Math.round(v * 100)}%`, appliance_standard: (v) => `Appliances +${Math.round(v * 100)}%`,
    coal_retirement: (v) => `Coal ${Math.round(v * 100)}% closed`, renewable_cost: (v) => (v < 0 ? "Cheap wind and solar" : "Pricey wind and solar"),
    gas_supply: (v) => (v > 0 ? "Plentiful gas" : "Scarce gas"), oil_price: (v) => `Oil x${v}`, nuclear: (v) => `Nuclear x${v}` };

  // ---- state --------------------------------------------------------------------------------------
  const S = { meta: null, man: null, fid: null, sc: null, cache: {}, year: 2035, steps: [], k: -1, playing: false, lapse: false, token: 0 };
  const idx = (k) => S.meta.keys.indexOf(k);
  const eiaAt = (k, y) => S.meta.eia[k][y - S.meta.years[0]];

  // ---- grades (data/fidelity.json): a module's grade in this run, a number's as its weakest piece ---
  const RANK = { match: 3, within: 2, stand: 1 };
  function modGrade(m) {
    if (m === "economy") return { grade: "fixed", label: "EIA's path", why: "Not modeled in this view: the loop uses EIA's own published economy." };
    const ported = (S.sc && S.sc.ported) || [];
    const part = ["residential", "commercial", "transportation"].includes(m) ? (ported.includes(m) ? `port:${m}` : "stand:demand_stub")
      : m === "industrial" ? "stand:demand_stub" : { electricity: "stand:electricity", natural_gas: "stand:natural_gas", oil: "stand:oil", coal: "stand:coal", emissions: "stand:emissions" }[m];
    const p = S.fid.parts[part];
    return { grade: p.grade, label: p.grade === "match" ? "ported" : p.label, why: `${p.name}: ${p.summary}`, part };
  }
  function keyGrade(key) {
    const mods = key === "co2" ? Object.keys(MODS).filter((m) => m !== "economy") : [S.meta.vars[key].module];
    let w = null;
    for (const m of mods) { const g = modGrade(m); if (!w || RANK[g.grade] < RANK[w.grade]) w = g; }
    return w;
  }
  const badge = (g) => `<span class="g g-${g.grade}" title="${esc(g.why)}">${esc(g.grade === "match" ? "matches EIA" : g.label)}</span>`;

  // ---- the stage ----------------------------------------------------------------------------------
  const cv = $("cv"), ctx = cv.getContext("2d");
  const G = { w: 0, h: 0, dpr: 1, pos: {}, R: 26, tall: false, parts: [], rings: [], edgeHeat: new Map(), labels: [], vals: {}, flash: {} };
  const sprite = (() => {
    const c = document.createElement("canvas"); c.width = c.height = 64;
    const g = c.getContext("2d"), r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(0.25, "rgba(255,255,255,.55)"); r.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = r; g.fillRect(0, 0, 64, 64); return c;
  })();
  const tinted = {};
  function tint(type) {
    if (tinted[type]) return tinted[type];
    const c = document.createElement("canvas"); c.width = c.height = 64;
    const g = c.getContext("2d"); g.drawImage(sprite, 0, 0); g.globalCompositeOperation = "source-in";
    g.fillStyle = `rgb(${COL[type].join(",")})`; g.fillRect(0, 0, 64, 64);
    return (tinted[type] = c);
  }

  function layout() {
    const r = $("stage").getBoundingClientRect();
    G.w = r.width; G.h = r.height; G.dpr = Math.min(2, window.devicePixelRatio || 1);
    cv.width = Math.round(G.w * G.dpr); cv.height = Math.round(G.h * G.dpr);
    G.tall = G.h > G.w * 1.05;
    const L = LAYOUT[G.tall ? "tall" : "wide"];
    for (const m in MODS) G.pos[m] = [L[m][0] * G.w, L[m][1] * G.h];
    G.R = Math.max(16, Math.min(30, Math.min(G.w, G.h) * 0.045));
  }
  // A quadratic curve from a to b, bowed to one side so a price and a quantity between the same two modules do not overlap.
  function curve(a, b, type) {
    const [x1, y1] = G.pos[a], [x2, y2] = G.pos[b], mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1, bow = (type === "p" ? -1 : 1) * Math.min(90, len * 0.16);
    return [x1, y1, mx - (dy / len) * bow, my + (dx / len) * bow, x2, y2];
  }
  const at = (c, t) => { const u = 1 - t; return [u * u * c[0] + 2 * u * t * c[2] + t * t * c[4], u * u * c[1] + 2 * u * t * c[3] + t * t * c[5]]; };

  // How big a step's change looks: log scale, 0.01% faint, 100% full.
  const mag = (rel) => Math.min(1, Math.log10(1 + Math.abs(rel) * 1e4) / 4);

  function draw(now) {
    const c = ctx;
    c.setTransform(G.dpr, 0, 0, G.dpr, 0, 0);
    c.clearRect(0, 0, G.w, G.h);
    // economy feeds demand: EIA's fixed path, drawn dotted and never animated
    c.setLineDash([2, 5]); c.strokeStyle = "rgba(140,138,130,.25)"; c.lineWidth = 1;
    for (const [a, b] of STATIC_EDGES) { const k = curve(a, b, "q"); c.beginPath(); c.moveTo(k[0], k[1]); c.quadraticCurveTo(k[2], k[3], k[4], k[5]); c.stroke(); }
    c.setLineDash([]);
    // edges, brighter while their value is moving
    for (const e of EDGES) {
      const k = curve(e[0], e[1], e[3]), heat = G.edgeHeat.get(e) || 0, col = COL[e[3]];
      c.strokeStyle = `rgba(${col.join(",")},${0.06 + 0.55 * heat})`; c.lineWidth = 1 + 2.5 * heat;
      c.beginPath(); c.moveTo(k[0], k[1]); c.quadraticCurveTo(k[2], k[3], k[4], k[5]); c.stroke();
    }
    // particles
    c.globalCompositeOperation = "lighter";
    G.parts = G.parts.filter((p) => now < p.t0 + p.dur);
    for (const p of G.parts) {
      const t = (now - p.t0) / p.dur; if (t < 0) continue;
      const img = tint(p.type);
      for (let tail = 0; tail < 2; tail++) {
        const tt = t - tail * 0.035; if (tt < 0) break;
        const [x, y] = at(p.curve, tt), s = p.size * (1 - tail * 0.3);
        c.globalAlpha = p.alpha * (1 - tail * 0.4) * Math.sin(Math.PI * Math.min(1, t * 1.05));
        c.drawImage(img, x - s / 2, y - s / 2, s, s);
      }
    }
    c.globalAlpha = 1;
    // shock and settle rings
    G.rings = G.rings.filter((r) => now < r.t0 + r.dur);
    for (const r of G.rings) {
      const t = (now - r.t0) / r.dur; if (t < 0) continue;
      const [x, y] = G.pos[r.m];
      c.strokeStyle = `rgba(${r.col.join(",")},${(1 - t) * r.a})`; c.lineWidth = r.w * (1 - t) + 0.5;
      c.beginPath(); c.arc(x, y, G.R + t * r.grow, 0, 6.2832); c.stroke();
    }
    c.globalCompositeOperation = "source-over";
    // nodes
    for (const m in MODS) drawNode(m, now);
    // the biggest changes of this step, as numbers on their edges, placed where they do not collide
    c.font = "600 11px system-ui,sans-serif"; c.textAlign = "center";
    const boxes = [];
    for (const l of G.labels) {
      const t = (now - l.t0) / l.dur; if (t < 0 || t > 1) continue;
      const k = curve(l.e[0], l.e[1], l.e[3]), w = c.measureText(l.text).width + 10;
      let spot = null;
      for (const tt of [0.5, 0.36, 0.64, 0.26, 0.74]) {
        const [x, y] = at(k, tt), b = [x - w / 2, y - 9, w, 17];
        if (!boxes.some((o) => b[0] < o[0] + o[2] && o[0] < b[0] + b[2] && b[1] < o[1] + o[3] && o[1] < b[1] + b[3])) { spot = b; break; }
      }
      if (!spot) continue;   // no room: the ticker still has it
      boxes.push(spot);
      c.globalAlpha = Math.min(1, 4 * t, 4 * (1 - t));
      c.fillStyle = "rgba(7,9,13,.88)"; c.fillRect(spot[0], spot[1], spot[2], spot[3]);
      c.fillStyle = `rgb(${COL[l.e[3]].join(",")})`; c.fillText(l.text, spot[0] + w / 2, spot[1] + 12.5);
    }
    c.globalAlpha = 1;
    // fade edge heat
    for (const [e, h] of G.edgeHeat) G.edgeHeat.set(e, h * 0.985);
  }

  function drawNode(m, now) {
    const c = ctx, [x, y] = G.pos[m], R = G.R, g = S.fid ? modGrade(m) : { grade: "fixed" };
    const fl = G.flash[m] ? Math.max(0, 1 - (now - G.flash[m]) / 900) : 0;
    // glow
    c.globalCompositeOperation = "lighter";
    const glowCol = g.grade === "match" ? [79, 227, 176] : g.grade === "fixed" ? [110, 108, 102] : [232, 163, 61];
    c.globalAlpha = 0.18 + 0.5 * fl;
    const gs = R * (3.2 + 1.5 * fl); c.drawImage(tintRGB(glowCol), x - gs / 2, y - gs / 2, gs, gs);
    c.globalAlpha = 1; c.globalCompositeOperation = "source-over";
    // body: ported solid, stand-in hollow and dashed, EIA's fixed path dotted grey
    const body = nodeSprite(g.grade, R);
    c.drawImage(body, x - body.width / G.dpr / 2, y - body.height / G.dpr / 2, body.width / G.dpr, body.height / G.dpr);
    // text
    c.textAlign = "center";
    c.font = `600 ${G.tall ? 12 : 13}px system-ui,sans-serif`; c.fillStyle = "#ece9e1";
    c.fillText(MODS[m].name, x, y + R + 15);
    const v = G.vals[m];
    if (v) {
      c.font = `500 ${G.tall ? 11 : 12}px system-ui,sans-serif`; c.fillStyle = "#a9a69d";
      c.fillText(v.text, x, y + R + 30);
      if (v.vs) { c.fillStyle = v.vsCol; c.fillText(v.vs, x, y + R + 44); }
    } else if (m === "economy") {
      c.font = "500 11px system-ui,sans-serif"; c.fillStyle = "#77756e"; c.fillText("EIA's path, not modeled here", x, y + R + 30);
    }
    c.font = "600 9.5px system-ui,sans-serif"; c.fillStyle = g.grade === "match" ? "#04342C" : g.grade === "fixed" ? "#8a8880" : "#E8A33D";
    c.fillText(g.grade === "match" ? "PORTED" : g.grade === "fixed" ? "FIXED" : "STAND-IN", x, y + 3.5);
  }
  // Node bodies drawn once per size: ported solid, stand-in hollow and dashed, EIA's fixed path dotted grey.
  const bodies = {};
  function nodeSprite(grade, R) {
    const key = `${grade}:${R}:${G.dpr}`;
    if (bodies[key]) return bodies[key];
    const size = Math.ceil((2 * R + 6) * G.dpr), cvs = document.createElement("canvas"); cvs.width = cvs.height = size;
    const c = cvs.getContext("2d"); c.scale(G.dpr, G.dpr);
    const x = size / G.dpr / 2, y = x;
    c.beginPath(); c.arc(x, y, R, 0, 6.2832);
    if (grade === "match") {
      const rg = c.createRadialGradient(x - R * 0.3, y - R * 0.3, R * 0.1, x, y, R);
      rg.addColorStop(0, "#8ff5d2"); rg.addColorStop(1, "#139a70"); c.fillStyle = rg; c.fill();
      c.strokeStyle = "#c9fff0"; c.lineWidth = 1.5; c.stroke();
    } else if (grade === "fixed") {
      c.fillStyle = "#0d0f13"; c.fill(); c.setLineDash([2, 4]); c.strokeStyle = "#77756e"; c.lineWidth = 1.5; c.stroke();
    } else {
      c.fillStyle = "rgba(232,163,61,.08)"; c.fill(); c.setLineDash([5, 4]); c.strokeStyle = "#E8A33D"; c.lineWidth = 1.8; c.stroke();
    }
    return (bodies[key] = cvs);
  }
  const rgbSprites = {};
  function tintRGB(col) {
    const key = col.join(",");
    if (rgbSprites[key]) return rgbSprites[key];
    const c = document.createElement("canvas"); c.width = c.height = 64;
    const g = c.getContext("2d"); g.drawImage(sprite, 0, 0); g.globalCompositeOperation = "source-in";
    g.fillStyle = `rgb(${key})`; g.fillRect(0, 0, 64, 64);
    return (rgbSprites[key] = c);
  }

  let rafOn = false;
  // draw time, smoothed, for checking the 60 fps budget from the console: window.__think.drawMs
  window.__think = { drawMs: 0, parts: 0 };
  function loop(now) {
    const t = performance.now(); draw(now);
    window.__think.drawMs = 0.9 * window.__think.drawMs + 0.1 * (performance.now() - t); window.__think.parts = G.parts.length;
    requestAnimationFrame(loop);
  }

  // ---- one scenario-year as recorded steps --------------------------------------------------------
  // Each step holds every key's value after that demand or supply step; `prev` is what the modules saw
  // before it (EIA's own value before the first step of the year, the shock's baseline).
  function stepsFor(y) {
    const raw = S.sc.steps.filter((s) => s.y === y && s.c === Math.max(...S.sc.steps.filter((t) => t.y === y).map((t) => t.c)));
    const keys = S.meta.keys;
    let prev = keys.map((k) => eiaAt(k, y));
    return raw.map((s, n) => {
      const cur = s.v.map((v, i) => (v === null ? prev[i] : v));
      const st = { ...s, n, cur, prev, first: n === 0 };
      prev = cur; return st;
    });
  }
  const rel = (a, b) => (Math.abs(b) > 1e-9 ? (a - b) / Math.abs(b) : 0);
  const pct = (r, d = 1) => `${r >= 0 ? "+" : "-"}${fmt(Math.abs(r * 100), Math.abs(r) < 0.001 ? 2 : d)}%`;
  function valueText(key, v) {
    const u = S.meta.vars[key].unit;
    if (u === "quads") return `${fmt(v, 2)} quads`;
    if (u === "Mt") return `${fmt(v)} Mt`;
    if (u === "$/gal") return `$${fmt(v, 2)}/gal`;
    if (u === "$/MMBtu") return `$${fmt(v, 2)}/MMBtu`;
    return `${fmt(v, 1)} ${u}`;
  }
  function setNodeValues(st, y) {
    for (const m in MODS) {
      const key = MODS[m].key; if (!key) continue;
      const v = st.cur[idx(key)], e = eiaAt(key, y), r = rel(v, e);
      G.vals[m] = { text: valueText(key, v), vs: Math.abs(r) < 0.0005 ? "same as EIA" : `${pct(r)} vs EIA`, vsCol: Math.abs(r) < 0.0005 ? "#77756e" : r > 0 ? "#ff9b85" : "#7fe0bf" };
    }
  }

  // Play one step: particles along every edge whose value changed at this step, in the direction it travels.
  function playStep(st, dur, quiet) {
    const now = performance.now(), keys = S.meta.keys;
    const moved = [];
    for (const e of EDGES) {
      const i = idx(e[2]), r = rel(st.cur[i], st.prev[i]);
      if (Math.abs(r) < 1e-6) continue;
      // demand steps move quantities; supply steps move prices, power-plant fuel and CO2
      const isDemandKey = e[3] === "q" && S.meta.vars[e[2]].module !== "electricity";
      if ((st.s === "d") !== isDemandKey) continue;
      moved.push([e, r]);
      const m = mag(r);
      G.edgeHeat.set(e, Math.max(G.edgeHeat.get(e) || 0, m));
      if (REDUCED) continue;
      const room = Math.max(0, 700 - G.parts.length);   // a ceiling on live particles keeps the frame rate
      const n = Math.min(room, Math.round((quiet ? 1 : 3) + (quiet ? 12 : 34) * m)), k = curve(e[0], e[1], e[3]);
      for (let p = 0; p < n; p++) G.parts.push({ curve: k, type: e[3], t0: now + Math.random() * dur * 0.55, dur: dur * (0.45 + Math.random() * 0.2),
        size: 7 + 11 * m * Math.random() + 3, alpha: 0.35 + 0.55 * m });
    }
    // the destination modules light up with the size of what reached them
    const hit = {};
    for (const [e, r] of moved) hit[e[1]] = Math.max(hit[e[1]] || 0, mag(r));
    for (const m in hit) {
      G.flash[m] = now + dur * 0.45;
      if (!REDUCED && hit[m] > 0.15) G.rings.push({ m, t0: now + dur * 0.45, dur: 900, grow: 30 * hit[m] + 8, w: 2.5, a: 0.8 * hit[m], col: st.s === "d" ? COL.q : COL.p });
    }
    // numbers on the five biggest
    const top = moved.slice().sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).filter((x, i, a) => a.findIndex((y) => y[0][2] === x[0][2]) === i).slice(0, quiet ? 0 : 5);
    G.labels = top.map(([e, r]) => ({ e, text: `${S.meta.vars[e[2]].label} ${pct(r)}`, t0: now + dur * 0.2, dur: dur * 0.95 }));
    return moved;
  }

  // ---- the narration: the real values of this step, plainly ----------------------------------------
  function narrate(st, moved, y) {
    const top = [];
    const seen = new Set();
    for (const [e, r] of moved.sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))) {
      if (seen.has(e[2])) continue; seen.add(e[2]);
      const v = S.meta.vars[e[2]];
      top.push(`${esc(v.label)} <span class="${r > 0 ? "up" : "dn"}">${pct(r)}</span>`);
      if (top.length === 3) break;
    }
    const pass = st.i;
    let head, cls;
    if (st.s === "d") {
      head = st.first ? `<b>Pass 1, demand.</b> The four demand modules answer EIA's ${y} prices with the levers in place (vs EIA):`
        : `<b>Pass ${pass}, demand.</b> Homes, businesses, industry and vehicles answer the new prices (vs what they used last pass):`;
      cls = "q";
    } else {
      head = `<b>Pass ${pass}, supply.</b> Electricity, gas, oil and coal price that demand (vs the prices it saw):`;
      cls = "p";
    }
    add(top.length ? `${head} ${top.join(", ")}.` : `${head} nothing moved more than 0.0001%.`, cls);
  }
  function add(html, cls) {
    const li = document.createElement("li"); li.className = cls || ""; li.innerHTML = html;
    const t = $("ticker"); t.insertBefore(li, t.firstChild);
    while (t.children.length > 7) t.lastChild.remove();
  }

  // ---- the settled year ---------------------------------------------------------------------------
  const SETTLED = [["co2", "US energy CO2"], ["pelrs", "Power price, homes"], ["pngrs", "Gas price, homes"], ["pmgtr", "Gasoline"],
    ["qtsrs", "Homes, all energy"], ["qtstr", "Vehicles, all energy"]];
  function paintSettled(y) {
    const st = stepsFor(y), last = st[st.length - 1];
    $("set-year").textContent = y;
    $("settled").innerHTML = SETTLED.map(([k, label]) => {
      const v = last.cur[idx(k)], e = eiaAt(k, y), r = rel(v, e);
      return `<div class="st"><div class="k">${label}</div><div class="v">${valueText(k, v).replace(/ (quads|Mt)$/, " <small>$1</small>")}</div>` +
        `<div class="d">${Math.abs(r) < 0.0005 ? "same as EIA" : `${pct(r)} vs EIA (${valueText(k, e)})`}</div>${badge(keyGrade(k))}</div>`;
    }).join("");
  }
  function paintCO2(upTo) {
    const svg = $("co2"), W = svg.clientWidth || 320, H = svg.clientHeight || 120, [y0, y1] = S.meta.years;
    const ys = []; for (let y = y0; y <= y1; y++) ys.push(y);
    const mine = ys.map((y) => { const st = S.sc.steps.filter((s) => s.y === y && s.s === "s"); return st.length ? st[st.length - 1].v[idx("co2")] : null; });
    const eia = ys.map((y) => eiaAt("co2", y));
    const all = [...eia, ...mine.filter((v) => v !== null)], lo = Math.min(...all) * 0.97, hi = Math.max(...all) * 1.02;
    const X = (y) => 30 + ((y - y0) / (y1 - y0)) * (W - 38), Y = (v) => 8 + (1 - (v - lo) / (hi - lo)) * (H - 26);
    const line = (arr, lim) => arr.map((v, i) => (v === null || ys[i] > lim ? null : `${X(ys[i])},${Y(v)}`)).filter(Boolean).join(" ");
    const cur = upTo || S.year;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.innerHTML = `<polyline points="${line(eia, y1)}" fill="none" stroke="#8a8880" stroke-dasharray="4 3" stroke-width="1.4"/>` +
      `<polyline points="${line(mine, upTo || y1)}" fill="none" stroke="#4FE3B0" stroke-width="2.2"/>` +
      `<line x1="${X(cur)}" x2="${X(cur)}" y1="6" y2="${H - 16}" stroke="rgba(255,255,255,.18)"/>` +
      `<text x="0" y="${Y(hi) + 8}">${fmt(hi)}</text><text x="0" y="${Y(lo)}">${fmt(lo)}</text>` +
      `<text x="${X(y0)}" y="${H - 2}" text-anchor="middle">${y0}</text><text x="${X(y1)}" y="${H - 2}" text-anchor="end">${y1}</text>` +
      `<text x="${W - 4}" y="14" text-anchor="end" style="fill:#4FE3B0">this run</text><text x="${W - 4}" y="26" text-anchor="end">EIA, dashed</text>`;
    $("co2-grade").innerHTML = badge(keyGrade("co2"));
  }

  // ---- playing ------------------------------------------------------------------------------------
  const wait = (ms, token) => new Promise((ok) => setTimeout(() => ok(token === S.token), ms));
  async function playYear(y, opts = {}) {
    const token = opts.token ?? ++S.token;
    const quiet = !!opts.quiet, dur = quiet ? 420 : REDUCED ? 1500 : 1600;
    const st = stepsFor(y);
    if (!quiet) { $("ticker").innerHTML = ""; G.labels = []; }
    if (!quiet && st.length) await shock(st, y, token);
    for (const s of st) {
      if (token !== S.token) return false;
      const moved = playStep(s, dur, quiet);
      setNodeValues(s, y);
      $("pass").textContent = `${y}, pass ${s.i}${s.s === "d" ? " demand" : " supply"}`;
      if (!quiet) narrate(s, moved, y);
      if (!(await wait(dur, token))) return false;
    }
    const last = st[st.length - 1];
    if (!quiet && last) {
      const passes = last.i;
      add(last.ok ? `<b>Agreed after ${passes} passes.</b> Every price and quantity moved less than EIA's tolerance on the last pass (largest price change ${pct(last.dp, 2).replace("+", "")}).`
        : `<b>Stopped after ${passes} passes</b> without passing EIA's test (largest price change ${pct(last.dp, 2).replace("+", "")}); NEMS moves on the same way.`, "ok");
      for (const m in MODS) if (m !== "economy" && !REDUCED) G.rings.push({ m, t0: performance.now(), dur: 1400, grow: 40, w: 2, a: 0.5, col: [79, 227, 176] });
      hero(`Settled for ${y}`, `${fmt(last.cur[idx("co2")])} Mt CO2, ${pct(rel(last.cur[idx("co2")], eiaAt("co2", y)))} vs EIA`, 2600);
    }
    paintSettled(y); paintCO2(opts.upTo);
    return true;
  }
  async function shock(st, y, token) {
    const lev = Object.entries(S.sc.levers || {});
    const words = lev.length ? lev.map(([k, v]) => LEVER_NAMES[k] ? LEVER_NAMES[k](v) : k).join(", ") : "no lever: EIA's own settings";
    const where = (S.sc.entered || []).map((m) => MODS[m].name).join(", ");
    add(`<b>${y}. The shock:</b> ${esc(words)}${where ? `, entering at ${esc(where)}` : ""}.`, "shock");
    const short = lev.map(([k, v]) => (SHORT[k] ? SHORT[k](v) : k)).join(" · ");
    const n = (S.sc.entered || []).length;
    hero(lev.length ? "The shock enters" : "No shock: EIA's settings", lev.length ? `${short}${n ? `, into ${n === 1 ? MODS[S.sc.entered[0]].name : `${n} modules`}` : ""}` : "Watch how little moves", 1700);
    if (!REDUCED) for (const m of S.sc.entered || []) {
      G.flash[m] = performance.now();
      for (let n = 0; n < 3; n++) G.rings.push({ m, t0: performance.now() + n * 260, dur: 1500, grow: Math.min(G.w, G.h) * 0.22, w: 4, a: 0.9, col: COL.c });
    }
    await wait(REDUCED ? 900 : 1800, token);
  }
  function hero(big, small, ms) {
    const h = $("hero");
    h.hidden = false; h.classList.remove("fade");
    h.innerHTML = `<b>${esc(big)}</b><span>${esc(small)}</span>`;
    clearTimeout(hero.t); hero.t = setTimeout(() => h.classList.add("fade"), ms);
  }

  async function play() {
    S.playing = true; setButtons();
    await playYear(S.year);
    S.playing = false; setButtons();
  }
  async function stepOnce() {
    // one recorded step at a time, for reading
    const st = stepsFor(S.year);
    if (S.k < 0) { $("ticker").innerHTML = ""; S.k = 0; add(`<b>${S.year}, stepping.</b> Press Step for each demand or supply answer.`, "shock"); }
    if (S.k >= st.length) { S.k = -1; paintSettled(S.year); return; }
    const s = st[S.k++];
    const moved = playStep(s, 1600, false); setNodeValues(s, S.year); narrate(s, moved, S.year);
    $("pass").textContent = `${S.year}, pass ${s.i}${s.s === "d" ? " demand" : " supply"}`;
  }
  async function lapse() {
    const token = ++S.token; S.lapse = true; setButtons();
    $("ticker").innerHTML = ""; add("<b>Time-lapse.</b> Every year's real passes, 2027 to 2050, sped up. The CO2 line fills in as each year settles.", "shock");
    for (let y = S.meta.years[0]; y <= S.meta.years[1]; y++) {
      S.year = y; $("year").value = y; $("year-out").textContent = y; $("play").textContent = `Play ${y}`;
      if (!(await playYear(y, { quiet: true, token, upTo: y }))) break;
    }
    if (token === S.token) add(`<b>2050 reached.</b> ${fmt(S.sc.steps.filter((s) => s.s === "s").length)} supply passes in all, recorded from the run.`, "ok");
    S.lapse = false; setButtons();
  }
  function stop() { S.token++; S.playing = false; S.lapse = false; S.k = -1; G.parts = []; G.labels = []; setButtons(); }
  function setButtons() {
    $("play").disabled = S.playing || S.lapse; $("step").disabled = S.playing || S.lapse; $("lapse").textContent = S.lapse ? "Stop" : "Time-lapse to 2050";
  }

  // ---- scenarios ----------------------------------------------------------------------------------
  async function pick(id) {
    stop();
    if (!S.cache[id]) S.cache[id] = await fetch(`data/think/${id}.json`).then((r) => r.json());
    S.sc = S.cache[id];
    for (const b of document.querySelectorAll(".chip")) b.setAttribute("aria-pressed", String(b.dataset.id === id));
    if (S.sc.kind === "lever") $("lever").value = id; else $("lever").value = "";
    G.vals = {}; const st = stepsFor(S.year); if (st.length) setNodeValues(st[st.length - 1], S.year);
    paintSettled(S.year); paintCO2(); links(); legend(); writeHash();
    $("ticker").innerHTML = "";
    add(`<b>${esc(S.sc.label)}.</b> ${esc(S.sc.desc)} Press Play to watch ${S.year} converge.`, "");
    if (S.sc.fast) add(`<b>Trial file:</b> every sector ran on the stub, not EIA's ported code.${S.sc.left_out && S.sc.left_out.length ? ` Left out: ${S.sc.left_out.join(", ")}.` : ""}`, "shock");
  }
  function links() {
    const lev = S.sc.levers || {};
    const h = Object.entries(lev).map(([k, v]) => `${k}=${v}`);
    const story = { reference: "eia", fast: "fast", ai: "ai", gas: "gas", nuke: "nuke" }[S.sc.id];
    $("to2050").href = `2050.html#${[...h, `y=${S.year}`, ...(story ? [`s=${story}`] : [])].join("&")}`;
    $("toEngine").href = `engine3d.html#a=yours&y=${S.year}&yours=${encodeURIComponent(Object.entries(lev).map(([k, v]) => `${k}:${v}`).join(","))}`;
  }
  function legend() {
    const p = (S.sc.ported || []).map((m) => MODS[m].name).join(", ");
    $("legend").innerHTML = `<span><i style="background:rgb(${COL.q})"></i>quantities, demand to supply</span>` +
      `<span><i style="background:rgb(${COL.p})"></i>prices, supply to demand</span><span><i style="background:rgb(${COL.c})"></i>CO2</span>` +
      `<span><b class="dot" style="background:#2fc795"></b>ported from EIA's code${p ? ` (${p})` : ""}</span>` +
      `<span><b class="dot" style="border:1.5px dashed #E8A33D"></b>stand-in</span><span><b class="dot" style="border:1.5px dotted #77756e"></b>EIA's fixed path</span>` +
      `<span>Particle density: how big that step's change was (log scale). Numbers are the model's.</span>`;
  }
  function writeHash() { history.replaceState(null, "", `#s=${S.sc.id}&y=${S.year}`); }

  async function main() {
    const [meta, man, fid] = await Promise.all(["data/think/meta.json", "data/think/manifest.json", "data/fidelity.json"].map((u) => fetch(u).then((r) => r.json())));
    Object.assign(S, { meta, man, fid });
    const stories = man.scenarios.filter((s) => s.kind === "story"), levers = man.scenarios.filter((s) => s.kind === "lever");
    $("stories").innerHTML = stories.map((s) => `<button class="chip" type="button" data-id="${s.id}" aria-pressed="false" title="${esc(s.desc)}">${esc(s.label)}</button>`).join("");
    $("lever").innerHTML = `<option value="">${levers.length ? "Choose a lever" : "Lever runs still computing"}</option>` + levers.map((s) => `<option value="${s.id}">${esc(s.label)}</option>`).join("");
    $("stories").addEventListener("click", (e) => { const b = e.target.closest(".chip"); if (b) pick(b.dataset.id); });
    $("lever").addEventListener("change", (e) => { if (e.target.value) pick(e.target.value); });
    $("year").addEventListener("input", (e) => {
      stop(); S.year = +e.target.value; $("year-out").textContent = S.year; $("play").textContent = `Play ${S.year}`;
      G.vals = {}; const st = stepsFor(S.year); if (st.length) setNodeValues(st[st.length - 1], S.year);
      paintSettled(S.year); paintCO2(); links(); writeHash();
    });
    $("play").addEventListener("click", play);
    $("step").addEventListener("click", stepOnce);
    $("lapse").addEventListener("click", () => (S.lapse ? stop() : lapse()));
    $("about").textContent = `${meta.about} ${REDUCED ? "Reduced motion is on: no particles, the same numbers. " : ""}` +
      "Ported modules run EIA's own Fortran logic in Python, checked against EIA's code; stand-ins are fitted to EIA's published runs. The economy is EIA's published path in this view.";
    layout();
    let rt = 0; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(layout, 120); });
    if (!rafOn) { rafOn = true; requestAnimationFrame(loop); }
    const q = new URLSearchParams(location.hash.slice(1));
    const y = +q.get("y"); if (y >= meta.years[0] && y <= meta.years[1]) { S.year = y; $("year").value = y; $("year-out").textContent = y; $("play").textContent = `Play ${y}`; }
    const want = man.scenarios.find((s) => s.id === q.get("s")) || man.scenarios.find((s) => s.id === "fast") || man.scenarios[0];
    await pick(want.id);
    // the hero moment: play once on arrival, unless the visitor asked for less motion
    if (!REDUCED) setTimeout(() => { if (!S.playing && !S.lapse) play(); }, 700);
  }
  addEventListener("DOMContentLoaded", () => main().catch((e) => {
    console.error(e);
    document.querySelector(".stage").insertAdjacentHTML("beforeend", `<p style="position:absolute;inset:auto 16px 16px;color:#E8A33D">The recorded runs did not load (${esc(e.message)}). Serve the web folder and run scripts/think_runs.py.</p>`);
  }));
})();
