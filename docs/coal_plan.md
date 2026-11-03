Coal Market Module port plan

Scope and evidence

This is a plan for a faithful AEO2026 CMM port to Python, linopy and HiGHS by one worker. Budget 14 working weeks, with a 12 to 18 week range once reference checkpoints are available. Obtaining an AIMMS reference export is an external dependency, not time silently included in that estimate. No CMM implementation or solver run was performed for this scoping document.

Inspected on 2026-11-02. Upstream is the read-only checkout at C:/Users/joshu/OneDrive/Desktop/3. AI Projects/NEMS Open/nems-upstream, commit 1bfbb2af4c3eb6e884227630ae67eb0e0e3c72ba. Paths and line numbers below are relative to that checkout unless stated otherwise. Counts include blank lines and comments. Routine counts run from the declaration through its closing END or brace, inclusive, rather than counting the space up to the next routine.

Method follows this checkout's SCOPE.md and CONTRIBUTING.md and the orchestration PLAN.md at C:/Users/joshu/OneDrive/Desktop/3. AI Projects/NEMS Open/PLAN.md. PLAN.md is absent from the coal-scoping checkout. Preserve EIA's calculations and quirks, compare intermediate states before translating readers, then test the complete chain. Keep compiler fidelity, LP equivalence and agreement with the converged NEMS reference as three separate checks.

The main finding is that AEO2026 CMM is already almost entirely AIMMS. There is no standalone coal.f, coal production Fortran file or coal distribution Fortran file in this source tree. Its production equations, transport calculations, distribution optimization, trade model, emissions controls and output assembly live together in models/coal/MainProject/coal.ams. The gfortran oracle can test the small remaining Fortran expectations hook. It cannot execute the AIMMS production equations or LP.

Code and file boundary

The complete CMM model-language inventory is:

- models/coal/MainProject/coal.ams: 28,310 lines, 95 procedures, 136 Variable declarations, 78 Constraint declarations and three MathematicalProgram declarations. Most lines outside procedures are data declarations, definitions, mappings and reports. These definitions are executable model logic and must be included in the effort estimate.
- models/coal/MainProject/case.ams: 44 lines, two case-management procedures. A legacy auxiliary file; Project.xml selects coal.ams. Do not assume every auxiliary file or GUI procedure is on the production call path.
- models/coal/MainProject/nchar.ams: seven lines, three string declarations, no routines. Scenario/date metadata.
- models/coal/Coal.aimms and MainProject/Project.xml: project/library configuration. The former names AIMMS 25.3.1.0 and AimmsXLLibrary 24.0.0.2; the latter names AIMMS 25.5.4.3. These are recorded file versions, not proof of the reference run's installed solver version.
- models/main/aimms_endpoint/MainProject/aimms_endpoint.ams: shared API host, dispatches cl::coal_API_Call at line 89. The Python port replaces this CMM boundary with a direct function call.

The complete remaining CMM-specific Fortran routine inventory is:

- source/util_tools.f90: COAL_EXPECT, lines 1360-1391, 32 lines. Copies XCL_1TESC and XCL_2TESC into the electricity planning expectations horizon, clamping beyond AEOLSTYR to the last available year.
- source/util_tools_prepro.f90: COAL_EXPECT, lines 1296-1327, 32 lines. Duplicate/preprocessing variant of the same logic. Treat these as one algorithm, not two port tasks.
- source/util_call_pyd1_module.f90: COAL_EXPECT_GO, lines 11-14, four lines, inside module CMM_RUN at lines 9-15. Calls COAL_EXPECT.
- source/pyfiler1-f2pywrappers2.f90: F2PYINITCMM_RUN, lines 7066-7070, five lines. Generated binding, replace with direct Python invocation. Related generated declarations are source/pyfiler1.pyf:6586-6589 and the coal_expect_go binding in source/pyfiler1module.c.

Shared Fortran support is not a second coal solver. NDATOT in source/util_tools.f90:374-501 (128 lines), with its counterpart in util_tools_prepro.f90:325-452 (128 lines), writes restart data and the COALUNITO plant/unit cycling file. Keep its coal serialization semantics in the harness; do not port the entire NEMS file manager for CMM. source/ind.f:12697-12880 contains COALTPC (184 lines), but it belongs to industrial demand, not CMM. Coal consumers in uecp.f, uefd.f, udat.f, emissions and refining remain outside this module's ownership.

Coal-specific include files, all declarations with no routines:

  includes/coalemm    789 lines    plant demand, coal quality and profiles
  includes/coalout     76 lines    aggregate outputs and balance state
  includes/coalprc     14 lines    marginal delivered electricity coal prices
  includes/acoalprc    14 lines    adjusted-price common block
  includes/coalrep     88 lines    production, trade and emissions reports
  includes/cdsparms    99 lines    coal dimensions and legacy limits
  includes/ecp_coal   264 lines    electricity-side coal representation
  includes/epmclprc    12 lines    alternate declaration of ACOALPRC
  includes/uso2grp    133 lines    electricity coal supply curves and expectations

Also load parametr, ncntrl, emmparm and the interface blocks named in the inventories below. Do not confuse the legacy NSREG=14 reporting dimension in cdsparms with the six physical supply regions in current input data. Likewise, epmclprc declares APCLELCDR in ACOALPRC while acoalprc declares PCLELCDR in that same common block. The restart key is ACOALPRC/pclelcdr; this is not an additional CMM output.

Shared Python integration to reuse or replace narrowly:

- models/main/nexec.py:168-186 calls CMM through aimms_endpoint.run_module, checks its status, then calls coal_expect_go.
- models/main/prenems_aimms.py builds CMMCONF, parses coalputvars.txt against input/dict.txt, and write_runval_cmm writes the SCEDES-selected input paths.
- models/main/aimms_endpoint.py transfers year/iteration data and checks COALOUT/coalcode; aimms_util.py and the older aimms_wrapper.py provide shared transfer support.
- models/main/steo_load.py, especially steovars_write_to_clsteo at line 163, generates coal/clsteo.txt from startup STEO data. Reuse the original loader initially, as the existing commercial oracle does.
- models/main/restart_load.py and input/dict.txt define restart loading and the variable dictionary. The existing local src/nems_open/snapshot.py, fortran_array.py and oracle_state.py provide the open-port equivalents.

