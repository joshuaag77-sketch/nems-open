! Run-time pieces of Intel's variable format expressions, for the AIMMS-coupled EMM oracle.
! uaimms.f writes and reads AIMMS set elements as zero-padded integers of width nfield: '(i<nfield>.<nfield>)'.
! gfortran has no <expr> in formats; oracle/aimms_fortran.py --pre rewrites each such format as a string built from
! these, which gives the same text ("01" for 1 with nfield = 2).
module oracle_vfe
  implicit none
contains
  function vfe(n) result(s)        ! 'i<n>.<n>'
    integer, intent(in) :: n
    character(len=16) :: s
    write(s, '(a,i0,a,i0)') 'i', n, '.', n
  end function vfe

  function vfi(n) result(s)        ! 'i<n>'
    integer, intent(in) :: n
    character(len=16) :: s
    write(s, '(a,i0)') 'i', n
  end function vfi
end module oracle_vfe
