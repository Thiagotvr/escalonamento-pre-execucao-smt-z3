"""Loading, parsing, validation, and saving of scheduling instances."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import (
    VALID_OBJECTIVES,
    InvalidInputError,
    ProcessSpec,
    SchedulingInstance,
    SegmentSpec,
)


def _require_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidInputError(
            f"Field {field_name!r} must be an integer, got {type(value).__name__}."
        )
    return value


def _require_non_empty_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidInputError(f"Field {field_name!r} must be a non-empty string.")
    return value


def _parse_pair_list(
    raw_pairs: Any, field_name: str, valid_segments: set[str]
) -> list[tuple[str, str]]:
    if not isinstance(raw_pairs, list):
        raise InvalidInputError(f"Field {field_name!r} must be a list of pairs.")
    pairs: list[tuple[str, str]] = []
    for idx, item in enumerate(raw_pairs):
        if not isinstance(item, list) or len(item) != 2:
            raise InvalidInputError(
                f"Entry {idx} in {field_name!r} must be a 2-element list."
            )
        src = _require_non_empty_str(item[0], f"{field_name}[{idx}][0]")
        dst = _require_non_empty_str(item[1], f"{field_name}[{idx}][1]")
        if src not in valid_segments:
            raise InvalidInputError(
                f"Unknown segment {src!r} referenced in {field_name}[{idx}]."
            )
        if dst not in valid_segments:
            raise InvalidInputError(
                f"Unknown segment {dst!r} referenced in {field_name}[{idx}]."
            )
        pairs.append((src, dst))
    return pairs


def _dedup_preserve_order(pairs: list[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for pair in pairs:
        if pair not in seen:
            seen.add(pair)
            result.append(pair)
    return tuple(result)


def parse_instance(data: Any) -> SchedulingInstance:
    """Parse and validate the schema of a scheduling instance dictionary.

    Distinguishes structural format errors (raises InvalidInputError) from
    mathematical infeasibility (e.g., cyclic precedence or impossible deadlines),
    which are preserved so planners diagnose them mathematically.
    """
    if not isinstance(data, dict):
        raise InvalidInputError("Instance payload must be a JSON object.")

    schema_version = _require_int(data.get("schema_version"), "schema_version")
    if schema_version != 1:
        raise InvalidInputError(f"Unsupported schema_version: {schema_version}")

    instance_id = _require_non_empty_str(data.get("instance_id"), "instance_id")
    objective = data.get("objective", "feasibility")
    if not isinstance(objective, str) or objective not in VALID_OBJECTIVES:
        raise InvalidInputError(
            f"Field 'objective' must be one of {sorted(VALID_OBJECTIVES)}, got {objective!r}."
        )

    raw_segments = data.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise InvalidInputError("Field 'segments' must be a non-empty list.")

    segments: list[SegmentSpec] = []
    segment_ids: set[str] = set()
    for idx, seg in enumerate(raw_segments):
        if not isinstance(seg, dict):
            raise InvalidInputError(f"segments[{idx}] must be an object.")
        seg_id = _require_non_empty_str(seg.get("id"), f"segments[{idx}].id")
        if seg_id in segment_ids:
            raise InvalidInputError(f"Duplicate segment id: {seg_id!r}.")
        release = _require_int(seg.get("release"), f"segments[{idx}].release")
        if release < 0:
            raise InvalidInputError(
                f"Segment {seg_id!r} release must be >= 0, got {release}."
            )
        execution_units = _require_int(
            seg.get("execution_units"), f"segments[{idx}].execution_units"
        )
        if execution_units <= 0:
            raise InvalidInputError(
                f"Segment {seg_id!r} execution_units must be > 0, got {execution_units}."
            )
        deadline = _require_int(seg.get("deadline"), f"segments[{idx}].deadline")
        segment_ids.add(seg_id)
        segments.append(
            SegmentSpec(
                id=seg_id,
                release=release,
                execution_units=execution_units,
                deadline=deadline,
            )
        )

    raw_processes = data.get("processes")
    if not isinstance(raw_processes, list) or not raw_processes:
        raise InvalidInputError("Field 'processes' must be a non-empty list.")

    processes: list[ProcessSpec] = []
    process_ids: set[str] = set()
    assigned_segments: set[str] = set()
    process_precedence: list[tuple[str, str]] = []

    for idx, proc in enumerate(raw_processes):
        if not isinstance(proc, dict):
            raise InvalidInputError(f"processes[{idx}] must be an object.")
        proc_id = _require_non_empty_str(proc.get("id"), f"processes[{idx}].id")
        if proc_id in process_ids:
            raise InvalidInputError(f"Duplicate process id: {proc_id!r}.")
        proc_segs_raw = proc.get("segments")
        if not isinstance(proc_segs_raw, list) or not proc_segs_raw:
            raise InvalidInputError(
                f"Process {proc_id!r} must have a non-empty 'segments' list."
            )
        proc_segs: list[str] = []
        for s_idx, s_id in enumerate(proc_segs_raw):
            seg_id = _require_non_empty_str(
                s_id, f"processes[{idx}].segments[{s_idx}]"
            )
            if seg_id not in segment_ids:
                raise InvalidInputError(
                    f"Process {proc_id!r} references unknown segment {seg_id!r}."
                )
            if seg_id in assigned_segments:
                raise InvalidInputError(
                    f"Segment {seg_id!r} appears more than once across processes."
                )
            assigned_segments.add(seg_id)
            proc_segs.append(seg_id)

        for a, b in zip(proc_segs, proc_segs[1:]):
            process_precedence.append((a, b))

        process_ids.add(proc_id)
        processes.append(ProcessSpec(id=proc_id, segments=tuple(proc_segs)))

    unassigned = segment_ids - assigned_segments
    if unassigned:
        raise InvalidInputError(
            f"Segments not assigned to any process: {sorted(unassigned)}."
        )

    explicit_precedence = _parse_pair_list(
        data.get("precedence", []), "precedence", segment_ids
    )
    # Never auto-symmetrize exclusion pairs!
    exclusion_pairs = _parse_pair_list(
        data.get("exclusion", []), "exclusion", segment_ids
    )

    all_precedence = _dedup_preserve_order(process_precedence + explicit_precedence)
    dedup_raw_precedence = _dedup_preserve_order(explicit_precedence)
    dedup_exclusion = _dedup_preserve_order(exclusion_pairs)

    return SchedulingInstance(
        schema_version=schema_version,
        instance_id=instance_id,
        objective=objective,
        processes=tuple(processes),
        segments=tuple(segments),
        precedence=all_precedence,
        exclusion=dedup_exclusion,
        raw_precedence=dedup_raw_precedence,
    )


def load_instance(path: str | Path) -> SchedulingInstance:
    """Load and parse a scheduling instance from a JSON file."""
    file_path = Path(path)
    try:
        raw_text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvalidInputError(f"Could not read instance file {file_path}: {exc}") from exc
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise InvalidInputError(f"Invalid JSON in {file_path}: {exc}") from exc
    return parse_instance(data)


def save_instance(instance: SchedulingInstance, path: str | Path) -> None:
    """Persist a scheduling instance to JSON."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(instance.canonical_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
