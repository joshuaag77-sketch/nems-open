!     Distributed solar (DPV) totals by EMM region, for the EMM oracle.
!     In NEMS, renew.f (RFM, not part of the oracle) fills COMMON /DPV/ from
!     the residential and commercial generator arrays when DPVDISPATCH is on
!     (util.f sets it). ECP's AIMMS model divides by DPVTOTCAPNR, so with the
!     block left at zero it stops on 0/0. Same sums as renew.f lines 425-435;
!     MPCGCtoN comes from EMM's own setup (udat.f), so this runs once that is
!     done.
      SUBROUTINE ORACLE_DPV
      IMPLICIT NONE
      include 'parametr'
      include 'ncntrl'
      include 'emmparm'
      include 'control'
      include 'cogen'
      include 'dispinyr'
      INTEGER IYR, IRG, ICNS
      IF (.NOT. DPVDISPATCH) RETURN
      IF (SUM(MPCGCtoN(:,:,10)) .LE. 0.0) RETURN
      DPVTOTCAPNR = 0.0
      DPVTOTGENNR = 0.0
      DO IYR = 1, MNUMYR
        DO IRG = 1, MNUMNR
          DO ICNS = 1, MNUMCR - 2
            DPVTOTCAPNR(IRG,IYR) = DPVTOTCAPNR(IRG,IYR) + MPCGCtoN(IRG,ICNS,10) * CGCOMMCAP(ICNS,IYR,8) &
              + MPCGCtoN(IRG,ICNS,10) * CGRESCAP(ICNS,IYR,8)
            DPVTOTGENNR(IRG,IYR) = DPVTOTGENNR(IRG,IYR) + MPCGCtoN(IRG,ICNS,10) * (CGCOMMGEN(ICNS,IYR,8,1) + CGCOMMGEN(ICNS,IYR,8,2)) &
              + MPCGCtoN(IRG,ICNS,10) * (CGRESGEN(ICNS,IYR,8,1) + CGRESGEN(ICNS,IYR,8,2))
          ENDDO
        ENDDO
      ENDDO
      END
