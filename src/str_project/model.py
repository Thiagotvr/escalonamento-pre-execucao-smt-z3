"""Core data models for scheduling instances, schedules, validation, and planning results."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import dataclass, field
from typing import Any

from . import __version__

VALID_OBJECTIVES = frozenset({"feasibility", "min_lmax"})
VALID_PLANNING_STATUSES = frozenset(
    {
        "feasible",
        "infeasible",
        "timeout",
        "unknown",
        "invalid_input",
        "implementation_error",
    }
)


class InvalidInputError(ValueError):
    """Raised when an input instance or artifact is structurally malformed."""


@dataclass(frozen=True)
class ProcessSpec:
    id: str
    segments: tuple[str, ...]


@dataclass(frozen=True)
class SegmentSpec:
    id: str
    release: int
    execution_units: int
    deadline: int


@dataclass(frozen=True)
class SchedulingInstance:
    schema_version: int
    instance_id: str
    objective: str
    processes: tuple[ProcessSpec, ...]
    segments: tuple[SegmentSpec, ...]
    precedence: tuple[tuple[str, str], ...]
    exclusion: tuple[tuple[str, str], ...]
    raw_precedence: tuple[tuple[str, str], ...] = ()

    def segment_map(self) -> dict[str, SegmentSpec]:
        return {seg.id: seg for seg in self.segments}

    def segment_ids(self) -> tuple[str, ...]:
        return tuple(seg.id for seg in self.segments)

    def total_units(self) -> int:
        return sum(seg.execution_units for seg in self.segments)

    def with_objective(self, objective: str) -> SchedulingInstance:
        if objective not in VALID_OBJECTIVES:
            raise InvalidInputError(f"Unsupported objective: {objective!r}")
        return SchedulingInstance(
            schema_version=self.schema_version,
            instance_id=self.instance_id,
            objective=objective,
            processes=self.processes,
            segments=self.segments,
            precedence=self.precedence,
            exclusion=self.exclusion,
            raw_precedence=self.raw_precedence,
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "instance_id": self.instance_id,
            "objective": self.objective,
            "processes": [
                {"id": p.id, "segments": list(p.segments)} for p in self.processes
            ],
            "segments": [
                {
                    "id": s.id,
                    "release": s.release,
                    "execution_units": s.execution_units,
                    "deadline": s.deadline,
                }
                for s in self.segments
            ],
            "precedence": [list(pair) for pair in self.precedence],
            "exclusion": [list(pair) for pair in self.exclusion],
        }

    def instance_hash(self) -> str:
        payload = json.dumps(
            self.canonical_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class UnitPlacement:
    segment_id: str
    unit_index: int
    start_tick: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "unit_index": self.unit_index,
            "start_tick": self.start_tick,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UnitPlacement:
        return cls(
            segment_id=str(data["segment_id"]),
            unit_index=int(data["unit_index"]),
            start_tick=int(data["start_tick"]),
        )


@dataclass(frozen=True)
class Schedule:
    units: tuple[UnitPlacement, ...]

    def sorted_units(self) -> tuple[UnitPlacement, ...]:
        return tuple(
            sorted(
                self.units,
                key=lambda u: (u.start_tick, u.segment_id, u.unit_index),
            )
        )

    def segment_bounds(self) -> dict[str, tuple[int, int]]:
        by_seg: dict[str, list[UnitPlacement]] = {}
        for u in self.units:
            by_seg.setdefault(u.segment_id, []).append(u)
        bounds: dict[str, tuple[int, int]] = {}
        for seg_id, placements in by_seg.items():
            ordered = sorted(placements, key=lambda u: u.unit_index)
            bounds[seg_id] = (ordered[0].start_tick, ordered[-1].start_tick + 1)
        return bounds

    def segment_lateness(self, instance: SchedulingInstance) -> dict[str, int]:
        bounds = self.segment_bounds()
        return {
            seg.id: bounds[seg.id][1] - seg.deadline
            for seg in instance.segments
            if seg.id in bounds
        }

    def compute_lmax(self, instance: SchedulingInstance) -> int:
        lateness = self.segment_lateness(instance)
        if not lateness:
            raise ValueError("Cannot compute Lmax for an empty schedule.")
        return max(lateness.values())

    def idle_intervals(self) -> list[tuple[int, int]]:
        ordered = self.sorted_units()
        if not ordered:
            return []
        intervals: list[tuple[int, int]] = []
        if ordered[0].start_tick > 0:
            intervals.append((0, ordered[0].start_tick))
        for prev, curr in zip(ordered, ordered[1:]):
            if curr.start_tick > prev.start_tick + 1:
                intervals.append((prev.start_tick + 1, curr.start_tick))
        return intervals

    def merged_intervals(self) -> list[dict[str, Any]]:
        """Group contiguous units of the same segment strictly for display/reporting."""
        ordered = self.sorted_units()
        if not ordered:
            return []
        merged: list[dict[str, Any]] = []
        cur_seg = ordered[0].segment_id
        cur_start = ordered[0].start_tick
        cur_end = cur_start + 1
        cur_first_u = ordered[0].unit_index
        cur_last_u = ordered[0].unit_index
        for u in ordered[1:]:
            if u.segment_id == cur_seg and u.start_tick == cur_end:
                cur_end = u.start_tick + 1
                cur_last_u = u.unit_index
            else:
                merged.append(
                    {
                        "segment_id": cur_seg,
                        "start_tick": cur_start,
                        "end_tick": cur_end,
                        "unit_indices": [cur_first_u, cur_last_u],
                    }
                )
                cur_seg = u.segment_id
                cur_start = u.start_tick
                cur_end = u.start_tick + 1
                cur_first_u = u.unit_index
                cur_last_u = u.unit_index
        merged.append(
            {
                "segment_id": cur_seg,
                "start_tick": cur_start,
                "end_tick": cur_end,
                "unit_indices": [cur_first_u, cur_last_u],
            }
        )
        return merged

    def to_dict(self) -> dict[str, Any]:
        return {
            "units": [u.to_dict() for u in self.sorted_units()],
            "merged_view": self.merged_intervals(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Schedule:
        units = tuple(UnitPlacement.from_dict(item) for item in data["units"])
        return cls(units=units)


@dataclass(frozen=True)
class PlanningLimits:
    timeout_ms: int = 30_000
    max_nodes: int | None = None
    save_smt2_path: str | None = None
    record_search_trace: bool = False


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    feasible: bool
    require_deadlines: bool
    errors: tuple[str, ...]
    logical_lmax: int | None
    segment_bounds: dict[str, tuple[int, int]]

    @property
    def ok(self) -> bool:
        return self.feasible if self.require_deadlines else self.valid

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "valid": self.valid,
            "feasible": self.feasible,
            "require_deadlines": self.require_deadlines,
            "logical_lmax": self.logical_lmax,
            "errors": list(self.errors),
            "segment_bounds": {
                k: [v[0], v[1]] for k, v in sorted(self.segment_bounds.items())
            },
        }


@dataclass
class PlanningResult:
    instance_id: str
    instance_hash: str
    planner: str
    objective: str
    status: str
    schedule: Schedule | None
    logical_lmax: int | None
    reason: str | None
    preprocessing_ns: int | None
    model_build_ns: int | None
    search_ns: int | None
    total_planning_ns: int | None
    nodes_generated: int | None
    nodes_expanded: int | None
    lower_bound: int | None
    versions: dict[str, str]
    validation: ValidationReport | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in VALID_PLANNING_STATUSES:
            raise ValueError(f"Invalid planning status: {self.status!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "instance_hash": self.instance_hash,
            "planner": self.planner,
            "objective": self.objective,
            "status": self.status,
            "schedule": self.schedule.to_dict() if self.schedule is not None else None,
            "logical_lmax": self.logical_lmax,
            "reason": self.reason,
            "preprocessing_ns": self.preprocessing_ns,
            "model_build_ns": self.model_build_ns,
            "search_ns": self.search_ns,
            "total_planning_ns": self.total_planning_ns,
            "nodes_generated": self.nodes_generated,
            "nodes_expanded": self.nodes_expanded,
            "lower_bound": self.lower_bound,
            "versions": dict(self.versions),
            "validation": self.validation.to_dict() if self.validation else None,
            "details": self.details,
        }


def collect_versions() -> dict[str, str]:
    """Collect runtime versions for reproducibility and reporting."""
    try:
        import z3

        z3_version = z3.get_version_string()
    except Exception:
        z3_version = "unavailable"
    return {
        "str_project": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "z3": z3_version,
    }
