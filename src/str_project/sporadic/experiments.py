"""Paired experiment runner executing Xu & Parnas and SMT/Z3 over identical frozen sporadic instances."""

from __future__ import annotations

import json
import math
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..model import PlanningLimits, PlanningResult, collect_versions
from ..planners.smt_z3 import plan_smt_z3
from ..planners.xu_parnas import plan_xu_parnas
from ..schedule_io import save_planning_result
from .adapter import adapt_sequence_to_instance, save_adapted_instance
from .generator import generate_sequence
from .models import (
    AdaptedSporadicInstance,
    CrossTaskRule,
    ScenarioSpec,
    SegmentTemplate,
    TaskSpec,
    parse_scenario_spec,
)
from .validation import validate_sporadic_schedule


def _canonical_status(planner_status: str) -> str:
    """Map internal PlanningResult status to standard SAT/UNSAT/TIMEOUT/UNKNOWN/ERROR labels."""
    mapping = {
        "feasible": "SAT",
        "infeasible": "UNSAT",
        "timeout": "TIMEOUT",
        "unknown": "UNKNOWN",
        "invalid_input": "INVALID_INPUT",
        "implementation_error": "IMPLEMENTATION_ERROR",
    }
    return mapping.get(planner_status, planner_status.upper())


def get_code_revision(repo_dir: Path | None = None) -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_dir or Path.cwd()),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or "unknown"
    except Exception:
        return "unknown"


@dataclass
class MethodRunRecord:
    scenario_id: str
    seed: int
    generation_mode: str
    horizon: int
    horizon_policy: str
    utilization_band: str
    jitter_label: str
    num_tasks: int
    num_jobs: int
    num_discarded_jobs: int
    num_segments: int
    total_units: int
    num_precedences: int
    num_exclusions: int
    nominal_utilization: float
    effective_utilization: float
    input_hash: str
    instance_hash: str
    method: str
    execution_order_index: int
    status: str  # SAT, UNSAT, TIMEOUT, UNKNOWN, INVALID_INPUT, IMPLEMENTATION_ERROR
    raw_status: str
    logical_lmax: int | None
    lower_bound: int | None
    prep_time_ns: int
    model_build_time_ns: int | None
    solver_time_ns: int | None
    planning_wall_time_ns: int
    nodes_generated: int | None
    nodes_expanded: int | None
    validation_passed: bool | None
    schedule_path: str | None
    failure_reason: str | None
    timeout: bool
    timeout_ms: int
    environment: dict[str, str]
    code_revision: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "seed": self.seed,
            "generation_mode": self.generation_mode,
            "horizon": self.horizon,
            "horizon_policy": self.horizon_policy,
            "utilization_band": self.utilization_band,
            "jitter_label": self.jitter_label,
            "num_tasks": self.num_tasks,
            "num_jobs": self.num_jobs,
            "num_discarded_jobs": self.num_discarded_jobs,
            "num_segments": self.num_segments,
            "total_units": self.total_units,
            "num_precedences": self.num_precedences,
            "num_exclusions": self.num_exclusions,
            "nominal_utilization": self.nominal_utilization,
            "effective_utilization": self.effective_utilization,
            "input_hash": self.input_hash,
            "instance_hash": self.instance_hash,
            "method": self.method,
            "execution_order_index": self.execution_order_index,
            "status": self.status,
            "raw_status": self.raw_status,
            "logical_lmax": self.logical_lmax,
            "lower_bound": self.lower_bound,
            "prep_time_ns": self.prep_time_ns,
            "model_build_time_ns": self.model_build_time_ns,
            "solver_time_ns": self.solver_time_ns,
            "planning_wall_time_ns": self.planning_wall_time_ns,
            "nodes_generated": self.nodes_generated,
            "nodes_expanded": self.nodes_expanded,
            "validation_passed": self.validation_passed,
            "schedule_path": self.schedule_path,
            "failure_reason": self.failure_reason,
            "timeout": self.timeout,
            "timeout_ms": self.timeout_ms,
            "environment": self.environment,
            "code_revision": self.code_revision,
        }


