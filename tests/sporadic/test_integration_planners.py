"""Integration tests for Fase C: both planners on sporadic scenarios, oracle cross-check, CLI."""

from __future__ import annotations

import json
from pathlib import Path

from str_project.oracle import solve_oracle
from str_project.sporadic import (
    adapt_sequence_to_instance,
    generate_sequence,
    parse_scenario_spec,
    run_sporadic_scenario,
)
from str_project.sporadic.cli import main as sporadic_cli_main


def test_small_feasible_sporadic_scenario_both_sat_and_verified(tmp_path: Path) -> None:
    sc = parse_scenario_spec(
        {
            "schema_version": "sporadic-v1",
            "scenario_id": "small_feas",
            "horizon": 40,
            "seed": 123,
            "generation_mode": "jittered",
            "jitter_max": 4,
            "tasks": [
                {"id": "A", "C": 3, "D": 8, "T": 12, "offset": 0},
                {"id": "B", "C": 2, "D": 7, "T": 10, "offset": 2},
            ],
        }
    )
    bundle = run_sporadic_scenario(sc, out_dir=tmp_path, timeout_ms=5_000)
    xu = bundle["records"]["xu-parnas"]
    z3 = bundle["records"]["smt-z3"]

    assert xu["instance_hash"] == z3["instance_hash"] == bundle["instance_hash"]
    assert xu["input_hash"] == z3["input_hash"] == bundle["input_hash"]
    assert xu["status"] == "SAT" and xu["validation_passed"] is True
    assert z3["status"] == "SAT" and z3["validation_passed"] is True
    assert bundle["agreement"] is True
    assert bundle["divergence_detected"] is False


def test_infeasible_sporadic_scenario_by_demand_both_unsat(tmp_path: Path) -> None:
    # Two tasks released simultaneously at t=0 with D=5 and C=4 + C=3 = 7 > 5
    sc = parse_scenario_spec(
        {
            "schema_version": "sporadic-v1",
            "scenario_id": "infeas_demand",
            "horizon": 10,
            "seed": 1,
            "generation_mode": "explicit",
            "tasks": [
                {"id": "A", "C": 4, "D": 5, "T": 10, "offset": 0, "explicit_releases": [0]},
                {"id": "B", "C": 3, "D": 5, "T": 10, "offset": 0, "explicit_releases": [0]},
            ],
        }
    )
    bundle = run_sporadic_scenario(sc, out_dir=tmp_path, timeout_ms=5_000)
    assert bundle["records"]["xu-parnas"]["status"] == "UNSAT"
    assert bundle["records"]["smt-z3"]["status"] == "UNSAT"
    assert bundle["agreement"] is True


def test_irregular_sporadic_with_directional_exclusions_and_oracle_audit(tmp_path: Path) -> None:
    # Irregular arrivals where activation k=1 hits mandatory preemption:
    # A at r=10 (C=2, D=3 -> d=13), B at r=11 (C=1, D=1 -> d=12)
    base_cfg = {
        "schema_version": "sporadic-v1",
        "scenario_id": "irreg_dir_ex",
        "horizon": 20,
        "seed": 1,
        "generation_mode": "explicit",
        "tasks": [
            {"id": "A", "C": 2, "D": 3, "T": 7, "offset": 0, "explicit_releases": [0, 10]},
            {"id": "B", "C": 1, "D": 1, "T": 8, "offset": 3, "explicit_releases": [3, 11]},
        ],
    }

    # Case 1: A EXCLUDES B -> infeasible (at k=1, A starts at 10 and blocks B at 11)
    sc_ab = parse_scenario_spec(
        {
            **base_cfg,
            "scenario_id": "irreg_A_ex_B",
            "cross_rules": [
                {
                    "kind": "exclusion",
                    "src_task": "A",
                    "src_segment": "S1",
                    "dst_task": "B",
                    "dst_segment": "S1",
                    "scope": "all_overlapping",
                }
            ],
        }
    )
    ad_ab = adapt_sequence_to_instance(generate_sequence(sc_ab))
    orac_ab = solve_oracle(ad_ab.instance)
    b_ab = run_sporadic_scenario(sc_ab, out_dir=tmp_path / "ab", timeout_ms=5_000)
    assert orac_ab.feasible is False
    assert b_ab["records"]["xu-parnas"]["status"] == "UNSAT"
    assert b_ab["records"]["smt-z3"]["status"] == "UNSAT"

    # Case 2: B EXCLUDES A -> feasible (A starts at 10 < s[B]=11, so B EXCLUDES A is vacuous!)
    sc_ba = parse_scenario_spec(
        {
            **base_cfg,
            "scenario_id": "irreg_B_ex_A",
            "cross_rules": [
                {
                    "kind": "exclusion",
                    "src_task": "B",
                    "src_segment": "S1",
                    "dst_task": "A",
                    "dst_segment": "S1",
                    "scope": "all_overlapping",
                }
            ],
        }
    )
    ad_ba = adapt_sequence_to_instance(generate_sequence(sc_ba))
    orac_ba = solve_oracle(ad_ba.instance)
    b_ba = run_sporadic_scenario(sc_ba, out_dir=tmp_path / "ba", timeout_ms=5_000)
    assert orac_ba.feasible is True
    assert b_ba["records"]["xu-parnas"]["status"] == "SAT"
    assert b_ba["records"]["smt-z3"]["status"] == "SAT"
    assert b_ba["records"]["xu-parnas"]["validation_passed"] is True
    assert b_ba["records"]["smt-z3"]["validation_passed"] is True


