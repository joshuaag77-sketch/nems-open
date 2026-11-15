# Natural gas market (src/nems_open/ngmm)

A national stand-in for EIA's NGMM. Plan and the reasons it is not a port: [ngmm_plan.md](ngmm_plan.md).

    run_model.run(ogs="ngmm")              # gas market, long-run supply response fitted on EIA's cases
    run_model.run(ogs="hsm", cycles=2)     # gas market, EIA's HSM sets expected production between cycles
    python -m nems_open.run_model --ogs hsm --cycles 2

`ogs="standin"` (the default) keeps the old fitted price curves.

## How it works

Each iteration of the loop, the supply stand-in hands the loop's US gas use (QBLK/qngas, all sectors,
power plants included) to `GasMarket.prices`, which clears one national market and returns every MPBLK
gas price. Electricity prices and power-plant fuel switching then read the market's gas price to power
plants, so the gas price feeds back to demand and power in the same iteration.

- Supply: NGMM's short-run curve (`curve.py`, ported from `SupplyCurveParameters` in `natgas.ams`)
  through expected production Q0 at last year's wellhead price P0. Elasticity 0.5 within 3% of Q0, 0.7
  below and 0.3 above out to 12%, then 0.8 down to a floor at 18% of Q0 and 0.2 up to a cap at 4.4 times.
