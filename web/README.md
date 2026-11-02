# Policy sandbox (demo v0)

A static page: open `index.html` in a browser. No server needed; the data is bundled in
`data/scenarios.js`. Chart.js loads from cdnjs.

Data: `python scripts/precompute_scenarios.py` runs `run_model` over the grid (carbon
price 0-200 $/t in 25s, 4 EV levels for 2035, 4 building levels for 2050; 144 runs,
about 90 seconds on 8 workers) and writes `data/scenarios/<id>.json`, `data/meta.json`
and the bundle. Each scenario holds yearly US CO2, delivered prices, energy use by
sector, gasoline use, and the run's convergence log per year.

Not deployed anywhere.

Engine view details: `python scripts/build_engine_catalog.py` builds `data/engine.js`
from the repo (SCOPE.md tables, EIA source line counts and routine headers in
nems-upstream, our Python, `pytest --collect-only`). Rerun it whenever a port lands.
The "trace this number" panel reads the `trace` block each scenario carries.

Publishing: `.github/workflows/pages.yml` deploys this folder to GitHub Pages, but only
when started by hand and only after Pages is enabled in the repo settings. Neither is
on.
