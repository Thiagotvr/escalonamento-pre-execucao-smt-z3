"""SMT/Z3 pre-run-time scheduling planner faithful to Xu & Parnas (1990).

Supports:
- objective='feasibility': pure QF_LIA satisfiability via z3.Solver.
- objective='min_lmax': exact Lmax minimization via z3.Optimize.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import z3

from ..model import (
    PlanningLimits,
    PlanningResult,
    Schedule,
    SchedulingInstance,
    UnitPlacement,
    collect_versions,
)
from ..validator import validate_schedule


def _stats_to_dict(stats: Any) -> dict[str, int | float]:
    out: dict[str, int | float] = {}
    try:
        for key in stats.keys():
            val = stats.get_key_value(key)
            if isinstance(val, (int, float)):
                out[str(key)] = val
    except Exception:
        pass
    return out


def _classify_unknown(reason: str) -> str:
    lowered = reason.lower()
    if "timeout" in lowered or "canceled" in lowered or "interrupted" in lowered:
        return "timeout"
    return "unknown"


def _has_precedence_cycle(instance: SchedulingInstance) -> bool:
    adj: dict[str, set[str]] = {s.id: set() for s in instance.segments}
    for a, b in instance.precedence:
        adj[a].add(b)
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


def plan_smt_z3(
    instance: SchedulingInstance,
    limits: PlanningLimits | None = None,
    *,
    objective: str | None = None,
) -> PlanningResult:
    """Solve the scheduling instance using SMT/Z3."""
    lim = limits or PlanningLimits()
    obj = objective or instance.objective
    versions = collect_versions()
    total_start = time.perf_counter_ns()

    if obj not in {"feasibility", "min_lmax"}:
        total_end = time.perf_counter_ns()
        return PlanningResult(
            instance_id=instance.instance_id,
            instance_hash=instance.instance_hash(),
            planner="smt-z3",
            objective=obj,
            status="invalid_input",
            schedule=None,
            logical_lmax=None,
            reason=f"Unsupported objective: {obj!r}",
            preprocessing_ns=0,
            model_build_ns=0,
            search_ns=0,
            total_planning_ns=total_end - total_start,
            nodes_generated=None,
            nodes_expanded=None,
            lower_bound=None,
            versions=versions,
        )

    prep_start = time.perf_counter_ns()
    # Dedicated fresh Z3 Context per instance for strict isolation across runs
    ctx = z3.Context()
    prep_end = time.perf_counter_ns()

    build_start = time.perf_counter_ns()
    if obj == "feasibility":
        solver: Any = z3.Solver(ctx=ctx)
    else:
        solver = z3.Optimize(ctx=ctx)

    x_vars: dict[tuple[str, int], Any] = {}
    all_x: list[Any] = []
    s_expr: dict[str, Any] = {}
    f_expr: dict[str, Any] = {}

    for seg in instance.segments:
        for k in range(1, seg.execution_units + 1):
            var = z3.Int(f"x_{seg.id}_{k}", ctx=ctx)
            x_vars[(seg.id, k)] = var
            all_x.append(var)
            solver.add(var >= 0)
        for k in range(1, seg.execution_units):
            solver.add(x_vars[(seg.id, k + 1)] >= x_vars[(seg.id, k)] + 1)

        s_i = x_vars[(seg.id, 1)]
        f_i = x_vars[(seg.id, seg.execution_units)] + 1
        s_expr[seg.id] = s_i
        f_expr[seg.id] = f_i

        solver.add(s_i >= seg.release)
        if obj == "feasibility":
            solver.add(f_i <= seg.deadline)

    # Single processor capacity: all unit start ticks are pairwise distinct
    solver.add(z3.Distinct(*all_x))

    # Precedence constraints (including process segment order)
    for src, dst in instance.precedence:
        solver.add(f_expr[src] <= s_expr[dst])

    # Directional exclusion constraints: (s[i] < s[j]) => (f[i] <= s[j])
    for src, dst in instance.exclusion:
        solver.add(z3.Implies(s_expr[src] < s_expr[dst], f_expr[src] <= s_expr[dst]))

    l_var: Any = None
    min_handle: Any = None
    if obj == "min_lmax":
        l_var = z3.Int("Lmax", ctx=ctx)
        for seg in instance.segments:
            solver.add(l_var >= f_expr[seg.id] - seg.deadline)
        min_handle = solver.minimize(l_var)

    # Configure Z3 query timeout in milliseconds
    if lim.timeout_ms is not None and lim.timeout_ms >= 0:
        # Z3 treats timeout=0 as unlimited; handle 0 explicitly as immediate timeout
        if lim.timeout_ms > 0:
            solver.set("timeout", int(lim.timeout_ms))

    build_end = time.perf_counter_ns()

    if lim.save_smt2_path:
        smt_path = Path(lim.save_smt2_path)
        smt_path.parent.mkdir(parents=True, exist_ok=True)
        smt_text = solver.to_smt2() if obj == "feasibility" else solver.sexpr()
        smt_path.write_text(smt_text, encoding="utf-8")

    # Enforce explicit zero-timeout guard (Z3 interprets timeout=0 as no limit)
    if lim.timeout_ms is not None and lim.timeout_ms == 0:
        total_end = time.perf_counter_ns()
        return PlanningResult(
            instance_id=instance.instance_id,
            instance_hash=instance.instance_hash(),
            planner="smt-z3",
            objective=obj,
            status="timeout",
            schedule=None,
            logical_lmax=None,
            reason="timeout_ms_zero_limit_exceeded",
            preprocessing_ns=prep_end - prep_start,
            model_build_ns=build_end - build_start,
            search_ns=0,
            total_planning_ns=total_end - total_start,
            nodes_generated=None,
            nodes_expanded=None,
            lower_bound=None,
            versions=versions,
            details={"z3_reason_unknown": "timeout"},
        )

    search_start = time.perf_counter_ns()
    check_res = solver.check()
    search_end = time.perf_counter_ns()
    z3_stats = _stats_to_dict(solver.statistics())

    if check_res == z3.unsat:
        reason = (
            "z3_unsat_cyclic_precedence"
            if _has_precedence_cycle(instance)
            else "z3_unsat_faithful_model"
        )
        total_end = time.perf_counter_ns()
        return PlanningResult(
            instance_id=instance.instance_id,
            instance_hash=instance.instance_hash(),
            planner="smt-z3",
            objective=obj,
            status="infeasible",
            schedule=None,
            logical_lmax=None,
            reason=reason,
            preprocessing_ns=prep_end - prep_start,
            model_build_ns=build_end - build_start,
            search_ns=search_end - search_start,
            total_planning_ns=total_end - total_start,
            nodes_generated=None,
            nodes_expanded=None,
            lower_bound=None,
            versions=versions,
            details={"z3_statistics": z3_stats},
        )

    if check_res == z3.unknown:
        unknown_reason = str(solver.reason_unknown())
        status = _classify_unknown(unknown_reason)
        total_end = time.perf_counter_ns()
        return PlanningResult(
            instance_id=instance.instance_id,
            instance_hash=instance.instance_hash(),
            planner="smt-z3",
            objective=obj,
            status=status,
            schedule=None,
            logical_lmax=None,
            reason=f"z3_{status}:{unknown_reason}",
            preprocessing_ns=prep_end - prep_start,
            model_build_ns=build_end - build_start,
            search_ns=search_end - search_start,
            total_planning_ns=total_end - total_start,
            nodes_generated=None,
            nodes_expanded=None,
            lower_bound=None,
            versions=versions,
            details={
                "z3_reason_unknown": unknown_reason,
                "z3_statistics": z3_stats,
            },
        )

    # check_res == z3.sat
    model = solver.model()
    units: list[UnitPlacement] = []
    for seg in instance.segments:
        for k in range(1, seg.execution_units + 1):
            val = model.eval(x_vars[(seg.id, k)], model_completion=True).as_long()
            units.append(UnitPlacement(segment_id=seg.id, unit_index=k, start_tick=int(val)))

    schedule = Schedule(units=tuple(units)).sorted_units()
    schedule_obj = Schedule(units=schedule)

    val_report = validate_schedule(
        instance,
        schedule_obj,
        require_deadlines=(obj == "feasibility"),
    )
    if not val_report.ok:
        total_end = time.perf_counter_ns()
        return PlanningResult(
            instance_id=instance.instance_id,
            instance_hash=instance.instance_hash(),
            planner="smt-z3",
            objective=obj,
            status="implementation_error",
            schedule=schedule_obj,
            logical_lmax=val_report.logical_lmax,
            reason=f"z3_schedule_failed_validation: {'; '.join(val_report.errors)}",
            preprocessing_ns=prep_end - prep_start,
            model_build_ns=build_end - build_start,
            search_ns=search_end - search_start,
            total_planning_ns=total_end - total_start,
            nodes_generated=None,
            nodes_expanded=None,
            lower_bound=None,
            versions=versions,
            validation=val_report,
            details={"z3_statistics": z3_stats},
        )

    lmax = val_report.logical_lmax
    lower_bound: int | None = None
    details: dict[str, Any] = {"z3_statistics": z3_stats}

    if obj == "min_lmax":
        opt_val = model.eval(l_var, model_completion=True).as_long()
        lower_bound = int(opt_val)
        details["optimal_certified"] = True
        details["z3_objective_lower"] = str(solver.lower(min_handle))
        details["z3_objective_upper"] = str(solver.upper(min_handle))
        status = "feasible" if (lmax is not None and lmax <= 0) else "infeasible"
        reason = (
            "z3_optimal_feasible"
            if status == "feasible"
            else "z3_optimal_positive_lmax_infeasible"
        )
    else:
        status = "feasible"
        reason = "z3_sat_verified"

    total_end = time.perf_counter_ns()
    return PlanningResult(
        instance_id=instance.instance_id,
        instance_hash=instance.instance_hash(),
        planner="smt-z3",
        objective=obj,
        status=status,
        schedule=schedule_obj,
        logical_lmax=lmax,
        reason=reason,
        preprocessing_ns=prep_end - prep_start,
        model_build_ns=build_end - build_start,
        search_ns=search_end - search_start,
        total_planning_ns=total_end - total_start,
        nodes_generated=None,
        nodes_expanded=None,
        lower_bound=lower_bound,
        versions=versions,
        validation=val_report,
        details=details,
    )
