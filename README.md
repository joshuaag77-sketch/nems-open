# NEMS Open

An open Python rebuild of the U.S. Energy Information Administration's National Energy Modeling System (NEMS), the model behind the Annual Energy Outlook. The goal is a model anyone can run, read and change, ending in a browser version where you can play with America's energy system to 2050.

Not affiliated with or endorsed by EIA.

## How it works

NEMS is about 300,000 lines of Fortran plus models that need paid solvers. We rebuild it one piece at a time, and every piece has to reproduce EIA's own numbers.

The answer key is the **oracle**: EIA's original Fortran, compiled with free gfortran and run outside NEMS on EIA's published AEO2026 reference run. It dumps EIA's internal state just before and just after each routine. A Python port passes when, fed the "before" state, it reproduces the "after" state.

## Status

Commercial buildings module (`source/comm.f`):

| Step | Status | Match vs EIA |
|---|---|---|
| Floorspace | Ported | 1e-6 |
| Service demand | Ported (calculation) | 4e-7 |
| Technology choice | Ported (calculation) | 2e-6 |
| Consumption | Ported (calculation) | 5e-7; US total to 4 decimals |
| Calibration, reports, on-site generation, file readers | Open | |

Other modules (residential, industrial, transportation, electricity, fuels) have not started. See [SCOPE.md](SCOPE.md) for the full map, the oracle, and EIA quirks the port keeps on purpose.

## Run it

You need Python 3.11+, numpy, pytest, and gfortran (on Windows: `winget install BrechtSanders.WinLibs.POSIX.UCRT`).

```
git clone https://github.com/EIAgov/NEMS nems-upstream     # EIA's code, about 1 GB
cd oracle
python -I gen_oracle.py ../nems-upstream cb2026          # dump EIA's reference run
bash build.sh                                            # compile EIA's commercial module
cd run && ./oracle.exe                                   # run it, about a minute
cd ../.. && python -m pytest                             # check every port against it
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Open pieces are listed as GitHub issues.
