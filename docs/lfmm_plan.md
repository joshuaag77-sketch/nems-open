# LFMM: scope and the smallest path

EIA's Liquid Fuels Market Module (LFMM) models US refining, biofuels and product trade. It is the
largest supply module we have not ported. This note sizes it, lists what crosses the restart
file, and records the path taken in this push: a fitted stand-in, graded amber, behind
`run_model.run(lfmm="standin")`, off by default.

## What EIA ships

| Piece | Where | Size |
|---|---|---|
| LP model (sets, variables, equations) | `models/lfmm/source/lfmodel.gms` | 87 KB, about 100 variable and equation blocks, `Model LFMM / all /` |
| Data prep | `lfprep.gms`, `lfinput.gms` | 320 KB |
| Shell: year loop, three solves per year (STEO volume limits off, then on) | `lfshell.gms` (+ `_hogs` variant) | 100 KB |
| NEMS interface (restart arrays to GAMS and back) | `lf_nem.gms` | 84 KB |
| Reports | `lfreport.gms`, `lfrepset.gms` | 510 KB |
| Fortran driver | `source/refine.f` (+ `_hogs`, `_logs`) | 4,000 lines; writes the GDX, calls GAMS, reads results |
| Input data | `models/lfmm/input/lfminput.gdx` (plus hp, lp, hogs variants), `lfminset.gdx`, `lfhist.gdx`, `lfinvest.gdx` | 8.2 MB each; binary GDX |
| Text inputs | `rfhist*.txt`, `rfinvest.txt`, `mu1prds.txt`, `mu2prds.txt`, `refogmap.txt`, `varlistl.txt` | 1 MB |

It is GAMS, not AIMMS. The coal lane's AIMMS composite-table parser does not apply. Its
transfer-schema and dictionary parser (`nems_open/dictionary.py`) does: the restart variables
below were read through `input/dict.txt` the same way. Solved with `Solve LFMM minimizing
TotalCost using lp`, so HiGHS can take it once translated.

What blocks a port today: every input table sits in GDX, and this machine has no GAMS and no GDX
reader (no `gams`, `gdxpds` or `gams.transfer`). The LP's row and column counts are not measured
for the same reason: they come from the sets in `lfminset.gdx`.

## What crosses the restart file

`varlistl.txt` lists what LFMM reads and writes, 343 entries across 39 blocks. The ones that matter:

**In** (from other modules)
- Demand: QBLK (53 arrays), product demand by sector and census division; TRANREP (15), E85 and
  flex-fuel detail; QONROAD.
- Prices: MPBLK (39), last iteration's prices, including gas, electricity and coal to refineries;
  NGTDMREP; COALOUT.
- Crude and liquids supply: OGSMOUT (16): domestic crude by type (OGCRDPRD, OGCRUDEREF), NGPL
  production (OGNGPLPRD, OGNGPLET/PR/BU/IS/PP), CO2 for EOR. INTOUT (all): world crude prices
  and import supply curves.
- Biomass and renewables: WRENEW (36). Macro: MACOUT (5). Policy: EMISSION (16), EMABLK, EMEBLK,
  AB32, TCS45Q (carbon prices, LCFS and RFS settings).
- Expectations: MXQBLK (44), MXPBLK (9).

**Out** (what the rest of the loop reads)
- Product prices, MPBLK: gasoline (PMGTR, PMGCM, PMGIN), diesel and distillate (PDSTR, PDSRS,
  PDSCM, PDSIN, PDSEL), jet (PJFTR), residual (PRLTR, PRLCM, PRLIN, PRLEL, PRHTR, PRHEL), kerosene
  (PKS*), propane (PPR*), feedstocks (PPFIN), asphalt (PASIN), coke (PPCIN), ethanol (PETTR).
- Refinery fuel, QBLK: QELRF, QNGRF, QCLRF, QBMRF, QSGRF, QPCRF, QOTRF, QDSRF, QRSRF, QLGRF,
  QRLRF, QTPRF, QTSRF; INDREP QCCRF (catalytic coke). Refinery fuel is counted inside industrial
  use (QNGIN includes QNGRF, QELIN includes QELRF, QSGIN is QSGRF).
- Trade and reporting: PMMOUT (crude runs RFQTDCRD, product supplied RFQPRDT, crude and product
  imports and exports), PMMRPT, PMMFTAB, LFMMOUT (137 arrays: capacity, utilisation, RFS and LCFS
  credits, biofuels).

