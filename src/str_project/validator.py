"""Independent schedule validator (does not depend on Z3 or Xu & Parnas routines)."""

from __future__ import annotations

from .model import Schedule, SchedulingInstance, ValidationReport


def validate_schedule(
    instance: SchedulingInstance,
    schedule: Schedule,
    require_deadlines: bool = True,
) -> ValidationReport:
    """Independently verify all 9 scheduling rules defined in Section 5.

    Rules checked:
    1. Every expected (segment_id, unit_index) in 1..C_i appears exactly once; no extra units.
    2. All start_tick values are non-negative integers.
    3. Distinct units never share the same start_tick (single processor capacity).
    4. Within each segment, x[i, k+1] >= x[i, k] + 1.
    5. s[i] = x[i, 1] and f[i] = x[i, C_i] + 1.
    6. s[i] >= release[i].
    7. Process segment order and all PRECEDE(i, j) relations hold: f[i] <= s[j].
    8. For every directional (i, j) in EXCLUDES: s[i] < s[j] implies f[i] <= s[j].
    9. Deadlines: f[i] <= deadline[i] (checked for feasibility; required if require_deadlines=True).
    """
    seg_map = instance.segment_map()
    structural_errors: list[str] = []
    deadline_errors: list[str] = []

    expected_units: set[tuple[str, int]] = {
        (seg.id, k)
        for seg in instance.segments
        for k in range(1, seg.execution_units + 1)
    }

    seen_units: dict[tuple[str, int], int] = {}
    used_ticks: dict[int, tuple[str, int]] = {}
    by_segment: dict[str, dict[int, int]] = {seg.id: {} for seg in instance.segments}

    # Rules 1, 2, 3
    for u in schedule.units:
        key = (u.segment_id, u.unit_index)
        if isinstance(u.unit_index, bool) or not isinstance(u.unit_index, int):
            structural_errors.append(
                f"Unit index for {u.segment_id!r} must be int, got {u.unit_index!r}."
            )
            continue
        if isinstance(u.start_tick, bool) or not isinstance(u.start_tick, int):
            structural_errors.append(
                f"Start tick for {key} must be int, got {u.start_tick!r}."
            )
            continue
        if u.start_tick < 0:
            structural_errors.append(
                f"Unit {key} has negative start_tick={u.start_tick}."
            )
        if key not in expected_units:
            structural_errors.append(f"Unexpected unit {key} not in instance.")
            continue
        if key in seen_units:
            structural_errors.append(f"Duplicate unit {key}.")
            continue
        seen_units[key] = u.start_tick
        by_segment[u.segment_id][u.unit_index] = u.start_tick

        if u.start_tick in used_ticks:
            other = used_ticks[u.start_tick]
            structural_errors.append(
                f"Processor conflict at tick {u.start_tick}: {other} and {key}."
            )
        else:
            used_ticks[u.start_tick] = key

    missing = sorted(expected_units - set(seen_units.keys()))
    if missing:
        structural_errors.append(f"Missing expected units: {missing}.")

    # Rules 4 & 5: intra-segment ordering and bounds
    bounds: dict[str, tuple[int, int]] = {}
    for seg in instance.segments:
        unit_ticks = by_segment[seg.id]
        if len(unit_ticks) != seg.execution_units:
            continue
        for k in range(1, seg.execution_units):
            if unit_ticks[k + 1] < unit_ticks[k] + 1:
                structural_errors.append(
                    f"Intra-segment ordering violated for {seg.id}: "
                    f"x[{seg.id},{k+1}]={unit_ticks[k+1]} < x[{seg.id},{k}]+1={unit_ticks[k]+1}."
                )
        s_i = unit_ticks[1]
        f_i = unit_ticks[seg.execution_units] + 1
        bounds[seg.id] = (s_i, f_i)

        # Rule 6: release time
        if s_i < seg.release:
            structural_errors.append(
                f"Release violated for {seg.id}: s={s_i} < release={seg.release}."
            )

        # Rule 9: deadline
        if f_i > seg.deadline:
            deadline_errors.append(
                f"Deadline violated for {seg.id}: f={f_i} > deadline={seg.deadline} "
                f"(lateness={f_i - seg.deadline})."
            )

    # Rule 7: process order + all precedences
    process_pairs: set[tuple[str, str]] = set()
    for proc in instance.processes:
        for a, b in zip(proc.segments, proc.segments[1:]):
            process_pairs.add((a, b))
    all_precedences = sorted(set(instance.precedence) | process_pairs)
    for src, dst in all_precedences:
        if src in bounds and dst in bounds:
            f_src = bounds[src][1]
            s_dst = bounds[dst][0]
            if f_src > s_dst:
                structural_errors.append(
                    f"Precedence violated for ({src} -> {dst}): f[{src}]={f_src} > s[{dst}]={s_dst}."
                )

    # Rule 8: directional EXCLUDES: s[i] < s[j] implies f[i] <= s[j]
    for src, dst in instance.exclusion:
        if src in bounds and dst in bounds:
            s_src, f_src = bounds[src]
            s_dst, _ = bounds[dst]
            if s_src < s_dst and f_src > s_dst:
                structural_errors.append(
                    f"Exclusion violated for ({src} EXCLUDES {dst}): "
                    f"s[{src}]={s_src} < s[{dst}]={s_dst} but f[{src}]={f_src} > s[{dst}]={s_dst}."
                )

    valid = len(structural_errors) == 0
    feasible = valid and len(deadline_errors) == 0
    errors = tuple(
        structural_errors + (deadline_errors if require_deadlines else [])
    )

    logical_lmax: int | None = None
    if len(bounds) == len(instance.segments):
        logical_lmax = max(bounds[seg.id][1] - seg.deadline for seg in instance.segments)

    return ValidationReport(
        valid=valid,
        feasible=feasible,
        require_deadlines=require_deadlines,
        errors=errors,
        logical_lmax=logical_lmax,
        segment_bounds=bounds,
    )
