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
    { id: "eia", title: "EIA's reference", desc: "No new policy: EIA's own forecast, as published in its Annual Energy Outlook 2026.", set: {} },
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
    if (key === "power_bill_month") return [demandPart("rs", ported), "stand:electricity"];
    if (key === "heat_bill_month") return [demandPart("rs", ported), "stand:natural_gas", "stand:oil"];
    if (key === "price_el_home" || key === "home_kwh_month") return key === "price_el_home" ? ["stand:electricity"] : [demandPart("rs", ported)];
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
  // One dot per number (site.js): green EIA's own code, amber our estimate, grey EIA's published number.
  function badge(g) { return NEMSDot.dot(g.grade, `${g.why}${g.emu ? `. Shown as an ${g.emu}` : ""}`); }
  const DATA_BADGE = () => NEMSDot.dot("data", "From EIA's plant list (AEO2026 input files), not modeled. Plants EIA lists as planned appear in their planned year.");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ---- state --------------------------------------------------------------------------------------
  const S = { emu: null, plants: null, fid: null, x: {}, year: 2035, story: "eia", out: null, src: null,
    real: {}, server: false, key: false, job: null };
  S.year = 2050;   // the page is about 2050: it opens there

  const defaults = () => UX2050.defaults(S.emu);
  const sig = UX2050.sig;
  const emulate = (x) => UX2050.emulate(S.emu, x);   // web/ux2050_model.js, shared with engine3d.html

  function compute() {
    const s = sig(S.x);
    if (!S.real[s]) { const kept = UX2050.loadReal(S.x); if (kept) S.real[s] = kept; }   // a run from earlier in this tab
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
      return `<span class="ends" title="${esc("The instant estimate leaves this lever out: it changes EIA's own building code, which only the full run has. Press Run the full model.")}">full run only</span>`;
    return NEMSDot.dot(row.grade === "ported" ? "match" : "stand", `${row.why}. Moves: ${row.moves}`);
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
      n.textContent = `The instant numbers leave out ${missing.map((l) => l.title.toLowerCase()).join(" and ")}. Run the full model to include them.`;
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
  // Household terms first. Each card: the number, what it means in one line, how it compares with EIA's
  // forecast, the dot, and the basis behind it (a fold-out, so it works on touch screens too).
  const EPA_T_PER_CAR = 4.6;   // EPA, "Greenhouse Gas Emissions from a Typical Passenger Vehicle": 4.6 t CO2 a year
  const has = (k) => S.out && S.out[k] && S.emu.eia[k];
  function card(o) {
    return `<div class="hh"><div class="k">${o.title} ${o.dot}</div><div class="v">${o.value}</div><div class="m">${o.line}</div>` +
      `<div class="d ${o.dir}">${o.vs}</div><details class="basis"><summary>How we got this</summary>${o.basis}</details></div>`;
  }
  const dirOf = (d, ref) => (Math.abs(d) < 0.005 * Math.abs(ref) ? "" : d > 0 ? "up" : "down");
  function moneyVs(d, ref, unit, cents) {
    if (Math.abs(d) < 0.005 * Math.abs(ref)) return "About the same as EIA's forecast";
    const amt = cents ? `${fmt(Math.abs(d) * 100)}¢` : `$${fmt(Math.abs(d))}`;
    return `${amt} ${unit} ${d > 0 ? "more" : "less"} than EIA's forecast`;
  }
  function paintStats() {
    const y = S.year, out = [];
    if (has("power_bill_month")) {
      const v = at("power_bill_month"), e = eia("power_bill_month");
      out.push(card({ title: "Home power bill", dot: badge(gradeOf("power_bill_month", S.src)), value: `$${fmt(v)}<small> a month</small>`,
        line: `A typical home's electricity bill in ${y}.`, vs: moneyVs(v - e, e, "a month"), dir: dirOf(v - e, e),
        basis: `The average US home's electricity use (about ${fmt(at("home_kwh_month"))} kWh a month, which includes charging an electric car at home, as EIA counts it) times the home power price (${fmt(at("price_el_home"), 1)}¢ per kWh). Both from the model; the number of homes from EIA. 2024 dollars.` }));
    }
    { const v = at("price_gasoline"), e = eia("price_gasoline");
      out.push(card({ title: "Gas at the pump", dot: badge(gradeOf("price_gasoline", S.src)), value: `$${fmt(v, 2)}<small> a gallon</small>`,
        line: `The average US price of a gallon of gasoline in ${y}.`, vs: moneyVs(v - e, e, "a gallon", true), dir: dirOf(v - e, e),
        basis: "The model's average US gasoline price, in 2024 dollars, including any carbon price you set." })); }
    if (has("heat_bill_month")) {
      const v = at("heat_bill_month"), e = eia("heat_bill_month");
      out.push(card({ title: "Home heating fuel", dot: badge(gradeOf("heat_bill_month", S.src)), value: `$${fmt(v)}<small> a month</small>`,
        line: "What a typical home spends on gas, propane and heating oil.", vs: moneyVs(v - e, e, "a month"), dir: dirOf(v - e, e),
        basis: "The average US home's spending on natural gas, propane, heating oil, kerosene and coal (for heat, hot water and cooking): the model's home use of each fuel times its home price, over EIA's number of homes. 2024 dollars." }));
    }
    { const v = at("co2"), e = eia("co2"), d = v - e, cars = Math.abs(d) / EPA_T_PER_CAR;
      out.push(card({ title: "CO2 from energy", dot: badge(gradeOf("co2", S.src)), value: `${fmt(v / 1000, 2)}<small> billion tons</small>`,
        line: `All the CO2 from US energy use in ${y}.`, dir: dirOf(d, e),
        vs: Math.abs(d) < 0.005 * e ? "About the same as EIA's forecast" :
          `${fmt(Math.abs(d))} million tons ${d > 0 ? "more" : "less"} than EIA's: like ${d > 0 ? "adding" : "taking"} ${fmt(cars)} million cars ${d > 0 ? "to" : "off"} the road for a year`,
        basis: `The model's CO2 from burning fuel across the US economy. The car comparison divides the difference from EIA's forecast by ${EPA_T_PER_CAR} tons, what the EPA says a typical passenger car emits in a year ("Greenhouse Gas Emissions from a Typical Passenger Vehicle").` }));
    }
    $("stats").innerHTML = out.join("");
    // the model's own units, for experts
    $("expert-stats").innerHTML =
      stat("US energy CO2", "co2", at("co2"), "million t", eia("co2"), 0, true) +
      stat("Power price, all users", "price_electricity", at("price_electricity"), "¢/kWh", eia("price_electricity"), 1, true) +
      (has("price_el_home") ? stat("Power price, homes", "price_el_home", at("price_el_home"), "¢/kWh", eia("price_el_home"), 1, true) : "") +
      stat("Gas price, homes", "price_gas_home", at("price_gas_home"), "$/MMBtu", eia("price_gas_home"), 2, true) +
      stat("Electricity used", "elec_sales_twh", at("elec_sales_twh"), "TWh", eia("elec_sales_twh"), 0, true);
  }
  // Phones: one line that stays on screen while the levers move (CSS shows it under 860 px).
  function paintMini() {
    const co2 = at("co2"), dc = co2 - eia("co2");
    const pb = has("power_bill_month") ? at("power_bill_month") : null, dpb = pb === null ? 0 : pb - eia("power_bill_month");
    $("minibar").innerHTML = `<span>${S.year}</span>` +
      (pb === null ? "" : `<span>Power bill <b>$${fmt(pb)}</b>/mo ${Math.abs(dpb) < 0.5 ? "" : `(${dpb > 0 ? "+" : "-"}$${fmt(Math.abs(dpb))})`}</span>`) +
      `<span>CO2 <b>${fmt(co2 / 1000, 2)}</b> bn t ${Math.abs(dc) < 0.005 * eia("co2") ? "" : `(${dc > 0 ? "+" : "-"}${fmt(Math.abs(dc) / EPA_T_PER_CAR)}m cars)`}</span>` +
      `<a href="#map-card" id="mini-go">Map</a>`;
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
    const scale = Math.pow(Math.min(1, M.w / 900), 0.75) * 0.2;   // smaller dots on a phone-sized map
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
    $("map-note").innerHTML = `Each dot is a real power plant on EIA's list ${DATA_BADGE()}. Bigger dots are bigger plants; brighter dots run more ${badge(gradeOf("power_gas", S.src))}. ` +
      `Your levers change how much plants run, not which plants exist.` +
      `<details class="basis"><summary>More about the map</summary>${fmt(S.plants.drawn)} of ${fmt(S.plants.units_in_file)} units in EIA's plant file (${S.plants.not_drawn.no_coordinates} have no coordinates), appearing and retiring on EIA's schedule. ` +
      `Brightness is each plant's own capacity factor scaled so its fuel matches the model's national total; there is no plant-by-plant dispatch. The 25 grid regions' borders are approximate (nearest plant).` +
      (off.length ? ` Output from plants the model builds after EIA's list ends has no dot: ${off.join(", ")} of ${y} output.` : "") + `</details>`;
  }

  function legend() {
    $("legend").innerHTML = S.plants.groups.map((g) => `<span><i style="background:${GROUP_COLOR[g]}"></i>${GROUP_LABEL[g]}</span>`).join("") +
      "";
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
    $("river-grade").innerHTML = badge(w);
  }

  // ---- the bill -----------------------------------------------------------------------------------
  function paintBill() {
    // all home energy (power, gas, propane, heating oil) per month: the yearly bill over twelve
    const K = "bill", per = 1 / 12, v = at(K) * per, r = eia(K) * per, d = v - r;
    $("bill-now").textContent = `$${fmt(v)}`;
    $("bill-vs").textContent = Math.abs(d) < 0.5 ? `About the same as EIA's forecast ($${fmt(r)}).` :
      `$${fmt(Math.abs(d))} a month ${d > 0 ? "more" : "less"} than EIA's forecast ($${fmt(r)}).`;
    $("bill-grade").innerHTML = badge(gradeOf("bill", S.src));
    const svg = d3.select("#bill-chart"), W = $("bill-chart").clientWidth, H = $("bill-chart").clientHeight;
    svg.attr("viewBox", `0 0 ${W} ${H}`).selectAll("*").remove();
    const ys = S.emu.years.filter((y) => y >= 2025), a = ys.map((y) => at(K, y) * per), b = ys.map((y) => eia(K, y) * per);
    const lo = Math.min(...a, ...b), hi = Math.max(...a, ...b), pad = (hi - lo) * 0.15 + 2;
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
      m.className = "mode mode-real"; m.textContent = "Full model run";
      m.title = `The full model ran these settings, with EIA's own code for ${S.src.ported.join(", ")}. Took ${fmt(S.src.job.elapsed_s / 60, 1)} minutes.`;
    } else if (S.job) {
      m.className = "mode mode-busy"; m.textContent = "Instant numbers, full run going";
      m.title = "The numbers shown are instant ones until the full run finishes.";
    } else {
      m.className = "mode mode-emu"; m.textContent = "Instant numbers";
      m.title = `Instant numbers come from a quick fit to ${S.emu.runs} runs of a fast version of the model. Each dot's hover gives how close the fit is.`;
    }
    const btn = $("run"), note = $("run-note");
    if (!S.server) {
      btn.disabled = true;
      note.innerHTML = "The full model runs on your own computer (<code>python scripts/serve_2050.py</code>). This site shows instant numbers.";
    } else if (S.job) {
      btn.disabled = true; note.textContent = `Running the full model... ${fmt(S.job.elapsed || 0)} s. It works through every year to 2050.`;
    } else if (S.src.kind === "real") {
      btn.disabled = true; note.textContent = "Showing the full run for these settings. Move a lever to go back to instant numbers.";
    } else {
      btn.disabled = false; note.textContent = "Runs the full model, with EIA's own code for homes, businesses and vehicles, on this computer. Takes several minutes.";
    }
  }
  async function startRun() {
    const levers = Object.fromEntries(LEVERS.map((l) => [l.key, S.x[l.key]]));
    const res = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ levers }) });
    const body = await res.json();
    if (!res.ok) { $("run-note").textContent = body.error || "The server refused the run."; return; }
    S.job = { id: body.id, sig: sig(S.x), x: { ...S.x }, elapsed: 0 }; paintMode();
    const poll = async () => {
      const j = await (await fetch(`/api/run/${S.job.id}`)).json();
      S.job.elapsed = j.elapsed_s;
      if (j.status === "running") { paintMode(); setTimeout(poll, 3000); return; }
      const s = S.job.sig, ran = S.job.x; S.job = null;
      if (j.status === "done") { S.real[s] = j; UX2050.saveReal(ran, j); }
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
    paintLevers(); paintMode(); paintStats(); paintMini();
    for (const el of document.querySelectorAll(".yr")) el.textContent = S.year;
    $("map-year").textContent = S.year; $("year").value = S.year;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => { drawPlants(); if ($("more").open) { paintRiver(); paintBill(); } });   // the fold draws when opened
    writeHash();
    // "How did it get that?": the engine opens on this scenario (engine3d.js reads `yours`)
    const enc = UX2050.encode(S.emu, S.x);
    $("how").href = `engine3d.html#a=yours&y=${S.year}` + (enc ? `&yours=${encodeURIComponent(enc)}` : "&yours=");
  }

  async function main() {
    const [emu, plants, fid] = await Promise.all(["data/ux2050/emulator.json?v=2", "data/ux2050/plants.json", "data/fidelity.json"]
      .map((u) => fetch(u).then((r) => r.json())));
    Object.assign(S, { emu, plants, fid });
    await loadGeo();
    buildLevers(); legend(); readHash();
    layoutMap(); update();
    $("year").addEventListener("input", (e) => { S.year = +e.target.value; update(); });
    $("more").addEventListener("toggle", () => { if ($("more").open) { paintRiver(); paintBill(); } });
    $("map").addEventListener("mousemove", hover);
    $("map").addEventListener("click", hover);   // touch screens have no hover: a tap shows the same card
    if (innerWidth < 860) $("lever-box").open = false;   // phones: stories first, the ten sliders one tap away
    $("minibar").addEventListener("click", (e) => { if (e.target.id === "mini-go") { e.preventDefault(); document.querySelector(".map-card").scrollIntoView({ behavior: "smooth" }); } });
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
  const GUIDE = [
    { el: () => document.querySelector(".stats"), t: "This is EIA's forecast for 2050",
      b: "These start as the U.S. Energy Information Administration's own projections: a typical home's bills, gas at the pump, and America's CO2. The map shows every power plant." },
    { el: () => document.querySelector(".levers"), t: "Pull a lever or pick a story",
      b: "Try a carbon price, more electric cars, or a data-center boom. Every number updates at once." },
    { el: () => document.querySelector(".stats"), t: "See what changed and how sure we are",
      b: "Each number says how it compares with EIA's forecast. The dot says how sure: green is EIA's own code, amber is our estimate, grey is EIA's published number." },
  ];
  function guide(force) {
    let seen = false;
    try { seen = localStorage.getItem("nems.guide.2050") === "done"; } catch (e) { /* storage blocked: show it */ }
    if (seen && !force) return;
    const box = $("guide"); let i = 0, lit = null;
    const done = () => { box.hidden = true; if (lit) lit.classList.remove("guide-on"); try { localStorage.setItem("nems.guide.2050", "done"); } catch (e) { /* not kept */ } };
    const show = () => {
      if (lit) lit.classList.remove("guide-on");
      const g = GUIDE[i]; lit = g.el(); if (lit) { lit.classList.add("guide-on"); const top = lit.getBoundingClientRect().top + scrollY - 56; scrollTo({ top: Math.max(0, top), behavior: "smooth" }); }
      box.innerHTML = `<div class="gs">Step ${i + 1} of ${GUIDE.length}</div><h3>${g.t}</h3><p>${g.b}</p>` +
        `<div class="gb"><button type="button" class="btn ghost" data-a="skip">Skip</button>${i ? '<button type="button" class="btn ghost" data-a="back">Back</button>' : ""}` +
        `<button type="button" class="btn primary" data-a="next">${i === GUIDE.length - 1 ? "Got it" : "Next"}</button></div>`;
      box.hidden = false; box.querySelector('[data-a="next"]').focus({ preventScroll: true });
    };
    box.onclick = (e) => {
      const a = e.target.dataset.a; if (!a) return;
      if (a === "skip" || (a === "next" && i === GUIDE.length - 1)) done();
      else { i += a === "next" ? 1 : -1; show(); }
    };
    box.onkeydown = (e) => { if (e.key === "Escape") done(); };
    show();
  }

  async function checkServer() {
    try {
      const h = await Promise.race([fetch("/api/health", { cache: "no-store" }), new Promise((_, no) => setTimeout(() => no(new Error("timeout")), 2500))]);
      const hj = await h.json();
      S.server = h.ok && hj.ok === true; S.key = S.server && hj.ask === true;
    } catch (e) { S.server = false; S.key = false; }
    S.checked = true;
    if (S.out) paintMode();
  }
  addEventListener("DOMContentLoaded", () => main().then(() => { $("dots").innerHTML = NEMSDot.legend(); $("guide-again").onclick = () => guide(true); guide(false); }).then(checkServer).catch((e) => {
    document.querySelector(".center").insertAdjacentHTML("afterbegin", `<p class="notice">The page could not load its data: ${esc(e.message)}. It needs a web server (python scripts/serve_2050.py).</p>`);
    console.error(e);
  }));
})();
