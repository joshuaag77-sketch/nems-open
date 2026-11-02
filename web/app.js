(function () {
  "use strict";
  const DATA = window.NEMS_DATA;
  const meta = DATA.meta;
  const ref = meta.reference;
  const years = meta.years;
  const yi = (y) => years.indexOf(y);

  // ---- levers --------------------------------------------------------------
  const el = (id) => document.getElementById(id);
  const levers = { carbon: el("carbon"), ev: el("ev"), bld: el("bld") };
  const evLabel = (v) => (v === null ? Math.round(ref.ev_share[yi(2035)] * 100) + "% (EIA)" : Math.round(v * 100) + "%");
  const bldLabel = (v) => (v === 1 ? "Same as EIA" : Math.round((1 - v) * 100) + "% less than EIA");

  function current() {
    const carbon = meta.carbon[+levers.carbon.value];
    const ev = meta.ev2035[+levers.ev.value];
    const bld = meta.buildings2050[+levers.bld.value];
    const id = `c${carbon}_ev${ev === null ? "ref" : Math.round(ev * 100)}_b${Math.round(bld * 100)}`;
    return { carbon, ev, bld, s: DATA.scenarios[id] };
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
  ];
  let measure = MEASURES[0];
  const tabs = el("tabs");
  MEASURES.forEach((m) => {
    const b = document.createElement("button");
    b.type = "button";
    b.role = "tab";
    b.textContent = m.label;
    b.setAttribute("aria-selected", m === measure);
    b.addEventListener("click", () => {
      measure = m;
      [...tabs.children].forEach((c) => c.setAttribute("aria-selected", c === b));
      render();
    });
    tabs.appendChild(b);
  });

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  let chart = null;
  function drawChart(s) {
    const accent = css("--accent"), refc = css("--ref"), line = css("--line"), muted = css("--muted");
    const scen = measure.get(s), base = measure.get(ref);
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

  // ---- engine view -------------------------------------------------------------
  const MODULES = [
    { group: "Demand" },
    { name: "Residential", kind: "real", tag: "Ported, matches EIA. Stub in this run", side: "d" },
    { name: "Commercial", kind: "real", tag: "Ported, matches EIA. Stub in this run", side: "d" },
    { name: "Industrial", kind: "partial", tag: "Being ported. Stub", side: "d" },
    { name: "Transportation", kind: "partial", tag: "Being ported. Stub", side: "d" },
    { group: "Supply" },
    { name: "Electricity", kind: "stand", tag: "Stand-in", side: "s" },
    { name: "Natural gas", kind: "stand", tag: "Stand-in", side: "s" },
    { name: "Oil and refining", kind: "stand", tag: "Stand-in", side: "s" },
    { name: "Coal", kind: "stand", tag: "Stand-in", side: "s" },
    { name: "Emissions", kind: "stand", tag: "EIA carbon factors", side: "s" },
  ];
  const modBox = el("modules");
  const modEls = { d: [], s: [] };
  MODULES.forEach((m) => {
    const div = document.createElement("div");
    if (m.group) {
      div.className = "mod-group";
      div.textContent = m.group;
    } else {
      div.className = "mod " + m.kind;
      div.innerHTML = `<div class="name">${m.name}</div><div class="tag">${m.tag}</div>`;
      modEls[m.side].push(div);
    }
    modBox.appendChild(div);
  });
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

  // ---- wiring ------------------------------------------------------------------
  function render(animate) {
    const c = current();
    el("carbon-out").textContent = `$${c.carbon} per ton CO2`;
    el("ev-out").textContent = evLabel(c.ev);
    el("bld-out").textContent = bldLabel(c.bld);
    kpis(c.s);
    drawChart(c.s);
    engine(c.s, animate);
  }
  Object.values(levers).forEach((l) => l.addEventListener("input", () => render(true)));
  el("year").addEventListener("input", () => engine(current().s, true));
  el("play").addEventListener("click", () => engine(current().s, true));
  el("reset").addEventListener("click", () => {
    levers.carbon.value = 0; levers.ev.value = 1; levers.bld.value = 0;
    render(true);
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
  render(true);
})();
