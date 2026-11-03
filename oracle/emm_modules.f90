! Modules EMM needs that gfortran does not have.

! The one module EMM needs from util_tools.f90, copied as is. The rest of that
! file needs Intel's ifport/ifwin.
MODULE EPHRTS_SWTICHES
      !LOGICAL :: TURN_ON_EPHRTS
      LOGICAL :: TURN_ON_DEBUGGING = .FALSE.
      INTEGER :: EPHRTS_DEBUG_SWITCH
      LOGICAL :: EPHRTS_READ_PARAMETER_FILE = .FALSE.
      INTEGER :: EPHRTS
END MODULE

! Intel's portability and runtime modules: only the timer, sleep, working
! directory and file-commit calls EMM makes. None of them changes a result.
MODULE IFPORT
CONTAINS
      REAL(4) FUNCTION TIMEF()
      INTEGER(8) C, R
      CALL SYSTEM_CLOCK(C, R)
      TIMEF = REAL(C) / REAL(R)
      END FUNCTION
      SUBROUTINE SLEEPQQ(MS)
      INTEGER(4) MS
      END SUBROUTINE
      INTEGER(4) FUNCTION GETCWD(DIR)
      CHARACTER(*) DIR
      DIR = '.'
      GETCWD = 0
      END FUNCTION
END MODULE

MODULE IFCORE
CONTAINS
      LOGICAL(4) FUNCTION COMMITQQ(UNIT)
      INTEGER(4) UNIT
      FLUSH(UNIT)
      COMMITQQ = .TRUE.
      END FUNCTION
END MODULE
