"""Tests for Etapa 2 & 6: logical and timed executor behavior and diagnostics."""

from __future__ import annotations

import time
from pathlib import Path

from str_project.application import (
    ApplicationConfig,
    Task,
    build_tasks,
    default_application_config,
)
from str_project.executor import TimingConfig, execute_schedule
from str_project.instance_io import load_instance
from str_project.schedule_io import known_integration_schedule

ROOT = Path(__file__).resolve().parent.parent


def test_logical_executor_order_matches_schedule_and_closes_files_before_end(tmp_path: Path) -> None:
    inst = load_instance(ROOT / "instances" / "temperature_case.json")
    cfg = default_application_config()
    csv_path = ROOT / "data" / "temperatures.csv"
    out_path = tmp_path / "record.json"
    sched = known_integration_schedule()

    tasks = build_tasks(cfg, csv_path, out_path)
    rep = execute_schedule(inst, sched, tasks, TimingConfig(mode="logical"))
    assert rep.status == "ok"
    assert len(rep.traces) == 19

    expected_order = [(u.segment_id, u.unit_index, u.start_tick) for u in sched.sorted_units()]
    observed_order = [(t.segment_id, t.unit_index, t.start_tick) for t in rep.traces]
    assert observed_order == expected_order

    # Output file is already flushed & closed on A8 unit 3 (no hidden finalization)
    assert out_path.exists()
    assert out_path.stat().st_size > 0
    assert rep.traces[-1].segment_id == "A8"
    assert rep.traces[-1].unit_index == 3
    assert rep.traces[-1].done is True


def test_timed_executor_succeeds_with_generous_quantum(tmp_path: Path) -> None:
    inst = load_instance(ROOT / "instances" / "temperature_case.json")
    cfg = default_application_config()
    csv_path = ROOT / "data" / "temperatures.csv"
    out_path = tmp_path / "timed_record.json"
    sched = known_integration_schedule()

    tasks = build_tasks(cfg, csv_path, out_path)
    # 5 ms per quantum -> 19 ticks ~ 95 ms, plenty for lightweight Python steps
    rep = execute_schedule(
        inst,
        sched,
        tasks,
        TimingConfig(mode="timed", quantum_ns=5_000_000, lead_time_ns=2_000_000),
    )
    assert rep.status == "ok", f"Timed run failed: {rep.error_message}"
    assert rep.units_executed == 19
    assert rep.max_slot_overrun_ns == 0
    assert all(st.physical_deadline_met for st in rep.segment_timings)


def test_deliberate_slow_task_triggers_runtime_budget_violation(tmp_path: Path) -> None:
    inst = load_instance(ROOT / "instances" / "temperature_case.json")
    cfg = default_application_config()
    csv_path = ROOT / "data" / "temperatures.csv"
    out_path = tmp_path / "slow_record.json"
    sched = known_integration_schedule()

    tasks = build_tasks(cfg, csv_path, out_path)
    orig_a2 = tasks.tasks["A2"]
    orig_exec = orig_a2._execute_unit

    def slow_exec(unit_index: int):
        time.sleep(0.015)  # 15 ms, clearly larger than 2 ms quantum
        return orig_exec(unit_index)

    orig_a2._execute_unit = slow_exec  # type: ignore[method-assign]

    rep = execute_schedule(
        inst,
        sched,
        tasks,
        TimingConfig(mode="timed", quantum_ns=2_000_000, lead_time_ns=2_000_000),
    )
    assert rep.status == "runtime_budget_violation"
    assert rep.failed_unit is not None
    assert rep.failed_unit["segment_id"] == "A2"
    assert rep.max_slot_overrun_ns > 0


def test_calibration_produces_valid_quantum_for_timed_execution(tmp_path: Path) -> None:
    from str_project.calibration import calibrate_quantum, load_calibration, save_calibration

    inst = load_instance(ROOT / "instances" / "temperature_case.json")
    cfg = default_application_config()
    csv_path = ROOT / "data" / "temperatures.csv"

    cal = calibrate_quantum(inst, csv_path, cfg, repetitions=5, warmup_runs=1)
    assert cal.quantum_ns > cal.global_work_stats["max_ns"]
    assert len(cal.per_unit_stats) == 19

    cal_path = tmp_path / "calibration.json"
    save_calibration(cal, cal_path)
    loaded = load_calibration(cal_path)
    assert loaded["quantum_ns"] == cal.quantum_ns

    # Execute timed schedule using the calibrated quantum
    tasks = build_tasks(cfg, csv_path, tmp_path / "calibrated_out.json")
    rep = execute_schedule(
        inst,
        known_integration_schedule(),
        tasks,
        TimingConfig(mode="timed", quantum_ns=loaded["quantum_ns"]),
    )
    assert rep.status == "ok", f"Calibrated timed run failed: {rep.error_message}"
    assert rep.units_executed == 19
    assert rep.max_slot_overrun_ns == 0
