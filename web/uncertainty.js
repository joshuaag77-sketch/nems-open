// Uncertainty bands: 10/50/90 over many runs, and which input explains the spread.
// Data: data/uncertainty.js (python -m nems_open.uncertainty run, then summary).
(function () {
  const card = document.getElementById("uncert");
  const D = window.UNCERTAINTY;
  if (!card) return;
  if (!D) { card.hidden = true; return; }
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const MEASURES = {
    co2: { label: "US energy CO2", unit: "million metric tons CO2 a year", digits: 0 },
    bill: { label: "Household energy bill", unit: "2024 dollars per household a year, all residential fuels", digits: 0 },
    gas: { label: "Home gas price", unit: "2024 dollars per MMBtu, natural gas delivered to homes", digits: 2 },
  };
  const FACTOR_COLOR = { oil_gas_supply: "--bad", economic_growth: "--accent", load_growth: "--partial", technology_cost: "--stand" };
  let measure = "co2", level = 0, year = 2050;
  let fan = null, bars = null;

  const el = (id) => document.getElementById(id);
  const fmt = (v, d) => Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const money = (p) => (p === 0 ? "No carbon price" : "$" + p + " carbon price");
  const signed = (v) => (v >= 0 ? "+" : "") + v + "%";

  function build(box, items, current, onPick) {
    box.textContent = "";
    items.forEach(([key, text]) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = text;
      b.setAttribute("aria-selected", String(key === current));
      b.addEventListener("click", () => { onPick(key); render(); });
      box.appendChild(b);
    });
  }

  function drawFan() {
    const entry = D.carbon[level], b = entry.bands[measure], m = MEASURES[measure];
    const accent = css("--accent"), refc = css("--ref"), line = css("--line"), muted = css("--muted");
    const soft = css("--accent-soft");
    const cfg = {
      type: "line",
      data: {
        labels: D.years,
        datasets: [
          { label: "10th percentile", order: 4, data: b.p10, borderWidth: 0, pointRadius: 0, backgroundColor: soft, fill: false },
          { label: "10th to 90th percentile", order: 3, data: b.p90, borderWidth: 0, pointRadius: 0, backgroundColor: soft, fill: "-1" },
          { label: "Median", order: 1, data: b.p50, borderColor: accent, backgroundColor: accent, borderWidth: 2.5, pointRadius: 0, tension: 0.2 },
          { label: "EIA reference", order: 2, data: D.reference[measure], borderColor: refc, backgroundColor: refc, borderWidth: 2, borderDash: [6, 5], pointRadius: 0, tension: 0.2 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: { duration: 250 },
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          title: { display: true, text: m.unit, align: "start", color: muted, font: { size: 12, weight: "normal" } },
          tooltip: { callbacks: { label: (c) => c.dataset.label + ": " + fmt(c.parsed.y, m.digits) } },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: muted, maxTicksLimit: 7 }, border: { color: line } },
          y: { grid: { color: line }, ticks: { color: muted }, border: { display: false } },
        },
      },
    };
    if (fan) fan.destroy();
    fan = new Chart(el("unc-fan"), cfg);
  }

  function drawBars() {
    const rows = D.carbon[level].sensitivity[measure][String(year)];
    const muted = css("--muted"), line = css("--line");
    const cfg = {
      type: "bar",
      data: {
        labels: rows.map((r) => D.factors[r.factor].label),
        datasets: [{ data: rows.map((r) => r.share * 100), backgroundColor: rows.map((r) => css(FACTOR_COLOR[r.factor] || "--accent")), borderRadius: 3 }],
      },
      options: {
        indexAxis: "y", responsive: true, maintainAspectRatio: false, animation: { duration: 250 },
        plugins: {
          legend: { display: false },
          title: { display: true, text: "Share of the spread in " + year + " explained by each input alone, %", align: "start", color: muted, font: { size: 12, weight: "normal" } },
          tooltip: { callbacks: { label: (c) => fmt(c.parsed.x, 1) + "% of the spread" } },
        },
        scales: {
          x: { min: 0, grid: { color: line }, ticks: { color: muted }, border: { display: false } },
          y: { grid: { display: false }, ticks: { color: muted, autoSkip: false }, border: { color: line } },
        },
      },
    };
    if (bars) bars.destroy();
    bars = new Chart(el("unc-bars"), cfg);
  }

  function text() {
    const e = D.carbon[level], j = D.years.indexOf(2050), b = e.bands[measure], m = MEASURES[measure];
    el("unc-summary").textContent =
      money(e.price) + ", 2050: 80% of the " + e.n.toLocaleString("en-US") + " runs land between " +
      fmt(b.p10[j], m.digits) + " and " + fmt(b.p90[j], m.digits) + " (median " + fmt(b.p50[j], m.digits) +
      "; EIA reference with no carbon price " + fmt(D.reference[measure][j], m.digits) + ").";
    const body = el("unc-inputs");
    body.textContent = "";
    Object.keys(D.factors).forEach((k) => {
      const f = D.factors[k], tr = document.createElement("tr");
      const ends = [f.low_case, f.high_case].filter((c, i, a) => c !== "cb2026" && a.indexOf(c) === i);
      const swing = ends.map((c) => {
        const s = f.swing[c];
        return s ? c + ": Brent " + signed(s.brent_2050_pct) + ", home gas " + signed(s.gas_to_homes_2050_pct) +
          ", electricity sales " + signed(s.electricity_sales_2050_pct) : c;
      }).join("; ");
      [f.label, ends.join(" and "), swing].forEach((t) => {
        const td = document.createElement("td");
        td.textContent = t;
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
  }

  function render() {
    build(el("unc-measures"), Object.keys(MEASURES).map((k) => [k, MEASURES[k].label]), measure, (k) => { measure = k; });
    build(el("unc-levels"), D.carbon.map((c, i) => [i, money(c.price)]), level, (k) => { level = Number(k); });
    build(el("unc-years"), [[2035, "2035"], [2050, "2050"]], year, (k) => { year = Number(k); });
    drawFan();
    drawBars();
    text();
  }

  function start() {
    if (window.Chart) render(); else setTimeout(start, 50);
  }
  start();
  const theme = el("theme");
  if (theme) theme.addEventListener("click", () => setTimeout(() => { if (window.Chart) render(); }, 30));
})();
