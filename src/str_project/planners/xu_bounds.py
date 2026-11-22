"""Critical segment, Z[i], G1/G2 expansion sets, and lower bounds for Xu & Parnas (1990)."""

from __future__ import annotations

from dataclasses import dataclass

from ..model import Schedule, SchedulingInstance


class LowerBoundInvariantError(RuntimeError):
    """Raised if an expected Xu & Parnas lower-bound set is unexpectedly empty."""


@dataclass(frozen=True)
class ExpandSets:
    latest_segment: str
    lmax: int
    z_set: frozenset[str]
    g1: frozenset[str]
    g2: frozenset[str]


def latest_segment(
    instance: SchedulingInstance,
    schedule: Schedule,
) -> tuple[str, int]:
    """Identify the critical segment j with maximum lateness (tie-break: latest completion).

    Returns (segment_id, Lmax).
    """
    bounds = schedule.segment_bounds()
    seg_map = instance.segment_map()
    best_seg = max(
        seg_map.keys(),
        key=lambda sid: (
            bounds[sid][1] - seg_map[sid].deadline,
            bounds[sid][1],
            sid,
        ),
    )
    lmax = bounds[best_seg][1] - seg_map[best_seg].deadline
    return best_seg, lmax


def compute_Z(
    schedule: Schedule,
    adjusted_release: dict[str, int],
    target_segment: str,
) -> set[str]:
    """Compute Z[i] by fixed point per Xu & Parnas (1990), Section IV, p. 364.

    Initially Z = {i}. Add segment k not in Z whenever there exists l in Z such that:
      (e[k] == s[l] and there exists l' in Z with r'[l'] < e[k])
      OR
      (s[l] < e[k] < e[l])

    Note: The existential condition `exists l' in Z with r'[l'] < e[k]` ensures k is
    included iff at least one segment in Z was already released before k finished
    (meaning k genuinely delays Z rather than finishing before Z's earliest release).
    """
    bounds = schedule.segment_bounds()
    z_set: set[str] = {target_segment}
    all_segs = list(bounds.keys())

    changed = True
    while changed:
        changed = False
        for k in all_segs:
            if k in z_set:
                continue
            _, e_k = bounds[k]
            should_add = False
            for l in z_set:
                s_l, e_l = bounds[l]
                if e_k == s_l and any(adjusted_release[lp] < e_k for lp in z_set):
                    should_add = True
                    break
                if s_l < e_k < e_l:
                    should_add = True
                    break
            if should_add:
                z_set.add(k)
                changed = True

    return z_set


def _unit_ticks_by_segment(schedule: Schedule) -> dict[str, tuple[int, ...]]:
    by_seg: dict[str, list[int]] = {}
    for u in schedule.units:
        by_seg.setdefault(u.segment_id, []).append(u.start_tick)
    return {sid: tuple(sorted(ticks)) for sid, ticks in by_seg.items()}


def has_unit_in_interval(
    unit_ticks: dict[str, tuple[int, ...]],
    segment_id: str,
    start_inclusive: int,
    end_exclusive: int,
) -> bool:
    """Return True if segment_id executes at least one unit during [start_inclusive, end_exclusive)."""
    return any(start_inclusive <= tick < end_exclusive for tick in unit_ticks.get(segment_id, ()))