There are 917 files under models/coal. The three .ams files above are all its model source. Supporting files include 36 files under input/, Cases/global_data.data, Cases/CMMLagData.data, coalmapping.txt, clsteo.txt, emmbench.txt, monitor.in.txt, monitor.out.txt, monitor.debug.txt, coal_out.mdb, coal_out.mdb.dsn, CoalOutput.xls, MainProject/Settings/Options.txt and LoggerConfig.xml. Cases may contain indispensable lagged state; Access and Excel outputs are reporting artifacts, not the mathematical model. The folder also contains project/user/developer state, MainProject/Coal.nch, four leave_blank.txt placeholders, eight bitmap assets, and 849 XML files. Of the XML files, 834 are GUI pages, four templates, four tools, two settings, four project metadata files and one logger configuration. Inventory these assets but do not rebuild the AIMMS GUI. All 36 input filenames and all 97 AIMMS procedures are listed below.

The main input/coal directory contains only steo_benchmark_cmm.csv. Most coal inputs are under models/coal/input, contrary to a simple input/cmm assumption. That CSV supplies aggregate STEO comparison tolerances, mostly 2%; these are not suitable port-equivalence tolerances. Also preserve input/steovars.csv, scedes/scedes.cb2026.csv and generated cl_runval.txt. The reference SCEDES and CPSBaseYr in coal.ams:19589 both select 2024; CPSEndYr is 2050. Do not use the stale CurrentStudyYear initial value of 2020 as the run start.

Execution and state

The production path is coal_API_Call -> NEMS_Monitor -> MainExecution. MainExecution reads inputs and NEMS globals, loads CMMLagData for the first base-year iteration, updates rate escalators, builds coal prices and supply steps, solves PartialLeastCostDomesticCoal, extracts primal values and shadow prices, updates lagged production/prices, constructs reports, initializes and copies global outputs, applies historical overwrites and calculates electricity supply curves. SendGlobalDataToNEMS then writes the transfer file. NEMS subsequently executes COAL_EXPECT.

Base-year iteration 1 uses CalculationOfCoalPricingEquationBaseYearItr1. Later calls use CalculationOfCoalPricingEquation. The first iteration uses base-year plant deliveries for parts of the contracts calculation; subsequent iterations use current electricity deliveries. qprods, LAG_PROD, mcnt_prev, ProdVolSolutionPriorYr and ExportMultCokeKeep/ExportMultSteamKeep carry state. ReadGlobalDataFromNEMS replaces all years initially and merges the current year on later calls. These details rule out a stateless LP driven only by final-year demand.

MainExecution has an explicit failed-solve retry with refreshed pricing and export multipliers. InfeasibleProcedure and RedoProcedure also contain solves, but their presence does not establish that the normal reference path calls them. Preserve the actual call conditions, escape penalties and status handling. A successful solver status alone is insufficient: CheckEscapeVectors treats EscapeVector > 0.01 as an escape-triggered solve.

Interface contract

The manifest names are from NEMS's perspective. models/coal/input/coalputvars.txt is NEMS -> CMM. coalgetvars.txt is CMM -> NEMS. The input manifest has 106 entries and 104 unique block/name pairs because PCLELCDR repeats. The output manifest has 157 unique pairs. The active writer, coal.ams:23582-23753, emits 159 distinct arrays and is the stronger authority for current outputs.

The active writer adds MPBLK/PMCIN, COALREP/CLIMPRANK, COALREP/CLEXPRANK, USO2GRP/CL_CRV_PROD and USO2GRP/EFD_SC_DR_PT relative to coalgetvars.txt. It does not emit that manifest's MPBLK/PELIN, MPBLK/PDSIN or USO2GRP/XCL_TRATI1. Preserve PELIN and PDSIN as input energy prices, not coal price outputs. Do not generate the Python output contract solely from coalgetvars.txt.

Restart confirmation was performed directly against the ZIP member list and NPY headers of output/aeo2026/cb2026/d011626a/restart.npz, not inferred from common-block names. The archive has 4,404 arrays. All 104 unique input-manifest names, all 157 output-manifest names and all 159 actual writer names exist, with uppercase block and lowercase variable keys. input/dict.txt also exists and gives units and dimensions. Presence confirms schema coverage, not that final restart values reconstruct internal AIMMS state or the inputs of every earlier iteration.

Reads, grouped by purpose:

- Sector demand: QBLK/QCLRS and QCLCM for residential/commercial coal; QCLIN for industrial steam coal; QMCIN for metallurgical coal; QCLRF and QCLSN for refining/synthetic fuel demand; QCLEL for aggregate electricity demand. These have shape (11,61). Use the actual census-region mappings and totals in the input tables, not a guessed 11-region geography. Quantities use the dictionary's tBTU convention.
- Electricity detail: COALEMM/QCLCLNR, RCLCLNR and XCLCLNR, the EMM_CL_UNITS/BTUS/ECPT/CLRG plant arrays, USO2GRP/UQCOAL and the scrubber arrays supply demand, plant group and control information. QCLCLNR has shape (16,61,38): 16 coal demand regions, 61 years, 38 utility subsectors. These inputs are necessary even when QCLEL is known.
- Macro and mining costs: MACOUT/MC_JPGDP, MC_RLRMCORPPUAA, MC_RMCORPPUAA, MC_WPI10, MC_JECIWSP, MC_JECIWSSP, MC_RMTCM10Y, MC_WPI14, MC_WPIIND05 and MC_WPI11. They feed deflation, capital costs, labor and producer-price escalators. MPBLK/PELIN and PDSIN supply industrial electricity/diesel prices. Transport also uses PRLTR, PRHTR, PDSTR, APONROAD/PDSTRHWY, QONROAD/QDSTRHWY and CFDSTRHWY, plus CONVFACT/CFRSQ and CFDSTR. Freeze these exogenous inputs to the reference initially; replacing macro is a separate project.
- Policy: EMISSION/EMLIM, EMETAX, EXTRARISK, EMRFSA, SO2_SHR_BY_CLRG, SO2_SHR_ALW_GRP, USW_CAMR, HG_MEFNC, EMEL_QHG and EMEL_PHG; the CSAPR block's TRANRULE*, TSO2_* arrays, SO2OTHCL and TEMRFSA; USO2GRP/BNK_TO_CMM_HG, C_ECP_SCRUB and ECP_SCRUB. COALEMM/ACI_*, PARM_A..D, FGD_FCTR, SCR_FCTR, MIN_EMF, PLNT_EMF, EMM_MEF, SO2OTHER, HGOTHER, Q_AC_SC and P_AC_SC describe control technology and emissions factors. Some legacy policy mechanisms are disabled or partly fixed; preserve the reference membership and flags instead of enabling every declared constraint.
- Other feedback and controls: PMMOUT/QCLRFPD for coal-to-liquids; COALOUT/TTONMILE, CQDBFT, CQSBB, sector balance adjustments and regional stocks; existing MPBLK coal prices and COALPRC/PCLELCDR; NCNTRL year/iteration/convergence controls; CYCLEINFO/CURIRUN and NCHAR scenario identifiers. Prices and some quantities are read and written, so the input/output sets overlap.
- Outside restart manifests: production, quality, route and contract tables; international demand/supply and ICMM export data; SCEDES settings and generated STEO inputs. Include their provenance in each test fixture.