- Needed production: cb2026's realised production plus k times the change in gas use and gross
  exports. Exports fall with the wellhead price (elasticity -0.55 above cb2026's price, -0.08 below).
- Long run: Q0 = Q0_ref times exp(1.1 times the mean log change in wellhead price over the last two
  years). Reference: cb2026, or (ogs="hsm") HSM's expected production on the previous cycle's prices.
- Prices: Henry Hub moves 0.94 per wellhead dollar. Each delivered price moves by its own share of the
  Henry Hub change by census division (US: residential 0.84, commercial 0.82, industrial 0.99,
  power 1.00, transport 1.12), fitted on all nine side cases.

Coefficients: `coefficients.json`, rebuilt by `python -m nems_open.ngmm.fit`.

## Checks

Baseline gas use reproduces cb2026's Henry Hub, wellhead and every delivered gas price to 1e-9.

EIA's side cases, each driven by its own gas use year by year (`fit.check`). The two supply cases get
their own expected production, as HSM would hand it.

| case | 2050 Henry Hub, EIA | ours | error | EIA move vs cb2026 | ours |
|---|---|---|---|---|---|
| hm2026 | 2.003 | 1.963 | -2.0% | +5.0% | +2.9% |
| lm2026 | 1.858 | 1.846 | -0.6% | -2.6% | -3.2% |
| higheldmd | 1.966 | 1.954 | -0.6% | +3.1% | +2.5% |
| highztc | 1.945 | 1.932 | -0.7% | +2.0% | +1.3% |
| lowztc | 1.817 | 1.768 | -2.7% | -4.7% | -7.3% |
| altelec | 1.893 | 1.918 | +1.3% | -0.7% | +0.5% |
| electrnp | 1.964 | 1.835 | -6.6% | +3.0% | -3.8% |
| highogs | 1.126 | 1.251 | +11.1% | -41.0% | -34.4% |
| lowogs | 5.628 | 5.315 | -5.6% | +195.1% | +178.7% |

1987 $/MMBtu. electrnp misses because EIA raises LNG exports in that case by assumption (13.8 Tcf
against 11.2 in cb2026); the market only moves exports with price.

Full loop, EIA's ported residential and commercial modules, cb2026 reference, ogs="ngmm": 2050 Henry
Hub 1.907 against EIA's 1.907, and residential, commercial, industrial, power and transport gas prices
all within 0.1% (the ported demand lands on EIA's gas use to 0.01%).

High demand (load_growth 1000 TWh, ogs="ngmm"): US gas use +6.1% in 2050, Henry Hub +2.7%, gas to
power plants +2.7%, residential gas +0.7%.

With HSM in the loop (ogs="hsm", cycles=2; HSM runs on cycle 1's wellhead prices, its expected production
centres cycle 2's curve, and runs once more at the end for production):

| run | 2050 Henry Hub | gas to power plants | US gas use | HSM expected L48 production | minutes |
|---|---|---|---|---|---|
| reference (EIA: 1.907) | 1.907 (0.0%) | 0.0% | 0.0% | 41,681 Bcf (EIA's restart 41,714) | 29 |
| high demand, load_growth 1000 TWh | +3.2% | +3.2% | +5.9% | 42,968 Bcf (+3.1%) | 12 |

The market's expected production in the high-demand run (43,254 Bcf) sits within 0.7% of HSM's own answer
on those prices, so the fitted response and HSM agree where they meet.

## EIA's real NGMM (ogs="aimms")

`src/nems_open/ngmm/aimms.py` runs EIA's own NGMM (AIMMS 25.5.7.1, academic licence) headless, with no
Fortran and no web service. NEMS hands NGMM one text file per year (ngputvars.txt, 118 arrays) and reads one
back (nggetvars.txt), so we write the input file from the restart and the loop, and read the output as
NEMS's filer.f does. The library gets one extra entry point, NGMM_File_Call (EIA's NGMM_MainExecution_API
without the request read); a wrapper project keeps one AIMMS process open and serves year requests from a
file, so NGMM keeps its year-to-year state in memory as it does in NEMS. ng_runval.txt and ngsteo.txt are
written the way EIA's Python writes them; the wrapper uses EIA's endpoint project settings.

    python -m nems_open.ngmm.aimms 2024 2050     # reference: NGMM on cb2026's final inputs (3 min)
    run_model.run(ogs="aimms")                   # NGMM inside the loop

Speed: 10.9 s for 2024 (first-year initialisation), about 1.4 s a year after; a full run adds about 5.5 min
of NGMM time (330 s, three solves and a reporting call a year).

Reference, NGMM once per year on cb2026's final inputs, against EIA's restart:

| | 2025-2026 | 2030 | 2035 | 2040 | 2045 | 2050 |
|---|---|---|---|---|---|---|
| Henry Hub | 0.0% | +4.4% | +2.9% | +4.1% | +4.9% | +3.0% |
| residential | 0.0% | +0.9% | +0.8% | +1.0% | +0.8% | +0.6% |
| industrial | 0.0% | +3.3% | +2.5% | +3.4% | +3.6% | +2.7% |
| power | -0.8% | +1.9% | +1.3% | +2.3% | +3.4% | +2.9% |
| dry production (ngscrv_q) | 0.0% | -0.1% | -0.1% | +0.2% | +0.2% | +0.2% |

EIA's restart is the end of several iterations and five cycles; this is one pass, which likely explains
the 3-5% gap from 2027. In run_model each price is scaled by EIA's value over this reference
(calibrate=True), so the baseline is EIA's and a run's moves are NGMM's.

Full loop (ported residential and commercial, ogs="aimms"):

| run | 2050 Henry Hub | residential | industrial | power | US gas use | minutes |
|---|---|---|---|---|---|---|
| reference | 1.907 (EIA 1.907) | 0.0% | 0.0% | -0.1% | 0.0% | 8.0 |
| load_growth 1000 TWh | +10.6% | +2.0% | +8.4% | +11.0% | +2.3% | 7.8 |

With one cycle HSM's expected production stays at cb2026's, so supply has no long-run response: the
real NGMM then answers the shock about three times as hard as the stand-in, and its higher price cuts the
extra gas use from +5.9% to +2.3%. With cycles=2, HSM runs between cycles on NGMM's own wellhead prices
and its expected production (OGSMOUT ogenagprd, ogadgprd, ogprcoak, ogshaleng, ogngplprd, cnenagprd,
cnadgprd) feeds NGMM in cycle 2, as in NEMS:

| run, ogs="aimms", cycles=2 | 2030 HH | 2040 HH | 2050 HH | residential | industrial | power | US gas use | minutes |
|---|---|---|---|---|---|---|---|---|
| reference (EIA 1.835, 2.164, 1.907) | 1.837 | 2.180 | 1.909 | 0.0% | 0.0% | 0.0% | 0.0% | 16 |
| load_growth 1000 TWh | 1.869 | 2.209 | 1.960 (+2.8%) | +0.4% | +1.9% | +3.5% | +5.4% | 16 |

Closing the supply loop takes the 2050 Henry Hub move from +10.6% to +2.8%: in line with EIA's own high
electricity demand case (+3.1% on +4.5% gas use) and with the stand-in (+3.2% on +5.9%). This is the
recommended setting for gas: EIA's market model and EIA's supply model, both on the loop's demand.

## Limits

- National: one curve, not NGMM's state network. Regional basis and pipeline constraints stay as in
  cb2026; regional prices differ only through each division's fitted pass-through.
- Demand-side moves are a little soft: on EIA's demand cases the Henry Hub move averages about 70% of
  EIA's where demand rises. The calibrated long-run elasticity trades that against stability (above
  about 1.4 the lagged response cobwebs).
- The gas supply lever still multiplies prices toward lowogs/highogs on top of the market; moving Q0
  toward those cases' expected production would be more faithful.
- Imports, Alaska, RNG and supplemental supplies are held at cb2026.
