"""Formal data models for sporadic tasks, activations, scenarios, and adapted instances."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..model import SchedulingInstance

VALID_GENERATION_MODES = frozenset(
    {"min_interval", "jittered", "bursty", "explicit", "mixed"}
)
VALID_HORIZON_POLICIES = frozenset(
    {"deadline_within_horizon", "release_within_horizon"}
)
VALID_RULE_KINDS = frozenset({"precedence", "exclusion"})
VALID_RULE_SCOPES = frozenset({"same_activation", "all_overlapping", "all_pairs"})


def _require_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Field {name!r} must be an integer, got {type(value).__name__}.")
    return value


def _require_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Field {name!r} must be a non-empty string.")
    return value


@dataclass(frozen=True)
class SegmentTemplate:
    """Segment blueprint belonging to a sporadic task."""

    id: str
    execution_units: int

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "execution_units": self.execution_units}


@dataclass(frozen=True)
class TaskSpec:
    """Sporadic task specification tau_i = (C_i, D_i, T_i) with optional segments and profile."""

    id: str
    C: int
    D: int
    T: int
    offset: int = 0
    segments: tuple[SegmentTemplate, ...] = ()
    mode: str | None = None
    jitter_max: int | None = None
    burst_size: int | None = None
    burst_gap: int | None = None
    explicit_releases: tuple[int, ...] | None = None

    def effective_segments(self) -> tuple[SegmentTemplate, ...]:
        if self.segments:
            return self.segments
        return (SegmentTemplate(id="S1", execution_units=self.C),)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "C": self.C,
            "D": self.D,
            "T": self.T,
            "offset": self.offset,
            "segments": [s.to_dict() for s in self.effective_segments()],
        }
        if self.mode is not None:
            d["mode"] = self.mode
        if self.jitter_max is not None:
            d["jitter_max"] = self.jitter_max
        if self.burst_size is not None:
            d["burst_size"] = self.burst_size
        if self.burst_gap is not None:
            d["burst_gap"] = self.burst_gap
        if self.explicit_releases is not None:
            d["explicit_releases"] = list(self.explicit_releases)
        return d


@dataclass(frozen=True)
class CrossTaskRule:
    """Explicit precedence or directional exclusion rule across task templates.

    Cross-task precedences are NEVER invented automatically; only rules declared
    explicitly via CrossTaskRule are instantiated by the adapter.
    """

    kind: str  # "precedence" or "exclusion"
    src_task: str
    src_segment: str
    dst_task: str
    dst_segment: str
    scope: str = "all_overlapping"  # "same_activation", "all_overlapping", "all_pairs"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "src_task": self.src_task,
            "src_segment": self.src_segment,
            "dst_task": self.dst_task,
            "dst_segment": self.dst_segment,
            "scope": self.scope,
        }


@dataclass(frozen=True)
class ScenarioSpec:
    """Complete reproducible specification for a finite-horizon sporadic scenario."""

    scenario_id: str
    horizon: int
    seed: int
    generation_mode: str
    tasks: tuple[TaskSpec, ...]
    cross_rules: tuple[CrossTaskRule, ...] = ()
    schema_version: str = "sporadic-v1"
    jitter_max: int = 0
    burst_size: int = 2
    burst_gap: int | None = None
    horizon_policy: str = "deadline_within_horizon"
    allow_unconstrained_deadlines: bool = False
    time_unit: str = "logical_unit"
    objective: str = "feasibility"

    def task_map(self) -> dict[str, TaskSpec]:
        return {t.id: t for t in self.tasks}

    def nominal_utilization(self) -> float:
        return sum(t.C / t.T for t in self.tasks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "scenario_id": self.scenario_id,
            "horizon": self.horizon,
            "seed": self.seed,
            "generation_mode": self.generation_mode,
            "jitter_max": self.jitter_max,
            "burst_size": self.burst_size,
            "burst_gap": self.burst_gap,
            "horizon_policy": self.horizon_policy,
            "allow_unconstrained_deadlines": self.allow_unconstrained_deadlines,
            "time_unit": self.time_unit,
            "objective": self.objective,
            "tasks": [t.to_dict() for t in self.tasks],
            "cross_rules": [r.to_dict() for r in self.cross_rules],
        }


@dataclass(frozen=True)
class Activation:
    """Single concrete sporadic job activation (task_id, activation_index)."""

    task_id: str
    activation_index: int
    release: int
    absolute_deadline: int
    execution_units: int

    @property
    def job_id(self) -> tuple[str, int]:
        return (self.task_id, self.activation_index)

    @property
    def process_id(self) -> str:
        return f"P_{self.task_id}_k{self.activation_index}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "activation_index": self.activation_index,
            "job_id": f"{self.task_id}_k{self.activation_index}",
            "process_id": self.process_id,
            "release": self.release,
            "absolute_deadline": self.absolute_deadline,
            "execution_units": self.execution_units,
        }


@dataclass(frozen=True)
class DiscardedActivation:
    """Activation excluded by the horizon policy, recorded explicitly (never silent)."""

    task_id: str
    activation_index: int
    release: int
    absolute_deadline: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "activation_index": self.activation_index,
            "release": self.release,
            "absolute_deadline": self.absolute_deadline,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class GeneratedSequence:
    """Validated, deterministically ordered set of sporadic activations for a scenario."""

    scenario: ScenarioSpec
    activations: tuple[Activation, ...]
    discarded_activations: tuple[DiscardedActivation, ...]
    sequence_hash: str

    def effective_utilization(self) -> float:
        if self.scenario.horizon <= 0:
            return 0.0
        return sum(a.execution_units for a in self.activations) / self.scenario.horizon

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.scenario.schema_version,
            "scenario_id": self.scenario.scenario_id,
            "seed": self.scenario.seed,
            "generation_mode": self.scenario.generation_mode,
            "horizon": self.scenario.horizon,
            "horizon_policy": self.scenario.horizon_policy,
            "time_unit": self.scenario.time_unit,
            "sequence_hash": self.sequence_hash,
            "nominal_utilization": self.scenario.nominal_utilization(),
            "effective_utilization": self.effective_utilization(),
            "activations": [a.to_dict() for a in self.activations],
            "discarded_activations": [d.to_dict() for d in self.discarded_activations],
        }


@dataclass(frozen=True)
class AdaptedSporadicInstance:
    """Frozen finite scheduling instance adapted from a sporadic activation sequence."""

    scenario: ScenarioSpec
    sequence: GeneratedSequence
    instance: SchedulingInstance
    input_hash: str
    segment_to_job: dict[str, tuple[str, int]]
    metadata: dict[str, Any]

    def to_export_dict(self) -> dict[str, Any]:
        inst_dict = self.instance.canonical_dict()
        return {
            "schema_version": self.scenario.schema_version,
            "scenario_id": self.scenario.scenario_id,
            "seed": self.scenario.seed,
            "generation_mode": self.scenario.generation_mode,
            "horizon": self.scenario.horizon,
            "horizon_policy": self.scenario.horizon_policy,
            "time_unit": self.scenario.time_unit,
            "objective": self.scenario.objective,
            "task_specs": [t.to_dict() for t in self.scenario.tasks],
            "cross_rules": [r.to_dict() for r in self.scenario.cross_rules],
            "activations": [a.to_dict() for a in self.sequence.activations],
            "discarded_activations": [
                d.to_dict() for d in self.sequence.discarded_activations
            ],
            "processes": inst_dict["processes"],
            "segments": inst_dict["segments"],
            "precedences": inst_dict["precedence"],
            "exclusions": inst_dict["exclusion"],
            "sequence_hash": self.sequence.sequence_hash,
            "instance_hash": self.instance.instance_hash(),
            "input_hash": self.input_hash,
            "metadata": self.metadata,
        }


def compute_canonical_sha256(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def parse_scenario_spec(data: Any) -> ScenarioSpec:
    """Parse a JSON/dict sporadic scenario configuration into ScenarioSpec."""
    if not isinstance(data, dict):
        raise ValueError("Scenario configuration must be a JSON object.")

    schema_version = str(data.get("schema_version", "sporadic-v1"))
    scenario_id = _require_str(data.get("scenario_id"), "scenario_id")
    horizon = _require_int(data.get("horizon"), "horizon")
    seed = _require_int(data.get("seed", 0), "seed")
    generation_mode = _require_str(
        data.get("generation_mode", "jittered"), "generation_mode"
    )
    jitter_max = _require_int(data.get("jitter_max", 0), "jitter_max")
    burst_size = _require_int(data.get("burst_size", 2), "burst_size")
    burst_gap_raw = data.get("burst_gap")
    burst_gap = _require_int(burst_gap_raw, "burst_gap") if burst_gap_raw is not None else None
    horizon_policy = _require_str(
        data.get("horizon_policy", "deadline_within_horizon"), "horizon_policy"
    )
    allow_unconstrained = bool(data.get("allow_unconstrained_deadlines", False))
    time_unit = _require_str(data.get("time_unit", "logical_unit"), "time_unit")
    objective = _require_str(data.get("objective", "feasibility"), "objective")

    raw_tasks = data.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError("Field 'tasks' must be a non-empty list.")

    tasks: list[TaskSpec] = []
    for idx, t in enumerate(raw_tasks):
        if not isinstance(t, dict):
            raise ValueError(f"tasks[{idx}] must be an object.")
        tid = _require_str(t.get("id"), f"tasks[{idx}].id")
        c_val = _require_int(t.get("C"), f"tasks[{idx}].C")
        d_val = _require_int(t.get("D"), f"tasks[{idx}].D")
        t_val = _require_int(t.get("T"), f"tasks[{idx}].T")
        offset = _require_int(t.get("offset", 0), f"tasks[{idx}].offset")

        segs_raw = t.get("segments")
        seg_templates: list[SegmentTemplate] = []
        if segs_raw is not None:
            if not isinstance(segs_raw, list) or not segs_raw:
                raise ValueError(f"tasks[{idx}].segments must be a non-empty list.")
            for s_idx, s in enumerate(segs_raw):
                if not isinstance(s, dict):
                    raise ValueError(f"tasks[{idx}].segments[{s_idx}] must be an object.")
                sid = _require_str(s.get("id"), f"tasks[{idx}].segments[{s_idx}].id")
                eu = _require_int(
                    s.get("execution_units"),
                    f"tasks[{idx}].segments[{s_idx}].execution_units",
                )
                seg_templates.append(SegmentTemplate(id=sid, execution_units=eu))

        t_mode = t.get("mode")
        if t_mode is not None:
            t_mode = _require_str(t_mode, f"tasks[{idx}].mode")
        t_jmax = t.get("jitter_max")
        if t_jmax is not None:
            t_jmax = _require_int(t_jmax, f"tasks[{idx}].jitter_max")
        t_bsize = t.get("burst_size")
        if t_bsize is not None:
            t_bsize = _require_int(t_bsize, f"tasks[{idx}].burst_size")
        t_bgap = t.get("burst_gap")
        if t_bgap is not None:
            t_bgap = _require_int(t_bgap, f"tasks[{idx}].burst_gap")
        t_expl = t.get("explicit_releases")
        explicit_tuple: tuple[int, ...] | None = None
        if t_expl is not None:
            if not isinstance(t_expl, list):
                raise ValueError(f"tasks[{idx}].explicit_releases must be a list of ints.")
            explicit_tuple = tuple(
                _require_int(v, f"tasks[{idx}].explicit_releases[{r_i}]")
                for r_i, v in enumerate(t_expl)
            )

        tasks.append(
            TaskSpec(
                id=tid,
                C=c_val,
                D=d_val,
                T=t_val,
                offset=offset,
                segments=tuple(seg_templates),
                mode=t_mode,
                jitter_max=t_jmax,
                burst_size=t_bsize,
                burst_gap=t_bgap,
                explicit_releases=explicit_tuple,
            )
        )

    raw_rules = data.get("cross_rules", [])
    if not isinstance(raw_rules, list):
        raise ValueError("Field 'cross_rules' must be a list.")
    rules: list[CrossTaskRule] = []
    for idx, r in enumerate(raw_rules):
        if not isinstance(r, dict):
            raise ValueError(f"cross_rules[{idx}] must be an object.")
        rules.append(
            CrossTaskRule(
                kind=_require_str(r.get("kind"), f"cross_rules[{idx}].kind"),
                src_task=_require_str(r.get("src_task"), f"cross_rules[{idx}].src_task"),
                src_segment=_require_str(
                    r.get("src_segment"), f"cross_rules[{idx}].src_segment"
                ),
                dst_task=_require_str(r.get("dst_task"), f"cross_rules[{idx}].dst_task"),
                dst_segment=_require_str(
                    r.get("dst_segment"), f"cross_rules[{idx}].dst_segment"
                ),
                scope=_require_str(
                    r.get("scope", "all_overlapping"), f"cross_rules[{idx}].scope"
                ),
            )
        )

    return ScenarioSpec(
        schema_version=schema_version,
        scenario_id=scenario_id,
        horizon=horizon,
        seed=seed,
        generation_mode=generation_mode,
        tasks=tuple(tasks),
        cross_rules=tuple(rules),
        jitter_max=jitter_max,
        burst_size=burst_size,
        burst_gap=burst_gap,
        horizon_policy=horizon_policy,
        allow_unconstrained_deadlines=allow_unconstrained,
        time_unit=time_unit,
        objective=objective,
    )


def load_scenario_spec(path: str | Path) -> ScenarioSpec:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_scenario_spec(raw)
