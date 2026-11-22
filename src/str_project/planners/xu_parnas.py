"""Full branch-and-bound pre-run-time scheduler of Xu & Parnas (1990)."""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from typing import Any

from ..model import (
    PlanningLimits,
    PlanningResult,
    Schedule,
    SchedulingInstance,
    collect_versions,
)
from ..validator import validate_schedule
from .xu_bounds import (
    ExpandSets,
    compute_expand_sets,
    compute_lower_bound,
    has_unit_in_interval,
)
from .xu_initial import build_valid_initial_schedule


@dataclass
class SearchNode:
    node_id: int
    parent_id: int | None
    branch_kind: str  # "root", "G1", "G2"
    added_relations: tuple[str, ...]
    pc: frozenset[tuple[str, str]]
    ex: frozenset[tuple[str, str]]
    pm: frozenset[tuple[str, str]]
    schedule: Schedule
    adjusted_releases: dict[str, int]
    lmax: int
    latest_seg: str
    lower_bound: int
    expand_sets: ExpandSets
    close_reason: str | None = None

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "parent_id": self.parent_id,
            "branch_kind": self.branch_kind,
            "added_relations": list(self.added_relations),
            "latest_segment": self.latest_seg,
            "g1": sorted(self.expand_sets.g1),
            "g2": sorted(self.expand_sets.g2),
            "lower_bound": self.lower_bound,
            "lmax": self.lmax,
            "close_reason": self.close_reason,
        }


def _unit_ticks_by_segment(schedule: Schedule) -> dict[str, tuple[int, ...]]:
    by_seg: dict[str, list[int]] = {}
    for u in schedule.units:
        by_seg.setdefault(u.segment_id, []).append(u.start_tick)
    return {sid: tuple(sorted(ticks)) for sid, ticks in by_seg.items()}


def expand_node(
    instance: SchedulingInstance,
    node: SearchNode,
    next_id_ref: list[int],
    visited_states: set[tuple[frozenset[tuple[str, str]], frozenset[tuple[str, str]]]],
    audit_log: list[dict[str, Any]] | None = None,
) -> list[SearchNode]:
    """Generate consistent child nodes from G1 and G2 per Xu & Parnas (1990), Section V & Appendix 2."""
    j = node.latest_seg
    bounds = node.schedule.segment_bounds()
    unit_ticks = _unit_ticks_by_segment(node.schedule)
    e_j = bounds[j][1]
    z_j = node.expand_sets.z_set

    candidates: list[tuple[str, tuple[str, ...], frozenset[tuple[str, str]], frozenset[tuple[str, str]]]] = []

    # G1 branching: for each k in G1, add PC(j, k)
    for k in sorted(node.expand_sets.g1):
        new_pc = node.pc | {(j, k)}
        candidates.append(("G1", (f"PC({j},{k})",), new_pc, node.pm))

    # G2 branching: for each k in G2:
    # - Add PC(l, k) for segments l executing between k and j in parent schedule with EX(k, l)
    # - Add PM(q, k) for segments q executing between k and j in parent schedule without EX(k, q)
    # - Add PM(j, k)
    for k in sorted(node.expand_sets.g2):
        s_k = bounds[k][0]
        added_pc: set[tuple[str, str]] = set()
        added_pm: set[tuple[str, str]] = {(j, k)}
        added_desc: list[str] = [f"PM({j},{k})"]

        for seg in instance.segments:
            m = seg.id
            if m == k or m == j:
                continue
            if m in z_j and has_unit_in_interval(unit_ticks, m, s_k, e_j):
                if (k, m) in node.ex:
                    added_pc.add((m, k))
                    added_desc.append(f"PC({m},{k})")
                else:
                    added_pm.add((m, k))
                    added_desc.append(f"PM({m},{k})")

        new_pc = node.pc | frozenset(added_pc)
        new_pm = node.pm | frozenset(added_pm)
        candidates.append(("G2", tuple(sorted(added_desc)), new_pc, new_pm))

    children: list[SearchNode] = []
    for kind, desc, cand_pc, cand_pm in candidates:
        init_res = build_valid_initial_schedule(instance, cand_pc, node.ex, cand_pm)
        if not init_res.ok or init_res.schedule is None:
            if audit_log is not None:
                audit_log.append(
                    {
                        "node_id": None,
                        "parent_id": node.node_id,
                        "branch_kind": kind,
                        "added_relations": list(desc),
                        "close_reason": init_res.reason,
                    }
                )
            continue

        state_key = (init_res.pc_closure, cand_pm)
        if state_key in visited_states:
            continue
        visited_states.add(state_key)

        exp_sets = compute_expand_sets(
            instance,
            init_res.schedule,
            init_res.adjusted_releases,
            init_res.pc_closure,
            node.ex,
            cand_pm,
        )
        lb = compute_lower_bound(
            instance,
            init_res.schedule,
            init_res.adjusted_releases,
            init_res.pc_closure,
            node.ex,
            cand_pm,
        )

        child_id = next_id_ref[0]
        next_id_ref[0] += 1
        children.append(
            SearchNode(
                node_id=child_id,
                parent_id=node.node_id,
                branch_kind=kind,
                added_relations=desc,
                pc=init_res.pc_closure,
                ex=node.ex,
                pm=cand_pm,
                schedule=init_res.schedule,
                adjusted_releases=init_res.adjusted_releases,
                lmax=exp_sets.lmax,
                latest_seg=exp_sets.latest_segment,
                lower_bound=lb,
                expand_sets=exp_sets,
            )
        )

    return children