## What the loop needs

The demand modules read product prices; the gas and power markets read refinery gas and
electricity. Everything else in LFMM's output is reporting or feeds modules we run off EIA's
numbers. So the smallest path is:

1. US refinery-gate price changes for gasoline, diesel, jet and residual, passed to every sector
   and region (distribution and tax margins are fixed in LFMM too).
2. Refinery fuel use (QBLK q*rf), with the change folded into industrial use so the gas market
   and CO2 see it.

## The stand-in (built)

`src/nems_open/lfmm/standin.py`, fitted by `python -m nems_open.lfmm.fit` on EIA's 10 AEO2026
cases (2027-2050, US).

    dP_p   = dBrent / heat_p  +  a_p * P0_p * dlog Q_p          (gasoline, diesel, jet, residual)
    dlog Q_ts = 0.51 * dlog Q_liquids                            (total refinery energy)
    dlog Q_el = 1.04 * dlog Q_liquids                            (refinery electricity)
    dlog s_ng = -0.98 * dlog(P_gas_ind / Brent)                  (gas share of refinery fuel)

Crude passes through dollar for dollar per barrel of product. That is set, not fitted: freed,
the fit gives 0.7 to 1.7 and holds out worse, because only the two oil and gas supply cases move
Brent. Own-demand responses: gasoline 0.57, jet 0.22, residual 0.48, diesel 0 (its fit is
negative). Coefficients and every case's error are in [lfmm_fit.md](lfmm_fit.md).

Results, largest US error 2027-2050:

| | cb2026 | demand-side cases (hm, lm, higheldmd, highztc, lowztc, altelec) | highogs | lowogs | electrnp |
|---|---|---|---|---|---|
| Gasoline, diesel, jet, residual | 0% (exact) | under 5% (worst 4.8%) | under 9% | 15% gasoline, 10% jet | under 9% |
| Refinery energy, total | 0% | under 3% | 7% | 3% | 3% (10% held out) |
| Refinery natural gas | 0% | 10% or less | 54% | 45% | 12% |

It meets the brief on cb2026 (exact by construction) and on the demand-side cases. It misses on
refinery gas when gas prices move far (lowogs: gas to industry 2.7 times the reference by 2050,
refinery gas falls to 0.38 times), and on gasoline in lowogs, where Brent rises 23% and gasoline
rises more than dollar for dollar. The supply stand-in misses gasoline in lowogs by the same 15%.

Grade: **amber**. A fit to EIA's runs, not EIA's LP: no capacity, no crude slate, no trade, no RFS
or LCFS, no biofuels. It responds to crude price, product demand and gas price, nothing else.

## In the loop

`run(lfmm="standin")` (CLI `--lfmm standin`). Each iteration, right after demand answers and
before EIA's convergence test, the stand-in reads that demand, Brent and last iteration's gas
price to industry, sets QBLK q*rf and folds the refinery change into q*in. After the supply
stand-in answers, its gasoline, diesel, jet and residual prices are replaced by LFMM's, keeping
the supply side's carbon adders and lever multipliers. On the baseline the run matches
`lfmm=None` to 1e-5. With 90% EV sales, 2050 refinery energy falls 8% (2,637 to 2,431 TBtu) and
gasoline falls a further 0.45 1987 $/MMBtu. Every year converges.

Known gap: the demand side's industrial stub carries the baseline's refinery fuel inside q*in and
scales it with its own price response; the fold assumes it is the baseline amount.

## Can it be checked with AIMMS?

No. LFMM is GAMS end to end: `refine.f` writes GDX files, calls GAMS on `lfshell.gms`, and reads GDX
back. No AIMMS project ships in `models/lfmm`. The AIMMS academic licence (used for coal and EMM)
does not help here. A reference run needs a GAMS licence that can solve an LP this size (the free
community licence caps model size, likely too small), plus EIA's NEMS-side driver or a standalone
run of `lfshell.gms` on GDX dumped from the cb2026 restart. The cheaper check, available now, is
EIA's own cb2026 outputs in the restart file (LFMMOUT, PMMOUT, MPBLK), which the stand-in already
reproduces exactly.

## Running EIA's LFMM: licences and readers (checked 2026-11-14)

