! Oracle driver: run EIA's original residential module on a saved NEMS run.
! Loads the restart file (minus the residential blocks, see gen_oracle.py), clears
! the residential quantities in QBLK, then calls RESD for every year from the RECS
! base year to 2050. The full shared state is dumped at the end as tag 'final'.

program oracle_resd
  implicit none
  include 'parametr'
  include 'ncntrl'
  include 'qblk'
  include 'resdrep'
  integer nbad, y, iters

  call load_restart(nbad)
  write(*,'(a,i0)') ' restart variables with size mismatch: ', nbad

  ! Residential fuel use, written by NEMSCN. Zeroed so any match is earned.
  QELRS = 0.0; QNGRS = 0.0; QDSRS = 0.0; QKSRS = 0.0; QLGRS = 0.0; QPRRS = 0.0
  QCLRS = 0.0; QBMRS = 0.0; QGERS = 0.0; QSTRS = 0.0; QPVRS = 0.0; QTRRS = 0.0
  QTPRS = 0.0; QTSRS = 0.0; QGFRS = 0.0; QGIRS = 0.0

  iters = 2
  do y = RECSYear - BASEYR + 1, LASTYR
    CURIYR = y
    CURCALYR = y + BASEYR - 1
    do CURITR = 1, iters
      FCRL = merge(1, 0, CURITR == iters)
      NCRL = FCRL
      call RESD
    enddo
    write(*,'(a,i0)') ' done ', CURCALYR
  enddo

  call oracle_state('final')
end program oracle_resd
