! EFD stand-in for the EMM oracle. hooks.py puts CALL EFD_STANDIN(CURIYR) where
! UTIL calls ELEFD (the EFD dispatch LP, solved in AIMMS, which we do not have).
!
! For each EMM region it reads the region's EFD output block (DISPOUT) from the
! in-run direct-access file, fills what EFP and LDSM read from EIA's own regional
! totals in the restart file (UEFDOUT, UETTOUT), and writes it back. Where the
! restart has no matching total, a plausible nonzero value is used so EFP's
! branches and division guards still run. Every such value is listed in SCOPE.md
! under "EFP oracle input stand-ins", with the constant used. Prices out of EFP
! will not match EIA until our own dispatch LP supplies this block.
!
! Units follow DISPOUT: costs in million 1987 dollars, trade in MWh.
      SUBROUTINE EFD_STANDIN(IYR)
      IMPLICIT NONE
      include 'parametr'
      include 'emmparm'
      include 'control'
      include 'ncntrl'
      include 'dispout'
      include 'uefdout'
      include 'uettout'
      include 'emission'
      INTEGER IYR, IRG, IO, IS, IV, ICAP
      REAL FUEL(2), GEN(2), OWNSHR(EFD_D_OWN)
      INTEGER OWNSRC(EFD_D_OWN)
      ! Splits of EIA's two ownership groups (1 utility, 2 nonutility) over EFD's
      ! five owners (1 private, 2 public, 3 EWG, 4 non-traditional cogen,
      ! 5 traditional cogen). Stand-in shares, see SCOPE.md.
      DATA OWNSHR /0.8, 0.2, 0.9, 0.05, 0.05/
      DATA OWNSRC /1, 1, 2, 2, 2/
      ! Stand-in unit costs, 1987 dollars: variable O&M and fixed O&M per MWh of
      ! generation, nuclear fuel per MMBtu, wholesale trade price per MWh,
      ! emission allowance cost as a share of fuel cost.
      REAL, PARAMETER :: VOM = 2.0, FOM = 8.0, PNUC = 0.4, PTRADE = 30.0, PALLW = 0.01

      DO IRG = 1, UNRGNS
         CALL GETOUT(IYR, IRG)
         DO IO = 1, 2
            FUEL(IO) = UFLCLNR(IO,IRG,IYR) * UPRCLNR(IRG,IYR) &
                     + (UFLGFNR(IO,IRG,IYR) + UFLGINR(IO,IRG,IYR) + UFLGCNR(IO,IRG,IYR)) * UPRNGNR(IRG,IYR) &
                     + UFLDSNR(IO,IRG,IYR) * UPRDSNR(IRG,IYR) &
                     + (UFLRLNR(IO,IRG,IYR) + UFLRHNR(IO,IRG,IYR)) * UPRRSNR(IRG,IYR) &
                     + UFLWDNR(IO,IRG,IYR) * UPRWDNR(IRG,IYR) &
                     + UFLURNR(IO,IRG,IYR) * PNUC
            GEN(IO) = UGNTLNR(IO,IRG,IYR)   ! billion kWh
         END DO
         ERTOMF = 0.0
         ERTOMX = 0.0
         DO IO = 1, EFD_D_OWN
            ! trillion Btu x $/MMBtu = million $; billion kWh x $/MWh = million $
            ERTFL(IO) = OWNSHR(IO) * FUEL(OWNSRC(IO))
            ERTOM(IO) = OWNSHR(IO) * GEN(OWNSRC(IO)) * VOM
            ERTOMF(1,IO) = OWNSHR(IO) * GEN(OWNSRC(IO)) * FOM
            ERTSO2(IO) = PALLW * ERTFL(IO)
            ERTNOX(IO) = PALLW * ERTFL(IO)
            ERTHG(IO) = 0.1 * PALLW * ERTFL(IO)
            ERTGSUB(IO) = OWNSHR(IO) * GEN(OWNSRC(IO)) / MAX(GEN(1) + GEN(2), 1.0E-6) * UPTCCST(IRG,IYR)
         END DO
         ! Nuclear fuel cost by fuel type (EFP reads ERFFL(UIUF))
         ERFFL = 0.0
         ERFFL(UIUF) = (UFLURNR(1,IRG,IYR) + UFLURNR(2,IRG,IYR)) * PNUC
         ! Nonutility payments: fixed part as a share of EWG fuel cost; cogen sales
         ! to the grid are not in the restart.
         EWGFIX = 0.2 * ERTFL(3)
         EWGREV = ERTFL(3) + ERTOM(3)
         EWGRCC = 0.01 * EWGREV
         EWGRIC = 0.05 * EWGREV
         EWGRNW = 0.0
         ! Trade, from UETTOUT (GWh and million $)
         ETDMMF = UTDMMF(IRG,IYR) * 1000.0
         ETDMME = UTDMME(IRG,IYR) * 1000.0
         ETDMDF = UTDMDF(IRG,IYR)
         ETDMDE = UTDMDE(IRG,IYR)
         ETIMPF = UTIMPF(IRG,IYR) * 1000.0
         ETIMPE = UTIMPE(IRG,IYR) * 1000.0
         ETEXPF = UTEXPF(IRG,IYR) * 1000.0
         ETEXPE = UTEXPE(IRG,IYR) * 1000.0
         ETIMPD = (ETIMPF + ETIMPE) / 1.0E6 * PTRADE
         ETEXPD = (ETEXPF + ETEXPE) / 1.0E6 * PTRADE
         ! Policy costs: RPS credit payments; carbon allowance cost from EMM's CO2
         ! emissions and the carbon tax.
         ERRPS = URPSCSTR(IRG,IYR)
         ERDSCAR = UTCAR(IRG,IYR) * EMETAX(1,IYR)
         ! Marginal energy cost by season and slice: average fuel cost per MWh.
         DO IS = 1, EFD_D_MSP
            DO IV = 1, EFD_D_MVS
               MARCST(IS,IV) = (FUEL(1) + FUEL(2)) / MAX(GEN(1) + GEN(2), 1.0E-6)
               MARCST2(IS,IV) = MARCST(IS,IV)
            END DO
         END DO
         ETGEN = GEN(1) + GEN(2)
         CALL STROUT(IYR, IRG)
         ! Dump this region's EFD output and build blocks (they live in files,
         ! not COMMON). GETBLD only reads; ELEFD also leaves the last region loaded.
         CALL GETBLD(1, IRG)
         CALL ORACLE_REGION(IRG)
      END DO
      END SUBROUTINE EFD_STANDIN
