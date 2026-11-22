"""Exhaustive enumerative oracle for tiny scheduling instances.

Used strictly as an independent ground-truth test oracle to audit both
feasible and infeasible classifications as well as optimal Lmax on tiny cases.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Schedule, SchedulingInstance, UnitPlacement
from .validator import validate_schedule


@dataclass(frozen=True)
class OracleResult:
    feasible: bool
    schedule: Schedule | None
    optimal_lmax: int | None
    states_visited: int
    reason: str


def _has_precedence_cycle(instance: SchedulingInstance) -> bool:
    adj: dict[str, set[str]] = {s.id: set() for s in instance.segments}
    for a, b in instance.precedence:
        adj[a].add(b)
    # Standard 3-color DFS
    color: dict[str, int] = {s.id: 0 for s in instance.segments}

    def dfs(u: str) -> bool:
        color[u] = 1
        for v in adj[u]:
            if color[v] == 1:
                return True
            if color[v] == 0 and dfs(v):
                return True
        color[u] = 2
        return False

    return any(color[s.id] == 0 and dfs(s.id) for s in instance.segments)


def solve_oracle(
    instance: SchedulingInstance,
    *,
    objective: str | None = None,
    max_total_units: int = 12,
    max_states: int = 2_000_000,
) -> OracleResult:
    """Enumerate valid schedules on tiny instances to certify ground truth.

    Supports both 'feasibility' (find any schedule with Lmax <= 0) and
    'min_lmax' (find globally minimum Lmax over all valid schedules).
    """
    obj = objective or instance.objective
    if obj not in {"feasibility", "min_lmax"}:
        raise ValueError(f"Unsupported objective for oracle: {obj!r}")

    total_units = instance.total_units()
    if total_units > max_total_units:
        raise ValueError(
            f"Instance has {total_units} units, exceeding oracle limit {max_total_units}."
        )

    if _has_precedence_cycle(instance):
        return OracleResult(
            feasible=False,
            schedule=None,
            optimal_lmax=None,
            states_visited=0,
            reason="cyclic_precedence",
        )

    segs = instance.segments
    n = len(segs)
    idx_of = {seg.id: i for i, seg in enumerate(segs)}
    releases = [seg.release for seg in segs]
    demands = [seg.execution_units for seg in segs]
    deadlines = [seg.deadline for seg in segs]

    preds: list[tuple[int, ...]] = [tuple() for _ in range(n)]
    pred_sets: list[set[int]] = [set() for _ in range(n)]
    for a, b in instance.precedence:
        pred_sets[idx_of[b]].add(idx_of[a])
    preds = [tuple(sorted(s)) for s in pred_sets]

    # excluded_by[j] = set of i such that (i, j) in EX (i excludes j)
    excluded_by: list[tuple[int, ...]] = [tuple() for _ in range(n)]
    excl_sets: list[set[int]] = [set() for _ in range(n)]
    for a, b in instance.exclusion:
        excl_sets[idx_of[b]].add(idx_of[a])
    excluded_by = [tuple(sorted(s)) for s in excl_sets]

    if obj == "feasibility":
        for seg in segs:
            if seg.release + seg.execution_units > seg.deadline:
                return OracleResult(
                    feasible=False,
                    schedule=None,
                    optimal_lmax=None,
                    states_visited=0,
                    reason="individual_deadline_impossible",
                )
        horizon = max(deadlines)
        if horizon < total_units:
            return OracleResult(
                feasible=False,
                schedule=None,
                optimal_lmax=None,
                states_visited=0,
                reason="total_demand_exceeds_max_deadline",
            )
    else:
        # Once t >= max(release), idling never improves Lmax.
        horizon = max(releases) + total_units

    best_lmax: int | None = None
    best_units: list[UnitPlacement] | None = None
    states_visited = 0

    done_units = [0] * n
    started_at: list[int | None] = [None] * n
    current_path: list[UnitPlacement] = []

    def backtrack(t: int, remaining_total: int, current_max_lateness: int | None) -> bool:
        nonlocal best_lmax, best_units, states_visited
        states_visited += 1
        if states_visited > max_states:
            raise RuntimeError(
                f"Oracle exceeded max_states={max_states} on {instance.instance_id}."
            )

        if remaining_total == 0:
            assert current_max_lateness is not None
            if obj == "feasibility":
                if current_max_lateness <= 0:
                    best_lmax = current_max_lateness
                    best_units = list(current_path)
                    return True
                return False
            if best_lmax is None or current_max_lateness < best_lmax:
                best_lmax = current_max_lateness
                best_units = list(current_path)
            return False

        if t + remaining_total > horizon:
            return False

        # Pruning on remaining segments
        if obj == "feasibility":
            for i in range(n):
                rem_i = demands[i] - done_units[i]
                if rem_i > 0:
                    earliest_start = max(t, releases[i])
                    if earliest_start + rem_i > deadlines[i]:
                        return False
        elif best_lmax is not None:
            for i in range(n):
                rem_i = demands[i] - done_units[i]
                if rem_i > 0:
                    earliest_finish = max(t, releases[i]) + rem_i
                    if earliest_finish - deadlines[i] >= best_lmax:
                        return False

        # Collect eligible segments at tick t
        eligible: list[int] = []
        for j in range(n):
            if done_units[j] >= demands[j]:
                continue
            if t < releases[j]:
                continue
            if any(done_units[p] < demands[p] for p in preds[j]):
                continue
            # Directional EXCLUDES: if i started (< t), is incomplete, and EX(i, j),
            # then j cannot start now (s[i] < s[j] would imply f[i] <= s[j]).
            # Note: if j already started BEFORE i (s[j] < s[i]), EX(i, j) does NOT
            # forbid j from resuming!
            blocked = False
            for i in excluded_by[j]:
                if i == j:
                    continue
                s_i = started_at[i]
                if s_i is not None and done_units[i] < demands[i]:
                    # If j has not started yet, starting j now gives s[i] < s[j]
                    # while i is incomplete (f[i] > t = s[j]), violating EX(i, j).
                    if started_at[j] is None:
                        blocked = True
                        break
                    # If j already started with s[i] < s[j], it would already have violated
                    # EX(i, j) earlier; if s[j] < s[i], EX(i, j) allows j to resume!
            if not blocked:
                eligible.append(j)

        # Try scheduling each eligible segment
        for j in eligible:
            prev_started = started_at[j]
            if prev_started is None:
                started_at[j] = t
            done_units[j] += 1
            unit_idx = done_units[j]
            current_path.append(UnitPlacement(segs[j].id, unit_idx, t))

            new_max_lateness = current_max_lateness
            if done_units[j] == demands[j]:
                lateness_j = (t + 1) - deadlines[j]
                if new_max_lateness is None or lateness_j > new_max_lateness:
                    new_max_lateness = lateness_j

            pruned = False
            if new_max_lateness is not None:
                if obj == "feasibility" and new_max_lateness > 0:
                    pruned = True
                elif obj == "min_lmax" and best_lmax is not None and new_max_lateness >= best_lmax:
                    pruned = True

            if not pruned:
                if backtrack(t + 1, remaining_total - 1, new_max_lateness):
                    return True

            current_path.pop()
            done_units[j] -= 1
            started_at[j] = prev_started

        # Try leaving tick t idle (only useful if some incomplete segment is not yet released,
        # or if no segment is eligible at tick t).
        has_future_release = any(
            done_units[i] < demands[i] and releases[i] > t for i in range(n)
        )
        if has_future_release:
            if not eligible:
                # Jump directly to the earliest future release
                next_t = min(
                    releases[i]
                    for i in range(n)
                    if done_units[i] < demands[i] and releases[i] > t
                )
                if backtrack(next_t, remaining_total, current_max_lateness):
                    return True
            else:
                if backtrack(t + 1, remaining_total, current_max_lateness):
                    return True

        return False

    backtrack(0, total_units, None)

    if best_units is None:
        return OracleResult(
            feasible=False,
            schedule=None,
            optimal_lmax=None,
            states_visited=states_visited,
            reason="exhausted_search_space_no_schedule",
        )

    schedule = Schedule(units=tuple(best_units))
    report = validate_schedule(
        instance, schedule, require_deadlines=(obj == "feasibility")
    )
    if not report.ok:
        raise AssertionError(
            f"Oracle produced schedule that failed validator: {report.errors}"
        )

    return OracleResult(
        feasible=(best_lmax is not None and best_lmax <= 0),
        schedule=schedule,
        optimal_lmax=best_lmax,
        states_visited=states_visited,
        reason="feasible_found" if (best_lmax is not None and best_lmax <= 0) else "optimal_found_positive_lmax",
    )
