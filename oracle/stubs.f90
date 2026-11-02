! Stand-ins for the NEMS services comm.f calls, so it runs outside NEMS.
! FILE_MGR opens files by key using run/filelist.txt.
! RTOVALUE returns scenario switches from run/options.txt.
! CALLSYS replaces Intel's DFPORT routine of the same name.

integer function file_mgr(func, name_in, new)
  implicit none
  character(1) func
  character(*) name_in
  logical new
  character(64) key
  character(512) path
  character(600) line
  integer u, ios, sp
  logical found
  integer, save :: units(500) = 0
  character(64), save :: keys(500) = ' '

  key = adjustl(name_in)
  if (func == 'C' .or. func == 'c') then
    do u = 1, 500
      if (keys(u) == key .and. units(u) > 0) then
        close(units(u))
        units(u) = 0
        keys(u) = ' '
        exit
      endif
    enddo
    file_mgr = 0
    return
  endif

  found = .false.
  open(newunit=u, file='filelist.txt', status='old', action='read')
  do
    read(u, '(a)', iostat=ios) line
    if (ios /= 0) exit
    sp = index(line, ' ')
    if (line(1:sp-1) == trim(key)) then
      path = adjustl(line(sp+1:))
      found = .true.
      exit
    endif
  enddo
  close(u)
  if (.not. found) then
    ! Report and debug files NEMS names at run time: send them to out/.
    call execute_command_line('if not exist out mkdir out')
    path = 'out/'//trim(key)//'.txt'
    open(newunit=u, file=trim(path), status='replace', action='write')
  else if (new) then
    open(newunit=u, file=trim(path), status='replace', action='write')
  else
    open(newunit=u, file=trim(path), status='old', action='read')
  endif
  do sp = 1, 500
    if (units(sp) == 0) then
      units(sp) = u
      keys(sp) = key
      exit
    endif
  enddo
  file_mgr = u
end function file_mgr

integer function rtovalue(name, default)
  implicit none
  character(*) name
  integer default
  character(64) k
  character(200) line
  integer u, ios, v
  rtovalue = default
  open(newunit=u, file='options.txt', status='old', action='read')
  do
    read(u, '(a)', iostat=ios) line
    if (ios /= 0) exit
    read(line, *, iostat=ios) k, v
    if (ios == 0 .and. trim(k) == trim(adjustl(name))) then
      rtovalue = v
      exit
    endif
  enddo
  close(u)
end function rtovalue

! Read one restart variable's raw bytes from run/dump. Lives here, apart from the
! generated loader, so gfortran doesn't type-check the untyped byte buffer.
subroutine ld(fname, nbytes, x, nbad)
  implicit none
  character(*) fname
  integer(8) nbytes
  integer(1) x(*)
  integer nbad, u, fsize
  inquire(file='dump/'//fname, size=fsize)
  if (fsize /= nbytes) then
    write(*,'(a,a,2i12)') ' size mismatch ', fname, fsize, nbytes
    nbad = nbad + 1
    return
  endif
  open(newunit=u, file='dump/'//fname, access='stream', form='unformatted', status='old')
  read(u) x(1:nbytes)
  close(u)
end subroutine ld

! Write one array's raw bytes to run/out for the Python tests.
subroutine dump(name, x, nbytes)
  implicit none
  character(*) name
  integer(1) x(*)
  integer(8) nbytes
  integer u
  call execute_command_line('if not exist out mkdir out')
  open(newunit=u, file='out/'//name//'.bin', access='stream', form='unformatted', status='replace')
  write(u) x(1:nbytes)
  close(u)
end subroutine dump

! Two INTEGERs written as reals ("1.000"), read the way Intel Fortran allows.
subroutine read_ints_lenient(u, a, b)
  implicit none
  integer u, a, b
  real ra, rb
  read(u, *) ra, rb
  a = nint(ra)
  b = nint(rb)
end subroutine read_ints_lenient

! State dump for hooks.py: raw bytes plus one index line with type and bounds.
subroutine odump(tag, name, iyr, x, nbytes, tcode, rnk, lb, ub)
  implicit none
  character(*) tag, name, tcode
  integer iyr, rnk, lb(*), ub(*)
  integer(1) x(*)
  integer(8) nbytes
  character(256) dir
  integer u, k
  write(dir, '(a,a,a,i0,a)') 'out/state/', tag, '/', iyr, '/'
  open(newunit=u, file=trim(dir)//name//'.bin', access='stream', form='unformatted', status='replace')
  write(u) x(1:nbytes)
  close(u)
  open(newunit=u, file=trim(dir)//'index.txt', position='append', action='write')
  write(u, '(a,1x,a,1x,i0)', advance='no') name, tcode, rnk
  do k = 1, rnk
    write(u, '(1x,i0,1x,i0)', advance='no') lb(k), ub(k)
  enddo
  write(u, *)
  close(u)
end subroutine odump

subroutine callsys(iret, cmd)
  implicit none
  integer iret
  character(*) cmd
  call execute_command_line(trim(cmd), exitstat=iret)
end subroutine callsys
