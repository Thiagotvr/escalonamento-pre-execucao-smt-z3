"""Adapter translating validated sporadic activations into the common SchedulingInstance contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..instance_io import parse_instance
from .models import (
    Activation,
    AdaptedSporadicInstance,
    CrossTaskRule,
    GeneratedSequence,
    compute_canonical_sha256,
)
from .validation import (
    SporadicValidationError,
    validate_activations,
    validate_adapted_instance,
)


def make_segment_id(task_id: str, template_segment_id: str, activation_index: int) -> str:
    """Build a globally unique, readable concrete segment identifier."""
    return f"{task_id}_{template_segment_id}_k{activation_index}"


def _windows_overlap(a: Activation, b: Activation) -> bool:
    """Return True if the scheduling intervals [r_a, d_a) and [r_b, d_b) overlap."""
    return a.release < b.absolute_deadline and b.release < a.absolute_deadline


def _instantiate_cross_rule(
    rule: CrossTaskRule,
    by_task: dict[str, list[Activation]],
) -> list[tuple[str, str]]:
    """Expand an explicit CrossTaskRule into concrete segment pairs without altering direction."""
    src_acts = by_task.get(rule.src_task, [])
    dst_acts = by_task.get(rule.dst_task, [])
    pairs: list[tuple[str, str]] = []

    if rule.scope == "same_activation":
        dst_by_idx = {a.activation_index: a for a in dst_acts}
        for s_act in src_acts:
            d_act = dst_by_idx.get(s_act.activation_index)
            if d_act is None:
                continue
            src_id = make_segment_id(rule.src_task, rule.src_segment, s_act.activation_index)
            dst_id = make_segment_id(rule.dst_task, rule.dst_segment, d_act.activation_index)
            if src_id != dst_id:
                pairs.append((src_id, dst_id))
    elif rule.scope == "all_overlapping":
        for s_act in src_acts:
            for d_act in dst_acts:
                if s_act.job_id == d_act.job_id and rule.src_segment == rule.dst_segment:
                    continue
                if _windows_overlap(s_act, d_act):
                    src_id = make_segment_id(
                        rule.src_task, rule.src_segment, s_act.activation_index
                    )
                    dst_id = make_segment_id(
                        rule.dst_task, rule.dst_segment, d_act.activation_index
                    )
                    pairs.append((src_id, dst_id))
    elif rule.scope == "all_pairs":
        for s_act in src_acts:
            for d_act in dst_acts:
                if s_act.job_id == d_act.job_id and rule.src_segment == rule.dst_segment:
                    continue
                src_id = make_segment_id(
                    rule.src_task, rule.src_segment, s_act.activation_index
                )
                dst_id = make_segment_id(
                    rule.dst_task, rule.dst_segment, d_act.activation_index
                )
                pairs.append((src_id, dst_id))
    else:
        raise SporadicValidationError(f"Unsupported cross-rule scope: {rule.scope!r}.")

    return pairs


def adapt_sequence_to_instance(sequence: GeneratedSequence) -> AdaptedSporadicInstance:
    """Convert a validated sporadic activation sequence into a frozen SchedulingInstance.

    Preserves exact release times, absolute deadlines (r + D), multi-segment templates,
    intra-process ordering, explicit cross-task precedences, and directional exclusions.
    """
    scenario = sequence.scenario
    validate_activations(scenario, sequence.activations, sequence.discarded_activations)

    if not sequence.activations:
        raise SporadicValidationError(
            f"Scenario {scenario.scenario_id!r} produced zero activations within horizon={scenario.horizon}."
        )

    task_map = scenario.task_map()
    by_task: dict[str, list[Activation]] = {t.id: [] for t in scenario.tasks}
    for act in sequence.activations:
        by_task[act.task_id].append(act)

    processes_json: list[dict[str, Any]] = []
    segments_json: list[dict[str, Any]] = []
    segment_to_job: dict[str, tuple[str, int]] = {}

    for act in sequence.activations:
        spec = task_map[act.task_id]
        templates = spec.effective_segments()
        seg_ids: list[str] = []
        for tmpl in templates:
            sid = make_segment_id(act.task_id, tmpl.id, act.activation_index)
            seg_ids.append(sid)
            segment_to_job[sid] = act.job_id
            segments_json.append(
                {
                    "id": sid,
                    "release": act.release,
                    "execution_units": tmpl.execution_units,
                    "deadline": act.absolute_deadline,
                }
            )
        processes_json.append({"id": act.process_id, "segments": seg_ids})

    explicit_prec: list[list[str]] = []
    explicit_excl: list[list[str]] = []

    for rule in scenario.cross_rules:
        pairs = _instantiate_cross_rule(rule, by_task)
        if rule.kind == "precedence":
            for a, b in pairs:
                explicit_prec.append([a, b])
        elif rule.kind == "exclusion":
            # Directional only: NEVER auto-symmetrize
            for a, b in pairs:
                explicit_excl.append([a, b])
        else:
            raise SporadicValidationError(f"Unknown cross-rule kind: {rule.kind!r}.")

    instance_payload = {
        "schema_version": 1,
        "instance_id": f"{scenario.scenario_id}__seed{scenario.seed}",
        "objective": scenario.objective,
        "processes": processes_json,
        "segments": segments_json,
        "precedence": explicit_prec,
        "exclusion": explicit_excl,
    }
    instance = parse_instance(instance_payload)

    metadata = {
        "num_tasks": len(scenario.tasks),
        "num_jobs": len(sequence.activations),
        "num_discarded_jobs": len(sequence.discarded_activations),
        "num_segments": len(instance.segments),
        "total_units": instance.total_units(),
        "num_precedences": len(instance.precedence),
        "num_exclusions": len(instance.exclusion),
        "nominal_utilization": scenario.nominal_utilization(),
        "effective_utilization": sequence.effective_utilization(),
    }

    input_hash = compute_canonical_sha256(
        {
            "sequence_hash": sequence.sequence_hash,
            "instance_hash": instance.instance_hash(),
            "schema_version": scenario.schema_version,
        }
    )

    adapted = AdaptedSporadicInstance(
        scenario=scenario,
        sequence=sequence,
        instance=instance,
        input_hash=input_hash,
        segment_to_job=segment_to_job,
        metadata=metadata,
    )
    validate_adapted_instance(adapted)
    return adapted


def save_adapted_instance(adapted: AdaptedSporadicInstance, path: str | Path) -> Path:
    """Persist the frozen adapted sporadic instance JSON BEFORE invoking any planner."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(adapted.to_export_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out_path
