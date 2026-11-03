! Stand-ins for routines EMM's Fortran calls that live outside the files the
! oracle compiles.
!
! Copied from EIA (same code): CENSUS and ISTATE (nemsfunct.f), UNITUNOPENED
! (arraycode.f).
! Timers (MPTIM2, MPTIM3): return 0; they only feed timing reports.
! RTOSTRING: only asked for AIMMSLOC, the AIMMS install folder. Returns blank.
! The rest is EMM's AIMMS interface (uaimms.f) and the LP solution readers. With
! the ECP and EFD solves swapped out they should never run; each prints one line
! the first time it is called, so the run log shows it if one is reached.

      FUNCTION CENSUS(IS)
      INTEGER CENSUS,ICENSD(53)
      DATA ICENSD/ 9, 6, 7, 8, 9, 8, 1, 5, 5, 5, &
                   5, 9, 4, 8, 3, 3, 4, 6, 7, 1, &
                   5, 1, 3, 4, 4, 6, 8, 5, 4, 4, &
                   1, 2, 8, 8, 2, 3, 7, 9, 2, 1, &
                   5, 4, 6, 7, 8, 5, 1, 9, 3, 5, &
                   8,11,11/
      CENSUS=0
      IF(IS.GE.1.AND.IS.LE.53) THEN
        CENSUS=ICENSD(IS)
      ELSE
        WRITE(6,*) 'BAD STATE INDEX IN FUNCTION CENSUS. IS=',IS
      ENDIF
      RETURN
      END

      FUNCTION ISTATE(STATE)
      CHARACTER*2 STATES(53),STATE
      DATA STATES/ 'AK','AL','AR','AZ','CA','CO','CT','DC','DE','FL', &
                   'GA','HI','IA','ID','IL','IN','KS','KY','LA','MA', &
                   'MD','ME','MI','MN','MO','MS','MT','NC','ND','NE', &
                   'NH','NJ','NM','NV','NY','OH','OK','OR','PA','RI', &
                   'SC','SD','TN','TX','UT','VA','VT','WA','WI','WV', &
                   'WY','US','48'/
      ISTATE=0
      DO 10 I=1,53
        IF(STATE.EQ.STATES(I))THEN
          ISTATE=I
          RETURN
        ENDIF
10    CONTINUE
      RETURN
      END

subroutine unitunopened(start,end,iunit)
implicit none
logical :: lopen
integer :: start,end,iunit
integer i
iunit=-1
do i= start,end
  iunit=i
  inquire(unit=iunit,opened=lopen)
  if(.not. lopen) then
     return
  endif
