# AIMMS reference runs we need

For the day the AIMMS academic license arrives. Written 2026-11-13 by the electricity capacity lane (branch `emm-capacity3`).

## What the license does and does not give us
EIA's AIMMS projects are in the checkout (`nems-upstream/models/*/MainProject/*.ams`), but none runs on its own: each gets its data from NEMS's Fortran at run time through transfer arrays (`uaimms.f`, `AIMMS_TransArray_out_*`) or per-year composite files (`./efd/composite_YYYY_II.txt`). So step 1 is not "open AIMMS and press run"; it is making our WSL EMM oracle (`oracle/build_wsl.sh emm`, which today skips ECP and stands in for EFD) call the real ECP and EFD setup, write those composite files, and hand them to AIMMS. AIMMS itself runs on Windows; the composite files are plain text, so WSL writes them and Windows AIMMS reads them.

## Models, in priority order
| # | AIMMS project | NEMS module | Why we need it |
|---|---|---|---|
| 1 | `models/ecp/MainProject/ecp.ams` | ECP, electricity capacity planning | The capacity lane's scorecard (builds, retirements by region and type) is matched to a tolerance today against outputs only; we cannot see ECP's inputs or duals |
| 2 | `models/efd/MainProject/efd.ams` | EFD, electricity dispatch | Its outputs (`ULREVS` family) set ECP's retirement groups; the EMM oracle uses a stand-in for it (`oracle/efd_standin.f90`) |
| 3 | `models/coal/MainProject/coal.ams` | CMM, coal market | The coal lane's plan (`docs/coal_plan.md`) names an AIMMS reference export as its blocker |
| 4 | `models/rest/MainProject/EMM_renewable.ams` | ReStore (storage dispatch inside EMM) | Battery cycling a third of EIA's (`docs/trade_storage.md`) |
| 5 | `models/ephrts/MainProject/ephrts.ams` | hydrogen | Off in cb2026 (`EPHRTS = 0`); last |

## Cases
1. **cb2026** (the AEO2026 reference restart every lane uses), years 2025 to 2050, final iteration of each year (`FCRL = 1`). This alone unblocks items 1 and 2.
2. **One policy side case**, for checking that our levers move the same way EIA's do: a carbon-price case if EIA ships one with these inputs, else `hm2026` / `lm2026` (high and low macro), which the macro lane already reads.

## Arrays to export (ECP and EFD), every year, final iteration
Per year as CSV or one npz per year: name, dimensions in Fortran order, values.

ECP inputs (written before `AIMMS_ECP` is called, `udat.f` / `uecp.f`):
- `EPGCAP(fuel region, retire group, ECP type)` and `EPGFOM(retire group, ECP type)`, per EMM region (`udat.f` 10820-10880). We rebuild these now (`emm/retire_groups.py`); this checks them.
- `RET_VAL`, `RET_CAP`, `RET_FOM`, `RET_FRG` per plant group record, and `RET_MIN`, `RET_MAX`, `RET_AVG` per type (the ranking behind the groups).
- `EPIRCCR` (capacity credit by intermittent type) and `EP_NET_PEAK`, `EPPEAK`, `EPMRM` per region (`CAP_CREDIT`, `EP$MRM`). Rebuilt now in `emm/capacity_credit.py`.
- `DUCK_SYSTEM_LOAD(month, day type, hour, region, year)`: the 864-hour load ECP sees.
- `EPDSCRT`, `EPUIRT`, `EPUCRE`, `UPRSK`, `UPNRRTEA`, `UPNIRTEA` per region and type (cost of capital and risk premiums). Rebuilt from the restart's macro rates; this checks the formula.
- `EPECAP(fuel region, ECP type, planning year)`: existing capacity by type.

ECP outputs (after the solve):
- Builds, retirements, retrofits and coal-to-gas conversions by ECP type, region and planning year (the LP's column values, not only the restart's `UADD*` totals).
- Duals of the reserve margin rows `R<region>XXXXX<year>` (the restart has only their average, `RMAVG`) and of the load rows by slice.
- The objective coefficient of each build and existing-capacity column (annualized capital cost as ECP sees it).

EFD outputs (feed next year's ECP):
- Per plant group: `ULREVS`, `ULCAPC`, `ULVCST`, `ULFCST`, `ULSO2P`, `ULNOXP`, `ULRPSP`, `ULHGP`, `ULGHG`, `ULTGEN` (`UEFDOUT`).
- Energy prices by region and EFD slice (duals of the demand rows).

Inputs missing from the checkout (not AIMMS, but same request to EIA or from the full NEMS install that comes with the license):
- The renewable module's `windalt` file: `IntStDdv` and `IntRegCrl` (single-site standard deviation and regional correlation of wind and solar), read in `renew.f` 1320-1341. `capacity_credit.py` assumes the variance cap binds so these drop out; the file would confirm or correct that.

## Coal (item 3)
Per `docs/coal_plan.md`: the coal LP's inputs and solution by supply curve, demand region and year for cb2026 (production, transport flows, the price duals by demand region, and the contract and diversity constraints' duals). The coal lane should confirm the exact array names before the run.

## Order of work on the day
1. Install AIMMS, open `ecp.ams` and `efd.ams`, note the AIMMS version they need (the project files name it).
2. In the WSL EMM oracle, swap the ECP skip and the EFD stand-in (`oracle/hooks.py`) for the real setup code up to the composite-file write; run 2025 only; feed AIMMS; compare the EFD solution's regional prices with our dispatch LP.
3. Then the full 2025 to 2050 export above, under `HEAVY.lock`.