Writes, grouped by purpose:

- Delivered prices: MPBLK/PCLRS, PCLCM, PCLIN, PCLSN, PCLEL and PMCIN, each (11,61). COALPRC/PCLELCDR is (2,16,61), scrubbed/unscrubbed electricity coal prices by demand region and year. Preserve 1987-dollar price conventions and explicit conversions; several report series use other dollar years. COALOUT/PCLRFPD, LCVBTU, LTRNTON, L_SO2P and L_HGP return refining/CTL prices, heat content, freight and policy cost components.
- Production and mine prices: COALOUT/CQSBB (energy production), CPSB and their conversion factors; COALREP/COALPROD and COALPROD2, each (11,17,61), for distribution with and without exports; COALPRICE; CLSULF/PCLSULF and CLSULF_BTU, with CLSULF shape (14,4,3,61); PMTD/PMTS and associated prices and heat units; regional rank/quality reports, waste coal, miners, wages and productivity. Reporting dimensions include historical categories and totals that are larger than current optimization sets.
- Trade and stocks: COALOUT/CQDBFB, shape (11,7,61), plus sector balance and regional stock arrays; COALREP/WSCF, WMCF and WTCF for world flows; PCLEX; CLIMPRANK and CLEXPRANK, each (5,61). Copy_Global:25365 onwards assigns CQDBFB sector 2 industrial imports, 3 coking imports, 5 exports, 6 electricity imports plus stocks and 7 total imports. Follow those assignments rather than treating all seven sectors as interchangeable trade totals. COALOUT/IIMP_BTU, EIMP_BTU and MIMP_BTU exist in restart but are not in this writer's output list.
- Electricity supply curves: USO2GRP/XCL_QECP (14,31,61), XCL_PECP, XCL_STEPS, XCL_PCAP and limits, ECP_PECP, EFD_PROD, CL_CRV_PROD, EFD_SC_DR_PT, import curves, contract/diversity limits, heat content, quality and transport escalators. XCL_1TESC and XCL_2TESC have shape (14,31,61,16); expectation index zero is the current year, followed by 30 future slots. Preserve the Fortran lower bounds in the adapter.
- Emissions and quality: COALEMM/SCLCLNR, CCLCLNR, BCLCLNR, HCLCLNR and GCLCLNR return sulfur, carbon, heat, mercury and removal information by region/year/plant type. COALREP/UTTSO2, UCSO2, UCMERC and ACMERC return emissions/removal reports. EMISSION/TOT_MERC is a mercury quantity; EMISSION/EMELPSO2 is an SO2 allowance price, not SO2 tonnage, and EMEL_PHG is a mercury penalty price. COALOUT/LIQUCARB and USO2GRP/XCL_CAR and XCL_CAR_YR return carbon content. There is no direct economy-wide CO2-total output in the CMM writer. Other NEMS components use the quantities and carbon intensities to calculate their emissions. Check assignments as well as exports: a declared/exported legacy array may retain a prior or initialized value in the reference configuration.
- Status and profiles: COALOUT/COALCODE, COALEMM/NUM_SC, coal delivery information, contract, transport and subbituminous/lignite diversity profile indices and values.

The exact input and actual output names are enumerated in the final appendix. No wildcard there implies an unverified restart variable.

LP boundary and size

PartialLeastCostDomesticCoal at coal.ams:633-639 is the active minimization LP. Its objective is ObjTotalCost. The normal solve at lines 289-291 explicitly requests dual simplex. It combines mining, domestic freight, international supply and ocean freight, imports, exports, emissions-control costs, stock adjustments and penalized escape variables. Supply prices and capacities are calculated procedurally before the solve. Nonlinear expressions in those calculations do not make the resulting optimization a nonlinear program.

The other declarations are not alternative production LPs to port blindly: not_used_LeastCostDomesticCoal at 625-632 uses AllVariables/AllConstraints and is marked unused; TransportationMultiplier at 15004-15009 has Type LS and no solve call was found for it. Use the active MyVariables/MyConstraints sets, not all declarations.

Verified structural size:

- MyVariables, lines 858-1011: 113 variable families selected from 136 declarations.
- MyConstraints, lines 710-857: 125 equation families, comprising 74 explicit Constraint identifiers and 51 equations attached to defined Variables. Four of the 78 declared Constraint identifiers are excluded. A linopy translation that only copies the Constraint declarations will miss many required equations.
- Current domestic inputs: six physical supply regions, 14 populated supply-curve tuples, 11 production steps, 16 coal demand regions, 38 electricity subsectors and eight activated-carbon steps including the no-ACI case. The 14 curves include two premium/coking curves; the electricity map excludes rank 4P.
- Current international mapping: 16 exporters, including four US districts and 12 foreign regions, 20 import regions including four US regions, two products (coking/thermal), and 10 supply steps. Only 10 foreign exporters have rows in the shipped clintlsupply.txt; set membership is broader than nonzero supply.
- One current-year horizon interval is solved at a time, with lagged state and separately constructed future electricity curves. This is not one perfect-foresight LP for 2024-2050.

