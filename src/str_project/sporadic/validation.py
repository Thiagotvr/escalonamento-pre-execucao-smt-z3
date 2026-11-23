"""Independent validation for sporadic specifications, arrival sequences, adapter integrity, and schedules."""

from __future__ import annotations

from ..model import Schedule, ValidationReport
from ..validator import validate_schedule
from .models import (
    VALID_GENERATION_MODES,
    VALID_HORIZON_POLICIES,
    VALID_RULE_KINDS,
    VALID_RULE_SCOPES,
    Activation,
    AdaptedSporadicInstance,
    DiscardedActivation,
    ScenarioSpec,
)


class SporadicValidationError(ValueError):
    """Raised when a sporadic scenario, arrival sequence, or adaptation violates invariants."""


def validate_scenario_spec(scenario: ScenarioSpec) -> None:
    """Validate structural and formal invariants of a sporadic ScenarioSpec."""
    if scenario.horizon <= 0:
        raise SporadicValidationError(f"Horizon H must be > 0, got {scenario.horizon}.")
    if scenario.generation_mode not in VALID_GENERATION_MODES:
        raise SporadicValidationError(
            f"Unsupported generation_mode {scenario.generation_mode!r}; "
            f"expected one of {sorted(VALID_GENERATION_MODES)}."
        )
    if scenario.horizon_policy not in VALID_HORIZON_POLICIES:
        raise SporadicValidationError(
            f"Unsupported horizon_policy {scenario.horizon_policy!r}."
        )
    if scenario.jitter_max < 0:
        raise SporadicValidationError(f"jitter_max must be >= 0, got {scenario.jitter_max}.")
    if scenario.burst_size <= 0:
        raise SporadicValidationError(f"burst_size must be > 0, got {scenario.burst_size}.")
    if scenario.burst_gap is not None and scenario.burst_gap < 0:
        raise SporadicValidationError(f"burst_gap must be >= 0, got {scenario.burst_gap}.")
    if not scenario.tasks:
        raise SporadicValidationError("Scenario must contain at least one task.")

    seen_tasks: set[str] = set()
    task_seg_ids: dict[str, set[str]] = {}
    for task in scenario.tasks:
        if task.id in seen_tasks:
            raise SporadicValidationError(f"Duplicate task id: {task.id!r}.")
        seen_tasks.add(task.id)

        if task.T <= 0:
            raise SporadicValidationError(f"Task {task.id!r}: T must be > 0, got {task.T}.")
        if task.C <= 0:
            raise SporadicValidationError(f"Task {task.id!r}: C must be > 0, got {task.C}.")
        if task.D < task.C:
            raise SporadicValidationError(
                f"Task {task.id!r}: D={task.D} < C={task.C} violates 0 < C <= D."
            )
        if not scenario.allow_unconstrained_deadlines and task.D > task.T:
            raise SporadicValidationError(
                f"Task {task.id!r}: D={task.D} > T={task.T} outside constrained-deadline "
                "scope (0 < C <= D <= T). Set allow_unconstrained_deadlines=True explicitly if intended."
            )
        if task.offset < 0:
            raise SporadicValidationError(
                f"Task {task.id!r}: negative offset={task.offset} not allowed in sporadic-v1."
            )
        if task.mode is not None and task.mode not in (VALID_GENERATION_MODES - {"mixed"}):
            raise SporadicValidationError(
                f"Task {task.id!r}: invalid per-task mode {task.mode!r}."
            )
        if task.jitter_max is not None and task.jitter_max < 0:
            raise SporadicValidationError(f"Task {task.id!r}: jitter_max must be >= 0.")
        if task.burst_size is not None and task.burst_size <= 0:
            raise SporadicValidationError(f"Task {task.id!r}: burst_size must be > 0.")
        if task.burst_gap is not None and task.burst_gap < 0:
            raise SporadicValidationError(f"Task {task.id!r}: burst_gap must be >= 0.")

        eff_segs = task.effective_segments()
        seg_ids: set[str] = set()
        total_c = 0
        for seg in eff_segs:
            if seg.id in seg_ids:
                raise SporadicValidationError(
                    f"Task {task.id!r}: duplicate segment template id {seg.id!r}."
                )
            if seg.execution_units <= 0:
                raise SporadicValidationError(
                    f"Task {task.id!r}, segment {seg.id!r}: execution_units must be > 0."
                )
            seg_ids.add(seg.id)
            total_c += seg.execution_units
        if total_c != task.C:
            raise SporadicValidationError(
                f"Task {task.id!r}: sum of template segments ({total_c}) != C ({task.C})."
            )
        task_seg_ids[task.id] = seg_ids

    for idx, rule in enumerate(scenario.cross_rules):
        if rule.kind not in VALID_RULE_KINDS:
            raise SporadicValidationError(f"cross_rules[{idx}]: invalid kind {rule.kind!r}.")
        if rule.scope not in VALID_RULE_SCOPES:
            raise SporadicValidationError(f"cross_rules[{idx}]: invalid scope {rule.scope!r}.")
        if rule.src_task not in task_seg_ids:
            raise SporadicValidationError(
                f"cross_rules[{idx}]: unknown src_task {rule.src_task!r}."
            )
        if rule.dst_task not in task_seg_ids:
            raise SporadicValidationError(
                f"cross_rules[{idx}]: unknown dst_task {rule.dst_task!r}."
            )
        if rule.src_segment not in task_seg_ids[rule.src_task]:
            raise SporadicValidationError(
                f"cross_rules[{idx}]: unknown src_segment {rule.src_segment!r} in task {rule.src_task!r}."
            )
        if rule.dst_segment not in task_seg_ids[rule.dst_task]:
            raise SporadicValidationError(
                f"cross_rules[{idx}]: unknown dst_segment {rule.dst_segment!r} in task {rule.dst_task!r}."
            )


