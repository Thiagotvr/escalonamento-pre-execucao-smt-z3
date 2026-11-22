"""Experimental physical quantum calibration for timed schedule execution (Section 11)."""

from __future__ import annotations

import json
import math
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .application import (
    ApplicationConfig,
    build_tasks,
    compute_file_sha256,
    default_application_config,
)
from .executor import TimingConfig, execute_schedule
from .model import Schedule, SchedulingInstance, collect_versions
from .schedule_io import known_integration_schedule


def _percentile(sorted_vals: list[int], p: float) -> int:
    if not sorted_vals:
        return 0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = (len(sorted_vals) - 1) * (p / 100.0)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return sorted_vals[lo]
    frac = idx - lo
    return int(round(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac))


def _summarize_samples(samples: list[int]) -> dict[str, int]:
    ordered = sorted(samples)
    return {
        "count": len(ordered),
        "min_ns": ordered[0] if ordered else 0,
        "median_ns": _percentile(ordered, 50.0),
        "p95_ns": _percentile(ordered, 95.0),
        "p99_ns": _percentile(ordered, 99.0),
        "max_ns": ordered[-1] if ordered else 0,
    }


@dataclass
class CalibrationResult:
    quantum_ns: int
    safety_factor: float
    min_margin_ns: int
    repetitions: int
    warmup_runs: int
    instance_id: str
    instance_hash: str
    input_path: str
    input_hash: str
    application_config: dict[str, Any]
    global_work_stats: dict[str, int]
    dispatch_probe_stats: dict[str, int]
    per_unit_stats: dict[str, dict[str, int]]
    versions: dict[str, str]
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "quantum_ns": self.quantum_ns,
            "safety_factor": self.safety_factor,
            "min_margin_ns": self.min_margin_ns,
            "repetitions": self.repetitions,
            "warmup_runs": self.warmup_runs,
            "instance_id": self.instance_id,
            "instance_hash": self.instance_hash,
            "input_path": self.input_path,
            "input_hash": self.input_hash,
            "application_config": self.application_config,
            "global_work_stats": self.global_work_stats,
            "dispatch_probe_stats": self.dispatch_probe_stats,
            "per_unit_stats": self.per_unit_stats,
            "versions": self.versions,
            "notes": self.notes,
        }


def _round_up_ns(value_ns: int, step_ns: int = 100_000) -> int:
    """Round nanoseconds up to a clean boundary (default 0.1 ms)."""
    return ((value_ns + step_ns - 1) // step_ns) * step_ns


def _measure_dispatch_overhead(probes: int = 20) -> list[int]:
    """Measure wake-up jitter of sleep+spin targeting 1 ms future absolute timestamps."""
    latenesses: list[int] = []
    for _ in range(probes):
        target = time.perf_counter_ns() + 1_000_000
        while True:
            rem = target - time.perf_counter_ns()
            if rem <= 0:
                break
            if rem > 500_000:
                time.sleep((rem - 500_000) / 1e9)
            else:
                while time.perf_counter_ns() < target:
                    pass
                break
        latenesses.append(max(0, time.perf_counter_ns() - target))
    return latenesses


def calibrate_quantum(
    instance: SchedulingInstance,
    input_path: str | Path,
    application_config: ApplicationConfig | None = None,
    *,
    schedule: Schedule | None = None,
    repetitions: int = 20,
    warmup_runs: int = 3,
    safety_factor: float = 4.0,
    min_margin_ns: int = 1_500_000,
) -> CalibrationResult:
    """Calibrate physical quantum_ns empirically over fresh executions of the real workload."""
    if repetitions < 1:
        raise ValueError("repetitions must be >= 1.")
    if warmup_runs < 0:
        raise ValueError("warmup_runs must be >= 0.")
    if safety_factor < 1.0:
        raise ValueError("safety_factor must be >= 1.0.")

    cfg = application_config or default_application_config()
    sched = schedule or known_integration_schedule()
    in_path = Path(input_path)
    input_hash = compute_file_sha256(in_path)

    per_unit_samples: dict[str, list[int]] = {}
    all_work_samples: list[int] = []

    with tempfile.TemporaryDirectory(prefix="str_calib_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        total_runs = warmup_runs + repetitions
        for run_idx in range(total_runs):
            out_file = tmp_root / f"calib_out_{run_idx}.json"
            tasks = build_tasks(cfg, in_path, out_file, block_id=f"calib_{run_idx}")
            report = execute_schedule(
                instance, sched, tasks, TimingConfig(mode="logical")
            )
            if report.status != "ok":
                raise RuntimeError(
                    f"Calibration run {run_idx} failed with status={report.status}: "
                    f"{report.error_message}"
                )
            if run_idx >= warmup_runs:
                for tr in report.traces:
                    key = f"{tr.segment_id}:{tr.unit_index}"
                    per_unit_samples.setdefault(key, []).append(tr.work_elapsed_ns)
                    all_work_samples.append(tr.work_elapsed_ns)

    dispatch_samples = _measure_dispatch_overhead(probes=max(10, repetitions))
    global_stats = _summarize_samples(all_work_samples)
    dispatch_stats = _summarize_samples(dispatch_samples)
    per_unit_stats = {
        key: _summarize_samples(vals) for key, vals in sorted(per_unit_samples.items())
    }

    max_work = global_stats["max_ns"]
    max_dispatch = dispatch_stats["max_ns"]
    raw_quantum = max(
        int(math.ceil(max_work * safety_factor)) + max_dispatch,
        max_work + max_dispatch + min_margin_ns,
    )
    quantum_ns = _round_up_ns(raw_quantum, step_ns=100_000)

    return CalibrationResult(
        quantum_ns=quantum_ns,
        safety_factor=safety_factor,
        min_margin_ns=min_margin_ns,
        repetitions=repetitions,
        warmup_runs=warmup_runs,
        instance_id=instance.instance_id,
        instance_hash=instance.instance_hash(),
        input_path=str(in_path),
        input_hash=input_hash,
        application_config=cfg.to_dict(),
        global_work_stats=global_stats,
        dispatch_probe_stats=dispatch_stats,
        per_unit_stats=per_unit_stats,
        versions=collect_versions(),
        notes=(
            "Experimental calibration on a general-purpose OS/Python runtime. "
            "Observed maximums are empirical measurements, not formal WCET proofs."
        ),
    )


def save_calibration(result: CalibrationResult, path: str | Path) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_calibration(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
