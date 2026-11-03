! Stand-ins for the NEMS services comm.f calls, so it runs outside NEMS.
! FILE_MGR opens files by key using run/filelist.txt.
! RTOVALUE returns scenario switches from run/options.txt.
! CALLSYS replaces Intel's DFPORT routine of the same name.

integer function file_mgr(func, name_in, new)
  implicit none
  character(1) func
  character(*) name_in
  ! One byte: callers pass LOGICAL*1 (tran.f) or default LOGICAL (comm.f). Reading
  ! four bytes from a LOGICAL*1 picks up whatever follows it in memory.
  logical(1) new
  character(64) key
  character(512) path
  character(600) line
  integer u, ios, sp
  logical found, found_open
  integer, save :: units(500) = 0
  character(64), save :: keys(500) = ' '

  key = adjustl(name_in)
  ! NEMS file names are CHARACTER*18 (filemgr.f), so callers with a shorter buffer
  ! (tran*.f: TRNSTOCKX_HDV_PRE2012 in CHARACTER*18) match on the first 18 characters.
  key = key(1:18)
  if (func == 'C' .or. func == 'c') then
    do u = 1, 500
      if (keys(u) == key .and. units(u) /= 0) then   ! newunit numbers are negative
        close(units(u))
        units(u) = 0
        keys(u) = ' '
        exit
      endif
    enddo
    file_mgr = 0
    return
  endif

  ! Keys listed in filemodes.txt (written only for EMM) open the way NEMS's
  ! filemgr.f opens them: action, access, form and record length from the scedes
  ! file, unformatted files big-endian, and a key already open keeps its unit.
  if (mode_open(key, u)) then
    if (.not. any(keys == key .and. units == u)) then
      do sp = 1, 500
        if (units(sp) == 0) then
          units(sp) = u
          keys(sp) = key
          exit
        endif
      enddo
    endif
    file_mgr = u
    return
  endif

  found = .false.
  open(newunit=u, file='filelist.txt', status='old', action='read')
  do
    read(u, '(a)', iostat=ios) line
    if (ios /= 0) exit
    sp = index(line, ' ')
    if (line(1:min(sp-1, 18)) == trim(key)) then
      path = adjustl(line(sp+1:))
      found = .true.
      exit
    endif
  enddo
  close(u)
  if (found .and. new .and. (index(path, '\input') > 0 .or. index(path, '/input/') > 0)) then
    ! An EIA input file: never write over one (tran*.f opens some inputs with NEW true).
    found = .false.
  endif
  ! Positive unit numbers from 200 up, as NEMS's FILE_MGR assigns them. tranair.f
  ! closes its debug unit in 2050 and then writes to it again; on a positive unit
  ! that reopens fort.<unit> (Intel and gfortran alike) instead of stopping.
  u = 200
  do
    inquire(unit=u, opened=found_open)
    if (.not. found_open) exit
    u = u + 1
  enddo
  if (.not. found) then
    ! Report and debug files NEMS names at run time: send them to out/.
    call execute_command_line('if not exist out mkdir out')
    path = 'out/'//trim(key)//'.txt'
    open(unit=u, file=trim(path), status='replace', action='write')
  else if (new) then
    open(unit=u, file=trim(path), status='replace', action='write')
  else
    open(unit=u, file=trim(path), status='old', action='read')
  endif
  do sp = 1, 500
    if (units(sp) == 0) then
      units(sp) = u
      keys(sp) = key
      exit
    endif
  enddo
  file_mgr = u

contains

  logical function mode_open(key, unit)
    character(*) key
    integer unit
    character(16) mkey, act, acc, frm, st
    character(512) mpath
    character(600) mline
    integer mu, mios, recl, k, sp1
    logical ex, isopen
    logical, save :: have_modes = .true.
    mode_open = .false.
    if (.not. have_modes) return
    inquire(file='filemodes.txt', exist=have_modes)
    if (.not. have_modes) return
    open(newunit=mu, file='filemodes.txt', status='old', action='read')
    do
      read(mu, '(a)', iostat=mios) mline
      if (mios /= 0) exit
      ! KEY ACTION ACCESS FORM RECL PATH (path last: it may hold spaces)
      read(mline, *, iostat=mios) mkey, act, acc, frm, recl
      if (mios /= 0 .or. trim(mkey) /= trim(key)) cycle
      sp1 = 0
      do k = 1, 5
        sp1 = sp1 + index(mline(sp1+1:), ' ')
        do while (mline(sp1+1:sp1+1) == ' ')
          sp1 = sp1 + 1
        enddo
      enddo
      mpath = adjustl(mline(sp1+1:))
      mode_open = .true.
      exit
    enddo
    close(mu)
    if (.not. mode_open) return
    inquire(file=trim(mpath), opened=isopen, number=unit)
    if (isopen .and. .not. new) then
      close(unit)               ! filemgr: an input file already open is reopened
    else if (isopen) then
      return
    endif
    inquire(file=trim(mpath), exist=ex)
    st = merge('UNKNOWN', 'NEW    ', ex)
    if (.not. new) st = 'OLD'
    if (act == 'READ') st = 'OLD'
    if (frm == 'UNFORMATTED' .and. acc == 'DIRECT') then
      open(newunit=unit, file=trim(mpath), access='DIRECT', form='UNFORMATTED', action=trim(act), &
           status=trim(st), recl=recl, convert='BIG_ENDIAN')
    else if (frm == 'UNFORMATTED') then
      open(newunit=unit, file=trim(mpath), access='SEQUENTIAL', form='UNFORMATTED', action=trim(act), &
           status=trim(st), convert='BIG_ENDIAN')
    else if (acc == 'DIRECT') then
      open(newunit=unit, file=trim(mpath), access='DIRECT', form='FORMATTED', action=trim(act), &
           status=trim(st), recl=recl)
    else
      open(newunit=unit, file=trim(mpath), access='SEQUENTIAL', form='FORMATTED', action=trim(act), &
           status=trim(st))
    endif
  end function mode_open
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

! Same as odump, for fixed-length text arrays.
subroutine odump_c(tag, name, iyr, x, nbytes, tcode, rnk, lb, ub)
  implicit none
  character(*) tag, name, tcode
  character(*) x(*)
  integer iyr, rnk, lb(*), ub(*)
  integer(8) nbytes
  character(256) dir
  integer u, k, n
  n = int(nbytes / len(x))
  write(dir, '(a,a,a,i0,a)') 'out/state/', tag, '/', iyr, '/'
  open(newunit=u, file=trim(dir)//name//'.bin', access='stream', form='unformatted', status='replace')
  write(u) x(1:n)
  close(u)
  open(newunit=u, file=trim(dir)//'index.txt', position='append', action='write')
  write(u, '(a,1x,a,1x,i0)', advance='no') name, tcode, rnk
  do k = 1, rnk
    write(u, '(1x,i0,1x,i0)', advance='no') lb(k), ub(k)
  enddo
  write(u, *)
  close(u)
end subroutine odump_c

subroutine callsys(iret, cmd)
  implicit none
  integer iret
  character(*) cmd
  call execute_command_line(trim(cmd), exitstat=iret)
end subroutine callsys
