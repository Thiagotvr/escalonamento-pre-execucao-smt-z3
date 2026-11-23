"""Deterministic, reproducible generator for sporadic task arrival sequences."""

from __future__ import annotations

import random

from .models import (
    Activation,
    DiscardedActivation,
    GeneratedSequence,
    ScenarioSpec,
    TaskSpec,
    compute_canonical_sha256,
)
from .validation import (
    SporadicValidationError,
    validate_activations,
    validate_scenario_spec,
)


def _choose_extra_gap(
    mode: str,
    rng: random.Random,
    *,
    T: int,
    jitter_max: int,
    arrival_in_burst: int,
    burst_size: int,
    burst_gap: int | None,
) -> int:
    """Return an integer extra gap >= 0 added on top of minimum inter-arrival T."""
    if mode == "min_interval":
        return 0
    if mode == "jittered":
        return rng.randint(0, jitter_max) if jitter_max > 0 else 0
    if mode == "bursty":
        # Inside a burst: arrivals separated by the minimum T (extra = 0).
        # At the end of a burst: insert a larger idle gap, still guaranteeing >= T total.
        if arrival_in_burst < burst_size:
            return 0
        if burst_gap is not None:
            return burst_gap
        lo = max(1, jitter_max // 2) if jitter_max > 0 else T
        hi = max(lo, jitter_max) if jitter_max > 0 else 2 * T
        return rng.randint(lo, hi)
    raise SporadicValidationError(f"Unsupported single-task generation mode: {mode!r}")


def generate_releases_for_task(
    task: TaskSpec,
    scenario: ScenarioSpec,
    rng: random.Random,
) -> list[int]:
    """Generate a validated list of release ticks for a single sporadic task."""
    mode = task.mode if (scenario.generation_mode == "mixed" and task.mode is not None) else scenario.generation_mode
    if mode == "mixed":
        # Fallback if a task in a mixed scenario omitted explicit per-task mode
        mode = "jittered"

    if mode == "explicit":
        if task.explicit_releases is None:
            raise SporadicValidationError(
                f"Task {task.id!r} uses mode='explicit' but has no explicit_releases."
            )
        releases = list(task.explicit_releases)
        for idx, r in enumerate(releases):
            if r < 0:
                raise SporadicValidationError(
                    f"Task {task.id!r}: explicit release[{idx}]={r} is negative."
                )
            if r < task.offset:
                raise SporadicValidationError(
                    f"Task {task.id!r}: explicit release[{idx}]={r} < offset={task.offset}."
                )
            if idx > 0:
                gap = r - releases[idx - 1]
                if gap < task.T:
                    raise SporadicValidationError(
                        f"Task {task.id!r}: explicit releases violate minimum separation T={task.T} "
                        f"between r[{idx - 1}]={releases[idx - 1]} and r[{idx}]={r} (gap={gap})."
                    )
        return releases

    jitter_max = task.jitter_max if task.jitter_max is not None else scenario.jitter_max
    burst_size = task.burst_size if task.burst_size is not None else scenario.burst_size
    burst_gap = task.burst_gap if task.burst_gap is not None else scenario.burst_gap

    r = task.offset
    releases = []
    count_in_burst = 0
    while r < scenario.horizon:
        releases.append(r)
        count_in_burst += 1
        extra = _choose_extra_gap(
            mode,
            rng,
            T=task.T,
            jitter_max=jitter_max,
            arrival_in_burst=count_in_burst,
            burst_size=burst_size,
            burst_gap=burst_gap,
        )
        if mode == "bursty" and count_in_burst >= burst_size:
            count_in_burst = 0
        assert extra >= 0
        r += task.T + extra
    return releases


def generate_sequence(scenario: ScenarioSpec) -> GeneratedSequence:
    """Deterministically generate and validate sporadic activations for a ScenarioSpec.

    Uses an isolated local Random(scenario.seed) instance (zero reliance on global RNG),
    filters activations according to scenario.horizon_policy while explicitly recording
    every discarded activation, sorts canonically by (release, task_id, activation_index),
    and verifies all arrival invariants before returning.
    """
    validate_scenario_spec(scenario)
    rng = random.Random(scenario.seed)

    kept: list[Activation] = []
    discarded: list[DiscardedActivation] = []

    for task in scenario.tasks:
        releases = generate_releases_for_task(task, scenario, rng)
        for act_idx, rel in enumerate(releases):
            abs_d = rel + task.D
            if rel >= scenario.horizon:
                discarded.append(
                    DiscardedActivation(
                        task_id=task.id,
                        activation_index=act_idx,
                        release=rel,
                        absolute_deadline=abs_d,
                        reason="release_at_or_beyond_horizon",
                    )
                )
                continue
            if (
                scenario.horizon_policy == "deadline_within_horizon"
                and abs_d > scenario.horizon
            ):
                discarded.append(
                    DiscardedActivation(
                        task_id=task.id,
                        activation_index=act_idx,
                        release=rel,
                        absolute_deadline=abs_d,
                        reason="deadline_exceeds_horizon",
                    )
                )
                continue

            kept.append(
                Activation(
                    task_id=task.id,
                    activation_index=act_idx,
                    release=rel,
                    absolute_deadline=abs_d,
                    execution_units=task.C,
                )
            )

    kept.sort(key=lambda a: (a.release, a.task_id, a.activation_index))
    discarded.sort(key=lambda d: (d.release, d.task_id, d.activation_index))

    kept_tuple = tuple(kept)
    discarded_tuple = tuple(discarded)

    validate_activations(scenario, kept_tuple, discarded_tuple)

    hash_payload = {
        "schema_version": scenario.schema_version,
        "scenario_id": scenario.scenario_id,
        "seed": scenario.seed,
        "horizon": scenario.horizon,
        "horizon_policy": scenario.horizon_policy,
        "generation_mode": scenario.generation_mode,
        "activations": [a.to_dict() for a in kept_tuple],
        "discarded_activations": [d.to_dict() for d in discarded_tuple],
    }
    seq_hash = compute_canonical_sha256(hash_payload)

    return GeneratedSequence(
        scenario=scenario,
        activations=kept_tuple,
        discarded_activations=discarded_tuple,
        sequence_hash=seq_hash,
    )