Useful pre-generation size calculations, not a claimed solver matrix count:

- ProductionVolumeSteps: 14 x 11 = 154 possible current-year columns before zero bounds.
- ElectricityTransport2: 12 electricity curves x 16 regions x 38 subsectors = 7,296 domain entries before other elimination.
- ElectricityTransportAC has an unfiltered declared domain of 8 x 6 x 1 x 2 x 5 x 16 x 38 = 291,840 entries using the shipped region/sulfur/mine/rank sets. Restricting to the 12 electricity-curve tuples would give 58,368 entries, but is only valid where the original bounds and equations prove all other tuples fixed or irrelevant. Do not silently impose that restriction.
- International Transport has at most 12 x 20 x 10 x 2 = 4,800 entries before its freight-availability filter, plus US export flows, imports, aggregations and escape variables.

Thus this is a sparse model with potentially tens of thousands of useful shipment columns and hundreds of thousands of declared electricity entries, not a 154-variable supply LP. Exact generated rows, columns, nonzeros and presolved size remain unmeasured. No coal MPS/LP or solver listing was found in models/coal or the reference output directory, which contains restart.rlx and restart.npz. GUI pages, array storage dimensions and variable-family counts are not solver row counts.

First LP milestone: export EIA's generated matrix before and after presolve for 2024, 2026, 2027, 2030 and 2050, recording year, iteration, options, solver version, rows, columns, nonzeros, objective, primal solution, duals, reduced costs and escape values. MainExecution's AIMCLSolvDebug branch already contains MPS and row/column mapping options. Apply any instrumentation to a working copy. Translate domains and coefficient generation into linopy, compare a canonical sparse matrix including bounds and objective constants, then run HiGHS on that same matrix. Keep any mathematical elimination of defined variables separately auditable.

Oracle and validation plan

Fortran: extract or compile COAL_EXPECT with its real includes and a minimal RTOVALUE stub. Feed USO2GRP and NCNTRL from controlled fixtures. Dump before/after XCL_1TESC and XCL_2TESC for the first projection year, an interior year and the end-of-horizon clamp, including an alternative AEOLSTYR. Match copies exactly. Record initialization and persistence of ilast: the upstream routine tests it before assignment and has no explicit SAVE declaration. Follow the existing oracle's compiler/static-initialization conventions and document their effect. No equation changes in the oracle copy.

AIMMS procedural calculations: use the same before/after-state principle, but an AIMMS run or supplied exported fixtures is required. Dump readers, rate escalators, both coal pricing procedures, LP coefficients, solve results, Copy_Global and electricity pricing. Include automatically evaluated parameter definitions, ordering, lagged values, cases and control flags. Translate into ordinary Python/NumPy functions; use float64 internally where AIMMS does, then cast at the Fortran interface. Keep explicit year, region, plant and supply-curve maps. Once calculations match, replace each AIMMS text reader and verify the parsed arrays against its checkpoint.

The shipped Cases/CMMLagData.data and global_data.data are candidates for initialization, not presumed fresh cb2026 oracle dumps. Verify their dates/content and export them to an open named-array format. The reference NPZ contains exchange state but not the whole AIMMS model or its LP objective/duals. If no AIMMS runtime/export is available, readers, the Fortran oracle and a provisional solver can still be built; rigorous intermediate-state and objective equivalence remains blocked. Do not claim the faithful port finished based only on matching national totals.

Proposed acceptance tolerances, fixed before tuning:

- Same checkpoint, deterministic readers/mappings: exact labels, dimensions, integers, flags and strings. For arithmetic use abs(error) <= 1e-8 + 1e-6 * abs(reference) in the checkpoint's units, with tighter exact-copy checks where applicable. Report any compiler/library difference separately.
- Same generated LP: normalized maximum primal bound/row residual <= 1e-7, dual feasibility and complementarity checked at comparable scaled tolerances, and relative objective difference <= 1e-6. Use a documented objective scale near zero. Require an optimal status and no new economically material escape use. Recompute the objective independently, including constants and penalties. The source's presolve_feasibility_tolerance=0.01 is a generation setting, not permission for a 1% economic-output error.
- Against cb2026 restart, with reference demand, macro and policy inputs: every populated output region/sector/year from 2024 through 2050 must satisfy abs(error) <= absolute_floor + 0.001 * abs(reference), a 0.1% relative target. Apply this to delivered and mine prices, production, imports, exports, stock changes, quality, emissions reports and electricity supply curves. Demand inputs loaded from restart do not count as reproduced outputs. Separately test untouched historical cells and first-year overwrites.
- Absolute floors after explicit unit normalization: 1e-4 dollars/MMBtu for prices; 1e-4 million short tons for mass flows; 1e-3 trillion Btu for energy flows; 1e-6 million short tons for SO2 quantities; 1e-6 short tons for mercury quantities; 1e-6 in the documented native units for coefficients and fractions. Convert price-per-ton and emissions-per-energy outputs to their specified comparison units rather than using the wrong floor. For structural zeros, require zero or the numerical floor, without masking entire sparse regions.
- Report per-array maxima, worst cells and national totals. Do not average away regional failures. Maintain a separate oracle-versus-EIA error budget if replaying final converged inputs cannot reconstruct the original iteration sequence; the port must first match the replay oracle.

LP degeneracy can produce different optimal routes or duals. Do not demand identical internal shipment matrices or solver bases when primal feasibility and objective agree. Published regional outputs and prices still have to meet the economic target. Where a price dual is nonunique, diagnose it with a small demand perturbation, reconstruct EIA's sign/scaling and pricing postprocessing, and document the dual range and any reproducible tie rule. If that cannot recover the reference price, mark it as an unresolved acceptance failure rather than silently widening all tolerances. MainExecution:315-320 scales demand shadow prices; EMISSION_EMELPSO2_A:11026-11033 changes sign and multiplies by 1000. Both deserve explicit tests.

Implementation sequence for one worker

1. Week 1, 1 week: freeze the source/input hashes and cb2026 contract; create src/nems_open/coal/state.py and a schema from actual transfers; validate all restart keys, dimensions, units and region maps. Build the COAL_EXPECT oracle and Python equivalent. Request or produce AIMMS checkpoint/matrix exports immediately. Exit: exact Fortran copy tests and one complete named CMM input fixture.

