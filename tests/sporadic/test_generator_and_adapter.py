"""Unit tests for Fase B: sporadic generator, arrival validator, and adapter."""

from __future__ import annotations

import pytest

from str_project.sporadic import (
    SporadicValidationError,
    adapt_sequence_to_instance,
    generate_sequence,
    parse_scenario_spec,
    validate_adapted_instance,
)


def _base_single_task(releases: list[int], *, T: int = 10, D: int = 7, C: int = 3, H: int = 50):
    return parse_scenario_spec(
        {
            "schema_version": "sporadic-v1",
            "scenario_id": "unit_explicit",
            "horizon": H,
            "seed": 1,
            "generation_mode": "explicit",
            "tasks": [
                {
                    "id": "A",
                    "C": C,
                    "D": D,
                    "T": T,
                    "offset": 0,
                    "explicit_releases": releases,
                }
            ],
        }
    )


def test_explicit_min_interval_0_10_20_is_valid() -> None:
    sc = _base_single_task([0, 10, 20], T=10, D=7, C=3, H=30)
    seq = generate_sequence(sc)
    assert [a.release for a in seq.activations] == [0, 10, 20]
    assert [a.absolute_deadline for a in seq.activations] == [7, 17, 27]
    assert len(seq.discarded_activations) == 0


def test_explicit_irregular_0_13_27_40_is_valid() -> None:
    sc = _base_single_task([0, 13, 27, 40], T=10, D=7, C=3, H=50)
    seq = generate_sequence(sc)
    assert [a.release for a in seq.activations] == [0, 13, 27, 40]
    assert [a.absolute_deadline for a in seq.activations] == [7, 20, 34, 47]


def test_explicit_0_9_20_violates_minimum_separation_T10_and_is_rejected() -> None:
    sc = _base_single_task([0, 9, 20], T=10, D=7, C=3, H=50)
    with pytest.raises(SporadicValidationError, match="minimum separation T=10"):
        generate_sequence(sc)


def test_two_jobs_same_task_D_le_T_have_exact_deadlines_and_no_overlap() -> None:
    sc = _base_single_task([0, 10], T=10, D=10, C=4, H=20)
    seq = generate_sequence(sc)
    assert len(seq.activations) == 2
    a0, a1 = seq.activations
    assert a0.release == 0 and a0.absolute_deadline == 10
    assert a1.release == 10 and a1.absolute_deadline == 20
    assert a0.absolute_deadline <= a1.release


def test_horizon_policy_includes_d_eq_H_and_records_discarded_d_gt_H() -> None:
    # r=0 -> d=7 (kept), r=13 -> d=20 == H (kept), r=23 -> d=30 > H (discarded? no, r=23 >= H)
    # Better: H=20, D=7, releases=[0, 13, 15]? No, T=10 -> use D=7, T=6, releases=[0, 6, 13, 19] -> d=[7, 13, 20, 26]
    sc = _base_single_task([0, 6, 13, 19], T=6, D=7, C=2, H=20)
    # D=7 > T=6 requires explicit allow_unconstrained_deadlines; instead test with T=7, D=7!
    sc_constrained = _base_single_task([0, 7, 13, 19], T=6, D=6, C=2, H=20)
    # r=0->d=6, r=7->d=13, r=13->d=19, r=19->d=25 > 20
    # Also test exact d == H: r=14 -> d=20
    sc_exact = _base_single_task([0, 7, 14], T=7, D=6, C=2, H=20)
    seq_exact = generate_sequence(sc_exact)
    assert [a.absolute_deadline for a in seq_exact.activations] == [6, 13, 20]
    assert len(seq_exact.discarded_activations) == 0

    seq_disc = generate_sequence(sc_constrained)
    assert [a.release for a in seq_disc.activations] == [0, 7, 13]
    assert len(seq_disc.discarded_activations) == 1
    assert seq_disc.discarded_activations[0].release == 19
    assert seq_disc.discarded_activations[0].absolute_deadline == 25
    assert seq_disc.discarded_activations[0].reason == "deadline_exceeds_horizon"


def test_determinism_same_seed_gives_identical_hashes_across_modes() -> None:
    for mode in ("min_interval", "jittered", "bursty"):
        sc = parse_scenario_spec(
            {
                "schema_version": "sporadic-v1",
                "scenario_id": f"det_{mode}",
                "horizon": 80,
                "seed": 4242,
                "generation_mode": mode,
                "jitter_max": 5,
                "burst_size": 2,
                "tasks": [
                    {"id": "A", "C": 3, "D": 7, "T": 10, "offset": 0},
                    {"id": "B", "C": 2, "D": 6, "T": 12, "offset": 2},
                ],
            }
        )
        seq1 = generate_sequence(sc)
        seq2 = generate_sequence(sc)
        assert seq1.sequence_hash == seq2.sequence_hash
        ad1 = adapt_sequence_to_instance(seq1)
        ad2 = adapt_sequence_to_instance(seq2)
        assert ad1.input_hash == ad2.input_hash
        assert ad1.instance.instance_hash() == ad2.instance.instance_hash()