def compute_expand_sets(
    instance: SchedulingInstance,
    schedule: Schedule,
    adjusted_release: dict[str, int],
    pc: set[tuple[str, str]] | frozenset[tuple[str, str]],
    ex: set[tuple[str, str]] | frozenset[tuple[str, str]],
    pm: set[tuple[str, str]] | frozenset[tuple[str, str]],
    latest: str | None = None,
) -> ExpandSets:
    """Compute Z[j], G1, and G2 for the critical segment j (Section IV, p. 364)."""
    bounds = schedule.segment_bounds()
    seg_map = instance.segment_map()
    if latest is None:
        j, lmax = latest_segment(instance, schedule)
    else:
        j = latest
        lmax = bounds[j][1] - seg_map[j].deadline

    z_j = compute_Z(schedule, adjusted_release, j)
    unit_ticks = _unit_ticks_by_segment(schedule)
    e_j = bounds[j][1]
    d_j = seg_map[j].deadline

    g1: set[str] = set()
    g2: set[str] = set()

    for i in z_j:
        if i == j:
            continue
        if not (d_j < seg_map[i].deadline):
            continue
        if (i, j) in pc or (i, j) in pm:
            continue

        if (i, j) in ex:
            g1.add(i)
        else:
            s_i = bounds[i][0]
            # Check that no segment l executing in [s[i], e[j]) has PC(i, l) or PM(i, l)
            conflict = any(
                has_unit_in_interval(unit_ticks, l_seg, s_i, e_j)
                and ((i, l_seg) in pc or (i, l_seg) in pm)
                for l_seg in seg_map
                if l_seg != i
            )
            if not conflict:
                g2.add(i)

    return ExpandSets(
        latest_segment=j,
        lmax=lmax,
        z_set=frozenset(z_j),
        g1=frozenset(g1),
        g2=frozenset(g2),
    )


def compute_lower_bound(
    instance: SchedulingInstance,
    schedule: Schedule,
    adjusted_release: dict[str, int],
    pc: set[tuple[str, str]] | frozenset[tuple[str, str]],
    ex: set[tuple[str, str]] | frozenset[tuple[str, str]],
    pm: set[tuple[str, str]] | frozenset[tuple[str, str]],
) -> int:
    """Compute the Xu & Parnas (1990) branch lower bound (pp. 364-365).

    For each segment i:
      K[i] = {k in Z[i] : k != i, d[i] < d[k], not PC(k, i), not PM(k, i)}
      if K[i] empty: LB[i] = e[i] - d[i]
      else: LB[i] = e[i] + min(GAP[k, i] - d[k] : k in K[i])
      LB1[i] = min(LB[i], e[i] - d[i])
      LB2[i] = r'[i] + c[i] - d[i]
    lowerbound = max(max(LB1[i], LB2[i]) for all i)
    """
    bounds = schedule.segment_bounds()
    seg_map = instance.segment_map()

    best_lb: int | None = None

    for seg in instance.segments:
        i = seg.id
        s_i, e_i = bounds[i]
        d_i = seg.deadline
        lateness_i = e_i - d_i
        z_i = compute_Z(schedule, adjusted_release, i)

        k_set = [
            k
            for k in z_i
            if k != i
            and d_i < seg_map[k].deadline
            and (k, i) not in pc
            and (k, i) not in pm
        ]

        if not k_set:
            lb_i = lateness_i
        else:
            terms: list[int] = []
            for k in k_set:
                if (k, i) not in ex:
                    gap_ki = 0
                else:
                    s_k = bounds[k][0]
                    gap_candidates = [
                        adjusted_release[l]
                        for l in z_i
                        if l != k
                        and s_k < bounds[l][0] <= s_i
                        and (k, l) not in pc
                    ]
                    if not gap_candidates:
                        raise LowerBoundInvariantError(
                            f"Empty GAP candidate set for (k={k}, i={i}) in Z[{i}]={sorted(z_i)}; "
                            f"bounds={bounds}, r'={adjusted_release}"
                        )
                    gap_ki = max(0, -s_k + min(gap_candidates))
                terms.append(gap_ki - seg_map[k].deadline)
            lb_i = e_i + min(terms)

        lb1_i = min(lb_i, lateness_i)
        lb2_i = adjusted_release[i] + seg.execution_units - d_i
        cand_lb = max(lb1_i, lb2_i)
        if best_lb is None or cand_lb > best_lb:
            best_lb = cand_lb

    if best_lb is None:
        raise LowerBoundInvariantError("Instance has no segments.")
    return best_lb
