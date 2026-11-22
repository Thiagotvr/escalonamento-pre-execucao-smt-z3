"""Tests for Etapa 5: full Xu & Parnas branch-and-bound search, G1/G2, lower bounds, and equivalence."""

from __future__ import annotations

import random
from pathlib import Path

from str_project.instance_io import load_instance, parse_instance
from str_project.model import PlanningLimits
from str_project.oracle import solve_oracle
from str_project.planners.smt_z3 import plan_smt_z3
from str_project.planners.xu_bounds import (
    compute_Z,
    compute_expand_sets,
    compute_lower_bound,
    latest_segment,
)
from str_project.planners.xu_initial import build_valid_initial_schedule
from str_project.planners.xu_parnas import plan_xu_parnas
from str_project.validator import validate_schedule

ROOT = Path(__file__).resolve().parent.parent


def test_xu_parnas_example_1_exercises_g1_branching() -> None:
    inst = load_instance(ROOT / "instances" / "xu_example_1.json")

    # Verify root Z, G1, G2, and lower bound directly
    root = build_valid_initial_schedule(inst, set(), set(inst.exclusion), set())
    assert root.ok and root.schedule is not None
    lat_seg, lmax = latest_segment(inst, root.schedule)
    assert lat_seg == "C" and lmax == 9
    z_c = compute_Z(root.schedule, root.adjusted_releases, "C")
    assert z_c == {"A", "B", "C"}
    exp = compute_expand_sets(
        inst, root.schedule, root.adjusted_releases, set(), set(inst.exclusion), set()
    )
    assert exp.g1 == frozenset({"A"})
    assert exp.g2 == frozenset()
    lb = compute_lower_bound(
        inst, root.schedule, root.adjusted_releases, set(), set(inst.exclusion), set()
    )
    assert lb == 0

    # Verify full search finds feasible schedule via G1 branching PC(C, A)
    res = plan_xu_parnas(inst, PlanningLimits(timeout_ms=10_000, record_search_trace=True))
    assert res.status == "feasible"
    assert res.schedule is not None
    assert res.logical_lmax == 0
    assert res.nodes_expanded is not None and res.nodes_expanded >= 1
    assert validate_schedule(inst, res.schedule, require_deadlines=True).ok
    # Check exact feasible schedule bounds from Section 7.7
    bounds = res.schedule.segment_bounds()
    assert bounds == {"D": (0, 20), "C": (50, 70), "B": (70, 90), "A": (90, 110)}


def test_xu_parnas_example_2_exercises_g2_branching_and_preemption() -> None:
    inst = load_instance(ROOT / "instances" / "xu_example_2.json")

    root = build_valid_initial_schedule(inst, set(), set(inst.exclusion), set())
    assert root.ok and root.schedule is not None
    exp = compute_expand_sets(
        inst, root.schedule, root.adjusted_releases, set(), set(inst.exclusion), set()
    )
    assert exp.latest_segment == "C"
    assert exp.lmax == 10
    assert exp.g1 == frozenset({"B"})
    assert exp.g2 == frozenset({"A"})

    res = plan_xu_parnas(inst, PlanningLimits(timeout_ms=10_000, record_search_trace=True))
    assert res.status == "feasible"
    assert res.schedule is not None
    assert res.logical_lmax == 0
    assert res.nodes_expanded is not None and res.nodes_expanded >= 1
    assert validate_schedule(inst, res.schedule, require_deadlines=True).ok
    # Verify A was preempted by C (B 10-30, A 30-60, C 60-90, A 90-110)
    bounds = res.schedule.segment_bounds()
    assert bounds == {"B": (10, 30), "A": (30, 110), "C": (60, 90)}
    # Verify search trace shows G2 child with PC(B,A) and PM(C,A)
    trace = res.details["search_trace"]
    g2_entries = [e for e in trace if e.get("branch_kind") == "G2"]
    assert any(
        "PC(B,A)" in e["added_relations"] and "PM(C,A)" in e["added_relations"]
        for e in g2_entries
    )