def validate_activations(
    scenario: ScenarioSpec,
    activations: tuple[Activation, ...] | list[Activation],
    discarded: tuple[DiscardedActivation, ...] | list[DiscardedActivation] = (),
) -> None:
    """Independently verify all sporadic arrival invariants BEFORE schedule planning.

    Checks:
    - Unique (task_id, activation_index)
    - Every activation belongs to a declared task with matching execution_units == C_i
    - r >= offset_i and r >= 0
    - d == r + D_i
    - Minimum inter-arrival separation r[i, k+1] - r[i, k] >= T_i across ALL generated
      releases (including discarded tail arrivals if present)
    - Horizon policy compliance for every kept activation
    - Stable canonical ordering (release, task_id, activation_index)
    """
    validate_scenario_spec(scenario)
    task_map = scenario.task_map()

    seen_jobs: set[tuple[str, int]] = set()
    by_task: dict[str, list[Activation]] = {t.id: [] for t in scenario.tasks}

    for act in activations:
        if act.task_id not in task_map:
            raise SporadicValidationError(f"Activation references unknown task {act.task_id!r}.")
        if act.activation_index < 0:
            raise SporadicValidationError(
                f"Activation {act.job_id} has negative activation_index."
            )
        if act.job_id in seen_jobs:
            raise SporadicValidationError(f"Duplicate job_id: {act.job_id}.")
        seen_jobs.add(act.job_id)

        spec = task_map[act.task_id]
        if act.release < 0:
            raise SporadicValidationError(
                f"Activation {act.job_id} has negative release={act.release}."
            )
        if act.release < spec.offset:
            raise SporadicValidationError(
                f"Activation {act.job_id} has release={act.release} < offset={spec.offset}."
            )
        expected_d = act.release + spec.D
        if act.absolute_deadline != expected_d:
            raise SporadicValidationError(
                f"Activation {act.job_id} has deadline={act.absolute_deadline}, expected {expected_d}."
            )
        if act.execution_units != spec.C:
            raise SporadicValidationError(
                f"Activation {act.job_id} has C={act.execution_units}, expected {spec.C}."
            )

        if act.release >= scenario.horizon:
            raise SporadicValidationError(
                f"Activation {act.job_id} has release={act.release} >= horizon={scenario.horizon}."
            )
        if (
            scenario.horizon_policy == "deadline_within_horizon"
            and act.absolute_deadline > scenario.horizon
        ):
            raise SporadicValidationError(
                f"Activation {act.job_id} has deadline={act.absolute_deadline} > horizon={scenario.horizon} "
                "under policy 'deadline_within_horizon'."
            )

        by_task[act.task_id].append(act)

    # Check minimum separation T_i per task (and verify consecutive indices / ordering)
    for task_id, task_acts in by_task.items():
        spec = task_map[task_id]
        ordered = sorted(task_acts, key=lambda a: a.activation_index)
        for prev, curr in zip(ordered, ordered[1:]):
            gap = curr.release - prev.release
            if gap < spec.T:
                raise SporadicValidationError(
                    f"Task {task_id!r} violates minimum separation T={spec.T}: "
                    f"r[{prev.activation_index}]={prev.release}, r[{curr.activation_index}]={curr.release} "
                    f"(gap={gap} < {spec.T})."
                )
            if not scenario.allow_unconstrained_deadlines and prev.absolute_deadline > curr.release:
                raise SporadicValidationError(
                    f"Task {task_id!r} jobs overlap unexpectedly under D<=T: "
                    f"d[{prev.activation_index}]={prev.absolute_deadline} > r[{curr.activation_index}]={curr.release}."
                )

    # Also validate discarded activations belong to known tasks and respect offset
    for disc in discarded:
        if disc.task_id not in task_map:
            raise SporadicValidationError(
                f"Discarded activation references unknown task {disc.task_id!r}."
            )
        spec = task_map[disc.task_id]
        if disc.release < spec.offset:
            raise SporadicValidationError(
                f"Discarded activation ({disc.task_id}, {disc.activation_index}) "
                f"has release={disc.release} < offset={spec.offset}."
            )