2. Weeks 2-3, 2 weeks: implement input readers and initialize lagged state. Suggested files: inputs.py, mappings.py and steo.py. Cover composite AIMMS tables, ordered sets, default/absent values, SCEDES path selection, plant-unit strings, histories, profiles, international data and STEO startup. Exit: reader outputs and 2024 first-call state match exported AIMMS arrays; all unresolved case-file dependencies are named.

3. Weeks 4-5, 2 weeks: port SetUpRateEscalators, both coal pricing procedures and their dependent parameter definitions into supply.py and transport.py. Preserve production/capacity feedback, labor productivity, dollar conversions, 11-step limits and carried state. Exit: matching pre-solve coefficients for base-year first iteration, later iterations, STEO and post-STEO years.

4. Weeks 6-8, 3 weeks: implement lp.py using linopy and HiGHS. Start with production and domestic sector balances, then electricity contracts/diversity and transport tiers, international trade and ICMM linkage, emissions controls and all active STEO/escape equations. Translate the 51 selected defining-variable equations as well as the 74 explicit constraints. Exit: canonical matrix comparison, measured sizes and same-matrix feasibility/objective tests for the five milestone years. Keep warm-start and performance work secondary to correctness.

5. Weeks 9-10, 2 weeks: port CalcCoalReportingTotals, CoaloutProcedure, Initialize_Global, Copy_Global, Overwrites, PriceAdjustment and CalculationOfElectricityPricingEquation into outputs.py and electricity.py, including their dependent report definitions. Match regional prices, quality, emissions, trade, future supply curves and profile updates. Exit: all 159 exported arrays accounted for, with active writes distinguished from carry-through values and confirmed dual sign/unit tests.

6. Weeks 11-12, 2 weeks: implement driver.py as a persistent year/iteration state machine; run 2024-2050 with frozen NEMS demand/macro/policy. Exercise iteration-1 versus later-iteration behavior, failed solves and restart/resume. Add meaningful regressions in tests/test_coal_inputs.py, test_coal_supply.py, test_coal_lp.py, test_coal_outputs.py and test_coal_chain.py. Exit: reference case meets the stated cell-level economic tolerances, with complete residual and escape reports.

7. Weeks 13-14, 2 weeks: test additional available AEO2026 cases and controlled demand/policy perturbations, address price degeneracy, verify cold start versus resumed state, document quirks and profile runtime/memory. Wire the direct Python module into the open runner with a clear coal input/output adapter. Exit: reproducible command, pinned dependencies, fixture provenance, tests, measured LP size and limitations documented. Full NEMS convergence remains a separate integration milestone.

Estimate totals 14 worker-weeks. The 12-week lower end assumes complete AIMMS fixtures, simple readers and limited dual differences. Allow 18 weeks if lagged state reconstruction, legacy policy behavior or price degeneracy requires substantial investigation. Waiting for licensed reference access can extend elapsed time beyond that range. A domestic-only transport prototype can appear earlier but is not the CMM port described here.

Deliverable is a stateful open CMM with open-format inputs and fixtures, no AIMMS/Access dependency at runtime, reproducible linopy/HiGHS solves, complete NEMS output coverage and the same fidelity discipline used for the demand modules. GUI pages and formatted Excel/Access reports are outside the first port; their underlying exchanged/report arrays are inside it.

Appendix A. AIMMS routine inventory

All entries below give name, inclusive source range and physical line count. Include GUI, debug and explicitly unused procedures in the inventory; the execution path above determines implementation priority. The three MathematicalProgram declarations are described separately in the LP section.

