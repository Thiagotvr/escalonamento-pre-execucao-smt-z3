"""End-to-end tests for Etapa 7: CLI workflow and comparative reporting."""

from __future__ import annotations

import json
from pathlib import Path

from str_project.cli import main as cli_main

ROOT = Path(__file__).resolve().parent.parent


def test_full_cli_pipeline_plan_validate_calibrate_execute_compare(tmp_path: Path) -> None:
    inst = str(ROOT / "instances" / "temperature_case.json")
    csv_in = str(ROOT / "data" / "temperatures.csv")

    xu_dir = tmp_path / "xu"
    z3_dir = tmp_path / "z3"
    cal_file = tmp_path / "calibration.json"
    cmp_dir = tmp_path / "comparison"

    # 1. Plan with both methods
    assert cli_main(["plan", "--method", "xu-parnas", "--instance", inst, "--out", str(xu_dir / "plan.json")]) == 0
    assert cli_main(["plan", "--method", "smt-z3", "--instance", inst, "--out", str(z3_dir / "plan.json")]) == 0

    # 2. Validate both plans independently
    assert cli_main(["validate", "--instance", inst, "--schedule", str(xu_dir / "plan.json")]) == 0
    assert cli_main(["validate", "--instance", inst, "--schedule", str(z3_dir / "plan.json")]) == 0

    # 3. Calibrate physical quantum
    assert (
        cli_main(
            [
                "calibrate",
                "--instance",
                inst,
                "--input",
                csv_in,
                "--repetitions",
                "5",
                "--warmup",
                "1",
                "--out",
                str(cal_file),
            ]
        )
        == 0
    )
    assert cal_file.exists()

    # 4. Execute logical mode for both
    assert (
        cli_main(
            [
                "execute",
                "--instance",
                inst,
                "--schedule",
                str(xu_dir / "plan.json"),
                "--input",
                csv_in,
                "--mode",
                "logical",
                "--out",
                str(xu_dir / "logical"),
            ]
        )
        == 0
    )
    assert (
        cli_main(
            [
                "execute",
                "--instance",
                inst,
                "--schedule",
                str(z3_dir / "plan.json"),
                "--input",
                csv_in,
                "--mode",
                "logical",
                "--out",
                str(z3_dir / "logical"),
            ]
        )
        == 0
    )

    # 5. Execute timed mode for both using shared calibrated quantum
    assert (
        cli_main(
            [
                "execute",
                "--instance",
                inst,
                "--schedule",
                str(xu_dir / "plan.json"),
                "--input",
                csv_in,
                "--mode",
                "timed",
                "--timing",
                str(cal_file),
                "--out",
                str(xu_dir / "timed"),
            ]
        )
        == 0
    )
    assert (
        cli_main(
            [
                "execute",
                "--instance",
                inst,
                "--schedule",
                str(z3_dir / "plan.json"),
                "--input",
                csv_in,
                "--mode",
                "timed",
                "--timing",
                str(cal_file),
                "--out",
                str(z3_dir / "timed"),
            ]
        )
        == 0
    )

    # 6. Compare runs
    assert cli_main(["compare", "--left", str(xu_dir), "--right", str(z3_dir), "--out", str(cmp_dir)]) == 0

    comp_json = json.loads((cmp_dir / "comparison.json").read_text(encoding="utf-8"))
    assert comp_json["planning"]["status_agreement"] is True
    assert comp_json["planning"]["left"]["validation_ok"] is True
    assert comp_json["planning"]["right"]["validation_ok"] is True
    assert comp_json["execution_logical"]["final_shared_state_equal"] is True
    assert comp_json["execution_logical"]["left_recorded_copy_consistent"] is True
    assert comp_json["execution_logical"]["right_recorded_copy_consistent"] is True
    assert comp_json["execution_timed"]["same_quantum_ns"] is True
    assert comp_json["execution_timed"]["final_shared_state_equal"] is True
    assert (cmp_dir / "comparison.md").exists()

    # 7. Alternating benchmark command
    bench_out = tmp_path / "bench.json"
    assert (
        cli_main(
            [
                "benchmark",
                "--instance",
                inst,
                "--repetitions",
                "3",
                "--warmup",
                "1",
                "--out",
                str(bench_out),
            ]
        )
        == 0
    )
    bench_data = json.loads(bench_out.read_text(encoding="utf-8"))
    assert bench_data["summary"]["xu-parnas"]["statuses"] == ["feasible"]
    assert bench_data["summary"]["smt-z3"]["statuses"] == ["feasible"]
