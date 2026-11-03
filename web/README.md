# Policy sandbox (demo v0)

A static page: open `index.html` in a browser. No server needed; the data is bundled in
`data/scenarios.js`. Chart.js loads from cdnjs.

Data: `python scripts/precompute_scenarios.py` runs `run_model` over the grid (carbon
price 0-200 $/t in 25s, 4 EV levels for 2035, 4 building levels for 2050; 144 runs,
about 90 seconds on 8 workers) and writes `data/scenarios/<id>.json`, `data/meta.json`
and the bundle. Each scenario holds yearly US CO2, delivered prices, energy use by
sector, gasoline use, and the run's convergence log per year.

Not deployed anywhere.

Sharing: the address holds the scenario (`#c=100&ev=80&b=90&m=pel&y=2035`: carbon price,
2035 EV share or `ref`, building energy as a percent of EIA's, chart measure, traced
year), so a copied link opens the same view. "Download CSV" saves the selected scenario
and EIA's reference, year by year. `about.html` credits EIA and states that the project
is independent.

Engine view details: `python scripts/build_engine_catalog.py` builds `data/engine.js`
from the repo (SCOPE.md tables, EIA source line counts and routine headers in
nems-upstream, our Python, `pytest --collect-only`). Rerun it whenever a port lands.
The "trace this number" panel reads the `trace` block each scenario carries.

Publishing: `.github/workflows/pages.yml` deploys this folder to GitHub Pages, but only
when started by hand and only after Pages is enabled in the repo settings. Neither is
on.

Real ported modules: `python scripts/precompute_real.py --workers 3` runs a 16-scenario grid
with ported residential and commercial and the dispatch LP (about 30 minutes a run; reruns
skip finished scenarios). It reads the oracle dumps from a clone's `oracle/run*/out`
(`--oracle-root`, default the main NEMS Open folder). Output: `data/real/*.json` and
`data/real.js`. The page's set switch stays disabled until all 16 are done.

Loading: the page loads `data/meta.js` (2 KB gzipped: both sets' grids and EIA's reference)
and fetches each scenario as it is shown (`data/scenarios/<id>.json`, `data/real/<id>.json`,
about 3 KB gzipped). Opened from disk, or if a fetch fails, it loads the set's bundle
(`scenarios.js` or `real.js`) instead. All scripts are deferred.

Fidelity: `python scripts/fidelity.py` builds `data/fidelity.js` and `data/fidelity.json`, a grade for every module and every number on the page, with its evidence: "matches EIA" (a port checked against EIA's Fortran oracle; tolerances read from the tests, routines done read from SCOPE.md), "within X%" (our own model of a piece, measured against cb2026 in the no-policy run) or "stand-in" (fitted; the fit's error on held-out runs). A number takes the grade of the weakest piece behind it. The page shows each grade as a badge (hover for the evidence); `scoreboard.html` lists them all. Rerun it whenever tests, SCOPE.md or the scenario data change.

3D engine: `engine3d.html` draws NEMS from data read out of EIA's release. `python scripts/engine_structure.py` writes `data/engine3d/structure.json` and `routines.json` (modules, routines and calls, reads and writes of the shared variables, switches, ported routines; its docstring has the rules). `python scripts/engine_runs.py` writes `data/engine3d/runs.json` (three scenarios from EIA's case inputs and the recorded Reference trace; about 90 seconds, the ported modules run once). Grades come from `data/fidelity.json`. It needs a web server (`python -m http.server --directory web`), loads three.js from a CDN, keeps its state in the address, and falls back to a flat page under 700 px or without WebGL. Precomputed, not live; positions carry no meaning.

Uncertainty bands: the "How sure is this?" card reads `data/uncertainty.js` (`python -m nems_open.uncertainty run` then `summary`; method in `docs/uncertainty.md`). 10th, 50th and 90th percentiles of US CO2, household energy bill and home gas price over many runs of the fast loop on EIA's side-case inputs, a bar chart of which input explains the spread, and a table of the ranges. They are our sampling on stand-ins, not EIA's, and the card says so. If the file is missing the card hides itself.
