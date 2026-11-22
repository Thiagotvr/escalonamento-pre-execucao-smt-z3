"""Shared cooperative schedule executor supporting logical and timed execution modes."""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .application import TaskRegistry, WorkloadError, compute_file_sha256
from .model import Schedule, SchedulingInstance, collect_versions
from .validator import validate_schedule


@dataclass(frozen=True)
class TimingConfig:
    mode: str = "logical"  # "logical" or "timed"
    quantum_ns: int | None = None
    lead_time_ns: int = 2_000_000
    spin_threshold_ns: int = 1_000_000
    allow_invalid_schedule: bool = False

    def __post_init__(self) -> None:
        if self.mode not in {"logical", "timed"}:
            raise ValueError(f"Unsupported execution mode: {self.mode!r}")
        if self.mode == "timed":
            if self.quantum_ns is None or self.quantum_ns <= 0:
                raise ValueError("Timed mode requires quantum_ns > 0.")


@dataclass(frozen=True)
class UnitTrace:
    segment_id: str
    unit_index: int
    start_tick: int
    planned_start_ns: int | None
    planned_end_ns: int | None
    actual_start_ns: int
    actual_end_ns: int
    dispatch_lateness_ns: int
    work_elapsed_ns: int
    cpu_elapsed_ns: int
    slot_overrun_ns: int
    done: bool
    exception: str | None
    state_version: int | None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "unit_index": self.unit_index,
            "start_tick": self.start_tick,
            "planned_start_ns": self.planned_start_ns,
            "planned_end_ns": self.planned_end_ns,
            "actual_start_ns": self.actual_start_ns,
            "actual_end_ns": self.actual_end_ns,
            "dispatch_lateness_ns": self.dispatch_lateness_ns,
            "work_elapsed_ns": self.work_elapsed_ns,
            "cpu_elapsed_ns": self.cpu_elapsed_ns,
            "slot_overrun_ns": self.slot_overrun_ns,
            "done": self.done,
            "exception": self.exception,
            "state_version": self.state_version,
            "details": self.details,
        }


@dataclass(frozen=True)
class SegmentTimingSummary:
    segment_id: str
    logical_release_tick: int
    logical_start_tick: int
    logical_end_tick: int
    logical_deadline_tick: int
    planned_release_ns: int | None
    planned_deadline_ns: int | None
    logical_completion_ns: int | None
    actual_start_ns: int | None
    actual_end_ns: int | None
    physical_deadline_met: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "logical_release_tick": self.logical_release_tick,
            "logical_start_tick": self.logical_start_tick,
            "logical_end_tick": self.logical_end_tick,
            "logical_deadline_tick": self.logical_deadline_tick,
            "planned_release_ns": self.planned_release_ns,
            "planned_deadline_ns": self.planned_deadline_ns,
            "logical_completion_ns": self.logical_completion_ns,
            "actual_start_ns": self.actual_start_ns,
            "actual_end_ns": self.actual_end_ns,
            "physical_deadline_met": self.physical_deadline_met,
        }


@dataclass
class ExecutionReport:
    status: str  # "ok", "invalid_schedule", "runtime_budget_violation", "runtime_dispatch_violation", "workload_error"
    mode: str
    instance_id: str
    instance_hash: str
    quantum_ns: int | None
    epoch_ns: int | None
    total_wall_ns: int
    total_cpu_ns: int
    units_executed: int
    total_expected_units: int
    max_dispatch_lateness_ns: int
    max_work_elapsed_ns: int
    max_slot_overrun_ns: int
    failed_unit: dict[str, Any] | None
    error_message: str | None
    traces: list[UnitTrace]
    segment_timings: list[SegmentTimingSummary]
    final_shared_state: dict[str, Any]
    recorded_copy: dict[str, Any] | None
    output_path: str
    input_path: str
    input_hash: str | None
    application_config: dict[str, Any]
    versions: dict[str, str]
    validation_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "mode": self.mode,
            "instance_id": self.instance_id,
            "instance_hash": self.instance_hash,
            "quantum_ns": self.quantum_ns,
            "epoch_ns": self.epoch_ns,
            "total_wall_ns": self.total_wall_ns,
            "total_cpu_ns": self.total_cpu_ns,
            "units_executed": self.units_executed,
            "total_expected_units": self.total_expected_units,
            "max_dispatch_lateness_ns": self.max_dispatch_lateness_ns,
            "max_work_elapsed_ns": self.max_work_elapsed_ns,
            "max_slot_overrun_ns": self.max_slot_overrun_ns,
            "failed_unit": self.failed_unit,
            "error_message": self.error_message,
            "validation_errors": self.validation_errors,
            "traces": [t.to_dict() for t in self.traces],
            "segment_timings": [s.to_dict() for s in self.segment_timings],
            "final_shared_state": self.final_shared_state,
            "recorded_copy": self.recorded_copy,
            "output_path": self.output_path,
            "input_path": self.input_path,
            "input_hash": self.input_hash,
            "application_config": self.application_config,
            "versions": self.versions,
        }


