"""Persistence helpers for schedules, planning results, and reference fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import InvalidInputError, PlanningResult, Schedule, UnitPlacement


def save_planning_result(result: PlanningResult, path: str | Path) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_planning_payload(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidInputError(f"Could not load JSON from {file_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise InvalidInputError(f"Expected JSON object in {file_path}.")
    return data


def save_schedule(schedule: Schedule, path: str | Path) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(schedule.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_schedule(path: str | Path) -> Schedule:
    """Load a Schedule either from a standalone schedule JSON or a PlanningResult JSON."""
    data = load_planning_payload(path)
    if "units" in data:
        sched_dict = data
    elif "schedule" in data:
        if data["schedule"] is None:
            raise InvalidInputError(
                f"Planning artifact {path} has status={data.get('status')!r} and no schedule."
            )
        sched_dict = data["schedule"]
    else:
        raise InvalidInputError(
            f"File {path} does not contain 'units' or 'schedule' fields."
        )
    try:
        return Schedule.from_dict(sched_dict)
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidInputError(f"Malformed schedule data in {path}: {exc}") from exc


def build_schedule_from_blocks(blocks: list[tuple[str, int, int]]) -> Schedule:
    """Helper to build unit-level schedules from contiguous (segment_id, start, end) blocks."""
    next_idx: dict[str, int] = {}
    units: list[UnitPlacement] = []
    for seg_id, start, end in blocks:
        if end <= start:
            raise ValueError(f"Block for {seg_id} must have end > start, got [{start}, {end}).")
        idx = next_idx.get(seg_id, 1)
        for tick in range(start, end):
            units.append(UnitPlacement(segment_id=seg_id, unit_index=idx, start_tick=tick))
            idx += 1
        next_idx[seg_id] = idx
    return Schedule(units=tuple(units))


def known_integration_schedule() -> Schedule:
    """Reference 19-unit valid schedule from Section 10 of the specification.

    Preempts A4 around S and lets P3 record initial state E0 (version 0).
    """
    return build_schedule_from_blocks(
        [
            ("A1", 0, 2),
            ("A2", 2, 3),
            ("A3", 3, 6),
            ("A4", 6, 8),
            ("S", 8, 10),
            ("A4", 10, 12),
            ("A5", 12, 13),
            ("A6", 13, 14),
            ("A7", 14, 16),
            ("A8", 16, 19),
        ]
    )


def known_version1_schedule() -> Schedule:
    """Reference 19-unit valid schedule where A7 finishes before S, so P3 records version 1."""
    return build_schedule_from_blocks(
        [
            ("A1", 0, 2),
            ("A2", 2, 3),
            ("A3", 3, 6),
            ("A4", 6, 10),
            ("A5", 10, 11),
            ("A6", 11, 12),
            ("A7", 12, 14),
            ("S", 14, 16),
            ("A8", 16, 19),
        ]
    )


def known_invalid_interleaved_schedule() -> Schedule:
    """Deliberately invalid schedule that interleaves A7 and S (violates A7 EXCLUDES S)."""
    return build_schedule_from_blocks(
        [
            ("A1", 0, 2),
            ("A2", 2, 3),
            ("A3", 3, 6),
            ("A4", 6, 10),
            ("A5", 10, 11),
            ("A6", 11, 12),
            ("A7", 12, 13),
            ("S", 13, 14),
            ("A7", 14, 15),
            ("S", 15, 16),
            ("A8", 16, 19),
        ]
    )
