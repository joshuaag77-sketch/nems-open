# Natural gas market (NGMM): plan

## What EIA ships

NGMM in AEO2025 and AEO2026 is AIMMS, not Fortran or Python: `nems-upstream/models/ngas/`
(`mainproject/natgas.ams`, about 17,000 lines, plus `nlp.ams` and `repts.ams`). It is a monthly
network model over states, hubs and pipeline arcs, solved as an LP/NLP inside AIMMS. NEMS talks to it
through the restart arrays listed in `input/nggetvars.txt` (in) and `input/ngputvars.txt` (out).

Reads (main ones): sector gas demand (QBLK q*ng, q*gf, q*gi, lease and plant fuel qlpin, pipeline fuel
qgptr), HSM's expected production (OGSMOUT ogenagprd, ogadgprd, ogrnagprd), world oil price, GDP
deflator, degree days and floorspace.

Writes: Henry Hub (NGTDMREP/oghhprng), wellhead prices by HSM region (ogwprng, ogprcng), delivered
prices by census division and sector (MPBLK png*, pgf*, pgi*, and the EMM-region arrays in NGTDMOUT),
imports and exports (ngimpvol, ngexpvol), production realised (ogrnagprd, ogprdng), and the national
short-run supply curve it used (NGTDMREP/ngscrv_q0, _p0, _q, _p, _elas, _per, _min, _max).

## Why not a port

No AIMMS licence, so no oracle: a port could only be matched to the restart, and 17,000 lines of
monthly state network for a showcase run that needs annual census-division prices is the wrong trade.

## What we build instead (src/nems_open/ngmm)

The same economics at national scale, with EIA's own curve and EIA's own numbers:

1. Short-run supply: NGMM's piecewise supply curve (`SupplyCurveParameters`, ported exactly) through
   HSM's expected production Q0 at last year's wellhead price P0, with the elasticities and step widths
   EIA writes to the restart (ngscrv_elas = 0.8, 0.7, 0.5, 0.3, 0.2; ngscrv_per = 3%, 9%).
2. Market clearing: production needed = baseline production plus the change in domestic use and net
   exports (lease, plant and pipeline fuel scale with it). LNG exports fall when prices rise (fitted on
   EIA's low and high oil and gas supply cases).
3. Long run: Q0 responds to the run's recent prices. With ogs="ngmm" by an elasticity fitted on EIA's
   seven demand-side cases; with ogs="hsm" EIA's HSM itself runs between cycles on the run's prices and
   hands its expected production to the next cycle.
4. Prices out: wellhead moves Henry Hub dollar for dollar; every delivered gas price (MPBLK, by census
   division and sector) moves by a fitted share of the Henry Hub change (distribution markups mostly fixed).

Calibration is exact by construction: baseline demand gives cb2026's prices to rounding.

## Checks

- Baseline demand reproduces cb2026 Henry Hub and delivered prices (unit test).
- Held-out: each of EIA's demand cases (hm2026, lm2026, higheldmd, highztc, lowztc, altelec, electrnp)
  driven by its own demand and exports; 2050 Henry Hub error reported in docs/ngmm.md.
- Reference run (ported demand, ogs="hsm"): 2050 Henry Hub and delivered prices within 5% of EIA.
- High-demand case raises the price.
