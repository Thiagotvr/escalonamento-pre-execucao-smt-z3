"""Tests for Etapa 4: Xu & Parnas relations, adjusted releases, and valid initial schedule."""

from __future__ import annotations

from pathlib import Path

from str_project.instance_io import load_instance, parse_instance
from str_project.planners.xu_initial import build_valid_initial_schedule
from str_project.planners.xu_relations import adjusted_releases, check_relations
from str_project.validator import validate_schedule

ROOT = Path(__file__).resolve().parent.parent


def test_check_relations_detects_all_inconsistent_pairs_and_pc_cycles() -> None:
    # Transitive PC cycle
    res_cyc = check_relations({("A", "B"), ("B", "C"), ("C", "A")}, set(), set())
    assert not res_cyc.consistent

    # PC(i,j) and PM(j,i) (even transitively!)
    res_pc_pm = check_relations({("A", "B"), ("B", "C")}, set(), {("C", "A")})
    assert not res_pc_pm.consistent

    # EX(i,j) and PM(j,i)
    res_ex_pm = check_relations(set(), {("A", "B")}, {("B", "A")})
    assert not res_ex_pm.consistent

    # PM(i,j) and PM(j,i)
    res_pm_pm = check_relations(set(), set(), {("A", "B"), ("B", "A")})
    assert not res_pm_pm.consistent

    # Consistent combination: EX(A,B) and PM(A,B) is allowed
    res_ok = check_relations({("A", "C")}, {("A", "B")}, {("A", "B")})
    assert res_ok.consistent


def test_adjusted_releases_for_temperature_case() -> None:
    inst = load_instance(ROOT / "instances" / "temperature_case.json")
    r_adj = adjusted_releases(inst, set(inst.precedence))
    assert r_adj == {
        "A1": 0,
        "A2": 2,
        "A3": 3,
        "A4": 6,
        "A5": 10,
        "A6": 11,
        "A7": 12,
        "S": 8,
        "A8": 10,
    }


def test_initial_schedule_reproduces_xu_example_1_root() -> None:
    inst = load_instance(ROOT / "instances" / "xu_example_1.json")
    res = build_valid_initial_schedule(inst, set(inst.precedence), set(inst.exclusion), set())
    assert res.ok and res.schedule is not None
    assert res.starts == {"D": 0, "A": 40, "B": 60, "C": 80}
    assert res.finishes == {"D": 20, "A": 60, "B": 80, "C": 100}
    assert res.idle_intervals == ((20, 40),)
    assert res.schedule.compute_lmax(inst) == 9
    assert validate_schedule(inst, res.schedule, require_deadlines=False).ok


def test_initial_schedule_reproduces_xu_example_2_root_and_g2_child() -> None:
    inst = load_instance(ROOT / "instances" / "xu_example_2.json")

    # Root schedule
    root = build_valid_initial_schedule(inst, set(inst.precedence), set(inst.exclusion), set())
    assert root.ok and root.schedule is not None
    assert root.starts == {"A": 0, "B": 50, "C": 70}
    assert root.finishes == {"A": 50, "B": 70, "C": 100}
    assert root.schedule.compute_lmax(inst) == 10

    # Child G2 with PC(B, A) and PM(C, A) -> B 10-30, A 30-60, C 60-90, A 90-110
    child = build_valid_initial_schedule(
        inst, {("B", "A")}, set(inst.exclusion), {("C", "A")}
    )
    assert child.ok and child.schedule is not None
    assert child.starts == {"B": 10, "A": 30, "C": 60}
    assert child.finishes == {"B": 30, "C": 90, "A": 110}
    assert child.schedule.compute_lmax(inst) == 0
    assert validate_schedule(inst, child.schedule, require_deadlines=True).ok


def test_tie_break_uses_largest_original_c_not_remaining_time() -> None:
    # A has c=4, d=10, released at 0 -> runs [0, 3), remaining=1 at t=3.
    # B has c=2, d=10, released at 3 -> remaining=2 > remaining(A)=1,
    # BUT original c(A)=4 > original c(B)=2, so A must NOT be preempted by B!
    inst = parse_instance(
        {
            "schema_version": 1,
            "instance_id": "tie_break_orig_c",
            "objective": "feasibility",
            "processes": [
                {"id": "PA", "segments": ["A"]},
                {"id": "PB", "segments": ["B"]},
            ],
            "segments": [
                {"id": "A", "release": 0, "execution_units": 4, "deadline": 10},
                {"id": "B", "release": 3, "execution_units": 2, "deadline": 10},
            ],
            "precedence": [],
            "exclusion": [],
        }
    )
    res = build_valid_initial_schedule(inst, set(), set(), set())
    assert res.ok and res.schedule is not None
    assert res.starts["A"] == 0 and res.finishes["A"] == 4
    assert res.starts["B"] == 4 and res.finishes["B"] == 6


def test_initial_schedule_solves_temperature_case_root() -> None:
    inst = load_instance(ROOT / "instances" / "temperature_case.json")
    res = build_valid_initial_schedule(inst, set(inst.precedence), set(inst.exclusion), set())
    assert res.ok and res.schedule is not None
    val = validate_schedule(inst, res.schedule, require_deadlines=True)
    assert val.ok
    assert res.schedule.compute_lmax(inst) <= 0