def test_simultaneous_arrivals_distinct_tasks_temperature_segmented_sporadic(tmp_path: Path) -> None:
    sc = parse_scenario_spec(
        {
            "schema_version": "sporadic-v1",
            "scenario_id": "temp_2_activations",
            "horizon": 48,
            "seed": 11,
            "generation_mode": "explicit",
            "tasks": [
                {
                    "id": "P1",
                    "C": 6,
                    "D": 8,
                    "T": 20,
                    "offset": 0,
                    "explicit_releases": [0, 23],
                    "segments": [
                        {"id": "A1", "execution_units": 2},
                        {"id": "A2", "execution_units": 1},
                        {"id": "A3", "execution_units": 3},
                    ],
                },
                {
                    "id": "P2",
                    "C": 8,
                    "D": 20,
                    "T": 20,
                    "offset": 0,
                    "explicit_releases": [0, 23],
                    "segments": [
                        {"id": "A4", "execution_units": 4},
                        {"id": "A5", "execution_units": 1},
                        {"id": "A6", "execution_units": 1},
                        {"id": "A7", "execution_units": 2},
                    ],
                },
                {
                    "id": "P3",
                    "C": 5,
                    "D": 12,
                    "T": 20,
                    "offset": 8,
                    "explicit_releases": [8, 31],
                    "segments": [
                        {"id": "S", "execution_units": 2},
                        {"id": "A8", "execution_units": 3},
                    ],
                },
            ],
            "cross_rules": [
                {
                    "kind": "precedence",
                    "src_task": "P1",
                    "src_segment": "A3",
                    "dst_task": "P2",
                    "dst_segment": "A4",
                    "scope": "same_activation",
                },
                {
                    "kind": "exclusion",
                    "src_task": "P2",
                    "src_segment": "A7",
                    "dst_task": "P3",
                    "dst_segment": "S",
                    "scope": "all_overlapping",
                },
                {
                    "kind": "exclusion",
                    "src_task": "P3",
                    "src_segment": "S",
                    "dst_task": "P2",
                    "dst_segment": "A7",
                    "scope": "all_overlapping",
                },
            ],
        }
    )
    bundle = run_sporadic_scenario(sc, out_dir=tmp_path, timeout_ms=10_000)
    assert bundle["records"]["xu-parnas"]["status"] == "SAT"
    assert bundle["records"]["smt-z3"]["status"] == "SAT"
    assert bundle["records"]["xu-parnas"]["validation_passed"] is True
    assert bundle["records"]["smt-z3"]["validation_passed"] is True


def test_timeout_zero_is_classified_as_timeout_never_unsat(tmp_path: Path) -> None:
    sc = parse_scenario_spec(
        {
            "schema_version": "sporadic-v1",
            "scenario_id": "timeout_check",
            "horizon": 30,
            "seed": 1,
            "generation_mode": "min_interval",
            "tasks": [{"id": "A", "C": 2, "D": 5, "T": 10, "offset": 0}],
        }
    )
    bundle = run_sporadic_scenario(sc, out_dir=tmp_path, timeout_ms=0)
    assert bundle["records"]["xu-parnas"]["status"] == "TIMEOUT"
    assert bundle["records"]["smt-z3"]["status"] == "TIMEOUT"
    assert bundle["records"]["xu-parnas"]["timeout"] is True
    assert bundle["records"]["smt-z3"]["timeout"] is True


def test_sporadic_cli_end_to_end_generate_run_validate(tmp_path: Path) -> None:
    cfg_file = tmp_path / "demo.json"
    cfg_file.write_text(
        json.dumps(
            {
                "schema_version": "sporadic-v1",
                "scenario_id": "cli_demo",
                "horizon": 30,
                "seed": 7,
                "generation_mode": "jittered",
                "jitter_max": 3,
                "tasks": [
                    {"id": "A", "C": 2, "D": 6, "T": 10, "offset": 0},
                    {"id": "B", "C": 2, "D": 7, "T": 12, "offset": 1},
                ],
            }
        ),
        encoding="utf-8",
    )
    inst_out = tmp_path / "inst.json"
    assert sporadic_cli_main(["generate", "--config", str(cfg_file), "--out", str(inst_out)]) == 0
    assert inst_out.exists()

    run_dir = tmp_path / "run"
    assert (
        sporadic_cli_main(
            ["run-scenario", "--config", str(cfg_file), "--out", str(run_dir), "--timeout-ms", "5000"]
        )
        == 0
    )
    xu_sched = run_dir / "schedules" / "cli_demo__seed7__xu-parnas.json"
    z3_sched = run_dir / "schedules" / "cli_demo__seed7__smt-z3.json"
    frozen_inst = run_dir / "instances" / "cli_demo__seed7.json"
    assert sporadic_cli_main(["validate", "--instance", str(frozen_inst), "--schedule", str(xu_sched)]) == 0
    assert sporadic_cli_main(["validate", "--instance", str(frozen_inst), "--schedule", str(z3_sched)]) == 0
