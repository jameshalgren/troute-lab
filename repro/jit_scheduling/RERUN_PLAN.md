# Rerun plan, 2026-10-30: segments, saturation, unequal costs, and the theory

*AI-drafted (Claude), 2026-10-30, at the author's request of that day. Not
reviewed by the author. The study's results and conventions are in [README.md](README.md);
this file records why the study is being rerun and what the rerun must show.*

## The author's framing

> During development, I ran tests on both segments and reaches, but the calculation unit is
> segments, so my first spreadsheets were segment-based. The goal was to maximize core
> saturation, i.e., minimizing the number of idle cores. The spreadsheet experiments showed
> that JIT was better than opportunistic for saturation. But that assumed strict blocking
> between orders or strides of the parallel computation. With that strict blocking, the
> Mississippi still has a 1,163-segment stretch of mainstem that must run on one core at
> the end. JIT doesn't shorten that stretch, but it keeps other work running alongside it
> so that only 5 segments' worth of cycle time at the end has only a single core busy.
> That's good, but does JIT guarantee the minimum idle time? If so, under what conditions?
> If opportunistic scheduling under the same blocking leaves the other cores idle through
> that stretch, what is the performance penalty?
>
> I wondered then, and have since seen, that a purely opportunistic actor-based approach
> can be much faster, especially if it is not naive (in scheduling, a naive policy runs
> whichever calculation is ready first, with no knowledge of its cost or its place in the
> network) during execution. What if we remove the blocking assumptions? At the time, we
> were trying to purely pre-schedule the execution order. If, instead, we let each
> calculation "know" how long it takes, the scheduler can use opportunistic ordering more
> intelligently. The question, then, is what math or computer-science studies confirm or
> relate to this?
>
> A critical part of our specific problem is the irregular structure of river networks.
> There is variation within the networks individually and there is massive variation in
> size and topology between the networks. What happens if we use a different
> representation -- a different "hydrofabric" -- such as the NextGen or GEOGLOWS networks?
> How does a network built with different assumptions of threshold contributing area or
> tributary density affect the parallel computation topology? Also important in our domain
> is the variation in calculation intensity -- a larger flood event will likely take at
> least slightly longer to converge in each calculation. How does that affect our choice of
> distribution of the parallel computation effort?
>
> In summary: We need to think about the difference between reach-based and segment-based
> parallelism. We need to examine both saturation AND performance. (We initially chose
> saturation as a surrogate for performance because our testing and instrumentation
> capacity was less sophisticated.) We also need an expanded research note, summarized as
> an appendix or footnote in the paper, with some of the theoretical background for all of
> this.

Follow-up (the author): rerun item 1 and do item 4 now; do item 2 with the Potomac case;
document item 3 as a next paper.

## Recap of the existing results (AI, 2026-10-30)

From `results/results.csv` of the revised study (Mississippi, by segment, zero overhead).

**Single-core tail.** Pure opportunistic scheduling ends with about 1,120–1,160 cycles on
one core; JIT with 5.

| Cores | First-ready opportunistic | 2020-style rounds | JIT | Longest-path-first |
|---|---:|---:|---:|---:|
| 36 | 1,119 | 1,163 | 5 | 72 |
| 128 | 1,145 | 1,163 | 5 | 103 |
| 1,024 | 1,158 | 1,163 | 5 | 1,161 |

The finish line the author saw in 2020 is real: naive opportunistic scheduling spends the
last ~1,150 cycles on one core. JIT overlaps that stretch with other work.

**Saturation and performance are one objective in this model.** With fixed total work W
and no overhead, idle core-time = P × makespan − W, so minimizing idle cores and minimizing
run time are the same thing. Saturation was an exact stand-in for performance, not a rough
one. What differs between policies is *when* cores sit idle:

| Policy | Idle core-cycles, 36 cores | When cores are idle |
|---|---:|---|
| 2020-style rounds | 92,396 | at the end |
| First-ready opportunistic | 83,324 | at the end |
| JIT | 56,540 (−39% vs rounds) | at the start (about 40% busy early) |
| Longest-path-first | 2,936 | almost never |

**A theory result that may reconcile the two views** (from memory; item 4 verifies it). A
river network is an in-forest: every segment has exactly one downstream. For equal-cost
tasks on an in-forest, Hu (1961) showed that this schedule is optimal: whenever a core is
free, run the ready task farthest from the root. Distance from the root is distance from
the outlet, which is the JIT ordering principle, executed opportunistically, without the
barrier between strides. The study's "longest-path-first" policy is exactly this rule. So
the finding is not that opportunistic beats JIT. It is that the JIT priority was right, and
the per-stride barrier costs the last few percent.

**Reach vs. segment.** Within a timestep a reach is a chain of segments, so the dependency
structure is the same at either granularity. What breaks is JIT measured in *reach hops*:
reaches differ in length, so equal hop counts do not mean equal work. Longest-path-first on
reaches with cost = segments gives exactly the segment result (31,118 cycles at 36 cores),
because its priority uses segment distance. The 2020 segment test measured the right thing,
and a reach-level implementation needs segment-distance priorities.

**Scale footnote (author, 2026-10-30).** The AGU 2020 poster's "over 600 billion"
routing computations per day
([`doc/AGU_Poster.md` L50](https://github.com/NOAA-OWP/t-route/blob/0d512ba026e3b10a432fb707fc80655a6c2f63e2/doc/AGU_Poster.md#L50))
may simply have used the exact segment count; "around 600 billion" is fine for the paper (the 2020 sheet gives
5.79×10¹¹; 5.96×10¹¹ with today's 2,776,734 segments).

## What the rerun must do

1. **Segment-first rerun, saturation emphasis.** Segments are the primary granularity, as
   in 2020; reaches stay as a secondary comparison. For each policy report idle core-time,
   the busy profile over time (where the idle time falls) and the single-core tail, next to
   makespan. Name the policies plainly: 2020 rounds; naive first-ready; JIT strides; JIT
   priority without barriers (Hu's rule, currently "longest-path-first"). Add a JIT variant
   on reaches that orders by segment distance.
2. **Unequal and unknown costs (Potomac).** Measure per-segment secant-iteration counts
   with the instrumented kernel port on the Potomac case in `repro/short_ts_switch/`,
   calm and flood, at several storm sizes. Then compare, under those costs: a schedule
   fixed in advance on assumed equal costs; a cost-aware dynamic scheduler (costs known as
   each unit becomes ready); and work stealing. Flood cost is spatially clustered, which
   is the hard case. T-Route computes many timesteps per subnetwork call, so per-unit cost
   averages over the run window; whether that blunts the flood effect is part of the
   measurement.
3. **Other hydrofabrics: next paper.** Documented as a topic for a later paper.
4. **Literature review.** In-tree scheduling theory and hydrology-specific parallel
   routing, every citation verified, for an appendix or footnote and a docs page.
