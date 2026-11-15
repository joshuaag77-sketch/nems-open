(function () {
  "use strict";
  const F = window.NEMS_FIDELITY;
  const el = (id) => document.getElementById(id);
  const esc = (x) => String(x).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  const pill = (grade, text) => `<span class="fid fid-${grade}">${esc(text)}</span>`;
  const NAMES = { match: "matches EIA", within: "within X%", stand: "stand-in" };
  const num = (x) => (x < 1e-3 ? x.toExponential(0) : String(x));
  const SETS = { fast: "Fast stand-ins (144 scenarios)", real: "Real ported modules (16 scenarios)", datacenter: "Data center story (ported residential, commercial and transportation, dispatch LP)" };

  el("grades").innerHTML = Object.entries(F.grades).map(([g, t]) => `<li>${pill(g, NAMES[g])} ${esc(t)}</li>`).join("");
  el("generated").textContent = `Built ${F.generated} from ${F.tests_collected.toLocaleString("en-US")} collected tests. Reference: ${F.reference}.`;

  // Evidence, as short lines: what was checked and how closely.
  function evidence(p) {
    const e = p.evidence, out = [];
    if (e.routines !== undefined) {
      out.push(`${e.routines_done} of ${e.routines} routines done (SCOPE.md, ${esc(e.scope_section)})` +
        (e.not_done.length ? `; not yet: ${esc(e.not_done.join("; "))}` : ""));
      if (e.tolerance_loosest) out.push(`Against EIA's Fortran (the oracle): ${num(e.tolerance_most_common)} typical, ${num(e.tolerance_loosest)} at worst, relative`);
      if (e.published_run_tolerance) out.push(`Against EIA's published run: within ${num(e.published_run_tolerance)} per cell (${esc(e.published_run_tests.join(", "))})`);
    }
    if (e.worst_gap_pct !== undefined) out.push(`Worst gap against ${esc(e.measured_against)}: ${e.worst_gap_pct}%`);
    if (e.fits) out.push("Fits: " + e.fits.map((f) => `${esc(f.price.replace("MPBLK/", ""))} ${f.rmse_pct}% in fit, ${f.held_out_rmse_pct_worst}% held out`).join("; "));
    if (e.fuels) out.push(`${e.fitted} of ${e.fuels} sector-fuel elasticities fitted`);
    if (e.tests !== undefined) out.push(`${e.tests.toLocaleString("en-US")} tests in ${e.test_files.length} files`);
    if (e.doc) out.push(`See ${esc(e.doc)}`);
    return `<p>${esc(p.summary)}</p><ul class="ev">${out.map((x) => `<li>${x}</li>`).join("")}</ul>` +
      (e.test_files && e.test_files.length ? `<details><summary>Test files</summary><p class="fine">${esc(e.test_files.join(", "))}</p></details>` : "");
  }
  const order = { match: 0, within: 1, stand: 2 };
  el("parts").querySelector("tbody").innerHTML = Object.entries(F.parts)
    .sort((a, b) => order[a[1].grade] - order[b[1].grade])
    .map(([, p]) => `<tr><td><b>${esc(p.name)}</b></td><td>${pill(p.grade, p.label)}</td><td>${evidence(p)}</td></tr>`).join("");

  // How close is the whole model to EIA: one run with every finished module on (scripts/full_model.py).
  fetch("data/full_model.json").then((r) => (r.ok ? r.json() : null)).then((W) => {
    if (!W) return;
    const pct = (x) => (x === undefined || x === null ? "" : `${x > 0 ? "+" : ""}${x.toFixed(1)}%`);
    const cls = (x) => (x === undefined || x === null ? "" : Math.abs(x) <= 2 ? "gap-ok" : Math.abs(x) <= 10 ? "gap-mid" : "gap-far");
    const fmt = (x) => (x === null || x === undefined ? "" : Math.abs(x) >= 100 ? Math.round(x).toLocaleString("en-US") : x.toFixed(2));
    const yrs = W.shown;
    const body = W.rows.map((r) => {
      const cells = yrs.map((y) => r.model === null ? `<td class="num" data-label="${y}: ">${fmt(r.eia && r.eia[y])}</td>`
        : `<td class="num ${cls(r.gap_pct[y])}" data-label="${y}: " title="Model ${fmt(r.model[y])}, EIA ${fmt(r.eia[y])} ${esc(r.unit)}">${pct(r.gap_pct[y])}</td>`).join("");
      const worst = r.model === null ? `<td data-label="Worst: "><i>${esc(r.note)}; EIA's value shown</i></td>`
        : `<td class="num ${cls(r.worst_gap_pct)}" data-label="Worst year: ">${pct(r.worst_gap_pct)}</td>`;
      return `<tr><td>${esc(r.label)} <span class="fine">${esc(r.unit)}</span></td>${cells}${worst}</tr>`;
    }).join("");
    const on = Object.entries(W.switches).map(([k, v]) => `${k}=${v}`).join(", ");
    el("whole").innerHTML = `<h2>How close is the whole model to EIA?${W.cycles_done && W.cycles_done < W.cycles ? ` <span class="fine">(${W.cycles_done} cycle of ${W.cycles})</span>` : ""}</h2>
      <p>One run of the whole model with every finished module switched on, on EIA's reference settings, against EIA's AEO2026 reference (cb2026). Each cell is the gap, model over EIA minus one; hover for both values.</p>
      <div class="tbl"><table class="rt board-t"><thead><tr><th>Number</th>${yrs.map((y) => `<th>${y}</th>`).join("")}<th>Worst year</th></tr></thead><tbody>${body}</tbody></table></div>
      <p class="fine">Run ${esc(W.generated)}${W.minutes ? `, ${W.minutes} minutes` : ""}${W.cycles_done && W.cycles_done < W.cycles ? `, after ${W.cycles_done} of ${W.cycles} cycles (NEMS repeats the whole span so slow-moving markets catch up; the later cycles had not finished)` : ""}; ${W.converged_years} of ${W.years[1] - W.years[0] + 1} years converged. Switches: ${esc(on)}. Sectors on EIA's ported code: ${esc(W.ported.join(", "))}. Not landed yet: ${esc(W.not_landed.join(", ") || "none")}. ${esc(W.method)}</p>`;
    el("whole").hidden = false;
  }).catch(() => {});

  el("sets").innerHTML = Object.entries(F.sets).map(([name, s]) => {
    const rows = Object.entries(s.outputs).map(([, o]) => {
      const by = [...new Set(Object.values(o.modules))].map((k) => F.parts[k].name);
      return `<tr><td>${esc(o.label)}</td><td>${pill(o.grade, o.label_grade)}</td>` +
        `<td class="num" data-label="Gap vs EIA: ">${o.gap_pct === undefined ? "n/a" : o.gap_pct.toFixed(2) + "%"}</td>` +
        `<td data-label="Produced by: ">${esc(by.join(", "))}</td></tr>`;
    }).join("");
    return `<h2>Numbers in the sandbox: ${esc(SETS[name] || name)}</h2>
      <p class="fine">Gap: the no-policy run against EIA's AEO2026 reference, worst year 2027-2050. A number is only as good as the weakest piece behind it.</p>
      <div class="tbl"><table class="rt board-t"><thead><tr><th>Number</th><th>Grade</th><th>Gap</th><th>Produced by</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }).join("");
})();
