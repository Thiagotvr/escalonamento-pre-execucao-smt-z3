"""Tests for Etapa 1: model, instance I/O, validator, known schedules, and oracle."""

from __future__ import annotations

from pathlib import Path

import pytest

from str_project.instance_io import load_instance, parse_instance
from str_project.model import InvalidInputError, Schedule, UnitPlacement
from str_project.oracle import solve_oracle
from str_project.schedule_io import (
    build_schedule_from_blocks,
    known_integration_schedule,
    known_invalid_interleaved_schedule,
    known_version1_schedule,
)
from str_project.validator import validate_schedule

ROOT = Path(__file__).resolve().parent.parent


def test_load_temperature_case_adds_process_precedence_and_preserves_directional_exclusion() -> None:
    inst = load_instance(ROOT / "instances" / "temperature_case.json")
    assert inst.instance_id == "temperature_case_v1"
    assert inst.total_units() == 19
    assert set(inst.precedence) == {
        ("A1", "A2"),
        ("A2", "A3"),
        ("A3", "A4"),
        ("A4", "A5"),
        ("A5", "A6"),
        ("A6", "A7"),
        ("S", "A8"),
    }
    assert set(inst.exclusion) == {("A7", "S"), ("S", "A7")}


def test_directional_exclusion_is_not_symmetrized() -> None:
    inst = load_instance(ROOT / "instances" / "xu_example_2.json")
    assert set(inst.exclusion) == {("A", "B"), ("B", "C")}
    assert ("B", "A") not in inst.exclusion
    assert ("C", "B") not in inst.exclusion


def test_invalid_input_raises_invalid_input_error() -> None:
    base = {
        "schema_version": 1,
        "instance_id": "bad",
        "objective": "feasibility",
        "processes": [{"id": "P1", "segments": ["A"]}],
        "segments": [{"id": "A", "release": 0, "execution_units": 0, "deadline": 5}],
        "precedence": [],
        "exclusion": [],
    }
    with pytest.raises(InvalidInputError):
        parse_instance(base)

    bool_c = {**base, "segments": [{"id": "A", "release": 0, "execution_units": True, "deadline": 5}]}
    with pytest.raises(InvalidInputError):
        parse_instance(bool_c)

    unknown_ref = {
        **base,
        "segments": [{"id": "A", "release": 0, "execution_units": 1, "deadline": 5}],
        "precedence": [["A", "MISSING"]],
    }
    with pytest.raises(InvalidInputError):
        parse_instance(unknown_ref)


def test_cyclic_precedence_is_parsed_as_valid_schema_not_format_error() -> None:
    data = {
        "schema_version": 1,
        "instance_id": "cycle",
        "objective": "feasibility",
        "processes": [
            {"id": "P1", "segments": ["A"]},
            {"id": "P2", "segments": ["B"]},
        ],
        "segments": [
            {"id": "A", "release": 0, "execution_units": 1, "deadline": 5},
            {"id": "B", "release": 0, "execution_units": 1, "deadline": 5},
        ],
        "precedence": [["A", "B"], ["B", "A"]],
        "exclusion": [],
    }
    inst = parse_instance(data)
    res = solve_oracle(inst)
    assert not res.feasible
    assert res.reason == "cyclic_precedence"


def test_known_integration_and_version1_schedules_pass_validator() -> None:
    inst = load_instance(ROOT / "instances" / "temperature_case.json")

    s0 = known_integration_schedule()
    r0 = validate_schedule(inst, s0, require_deadlines=True)
    assert r0.ok and r0.valid and r0.feasible
    assert r0.logical_lmax == -1  # A8 ends at 19 <= 20, A3 ends at 6 <= 8

    s1 = known_version1_schedule()
    r1 = validate_schedule(inst, s1, require_deadlines=True)
    assert r1.ok and r1.valid and r1.feasible


def test_validator_rejects_interleaved_exclusion_and_other_violations() -> None:
    inst = load_instance(ROOT / "instances" / "temperature_case.json")

    bad_excl = known_invalid_interleaved_schedule()
    rep = validate_schedule(inst, bad_excl, require_deadlines=True)
    assert not rep.valid
    assert not rep.ok
    assert any("Exclusion violated" in e for e in rep.errors)

    # Missing unit
    s_missing = Schedule(units=known_integration_schedule().units[:-1])
    rep_missing = validate_schedule(inst, s_missing)
    assert not rep_missing.valid
    assert any("Missing expected units" in e for e in rep_missing.errors)

    # Processor conflict (duplicate tick)
    units = list(known_integration_schedule().units)
    units[-1] = UnitPlacement(units[-1].segment_id, units[-1].unit_index, 0)
    rep_conflict = validate_schedule(inst, Schedule(units=tuple(units)))
    assert not rep_conflict.valid
    assert any("Processor conflict" in e for e in rep_conflict.errors)

    # Deadline violation rejected when require_deadlines=True, accepted as valid when False
    late_sched = build_schedule_from_blocks(
        [
            ("A1", 0, 2),
            ("A2", 2, 3),
            ("A3", 3, 6),
            ("A4", 6, 10),
            ("A5", 10, 11),
            ("A6", 11, 12),
            ("A7", 12, 14),
            ("S", 14, 16),
            ("A8", 18, 21),  # f[A8] = 21 > 20
        ]
    )
    rep_strict = validate_schedule(inst, late_sched, require_deadlines=True)
    assert rep_strict.valid
    assert not rep_strict.feasible
    assert not rep_strict.ok
    assert rep_strict.logical_lmax == 1

    rep_valid_only = validate_schedule(inst, late_sched, require_deadlines=False)
    assert rep_valid_only.valid
    assert rep_valid_only.ok


def test_directional_exclusion_semantics_in_validator_and_oracle() -> None:
    """Section 12.1: A(r=0,C=2,d=3), B(r=1,C=1,d=2).
    - No exclusion: feasible via A(0), B(1), A(2).
    - Only A EXCLUDES B: infeasible.
    - Only B EXCLUDES A: feasible (A starts at 0 < s[B]=1, so B EXCLUDES A is vacuous!).
    """
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
    sched_aba = build_schedule_from_blocks([("A", 0, 1), ("B", 1, 2), ("A", 2, 3)])

    inst_none = parse_instance(base)
    assert validate_schedule(inst_none, sched_aba).ok
    assert solve_oracle(inst_none).feasible

    inst_ab = parse_instance({**base, "exclusion": [["A", "B"]]})
    assert not validate_schedule(inst_ab, sched_aba).ok
    assert not solve_oracle(inst_ab).feasible

    inst_ba = parse_instance({**base, "exclusion": [["B", "A"]]})
    assert validate_schedule(inst_ba, sched_aba).ok
    assert solve_oracle(inst_ba).feasible
