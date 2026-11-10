// "Your America in 2050": levers, plant map, energy river and household bill, every number graded.
// Data: data/ux2050/emulator.json (instant estimates), data/ux2050/plants.json (EIA's plant file),
// data/fidelity.json (grades). The real model runs through scripts/serve_2050.py when it is running.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const fmt = (v, d = 0) => Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

  // ---- levers: what the page shows; `key` is the emulator / server name ----------------------------
  const LEVERS = [
    { key: "carbon_price", py: "carbon_price", title: "Carbon price", lo: 0, hi: 200, step: 5,
      show: (v) => v ? `$${fmt(v)} per ton CO2` : "None (EIA)", ends: ["$0", "$200/t"] },
    { key: "ev_2035", py: "ev_share", title: "EV sales", lo: 0.25, hi: 1, step: 0.01,
      show: (v, off) => Math.abs(v - off) < 0.006 ? `${fmt(v * 100)}% of new cars in 2035 (EIA)` : `${fmt(v * 100)}% of new cars in 2035`, ends: ["25%", "100%"] },
    { key: "load_growth", py: "load_growth", title: "Data centers and new load", lo: 0, hi: 1000, step: 25,
      show: (v) => v ? `+${fmt(v)} TWh a year by 2050` : "EIA's growth only", ends: ["+0", "+1,000 TWh"] },
    { key: "building_code", py: "building_code", title: "Building codes", lo: 0, hi: 0.4, step: 0.05, realOnly: true,
      show: (v) => v ? `-${fmt(v * 100)}% heating and cooling, new buildings` : "EIA's codes", ends: ["EIA", "-40%"] },
    { key: "appliance_standard", py: "appliance_standard", title: "Appliance standards", lo: 0, hi: 0.4, step: 0.05, realOnly: true,
      show: (v) => v ? `Least efficient model ${fmt(v * 100)}% better` : "EIA's standards", ends: ["EIA", "+40%"] },
    { key: "coal_retirement", py: "coal_retirement", title: "Coal retirements", lo: 0, hi: 1, step: 0.05,
      show: (v) => v ? `${fmt(v * 100)}% of coal closed early by 2035` : "EIA's schedule", ends: ["EIA", "All"] },
    { key: "renewable_cost", py: "renewable_cost", title: "Wind and solar cost", lo: -1, hi: 1, step: 0.1,
      show: (v) => v === 0 ? "EIA's reference" : v < 0 ? `${fmt(-v * 100)}% toward EIA's low-cost case` : `${fmt(v * 100)}% toward EIA's high-cost case`, ends: ["Cheaper", "Pricier"] },
    { key: "gas_supply", py: "gas_supply", title: "Gas supply", lo: -1, hi: 1, step: 0.1,
      show: (v) => v === 0 ? "EIA's reference" : v < 0 ? `${fmt(-v * 100)}% toward EIA's scarce case` : `${fmt(v * 100)}% toward EIA's plentiful case`, ends: ["Scarce", "Plentiful"] },
    { key: "oil_price", py: "oil_price", title: "Oil price", lo: 0.5, hi: 2, step: 0.05,
      show: (v) => Math.abs(v - 1) < 1e-9 ? "EIA's Brent path" : `${fmt(v, 2)} x EIA's Brent path`, ends: ["Half", "Double"] },
    { key: "nuclear", py: "nuclear", title: "Nuclear", lo: 0.5, hi: 1.5, step: 0.05,
      show: (v) => Math.abs(v - 1) < 1e-9 ? "EIA's output" : `${fmt(v, 2)} x EIA's output by 2040`, ends: ["Half", "+50%"] },
  ];
  const STORIES = [
    { id: "eia", title: "EIA's reference", desc: "No new policy. EIA's AEO2026 counterfactual baseline, as published.", set: {} },
    { id: "fast", title: "Fast clean-up", desc: "A $100 carbon price, 90% EV sales by 2035, coal closed early, cheaper wind and solar, tighter buildings.",
      set: { carbon_price: 100, ev_2035: 0.9, coal_retirement: 0.8, renewable_cost: -1, building_code: 0.2, appliance_standard: 0.2 } },
    { id: "ai", title: "AI boom", desc: "Data centers add 600 TWh a year of demand by 2050, about 13% more electricity than EIA expects. Nothing else changes.",
      set: { load_growth: 600 } },
    { id: "gas", title: "Cheap gas, slow EVs", desc: "Plentiful shale gas, oil 25% cheaper, EV sales stuck at 35% of new cars.",
      set: { gas_supply: 1, oil_price: 0.75, ev_2035: 0.35 } },
    { id: "nuke", title: "Nuclear comeback", desc: "50% more nuclear output by 2040, a $50 carbon price, data centers adding 300 TWh.",
      set: { nuclear: 1.5, carbon_price: 50, load_growth: 300 } },
  ];

  const GROUP_COLOR = { coal: "#9b8f84", gas: "#E8A33D", oil: "#D0583F", nuclear: "#B48AE0", hydro: "#4C9BE8",
    wind: "#5DCAA5", solar: "#F2D04B", other: "#86B35E", storage: "#E07AAE" };
  const GROUP_LABEL = { coal: "Coal", gas: "Gas", oil: "Oil", nuclear: "Nuclear", hydro: "Hydro", wind: "Wind",
    solar: "Solar", other: "Bio, geo, waste", storage: "Batteries" };
  const POWER_KEY = { coal: "power_coal", gas: "power_gas", oil: "power_oil", nuclear: "power_nuclear", hydro: "power_hydro",
    wind: "power_wind", solar: "power_solar", other: "power_other" };

  // ---- grades -------------------------------------------------------------------------------------
  const RANK = { match: 3, within: 2, stand: 1 };
  const SECTOR_PART = { rs: "residential", cm: "commercial", in: "industrial", tr: "transportation" };
  const SUPPLY = ["stand:electricity", "stand:natural_gas", "stand:oil", "stand:coal", "stand:emissions"];
  function demandPart(sector, ported) {
    const name = SECTOR_PART[sector];
    return ported.includes(name) ? `port:${name}` : "stand:demand_stub";
  }
  function partsFor(key, ported) {
    const all = ["rs", "cm", "in", "tr"].map((s) => demandPart(s, ported));
    if (key === "co2") return [...all, ...SUPPLY];
    if (key === "co2_el") return [...all, "stand:electricity", "stand:natural_gas", "stand:coal", "stand:emissions"];
    let m = key.match(/^co2_(rs|cm|in|tr)$/);
    if (m) return [demandPart(m[1], ported), "stand:emissions"];
    if (key === "elec_sales_twh") return all;
    if (key === "price_electricity") return ["stand:electricity", ...all];
    if (key === "price_gas_home") return ["stand:natural_gas"];
    if (key === "price_gasoline" || key === "price_diesel") return ["stand:oil"];
    if (key === "bill") return [demandPart("rs", ported), "stand:electricity", "stand:natural_gas"];
    m = key.match(/^flow_\w+_(rs|cm|in|tr)$/);
    if (m) return [demandPart(m[1], ported)];
    return ["stand:electricity"];   // power-sector flows, losses, generation by fuel
  }
  // A number's grade: the weakest piece behind it (as scripts/fidelity.py does), plus the emulator's own error.
  function gradeOf(key, src) {
    const parts = partsFor(key, src.ported).map((p) => [p, S.fid.parts[p]]).filter(([, v]) => v);
    let worst = parts[0];
    for (const p of parts) if (RANK[p[1].grade] < RANK[worst[1].grade]) worst = p;
    const g = { grade: worst[1].grade, label: worst[1].label, why: `${worst[1].name}: ${worst[1].summary}` };
    if (src.kind === "emu") {
      const e = S.emu.error[key];
      g.emu = e ? `instant estimate, typically within ${fmtPct(e.mean_pct)} of a full fast-loop run (95% of checks within ${fmtPct(e.p95_pct)})` : "instant estimate";
      g.emuShort = e ? `est. ±${fmtPct(e.p95_pct)}` : "estimate";
    }
    return g;
  }
  const fmtPct = (p) => (p < 0.1 ? "0.1%" : p < 10 ? `${p.toFixed(1)}%` : `${Math.round(p)}%`);
  function badge(g) {
    const b = `<span class="g g-${g.grade}" title="${esc(g.why)}">${esc(g.label)}</span>`;
    return g.emu ? b + `<span class="g g-emu" title="${esc(g.emu)}">${esc(g.emuShort)}</span>` : b;
  }
  const DATA_BADGE = () => `<span class="g g-data" title="${esc("Read from EIA's AEO2026 input files (the EMM plant file), not modeled. Units EIA lists as planned appear in their planned year.")}">EIA data</span>`;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ---- state --------------------------------------------------------------------------------------
  const S = { emu: null, plants: null, fid: null, x: {}, year: 2035, story: "eia", out: null, src: null,
    real: {}, server: false, job: null };

  function defaults() {
    const x = {};
    for (const l of LEVERS) x[l.key] = l.key === "ev_2035" ? S.emu.levers.ev_2035.off : (S.emu.levers[l.key] ? S.emu.levers[l.key].off : 0);
    return x;
  }
  const sig = (x) => LEVERS.map((l) => `${l.key}=${(+x[l.key]).toFixed(3)}`).join("&");

  // ---- the emulator -------------------------------------------------------------------------------
  // The polynomial, shifted so EIA's settings return the reference run exactly (the fit was measured that way).
  function emulate(x) {
    const raw = poly(x);
    if (!S.refPoly) S.refPoly = poly(Object.fromEntries(Object.entries(S.emu.levers).map(([n, L]) => [n, L.off])));
    const out = {};
    for (const k in raw) out[k] = raw[k].map((v, j) => v - S.refPoly[k][j] + S.emu.fast_reference[k][j]);
    for (const k in out) if (!k.startsWith("co2")) out[k] = out[k].map((v) => Math.max(0, v));   // a polynomial can dip below zero
    return out;
  }
  function poly(x) {
    const names = Object.keys(S.emu.levers);
    const z = names.map((n) => { const L = S.emu.levers[n]; return 2 * (x[n] - L.low) / (L.high - L.low) - 1; });
    const f = S.emu.terms.map((t) => t.reduce((a, i) => a * z[i], 1));
    const out = {};
    for (const [k, coef] of Object.entries(S.emu.coef)) {
      const ny = coef[0].length, y = new Array(ny).fill(0);
      for (let t = 0; t < coef.length; t++) { const ft = f[t]; if (ft === 0) continue; const row = coef[t]; for (let j = 0; j < ny; j++) y[j] += row[j] * ft; }
      out[k] = y;
    }
    return out;
  }

  function compute() {
    const s = sig(S.x);
    if (S.real[s]) {
      S.out = S.real[s].result; S.src = { kind: "real", ported: S.real[s].ported, job: S.real[s] };
    } else {
      S.out = emulate(S.x); S.src = { kind: "emu", ported: [] };
    }
  }
  const yi = (y) => S.emu.years.indexOf(y);
  const at = (k, y = S.year) => S.out[k][yi(y)];
  const eia = (k, y = S.year) => S.emu.eia[k][yi(y)];

  // ---- levers UI ----------------------------------------------------------------------------------
  function leverGrade(l) {
    const tbl = S.emu.lever_grades[S.src && S.src.kind === "real" ? "real" : "instant"];
    const row = tbl.find((r) => r.name === l.py);
    if (l.realOnly && !(S.src && S.src.kind === "real"))
      return `<span class="g g-none" title="${esc("The instant estimate leaves this lever out: it edits input tables of EIA's ported residential and commercial routines, which only the real run has. Press Run the real model.")}">real run only</span>`;
    const cls = row.grade === "ported" ? "match" : row.grade === "own model" ? "within" : "stand";
    return `<span class="g g-${cls}" title="${esc(row.why + ". Moves: " + row.moves)}">${esc(row.grade)}</span>`;
  }
  function buildLevers() {
    $("levers").innerHTML = LEVERS.map((l) => `
      <div class="lever${l.realOnly ? " real-only" : ""}" data-k="${l.key}">
        <div class="lever-top"><label for="lv-${l.key}">${l.title}</label><output id="lv-${l.key}-out"></output></div>
        <input id="lv-${l.key}" type="range" min="${l.lo}" max="${l.hi}" step="${l.step}">
        <div class="lever-foot"><span class="ends">${l.ends[0]}</span><span id="lv-${l.key}-g"></span><span class="ends">${l.ends[1]}</span></div>
      </div>`).join("");
    for (const l of LEVERS) {
      $(`lv-${l.key}`).addEventListener("input", (e) => { S.x[l.key] = +e.target.value; S.story = null; update(); });
    }
    $("stories").innerHTML = STORIES.map((s) => `<button class="story" type="button" data-id="${s.id}" aria-pressed="false">${s.title}</button>`).join("") + `<p id="story-desc" class="story-desc"></p>`;
    $("stories").addEventListener("click", (e) => {
      const b = e.target.closest(".story"); if (!b) return;
      const s = STORIES.find((t) => t.id === b.dataset.id);
      S.x = Object.assign(defaults(), s.set); S.story = s.id; update();
    });
  }
  function paintLevers() {
    for (const l of LEVERS) {
      const off = l.key === "ev_2035" ? S.emu.levers.ev_2035.off : null;
      $(`lv-${l.key}`).value = S.x[l.key];
      $(`lv-${l.key}-out`).textContent = l.show(S.x[l.key], off);
      $(`lv-${l.key}-g`).innerHTML = leverGrade(l);
    }
    const missing = LEVERS.filter((l) => l.realOnly && S.x[l.key] > 0);
    const n = $("instant-note");
    if (S.src.kind === "emu" && missing.length) {
      n.hidden = false;
      n.textContent = `The instant estimate leaves out ${missing.map((l) => l.title.toLowerCase()).join(" and ")}. Run the real model to include them.`;
    } else n.hidden = true;
    for (const b of document.querySelectorAll(".story")) b.setAttribute("aria-pressed", String(b.dataset.id === S.story));
    const st = STORIES.find((s) => s.id === S.story);
    $("story-desc").textContent = st ? st.desc : "Your own mix.";
  }

  // ---- headline numbers ---------------------------------------------------------------------------
  function stat(title, key, value, unit, ref, digits, lowerIsGood) {
    const d = value - ref, pct = ref ? (100 * d) / ref : 0;
    const dir = Math.abs(pct) < 0.5 ? "" : (d > 0) === lowerIsGood ? "up" : "down";
    const word = Math.abs(pct) < 0.5 ? "about the same as EIA" : `${d > 0 ? "+" : ""}${fmt(pct, Math.abs(pct) < 10 ? 1 : 0)}% vs EIA (${fmt(ref, digits)})`;
    return `<div class="stat"><div class="k">${title}, ${S.year}</div>
      <div class="v">${fmt(value, digits)} <small>${unit}</small></div>
      <div class="d ${dir}">${word}</div><div class="grades">${badge(gradeOf(key, S.src))}</div></div>`;
  }
  function paintStats() {
    $("stats").innerHTML =
      stat("US energy CO2", "co2", at("co2"), "million t", eia("co2"), 0, true) +
      stat("Electricity price", "price_electricity", at("price_electricity"), "¢/kWh", eia("price_electricity"), 1, true) +
      stat("Gasoline", "price_gasoline", at("price_gasoline"), "$/gal", eia("price_gasoline"), 2, true) +
      stat("Electricity used", "elec_sales_twh", at("elec_sales_twh"), "TWh", eia("elec_sales_twh"), 0, true);
  }

  // ---- the map ------------------------------------------------------------------------------------
  const M = { proj: null, pts: null, w: 0, h: 0, dpr: 1, nation: null, states: null, delaunay: null, regionCenters: null };

  async function loadGeo() {
    const us = await (await fetch("https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/states-10m.json")).json();
    const keep = us.objects.states.geometries.filter((g) => !["02", "15", "72", "60", "66", "69", "78"].includes(g.id));
    M.nation = topojson.merge(us, keep);
    M.states = topojson.mesh(us, { type: "GeometryCollection", geometries: keep }, (a, b) => a !== b);
  }

  function layoutMap() {
    const box = $("map").getBoundingClientRect();
    M.w = Math.max(200, box.width); M.h = Math.max(150, box.height); M.dpr = window.devicePixelRatio || 1;
    for (const id of ["map-bg", "map-fg"]) { const c = $(id); c.width = M.w * M.dpr; c.height = M.h * M.dpr; }
    M.proj = d3.geoAlbers().fitExtent([[8, 8], [M.w - 8, M.h - 8]], M.nation);
    const rows = S.plants.rows;
    M.pts = new Float32Array(rows.length * 2);
    rows.forEach((r, i) => { const p = M.proj([r[0], r[1]]) || [-99, -99]; M.pts[2 * i] = p[0]; M.pts[2 * i + 1] = p[1]; });
    M.delaunay = new d3.Delaunay(M.pts);
    drawRegions();
  }

  // Region shading: each point of the map takes the region of its nearest plant. EIA publishes the 25
  // regions as utility territories, not lines on a map, so the borders are approximate and the page says so.
  function drawRegions() {
    const c = $("map-bg").getContext("2d");
    c.setTransform(M.dpr, 0, 0, M.dpr, 0, 0);
    c.clearRect(0, 0, M.w, M.h);
    const path = d3.geoPath(M.proj, c);
    c.save(); c.beginPath(); path(M.nation); c.clip();
    const vor = M.delaunay.voronoi([0, 0, M.w, M.h]);
    const rows = S.plants.rows, tint = ["#1a212b", "#1e2630", "#182029", "#202833", "#1c232d"];
    for (let i = 0; i < rows.length; i++) { c.beginPath(); vor.renderCell(i, c); c.fillStyle = tint[rows[i][4] % 5]; c.fill(); }
    // borders where neighbouring cells sit in different regions
    c.beginPath();
    const { halfedges, triangles } = M.delaunay, cc = vor.circumcenters;
    for (let e = 0; e < halfedges.length; e++) {
      const o = halfedges[e]; if (o < e) continue;
      const a = triangles[e], b = triangles[e % 3 === 2 ? e - 2 : e + 1];
      if (rows[a][4] === rows[b][4]) continue;
      const t1 = Math.floor(e / 3), t2 = Math.floor(o / 3);
      c.moveTo(cc[2 * t1], cc[2 * t1 + 1]); c.lineTo(cc[2 * t2], cc[2 * t2 + 1]);
    }
    c.strokeStyle = "#3b4554"; c.lineWidth = 1; c.stroke();
    c.restore();
    c.beginPath(); path(M.states); c.strokeStyle = "#ffffff12"; c.lineWidth = 0.6; c.stroke();
    c.beginPath(); path(M.nation); c.strokeStyle = "#4a5361"; c.lineWidth = 1; c.stroke();
    // region labels at the capacity-weighted centre of their plants
    const sum = {};
    rows.forEach((r, i) => { const s = sum[r[4]] || (sum[r[4]] = [0, 0, 0]); s[0] += M.pts[2 * i] * r[2]; s[1] += M.pts[2 * i + 1] * r[2]; s[2] += r[2]; });
    M.regionCenters = sum;
    c.font = "600 10px system-ui,sans-serif"; c.fillStyle = "#ffffff40"; c.textAlign = "center";
    for (const [reg, s] of Object.entries(sum)) c.fillText(S.plants.regions[reg - 1], s[0] / s[2], s[1] / s[2]);
  }

  // How hard each fuel's plants run in a year: each plant's own capacity factor times the run's fuel use
  // for that fuel relative to 2025, spread over the fleet that is online (EIA's schedule).
  function utilization(y) {
    const P = S.plants, j = P.years.indexOf(y), j0 = P.years.indexOf(2025), k = {};
    for (const g of P.groups) {
      const key = POWER_KEY[g];
      if (!key) { k[g] = 1; continue; }
      const q0 = at(key, 2025), q = at(key, y), f0 = P.fleet_mw_cf[g][j0], f = P.fleet_mw_cf[g][j];
      k[g] = q0 > 0 && f > 0 ? (q / q0) * (f0 / f) : 0;
    }
    return k;
  }

  function drawPlants() {
    const c = $("map-fg").getContext("2d"), rows = S.plants.rows, groups = S.plants.groups;
    c.setTransform(M.dpr, 0, 0, M.dpr, 0, 0); c.clearRect(0, 0, M.w, M.h);
    const k = utilization(S.year), y = S.year;
    const scale = Math.sqrt(M.w / 900) * 0.2;
    const cap = {}, served = {}, wanted = {};
    // draw big plants first so small ones stay visible on top
    const order = M.order || (M.order = rows.map((_, i) => i).sort((a, b) => rows[b][2] - rows[a][2]));
    for (const i of order) {
      const r = rows[i];
      if (r[5] > y || r[6] <= y) continue;
      const g = groups[r[3]], want = r[7] * k[g], u = Math.min(1, want);
      cap[g] = (cap[g] || 0) + r[2]; served[g] = (served[g] || 0) + u * r[2]; wanted[g] = (wanted[g] || 0) + want * r[2];
      c.globalAlpha = 0.12 + 0.88 * Math.sqrt(Math.max(0, u));
      c.fillStyle = GROUP_COLOR[g];
      c.beginPath(); c.arc(M.pts[2 * i], M.pts[2 * i + 1], Math.max(0.8, Math.sqrt(r[2]) * scale), 0, 6.2832); c.fill();
    }
    c.globalAlpha = 1;
    M.capacity = cap; M.k = k;
    // generation the run asks of a fuel beyond what its plants on the map can give comes from plants the
    // model builds later, which are not in EIA's plant file and so have no dot
    const off = Object.keys(POWER_KEY).filter((g) => wanted[g] > served[g] * 1.02)
      .map((g) => `${GROUP_LABEL[g].toLowerCase()} ${fmt(100 * (1 - served[g] / wanted[g]))}%`);
    $("map-note").innerHTML = `Every dot is a unit in EIA's plant file ${DATA_BADGE()}: ${fmt(S.plants.drawn)} of ${fmt(S.plants.units_in_file)} units (${S.plants.not_drawn.no_coordinates} have no coordinates), appearing and retiring on EIA's schedule. ` +
      `<b>Plants change how much they run, not whether they exist.</b> Brightness is each plant's own capacity factor scaled so its fuel matches the run's national total ${badge(gradeOf("power_gas", S.src))}; there is no plant-by-plant dispatch. Region borders are approximate (nearest plant).` +
      (off.length ? ` Output from plants the model builds after EIA's list ends has no dot: ${off.join(", ")} of ${y} output.` : "");
  }

  function legend() {
    $("legend").innerHTML = S.plants.groups.map((g) => `<span><i style="background:${GROUP_COLOR[g]}"></i>${GROUP_LABEL[g]}</span>`).join("") +
      `<span>size: capacity, brightness: how hard it runs</span>`;
  }

  function hover(ev) {
    const box = $("map").getBoundingClientRect(), x = ev.clientX - box.left, y = ev.clientY - box.top;
    const i = M.delaunay.find(x, y), r = S.plants.rows[i];
    const tip = $("tip");
    if (!r || Math.hypot(M.pts[2 * i] - x, M.pts[2 * i + 1] - y) > 40) { tip.hidden = true; return; }
    const g = S.plants.groups[r[3]], reg = S.plants.regions[r[4] - 1], k = (M.k || {})[g] || 1;
    const live = r[5] <= S.year && r[6] > S.year;
    // the region's capacity by fuel this year
    const byG = {};
    S.plants.rows.forEach((p) => { if (p[4] === r[4] && p[5] <= S.year && p[6] > S.year) byG[S.plants.groups[p[3]]] = (byG[S.plants.groups[p[3]]] || 0) + p[2]; });
    const top = Object.entries(byG).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([gg, mw]) => `${GROUP_LABEL[gg]} ${fmt(mw / 1000, 1)} GW`).join(", ");
    tip.innerHTML = `<b>${GROUP_LABEL[g]}, ${fmt(r[2])} MW</b> ${DATA_BADGE()}
      <div>${live ? `Runs about ${fmt(100 * Math.min(1, r[7] * k))}% of the year in ${S.year}` : r[5] > S.year ? `Planned, online ${r[5]}` : `Retired ${r[6]}`} ${live ? badge(gradeOf("power_gas", S.src)) : ""}</div>
      <div>Online ${r[5]}${r[6] < 9999 ? `, retires ${r[6]}` : ""}</div>
      <div style="margin-top:4px"><b>Region ${reg}</b> (${r[4]} of 25): ${top}</div>`;
    tip.hidden = false;
    tip.style.left = Math.min(x + 14, M.w - 290) + "px"; tip.style.top = Math.min(y + 10, M.h - 110) + "px";
  }

  // ---- the energy river ---------------------------------------------------------------------------
  const SRC = [["petroleum", "Petroleum", "#D0583F"], ["gas", "Natural gas", "#E8A33D"], ["coal", "Coal", "#9b8f84"],
    ["nuclear", "Nuclear", "#B48AE0"], ["renewables", "Renewables", "#5DCAA5"]];
  const USE = [["rs", "Homes"], ["cm", "Businesses"], ["in", "Industry"], ["tr", "Vehicles"]];
  function paintRiver() {
    const svg = d3.select("#river"), W = $("river").clientWidth, H = $("river").clientHeight;
    svg.attr("viewBox", `0 0 ${W} ${H}`).selectAll("*").remove();
    const nodes = [...SRC.map(([id, name, c]) => ({ id, name, c })), { id: "el", name: "Power plants", c: "#7FB2F0" },
      ...USE.map(([id, name]) => ({ id, name, c: "#c9c6bd" })), { id: "loss", name: "Losses", c: "#55524c" }];
    const links = [];
    const add = (s, t, key) => { const v = at(key); if (v > 0.02) links.push({ source: s, target: t, value: v, key }); };
    for (const [s] of SRC) if (s !== "nuclear") for (const [u] of USE) add(s, u, `flow_${s}_${u}`);
    for (const [s] of SRC) add(s, "el", `flow_${s}_el`);
    for (const [u] of USE) add("el", u, `flow_electricity_${u}`);
    add("el", "loss", "flow_losses");
    const used = new Set(links.flatMap((l) => [l.source, l.target]));
    const sk = d3.sankey().nodeId((d) => d.id).nodeWidth(10).nodePadding(10).nodeSort(null)
      .extent([[1, 6], [W - 1, H - 6]]);
    const g = sk({ nodes: nodes.filter((n) => used.has(n.id)).map((d) => ({ ...d })), links: links.map((d) => ({ ...d })) });
    const colorOf = (n) => n.c;
    svg.append("g").attr("fill", "none").selectAll("path").data(g.links).join("path")
      .attr("d", d3.sankeyLinkHorizontal()).attr("stroke", (d) => colorOf(d.source)).attr("stroke-opacity", 0.38)
      .attr("stroke-width", (d) => Math.max(1, d.width))
      .append("title").text((d) => `${d.source.name} to ${d.target.name}: ${fmt(d.value, 2)} quads in ${S.year} (EIA: ${fmt(eia(d.key), 2)}). Grade: ${gradeOf(d.key, S.src).label}`);
    const node = svg.append("g").attr("class", "node").selectAll("g").data(g.nodes).join("g");
    node.append("rect").attr("x", (d) => d.x0).attr("y", (d) => d.y0).attr("width", (d) => d.x1 - d.x0)
      .attr("height", (d) => Math.max(1, d.y1 - d.y0)).attr("fill", colorOf)
      .append("title").text((d) => `${d.name}: ${fmt(d.value, 1)} quads`);
    node.append("text").attr("x", (d) => (d.x0 < W / 2 ? d.x1 + 5 : d.x0 - 5)).attr("y", (d) => (d.y0 + d.y1) / 2)
      .attr("dy", "0.35em").attr("text-anchor", (d) => (d.x0 < W / 2 ? "start" : "end"))
      .text((d) => `${d.name} ${fmt(d.value, 1)}`);
    // the river's weakest number decides its badge
    const keys = g.links.map((l) => l.key);
    let w = gradeOf(keys[0], S.src);
    for (const k of keys) { const gg = gradeOf(k, S.src); if (RANK[gg.grade] < RANK[w.grade]) w = gg; }
    $("river-grade").innerHTML = badge(w) + ` <span class="g g-none" title="${esc("Each band's own grade is in its hover text. Bands into homes and businesses are ported EIA code in a real run; power plants and fuels are stand-ins.")}">per band on hover</span>`;
  }

  // ---- the bill -----------------------------------------------------------------------------------
  function paintBill() {
    const v = at("bill"), r = eia("bill"), d = v - r;
    $("bill-now").textContent = `$${fmt(v)}`;
    $("bill-vs").textContent = Math.abs(d) < 5 ? `About the same as EIA's reference ($${fmt(r)}).` :
      `$${fmt(Math.abs(d))} ${d > 0 ? "more" : "less"} than EIA's reference ($${fmt(r)}).`;
    $("bill-grade").innerHTML = badge(gradeOf("bill", S.src));
    const svg = d3.select("#bill-chart"), W = $("bill-chart").clientWidth, H = $("bill-chart").clientHeight;
    svg.attr("viewBox", `0 0 ${W} ${H}`).selectAll("*").remove();
    const ys = S.emu.years.filter((y) => y >= 2025), a = ys.map((y) => at("bill", y)), b = ys.map((y) => eia("bill", y));
    const lo = Math.min(...a, ...b), hi = Math.max(...a, ...b), pad = (hi - lo) * 0.15 + 20;
    const x = d3.scaleLinear([2025, 2050], [34, W - 8]), y = d3.scaleLinear([lo - pad, hi + pad], [H - 16, 6]);
    svg.append("g").selectAll("text").data(y.ticks(3)).join("text").attr("x", 0).attr("y", (t) => y(t) + 3).text((t) => `$${fmt(t)}`);
    svg.append("g").selectAll("text").data([2025, 2035, 2050]).join("text").attr("x", (t) => x(t)).attr("y", H - 2).attr("text-anchor", (t) => (t === 2050 ? "end" : "middle")).text((t) => t);
    const line = d3.line().x((_, i) => x(ys[i])).y((d) => y(d));
    svg.append("path").attr("d", line(b)).attr("fill", "none").attr("stroke", "#a9a79f").attr("stroke-dasharray", "4 3").attr("stroke-width", 1.5);
    svg.append("path").attr("d", line(a)).attr("fill", "none").attr("stroke", "#5DCAA5").attr("stroke-width", 2.2);
    svg.append("line").attr("x1", x(S.year)).attr("x2", x(S.year)).attr("y1", 6).attr("y2", H - 16).attr("stroke", "#ffffff30");
    svg.append("circle").attr("cx", x(S.year)).attr("cy", y(v)).attr("r", 3.5).attr("fill", "#5DCAA5");
    svg.append("text").attr("x", W - 8).attr("y", y(b[b.length - 1]) + (b[b.length - 1] > a[a.length - 1] ? -6 : 12)).attr("text-anchor", "end").text("EIA");
    svg.append("text").attr("x", W - 8).attr("y", y(a[a.length - 1]) + (a[a.length - 1] >= b[b.length - 1] ? -6 : 12)).attr("text-anchor", "end").attr("fill", "#5DCAA5").style("fill", "#5DCAA5").text("You");
  }

  // ---- mode, real runs ----------------------------------------------------------------------------
  function paintMode() {
    const m = $("mode");
    if (S.src.kind === "real") {
      m.className = "mode mode-real"; m.textContent = "Real model run";
      m.title = `run_model.run with ${S.src.ported.join(", ")} through EIA's ported routines, supply on the stand-in. Took ${fmt(S.src.job.elapsed_s / 60, 1)} min.`;
    } else if (S.job) {
      m.className = "mode mode-busy"; m.textContent = "Instant estimate, real run going";
      m.title = "The numbers shown are the emulator's until the real run finishes.";
    } else {
      m.className = "mode mode-emu"; m.textContent = "Instant estimate";
      m.title = `An emulator fitted to ${S.emu.runs} runs of the fast loop (every sector on a stub, supply on the stand-in). Each number's purple tag gives its error on runs the fit never saw.`;
    }
    const btn = $("run"), note = $("run-note");
    if (!S.server) {
      btn.disabled = true;
      note.innerHTML = "The real model runs on your own computer: <code>python scripts/serve_2050.py</code>, then open this page from it. The preview site shows instant estimates only.";
    } else if (S.job) {
      btn.disabled = true; note.textContent = `Running the real model... ${fmt(S.job.elapsed || 0)} s. EIA's ported residential, commercial and transportation routines run every year to 2050.`;
    } else if (S.src.kind === "real") {
      btn.disabled = true; note.textContent = "Showing the real run for these levers. Move a lever to go back to instant estimates.";
    } else {
      btn.disabled = false; note.textContent = "Runs EIA's ported residential, commercial and transportation code with these levers, on this computer. Takes several minutes; the page keeps the result for these exact settings.";
    }
  }
  async function startRun() {
    const levers = Object.fromEntries(LEVERS.map((l) => [l.key, S.x[l.key]]));
    const res = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ levers }) });
    const body = await res.json();
    if (!res.ok) { $("run-note").textContent = body.error || "The server refused the run."; return; }
    S.job = { id: body.id, sig: sig(S.x), elapsed: 0 }; paintMode();
    const poll = async () => {
      const j = await (await fetch(`/api/run/${S.job.id}`)).json();
      S.job.elapsed = j.elapsed_s;
      if (j.status === "running") { paintMode(); setTimeout(poll, 3000); return; }
      const s = S.job.sig; S.job = null;
      if (j.status === "done") { S.real[s] = j; }
      else $("run-note").textContent = `The real run failed: ${j.error}`;
      update();
    };
    setTimeout(poll, 2000);
  }

  // ---- address, update ----------------------------------------------------------------------------
  function writeHash() {
    const d = defaults(), parts = LEVERS.filter((l) => Math.abs(S.x[l.key] - d[l.key]) > 1e-9).map((l) => `${l.key}=${+(+S.x[l.key]).toFixed(3)}`);
    parts.push(`y=${S.year}`); if (S.story) parts.push(`s=${S.story}`);
    history.replaceState(null, "", "#" + parts.join("&"));
  }
  function readHash() {
    S.x = defaults();
    const kvs = location.hash.slice(1).split("&");
    const st = STORIES.find((t) => kvs.includes(`s=${t.id}`));
    if (st) Object.assign(S.x, st.set);   // a story's levers, then any the address sets itself
    for (const kv of kvs) {
      const [k, v] = kv.split("=");
      if (k === "y" && +v >= 2027 && +v <= 2050) S.year = +v;
      else if (k === "s") S.story = v;
      else { const l = LEVERS.find((t) => t.key === k); if (l && isFinite(+v)) S.x[k] = Math.min(l.hi, Math.max(l.lo, +v)); }
    }
  }

  let raf = 0;
  function update() {
    compute();
    paintLevers(); paintMode(); paintStats();
    for (const el of document.querySelectorAll(".yr")) el.textContent = S.year;
    $("map-year").textContent = S.year; $("year").value = S.year;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => { drawPlants(); paintRiver(); paintBill(); });
    writeHash();
  }

  async function main() {
    const [emu, plants, fid] = await Promise.all(["data/ux2050/emulator.json", "data/ux2050/plants.json", "data/fidelity.json"]
      .map((u) => fetch(u).then((r) => r.json())));
    Object.assign(S, { emu, plants, fid });
    await loadGeo();
    buildLevers(); legend(); readHash();
    layoutMap(); update();
    $("year").addEventListener("input", (e) => { S.year = +e.target.value; update(); });
    $("map").addEventListener("mousemove", hover);
    $("map").addEventListener("mouseleave", () => { $("tip").hidden = true; });
    let timer = null;
    $("play").addEventListener("click", () => {
      if (timer) { clearInterval(timer); timer = null; $("play").textContent = "Play"; return; }
      if (S.year >= 2050) S.year = 2026;
      $("play").textContent = "Pause";
      timer = setInterval(() => { S.year += 1; update(); if (S.year >= 2050) { clearInterval(timer); timer = null; $("play").textContent = "Play"; } }, 450);
    });
    $("run").addEventListener("click", startRun);
    let rt = 0;
    addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { layoutMap(); update(); }, 150); });
    paintMode();
  }
  // The real model needs scripts/serve_2050.py; the static preview has no /api, so the button explains instead.
  async function checkServer() {
    try {
      const h = await Promise.race([fetch("/api/health", { cache: "no-store" }), new Promise((_, no) => setTimeout(() => no(new Error("timeout")), 2500))]);
      S.server = h.ok && (await h.json()).ok === true;
    } catch (e) { S.server = false; }
    if (S.out) paintMode();
  }
  addEventListener("DOMContentLoaded", () => main().then(checkServer).catch((e) => {
    document.querySelector(".center").insertAdjacentHTML("afterbegin", `<p class="notice">The page could not load its data: ${esc(e.message)}. It needs a web server (python scripts/serve_2050.py).</p>`);
    console.error(e);
  }));
})();