def _wait_until(target_ns: int, spin_threshold_ns: int) -> None:
    """Wait until monotonic perf_counter_ns reaches target_ns using absolute deadlines."""
    while True:
        remaining = target_ns - time.perf_counter_ns()
        if remaining <= 0:
            return
        if remaining > spin_threshold_ns:
            sleep_sec = (remaining - spin_threshold_ns) / 1_000_000_000.0
            if sleep_sec > 0:
                time.sleep(sleep_sec)
        else:
            # Fine-grained wait for final sub-millisecond stretch
            while time.perf_counter_ns() < target_ns:
                pass
            return


def _verify_tasks_match_instance(
    instance: SchedulingInstance, tasks: TaskRegistry
) -> list[str]:
    errors: list[str] = []
    for seg in instance.segments:
        if seg.id not in tasks.tasks:
            errors.append(f"Missing task implementation for segment {seg.id!r}.")
            continue
        task = tasks.tasks[seg.id]
        if task.expected_units != seg.execution_units:
            errors.append(
                f"Task {seg.id!r} expects {task.expected_units} units, "
                f"but instance specifies {seg.execution_units}."
            )
    return errors


def _build_segment_timings(
    instance: SchedulingInstance,
    schedule: Schedule,
    traces: list[UnitTrace],
    epoch_ns: int | None,
    quantum_ns: int | None,
) -> list[SegmentTimingSummary]:
    bounds = schedule.segment_bounds()
    traces_by_seg: dict[str, list[UnitTrace]] = {}
    for tr in traces:
        traces_by_seg.setdefault(tr.segment_id, []).append(tr)

    summaries: list[SegmentTimingSummary] = []
    for seg in instance.segments:
        if seg.id not in bounds:
            continue
        s_tick, f_tick = bounds[seg.id]
        seg_traces = traces_by_seg.get(seg.id, [])
        actual_start = seg_traces[0].actual_start_ns if seg_traces else None
        actual_end = (
            seg_traces[-1].actual_end_ns
            if len(seg_traces) == seg.execution_units and seg_traces[-1].done
            else None
        )
        if epoch_ns is not None and quantum_ns is not None:
            planned_rel = epoch_ns + seg.release * quantum_ns
            planned_dl = epoch_ns + seg.deadline * quantum_ns
            logical_comp = epoch_ns + f_tick * quantum_ns
            dl_met = (actual_end <= planned_dl) if actual_end is not None else False
        else:
            planned_rel = None
            planned_dl = None
            logical_comp = None
            dl_met = None

        summaries.append(
            SegmentTimingSummary(
                segment_id=seg.id,
                logical_release_tick=seg.release,
                logical_start_tick=s_tick,
                logical_end_tick=f_tick,
                logical_deadline_tick=seg.deadline,
                planned_release_ns=planned_rel,
                planned_deadline_ns=planned_dl,
                logical_completion_ns=logical_comp,
                actual_start_ns=actual_start,
                actual_end_ns=actual_end,
                physical_deadline_met=dl_met,
            )
        )
    return summaries


