"""Tests for Etapa 3: SMT/Z3 planner (feasibility, min_lmax, directional EX, oracle equivalence)."""

from __future__ import annotations

import random
from pathlib import Path

from str_project.instance_io import load_instance, parse_instance
from str_project.model import PlanningLimits
from str_project.oracle import solve_oracle
from str_project.planners.smt_z3 import plan_smt_z3
from str_project.validator import validate_schedule

ROOT = Path(__file__).resolve().parent.parent


def test_smt_z3_solves_temperature_case_and_saves_smt2(tmp_path: Path) -> None:
    inst = load_instance(ROOT / "instances" / "temperature_case.json")
    smt_file = tmp_path / "temp.smt2"
    res = plan_smt_z3(inst, PlanningLimits(timeout_ms=10_000, save_smt2_path=str(smt_file)))
    assert res.status == "feasible"
    assert res.schedule is not None
    assert len(res.schedule.units) == 19
    assert res.logical_lmax is not None and res.logical_lmax <= 0
    assert res.validation is not None and res.validation.ok
    assert validate_schedule(inst, res.schedule, require_deadlines=True).ok
    assert smt_file.exists() and "distinct" in smt_file.read_text(encoding="utf-8")


def test_smt_z3_solves_xu_examples_1_and_2() -> None:
    inst1 = load_instance(ROOT / "instances" / "xu_example_1.json")
    res1 = plan_smt_z3(inst1, PlanningLimits(timeout_ms=15_000))
    assert res1.status == "feasible"
    assert res1.schedule is not None
    assert validate_schedule(inst1, res1.schedule, require_deadlines=True).ok

    inst2 = load_instance(ROOT / "instances" / "xu_example_2.json")
    res2 = plan_smt_z3(inst2, PlanningLimits(timeout_ms=15_000))
    assert res2.status == "feasible"
    assert res2.schedule is not None
    assert validate_schedule(inst2, res2.schedule, require_deadlines=True).ok


def test_smt_z3_directional_exclusion_and_mandatory_preemption() -> None:
    base = {
        "schema_version": 1,
        "instance_id": "preempt_case",
        "objective": "feasibility",
        "processes": [
            {"id": "PA", "segments": ["A"]},
            {"id": "PB", "segments": ["B"]},
        ],
        "segments": [
            {"id": "A", "release": 0, "execution_units": 2, "deadline": 3},
            {"id": "B", "release": 1, "execution_units": 1, "deadline": 2},
        ],
        "precedence": [],
        "exclusion": [],
    }
    res_none = plan_smt_z3(parse_instance(base))
    assert res_none.status == "feasible"

    res_ab = plan_smt_z3(parse_instance({**base, "exclusion": [["A", "B"]]}))
    assert res_ab.status == "infeasible"

    res_ba = plan_smt_z3(parse_instance({**base, "exclusion": [["B", "A"]]}))
    assert res_ba.status == "feasible"


def test_smt_z3_infeasible_cases_demand_deadline_and_cycle() -> None:
    # Cyclic precedence
    cyc = parse_instance(
        {
            "schema_version": 1,
            "instance_id": "cyc",
            "objective": "feasibility",
            "processes": [
                {"id": "P1", "segments": ["A"]},
                {"id": "P2", "segments": ["B"]},
            ],
            "segments": [
                {"id": "A", "release": 0, "execution_units": 2, "deadline": 10},
                {"id": "B", "release": 0, "execution_units": 2, "deadline": 10},
            ],
            "precedence": [["A", "B"], ["B", "A"]],
            "exclusion": [],
        }
    )
    res_cyc = plan_smt_z3(cyc)
    assert res_cyc.status == "infeasible"
    assert "cyclic" in (res_cyc.reason or "")

    # Total demand > max deadline
    over = parse_instance(
        {
            "schema_version": 1,
            "instance_id": "over",
            "objective": "feasibility",
            "processes": [
                {"id": "P1", "segments": ["A"]},
                {"id": "P2", "segments": ["B"]},
            ],
            "segments": [
                {"id": "A", "release": 0, "execution_units": 4, "deadline": 5},
                {"id": "B", "release": 0, "execution_units": 3, "deadline": 5},
            ],
            "precedence": [],
            "exclusion": [],
        }
    )
    res_over = plan_smt_z3(over)
    assert res_over.status == "infeasible"


def test_smt_z3_timeout_never_becomes_infeasible() -> None:
    inst = load_instance(ROOT / "instances" / "temperature_case.json")
    res = plan_smt_z3(inst, PlanningLimits(timeout_ms=0))
    assert res.status == "timeout"
    assert res.status != "infeasible"


def test_smt_z3_matches_oracle_on_random_tiny_instances_feasibility_and_min_lmax() -> None:
    rng = random.Random(2026)
    for idx in range(40):
        n_segs = rng.randint(2, 4)
        seg_names = [f"S{i}" for i in range(n_segs)]
        segments = []
        for name in seg_names:
            r = rng.randint(0, 4)
            c = rng.randint(1, 3)
            d = r + c + rng.randint(0, 3)
            segments.append({"id": name, "release": r, "execution_units": c, "deadline": d})
        prec = []
        excl = []
        for i in range(n_segs):
            for j in range(n_segs):
                if i == j:
                    continue
                if i < j and rng.random() < 0.2:
                    prec.append([seg_names[i], seg_names[j]])
                if rng.random() < 0.3:
                    excl.append([seg_names[i], seg_names[j]])

        inst = parse_instance(
            {
                "schema_version": 1,
                "instance_id": f"rand_{idx}",
                "objective": "feasibility",
                "processes": [{"id": f"P{i}", "segments": [name]} for i, name in enumerate(seg_names)],
                "segments": segments,
                "precedence": prec,
                "exclusion": excl,
            }
        )

        orac_f = solve_oracle(inst, objective="feasibility")
        z3_f = plan_smt_z3(inst, PlanningLimits(timeout_ms=10_000), objective="feasibility")
        assert (z3_f.status == "feasible") == orac_f.feasible, f"Mismatch on {inst.instance_id}"

        if idx < 15:
            orac_opt = solve_oracle(inst, objective="min_lmax")
            z3_opt = plan_smt_z3(inst, PlanningLimits(timeout_ms=10_000), objective="min_lmax")
            assert z3_opt.logical_lmax == orac_opt.optimal_lmax, (
                f"Optimal Lmax mismatch on {inst.instance_id}: z3={z3_opt.logical_lmax}, oracle={orac_opt.optimal_lmax}"
            )
            assert z3_opt.lower_bound == orac_opt.optimal_lmax
