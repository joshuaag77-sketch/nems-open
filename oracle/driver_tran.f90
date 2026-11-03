! Oracle driver for the transportation module: run EIA's original tran.f,
! tranfrt.f and tranair.f on a saved NEMS run. Loads the restart file, then calls
! TRAN for every year NEMS does (TRAN returns before 1995), and dumps the module's
! shared outputs to out/state/final/0 for the Python tests (oracle_final, written
! by hooks_tran.py).

program oracle_tran
  implicit none
  include 'parametr'
  include 'ncntrl'
  integer nbad, y, iters

  call load_restart(nbad)
  write(*,'(a,i0)') ' restart variables with size mismatch: ', nbad
  call oracle_zero

  ! NEMS calls TRAN 3 times a year: TAIRT adds to LFDOMAVG on every call, and
  ! EIA's TRTRAVLD(3,:) is exactly 3 calls' worth in every year.
  iters = 3
  do y = 1, LASTYR
    CURIYR = y
    CURCALYR = y + BASEYR - 1
    do CURITR = 1, iters
      FCRL = merge(1, 0, CURITR == iters)
      NCRL = FCRL
      call TRAN
    enddo
    if (CURCALYR >= 1995) write(*,'(a,i0)') ' done ', CURCALYR
  enddo

  call oracle_final
end program oracle_tran