def test_xu_parnas_solves_temperature_case() -> None:
    inst = load_instance(ROOT / "instances" / "temperature_case.json")
    res = plan_xu_parnas(inst, PlanningLimits(timeout_ms=10_000))
    assert res.status == "feasible"
    assert res.schedule is not None
    assert len(res.schedule.units) == 19
    assert res.logical_lmax is not None and res.logical_lmax <= 0
    assert validate_schedule(inst, res.schedule, require_deadlines=True).ok


def test_xu_parnas_directional_exclusion_and_infeasible_cases() -> None:
    base = {
        "schema_version": 1,
        "instance_id": "preempt_dir",
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
    assert plan_xu_parnas(parse_instance(base)).status == "feasible"
    assert plan_xu_parnas(parse_instance({**base, "exclusion": [["A", "B"]]})).status == "infeasible"
    assert plan_xu_parnas(parse_instance({**base, "exclusion": [["B", "A"]]})).status == "feasible"

    # Cyclic precedence -> infeasible with diagnostic
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
    res_cyc = plan_xu_parnas(cyc)
    assert res_cyc.status == "infeasible"
    assert "cyclic" in (res_cyc.reason or "")


def test_xu_parnas_timeout_and_max_nodes_never_become_infeasible() -> None:
    inst = load_instance(ROOT / "instances" / "xu_example_1.json")
    res_t0 = plan_xu_parnas(inst, PlanningLimits(timeout_ms=0))
    assert res_t0.status == "timeout"

    res_n1 = plan_xu_parnas(inst, PlanningLimits(timeout_ms=10_000, max_nodes=1))
    assert res_n1.status == "timeout"
    assert res_n1.status != "infeasible"


def test_xu_parnas_agrees_with_oracle_and_smt_z3_on_100_random_instances() -> None:
    """Fuzz-audit Xu & Parnas against BOTH the exhaustive oracle and SMT/Z3."""
    rng = random.Random(1990)
    for idx in range(100):
        n_segs = rng.randint(2, 4)
        seg_names = [f"S{i}" for i in range(n_segs)]
        segments = []
        for name in seg_names:
            r = rng.randint(0, 5)
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
                if rng.random() < 0.35:
                    excl.append([seg_names[i], seg_names[j]])

        inst = parse_instance(
            {
                "schema_version": 1,
                "instance_id": f"fuzz_{idx}",
                "objective": "feasibility",
                "processes": [{"id": f"P{i}", "segments": [name]} for i, name in enumerate(seg_names)],
                "segments": segments,
                "precedence": prec,
                "exclusion": excl,
            }
        )

        # Feasibility comparison across all 3 (Oracle, SMT/Z3, Xu & Parnas)
        orac_f = solve_oracle(inst, objective="feasibility")
        xu_f = plan_xu_parnas(inst, PlanningLimits(timeout_ms=10_000), objective="feasibility")
        z3_f = plan_smt_z3(inst, PlanningLimits(timeout_ms=10_000), objective="feasibility")

        assert (xu_f.status == "feasible") == orac_f.feasible, (
            f"Feasibility mismatch Xu vs Oracle on {inst.instance_id}: "
            f"xu={xu_f.status}, oracle={orac_f.feasible}, inst={inst.canonical_dict()}"
        )
        assert xu_f.status == z3_f.status, (
            f"Feasibility mismatch Xu vs Z3 on {inst.instance_id}: xu={xu_f.status}, z3={z3_f.status}"
        )

        # Optimal Lmax comparison on first 30 instances
        if idx < 30:
            orac_opt = solve_oracle(inst, objective="min_lmax")
            xu_opt = plan_xu_parnas(inst, PlanningLimits(timeout_ms=10_000), objective="min_lmax")
            z3_opt = plan_smt_z3(inst, PlanningLimits(timeout_ms=10_000), objective="min_lmax")
            assert xu_opt.logical_lmax == orac_opt.optimal_lmax, (
                f"Optimal Lmax mismatch Xu vs Oracle on {inst.instance_id}: "
                f"xu={xu_opt.logical_lmax}, oracle={orac_opt.optimal_lmax}, inst={inst.canonical_dict()}"
            )
            assert xu_opt.logical_lmax == z3_opt.logical_lmax