models/coal/MainProject/coal.ams

  coal_API_Call: 8-44, 37 lines
  ErrorHandler: 78-100, 23 lines
  not_used_CreateAccessFileConnectionString: 118-186, 69 lines
  MainExecution: 187-446, 260 lines
  COALSetOptions: 447-462, 16 lines
  COALResetOptions: 463-485, 23 lines
  OverwritesFixForHistory: 486-495, 10 lines
  not_used_YearLoop_old: 496-536, 41 lines
  Empty_Results: 537-555, 19 lines
  YearLoop_new: 556-595, 40 lines
  NEMS_OverwritesMake: 596-623, 28 lines
  CheckEscapeVectors: 1825-1871, 47 lines
  WriteEMMDBTables: 3049-3159, 111 lines
  EmptyEMMDBTables: 3160-3248, 89 lines
  WriteMinePrices: 3249-3269, 21 lines
  WriteToExcelFileAxll: 3270-3428, 159 lines
  CheckExcelError: 3429-3445, 17 lines
  SaveGlobal: 3485-3495, 11 lines
  LoadGlobal: 3496-3505, 10 lines
  CoaloutProcedure: 6614-6737, 124 lines
  CMMLagDataSave: 11711-11721, 11 lines
  SaveAll: 11722-11732, 11 lines
  CMMLagDataLoad: 11733-11745, 13 lines
  RestartDataTestSavingcase: 11746-11750, 5 lines
  RestartDataTestloadingcase: 11751-11756, 6 lines
  CalcCoalReportingTotals: 11757-11865, 109 lines
  CycleDataSave: 11866-11876, 11 lines
  TestEmptyPlantFile: 11940-11946, 7 lines
  CalculationOfCoalPricingEquation: 18925-19228, 304 lines
  CalculationOfCoalPricingEquationBaseYearItr1: 19229-19318, 90 lines
  CalculationOfElectricityPricingEquation: 20150-20483, 334 lines
  ReadData: 23014-23327, 314 lines
  not_used_PrepDBData: 23328-23581, 254 lines
  SendGlobalDataToNEMS: 23582-23753, 172 lines
  SendGlobalDataToNEMS_HistOverwrites: 23754-23926, 173 lines
  SetUpRateEscalators: 23927-24068, 142 lines
  NEMS_Monitor: 24106-24180, 75 lines
  MainTermination: 24181-24188, 8 lines
  WriteData: 24189-24207, 19 lines
  PutGlobalData: 24208-24760, 553 lines
  GetGlobalData: 24761-24774, 14 lines
  ReadGlobalDataFromNEMS: 24775-24796, 22 lines
  WriteEscapeVectorTotal: 24797-24801, 5 lines
  MainInitialization: 24802-24808, 7 lines
  Overwrites: 24809-25118, 310 lines
  Initialize_Global: 25119-25298, 180 lines
  Copy_Global: 25299-25627, 329 lines
  InfeasibleProcedure: 25628-25734, 107 lines
  RedoProcedure: 25735-25782, 48 lines
  WriteDataLagged: 25783-25788, 6 lines
  PriceAdjustment: 25789-25821, 33 lines
  create_case: 25822-25826, 5 lines
  EmptyVariablesWhenInfeasible: 25827-25836, 10 lines
  ExportClientSupplyData: 25924-25937, 14 lines
  Calculate_report_totals: 27114-27127, 14 lines
  Calculate_production: 27128-27179, 52 lines
  Calculate_demands_and_transport: 27180-27262, 83 lines
  Calculate_prices: 27263-27359, 97 lines
  ConvertTbtu2Tons: 27360-27449, 90 lines
  ConvertYearDollars: 27450-27496, 47 lines
  SetInitialDisplayYear: 27497-27503, 7 lines
  Load_Initial_CaseFile: 27504-27513, 10 lines
  SelectRegInTable1: 27514-27526, 13 lines
  SelectRegInTable2: 27527-27537, 11 lines
  SelectCrvInTable: 27538-27550, 13 lines
  SelectRegInTableE1: 27551-27563, 13 lines
  SelectRegInTableE12: 27564-27576, 13 lines
  SelectCrvInTableE3: 27577-27588, 12 lines
  SelectSet: 27589-27600, 12 lines
  SelectAll: 27601-27609, 9 lines
  SetDefaultCoalTypes: 27610-27622, 13 lines
  Add_USTotal: 27623-27632, 10 lines
  SelectSupCrv: 27633-27641, 9 lines
  ClearSelections: 27642-27647, 6 lines
  ClearSelections1: 27648-27654, 7 lines
  ClearSelections2: 27655-27660, 6 lines
  ReloadLagData: 27661-27666, 6 lines
  GetCaseName: 28024-28032, 9 lines
  GetSelectedCaseNames: 28033-28042, 10 lines
  CompareRuns: 28043-28070, 28 lines
  HighlightDiffE2: 28071-28076, 6 lines
  HighlightDiffE3: 28077-28082, 6 lines
  HighlightDiffE4: 28083-28088, 6 lines
  HighlightDiffE5: 28089-28094, 6 lines
  HighlightDiffE6: 28095-28100, 6 lines
  HighlightDiffE7: 28101-28106, 6 lines
  HighlightDiffE8: 28107-28112, 6 lines
  HighlightDiffE9: 28113-28118, 6 lines
  HighlightDiffE10: 28119-28124, 6 lines
  HighlightDifferences: 28125-28152, 28 lines
  LocalizationReadLanguage: 28208-28223, 16 lines
  LocalizationWriteLanguage: 28224-28253, 30 lines
  LocalizationReadAll: 28254-28271, 18 lines
  LocalizationWriteAll: 28272-28291, 20 lines
  LocalizationInitialize: 28292-28308, 17 lines
  Total: 95 routines.

models/coal/MainProject/case.ams

  ReportDataSave: 15-25, 11 lines
  CreateCasesForComparison: 26-43, 18 lines
  Total: 2 routines.

models/coal/MainProject/nchar.ams

  Total: 0 routines.

Appendix B. Complete models/coal/input inventory

Physical line counts, including comments and table headers. cmmfiles.txt is a historical directory listing, not a trustworthy manifest of files currently present. All 36 actual files are listed here.

  cdsImpSurcharge.txt: 2306 lines
  cdsRegionRef.txt: 955 lines
  claggexportmap.txt: 20 lines
  cldistance.txt: 193 lines
  clexportlimits.txt: 14 lines
  clfeasiblerout.txt: 223 lines
  clflags.txt: 130 lines
  clfreight.txt: 565 lines
  climportlimits.txt: 435 lines
  clintldemand.txt: 1635 lines
  clintlquality.txt: 27 lines
  clintlsupply.txt: 7203 lines
  clintlusexport.txt: 2216 lines
  cloceandist.txt: 643 lines
  clrateselec.txt: 228 lines
  clratesnonelec.txt: 3151 lines
  cltonrailmile.txt: 9829 lines
  cltonspercar.txt: 10 lines
  clusexporticmm.txt: 1140 lines
  cmmCoalPlntData.txt: 1128 lines
  cmmfiles.txt: 44 lines
  cmmhcldist.txt: 69 lines
  cmmhclworld.txt: 2378 lines
  cmmheastwest.txt: 121 lines
  cmmhmiscellaneous.txt: 30 lines
  cmmhsectoral.txt: 138 lines
  cmmProfiles.txt: 4175 lines
  cmmRCAFwts.txt: 10 lines
  cmmUScoalImports.txt: 64 lines
  coalgetvars.txt: 157 lines
  coalputvars.txt: 106 lines
  coalunits.txt: 1072 lines
  cpsProdParam.txt: 1145 lines
  cpsRegionRef.txt: 1028 lines
  cpsSCrvYearIndx.txt: 689 lines
  ICMMcommodityMap.txt: 24 lines

Appendix C. Exact restart-verified interface names

Each line is an existing restart.npz key followed by its stored NumPy shape. () means scalar. Names are case-sensitive here. These are whole-array shapes; the runtime transfer often selects only the current-year slice. Character arrays require string decoding and numeric arrays require the original index bounds. All listed names were found; no missing names were suppressed.