def execute_schedule(
    instance: SchedulingInstance,
    schedule: Schedule,
    tasks: TaskRegistry,
    timing_config: TimingConfig | None = None,
) -> ExecutionReport:
    """Execute a verified schedule cooperatively over real application tasks."""
    cfg = timing_config or TimingConfig(mode="logical")
    versions = collect_versions()
    ctx = tasks.context
    input_hash = (
        compute_file_sha256(ctx.input_path) if Path(ctx.input_path).exists() else None
    )

    val_report = validate_schedule(instance, schedule, require_deadlines=True)
    task_errors = _verify_tasks_match_instance(instance, tasks)
    all_pre_errors = list(val_report.errors) + task_errors

    if task_errors or (not val_report.ok and not cfg.allow_invalid_schedule):
        return ExecutionReport(
            status="invalid_schedule",
            mode=cfg.mode,
            instance_id=instance.instance_id,
            instance_hash=instance.instance_hash(),
            quantum_ns=cfg.quantum_ns,
            epoch_ns=None,
            total_wall_ns=0,
            total_cpu_ns=0,
            units_executed=0,
            total_expected_units=instance.total_units(),
            max_dispatch_lateness_ns=0,
            max_work_elapsed_ns=0,
            max_slot_overrun_ns=0,
            failed_unit=None,
            error_message="; ".join(all_pre_errors),
            traces=[],
            segment_timings=[],
            final_shared_state=ctx.shared_state.to_dict(),
            recorded_copy=copy.deepcopy(ctx.private_copy),
            output_path=str(ctx.output_path),
            input_path=str(ctx.input_path),
            input_hash=input_hash,
            application_config=ctx.config.to_dict(),
            versions=versions,
            validation_errors=all_pre_errors,
        )

    ordered = schedule.sorted_units()
    traces: list[UnitTrace] = []
    status = "ok"
    failed_unit: dict[str, Any] | None = None
    error_message: str | None = None

    epoch_ns: int | None = None
    quantum_ns = cfg.quantum_ns if cfg.mode == "timed" else None
    if cfg.mode == "timed":
        epoch_ns = time.perf_counter_ns() + cfg.lead_time_ns

    wall_start = time.perf_counter_ns()
    cpu_start = time.process_time_ns()

    try:
        for unit in ordered:
            task = tasks.get(unit.segment_id)
            if epoch_ns is not None and quantum_ns is not None:
                planned_start = epoch_ns + unit.start_tick * quantum_ns
                planned_end = epoch_ns + (unit.start_tick + 1) * quantum_ns
                _wait_until(planned_start, cfg.spin_threshold_ns)
            else:
                planned_start = None
                planned_end = None

            actual_start = time.perf_counter_ns()
            unit_cpu_start = time.process_time_ns()

            if planned_start is not None and planned_end is not None:
                dispatch_lateness = max(0, actual_start - planned_start)
                if actual_start >= planned_end:
                    slot_overrun = actual_start - planned_end
                    tr = UnitTrace(
                        segment_id=unit.segment_id,
                        unit_index=unit.unit_index,
                        start_tick=unit.start_tick,
                        planned_start_ns=planned_start,
                        planned_end_ns=planned_end,
                        actual_start_ns=actual_start,
                        actual_end_ns=actual_start,
                        dispatch_lateness_ns=dispatch_lateness,
                        work_elapsed_ns=0,
                        cpu_elapsed_ns=0,
                        slot_overrun_ns=slot_overrun,
                        done=False,
                        exception="runtime_dispatch_violation",
                        state_version=ctx.shared_state.version,
                    )
                    traces.append(tr)
                    status = "runtime_dispatch_violation"
                    failed_unit = unit.to_dict()
                    error_message = (
                        f"Unit ({unit.segment_id}, {unit.unit_index}) missed its entire slot "
                        f"at tick {unit.start_tick} (dispatch_lateness_ns={dispatch_lateness})."
                    )
                    break
            else:
                dispatch_lateness = 0

            exc_text: str | None = None
            done = False
            state_version: int | None = None
            details: dict[str, Any] = {}
            try:
                res = task.step(unit.unit_index)
                done = res.done
                state_version = res.state_version
                details = res.details
            except Exception as exc:
                exc_text = f"{type(exc).__name__}: {exc}"
                state_version = ctx.shared_state.version

            actual_end = time.perf_counter_ns()
            unit_cpu_end = time.process_time_ns()
            work_elapsed = actual_end - actual_start
            cpu_elapsed = unit_cpu_end - unit_cpu_start
            slot_overrun = (
                max(0, actual_end - planned_end) if planned_end is not None else 0
            )

            tr = UnitTrace(
                segment_id=unit.segment_id,
                unit_index=unit.unit_index,
                start_tick=unit.start_tick,
                planned_start_ns=planned_start,
                planned_end_ns=planned_end,
                actual_start_ns=actual_start,
                actual_end_ns=actual_end,
                dispatch_lateness_ns=dispatch_lateness,
                work_elapsed_ns=work_elapsed,
                cpu_elapsed_ns=cpu_elapsed,
                slot_overrun_ns=slot_overrun,
                done=done,
                exception=exc_text,
                state_version=state_version,
                details=details,
            )
            traces.append(tr)

            if exc_text is not None:
                status = "workload_error"
                failed_unit = unit.to_dict()
                error_message = exc_text
                break

            if planned_end is not None and actual_end > planned_end:
                status = "runtime_budget_violation"
                failed_unit = unit.to_dict()
                error_message = (
                    f"Unit ({unit.segment_id}, {unit.unit_index}) exceeded reserved slot "
                    f"at tick {unit.start_tick} by {slot_overrun} ns "
                    f"(work_elapsed_ns={work_elapsed}, quantum_ns={quantum_ns})."
                )
                break
    finally:
        tasks.cleanup()

    total_wall = time.perf_counter_ns() - wall_start
    total_cpu = time.process_time_ns() - cpu_start
    max_dispatch = max((t.dispatch_lateness_ns for t in traces), default=0)
    max_work = max((t.work_elapsed_ns for t in traces), default=0)
    max_overrun = max((t.slot_overrun_ns for t in traces), default=0)
    seg_timings = _build_segment_timings(instance, schedule, traces, epoch_ns, quantum_ns)

    return ExecutionReport(
        status=status,
        mode=cfg.mode,
        instance_id=instance.instance_id,
        instance_hash=instance.instance_hash(),
        quantum_ns=quantum_ns,
        epoch_ns=epoch_ns,
        total_wall_ns=total_wall,
        total_cpu_ns=total_cpu,
        units_executed=len(traces),
        total_expected_units=instance.total_units(),
        max_dispatch_lateness_ns=max_dispatch,
        max_work_elapsed_ns=max_work,
        max_slot_overrun_ns=max_overrun,
        failed_unit=failed_unit,
        error_message=error_message,
        traces=traces,
        segment_timings=seg_timings,
        final_shared_state=ctx.shared_state.to_dict(),
        recorded_copy=copy.deepcopy(ctx.private_copy),
        output_path=str(ctx.output_path),
        input_path=str(ctx.input_path),
        input_hash=input_hash,
        application_config=ctx.config.to_dict(),
        versions=versions,
        validation_errors=all_pre_errors,
    )
