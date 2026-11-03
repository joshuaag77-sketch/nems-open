(function () {
  "use strict";
  const F = window.NEMS_FIDELITY;
  const el = (id) => document.getElementById(id);
  const esc = (x) => String(x).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  const pill = (grade, text) => `<span class="fid fid-${grade}">${esc(text)}</span>`;
  const NAMES = { match: "matches EIA", within: "within X%", stand: "stand-in" };
  const num = (x) => (x < 1e-3 ? x.toExponential(0) : String(x));
  const SETS = { fast: "Fast stand-ins (144 scenarios)", real: "Real ported modules (16 scenarios)" };

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
