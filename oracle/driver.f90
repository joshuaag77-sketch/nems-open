! Oracle driver: run EIA's original commercial module on a saved NEMS run.
! Loads the restart file, clears what the commercial module writes, then calls
! COMM for every projection year and dumps results to out/ for the Python tests.

program oracle
  implicit none
  ! Same include order as COMFloorspace, which compiles cleanly.
  include 'parametr'
  include 'ncntrl'
  include 'macout'
  include 'comparm'
  include 'comvars'
  include 'commrep'
  integer nbad, y, iters

  call load_restart(nbad)
  write(*,'(a,i0)') ' restart variables with size mismatch: ', nbad

  ! Zero the module's outputs so any match against EIA is earned, not loaded.
  CMTotalFlspc = 0.0
  SurvFloorTotal = 0.0
  CMNewFloorSpace = 0.0
  AgedNew = 0.0

  ! 4 iterations gives identical results to 2 (checked 2026-11-01).
  iters = 2
  FIRSYR = CBECSyear - BASEYR + 2
  do y = FIRSYR, LASTYR
    CURIYR = y
    CURCALYR = y + BASEYR - 1
    do CURITR = 1, iters
      FCRL = merge(1, 0, CURITR == iters)
      NCRL = FCRL
      call COMM
    enddo
    write(*,'(a,i0)') ' done ', CURCALYR
  enddo

  call dump('cmtotalflspc', CMTotalFlspc, sizeof(CMTotalFlspc))
  call dump('survfloortotal', SurvFloorTotal, sizeof(SurvFloorTotal))
  call dump('servdmdexbldg', ServDmdExBldg, sizeof(ServDmdExBldg))
  call dump('newservdmd', NewServDmd, sizeof(NewServDmd))
  call dump('cmusconsumption', CMUSConsumption, sizeof(CMUSConsumption))

end program oracle