def plan_xu_parnas(
    instance: SchedulingInstance,
    limits: PlanningLimits | None = None,
    *,
    objective: str | None = None,
) -> PlanningResult:
    """Run the complete Xu & Parnas (1990) branch-and-bound pre-run-time scheduler."""
    lim = limits or PlanningLimits()
    obj = objective or instance.objective
    versions = collect_versions()
    total_start = time.perf_counter_ns()

    if obj not in {"feasibility", "min_lmax"}:
        total_end = time.perf_counter_ns()
        return PlanningResult(
            instance_id=instance.instance_id,
            instance_hash=instance.instance_hash(),
            planner="xu-parnas",
            objective=obj,
            status="invalid_input",
            schedule=None,
            logical_lmax=None,
            reason=f"Unsupported objective: {obj!r}",
            preprocessing_ns=0,
            model_build_ns=None,
            search_ns=0,
            total_planning_ns=total_end - total_start,
            nodes_generated=0,
            nodes_expanded=0,
            lower_bound=None,
            versions=versions,
        )

    deadline_ns = (
        total_start + lim.timeout_ms * 1_000_000
        if lim.timeout_ms is not None
        else None
    )

    prep_start = time.perf_counter_ns()
    root_pc = frozenset(instance.precedence)
    root_ex = frozenset(instance.exclusion)
    root_pm: frozenset[tuple[str, str]] = frozenset()
    prep_end = time.perf_counter_ns()

    if lim.timeout_ms is not None and lim.timeout_ms == 0:
        total_end = time.perf_counter_ns()
        return PlanningResult(
            instance_id=instance.instance_id,
            instance_hash=instance.instance_hash(),
            planner="xu-parnas",
            objective=obj,
            status="timeout",
            schedule=None,
            logical_lmax=None,
            reason="timeout_ms_zero_limit_exceeded",
            preprocessing_ns=prep_end - prep_start,
            model_build_ns=None,
            search_ns=0,
            total_planning_ns=total_end - total_start,
            nodes_generated=0,
            nodes_expanded=0,
            lower_bound=None,
            versions=versions,
        )

    search_start = time.perf_counter_ns()
    audit_log: list[dict[str, Any]] | None = [] if lim.record_search_trace else None

    root_init = build_valid_initial_schedule(instance, root_pc, root_ex, root_pm)
    if not root_init.ok or root_init.schedule is None:
        search_end = time.perf_counter_ns()
        total_end = time.perf_counter_ns()
        return PlanningResult(
            instance_id=instance.instance_id,
            instance_hash=instance.instance_hash(),
            planner="xu-parnas",
            objective=obj,
            status="infeasible",
            schedule=None,
            logical_lmax=None,
            reason=root_init.reason or "root_relations_inconsistent",
            preprocessing_ns=prep_end - prep_start,
            model_build_ns=None,
            search_ns=search_end - search_start,
            total_planning_ns=total_end - total_start,
            nodes_generated=1,
            nodes_expanded=0,
            lower_bound=None,
            versions=versions,
        )

    root_exp = compute_expand_sets(
        instance,
        root_init.schedule,
        root_init.adjusted_releases,
        root_init.pc_closure,
        root_ex,
        root_pm,
    )
    root_lb = compute_lower_bound(
        instance,
        root_init.schedule,
        root_init.adjusted_releases,
        root_init.pc_closure,
        root_ex,
        root_pm,
    )

    root_node = SearchNode(
        node_id=0,
        parent_id=None,
        branch_kind="root",
        added_relations=(),
        pc=root_init.pc_closure,
        ex=root_ex,
        pm=root_pm,
        schedule=root_init.schedule,
        adjusted_releases=root_init.adjusted_releases,
        lmax=root_exp.lmax,
        latest_seg=root_exp.latest_segment,
        lower_bound=root_lb,
        expand_sets=root_exp,
    )

    next_id_ref = [1]
    nodes_generated = 1
    nodes_expanded = 0
    visited_states: set[tuple[frozenset[tuple[str, str]], frozenset[tuple[str, str]]]] = {
        (root_init.pc_closure, root_pm)
    }

    incumbent_schedule: Schedule = root_node.schedule
    incumbent_lmax: int = root_node.lmax
    best_known_lb: int = root_node.lower_bound

    # Priority queue ordered by (lower_bound, lmax, node_id)
    open_heap: list[tuple[int, int, int, SearchNode]] = []
    timed_out = False
    timeout_reason: str | None = None

    def _should_open(node: SearchNode) -> bool:
        if node.lmax == node.lower_bound:
            node.close_reason = "closed_locally_optimal"
            return False
        if node.lower_bound >= incumbent_lmax:
            node.close_reason = "closed_pruned_by_incumbent"
            return False
        if obj == "feasibility" and node.lower_bound > 0:
            node.close_reason = "closed_pruned_positive_lb"
            return False
        return True

    if obj == "feasibility" and incumbent_lmax <= 0:
        root_node.close_reason = "feasible_at_root"
        if audit_log is not None:
            audit_log.append(root_node.to_audit_dict())
    else:
        if _should_open(root_node):
            heapq.heappush(
                open_heap, (root_node.lower_bound, root_node.lmax, root_node.node_id, root_node)
            )
        elif audit_log is not None:
            audit_log.append(root_node.to_audit_dict())

        while open_heap:
            if deadline_ns is not None and time.perf_counter_ns() >= deadline_ns:
                timed_out = True
                timeout_reason = f"timeout_ms_exceeded:{lim.timeout_ms}"
                break
            if lim.max_nodes is not None and nodes_generated >= lim.max_nodes:
                timed_out = True
                timeout_reason = f"max_nodes_exceeded:{lim.max_nodes}"
                break

            _, _, _, current = heapq.heappop(open_heap)

            # Re-check pruning against potentially improved incumbent
            if current.lower_bound >= incumbent_lmax:
                current.close_reason = "closed_pruned_by_incumbent"
                if audit_log is not None:
                    audit_log.append(current.to_audit_dict())
                continue
            if obj == "feasibility" and current.lower_bound > 0:
                current.close_reason = "closed_pruned_positive_lb"
                if audit_log is not None:
                    audit_log.append(current.to_audit_dict())
                continue

            nodes_expanded += 1
            children = expand_node(instance, current, next_id_ref, visited_states, audit_log)
            nodes_generated += len(children)

            if not children:
                current.close_reason = "closed_no_consistent_children"
            else:
                current.close_reason = "expanded"
            if audit_log is not None:
                audit_log.append(current.to_audit_dict())

            found_feasible_early = False
            for child in children:
                if child.lmax < incumbent_lmax:
                    incumbent_lmax = child.lmax
                    incumbent_schedule = child.schedule
                    if obj == "feasibility" and incumbent_lmax <= 0:
                        child.close_reason = "feasible_found"
                        if audit_log is not None:
                            audit_log.append(child.to_audit_dict())
                        found_feasible_early = True
                        break

                if _should_open(child):
                    heapq.heappush(
                        open_heap, (child.lower_bound, child.lmax, child.node_id, child)
                    )
                elif audit_log is not None:
                    audit_log.append(child.to_audit_dict())

            if found_feasible_early:
                break

            # Early termination if remaining open nodes cannot improve incumbent
            if open_heap and open_heap[0][0] >= incumbent_lmax:
                break
            if obj == "feasibility" and open_heap and open_heap[0][0] > 0:
                break

    search_end = time.perf_counter_ns()

    details: dict[str, Any] = {
        "root_lmax": root_node.lmax,
        "root_lower_bound": root_node.lower_bound,
        "root_latest_segment": root_node.latest_seg,
        "root_g1": sorted(root_node.expand_sets.g1),
        "root_g2": sorted(root_node.expand_sets.g2),
    }
    if audit_log is not None:
        details["search_trace"] = audit_log

    if timed_out:
        total_end = time.perf_counter_ns()
        details["incumbent_lmax"] = incumbent_lmax
        details["open_nodes_remaining"] = len(open_heap)
        best_open_lb = open_heap[0][0] if open_heap else best_known_lb
        return PlanningResult(
            instance_id=instance.instance_id,
            instance_hash=instance.instance_hash(),
            planner="xu-parnas",
            objective=obj,
            status="timeout",
            schedule=None,
            logical_lmax=incumbent_lmax,
            reason=timeout_reason,
            preprocessing_ns=prep_end - prep_start,
            model_build_ns=None,
            search_ns=search_end - search_start,
            total_planning_ns=total_end - total_start,
            nodes_generated=nodes_generated,
            nodes_expanded=nodes_expanded,
            lower_bound=best_open_lb,
            versions=versions,
            details=details,
        )

    # Search completed! Determine final classification and validate returned schedule.
    val_report = validate_schedule(
        instance,
        incumbent_schedule,
        require_deadlines=(obj == "feasibility" and incumbent_lmax <= 0),
    )
    if not val_report.valid:
        total_end = time.perf_counter_ns()
        return PlanningResult(
            instance_id=instance.instance_id,
            instance_hash=instance.instance_hash(),
            planner="xu-parnas",
            objective=obj,
            status="implementation_error",
            schedule=incumbent_schedule,
            logical_lmax=incumbent_lmax,
            reason=f"xu_schedule_failed_validation: {'; '.join(val_report.errors)}",
            preprocessing_ns=prep_end - prep_start,
            model_build_ns=None,
            search_ns=search_end - search_start,
            total_planning_ns=total_end - total_start,
            nodes_generated=nodes_generated,
            nodes_expanded=nodes_expanded,
            lower_bound=best_known_lb,
            versions=versions,
            validation=val_report,
            details=details,
        )

    if obj == "feasibility":
        if incumbent_lmax <= 0 and val_report.feasible:
            status = "feasible"
            out_schedule: Schedule | None = incumbent_schedule
            reason = "xu_parnas_feasible_verified"
            certified_lb = min(root_lb, incumbent_lmax)
        else:
            status = "infeasible"
            out_schedule = None
            reason = "xu_parnas_search_exhausted_no_feasible_schedule"
            certified_lb = incumbent_lmax if not open_heap else min(incumbent_lmax, open_heap[0][0])
            details["best_valid_lmax"] = incumbent_lmax
    else:
        # min_lmax mode: full branch-and-bound finished => incumbent_lmax is certified optimal
        certified_lb = incumbent_lmax
        details["optimal_certified"] = True
        out_schedule = incumbent_schedule
        if incumbent_lmax <= 0 and val_report.feasible:
            status = "feasible"
            reason = "xu_parnas_optimal_feasible"
        else:
            status = "infeasible"
            reason = "xu_parnas_optimal_positive_lmax_infeasible"

    total_end = time.perf_counter_ns()
    return PlanningResult(
        instance_id=instance.instance_id,
        instance_hash=instance.instance_hash(),
        planner="xu-parnas",
        objective=obj,
        status=status,
        schedule=out_schedule,
        logical_lmax=incumbent_lmax,
        reason=reason,
        preprocessing_ns=prep_end - prep_start,
        model_build_ns=None,
        search_ns=search_end - search_start,
        total_planning_ns=total_end - total_start,
        nodes_generated=nodes_generated,
        nodes_expanded=nodes_expanded,
        lower_bound=certified_lb,
        versions=versions,
        validation=val_report,
        details=details,
    )
