! gfortran stand-ins for the Intel Fortran library routines EIA's AIMMS interface (uaimms.f) uses.
! Only for the AIMMS-coupled EMM oracle (NEMS_ORACLE_AIMMS=1, oracle/build.sh).
!   COMMITQQ(unit): flush a unit to disk before another program reads the file.
!   TIMEF(): seconds since the first call (feeds timing messages only).
!   SLEEPQQ(ms): pause.
!   GETCWD(dir): current folder (gfortran's own GETCWD extension), returns 0 on success.

module ifcore
  implicit none
contains
  logical function commitqq(unit)
    integer, intent(in) :: unit
    flush(unit)
    commitqq = .true.
  end function commitqq
end module ifcore

module ifport
  implicit none
contains
  real(4) function timef()
    integer(8), save :: t0 = -1
    integer(8) :: t, rate
    call system_clock(t, rate)
    if (t0 < 0) t0 = t
    timef = real(t - t0, 4) / real(rate, 4)
  end function timef

  subroutine sleepqq(ms)
    integer, intent(in) :: ms
    call execute_command_line('sleep ' // trim(adjustl(itoa(ms / 1000 + 1))))
  end subroutine sleepqq

  integer(4) function getcwd(dir)
    character(*), intent(out) :: dir
    integer :: st
    call get_environment_variable('PWD', dir, status=st)
    getcwd = st
  end function getcwd

  function itoa(i) result(s)
    integer, intent(in) :: i
    character(12) :: s
    write(s, '(i0)') i
  end function itoa
end module ifport
