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

Data center story: `datacenter.html` steps through four load cases; `engine3d.html` shows them as cards, and the ring animates each module's change between steps. `src/nems_open/datacenter_load.json` holds every load assumption with its source and every choice that is ours. `python scripts/datacenter_runs.py` runs them with ported residential, commercial and transportation and the dispatch LP (23 to 38 minutes each, one at a time, resumable) and writes `data/datacenter/*.json` and `data/datacenter.js`. Rerun `scripts/fidelity.py` after. Precomputed, not live.
Uncertainty bands: the "How sure is this?" card reads `data/uncertainty.js` (`python -m nems_open.uncertainty run` then `summary`; method in `docs/uncertainty.md`). 10th, 50th and 90th percentiles of US CO2, household energy bill and home gas price over many runs of the fast loop on EIA's side-case inputs, a bar chart of which input explains the spread, and a table of the ranges. They are our sampling on stand-ins, not EIA's, and the card says so. If the file is missing the card hides itself.

Switch atlas (`switches.html`): every key in EIA's scedes files, where the code reads it,
what it does, and which AEO side cases change it. `python scripts/build_switches.py` writes
`data/switches.json` and `data/switches.js` from `scripts/switches_meanings.json` (what readers
established from the code) and `scripts/switch_sites.py` (what a script can establish).

## Your America in 2050 (`2050.html`)

One screen for the curious public: ten levers or a story card on the left; a map of EIA's plant file
(27,124 of 27,337 units with coordinates, sized by capacity, colored by fuel, brightness by how hard
each runs) over the 25 EMM regions with a 2027-2050 slider; an energy river (sources to uses, from
QBLK); and the household energy bill against EIA's reference.

- Instant answers come from an emulator (`data/ux2050/emulator.json`): a polynomial fitted to 257
  fast-loop runs over eight levers (`python scripts/build_ux2050.py runs`, then `fit`). Each number's
  purple tag is the emulator's error on held-out runs; its grade badge is the weakest piece behind it,
  from `data/fidelity.json`. Building codes and appliance standards need EIA's ported buildings code,
  which the fast loop refuses, so the emulator leaves them out and says so.
- "Run the real model" calls `run_model.run` with residential, commercial and transportation ported,
  through `python scripts/serve_2050.py` (serves `web/` on http://localhost:8050 and adds `/api/run`).
  The page labels which result is which. Without the server the button explains how to start it.
- Plants: `python scripts/build_ux2050.py plants` writes `data/ux2050/plants.json` from the EMM plant
  file (`V_EMM_PLTF860`). Plants appear and retire on EIA's schedule; levers change how much they run,
  never which exist. Brightness is each plant's capacity factor scaled so its fuel matches the run's
  national total. Region borders are approximate (each point takes its nearest plant's region).
- "How did it get that?" opens `engine3d.html`.

Vercel preview: `vercel.json` serves `web/` with `/` going to `2050.html`; `.vercelignore` uploads
only `web/`; git deploys are off. A preview is `vercel deploy` (never `--prod`) from the repo root.
The preview has no `/api`, so it shows instant estimates only. Nothing is deployed yet.
