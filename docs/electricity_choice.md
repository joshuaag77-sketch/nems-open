# Electricity: which model replaces EMM

Branch `elec-scoping`, 2026-11-02. Scoping for issue #7.

## Recommendation

Build a purpose-made LP in linopy with HiGHS, shaped like EMM's own ECP and EFD, and port EMM's Fortran pricing (EFP) and load code (LDSM) with the oracle method. Use PyPSA-USA and GenX as cross-checks and as a source of cost and resource data, not as the base.

Confidence: medium (about 70%). The fact that would move it: a one-week spike showing that ReEDS or PyPSA-USA can be re-zoned to the EMM regions and reproduce EIA's 2025 to 2035 capacity additions within 15% with no custom data work. I doubt it, but it is the cheapest way to be wrong.

Why, in order of weight:
1. Both EMM optimization models are plain LPs. `models/ecp/MainProject/ecp.ams` and `models/efd/MainProject/efd.ams` each declare `Type: LP` (checked in the AIMMS source). Nothing needs a MIP solver. A direct translation to linopy is feasible, and HiGHS handles LPs well.
2. NEMS does not just need generation and capacity. It needs retail prices by sector and census division, and those come from EFP (`uefp.f`, 12k lines of Fortran: cost of capital, rate base, depreciation, allocation to sectors). No candidate has this. It has to be ported whichever model we pick, so most of the exchange logic is ours either way.
3. The adoptable models use different regions, different plant data and different policy logic from EIA's. The crosswalk and data work is close to the size of writing a small LP, and then the result no longer tracks EIA's assumptions.
4. ReEDS is the closest in spirit but needs GAMS, and open-solver support is a side path.

Honest cost of this choice: it is the most work of the four, and a first version will not reproduce EIA's plant-by-plant detail (200 plant groups per retrofit cluster, 55 dispatchable types in ECP). The plan below stages the detail in.

## Comparison

| | ReEDS (NREL ReEDS-2.0) | PyPSA-USA | GenX (Julia) | linopy + HiGHS, EMM-shaped |
|---|---|---|---|---|
| License | BSD-3 | MIT | GPL-2.0 | Ours, Apache 2.0 like the repo. linopy and HiGHS are open source |
| Solver | GAMS required; CPLEX recommended. COIN-OR Cbc has solved small systems, "not actively maintained". No HiGHS support found | Gurobi default; HiGHS and GLPK supported | HiGHS default; Gurobi, CPLEX optional | HiGHS |
| Free-solver ready | No. GAMS itself is paid | Yes, slower | Yes | Yes |
| Regions vs EMM's 25 | Balancing-area zones (about 130, from memory), not EMM regions. Needs a crosswalk | Clusters of the transmission network, three interconnections, lower 48. Needs a crosswalk | You define zones. Region-neutral | Native: the 25 EMM regions plus Alaska and Hawaii (MNUMNR=28 with the US row) |
| Maps to 9 census divisions | Via crosswalk | Via crosswalk | Via crosswalk | Via EMM's own conversion matrices (`CNV1CRNR`, `DSMCENV`) |
| Prices by sector | No. System cost and marginal prices only | No | No | Needs the EFP port (planned) |
| EIA AEO2026 inputs | Not directly. Different plant, cost, policy tables | Not directly | Not directly | Yes, reads `input/emm/` and the oracle arrays |
| 2025 to 2050 solve | Hours per scenario with CPLEX (from memory) | Overnight to days at full detail; hours when clustered | Myopic mode is quick; perfect foresight is heavy | Target: per-year LP in minutes, full run under 90 minutes (estimate below) |
| Takes NEMS demand | Own demand profiles; adapter needed | Own demand; adapter needed | CSV load per zone; adapter easy | Native: census-division sales plus LDSM load shapes |
| Returns NEMS outputs | Generation, capacity, emissions; no sector prices, no unit-level coal use | Same | Same | All, by construction |
| Maintenance | NREL repo archived 2026-04-22; work moved to the ReEDS-Model org | Active, research-led | Active, large community | Ours |

Sources checked: the ReEDS and GenX GitHub pages, PyPSA-USA docs, a 2021 note on running ReEDS with open solvers, and 2026 HiGHS benchmark slides (HiGHS about 1.5x slower than Gurobi on LPs, diverging past roughly a million variables). Items marked "from memory" were not confirmed this session.

## Run-time estimate for the recommended design

Annual steps 2025 to 2050 is 26 solves in a myopic loop. EMM itself solves ECP with a 30-year planning horizon and 10 explicit years.

- Dispatch (EFD-like): 27 regions, about 60 unit types, 48 to 96 time slices: 100k to 400k variables per year. HiGHS: seconds to a few minutes.
- Capacity (ECP-like): same regions, 12 load groups by 24 vertical segments (`ECP_D_STP`, `ECP_D_VLS`), 55 dispatchable plus 9 intermittent plus 11 other renewable plus 3 storage types: about 0.5M to 1.5M variables with a 10-year explicit window. HiGHS interior point: minutes to tens of minutes.
- Whole run: roughly 30 to 90 minutes if the NEMS loop needs 3 to 5 iterations per year. This is an estimate, not a measurement. Step 2 of the plan measures dispatch, step 4 measures capacity.

## Interface spec

Dimensions from `includes/parametr`: MNUMYR=61 (1990 to 2050), MNUMCR=11 (nine census divisions, California, US total), MNUMNR=28 (EMM regions incl. Alaska, Hawaii, US). Shapes in brackets were checked in the `cb2026` reference `restart.npz`, and are the checkable targets. Rows without a shape come from the Fortran includes only.

### In (NEMS to electricity)