Inputs (104 unique arrays)

  APONROAD/pdstrhwy (11, 61)
  COALEMM/aci_cst (8, 3, 38)
  COALEMM/aci_opt (8, 3, 38, 61)
  COALEMM/aci_steps (80, 3)
  COALEMM/emm_cl_btus (1800, 61)
  COALEMM/emm_cl_clrg (1800,)
  COALEMM/emm_cl_ecpt (1800, 61)
  COALEMM/emm_cl_units (1800, 10)
  COALEMM/emm_mef (8, 3, 38)
  COALEMM/fgd_fctr (38, 3)
  COALEMM/hgother (61,)
  COALEMM/min_emf (80, 3)
  COALEMM/p_ac_sc (5,)
  COALEMM/parm_a (38, 3)
  COALEMM/parm_b (38, 3)
  COALEMM/parm_c (38, 3)
  COALEMM/parm_d (38, 3)
  COALEMM/plnt_emf (80, 3)
  COALEMM/q_ac_sc (5,)
  COALEMM/qclclnr (16, 61, 38)
  COALEMM/rclclnr (16, 61, 38)
  COALEMM/scr_fctr (38, 3)
  COALEMM/so2other (61, 2)
  COALEMM/xclclnr (16, 61, 38)
  COALOUT/appstocks (61,)
  COALOUT/cqdbft (11, 7, 61)
  COALOUT/cqsbb (3, 61)
  COALOUT/eleccoalbal (61,)
  COALOUT/indcokebal (61,)
  COALOUT/indsteambal (61,)
  COALOUT/intstocks (61,)
  COALOUT/ttonmile (61,)
  COALOUT/weststocks (61,)
  COALPRC/pclelcdr (2, 16, 61)
  CONVFACT/cfdstr (61,)
  CONVFACT/cfrsq ()
  CSAPR/so2othcl (61, 16)
  CSAPR/temrfsa (61, 3)
  CSAPR/tranrule1 ()
  CSAPR/tranrule2 ()
  CSAPR/tso2_lim_by_clrg (16,)
  CSAPR/tso2_lm1_by_clrg (16,)
  CSAPR/tso2_shr_by_clrg (16, 3)
  CSAPR/tso2_vr_by_clrg ()
  CSAPR/tso2_vr1_by_clrg (16,)
  CSAPR/tso2_vr3_by_clrg (16,)
  CSAPR/tso2_yr_by_clrg ()
  CYCLEINFO/curirun ()
  EMISSION/emel_phg (16, 61)
  EMISSION/emel_qhg (16, 61)
  EMISSION/emetax (15, 61)
  EMISSION/emlim (4, 61)
  EMISSION/emrfsa (61, 2)
  EMISSION/extrarisk (61,)
  EMISSION/hg_mefnc (16, 61)
  EMISSION/so2_shr_alw_grp (61, 2)
  EMISSION/so2_shr_by_clrg (16, 2)
  EMISSION/usw_camr ()
  MACOUT/mc_jeciwsp (61,)
  MACOUT/mc_jeciwssp (61,)
  MACOUT/mc_jpgdp (64,)
  MACOUT/mc_rlrmcorppuaa (61,)
  MACOUT/mc_rmcorppuaa (61,)
  MACOUT/mc_rmtcm10y (61,)
  MACOUT/mc_wpi10 (61,)
  MACOUT/mc_wpi11 (61,)
  MACOUT/mc_wpi14 (61,)
  MACOUT/mc_wpiind05 (61,)
  MPBLK/pclcm (11, 61)
  MPBLK/pclel (11, 61)
  MPBLK/pclin (11, 61)
  MPBLK/pclrs (11, 61)
  MPBLK/pclsn (11, 61)
  MPBLK/pdsin (11, 61)
  MPBLK/pdstr (11, 61)
  MPBLK/pelin (11, 61)
  MPBLK/prhtr (11, 61)
  MPBLK/prltr (11, 61)
  NCHAR/date ()
  NCHAR/scen ()
  NCHAR/scen_date ()
  NCNTRL/cnvtst (14, 61)
  NCNTRL/curcalyr ()
  NCNTRL/curitr ()
  NCNTRL/curiyr ()
  NCNTRL/fcrl ()
  NCNTRL/ijumpcalyr ()
  NCNTRL/ijumpyr ()
  NCNTRL/lastyr ()
  NCNTRL/prtdbgc ()
  PMMOUT/qclrfpd (10, 61)
  QBLK/qclcm (11, 61)
  QBLK/qclel (11, 61)
  QBLK/qclin (11, 61)
  QBLK/qclrf (11, 61)
  QBLK/qclrs (11, 61)
  QBLK/qclsn (11, 61)
  QBLK/qmcin (11, 61)
  QONROAD/cfdstrhwy (61,)
  QONROAD/qdstrhwy (11, 61)
  USO2GRP/bnk_to_cmm_hg (61,)
  USO2GRP/c_ecp_scrub (38,)
  USO2GRP/ecp_scrub (38, 61)
  USO2GRP/uqcoal (38, 16, 61)