def _run_single_method(
    method: str,
    adapted: AdaptedSporadicInstance,
    limits: PlanningLimits,
    *,
    prep_time_ns: int,
    execution_order_index: int,
    schedule_out_path: Path | None,
    utilization_band: str,
    jitter_label: str,
    code_revision: str,
    env: dict[str, str],
) -> MethodRunRecord:
    wall_start = time.perf_counter_ns()
    if method == "xu-parnas":
        res: PlanningResult = plan_xu_parnas(
            adapted.instance, limits, objective=adapted.scenario.objective
        )
    elif method == "smt-z3":
        res = plan_smt_z3(
            adapted.instance, limits, objective=adapted.scenario.objective
        )
    else:
        raise ValueError(f"Unknown planning method: {method!r}")
    wall_end = time.perf_counter_ns()

    assert res.instance_hash == adapted.instance.instance_hash(), (
        f"Instance hash mismatch for {method} on {adapted.scenario.scenario_id}!"
    )

    validation_passed: bool | None = None
    failure_reason = res.reason
    canonical = _canonical_status(res.status)
    saved_sched_path: str | None = None

    if res.status == "feasible" and res.schedule is not None:
        val_rep = validate_sporadic_schedule(
            adapted,
            res.schedule,
            require_deadlines=(adapted.scenario.objective == "feasibility"),
        )
        validation_passed = val_rep.ok
        if not val_rep.ok:
            canonical = "IMPLEMENTATION_ERROR"
            failure_reason = f"independent_validation_failed: {'; '.join(val_rep.errors)}"
        if schedule_out_path is not None:
            save_planning_result(res, schedule_out_path)
            saved_sched_path = str(schedule_out_path)
    elif schedule_out_path is not None:
        save_planning_result(res, schedule_out_path)
        saved_sched_path = str(schedule_out_path)

    meta = adapted.metadata
    return MethodRunRecord(
        scenario_id=adapted.scenario.scenario_id,
        seed=adapted.scenario.seed,
        generation_mode=adapted.scenario.generation_mode,
        horizon=adapted.scenario.horizon,
        horizon_policy=adapted.scenario.horizon_policy,
        utilization_band=utilization_band,
        jitter_label=jitter_label,
        num_tasks=int(meta["num_tasks"]),
        num_jobs=int(meta["num_jobs"]),
        num_discarded_jobs=int(meta["num_discarded_jobs"]),
        num_segments=int(meta["num_segments"]),
        total_units=int(meta["total_units"]),
        num_precedences=int(meta["num_precedences"]),
        num_exclusions=int(meta["num_exclusions"]),
        nominal_utilization=float(meta["nominal_utilization"]),
        effective_utilization=float(meta["effective_utilization"]),
        input_hash=adapted.input_hash,
        instance_hash=adapted.instance.instance_hash(),
        method=method,
        execution_order_index=execution_order_index,
        status=canonical,
        raw_status=res.status,
        logical_lmax=res.logical_lmax,
        lower_bound=res.lower_bound,
        prep_time_ns=prep_time_ns,
        model_build_time_ns=res.model_build_ns,
        solver_time_ns=res.search_ns,
        planning_wall_time_ns=res.total_planning_ns or (wall_end - wall_start),
        nodes_generated=res.nodes_generated,
        nodes_expanded=res.nodes_expanded,
        validation_passed=validation_passed,
        schedule_path=saved_sched_path,
        failure_reason=failure_reason,
        timeout=(canonical == "TIMEOUT"),
        timeout_ms=limits.timeout_ms,
        environment=env,
        code_revision=code_revision,
    )