**Free GAMS licences.** The Community licence (academic, 12 months) caps LP at 5,000 rows and 5,000 columns; LFMM's LP
(about 100 variable families and 136 equation families over refining regions, refinery types, processes and modes,
crudes, sources and supply steps, streams, census divisions and three periods, `lfmodel.gms`) is far above that, though
its exact size is unmeasured (it comes from the sets in `lfminset.gdx`). The demo licence is smaller still. Since
June 2026 GAMS offers a free **Personal licence** that, per GAMS, supersedes the Community licence and has no model-size
limit, for individual, non-commercial use by students, researchers and hobbyists, with open-source solvers only (HiGHS,
SCIP, IPOPT, SHOT; no CPLEX, Xpress or Gurobi). A free academic GAMSPy licence (institutional email) adds some commercial
solvers. Full academic GAMS is discounted, not free. Penn's software licensing office lists no GAMS site licence
(listings cover MATLAB, Mathematica, Stata, SPSS, Esri); ask licenses@upenn.edu before paying for anything. Sources:
gams.com/free-licenses, forum.gams.com "Availability of the New GAMS Personal License", gams.com UG_License,
osl.isc.upenn.edu.

So lfshell.gms fits the free Personal licence, not the Community or demo ones. Signing up and installing GAMS is
Josh's step. One catch: EIA solves LFMM with Xpress (`$set LPsolver Xpress` in lfshell.gms; a CPLEX option file is
kept). The Personal licence would solve it with HiGHS (one line). Product prices are LP duals, so where the LP is
degenerate HiGHS can return different prices than Xpress; that needs a check against cb2026, as coal and gas had.

**Reading EIA's GDX files.** The GDX files are GDX version 7 from GAMS 43.2, uncompressed (element names are plain
text). Tried in a throwaway environment: `gamsapi[transfer]` 54.7.0 from PyPI installs, but the wheel carries only the
Python wrapper (`gams.core.gdx`); the GDX library itself (`gdxcclib64.dll`) comes with a GAMS installation, so
gams.transfer and gdxpds cannot read GDX here until GAMS is installed. Reading needs no licence. Without GAMS there are
two open routes: build GAMS's MIT-licensed GDX library from its GitHub source (GAMS-dev/gdx), or write a small
pure-Python reader for uncompressed GDX v7 against that source.

**Smallest slice for product prices.** Prices are not a slice: LFMM sets each product's price from the dual of its
census-division demand row (`RecipeDemands.m(CenDiv, product, Period)` divided by the GDP deflator, lfreport.gms
915-945), then adds margins and policy adjustments (AB 32 in the Pacific). Refining is joint production, so one
gasoline or diesel price needs the whole refinery LP for the current period: crude supply and transport, processes
and modes, recipe and specification blending, transport to census divisions, product trade, and the RFS block
(RIN costs move gasoline and diesel prices). What can be left out for a first translation: the three-period
look-ahead (current period only), LCFS, CFP and WACFS (state programs, separable blocks), CO2 for EOR, coal and
biomass to liquids. Still weeks of work, most of it the data layer (lfprep.gms, 320 KB, builds the coefficients).

**Recommendation.** Fastest path to EIA's real refining model in the loop, the way coal and gas went: Josh signs up for
the free GAMS Personal licence and installs GAMS; then `run(lfmm="gams")` writes LFMM's per-year GDX input from the
loop (gams.transfer, now able to load the GDX library), runs lfshell.gms with HiGHS, and reads prices and refinery fuel
back. Check HiGHS against cb2026 first. The HiGHS translation stays the open fallback, as for coal.

## Full port, later

1. GDX reader. GAMS publishes its GDX library as open source; a small reader (or a one-time
   dump to npz on a machine with GAMS) unlocks every input table.
2. Translate `lfmodel.gms` to HiGHS (as the coal lane did for CMM), with `lf_nem.gms` as the
   map from restart arrays to model parameters and back. Reuse `dictionary.py` for the arrays.
3. Port the three-solve sequence in `lfshell.gms` and the price recovery (duals of the product
   balance rows give the refinery-gate prices).
4. Oracle: EIA's cb2026 LFMMOUT, PMMOUT and MPBLK arrays in the restart file.

Rough size: larger than the coal LP. Weeks, not days, and most of it is the data layer.
