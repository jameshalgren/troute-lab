! Harness: route an inflow hydrograph through N identical reaches with the verbatim
! WRF-Hydro SUBMUSKINGCUNGE, original (mc_orig) and patched (mc_patched).
! AI-written (Claude, 2026-10-09). Sequential (current-step) upstream inflow, no lateral
! inflow, no channel loss. Usage:
!   driver <orig|patched> <config.txt> <inflow.txt> <out.txt>
! config.txt: nseg dx dt So n Cs Bw Tw TwCC nCC nspin nout   (one line, free format)
! inflow.txt: one value per line (m3/s), first value is the steady base flow
! out.txt   : one line per step: step, inflow, outflow at segments listed below
program driver
  use mc_orig,    only: sub_orig    => SUBMUSKINGCUNGE
  use mc_patched, only: sub_patched => SUBMUSKINGCUNGE
  use iso_fortran_env, only: int64
  implicit none
  character(len=256) :: variant, cfgf, inf, outf
  integer :: nseg, nspin, nout, nt, i, k, ios, u
  real :: dx, dt, So, n, Cs, Bw, Tw, TwCC, nCC
  real, allocatable :: inflow(:), qprev(:), qcur(:), depth(:), vel(:), qloss(:)
  integer, allocatable :: outseg(:)
  real :: qup, quc, qdc, val
  integer(kind=int64) :: idx

  call get_command_argument(1, variant)
  call get_command_argument(2, cfgf)
  call get_command_argument(3, inf)
  call get_command_argument(4, outf)

  open(newunit=u, file=trim(cfgf), status='old')
  read(u, *) nseg, dx, dt, So, n, Cs, Bw, Tw, TwCC, nCC, nspin, nout
  allocate(outseg(nout))
  read(u, *) outseg
  close(u)

  ! read inflow series
  nt = 0
  open(newunit=u, file=trim(inf), status='old')
  do
    read(u, *, iostat=ios) val
    if (ios /= 0) exit
    nt = nt + 1
  end do
  rewind(u)
  allocate(inflow(nt))
  do i = 1, nt
    read(u, *) inflow(i)
  end do
  close(u)

  allocate(qprev(nseg), qcur(nseg), depth(nseg), vel(nseg), qloss(nseg))
  qprev = inflow(1); qcur = inflow(1); depth = 0.0; vel = 0.0; qloss = 0.0

  ! spin-up at the base flow so every reach starts at its own steady depth
  do i = 1, nspin
    call step(inflow(1), inflow(1))
  end do

  open(newunit=u, file=trim(outf), status='replace')
  do i = 2, nt
    call step(inflow(i-1), inflow(i))
    write(u, '(I8,1X,ES16.8)', advance='no') i - 1, inflow(i)
    do k = 1, nout
      write(u, '(1X,ES16.8)', advance='no') qcur(outseg(k))
    end do
    write(u, *)
  end do
  close(u)

contains

  subroutine step(qin_prev, qin_cur)
    real, intent(in) :: qin_prev, qin_cur
    integer :: kk
    do kk = 1, nseg
      if (kk == 1) then
        qup = qin_prev; quc = qin_cur
      else
        qup = qprev(kk-1); quc = qcur(kk-1)
      end if
      qdc = 0.0
      idx = kk
      if (trim(variant) == 'orig') then
        call sub_orig(qdc, vel(kk), qloss(kk), idx, qup, quc, qprev(kk), 0.0, dt, So, dx, &
                      n, Cs, Bw, Tw, TwCC, nCC, depth(kk), 0.0)
      else
        call sub_patched(qdc, vel(kk), qloss(kk), idx, qup, quc, qprev(kk), 0.0, dt, So, dx, &
                         n, Cs, Bw, Tw, TwCC, nCC, depth(kk), 0.0)
      end if
      qcur(kk) = qdc
    end do
    qprev = qcur
  end subroutine step

end program driver