enddo
return
end

      SUBROUTINE MPTIM2(ICSEC)
      INTEGER ICSEC
      ICSEC = 0
      END
      SUBROUTINE MPTIM3(ICSEC, ICWALL)
      INTEGER ICSEC, ICWALL
      ICSEC = 0
      ICWALL = 0
      END
      SUBROUTINE RTOSTRING(RTONAME, RTOVALUE)
      CHARACTER*(*) RTONAME, RTOVALUE
      RTOVALUE = ' '
      END

      SUBROUTINE STUB_HIT(NAME)
      CHARACTER*(*) NAME
      CHARACTER(40) SEEN(100)
      INTEGER NSEEN, I
      SAVE SEEN, NSEEN
      DO I = 1, NSEEN
         IF (SEEN(I) .EQ. NAME) RETURN
      END DO
      IF (NSEEN .LT. 100) THEN
         NSEEN = NSEEN + 1
         SEEN(NSEEN) = NAME
      END IF
      WRITE(6,'(2A)') ' ORACLE STUB CALLED: ', NAME
      END

      SUBROUTINE MAKMSK
      CALL STUB_HIT('MAKMSK')
      END
      SUBROUTINE CWFSCOL
      CALL STUB_HIT('CWFSCOL')
      END
      SUBROUTINE CWFSROW
      CALL STUB_HIT('CWFSROW')
      END
      SUBROUTINE DWFSCOL
      CALL STUB_HIT('DWFSCOL')
      END
      SUBROUTINE DWFSROW
      CALL STUB_HIT('DWFSROW')
      END
      SUBROUTINE USEHASH
      CALL STUB_HIT('USEHASH')
      END
      SUBROUTINE GET_MASKED_COL
      CALL STUB_HIT('GET_MASKED_COL')
      END
      SUBROUTINE EFD_SET_AIMMS_ROW_ID
      CALL STUB_HIT('EFD_SET_AIMMS_ROW_ID')
      END
      SUBROUTINE ECP_SET_AIMMS_ROW_ID
      CALL STUB_HIT('ECP_SET_AIMMS_ROW_ID')
      END
      SUBROUTINE EFD_SET_AIMMS_COL_ID
      CALL STUB_HIT('EFD_SET_AIMMS_COL_ID')
      END
      SUBROUTINE ECP_SET_AIMMS_COL_ID
      CALL STUB_HIT('ECP_SET_AIMMS_COL_ID')
      END
      SUBROUTINE EFD_ASSIGN_COEFF
      CALL STUB_HIT('EFD_ASSIGN_COEFF')
      END
      SUBROUTINE ECP_ASSIGN_COEFF
      CALL STUB_HIT('ECP_ASSIGN_COEFF')
      END
      SUBROUTINE SETTOUSEAIMSEFDPOSTADJST
      CALL STUB_HIT('SETTOUSEAIMSEFDPOSTADJST')
      END
      SUBROUTINE SETTOUSEAIMSECPPOSTADJST
      CALL STUB_HIT('SETTOUSEAIMSECPPOSTADJST')
      END
      SUBROUTINE READAIMEFDOPTIONS
      CALL STUB_HIT('READAIMEFDOPTIONS')
      END
      SUBROUTINE READAIMECPOPTIONS
      CALL STUB_HIT('READAIMECPOPTIONS')
      END
      SUBROUTINE EFD_LIST_AIMMS_ROWCOLS
      CALL STUB_HIT('EFD_LIST_AIMMS_ROWCOLS')
      END
      SUBROUTINE EFD_FILL_AIMMS_COEFF
      CALL STUB_HIT('EFD_FILL_AIMMS_COEFF')
      END
      SUBROUTINE EFD_AIMMS_INIT
      CALL STUB_HIT('EFD_AIMMS_INIT')
      END
      SUBROUTINE ECP_LIST_AIMMS_ROWCOLS
      CALL STUB_HIT('ECP_LIST_AIMMS_ROWCOLS')
      END
      SUBROUTINE ECP_FILL_AIMMS_COEFF
      CALL STUB_HIT('ECP_FILL_AIMMS_COEFF')
      END
      SUBROUTINE ECP_AIMMS_INIT
      CALL STUB_HIT('ECP_AIMMS_INIT')
      END
      SUBROUTINE CHECKTODISABLEEFDOMLLP
      CALL STUB_HIT('CHECKTODISABLEEFDOMLLP')
      END
      SUBROUTINE CHECKTODISABLEECPOMLLP
      CALL STUB_HIT('CHECKTODISABLEECPOMLLP')
      END
      SUBROUTINE AIMMS_TRANSFER_OUT_EFD
      CALL STUB_HIT('AIMMS_TRANSFER_OUT_EFD')
      END
      SUBROUTINE AIMMS_TRANSFER_OUT_ECP
      CALL STUB_HIT('AIMMS_TRANSFER_OUT_ECP')
      END
      SUBROUTINE AIMMS_RESTORE
      CALL STUB_HIT('AIMMS_RESTORE')
      END
      SUBROUTINE AIMMS_INTXTVAR_EFD
      CALL STUB_HIT('AIMMS_INTXTVAR_EFD')
      END
      SUBROUTINE AIMMS_INTXTVAR_ECP
      CALL STUB_HIT('AIMMS_INTXTVAR_ECP')
      END
      SUBROUTINE AIMMS_INTXT_EFD
      CALL STUB_HIT('AIMMS_INTXT_EFD')
      END
      SUBROUTINE AIMMS_INTXT_ECP
      CALL STUB_HIT('AIMMS_INTXT_ECP')
      END
      SUBROUTINE AIMMS_EFD
      CALL STUB_HIT('AIMMS_EFD')
      END
      SUBROUTINE AIMMS_ECP
      CALL STUB_HIT('AIMMS_ECP')
      END
