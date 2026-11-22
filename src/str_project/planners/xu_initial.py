"""Valid initial schedule construction for Xu & Parnas (1990), Appendix 1."""

from __future__ import annotations

from dataclasses import dataclass

from ..model import Schedule, SchedulingInstance, UnitPlacement
from .xu_relations import adjusted_releases, check_relations


@dataclass(frozen=True)
class InitialScheduleResult:
    ok: bool
    schedule: Schedule | None
    adjusted_releases: dict[str, int]
    starts: dict[str, int]
    finishes: dict[str, int]
    idle_intervals: tuple[tuple[int, int], ...]
    pc_closure: frozenset[tuple[str, str]]
    reason: str | None = None


def build_valid_initial_schedule(
    instance: SchedulingInstance,
    pc: set[tuple[str, str]] | frozenset[tuple[str, str]],
    ex: set[tuple[str, str]] | frozenset[tuple[str, str]],
    pm: set[tuple[str, str]] | frozenset[tuple[str, str]],
) -> InitialScheduleResult:
    """Build a valid initial schedule respecting r', PC, EX, and PM (without deadline filtering).

    Selection rule among eligible non-preempted candidates:
    1. Earliest deadline d[j]
    2. Largest original computation demand c[j] (NOT remaining time)
    3. Deterministic tie-break by segment_id (lexicographic)
    """
    rel_check = check_relations(pc, ex, pm)
    if not rel_check.consistent:
        return InitialScheduleResult(
            ok=False,
            schedule=None,
            adjusted_releases={},
            starts={},
            finishes={},
            idle_intervals=(),
            pc_closure=rel_check.pc_closure,
            reason=f"inconsistent_relations:{rel_check.reason}",
        )

    pc_c = rel_check.pc_closure
    r_adj = adjusted_releases(instance, pc_c)
    seg_map = instance.segment_map()
    seg_ids = [s.id for s in instance.segments]

    preds: dict[str, set[str]] = {sid: set() for sid in seg_ids}
    for u, v in pc_c:
        if u in seg_map and v in seg_map:
            preds[v].add(u)

    excluded_by: dict[str, set[str]] = {sid: set() for sid in seg_ids}
    excludes_any: set[str] = set()
    for u, v in ex:
        if u in seg_map and v in seg_map and u != v:
            excluded_by[v].add(u)
            excludes_any.add(u)

    remaining: dict[str, int] = {s.id: s.execution_units for s in instance.segments}
    starts: dict[str, int] = {}
    finishes: dict[str, int] = {}
    units: list[UnitPlacement] = []
    idle_intervals: list[tuple[int, int]] = []

    incomplete = set(seg_ids)
    t = 0

    while incomplete:
        # 1. Determine eligible segments at tick t
        eligible: list[str] = []
        for j in incomplete:
            if t < r_adj[j]:
                continue
            if any(p in incomplete for p in preds[j]):
                continue
            # Check directional EX(i, j): no started incomplete i (s[i] < t) that excludes j
            # unless j already started strictly before i (s[j] < s[i]).
            blocked = False
            s_j = starts.get(j)
            for i in excluded_by[j]:
                if i in incomplete and i in starts and starts[i] < t:
                    if s_j is None or starts[i] < s_j:
                        blocked = True
                        break
            if not blocked:
                eligible.append(j)

        if not eligible:
            # Advance to earliest future adjusted release among incomplete segments
            future_releases = [r_adj[j] for j in incomplete if r_adj[j] > t]
            if not future_releases:
                return InitialScheduleResult(
                    ok=False,
                    schedule=None,
                    adjusted_releases=r_adj,
                    starts=starts,
                    finishes=finishes,
                    idle_intervals=tuple(idle_intervals),
                    pc_closure=pc_c,
                    reason="deadlock_no_eligible_and_no_future_release",
                )
            next_t = min(future_releases)
            idle_intervals.append((t, next_t))
            t = next_t
            continue

        # 2. Apply PM priority filter: remove j if some other eligible i has PM(i, j)
        eligible_set = set(eligible)
        candidates = [
            j
            for j in eligible
            if not any((i, j) in pm for i in eligible_set if i != j)
        ]
        if not candidates:
            return InitialScheduleResult(
                ok=False,
                schedule=None,
                adjusted_releases=r_adj,
                starts=starts,
                finishes=finishes,
                idle_intervals=tuple(idle_intervals),
                pc_closure=pc_c,
                reason="deadlock_pm_cycle_among_eligible_segments",
            )

        # 3. Choose earliest deadline; tie-break by LARGEST original c[j]; then segment_id
        chosen = min(
            candidates,
            key=lambda sid: (
                seg_map[sid].deadline,
                -seg_map[sid].execution_units,
                sid,
            ),
        )

        was_unstarted = chosen not in starts
        if was_unstarted:
            starts[chosen] = t

        # Determine how many consecutive ticks chosen can execute before next event
        next_release_candidates = [r_adj[u] for u in incomplete if r_adj[u] > t]
        next_event = t + remaining[chosen]
        if next_release_candidates:
            next_event = min(next_event, min(next_release_candidates))

        step = next_event - t
        # If chosen just started and excludes other segments, re-evaluate after 1 tick
        # because s[chosen] < t+1 may remove segments from eligible and change PM filtering.
        if was_unstarted and step > 1 and chosen in excludes_any:
            step = 1

        orig_c = seg_map[chosen].execution_units
        done_so_far = orig_c - remaining[chosen]
        for offset in range(step):
            units.append(
                UnitPlacement(
                    segment_id=chosen,
                    unit_index=done_so_far + offset + 1,
                    start_tick=t + offset,
                )
            )

        remaining[chosen] -= step
        t += step
        if remaining[chosen] == 0:
            finishes[chosen] = t
            incomplete.remove(chosen)

    schedule = Schedule(units=tuple(units))
    return InitialScheduleResult(
        ok=True,
        schedule=schedule,
        adjusted_releases=r_adj,
        starts=starts,
        finishes=finishes,
        idle_intervals=tuple(idle_intervals),
        pc_closure=pc_c,
        reason=None,
    )