def test_bursty_never_violates_T_and_mixed_allows_simultaneous_arrivals() -> None:
    sc = parse_scenario_spec(
        {
            "schema_version": "sporadic-v1",
            "scenario_id": "mixed_test",
            "horizon": 100,
            "seed": 99,
            "generation_mode": "mixed",
            "tasks": [
                {"id": "T_min", "C": 2, "D": 8, "T": 10, "offset": 0, "mode": "min_interval"},
                {"id": "T_jit", "C": 2, "D": 9, "T": 10, "offset": 0, "mode": "jittered", "jitter_max": 4},
                {"id": "T_bst", "C": 3, "D": 10, "T": 12, "offset": 0, "mode": "bursty", "burst_size": 2, "burst_gap": 15},
            ],
        }
    )
    seq = generate_sequence(sc)
    # Simultaneous release at t=0 across all three tasks
    at_zero = [a.task_id for a in seq.activations if a.release == 0]
    assert set(at_zero) == {"T_min", "T_jit", "T_bst"}

    # Verify bursty task gaps are >= T=12 and include burst_gap pattern (12 then 27)
    bst_releases = [a.release for a in seq.activations if a.task_id == "T_bst"]
    bst_gaps = [b - a for a, b in zip(bst_releases, bst_releases[1:])]
    assert all(g >= 12 for g in bst_gaps)
    assert bst_gaps[0] == 12
    assert bst_gaps[1] == 27  # T + burst_gap = 12 + 15


def test_segmented_temperature_templates_preserve_precedences_and_directional_exclusions() -> None:
    sc = parse_scenario_spec(
        {
            "schema_version": "sporadic-v1",
            "scenario_id": "temp_sporadic_template",
            "horizon": 50,
            "seed": 7,
            "generation_mode": "explicit",
            "tasks": [
                {
                    "id": "P1",
                    "C": 6,
                    "D": 8,
                    "T": 20,
                    "offset": 0,
                    "explicit_releases": [0, 22],
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
                    "explicit_releases": [0, 22],
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
                    "explicit_releases": [8, 30],
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
    seq = generate_sequence(sc)
    adapted = adapt_sequence_to_instance(seq)
    validate_adapted_instance(adapted)

    # 2 activations of each of 3 tasks = 6 processes, 18 segments, 38 units
    assert len(adapted.instance.processes) == 6
    assert len(adapted.instance.segments) == 18
    assert adapted.instance.total_units() == 38

    # Check intra-process + cross precedence without spurious cross-activation links
    prec = set(adapted.instance.precedence)
    assert ("P1_A3_k0", "P2_A4_k0") in prec
    assert ("P1_A3_k1", "P2_A4_k1") in prec
    assert ("P1_A3_k0", "P2_A4_k1") not in prec
    assert ("P2_A7_k0", "P3_S_k0") not in prec  # Never invent A7 -> S!

    # Check directional exclusions on overlapping windows ([0,20) overlaps [8,20); [22,42) overlaps [30,42))
    excl = set(adapted.instance.exclusion)
    assert ("P2_A7_k0", "P3_S_k0") in excl
    assert ("P3_S_k0", "P2_A7_k0") in excl
    assert ("P2_A7_k1", "P3_S_k1") in excl
    assert ("P3_S_k1", "P2_A7_k1") in excl
    # Non-overlapping windows ([0,20) vs [30,42)) should NOT get spurious exclusions
    assert ("P2_A7_k0", "P3_S_k1") not in excl


def test_directional_exclusion_is_not_symmetrized_by_adapter() -> None:
    sc = parse_scenario_spec(
        {
            "schema_version": "sporadic-v1",
            "scenario_id": "dir_only",
            "horizon": 10,
            "seed": 1,
            "generation_mode": "explicit",
            "tasks": [
                {"id": "A", "C": 2, "D": 3, "T": 10, "offset": 0, "explicit_releases": [0]},
                {"id": "B", "C": 1, "D": 1, "T": 10, "offset": 1, "explicit_releases": [1]},
            ],
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
    adapted = adapt_sequence_to_instance(generate_sequence(sc))
    assert ("A_S1_k0", "B_S1_k0") in adapted.instance.exclusion
    assert ("B_S1_k0", "A_S1_k0") not in adapted.instance.exclusion
