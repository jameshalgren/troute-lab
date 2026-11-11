! Potomac example: route a network with the verbatim WRF-Hydro SUBMUSKINGCUNGE, original
! (mc_orig) or patched (mc_patched), the way DRIVE_CHANNEL does for channel_option = 2
! (module_channel_routing.F90 at 55ed71c8, DRIVE_CHANNEL, the channel_option /= 3 branch):
!   - QLateral is held for the whole hour; the channel steps at dt within it (nsub steps);
!   - every link gets Qup = Quc = the sum of its upstream links' flow from the previous
!     step (QLINK(:,1) = QLINK(:,2) at the end of each step, and both are broadcast
!     before the loop), so the loop order does not matter;
!   - outputs go to a temporary array and are copied after all links are done.
! Not exercised: reservoirs (all links routed as channels), channel loss (ChannK = 0;
! RouteLink Kchan is 0 on every Potomac link), nudging, MPI.
! AI-written (Claude, 2026-10-16).
!
! Usage: network_driver <orig|patched> <inputs.bin> <outprefix> [lagged|sequential]
! Upstream inflow mode (4th argument; added 2026-11-02, AI-written, Claude):
!   lagged (default; WRF-Hydro-faithful, as described above): Qup = Quc = the sum of the
!     upstream links' previous-step flow. This is T-Route's assume_short_ts True, the
!     operational NWM setting.
!   sequential (not what WRF-Hydro does; for comparison only): links are processed in
!     topological order (headwaters first); Qup = the sum of the upstream links'
!     previous-step flow, Quc = the sum of their flow from this step. This is T-Route's
!     assume_short_ts False.
! inputs.bin (stream, native endianness), written by potomac_inputs.py:
!   int32 n, nhours, nsub, nrec; real32 dt
!   int32 down(n)            (1-based index of the downstream link, 0 at the outlet)
!   int64 linkid(n)
!   real32 So, dx, nman, Cs, Bw, Tw, TwCC, nCC, q0   (each n)
!   int32 rec(nrec)          (links whose hourly flow is written)
!   real32 ql(n, nhours)     (hourly lateral inflow, m3/s)
! Outputs:
!   <outprefix>_hydro.bin  real32 (nrec, nhours+1)  flow at rec links, t = 0, 1 h, ...
!   <outprefix>_peaks.bin  real32 qpeak(n), int32 kpeak(n) (step of the peak), real64 vol(n)
!   <outprefix>_floor.bin  int32 nfloor(n): steps with X on its 0.25 floor, per link (diagnostic)
!   <outprefix>_diag.txt   counts (see the write statement at the end)
! Diagnostics (not part of the routing): after each call, X is recomputed from the
! converged depth and outflow with the routine's own Ck and width formulas. The routine
! itself evaluates X at its last secant iterate, so this is a close diagnostic, not the
! routine's internal value.
program network_driver
  use mc_orig,    only: sub_orig    => SUBMUSKINGCUNGE
  use mc_patched, only: sub_patched => SUBMUSKINGCUNGE
  use iso_fortran_env, only: int32, int64, real32, real64
  implicit none
  character(len=512) :: variant, inpf, outp, mode
  integer(int32) :: n, nhours, nsub, nrec
  real(real32) :: dt
  integer(int32), allocatable :: down(:), rec(:), kpeak(:), nfloor(:), topo(:), nup(:)
  integer(int64), allocatable :: linkid(:)
  real(real32), allocatable :: So(:), dx(:), nman(:), Cs(:), Bw(:), Tw(:), TwCC(:), nCC(:)
  real(real32), allocatable :: q0(:), ql(:,:), q(:), qtmp(:), qin(:), qinc(:), depth(:), vel(:), qloss(:)
  real(real32), allocatable :: qpeak(:), hydro(:,:)
  real(real64), allocatable :: vol(:)
  integer :: u, h, s, k, kk, step, ntopo, head
  logical :: patched, sequential
  real(real32) :: qdc
  real(real64) :: maxdev_steady
  ! diagnostics
  integer(int64) :: nss, n_floor, n_ckzero, n_kclamp, n_overbank, n_dry
  real(real64) :: w_all, w_floor
  real(real32) :: Dc
  logical :: floor_now

  call get_command_argument(1, variant)
  call get_command_argument(2, inpf)
  call get_command_argument(3, outp)
  patched = trim(variant) == 'patched'
  mode = 'lagged'
  if (command_argument_count() >= 4) call get_command_argument(4, mode)
  if (trim(mode) /= 'lagged' .and. trim(mode) /= 'sequential') error stop 'mode: lagged or sequential'
  sequential = trim(mode) == 'sequential'

  open(newunit=u, file=trim(inpf), access='stream', form='unformatted', status='old')
  read(u) n, nhours, nsub, nrec, dt
  allocate(down(n), linkid(n), So(n), dx(n), nman(n), Cs(n), Bw(n), Tw(n), TwCC(n), nCC(n), q0(n))
  allocate(rec(nrec), ql(n, nhours))
  read(u) down
  read(u) linkid
  read(u) So; read(u) dx; read(u) nman; read(u) Cs; read(u) Bw; read(u) Tw
  read(u) TwCC; read(u) nCC; read(u) q0
  read(u) rec
  read(u) ql
  close(u)

  allocate(q(n), qtmp(n), qin(n), qinc(n), depth(n), vel(n), qloss(n), qpeak(n), kpeak(n), vol(n), nfloor(n))
  allocate(hydro(nrec, nhours + 1))
  ! processing order: input order (lagged; the order does not matter there), or
  ! topological, headwaters first (sequential; Kahn's algorithm on down)
  allocate(topo(n), nup(n))
  if (sequential) then
    nup = 0
    do k = 1, n
      if (down(k) > 0) nup(down(k)) = nup(down(k)) + 1
    end do
    ntopo = 0
    do k = 1, n
      if (nup(k) == 0) then
        ntopo = ntopo + 1; topo(ntopo) = k
      end if
    end do
    head = 1
    do while (head <= ntopo)
      k = topo(head); head = head + 1
      if (down(k) > 0) then
        nup(down(k)) = nup(down(k)) - 1
        if (nup(down(k)) == 0) then
          ntopo = ntopo + 1; topo(ntopo) = down(k)
        end if
      end if
    end do
    if (ntopo /= n) error stop 'network is not a tree (cycle in down)'
  else
    topo = [(k, k = 1, n)]
  end if
  q = q0; depth = 0.0; vel = 0.0; qloss = 0.0
  qpeak = q0; kpeak = 0; vol = 0.0d0; nfloor = 0
  hydro(:, 1) = q(rec)
  nss = 0; n_floor = 0; n_ckzero = 0; n_kclamp = 0; n_overbank = 0; n_dry = 0
  w_all = 0.0d0; w_floor = 0.0d0; maxdev_steady = 0.0d0

  step = 0
  do h = 1, nhours
    do s = 1, nsub
      step = step + 1
      qin = 0.0
      do k = 1, n
        if (down(k) > 0) qin(down(k)) = qin(down(k)) + q(k)
      end do
      if (sequential) then
        qinc = 0.0                   ! filled with this step's upstream outflow as links finish
      else
        qinc = qin                   ! Quc = Qup, previous step
      end if
      do kk = 1, n
        k = topo(kk)
        qdc = 0.0
        if (patched) then
          call sub_patched(qdc, vel(k), qloss(k), linkid(k), qin(k), qinc(k), q(k), ql(k, h), dt, &
                           So(k), dx(k), nman(k), Cs(k), Bw(k), Tw(k), TwCC(k), nCC(k), depth(k), 0.0)
        else
          call sub_orig(qdc, vel(k), qloss(k), linkid(k), qin(k), qinc(k), q(k), ql(k, h), dt, &
                        So(k), dx(k), nman(k), Cs(k), Bw(k), Tw(k), TwCC(k), nCC(k), depth(k), 0.0)
        end if
        qtmp(k) = qdc
        if (sequential .and. down(k) > 0) qinc(down(k)) = qinc(down(k)) + qdc
        call diagnose(k, qdc)
      end do
      q = qtmp
      vol = vol + real(q, real64) * dt
      do k = 1, n
        if (q(k) > qpeak(k)) then
          qpeak(k) = q(k); kpeak(k) = step
        end if
      end do
      if (h <= 24) maxdev_steady = max(maxdev_steady, maxval(abs(real(q, real64) - q0)))
    end do
    hydro(:, h + 1) = q(rec)
  end do

  open(newunit=u, file=trim(outp)//'_hydro.bin', access='stream', form='unformatted', status='replace')
  write(u) hydro
  close(u)
  open(newunit=u, file=trim(outp)//'_peaks.bin', access='stream', form='unformatted', status='replace')
  write(u) qpeak; write(u) kpeak; write(u) vol
  close(u)
  open(newunit=u, file=trim(outp)//'_floor.bin', access='stream', form='unformatted', status='replace')
  write(u) nfloor
  close(u)
  open(newunit=u, file=trim(outp)//'_diag.txt', status='replace')
  write(u, '(A)') 'segment_steps floor ck_zero kclamp overbank dry flow_weight_all flow_weight_floor maxdev_steady_m3s'
  write(u, '(6(I0,1X),3(ES24.16,1X))') nss, n_floor, n_ckzero, n_kclamp, n_overbank, n_dry, w_all, w_floor, &
      maxdev_steady
  close(u)

contains

  ! Recompute D = Q/(B*So*Ck*dx) at the converged depth with the routine's formulas
  ! (bankfull depth, area, hydraulic radius, Ck and width as in SUBMUSKINGCUNGE).
  ! X sits on the 0.25 floor when D >= 1 (current formula) or D >= 0.5 (patched).
  subroutine diagnose(k, qq)
    integer, intent(in) :: k
    real(real32), intent(in) :: qq
    real(real32) :: z, bfd, hh, Twl, AREA, AREAC, WP, WPC, R, Ck, B
    logical :: over
    nss = nss + 1
    w_all = w_all + qq
    hh = depth(k)
    if (hh <= 0.0 .or. qq <= 0.0) then
      n_dry = n_dry + 1
      return
    end if
    if (Cs(k) == 0.0) then
      z = 1.0
    else
      z = 1.0 / Cs(k)
    end if
    if (Bw(k) > Tw(k)) then
      bfd = Bw(k) / 0.00001
    else if (Bw(k) == Tw(k)) then
      bfd = Bw(k) / (2.0 * z)
    else
      bfd = (Tw(k) - Bw(k)) / (2.0 * z)
    end if
    Twl = Bw(k) + 2.0 * z * hh
    over = (hh > bfd) .and. (TwCC(k) > 0.0) .and. (nCC(k) > 0.0)
    if (over) then
      AREA = (Bw(k) + bfd * z) * bfd
      AREAC = TwCC(k) * (hh - bfd)
      WP = Bw(k) + 2.0 * bfd * sqrt(1.0 + z * z)
      WPC = TwCC(k) + 2.0 * (hh - bfd)
      R = (AREA + AREAC) / (WP + WPC)
      Ck = max(0.0, ((sqrt(So(k)) / nman(k)) * ((5./3.) * R**(2./3.) - &
           ((2./3.) * R**(5./3.) * (2.0 * sqrt(1.0 + z * z) / (Bw(k) + 2.0 * bfd * z)))) * AREA &
           + ((sqrt(So(k)) / nCC(k)) * (5./3.) * (hh - bfd)**(2./3.)) * AREAC) / (AREA + AREAC))
    else
      AREA = (Bw(k) + hh * z) * hh
      WP = Bw(k) + 2.0 * hh * sqrt(1.0 + z * z)
      R = AREA / WP
      Ck = max(0.0, (sqrt(So(k)) / nman(k)) * ((5./3.) * R**(2./3.) - &
           ((2./3.) * R**(5./3.) * (2.0 * sqrt(1.0 + z * z) / (Bw(k) + 2.0 * hh * z)))))
    end if
    if (Ck <= 0.0) then
      n_ckzero = n_ckzero + 1          ! the routine sets X = 0.5 when Ck = 0
      return
    end if
    if (over) then
      n_overbank = n_overbank + 1
      B = TwCC(k)
    else
      B = Twl
    end if
    if (dx(k) / Ck < dt) n_kclamp = n_kclamp + 1     ! Km = max(dt, dx/Ck) binds
    Dc = qq / (B * So(k) * Ck * dx(k))
    if (patched) then
      floor_now = Dc >= 0.5
    else
      floor_now = Dc >= 1.0
    end if
    if (floor_now) then
      n_floor = n_floor + 1
      nfloor(k) = nfloor(k) + 1
      w_floor = w_floor + qq
    end if
  end subroutine diagnose

end program network_driver