| Quantity | Variables | Shape | Source |
|---|---|---|---|
| Electricity sales by sector | `QBLK/QELRS, QELCM, QELIN, QELTR` | [11, 61] | demand modules |
| Load shape by end use and EMM region | LDSM output: `dsmnemsc`, ECP and EFD load duration curve blocks | by EMM region; 12 groups x 24 segments (ECP); season and segment (EFD) | `ELLDSM` in `uldsm.f` |
| Fuel prices to power | `MPBLK/PNGEL, PCLEL, PDSEL, PRSEL` | [11, 61] | gas, coal, oil modules |
| Gas price by gas region | NGTDM prices to EFD | 17 gas regions (see `UEFDOUT/QNGELGR`) | natural gas module |
| Coal supply curves and transport | `coalemm` block (`MX_SUPPLY_CURVES`, `CMM_*` profiles) | by coal supply region | coal module |
| Uranium, biomass, hydrogen prices | EFD fuel price inputs | by region | supply stand-in |
| Macro | interest rates, inflation, deflator for capital cost | [61] | macro driver |
| Policy | tax credits, RPS (`UECPOUT/ST_RPS_*`), CO2 and 111d rules (`CALC111D`), CCS credits | by state or EMM region | `input/emm/`, scenario files |
| Renewable resource and cost | wind, solar, geothermal steps, distributed generation | by EMM region | `input/emm/`, renewable module |

### Out (electricity to NEMS)

| Quantity | Variables | Shape |
|---|---|---|
| Retail price by sector | `MPBLK/PELRS, PELCM, PELIN, PELTR, PELAS` | [11, 61] |
| Price components | `UEFPOUT/PELAV, PELCP, PELFL, PELOM, PELWH, PELME, PELTL, PELBS` | [11, 61] |
| Wholesale price by end use | `EUSPRC/PELWHRS` and siblings | [11, 61] |
| Fuel use by plant fuel | `QBLK/QCLEL, QNGEL, QDSEL, QRSEL, QUREL, QGEEL, QSTEL, QPVEL, QWIEL, QTREL` | [11, 61] |
| Gas use by gas region | `UEFDOUT/QNGELGR` | [17, 61] |
| Coal use by coal unit | `coalemm`: `EMM_CL_BTUS, EMM_CL_CF, EMM_CL_ECPT`; retirements and retrofits `R_RY, E_RY, EG_RY` | by unit |
| Generation and capacity by type | `UDATOUT/UGEN*` and `UCAP*` (for example `UCAPSSU`, `UGENNU`), builds `UECPOUT/UADD*` | [28, 61] each |
| Emissions | `EMISSION/EMELC, EMEL, EMELNOX, EMELSC, EMELCCS`, `ECP_QCAR` | [11, 8, 61], [28, 61], [61] |
| Duals for other modules | marginal price by EFD slice, carbon and RPS credit prices | by region and year |

Minimum set to close the NEMS loop in the first version: sales and load shape in; PELxx, the Q*EL fuel use rows, generation, capacity and CO2 out. The rest is staged.

## Tolerance for "first version works"

Against the `cb2026` reference case, 2025 to 2050:
- National average retail price (PELAS) within 5% each year; each census division within 10% on average over the horizon.
- National generation by fuel group (coal, gas, nuclear, wind, solar, hydro, other) within 10% in each of 2030, 2040, 2050.
- Coal and gas use for power (QCLEL, QNGEL) within 10%.
- Electric power CO2 within 10%.
- Capacity additions through 2035 within 15%. This is the least stable quantity in any capacity model.

Bit-for-bit matching is not the goal. A solver and formulation change will move the marginal builds, so the test is aggregates, not plants.

## Step plan

One person plus agents. Weeks are elapsed calendar weeks.

| Step | Weeks | Done when |
|---|---|---|
| 1. Data layer: read `input/emm/` (plant list, `ecpdaty.xlsx`, `emmcntl.txt`, `eldatyr.txt`, load files) and the oracle arrays into one Python data package | 2 | Existing capacity by region and type matches `UCAP*` for 2025 |
| 2. Dispatch LP (EFD-like), capacity fixed from the oracle, 27 regions, 48 slices | 2 | Generation by type and marginal price within 10% of the reference for 2025, 2030, 2040, 2050; solve time measured |
| 3. Port LDSM (`uldsm.f`) so load shapes come from NEMS demand, not the oracle | 3 | Load blocks match the oracle within float tolerance |
| 4. Capacity LP (ECP-like), myopic, builds and retirements, tax credits, RPS | 4 | Additions to 2035 within 15%, to 2050 within 25% |
| 5. Port EFP pricing (`uefp.f`) | 4 | PELxx within 5% national when fed oracle costs and generation |
| 6. Fuel and policy coupling: gas and coal prices from the stand-in, 111d, CCS, emissions | 2 | Q*EL and CO2 within tolerance |
| 7. Close the loop in NEMS Open with the demand modules and the supply stand-in; run the reference case | 2 | All tolerance rows above met for `cb2026` |
| Total | 19 | First version producing prices within tolerance |

Plan on 4 to 5 months with slack. Steps 2 and 5 can start alongside step 1 with a second worker, since both take oracle inputs, which saves about 3 weeks.

Main risk is step 4. EMM has plant-level retrofit logic (scrubbers, CCS retrofit, biomass cofiring, up to 200 plant groups per cluster) that the first version leaves out. If step 4 misses its margin after two weeks of tuning, fall back to fixing the capacity path from the reference case for the base run and optimize builds only in policy scenarios.

## What I did not check

- ReEDS and PyPSA-USA region counts, run times and release dates were not confirmed from their docs this session.
- The size of the ECP LP is inferred from set sizes in `emmparm`, not from a solved instance.
- I did not read all of `ecp.ams` (118k lines) or `efd.ams` (52k). The interface list comes from the Fortran includes and the reference `restart.npz`.
