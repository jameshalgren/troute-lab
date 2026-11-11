! Stubs for the symbols SUBMUSKINGCUNGE needs from the rest of WRF-Hydro
! (AI-written, Claude, 2026-10-09). Only used on the non-convergence warning path
! (linkls_s, my_id) and the fatal-error path (hydro_stop).
module harness_stubs
  implicit none
  integer :: my_id = 0
  integer :: linkls_s(1) = (/ 1 /)
contains
  subroutine hydro_stop(msg)
    character(len=*), intent(in) :: msg
    print *, "HYDRO_stop: ", trim(msg)
    stop 1
  end subroutine hydro_stop
end module harness_stubs
