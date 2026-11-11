! Test driver for T-Route's Muskingum-Cunge kernel (muskingcungenwm).
!
!   driver CASES OUT ORDER PRESET SCRIBBLE MODE
!
! CASES    float32 stream: int32 n, then n records of 15 inputs in the kernel's argument
!          order (dt, qup, quc, qdp, ql, dx, bw, tw, twcc, n, ncc, cs, s0, velp, depthp).
! OUT      float32 stream: n records of 6 outputs (qdc, velc, depthc, ck, cn, X), then
!          n int32 flags (bit 0: IEEE invalid raised during the call; bit 1: divide by
!          zero; bit 2: overflow).
! ORDER    f = cases in file order, r = reverse order (changes what the previous call
!          left on the stack, as a different network order would).
! PRESET   value written into every output argument before the call. T-Route's Cython
!          caller (reach.pyx) sets them to 0.0; any other value exposes reads of
!          intent(out) arguments and outputs left unset.
! SCRIBBLE 0 = nothing between calls; k > 0 = before each call, run a routine that fills
!          a stack array with values derived from k and the case index (stack residue
!          that differs between runs, as in another process or call history).
! MODE     c = call the bind(c) wrapper c_muskingcungenwm through an interface without
!          intents, as T-Route's Cython code does from C: the preset values reach the
!          kernel. f = call muskingcungenwm directly from Fortran: the compiler may treat
!          the intent(out) actuals as undefined at the call and drop the preset stores
!          (gfortran >= 13 does at -O2), so the kernel sees whatever the previous call
!          left in them.
!
! Built with -DTRACE against an instrumented kernel (kernels.py instrument()), it also
! writes, after the flags, n records of 9 int32 event counts per call (module
! kernel_trace, int64 array ev): 1 solve met tolerance on its last allowed pass, 2 negative
! Secant step, 3 degenerate Secant slope (Qj_0 == Qj), 4 retry (goto 110), 5 search
! abandoned (tries > 4), 6 loop body skipped after a retry, 7 no-flow branch,
! 8 Secant iterations, 9 restart of a collapsed search (degenerate root, patch 0008).
program mc_driver
    use precis
    use muskingcunge_module, only: muskingcungenwm
    use, intrinsic :: ieee_arithmetic
    use, intrinsic :: iso_c_binding, only: c_float
    use, intrinsic :: iso_fortran_env, only: int32
#ifdef TRACE
    use kernel_trace, only: ev
#endif
    implicit none

    interface
        ! T-Route's view of the kernel: the C prototype in pyMCsingleSegStime_NoLoop.h
        ! (all float *, no intents).
        subroutine c_mc(dt, qup, quc, qdp, ql, dx, bw, tw, twcc, n, ncc, cs, s0, velp, &
                depthp, qdc, velc, depthc, ck, cn, X) bind(c, name='c_muskingcungenwm')
            import :: c_float
            real(c_float) :: dt, qup, quc, qdp, ql, dx, bw, tw, twcc, n, ncc, cs, s0
            real(c_float) :: velp, depthp, qdc, velc, depthc, ck, cn, X
        end subroutine c_mc
    end interface

    character(len=4096) :: fin, fout, arg
    character(len=1) :: order, mode
    real(prec) :: preset
    integer :: scribble_seed, n, k, i, u, ios
    real(prec), allocatable :: inp(:, :), out(:, :)
    integer(int32), allocatable :: flags(:)
#ifdef TRACE
    integer(int32), allocatable :: events(:, :)
#endif
    real(prec) :: qdc, velc, depthc, ck, cn, X
    logical :: f_inv, f_div, f_ovf

    call get_command_argument(1, fin)
    call get_command_argument(2, fout)
    call get_command_argument(3, arg); order = arg(1:1)
    call get_command_argument(4, arg); read(arg, *) preset
    call get_command_argument(5, arg); read(arg, *) scribble_seed
    call get_command_argument(6, arg); mode = arg(1:1)
    if (mode /= 'c' .and. mode /= 'f') error stop "MODE must be c or f"

    open(newunit=u, file=trim(fin), access='stream', form='unformatted', status='old', iostat=ios)
    if (ios /= 0) error stop "cannot open cases file"
    read(u) n
    allocate(inp(15, n), out(6, n), flags(n))
#ifdef TRACE
    allocate(events(9, n))
#endif
    read(u) inp
    close(u)

    do k = 1, n
        if (order == 'r') then
            i = n + 1 - k
        else
            i = k
        end if
        if (scribble_seed > 0) call scribble(scribble_seed, i)
        qdc = preset; velc = preset; depthc = preset
        ck = preset; cn = preset; X = preset
        call ieee_set_flag(ieee_all, .false.)
#ifdef TRACE
        ev = 0
#endif
        if (mode == 'c') then
            call c_mc(inp(1, i), inp(2, i), inp(3, i), inp(4, i), inp(5, i), &
                inp(6, i), inp(7, i), inp(8, i), inp(9, i), inp(10, i), inp(11, i), &
                inp(12, i), inp(13, i), inp(14, i), inp(15, i), &
                qdc, velc, depthc, ck, cn, X)
        else
            call muskingcungenwm(inp(1, i), inp(2, i), inp(3, i), inp(4, i), inp(5, i), &
                inp(6, i), inp(7, i), inp(8, i), inp(9, i), inp(10, i), inp(11, i), &
                inp(12, i), inp(13, i), inp(14, i), inp(15, i), &
                qdc, velc, depthc, ck, cn, X)
        end if
        call ieee_get_flag(ieee_invalid, f_inv)
        call ieee_get_flag(ieee_divide_by_zero, f_div)
        call ieee_get_flag(ieee_overflow, f_ovf)
        out(:, i) = [qdc, velc, depthc, ck, cn, X]
        flags(i) = merge(1, 0, f_inv) + merge(2, 0, f_div) + merge(4, 0, f_ovf)
#ifdef TRACE
        events(:, i) = int(ev, int32)
#endif
    end do
    call ieee_set_flag(ieee_all, .false.)

    open(newunit=u, file=trim(fout), access='stream', form='unformatted', status='replace')
    write(u) out
    write(u) flags
#ifdef TRACE
    write(u) events
#endif
    close(u)

contains

    ! Leave case-dependent values on the stack where the kernel's locals will live.
    subroutine scribble(seed, i)
        integer, intent(in) :: seed, i
        real(prec), volatile :: junk(512)
        integer :: j
        do j = 1, size(junk)
            junk(j) = real(mod(seed * 7919 + i * 104729 + j * 31, 2003) - 1001, prec) * 0.37_prec
        end do
    end subroutine scribble

end program mc_driver
