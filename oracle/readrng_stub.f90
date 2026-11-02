! Replacement for EIA's ReadRngXLSX. Loads the named ranges that xlsx_ranges.py
! flattened to input/<book>.<sheet>.rng into the same WK1 buffers EIA fills,
! so EIA's own GETRNG* routines do the copying.

subroutine readrngxlsx(funit_in, sheet)
  implicit none
  include 'wk1block'
  integer*4 funit_in
  character*(*) sheet
  character(512) fname, rngfile
  character(300) line
  character(16) nm
  integer u, n, i, j, nv, c1, r1, c2, r2, islash, dot

  inquire(unit=funit_in, name=fname)
  islash = scan(fname, '/\', .true.)
  dot = index(fname, '.', .true.)
  rngfile = 'input/'//fname(islash+1:dot-1)//'.'//trim(sheet)//'.rng'

  icount = 0
  ivcount = 0
  istrcount = 0
  open(newunit=u, file=trim(rngfile), status='old', action='read')
  read(u, *) n
  do i = 1, n
    read(u, *) nm, c1, r1, c2, r2, nv
    icount = icount + 1
    rngname(icount) = nm
    rngdim(icount, 1) = c1
    rngdim(icount, 2) = r1
    rngdim(icount, 3) = c2
    rngdim(icount, 4) = r2
    rngloc(icount) = ivcount + 1
    do j = 1, nv
      read(u, '(a)') line
      ivcount = ivcount + 1
      if (line(1:2) == 'S ') then
        istrcount = istrcount + 1
        rnglab(istrcount) = line(3:)
        rnglen(istrcount) = len_trim(line(3:))
        rngval(ivcount) = real(istrcount)
      else
        read(line, *) rngval(ivcount)
      endif
    enddo
  enddo
  close(u)
end subroutine readrngxlsx