def run_sporadic_scenario(
    scenario: ScenarioSpec,
    *,
    out_dir: str | Path | None = None,
    timeout_ms: int = 5_000,
    method_order: tuple[str, str] = ("xu-parnas", "smt-z3"),
    save_instance: bool = True,
    save_schedules: bool = True,
    utilization_band: str = "custom",
    jitter_label: str = "custom",
    code_revision: str | None = None,
) -> dict[str, Any]:
    """Generate, validate, freeze, solve (both methods), and independently verify a sporadic scenario."""
    env = collect_versions()
    rev = code_revision or get_code_revision()

    prep_start = time.perf_counter_ns()
    seq = generate_sequence(scenario)
    adapted = adapt_sequence_to_instance(seq)
    prep_end = time.perf_counter_ns()
    prep_time_ns = prep_end - prep_start

    instance_path: Path | None = None
    if out_dir is not None and save_instance:
        inst_dir = Path(out_dir) / "instances"
        instance_path = save_adapted_instance(
            adapted, inst_dir / f"{scenario.scenario_id}__seed{scenario.seed}.json"
        )

    limits = PlanningLimits(timeout_ms=timeout_ms)
    records: dict[str, MethodRunRecord] = {}

    for idx, method in enumerate(method_order):
        sched_path: Path | None = None
        if out_dir is not None and save_schedules:
            sched_path = (
                Path(out_dir)
                / "schedules"
                / f"{scenario.scenario_id}__seed{scenario.seed}__{method}.json"
            )
        records[method] = _run_single_method(
            method,
            adapted,
            limits,
            prep_time_ns=prep_time_ns,
            execution_order_index=idx,
            schedule_out_path=sched_path,
            utilization_band=utilization_band,
            jitter_label=jitter_label,
            code_revision=rev,
            env=env,
        )

    xu_rec = records["xu-parnas"]
    z3_rec = records["smt-z3"]
    both_decided = xu_rec.status in {"SAT", "UNSAT"} and z3_rec.status in {"SAT", "UNSAT"}
    agreement: bool | None = (xu_rec.status == z3_rec.status) if both_decided else None
    divergence = both_decided and (xu_rec.status != z3_rec.status)

    result_bundle = {
        "scenario_id": scenario.scenario_id,
        "seed": scenario.seed,
        "input_hash": adapted.input_hash,
        "instance_hash": adapted.instance.instance_hash(),
        "instance_path": str(instance_path) if instance_path else None,
        "method_order": list(method_order),
        "agreement": agreement,
        "divergence_detected": divergence,
        "records": {
            "xu-parnas": xu_rec.to_dict(),
            "smt-z3": z3_rec.to_dict(),
        },
    }
    if out_dir is not None and save_schedules:
        log_path = Path(out_dir) / "logs" / f"{scenario.scenario_id}__seed{scenario.seed}.json"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            json.dumps(result_bundle, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return result_bundle


def build_matrix_scenarios(matrix_cfg: dict[str, Any]) -> list[tuple[ScenarioSpec, str, str]]:
    """Expand a matrix specification JSON into deterministic (ScenarioSpec, util_band, jitter_label) entries."""
    task_counts: list[int] = list(matrix_cfg["task_counts"])
    horizons: list[int] = list(matrix_cfg["horizons"])
    patterns: list[str] = list(matrix_cfg["patterns"])
    jitter_ratios: dict[str, float] = dict(matrix_cfg["jitter_ratios"])
    utilization_profiles: dict[str, list[dict[str, Any]]] = dict(
        matrix_cfg["utilization_profiles"]
    )
    seeds: list[int] = list(matrix_cfg["seeds"])
    horizon_policy: str = str(matrix_cfg.get("horizon_policy", "deadline_within_horizon"))
    burst_size: int = int(matrix_cfg.get("burst_size", 2))
    include_exclusions: bool = bool(matrix_cfg.get("include_exclusions", True))
    include_precedences: bool = bool(matrix_cfg.get("include_precedences", True))

    entries: list[tuple[ScenarioSpec, str, str]] = []

    for n_tasks in task_counts:
        for horizon in horizons:
            for util_band, base_templates in utilization_profiles.items():
                # Build N tasks by cycling/adjusting the profile templates cleanly so
                # sum(C_i / T_i) stays in the target utilization band.
                raw_tasks: list[TaskSpec] = []
                for i in range(n_tasks):
                    tmpl = base_templates[i % len(base_templates)]
                    # Scale T proportionally when n_tasks exceeds base template count so
                    # nominal utilization stays comparable across N=3, 5, 8.
                    scale_n = max(1.0, n_tasks / len(base_templates))
                    base_c = int(tmpl["C"])
                    base_t = int(math.ceil(int(tmpl["T"]) * scale_n))
                    base_d = int(math.ceil(int(tmpl["D"]) * scale_n))
                    base_d = max(base_c, min(base_d, base_t))
                    offset = int(tmpl.get("offset", 0))

                    # Optional 2-segment split for tasks with C >= 2 to preserve segmented structure
                    if base_c >= 2:
                        c1 = base_c // 2
                        c2 = base_c - c1
                        segs = (
                            SegmentTemplate(id="S1", execution_units=c1),
                            SegmentTemplate(id="S2", execution_units=c2),
                        )
                    else:
                        segs = (SegmentTemplate(id="S1", execution_units=base_c),)

                    raw_tasks.append(
                        TaskSpec(
                            id=f"T{i + 1}",
                            C=base_c,
                            D=base_d,
                            T=base_t,
                            offset=offset,
                            segments=segs,
                        )
                    )

                cross_rules: list[CrossTaskRule] = []
                if include_exclusions and n_tasks >= 2:
                    # Directional exclusion between last segment of T1 and first segment of T2 (and vice-versa on T2/T3)
                    t1_last = raw_tasks[0].effective_segments()[-1].id
                    t2_first = raw_tasks[1].effective_segments()[0].id
                    cross_rules.append(
                        CrossTaskRule(
                            kind="exclusion",
                            src_task=raw_tasks[0].id,
                            src_segment=t1_last,
                            dst_task=raw_tasks[1].id,
                            dst_segment=t2_first,
                            scope="all_overlapping",
                        )
                    )
                    if n_tasks >= 3:
                        t3_first = raw_tasks[2].effective_segments()[0].id
                        cross_rules.append(
                            CrossTaskRule(
                                kind="exclusion",
                                src_task=raw_tasks[1].id,
                                src_segment=raw_tasks[1].effective_segments()[-1].id,
                                dst_task=raw_tasks[2].id,
                                dst_segment=t3_first,
                                scope="all_overlapping",
                            )
                        )
                if include_precedences and n_tasks >= 3:
                    # Explicit same-activation precedence only between T1 and T2 when they share T & offset
                    if raw_tasks[0].T == raw_tasks[1].T and raw_tasks[0].offset == raw_tasks[1].offset:
                        cross_rules.append(
                            CrossTaskRule(
                                kind="precedence",
                                src_task=raw_tasks[0].id,
                                src_segment=raw_tasks[0].effective_segments()[-1].id,
                                dst_task=raw_tasks[1].id,
                                dst_segment=raw_tasks[1].effective_segments()[0].id,
                                scope="same_activation",
                            )
                        )

                for pattern in patterns:
                    if pattern == "min_interval":
                        j_items = [("J0", 0.0)]
                    else:
                        j_items = [
                            (lbl, ratio)
                            for lbl, ratio in jitter_ratios.items()
                            if ratio > 0.0 or pattern == "bursty"
                        ]

                    for j_label, j_ratio in j_items:
                        # Compute per-task integer jitter floor(T_i * ratio) documented explicitly
                        tasks_with_j = tuple(
                            TaskSpec(
                                id=t.id,
                                C=t.C,
                                D=t.D,
                                T=t.T,
                                offset=t.offset,
                                segments=t.segments,
                                jitter_max=int(math.floor(t.T * j_ratio)),
                                burst_size=burst_size if pattern == "bursty" else None,
                                burst_gap=(
                                    max(1, int(math.floor(t.T * max(0.5, j_ratio))))
                                    if pattern == "bursty"
                                    else None
                                ),
                            )
                            for t in raw_tasks
                        )
                        for seed in seeds:
                            sid = f"N{n_tasks}_H{horizon}_{util_band}_{pattern}_{j_label}"
                            spec = ScenarioSpec(
                                scenario_id=sid,
                                horizon=horizon,
                                seed=seed,
                                generation_mode=pattern,
                                tasks=tasks_with_j,
                                cross_rules=tuple(cross_rules),
                                jitter_max=int(
                                    math.floor(raw_tasks[0].T * j_ratio)
                                ),
                                burst_size=burst_size,
                                horizon_policy=horizon_policy,
                            )
                            entries.append((spec, util_band, j_label))
    return entries


def run_sporadic_matrix(
    matrix_cfg: dict[str, Any],
    out_dir: str | Path,
    *,
    timeout_ms: int | None = None,
    warmup_scenarios: int = 1,
    save_all_instances: bool = False,
    save_all_schedules: bool = False,
) -> dict[str, Any]:
    """Execute a full sporadic experimental matrix with warmup and alternating planner order."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    eff_timeout = int(timeout_ms if timeout_ms is not None else matrix_cfg.get("timeout_ms", 5_000))
    entries = build_matrix_scenarios(matrix_cfg)
    rev = get_code_revision()

    # Freeze exact matrix config inside results dir
    (out / "matrix_config_frozen.json").write_text(
        json.dumps(matrix_cfg, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Warmup runs (discarded from metrics, executed on first scenario)
    for w_idx in range(min(warmup_scenarios, len(entries))):
        w_spec, w_util, w_jit = entries[w_idx]
        run_sporadic_scenario(
            w_spec,
            out_dir=None,
            timeout_ms=eff_timeout,
            method_order=("xu-parnas", "smt-z3"),
            save_instance=False,
            save_schedules=False,
            utilization_band=w_util,
            jitter_label=w_jit,
            code_revision=rev,
        )

    all_records: list[dict[str, Any]] = []
    pair_summaries: list[dict[str, Any]] = []

    for run_idx, (spec, util_band, j_label) in enumerate(entries):
        order = ("xu-parnas", "smt-z3") if run_idx % 2 == 0 else ("smt-z3", "xu-parnas")
        # Save sample instances/schedules for first seed of each configuration (or all if requested)
        is_sample = save_all_instances or (spec.seed == matrix_cfg["seeds"][0])
        bundle = run_sporadic_scenario(
            spec,
            out_dir=out,
            timeout_ms=eff_timeout,
            method_order=order,
            save_instance=is_sample,
            save_schedules=save_all_schedules or is_sample,
            utilization_band=util_band,
            jitter_label=j_label,
            code_revision=rev,
        )
        all_records.append(bundle["records"]["xu-parnas"])
        all_records.append(bundle["records"]["smt-z3"])
        pair_summaries.append(
            {
                "scenario_id": spec.scenario_id,
                "seed": spec.seed,
                "input_hash": bundle["input_hash"],
                "instance_hash": bundle["instance_hash"],
                "xu_status": bundle["records"]["xu-parnas"]["status"],
                "z3_status": bundle["records"]["smt-z3"]["status"],
                "agreement": bundle["agreement"],
                "divergence_detected": bundle["divergence_detected"],
            }
        )

    return {
        "matrix_id": matrix_cfg.get("matrix_id", "sporadic_matrix"),
        "timeout_ms": eff_timeout,
        "warmup_scenarios": warmup_scenarios,
        "total_scenarios": len(entries),
        "code_revision": rev,
        "environment": collect_versions(),
        "records": all_records,
        "pairs": pair_summaries,
    }
