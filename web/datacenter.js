// The data center story: four load cases, one step at a time. Every number here, including
// those in sentences, is read from data/datacenter.js (scripts/datacenter_runs.py); every
// grade from data/fidelity.js (scripts/fidelity.py).
(function () {
  "use strict";
  const D = window.NEMS_DATACENTER, F = window.NEMS_FIDELITY;
  const el = (id) => document.getElementById(id);
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const fmt = (x, d = 0) => Number(x).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const KEYS = Object.keys(D.case_notes).filter((k) => D.cases[k]);
  const yi = (y) => D.years.indexOf(y);
  const OUT = (F.sets.datacenter || F.sets.real).outputs;
  const pill = (key) => { const o = OUT[key]; return o ? `<span class="fid fid-${o.grade}" title="${esc(o.summary)}">${esc(o.label_grade)}</span>` : ""; };
  const assumed = (title) => `<span class="fid fid-input" title="${esc(title)}">public forecast</span>`;
  const quote = (s) => s.findings;

  let step = 0, year = 2035, metric = "dc";
  try { const q = new URLSearchParams(location.hash.slice(1)); if (KEYS.includes(q.get("s"))) step = KEYS.indexOf(q.get("s")); if (+q.get("y")) year = +q.get("y"); if (q.get("m")) metric = q.get("m"); } catch (e) { /* a bad address just starts at the top */ }

  const ROWS = [
    { k: "dc", label: "Data center electricity", unit: " TWh", d: 0, get: (c) => c.datacenter_twh, input: true },
    { k: "gw", label: "The same, as load", unit: " GW", d: 0, get: (c) => c.datacenter_gw, input: true },
    { k: "sales", label: "All US power sales", unit: " TWh", d: 0, get: (c) => c.trace.totals.elec.map((x) => x * 1000 / 3.412), out: "use" },
    { k: "co2", label: "US energy CO2", unit: " Mt", d: 0, get: (c) => c.co2, out: "co2" },
    { k: "co2el", label: "Power plant CO2", unit: " Mt", d: 0, get: (c) => c.trace.co2_sector.el, out: "co2.el" },
    { k: "whl", label: "Wholesale power", unit: " $/MWh", d: 1, get: (c) => c.wholesale, out: "whl" },
    { k: "pel", label: "Average retail power price", unit: " ¢/kWh", d: 1, get: (c) => c.prices.electricity, out: "pel" },
    { k: "bill", label: "Household energy bill", unit: " $/yr", d: 0, get: (c) => c.bill, out: "bill" },
    { k: "ng", label: "Home gas price", unit: " $/MMBtu", d: 2, get: (c) => c.prices.gas_home, out: "ng" },
    { k: "burn", label: "Gas burned in power plants", unit: " quads", d: 2, get: (c) => c.trace.power_burn.gas, out: "co2.el" },
    { k: "uns", label: "Load the fleet cannot meet", unit: " TWh", d: 1, get: (c) => c.unserved_twh, out: "unserved" },
    { k: "cut", label: "Flexible load cut", unit: " TWh", d: 1, get: (c) => c.curtailed_twh, out: "unserved" },
  ];
  const row = (k) => ROWS.find((r) => r.k === k);
  const val = (key, k, y = year) => { const v = row(k).get(D.cases[key])[yi(y)]; return v === null || v === undefined ? NaN : v; };
  const METRICS = ["dc", "co2", "co2el", "whl", "bill", "uns"].map(row);
  const COLORS = { reference: "--ref", utility: "--partial", ai_high: "--accent", ai_high_flex: "--stand" };

  // ---- the words for each step, built from the data ------------------------------------
  const src = (id) => { const s = D.sources[id]; return `<a href="${esc(s.url)}">${esc(s.publisher)}, ${esc(s.date)}</a>`; };
  function delta(k, key, base, y = year) {
    const a = val(key, k, y), b = val(base, k, y), r = row(k), d = a - b;
    if (!isFinite(a) || !isFinite(b)) return "n/a";
    return `${d >= 0 ? "+" : "-"}${fmt(Math.abs(d), r.d)}${r.unit}`;
  }
  const STORY = {
    reference: () => {
      const y = 2035;
      return `<p>EIA's reference already has data centers growing fast. On the whole-facility count Berkeley Lab uses, they go from ${fmt(val("reference", "dc", 2025))} TWh in 2025 to ${fmt(val("reference", "dc", y))} TWh in ${y}, about ${fmt(val("reference", "gw", y))} GW of load.</p>
        <p class="fine">EIA's own category is narrower (servers only), so it is scaled by the 2023 ratio to ${src("lbnl_2024")}. Scaled this way, EIA's 2028 is ${fmt(val("reference", "dc", 2028))} TWh, against that report's range of ${quote(D.sources.lbnl_2024).twh_2028_low.value} to ${quote(D.sources.lbnl_2024).twh_2028_high.value}.</p>`;
    },
    utility: () => {
      const f = quote(D.sources.grid_strategies_2025);
      return `<p>Add up what utilities and grid operators have published and you get about ${f.datacenter_peak_growth_gw_2025_2030.value} GW of new data center load by 2030 (${src("grid_strategies_2025")}). Against EIA's reference, that adds ${fmt(val("utility", "dc", 2030) - val("reference", "dc", 2030))} TWh in 2030. Power plant CO2 moves ${delta("co2el", "utility", "reference", 2030)} that year and wholesale power ${delta("whl", "utility", "reference", 2030)}.</p>
        <p class="fine">The same report doubts its own total: analysts put growth nearer ${f.market_analyst_gw_2025_2030.value} GW, so utility forecasts are likely about ${f.datacenter_peak_growth_gw_2025_2030.value - f.market_analyst_gw_2025_2030.value} GW too high. No forecast here goes past 2030, so the added amount is held flat after that.</p>`;
    },
    ai_high: () => {
      const a = quote(D.sources.anthropic_2025).ai_capacity_gw_2028.value, b = quote(D.sources.bnef_2026).datacenter_gw_2035.value;
      return `<p>Higher numbers come from the AI industry and from analysts. One developer says US AI needs at least ${a} GW by 2028 (${src("anthropic_2025")}), and BloombergNEF now expects ${b} GW for all data centers by 2035 (${src("bnef_2026")}). By 2035 this case adds ${fmt(val("ai_high", "dc", 2035) - val("reference", "dc", 2035))} TWh over EIA. Power plant CO2 moves ${delta("co2el", "ai_high", "reference", 2035)} and wholesale power ${delta("whl", "ai_high", "reference", 2035)}. Gas burned in power plants moves ${delta("burn", "ai_high", "reference", 2035)}: with nothing being built, existing gas plants carry it. ${val("ai_high", "uns", 2035) > 0 ? `The fleet cannot make ${fmt(val("ai_high", "uns", 2035), 1)} TWh of it.` : "The fleet can make all of that energy, which is not the same as holding the peak hour."}</p>
        <p class="fine">${esc(D.sources.anthropic_2025.disclosure)} No hyperscaler publishes a US-wide load forecast, so this is the nearest public statement. The BloombergNEF figure comes through a news report; the forecast itself is paid.</p>`;
    },
    ai_high_flex: () => {
      const f = quote(D.sources.duke_2025).curtailment_share;
      const cuts = val("ai_high_flex", "cut", 2035);
      return `<p>Same load, but the new data centers can cut ${(f.value * 100).toFixed(1)}% of their yearly energy when the grid is tightest, the rate studied by ${src("duke_2025")}. In 2035 they cut ${fmt(cuts, 1)} TWh. Power plant CO2 moves ${delta("co2el", "ai_high_flex", "ai_high", 2035)} and wholesale power ${delta("whl", "ai_high_flex", "ai_high", 2035)}: almost nothing.</p>
        <p class="fine">That small effect is a limit of this model, not a finding against flexibility. Duke's result is about holding the peak with less new capacity, and this model neither builds capacity nor tests the peak hour. It can only see the energy in those hours.</p>`;
    },
  };

  // ---- drawing -----------------------------------------------------------------------------
  const STEP_N = KEYS.length;
  el("steps").innerHTML = KEYS.map((k, i) => `<button type="button" role="tab" data-i="${i}">${i + 1}. ${esc(D.case_notes[k].label)}</button>`).join("");
  el("steps").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { step = +b.dataset.i; draw(); }));
  el("metrics").innerHTML = METRICS.map((m) => `<button type="button" role="tab" data-k="${m.k}">${esc(m.label)}</button>`).join("");
  el("metrics").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { metric = b.dataset.k; draw(); }));
  el("years").innerHTML = [2030, 2035, 2050].map((y) => `<button type="button" data-y="${y}">${y}</button>`).join("");
  el("years").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { year = +b.dataset.y; draw(); }));

  let chart = null;
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  function drawChart(cur) {
    const m = row(metric);
    const first = yi(D.start_year);
    const labels = D.years.slice(first);
    const data = KEYS.map((k) => ({
      label: D.case_notes[k].label, data: m.get(D.cases[k]).slice(first), borderColor: css(COLORS[k]), backgroundColor: css(COLORS[k]),
      borderWidth: k === cur ? 3 : 1.5, borderDash: k === cur ? [] : [5, 4], pointRadius: 0, tension: 0.15,
    }));
    if (chart) chart.destroy();
    if (!window.Chart) return;
    chart = new window.Chart(el("chart"), {
      type: "line", data: { labels, datasets: data },
      options: { responsive: true, maintainAspectRatio: false, animation: { duration: 400 }, interaction: { mode: "index", intersect: false },
        plugins: { legend: { labels: { color: css("--muted"), boxHeight: 2 } }, title: { display: true, text: m.label + "," + m.unit, align: "start", color: css("--muted"), font: { weight: "normal", size: 12 } } },
        scales: { x: { ticks: { color: css("--muted"), maxTicksLimit: 8 }, grid: { display: false } }, y: { ticks: { color: css("--muted") }, grid: { color: css("--line") } } } },
    });
  }
  function drawTable(cur) {
    const prev = KEYS[Math.max(0, KEYS.indexOf(cur) - 1)];
    el("numbers").innerHTML = `<thead><tr><th>${year}</th><th>Grade</th><th class="num">EIA reference</th><th class="num">This step</th>${cur === prev ? "" : `<th class="num">Change from step ${KEYS.indexOf(prev) + 1}</th>`}</tr></thead><tbody>` +
      ROWS.filter((r) => r.k !== "cut" || D.case_notes[cur].flex_share).map((r) => {
        const a = val(cur, r.k), b = val("reference", r.k);
        const grade = r.input ? assumed(`${D.case_notes[cur].short} Sources: ${D.case_notes[cur].sources.map((s) => D.sources[s].publisher).join("; ")}`) : pill(r.out);
        return `<tr><td>${esc(r.label)}</td><td>${grade}</td><td class="num" data-label="EIA reference: ">${isFinite(b) ? fmt(b, r.d) + r.unit : "n/a"}</td><td class="num" data-label="This step: "><b>${isFinite(a) ? fmt(a, r.d) + r.unit : "n/a"}</b></td>` +
          (cur === prev ? "" : `<td class="num" data-label="Change: ">${delta(r.k, cur, prev)}</td>`) + `</tr>`;
      }).join("") + `</tbody>`;
    el("numbers-note").textContent = `Hover a grade for its evidence. ${D.sectors.join(", ")} run EIA's ported code; electricity runs the dispatch LP; industrial, gas, oil, coal and retail power prices stay fitted. Prices in ${D.dollars}.`;
  }
  function draw() {
    const cur = KEYS[step];
    el("steps").querySelectorAll("button").forEach((b, i) => b.setAttribute("aria-selected", i === step));
    el("metrics").querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", b.dataset.k === metric));
    el("years").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", +b.dataset.y === year));
    el("step").innerHTML = `<h2>${step + 1}. ${esc(D.case_notes[cur].label)}</h2>${STORY[cur]()}
      <div class="step-nav">${step ? `<button type="button" class="ghost" id="back">Back</button>` : ""}${step < STEP_N - 1 ? `<button type="button" class="ghost" id="next">Next: ${esc(D.case_notes[KEYS[step + 1]].label)}</button>` : ""}</div>`;
    const go = (id, d) => { const b = el(id); if (b) b.addEventListener("click", () => { step += d; draw(); }); };
    go("back", -1); go("next", 1);
    drawChart(cur); drawTable(cur);
    try { history.replaceState(null, "", `#s=${cur}&y=${year}&m=${metric}`); } catch (e) { /* opened from disk */ }
  }

  // The check: EIA's high-demand case builds plants; this fleet does not. CO2 per TWh added, 2050.
  const per100 = (co2, twh) => (100 * co2) / twh;
  const j50 = yi(2050), U = D.cases.utility;
  const eiaPer = per100(D.eia_builds.co2_mt[j50], D.eia_builds.added_twh[j50]);
  const ourPer = per100(U.co2[j50] - D.cases.reference.co2[j50], U.added_twh[j50]);
  el("limits").innerHTML = `<h2>What this cannot tell you</h2><ul>` +
    `<li><b>Nothing gets built.</b> ${esc(D.choices.fleet)} A check: in 2050, EIA's own high-demand case, which does build, adds ${fmt(eiaPer)} Mt of CO2 per 100 TWh of extra sales. The utility case here adds ${fmt(ourPer)} Mt per 100 TWh.</li>` +
    ["adequacy", "scope", "gw_to_twh", "after_last_anchor", "flexibility"].map((k) => `<li>${esc(D.choices[k])}</li>`).join("") +
    `<li>Retail prices come from curves fitted to EIA's runs, and the rest of supply stays fitted too, so the grades above say which numbers to lean on. <a href="scoreboard.html">Every grade and its evidence</a>.</li></ul>`;
  const used = [...new Set(KEYS.flatMap((k) => D.case_notes[k].sources))];
  el("sources").innerHTML = `<h2>Where each assumption comes from</h2><ul class="links">` + used.map((id) => {
    const s = D.sources[id];
    return `<li><a href="${esc(s.url)}">${esc(s.title)}</a>, ${esc(s.publisher)}, ${esc(s.date)}. Read: ${esc(s.read)}.<ul class="ev">` +
      Object.values(s.findings).map((f) => `<li>${esc(f.where)}</li>`).join("") + `</ul></li>`;
  }).join("") + `</ul>`;
  draw();
})();