def validate_adapted_instance(adapted: AdaptedSporadicInstance) -> None:
    """Verify that adapter conversion faithfully preserved all jobs, segments, and relations."""
    seq = adapted.sequence
    inst = adapted.instance
    task_map = adapted.scenario.task_map()

    validate_activations(adapted.scenario, seq.activations, seq.discarded_activations)

    if len(inst.processes) != len(seq.activations):
        raise SporadicValidationError(
            f"Adapter process count ({len(inst.processes)}) != activation count ({len(seq.activations)})."
        )

    expected_total_segments = sum(
        len(task_map[a.task_id].effective_segments()) for a in seq.activations
    )
    if len(inst.segments) != expected_total_segments:
        raise SporadicValidationError(
            f"Adapter segment count ({len(inst.segments)}) != expected ({expected_total_segments})."
        )

    expected_total_units = sum(a.execution_units for a in seq.activations)
    if inst.total_units() != expected_total_units:
        raise SporadicValidationError(
            f"Adapter total units ({inst.total_units()}) != expected ({expected_total_units})."
        )

    seg_map = inst.segment_map()
    proc_map = {p.id: p for p in inst.processes}
    for act in seq.activations:
        if act.process_id not in proc_map:
            raise SporadicValidationError(f"Missing adapted process {act.process_id!r}.")
        proc = proc_map[act.process_id]
        templates = task_map[act.task_id].effective_segments()
        if len(proc.segments) != len(templates):
            raise SporadicValidationError(
                f"Process {act.process_id!r} segment count mismatch."
            )
        for seg_id, tmpl in zip(proc.segments, templates):
            seg = seg_map[seg_id]
            if seg.release != act.release:
                raise SporadicValidationError(
                    f"Segment {seg_id!r} release={seg.release} != activation release={act.release}."
                )
            if seg.deadline != act.absolute_deadline:
                raise SporadicValidationError(
                    f"Segment {seg_id!r} deadline={seg.deadline} != activation deadline={act.absolute_deadline}."
                )
            if seg.execution_units != tmpl.execution_units:
                raise SporadicValidationError(
                    f"Segment {seg_id!r} C={seg.execution_units} != template C={tmpl.execution_units}."
                )
        for a_seg, b_seg in zip(proc.segments, proc.segments[1:]):
            if (a_seg, b_seg) not in inst.precedence:
                raise SporadicValidationError(
                    f"Intra-process precedence ({a_seg} -> {b_seg}) missing from adapted instance."
                )


def validate_sporadic_schedule(
    adapted: AdaptedSporadicInstance,
    schedule: Schedule,
    *,
    require_deadlines: bool = True,
) -> ValidationReport:
    """Independently verify a schedule for an adapted sporadic scenario.

    First validates the arrival sequence and adapter integrity, then delegates all
    9 core scheduling checks to the existing independent validator.
    """
    validate_adapted_instance(adapted)
    return validate_schedule(
        adapted.instance,
        schedule,
        require_deadlines=require_deadlines,
    )
