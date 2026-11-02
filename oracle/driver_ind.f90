! Oracle driver: run EIA's original industrial module on a saved NEMS run.
! Loads the restart file (minus INDREP and INDOUT, see gen_oracle.py), clears the
! industrial quantities in QBLK from the base year on, then calls IND for every
! year as NEMS does: iterations with NCRL=0 (the last one with FCRL=1), then the
! reporting call with NCRL=1. The shared state is dumped at the end as tag 'final'.

program oracle_ind
  implicit none
  include 'parametr'
  include 'ncntrl'
  include 'qblk'
  integer nbad, y, iters

  call load_restart(nbad)
  write(*,'(a,i0)') ' restart variables with size mismatch: ', nbad

  ! Industrial fuel use, written by IND (WEXOG). Zeroed so any match is earned.
  ! IBYR2 = 2021 in ind.f; it is local to that file.

  iters = 2
  do y = 1, LASTYR
    CURIYR = y
    CURCALYR = y + BASEYR - 1
    do CURITR = 1, iters
      FCRL = merge(1, 0, CURITR == iters)
      NCRL = 0
      call IND
    enddo
    FCRL = 1
    NCRL = 1
    call IND
    write(*,'(a,i0)') ' done ', CURCALYR
  enddo

  call dump('qasin', QASIN, sizeof(QASIN))
  call dump('qbmin', QBMIN, sizeof(QBMIN))
  call dump('qbuin', QBUIN, sizeof(QBUIN))
  call dump('qciin', QCIIN, sizeof(QCIIN))
  call dump('qclin', QCLIN, sizeof(QCLIN))
  call dump('qdsin', QDSIN, sizeof(QDSIN))
  call dump('qelin', QELIN, sizeof(QELIN))
  call dump('qetin', QETIN, sizeof(QETIN))
  call dump('qgein', QGEIN, sizeof(QGEIN))
  call dump('qgfin', QGFIN, sizeof(QGFIN))
  call dump('qgiin', QGIIN, sizeof(QGIIN))
  call dump('qh2in', QH2IN, sizeof(QH2IN))
  call dump('qhoin', QHOIN, sizeof(QHOIN))
  call dump('qisin', QISIN, sizeof(QISIN))
  call dump('qksin', QKSIN, sizeof(QKSIN))
  call dump('qlgin', QLGIN, sizeof(QLGIN))
  call dump('qlpin', QLPIN, sizeof(QLPIN))
  call dump('qluin', QLUIN, sizeof(QLUIN))
  call dump('qmcin', QMCIN, sizeof(QMCIN))
  call dump('qmgin', QMGIN, sizeof(QMGIN))
  call dump('qmsin', QMSIN, sizeof(QMSIN))
  call dump('qngin', QNGIN, sizeof(QNGIN))
  call dump('qngpin', QNGPIN, sizeof(QNGPIN))
  call dump('qotin', QOTIN, sizeof(QOTIN))
  call dump('qpcin', QPCIN, sizeof(QPCIN))
  call dump('qpfin', QPFIN, sizeof(QPFIN))
  call dump('qppin', QPPIN, sizeof(QPPIN))
  call dump('qprin', QPRIN, sizeof(QPRIN))
  call dump('qpvin', QPVIN, sizeof(QPVIN))
  call dump('qrlin', QRLIN, sizeof(QRLIN))
  call dump('qrsin', QRSIN, sizeof(QRSIN))
  call dump('qsgin', QSGIN, sizeof(QSGIN))
  call dump('qstin', QSTIN, sizeof(QSTIN))
  call dump('qsulfurin', QSULFURIN, sizeof(QSULFURIN))
  call dump('qtpin', QTPIN, sizeof(QTPIN))
  call dump('qtrin', QTRIN, sizeof(QTRIN))
  call dump('qtsin', QTSIN, sizeof(QTSIN))
  call dump('qwiin', QWIIN, sizeof(QWIIN))

  call oracle_state('final')
end program oracle_ind
