(function () {
  "use strict";
  const DATA = window.NEMS_DATA;
  const meta = DATA.meta;
  const ref = meta.reference;
  const years = meta.years;
  const yi = (y) => years.indexOf(y);

  // ---- scenario sets -------------------------------------------------------------
  // fast: every sector on the stub, supply on fitted curves (144 runs).
  // real: ported residential and commercial plus the dispatch LP (16 runs, scripts/precompute_real.py).
  const REAL = window.NEMS_REAL;
  const SETS = { fast: { carbon: meta.carbon, ev2035: meta.ev2035, buildings2050: meta.buildings2050, scenarios: DATA.scenarios } };
  if (REAL && REAL.meta.complete) SETS.real = { ...REAL.meta, scenarios: REAL.scenarios };
  let set = "fast";
  const grid = () => SETS[set];
  const LIVE = { residential: "Ported module ran in this run", commercial: "Ported module ran in this run",
                 electricity: "Dispatch LP ran in this run" };

  // ---- levers --------------------------------------------------------------
  const el = (id) => document.getElementById(id);
  const levers = { carbon: el("carbon"), ev: el("ev"), bld: el("bld") };
  const evLabel = (v) => (v === null ? Math.round(ref.ev_share[yi(2035)] * 100) + "% (EIA)" : Math.round(v * 100) + "%");
  const bldLabel = (v) => (v === 1 ? "Same as EIA" : Math.round((1 - v) * 100) + "% less than EIA");

  function current() {
    const g = grid();
    const carbon = g.carbon[+levers.carbon.value];
    const ev = g.ev2035[+levers.ev.value];
    const bld = g.buildings2050[+levers.bld.value];
    const id = `c${carbon}_ev${ev === null ? "ref" : Math.round(ev * 100)}_b${Math.round(bld * 100)}`;
    return { carbon, ev, bld, s: g.scenarios[id] };
  }
  const ticks = (id, labels) => (el(id).innerHTML = labels.map((t) => `<span>${t}</span>`).join(""));
  function setupLevers() {
    const g = grid();
    levers.carbon.max = g.carbon.length - 1;
    levers.ev.max = g.ev2035.length - 1;
    levers.bld.max = g.buildings2050.length - 1;
    ticks("carbon-ticks", set === "fast" ? ["$0", "$100", "$200"] : g.carbon.map((c) => "$" + c));
    ticks("ev-ticks", g.ev2035.map((v) => (v === null ? "EIA" : Math.round(v * 100) + "%")));
    ticks("bld-ticks", g.buildings2050.map((v) => (v === 1 ? "EIA" : "-" + Math.round((1 - v) * 100) + "%")));
  }
  function switchSet(to) {
    if (!SETS[to]) return;
    const c = current();
    set = to;
    const g = grid();
    setupLevers();
    const near = (list, v) => list.reduce((best, x, i) => (Math.abs(x - v) < Math.abs(list[best] - v) ? i : best), 0);
    levers.carbon.value = near(g.carbon, c.carbon);
    levers.ev.value = Math.max(0, g.ev2035.indexOf(c.ev));
    levers.bld.value = g.buildings2050.indexOf(c.bld) >= 0 ? g.buildings2050.indexOf(c.bld) : near(g.buildings2050, c.bld);
    document.querySelectorAll(".setswitch button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.set === set));
    el("set-note").textContent = set === "fast"
      ? "Every demand sector on a fitted stub, supply on curves fitted to EIA's runs. Seconds a run, so the full grid is here."
      : "Residential and commercial run EIA's ported code, electricity runs the dispatch LP. Industrial, transportation, gas, oil, coal and retail power prices stay fitted. The LP dispatches EIA's reference plant fleet and builds nothing, so a carbon price cuts power CO2 less here than in the fast set. Ten to 45 minutes a run, so a smaller grid.";
    el("grid-note").textContent = set === "fast"
      ? "Every combination was run ahead of time (144 runs), so the sliders snap to the grid. Prices are 2024 dollars."
      : "Every combination was run ahead of time (16 runs), so the sliders snap to the grid. Prices are 2024 dollars.";
    [...tabs.children].forEach((b, i) => (b.hidden = !!MEASURES[i].realOnly && set !== "real"));
    if (measure.realOnly && set !== "real") selectMeasure(MEASURES[0]);
  }

  // ---- formatting ------------------------------------------------------------
  const fmt = (x, d = 0) => x.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  function delta(now, base, lowerIsGood, unit, d) {
    const diff = now - base;
    const pct = base ? (100 * diff) / base : 0;
    if (Math.abs(pct) < 0.05) return "Same as EIA";
    const cls = (diff < 0) === lowerIsGood ? "good" : "bad";
    const sign = diff > 0 ? "+" : "-";
    return `<span class="${cls}">${sign}${fmt(Math.abs(pct), 1)}%</span> vs EIA ${fmt(base, d)}${unit}`;
  }

  function kpis(s) {
    const j = yi(2050);
    el("k-co2").textContent = fmt(s.co2[j]) + " Mt";
    el("k-co2-d").innerHTML = delta(s.co2[j], ref.co2[j], true, " Mt", 0);
    el("k-pel").textContent = fmt(s.prices.electricity[j], 1) + " ¢/kWh";
    el("k-pel-d").innerHTML = delta(s.prices.electricity[j], ref.prices.electricity[j], true, "¢", 1);
    el("k-gas").textContent = fmt(s.gasoline_bgal[j], 1) + " bn gal";
    el("k-gas-d").innerHTML = delta(s.gasoline_bgal[j], ref.gasoline_bgal[j], true, " bn gal", 1);
    let avoided = 0, total = 0;
    for (let y = meta.start_year; y <= 2050; y++) {
      avoided += ref.co2[yi(y)] - s.co2[yi(y)];
      total += ref.co2[yi(y)];
    }
    el("k-cum").textContent = fmt(avoided / 1000, 1) + " Gt";
    el("k-cum-d").textContent = Math.abs(avoided) < 1 ? "Same as EIA" : fmt((100 * avoided) / total, 1) + "% of EIA's 2027-2050 total";
  }

  // ---- chart -----------------------------------------------------------------
  const MEASURES = [
    { key: "co2", label: "CO2", unit: "million metric tons CO2", get: (d) => d.co2 },
    { key: "pel", label: "Power price", unit: "cents per kWh, 2024 $", get: (d) => d.prices.electricity },
    { key: "mg", label: "Gasoline price", unit: "$ per gallon, 2024 $", get: (d) => d.prices.gasoline },
    { key: "ng", label: "Home gas price", unit: "$ per MMBtu, 2024 $", get: (d) => d.prices.gas_home },
    { key: "gal", label: "Gasoline use", unit: "billion gallons", get: (d) => d.gasoline_bgal },
    { key: "use", label: "Energy use", unit: "quadrillion Btu, delivered to all sectors",
      get: (d) => years.map((_, i) => Object.values(d.energy).reduce((a, s) => a + s[i], 0)) },
    { key: "whl", label: "Wholesale power", unit: "$ per MWh, 2024 $, load-weighted marginal cost from the dispatch LP",
      get: (d) => d.wholesale || years.map(() => null), realOnly: true },
  ];
  let measure = MEASURES[0];
  const tabs = el("tabs");
  MEASURES.forEach((m) => {
    const b = document.createElement("button");
    b.type = "button";
    b.role = "tab";
    b.textContent = m.label;
    b.setAttribute("aria-selected", m === measure);
    b.addEventListener("click", () => { selectMeasure(m); render(); });
    tabs.appendChild(b);
  });
  function selectMeasure(m) {
    measure = m;
    [...tabs.children].forEach((c, i) => c.setAttribute("aria-selected", MEASURES[i] === m));
  }

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  let chart = null;
  function drawChart(s) {
    const accent = css("--accent"), refc = css("--ref"), line = css("--line"), muted = css("--muted");
    const scen = measure.get(s), base = measure.realOnly ? years.map(() => null) : measure.get(ref);
    document.querySelector(".ref-key").hidden = !!measure.realOnly;
    const cfg = {
      type: "line",
      data: {
        labels: years,
        datasets: [
          { label: "This run", data: scen, borderColor: accent, backgroundColor: accent, borderWidth: 2.5, pointRadius: 0, tension: 0.2 },
          { label: "EIA reference", data: base, borderColor: refc, backgroundColor: refc, borderWidth: 2, borderDash: [6, 5], pointRadius: 0, tension: 0.2 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: { duration: 250 },
        interaction: { mode: "index", intersect: false },
        onClick: (e, items, c) => {
          const pts = c.getElementsAtEventForMode(e, "index", { intersect: false }, false);
          if (pts.length) { traceYear = years[pts[0].index]; trace(s); writeHash(); }
        },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt(c.parsed.y, measure.key === "co2" ? 0 : 2)}` } },
          title: { display: true, text: measure.unit, align: "start", color: muted, font: { size: 12, weight: "normal" } },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: muted, maxTicksLimit: 7 }, border: { color: line } },
          y: { grid: { color: line }, ticks: { color: muted }, border: { display: false } },
        },
      },
    };
    if (chart) chart.destroy();
    chart = new Chart(el("chart"), cfg);
  }

  // ---- trace this number -------------------------------------------------------
  let traceYear = 2050;
  const MODULE_FOR = { co2: "emissions", pel: "electricity", mg: "oil", ng: "natural_gas", gal: "transportation", use: null, whl: "electricity" };
  const VARIABLE = {
    co2: "Sum of five sectors: fuel use x EIA's carbon factor (EMEBLK), scaled to EIA's sector carbon (EMISSION/em*c)",
    pel: "MPBLK/pelas, average delivered electricity price",
    mg: "MPBLK/pmgtr, gasoline delivered to transportation",
    ng: "MPBLK/pngrs, natural gas delivered to homes",
    gal: "QBLK/qmgtr, motor gasoline used in transportation",
    use: "QBLK/qtsrs + qtscm + qtsin + qtstr, delivered energy by sector",
    whl: "Dispatch LP: load-weighted marginal cost over 25 EMM regions. In 2025-2030 a few short hours set $1,000/MWh in some regions; read it as a signal, not a price",
  };
  const GEN = { coal: "Coal", coal_ccs: "Coal with CCS", gas_cc: "Gas combined cycle", gas_ccs: "Gas with CCS", gas_ct: "Gas turbine",
                steam: "Oil and gas steam", nuclear: "Nuclear", hydro: "Hydro", wind: "Wind", solar: "Solar", battery: "Battery", other: "Other" };
  const SECTOR = { rs: "Homes", cm: "Businesses", in: "Industry", tr: "Transportation", el: "Power plants" };
  function rowsFor(key, s, j) {
    const t = s.trace, r = ref.trace;
    const row = (label, a, b, d, unit) => ({ label, a, b, d, unit });
    switch (key) {
      case "co2": return [
        ...Object.keys(SECTOR).map((k) => row(`${SECTOR[k]} CO2`, t.co2_sector[k][j], r.co2_sector[k][j], 0, " Mt")),
        row("Gas burned in power plants", t.power_burn.gas[j], r.power_burn.gas[j], 2, " quads"),
        row("Coal burned in power plants", t.power_burn.coal[j], r.power_burn.coal[j], 2, " quads")];
      case "pel": return [
        row("Electricity sold", t.totals.elec[j], r.totals.elec[j], 2, " quads"),
        row("Gas price to power plants, before carbon", t.gas_to_power[j], r.gas_to_power[j], 2, " $/MMBtu"),
        row("Carbon cost in the price", t.adders.electricity[j], 0, 2, "¢/kWh")];
      case "mg": return [
        row("Gasoline used, all sectors", t.totals.gasoline[j], r.totals.gasoline[j], 2, " quads"),
        row("Carbon cost in the price", t.adders.gasoline[j], 0, 2, " $/gal")];
      case "ng": return [
        row("Natural gas used, all sectors", t.totals.gas[j], r.totals.gas[j], 2, " quads"),
        row("Gas burned in power plants", t.power_burn.gas[j], r.power_burn.gas[j], 2, " quads"),
        row("Carbon cost in the price", t.adders.gas_home[j], 0, 2, " $/MMBtu")];
      case "gal": return [
        row("Gasoline price", s.prices.gasoline[j], ref.prices.gasoline[j], 2, " $/gal"),
        row("Cut by the EV lever", t.ev_cut_bgal[j], 0, 1, " bn gal")];
      case "use": return Object.keys(s.energy).map((k) => row(k[0].toUpperCase() + k.slice(1), s.energy[k][j], ref.energy[k][j], 2, " quads"));
      case "whl": return Object.entries(s.generation_twh || {}).filter(([, v]) => v[j] > 0.05)
        .sort((x, y) => y[1][j] - x[1][j]).map(([g, v]) => row(`${GEN[g] || g} generation`, v[j], null, 0, " TWh"));
    }
    return [];
  }
  function story(key, s, j) {
    const t = s.trace, a = measure.get(s)[j], b = measure.get(ref)[j];
    if (key === "pel" || key === "mg" || key === "ng") {
      if (Math.abs(a - b) < 1e-3) return "Same as EIA: nothing upstream moved.";
      const adder = t.adders[{ pel: "electricity", mg: "gasoline", ng: "gas_home" }[key]][j];
      const rest = a - b - adder;
      return `Carbon cost adds ${fmt(adder, 2)}. The other ${rest >= 0 ? "+" : "-"}${fmt(Math.abs(rest), 2)} is the fitted price curve answering the change in demand${key === "pel" ? " and in the gas price to power plants" : ""}.`;
    }
    if (key === "gal") {
      if (Math.abs(a - b) < 0.05) return "Same as EIA: nothing upstream moved.";
      const cut = t.ev_cut_bgal[j], rest = a - b + cut;
      return `The EV lever removes ${fmt(cut, 1)} bn gal. The price response ${rest >= 0 ? "adds" : "removes"} ${fmt(Math.abs(rest), 1)} bn gal (fitted stub elasticity).`;
    }
    if (key === "whl") return "No EIA line: EIA's run reports its own price model's output, not this LP's marginal cost.";
    if (key === "co2") {
      if (Math.abs(a - b) < 1) return "Same as EIA: nothing upstream moved.";
      const d = Object.keys(SECTOR).map((k) => [k, t.co2_sector[k][j] - ref.trace.co2_sector[k][j]]).sort((x, y) => x[1] - y[1]);
      return `Biggest change: ${SECTOR[d[0][0]].toLowerCase()}, ${fmt(d[0][1], 0)} Mt.`;
    }
    return "";
  }
  function trace(s) {
    const j = yi(traceYear);
    const key = measure.key;
    const a = measure.get(s)[j], b = measure.realOnly ? null : measure.get(ref)[j];
    const d = key === "co2" || key === "whl" ? 0 : 2;
    const mod = MODULE_FOR[key];
    const name = (k) => `${ENGINE.modules[k].name} (${set === "real" && LIVE[k] ? (k === "electricity" ? "dispatch LP" : "port, ran")
      : ({ stand: "stand-in", partial: "stub", real: "port" })[ENGINE.modules[k].kind]})`;
    const rows = rowsFor(key, s, j).map((r) => {
      if (r.b === null) return `<tr><td>${r.label}</td><td>${r.a === null ? "n/a" : fmt(r.a, r.d) + r.unit}</td><td>n/a</td><td></td></tr>`;
      const diff = r.a - r.b, same = Math.abs(diff) < 0.5 * 10 ** -r.d;
      return `<tr><td>${r.label}</td><td>${fmt(r.a, r.d)}${r.unit}</td><td>${fmt(r.b, r.d)}${r.unit}</td><td class="${same ? "" : diff < 0 ? "down" : "up"}">${same ? "same" : (diff > 0 ? "+" : "-") + fmt(Math.abs(diff), r.d)}</td></tr>`;
    }).join("");
    el("trace-body").innerHTML = `
      <div class="trace-head"><div><div class="kpi-label">${measure.label}, ${traceYear}</div>
        <div class="kpi-value">${a === null ? "n/a" : fmt(a, d)}</div><div class="kpi-delta">${b === null ? "No EIA reference" : "EIA " + fmt(b, d)}</div></div>
        <div class="made-by"><div class="kpi-label">Produced by</div>
        <div class="made-btns">${(mod ? [mod] : ["residential", "commercial", "industrial", "transportation"]).map((k) => `<button type="button" class="ghost" data-mod="${k}">${name(k)}</button>`).join("")}</div>
        <div class="fine"><code>${VARIABLE[key]}</code></div></div></div>
      <table class="rt trace-t"><thead><tr><th>What fed it</th><th>This run</th><th>EIA</th><th>Change</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="story">${story(key, s, j)}</p>`;
    el("trace-body").querySelectorAll("[data-mod]").forEach((b) => b.addEventListener("click", () => openModule(b.dataset.mod)));
  }

  // ---- engine view -------------------------------------------------------------
  const ENGINE = window.NEMS_ENGINE;
  const TAGS = { real: "Ported, matches EIA. Stub in this run", partial: "Being ported. Stub", stand: "Stand-in" };
  const modBox = el("modules");
  const modEls = { d: [], s: [] };
  let lastSide = null;
  Object.entries(ENGINE.modules).forEach(([key, m]) => {
    const side = m.side === "demand" ? "d" : "s";
    if (side !== lastSide) {
      const g = document.createElement("div");
      g.className = "mod-group";
      g.textContent = side === "d" ? "Demand" : "Supply";
      modBox.appendChild(g);
      lastSide = side;
    }
    const b = document.createElement("button");
    b.type = "button";
    b.className = "mod " + m.kind;
    b.dataset.key = key;
    b.setAttribute("aria-label", `${m.name}: open details`);
    b.innerHTML = `<div class="name">${m.name}</div><div class="tag"></div>`;
    b.addEventListener("click", () => openModule(key));
    modEls[side].push(b);
    modBox.appendChild(b);
  });

  function tagModules() {
    modBox.querySelectorAll("button.mod").forEach((b) => {
      const key = b.dataset.key, m = ENGINE.modules[key], live = set === "real" && LIVE[key];
      b.classList.toggle("live", !!live);
      b.querySelector(".tag").textContent = live ? LIVE[key]
        : key === "emissions" ? "EIA carbon factors"
        : m.kind === "real" ? (set === "real" ? "Ported, matches EIA" : TAGS.real) : TAGS[m.kind];
    });
  }

  // ---- module details ------------------------------------------------------------
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const STATUS = {
    real: "Ported from EIA's code and matching EIA",
    partial: "Being ported. This demo runs a fitted stub in its place",
    stand: "Stand-in: curves fitted to EIA's AEO2026 runs, to be replaced by a port",
  };
  const coefName = (k) => ({ q: "own use", pngel: "gas price" })[k] || k;
  function openModule(key) {
    const m = ENGINE.modules[key];
    const dlg = el("module-dialog");
    const real = m.kind === "real";
    const hasMatch = m.routines.some((r) => r.match);
    const third = real ? (hasMatch ? "<th>Match vs EIA</th>" : "") : "<th>File</th>";
    const routines = m.routines.length
      ? `<table class="rt"><thead><tr><th>Routine</th><th>${real ? "State" : "Lines"}</th>${third}</tr></thead><tbody>` +
        m.routines.map((r) => real
          ? `<tr class="${r.done ? "done" : "todo"}"><td><code>${esc(r.name)}</code></td><td>${esc(r.state)}</td>${hasMatch ? `<td>${esc(r.match)}</td>` : ""}</tr>`
          : `<tr><td><code>${esc(r.name)}</code></td><td>${esc(r.lines)}</td><td>${esc(r.file || "")}</td></tr>`).join("") +
        `</tbody></table><p class="fine">From ${esc(m.routines_source)}${real ? "" : ", longest first"}.</p>`
      : "";
    const fits = (m.fits || []).length
      ? `<h3>What the stand-in does instead</h3><table class="rt"><thead><tr><th>Price</th><th>Fitted response</th><th>R2</th><th>Error</th></tr></thead><tbody>` +
        m.fits.map((f) => `<tr><td><code>${esc(f.price)}</code></td><td>${Object.entries(f.coef).map(([k, v]) => `${coefName(k)} ${v}`).join(", ")}</td><td>${f.r2}</td><td>${f.rmse_pct}%</td></tr>`).join("") +
        `</tbody></table>` +
        (m.switching ? `<p class="fine">Power-plant fuel switching: gas burn ${m.switching.gas_own} per 1% of gas cost; coal ${m.switching.coal_own} per 1% of its own cost (assumed), ${m.switching.coal_from_gas_cost} per 1% of gas cost.</p>` : "")
      : "";
    const files = m.eia_files.map((f) => `<li><code>${esc(f.path)}</code> ${fmt(f.lines)} lines</li>`).join("");
    const tests = Object.entries(m.test_files).map(([f, n]) => `<li><code>${esc(f)}</code> ${n}</li>`).join("");
    el("module-body").innerHTML = `
      <h2>${esc(m.name)}</h2>
      <p class="status ${m.kind}">${STATUS[m.kind]}</p>
      <div class="facts">
        <div><span class="n">${fmt(m.eia_lines)}</span><span>lines of EIA source in ${m.eia_file_count} file${m.eia_file_count === 1 ? "" : "s"}</span></div>
        <div><span class="n">${fmt(m.ours_lines)}</span><span>lines of our Python</span></div>
        <div><span class="n">${fmt(m.tests)}</span><span>tests</span></div>
      </div>
      ${m.eia_state ? `<p class="fine">EIA module map: ${esc(m.eia_state)}${m.blocker && m.blocker !== "None" ? `. Blocker: ${esc(m.blocker)}` : ""}</p>` : ""}
      ${routines ? `<h3>${real ? "Routines" : "EIA's largest routines"}</h3>${routines}` : ""}
      ${fits}
      <h3>EIA source it replaces</h3><ul class="files">${files}</ul>
      ${tests ? `<h3>Tests</h3><ul class="files">${tests}</ul>` : ""}
      <p class="fine">Generated from the repo on ${ENGINE.totals.generated} by scripts/build_engine_catalog.py (${fmt(ENGINE.totals.tests)} tests in the repo).</p>`;
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
  }
  el("module-close").addEventListener("click", () => el("module-dialog").close());
  el("module-dialog").addEventListener("click", (e) => { if (e.target.id === "module-dialog") e.target.close(); });

  const nDemand = modEls.d.length, nSupply = modEls.s.length;
  const callsFor = (passes) => passes * nDemand + (passes + 1) * nSupply;

  let timers = [];
  const stop = () => { timers.forEach(clearTimeout); timers = []; };
  const light = (side) => {
    modEls.d.forEach((m) => m.classList.toggle("on", side === "d"));
    modEls.s.forEach((m) => m.classList.toggle("on", side === "s"));
  };
  const pctText = (x) => (x >= 0.01 ? fmt(100 * x, 1) : x >= 1e-4 ? fmt(100 * x, 3) : (100 * x).toExponential(1)) + "%";

  function engine(s, animate) {
    stop();
    const year = +el("year").value;
    el("year-out").textContent = year;
    const rep = s.convergence[String(year)];
    const dp = rep.dp;
    let total = 0;
    Object.values(s.convergence).forEach((r) => (total += callsFor(r.passes)));
    el("c-passes").textContent = rep.passes;
    el("c-calls").textContent = callsFor(rep.passes);
    el("c-total").textContent = fmt(total);

    const bars = el("gap-bars");
    bars.innerHTML = "";
    const lo = Math.log10(1e-5), hi = Math.log10(Math.max(...dp, 1e-3) * 1.2);
    const barEls = dp.map((v, i) => {
      const b = document.createElement("div");
      b.className = "b";
      const h = Math.max(0.03, (Math.log10(Math.max(v, 1e-6)) - lo) / (hi - lo));
      b.style.height = (100 * h).toFixed(1) + "%";
      b.title = `Pass ${i + 1}: largest price change ${pctText(v)}`;
      bars.appendChild(b);
      return b;
    });
    const finish = () => {
      light(null);
      barEls.forEach((b) => b.classList.add("shown"));
      el("pass-label").textContent = `Converged after ${rep.passes} pass${rep.passes > 1 ? "es" : ""}`;
      el("gap-label").textContent = `last change ${pctText(dp[dp.length - 1])}`;
    };
    if (!animate || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return finish();

    el("pass-label").textContent = "Starting " + year;
    el("gap-label").textContent = "";
    light(null);
    const step = 420;
    let t = 0;
    const at = (fn) => timers.push(setTimeout(fn, (t += step)));
    at(() => { light("s"); el("pass-label").textContent = "Pass 0: levers applied"; el("gap-label").textContent = "supply reprices"; });
    dp.forEach((v, i) => {
      at(() => { light("d"); el("pass-label").textContent = `Pass ${i + 1}: demand responds`; });
      at(() => {
        light("s");
        barEls[i].classList.add("shown");
        el("pass-label").textContent = `Pass ${i + 1}: supply reprices`;
        el("gap-label").textContent = `largest price change ${pctText(v)}`;
      });
    });
    at(finish);
  }

  // ---- share link (URL hash) ----------------------------------------------------
  // #c=100&ev=80&b=90&m=pel&y=2035: levers, chart measure, traced year.
  const evCode = (v) => (v === null ? "ref" : String(Math.round(v * 100)));
  function writeHash() {
    const c = current();
    const h = `${set === "real" ? "set=real&" : ""}c=${c.carbon}&ev=${evCode(c.ev)}&b=${Math.round(c.bld * 100)}&m=${measure.key}&y=${traceYear}`;
    if (location.hash.slice(1) !== h) history.replaceState(null, "", "#" + h);
  }
  function readHash() {
    const q = new URLSearchParams(location.hash.slice(1));
    const pick = (list, val, code) => { const i = list.findIndex((v) => code(v) === val); return i >= 0 ? i : null; };
    const want = q.get("set") === "real" && SETS.real ? "real" : "fast";
    if (want !== set) switchSet(want);
    const g = grid();
    const ci = pick(g.carbon, q.get("c"), String);
    const ei = pick(g.ev2035, q.get("ev"), evCode);
    const bi = pick(g.buildings2050, q.get("b"), (v) => String(Math.round(v * 100)));
    if (ci !== null) levers.carbon.value = ci;
    if (ei !== null) levers.ev.value = ei;
    if (bi !== null) levers.bld.value = bi;
    const m = MEASURES.find((x) => x.key === q.get("m") && (!x.realOnly || set === "real"));
    if (m) selectMeasure(m);
    const y = +q.get("y");
    if (years.includes(y)) traceYear = y;
  }
  const say = (msg) => { el("share-msg").textContent = msg; setTimeout(() => (el("share-msg").textContent = ""), 4000); };
  el("copy-link").addEventListener("click", async () => {
    writeHash();
    try {
      await navigator.clipboard.writeText(location.href);
      say("Link copied.");
    } catch (e) {
      const t = document.createElement("textarea");
      t.value = location.href;
      document.body.appendChild(t);
      t.select();
      const ok = document.execCommand && document.execCommand("copy");
      t.remove();
      say(ok ? "Link copied." : "Copy the address bar: it now holds this scenario.");
    }
  });

  // ---- CSV download ------------------------------------------------------------
  function csv() {
    const c = current(), s = c.s;
    const cols = [
      ["US energy CO2 (million metric tons)", (d) => d.co2],
      ["Electricity price, all sectors (2024 cents/kWh)", (d) => d.prices.electricity],
      ["Natural gas price, homes (2024 $/MMBtu)", (d) => d.prices.gas_home],
      ["Gasoline price, transport (2024 $/gal)", (d) => d.prices.gasoline],
      ["Diesel price, transport (2024 $/gal)", (d) => d.prices.diesel],
      ["Gasoline use (billion gallons)", (d) => d.gasoline_bgal],
      ["Electricity sold (quads)", (d) => d.power_sales],
      ...Object.keys(s.energy).map((k) => [`Delivered energy, ${k} (quads)`, (d) => d.energy[k]]),
      ...Object.keys(s.trace.co2_sector).map((k) => [`CO2, ${({ rs: "residential", cm: "commercial", in: "industrial", tr: "transportation", el: "electric power" })[k]} (million metric tons)`, (d) => d.trace.co2_sector[k]]),
      ...(s.wholesale ? [["Wholesale power, dispatch LP marginal cost (2024 $/MWh)", (d) => d.wholesale]] : []),
      ...Object.keys(s.generation_twh || {}).map((g) => [`Generation, ${GEN[g] || g} (TWh)`, (d) => d.generation_twh && d.generation_twh[g]]),
    ];
    const head = ["year", ...cols.flatMap(([n]) => [`${n}, this run`, `${n}, EIA reference`])];
    const q = (v) => (/[",]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
    const lines = [head.map(q).join(",")];
    const at = (a, i) => (a && a[i] !== null && a[i] !== undefined ? a[i] : "");
    years.forEach((y, i) => lines.push([y, ...cols.flatMap(([, g]) => [at(g(s), i), at(g(ref), i)])].join(",")));
    const about = [
      `# NEMS Open policy sandbox, scenario ${s.id}: carbon price $${c.carbon}/t CO2 (2024 $) from 2027; plug-in share of new light-duty sales in 2035 ${c.ev === null ? "EIA reference" : Math.round(c.ev * 100) + "%"}; building energy use ${c.bld === 1 ? "as EIA" : Math.round((1 - c.bld) * 100) + "% below EIA"} by 2050.`,
      set === "real"
        ? "# Real ported modules: residential and commercial from EIA's ported code, electricity from the dispatch LP; industrial, transportation, gas, oil, coal and retail power prices fitted. Reference: EIA AEO2026 Counterfactual Baseline. Not affiliated with or endorsed by EIA."
        : "# Fast stand-ins: demand from a fitted stub, supply from a fitted stand-in. Reference: EIA AEO2026 Counterfactual Baseline. Not affiliated with or endorsed by EIA.",
    ];
    return about.join("\n") + "\n" + lines.join("\n") + "\n";
  }
  el("download-csv").addEventListener("click", () => {
    const blob = new Blob([csv()], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `nems-open_${set === "real" ? "real_" : ""}${current().s.id}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    say("CSV downloaded.");
  });

  // ---- how this works --------------------------------------------------------------
  (function statusTable() {
    const label = { real: "Ported, matches EIA", partial: "Being ported (stub)", stand: "Stand-in" };
    el("status-table").querySelector("tbody").innerHTML = Object.entries(ENGINE.modules).map(([key, m]) =>
      `<tr><td><button type="button" class="link" data-mod="${key}">${m.name}</button></td><td><i class="dot ${m.kind}"></i>${label[m.kind]}</td><td>${fmt(m.eia_lines)}</td><td>${fmt(m.tests)}</td></tr>`).join("");
    el("status-table").querySelectorAll("[data-mod]").forEach((b) => b.addEventListener("click", () => openModule(b.dataset.mod)));
    el("status-note").textContent = `From the repo on ${ENGINE.totals.generated}: ${fmt(ENGINE.totals.tests)} tests in all. EIA lines count every source file the module replaces, AIMMS models included.`;
  })();
  el("go-how").addEventListener("click", () => el("how").scrollIntoView({ behavior: "smooth", block: "start" }));

  // ---- wiring ------------------------------------------------------------------
  // ---- what changed ---------------------------------------------------------------
  // The CO2 change against the same models with no policy (for the fast set that is EIA's
  // reference itself), split by sector over 2027-2050, top three with what moved them.
  const SECTOR_NAME = { rs: "Homes", cm: "Businesses", in: "Industry", tr: "Transportation", el: "Power plants" };
  function explain(c) {
    const s = c.s, b = grid().scenarios["c0_evref_b100"] || ref;
    const j = yi(2050), from = yi(meta.start_year);
    const cum = (k) => { let t = 0; for (let i = from; i <= j; i++) t += b.trace.co2_sector[k][i] - s.trace.co2_sector[k][i]; return t; };
    const cuts = Object.keys(SECTOR_NAME).map((k) => [k, cum(k)]);
    const total = cuts.reduce((a, [, v]) => a + v, 0);
    const box = el("explain-body");
    el("explain-base").textContent = set === "real" ? "Against the same real modules run with no policy." : "Against EIA's reference.";
    if (Math.abs(total) < 1 && cuts.every(([, v]) => Math.abs(v) < 1)) {
      box.innerHTML = `<p class="story">No policy: this run is the baseline, so nothing changed.</p>`;
      return;
    }
    const t = s.trace, r = b.trace;
    const more = (x, unit, d = 1) => `${fmt(Math.abs(x), d)}${unit} ${x < 0 ? "less" : "more"}`;
    const pct = (a, z) => (z ? (100 * (a - z)) / z : 0);
    const why = {
      el: () => {
        const sales = pct(t.totals.elec[j], r.totals.elec[j]);
        const fuel = [["gas", t.power_burn.gas[j] - r.power_burn.gas[j]], ["coal", t.power_burn.coal[j] - r.power_burn.coal[j]]]
          .filter(([, d]) => Math.abs(d) >= 0.01).map(([f, d]) => `${more(d, " quads", Math.abs(d) < 0.1 ? 2 : 1)} ${f}`);
        return (fuel.length ? `In 2050 they burn ${fuel.join(" and ")}. ` : "")
          + `Electricity sold is ${fmt(Math.abs(sales), 1)}% ${sales < 0 ? "lower" : "higher"}${set === "real" ? " (dispatch LP, existing fleet only)" : " (fitted fuel switching)"}.`;
      },
      tr: () => {
        const cut = t.ev_cut_bgal[j] - (r.ev_cut_bgal ? r.ev_cut_bgal[j] : 0);
        const all = b.gasoline_bgal[j] - s.gasoline_bgal[j];
        const parts = [];
        if (Math.abs(cut) >= 0.05) parts.push(`the EV lever takes ${fmt(cut, 1)} bn gal of gasoline out of 2050`);
        if (Math.abs(all - cut) >= 0.05) parts.push(`higher prices ${all - cut > 0 ? "cut" : "add"}${parts.length ? " another" : ""} ${fmt(Math.abs(all - cut), 1)} bn gal${parts.length ? "" : " of gasoline in 2050"}`);
        return parts.length ? parts.join("; ").replace(/^./, (x) => x.toUpperCase()) + "." : "Small changes in fuel prices.";
      },
      bld: () => {
        const parts = [];
        if (c.bld < 1) parts.push(`building energy set ${Math.round((1 - c.bld) * 100)}% below EIA by 2050`);
        if (t.adders.gas_home[j] > 0.005) parts.push(`the carbon cost adds $${fmt(t.adders.gas_home[j], 2)}/MMBtu to home gas`);
        if (c.bld < 1) parts.push("and the electricity saved shows up under power plants, not here");
        return parts.length ? parts.join(", ").replace(/^./, (x) => x.toUpperCase()) + "." : "Small changes in fuel prices.";
      },
      in: () => (c.carbon ? `Industry here responds only to fuel prices (fitted stub): the $${c.carbon}/t carbon cost raises what it pays for gas, oil and coal.` : "Small changes in fuel prices."),
    };
    const say = (k) => (k === "el" ? why.el() : k === "tr" ? why.tr() : k === "in" ? why.in() : why.bld());
    const top = cuts.filter(([, v]) => Math.abs(v) >= 1).sort((x, y) => Math.abs(y[1]) - Math.abs(x[1])).slice(0, 3);
    const big = Math.max(...top.map(([, v]) => Math.abs(v)));
    box.innerHTML = `<p class="story">CO2 ${total >= 0 ? "falls" : "rises"} by ${fmt(Math.abs(total) / 1000, 2)} Gt over 2027-2050. The biggest moves:</p><ol class="drivers">` +
      top.map(([k, v]) => `<li><div class="drv-head"><b>${SECTOR_NAME[k]}</b><span>${v >= 0 ? "-" : "+"}${fmt(Math.abs(v))} Mt${total ? `, ${fmt(Math.abs(100 * v / total), 0)}% of the change` : ""}</span></div>
        <div class="drv-bar"><i class="${v >= 0 ? "cut" : "rise"}" style="width:${(100 * Math.abs(v) / big).toFixed(1)}%"></i></div>
        <p>${say(k)}</p></li>`).join("") + `</ol>`;
  }

  function render(animate) {
    const c = current();
    el("carbon-out").textContent = `$${c.carbon} per ton CO2`;
    el("ev-out").textContent = evLabel(c.ev);
    el("bld-out").textContent = bldLabel(c.bld);
    tagModules();
    kpis(c.s);
    drawChart(c.s);
    trace(c.s);
    explain(c);
    engine(c.s, animate);
    writeHash();
  }
  Object.values(levers).forEach((l) => l.addEventListener("input", () => render(true)));
  el("year").addEventListener("input", () => engine(current().s, true));
  el("play").addEventListener("click", () => engine(current().s, true));
  el("reset").addEventListener("click", () => {
    const g = grid();
    levers.carbon.value = 0; levers.ev.value = g.ev2035.indexOf(null); levers.bld.value = g.buildings2050.indexOf(1);
    render(true);
  });
  document.querySelectorAll(".setswitch button").forEach((b) => {
    if (!SETS[b.dataset.set]) { b.disabled = true; b.title = "Not computed yet"; }
    b.addEventListener("click", () => { if (b.dataset.set !== set) { switchSet(b.dataset.set); render(true); } });
  });

  // ---- theme -------------------------------------------------------------------
  const root = document.documentElement;
  const themeBtn = el("theme");
  const systemDark = () => window.matchMedia("(prefers-color-scheme: dark)").matches;
  const isDark = () => root.dataset.theme ? root.dataset.theme === "dark" : systemDark();
  const label = () => (themeBtn.textContent = isDark() ? "Light" : "Dark");
  try { const saved = localStorage.getItem("nems-theme"); if (saved) root.dataset.theme = saved; } catch (e) { /* storage blocked */ }
  themeBtn.addEventListener("click", () => {
    root.dataset.theme = isDark() ? "light" : "dark";
    try { localStorage.setItem("nems-theme", root.dataset.theme); } catch (e) { /* storage blocked */ }
    label();
    render(false);
  });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { label(); render(false); });
  label();
  switchSet("fast");
  readHash();
  window.addEventListener("hashchange", () => { readHash(); render(false); });
  render(true);
})();