Outputs (159 unique arrays)

  COALEMM/bclclnr (16, 61, 38)
  COALEMM/cclclnr (16, 61, 38)
  COALEMM/cmm_cl_btus (26, 1800)
  COALEMM/cmm_cont_indx (26, 1800)
  COALEMM/cmm_cont_prf (500, 61)
  COALEMM/cmm_ldv_indx (1800,)
  COALEMM/cmm_ldv_prf (500, 61)
  COALEMM/cmm_sdv_indx (1800,)
  COALEMM/cmm_sdv_prf (500, 61)
  COALEMM/cmm_trans_indx (26, 1800)
  COALEMM/cmm_trans_prf (500, 61)
  COALEMM/gclclnr (16, 61, 38)
  COALEMM/hclclnr (16, 61, 38)
  COALEMM/new_ldv_indx (16,)
  COALEMM/new_sdv_indx (16,)
  COALEMM/num_sc ()
  COALEMM/pcaclnr (16, 61, 38)
  COALEMM/phgclnr (16, 61, 38)
  COALEMM/pslclnr (16, 61, 38)
  COALEMM/sclclnr (16, 61, 38)
  COALOUT/appstocks (61,)
  COALOUT/clsyngqn (17, 61)
  COALOUT/coalcode ()
  COALOUT/cpdbft (11, 7, 61)
  COALOUT/cpsb (3, 61)
  COALOUT/cpsbt (3, 61)
  COALOUT/cqdbfb (11, 7, 61)
  COALOUT/cqdbft (11, 7, 61)
  COALOUT/cqsbb (3, 61)
  COALOUT/cqsbt (3, 61)
  COALOUT/eleccoalbal (61,)
  COALOUT/indcokebal (61,)
  COALOUT/indsteambal (61,)
  COALOUT/intstocks (61,)
  COALOUT/l_hgp (10, 61)
  COALOUT/l_so2p (10, 61)
  COALOUT/lcvbtu (10, 61)
  COALOUT/liqucarb (11, 61)
  COALOUT/ltrnton (10, 61)
  COALOUT/pclrfpd (10, 61)
  COALOUT/totminers (61,)
  COALOUT/ttonmile (61,)
  COALOUT/weststocks (61,)
  COALPRC/pclelcdr (2, 16, 61)
  COALREP/absulf (4, 61)
  COALREP/absulf_btu (4, 61)
  COALREP/acmerc (61,)
  COALREP/alsulf (4, 61)
  COALREP/alsulf_btu (4, 61)
  COALREP/apsulf (4, 61)
  COALREP/apsulf_btu (4, 61)
  COALREP/clexprank (5, 61)
  COALREP/climprank (5, 61)
  COALREP/clsulf (14, 4, 3, 61)
  COALREP/clsulf_btu (14, 4, 3, 61)
  COALREP/coal2gas (11, 61)
  COALREP/coalprice (17, 61)
  COALREP/coalprod (11, 17, 61)
  COALREP/coalprod2 (11, 17, 61)
  COALREP/ibsulf (4, 61)
  COALREP/ibsulf_btu (4, 61)
  COALREP/ilsulf (4, 61)
  COALREP/ilsulf_btu (4, 61)
  COALREP/labprodgrowth (61,)
  COALREP/pabsulf (4, 61)
  COALREP/palsulf (4, 61)
  COALREP/papsulf (4, 61)
  COALREP/pclex (11, 61)
  COALREP/pclsulf (14, 4, 3, 61)
  COALREP/pibsulf (4, 61)
  COALREP/pilsulf (4, 61)
  COALREP/pmtd (14, 61)
  COALREP/pmtd_btu (14, 61)
  COALREP/pmtdp (14, 61)
  COALREP/pmts (14, 61)
  COALREP/pmts_btu (14, 61)
  COALREP/pmtsp (14, 61)
  COALREP/pwbsulf (4, 61)
  COALREP/pwlsulf (4, 61)
  COALREP/pwpsulf (4, 61)
  COALREP/pwssulf (4, 61)
  COALREP/tmpmbtu (61,)
  COALREP/totlabprod (61,)
  COALREP/tspmbtu (61,)
  COALREP/ucmerc (38, 61)
  COALREP/ucso2 (38, 61)
  COALREP/utcons (38, 61)
  COALREP/uttso2 (38, 61)
  COALREP/wagegrowth (61,)
  COALREP/wagephour (61,)
  COALREP/wbsulf (4, 61)
  COALREP/wbsulf_btu (4, 61)
  COALREP/wc_dist_st (11, 17, 61)
  COALREP/wc_prod_btu (11, 17, 61)
  COALREP/wc_prod_st (11, 17, 61)
  COALREP/wlsulf (4, 61)
  COALREP/wlsulf_btu (4, 61)
  COALREP/wmcf (4, 11, 61)
  COALREP/wpsulf (4, 61)
  COALREP/wpsulf_btu (4, 61)
  COALREP/wscf (4, 11, 61)
  COALREP/wssulf (4, 61)
  COALREP/wssulf_btu (4, 61)
  COALREP/wtcf (4, 11, 61)
  EMISSION/emel_phg (16, 61)
  EMISSION/emelpso2 (61, 2)
  EMISSION/tot_merc (61,)
  MPBLK/pclcm (11, 61)
  MPBLK/pclel (11, 61)
  MPBLK/pclin (11, 61)
  MPBLK/pclrs (11, 61)
  MPBLK/pclsn (11, 61)
  MPBLK/pmcin (11, 61)
  USO2GRP/cl_crv_prod (14, 61)
  USO2GRP/ctl_cldr (16,)
  USO2GRP/ctl_other (14, 61)
  USO2GRP/ctl_trate (14, 16)
  USO2GRP/ctlbtu (14, 16, 61)
  USO2GRP/ecp_pecp (14, 11, 61)
  USO2GRP/efd_cont (26, 16, 2, 61)
  USO2GRP/efd_dvlg (16, 38)
  USO2GRP/efd_dvsb (16, 38)
  USO2GRP/efd_lg_dvlim (16, 38, 61)
  USO2GRP/efd_prod (14,)
  USO2GRP/efd_rank (26,)
  USO2GRP/efd_sb_dvlim (16, 38, 61)
  USO2GRP/efd_sc_dr_pt (26, 16, 38)
  USO2GRP/efd_tier1 (14, 16, 38)
  USO2GRP/efd_tier1_lim (14, 16, 2, 61)
  USO2GRP/xcl_1tesc (14, 31, 61, 16)
  USO2GRP/xcl_2tesc (14, 31, 61, 16)
  USO2GRP/xcl_btu (26,)
  USO2GRP/xcl_car (26,)
  USO2GRP/xcl_car_yr (26, 61)
  USO2GRP/xcl_hg (26,)
  USO2GRP/xcl_hg_yr (26, 61)
  USO2GRP/xcl_import (16, 61)
  USO2GRP/xcl_max_incr (14, 61)
  USO2GRP/xcl_mx_pcap (14,)
  USO2GRP/xcl_other (26, 61)
  USO2GRP/xcl_pcap (14, 61)
  USO2GRP/xcl_pcap_limit (14, 61)
  USO2GRP/xcl_pecp (14, 11, 31, 61)
  USO2GRP/xcl_pimp (12, 10, 61)
  USO2GRP/xcl_plim (14, 61)
  USO2GRP/xcl_qecp (14, 31, 61)
  USO2GRP/xcl_qimp (12, 10, 61)
  USO2GRP/xcl_so2 (26,)
  USO2GRP/xcl_so2_yr (26, 61)
  USO2GRP/xcl_steps (11,)
  USO2GRP/xcl_stock (61,)
  USO2GRP/xcl_tesci (4, 61, 16)
  USO2GRP/xcl_tr_in (4, 12, 16, 61)
  USO2GRP/xcl_tr_t1 (14, 16, 61)
  USO2GRP/xcl_tr_t2 (14, 16, 61)
  USO2GRP/xcl_trat1 (14, 16)
  USO2GRP/xcl_trate (14, 16)
  USO2GRP/xcl_trati2 (12, 16)
  USO2GRP/xcl_type (26,)

