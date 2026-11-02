! Oracle driver: run EIA's electricity module (EMM) Fortran on a saved NEMS run.
! Loads the restart file (minus EFP's outputs, see gen_oracle.py), then calls
! UTIL, EMM's yearly entry, for every year and iteration the way NEMS does. UTIL
! returns at once before EMM's start year (2020) and runs its own setup on the
! first call. The ECP and EFD solves are swapped out by hooks.py (ECP: skipped;
! EFD: efd_standin.f90). LDSM and EFP run as EIA wrote them. The full shared
! state is dumped at the end as tag 'final'.

program oracle_emm
  use ephrts_swtiches
  implicit none
  include 'parametr'
  include 'ncntrl'
  integer nbad, y, iters

  call load_restart(nbad)
  write(*,'(a,i0)') ' restart variables with size mismatch: ', nbad

  EPHRTS = 0                  ! scedes EPHRTS: hydrogen submodule off in cb2026
  TURN_ON_DEBUGGING = .FALSE.

  iters = 2
  do y = FIRSYR, LASTYR
    CURIYR = y
    CURCALYR = y + BASEYR - 1
    do CURITR = 1, iters
      FCRL = merge(1, 0, CURITR == iters)
      NCRL = FCRL
      call UTIL
    enddo
    if (CURCALYR >= 2020) write(*,'(a,i0)') ' done ', CURCALYR
  enddo

  call oracle_state('final')
end program oracle_emm
