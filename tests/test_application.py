"""Tests for Etapa 2: real application segments (A1-A8, S) and functional equivalence."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from str_project.application import (
    ApplicationConfig,
    StateConsistencyError,
    WorkloadError,
    build_tasks,
    default_application_config,
    generate_temperature_fixture,
    load_application_config,
    run_sequential_reference,
)
from str_project.executor import TimingConfig, execute_schedule
from str_project.instance_io import load_instance
from str_project.schedule_io import (
    known_integration_schedule,
    known_invalid_interleaved_schedule,
    known_version1_schedule,
)

ROOT = Path(__file__).resolve().parent.parent


def test_fixture_csv_matches_specification() -> None:
    csv_path = ROOT / "data" / "temperatures.csv"
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "instante,temperatura"
    assert len(lines) == 121
    assert lines[1] == "0,24.0"
    assert lines[2] == "1,24.1"
    assert lines[3] == "2,24.2"
    assert lines[-1] == "119,35.9"


def test_build_tasks_does_not_execute_io_eagerly(tmp_path: Path) -> None:
    cfg = load_application_config(ROOT / "data" / "application_config.json")
    out_file = tmp_path / "record.json"
    missing_input = tmp_path / "does_not_exist.csv"
    # Building tasks must not open input or create output prematurely
    tasks = build_tasks(cfg, missing_input, out_file)
    assert not out_file.exists()
    assert tasks.context.raw_rows is None
    assert tasks.context.shared_state.version == 0


def test_p1_p2_match_sequential_reference_with_preemption(tmp_path: Path) -> None:
    inst = load_instance(ROOT / "instances" / "temperature_case.json")
    cfg = load_application_config(ROOT / "data" / "application_config.json")
    csv_path = ROOT / "data" / "temperatures.csv"

    ref = run_sequential_reference(cfg, csv_path)

    # Known integration schedule preempts A4 around S and logs E0 (version 0)
    out0 = tmp_path / "out_v0.json"
    tasks0 = build_tasks(cfg, csv_path, out0)
    rep0 = execute_schedule(inst, known_integration_schedule(), tasks0, TimingConfig(mode="logical"))
    assert rep0.status == "ok"
    assert rep0.units_executed == 19
    assert out0.exists()

    # Final shared state (published by A7) must match sequential reference
    st0 = rep0.final_shared_state
    assert st0["version"] == 1
    assert st0["alert_active"] is True
    assert st0["ventilation_on"] is True
    for key in ("count", "min", "max", "mean", "variance"):
        assert math.isclose(st0["indicators"][key], ref["indicators"][key], rel_tol=1e-12, abs_tol=1e-12)

    # Recorded file used S's private copy (E0, version 0) even though A7 finished before A8!
    disk0 = json.loads(out0.read_text(encoding="utf-8"))
    assert disk0["recorded_state"]["version"] == 0
    assert disk0["recorded_state"]["alert"] == "sem_dados"
    assert disk0["recorded_state"]["indicators"] is None
    assert disk0["recorded_state"]["command"] == "desligado"

    # Known version 1 schedule: A7 finishes before S, so P3 records version 1
    out1 = tmp_path / "out_v1.json"
    tasks1 = build_tasks(cfg, csv_path, out1)
    rep1 = execute_schedule(inst, known_version1_schedule(), tasks1, TimingConfig(mode="logical"))
    assert rep1.status == "ok"
    disk1 = json.loads(out1.read_text(encoding="utf-8"))
    assert disk1["recorded_state"]["version"] == 1
    assert disk1["recorded_state"]["alert_active"] is True
    assert disk1["recorded_state"]["ventilation_on"] is True
    for key in ("count", "min", "max", "mean", "variance"):
        assert math.isclose(
            disk1["recorded_state"]["indicators"][key],
            ref["indicators"][key],
            rel_tol=1e-12,
            abs_tol=1e-12,
        )


def test_a3_preserves_moving_average_window_across_units(tmp_path: Path) -> None:
    cfg = default_application_config()
    csv_path = ROOT / "data" / "temperatures.csv"
    ref = run_sequential_reference(cfg, csv_path)
    tasks = build_tasks(cfg, csv_path, tmp_path / "rec.json")
    for seg_id, count in [("A1", 2), ("A2", 1), ("A3", 3)]:
        for k in range(1, count + 1):
            tasks.get(seg_id).step(k)
    assert tasks.context.filtered_samples is not None
    assert len(tasks.context.filtered_samples) == len(ref["filtered_samples"])
    for (i1, v1), (i2, v2) in zip(tasks.context.filtered_samples, ref["filtered_samples"]):
        assert i1 == i2
        assert math.isclose(v1, v2, rel_tol=1e-12, abs_tol=1e-12)


def test_invalid_samples_trigger_workload_error_not_infeasible(tmp_path: Path) -> None:
    inst = load_instance(ROOT / "instances" / "temperature_case.json")
    cfg = default_application_config()
    bad_csv = tmp_path / "bad.csv"
    lines = ["instante,temperatura"] + [f"{i},999.0" for i in range(120)]
    bad_csv.write_text("\n".join(lines) + "\n", encoding="utf-8")

    tasks = build_tasks(cfg, bad_csv, tmp_path / "out.json")
    rep = execute_schedule(inst, known_integration_schedule(), tasks, TimingConfig(mode="logical"))
    assert rep.status == "workload_error"
    assert rep.failed_unit is not None
    assert rep.failed_unit["segment_id"] == "A2"


def test_interleaved_a7_and_s_rejected_by_validator_and_caught_in_deliberate_test(tmp_path: Path) -> None:
    inst = load_instance(ROOT / "instances" / "temperature_case.json")
    cfg = default_application_config()
    csv_path = ROOT / "data" / "temperatures.csv"
    bad_sched = known_invalid_interleaved_schedule()

    # Normal execution rejects invalid schedule before running any task
    tasks1 = build_tasks(cfg, csv_path, tmp_path / "out1.json")
    rep1 = execute_schedule(inst, bad_sched, tasks1, TimingConfig(mode="logical"))
    assert rep1.status == "invalid_schedule"
    assert rep1.units_executed == 0

    # Deliberate failure test mode lets it run and verifies S catches torn read
    tasks2 = build_tasks(cfg, csv_path, tmp_path / "out2.json")
    rep2 = execute_schedule(
        inst,
        bad_sched,
        tasks2,
        TimingConfig(mode="logical", allow_invalid_schedule=True),
    )
    assert rep2.status == "workload_error"
    assert rep2.failed_unit is not None
    assert rep2.failed_unit["segment_id"] == "S"
    assert "StateConsistencyError" in (rep2.error_message or "")
