"""Dedicated CLI for the sporadic task extension (python -m str_project.sporadic.cli)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..instance_io import parse_instance
from ..schedule_io import load_schedule
from ..validator import validate_schedule
from .adapter import adapt_sequence_to_instance, save_adapted_instance
from .experiments import run_sporadic_matrix, run_sporadic_scenario
from .generator import generate_sequence
from .models import load_scenario_spec
from .reporting import export_matrix_results
from .validation import SporadicValidationError


def _cmd_generate(args: argparse.Namespace) -> int:
    spec = load_scenario_spec(args.config)
    seq = generate_sequence(spec)
    adapted = adapt_sequence_to_instance(seq)
    out_path = save_adapted_instance(adapted, args.out)
    print(
        json.dumps(
            {
                "scenario_id": spec.scenario_id,
                "seed": spec.seed,
                "generation_mode": spec.generation_mode,
                "horizon": spec.horizon,
                "num_jobs": adapted.metadata["num_jobs"],
                "num_discarded_jobs": adapted.metadata["num_discarded_jobs"],
                "num_segments": adapted.metadata["num_segments"],
                "total_units": adapted.metadata["total_units"],
                "input_hash": adapted.input_hash,
                "instance_hash": adapted.instance.instance_hash(),
                "out": str(out_path),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _cmd_run_scenario(args: argparse.Namespace) -> int:
    spec = load_scenario_spec(args.config)
    bundle = run_sporadic_scenario(
        spec,
        out_dir=args.out,
        timeout_ms=args.timeout_ms,
        save_instance=True,
        save_schedules=args.save_schedules,
    )
    print(
        json.dumps(
            {
                "scenario_id": bundle["scenario_id"],
                "seed": bundle["seed"],
                "input_hash": bundle["input_hash"],
                "instance_hash": bundle["instance_hash"],
                "agreement": bundle["agreement"],
                "xu-parnas": {
                    "status": bundle["records"]["xu-parnas"]["status"],
                    "validation_passed": bundle["records"]["xu-parnas"]["validation_passed"],
                    "wall_ms": round(bundle["records"]["xu-parnas"]["planning_wall_time_ns"] / 1e6, 3),
                },
                "smt-z3": {
                    "status": bundle["records"]["smt-z3"]["status"],
                    "validation_passed": bundle["records"]["smt-z3"]["validation_passed"],
                    "wall_ms": round(bundle["records"]["smt-z3"]["planning_wall_time_ns"] / 1e6, 3),
                },
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _cmd_run_matrix(args: argparse.Namespace) -> int:
    matrix_cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    matrix_out = run_sporadic_matrix(
        matrix_cfg,
        out_dir=args.out,
        timeout_ms=args.timeout_ms,
        warmup_scenarios=args.warmup,
        save_all_instances=args.save_all,
        save_all_schedules=args.save_all,
    )
    summary = export_matrix_results(matrix_out, args.out, generate_plots=not args.no_plots)
    print(
        json.dumps(
            {
                "matrix_id": summary["matrix_id"],
                "total_scenarios": summary["total_scenarios"],
                "decided_pairs": summary["decided_pairs"],
                "agreed_pairs": summary["agreed_pairs"],
                "agreement_rate": summary["agreement_rate"],
                "divergences": len(summary["divergences"]),
                "xu-parnas": summary["overall"]["xu-parnas"],
                "smt-z3": summary["overall"]["smt-z3"],
                "out": str(args.out),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    raw_inst = json.loads(Path(args.instance).read_text(encoding="utf-8"))
    inst_dict = {
        "schema_version": 1,
        "instance_id": f"{raw_inst['scenario_id']}__seed{raw_inst['seed']}",
        "objective": raw_inst.get("objective", "feasibility"),
        "processes": raw_inst["processes"],
        "segments": raw_inst["segments"],
        "precedence": raw_inst["precedences"],
        "exclusion": raw_inst["exclusions"],
    }
    instance = parse_instance(inst_dict)
    schedule = load_schedule(args.schedule)
    report = validate_schedule(
        instance, schedule, require_deadlines=not args.no_require_deadlines
    )
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    return 0 if report.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="str_project.sporadic.cli",
        description="Extensão para Tarefas Esporádicas — Xu & Parnas vs SMT/Z3",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("generate", help="Generate and freeze an adapted sporadic instance.")
    p_gen.add_argument("--config", required=True)
    p_gen.add_argument("--out", required=True)
    p_gen.set_defaults(func=_cmd_generate)

    p_sc = sub.add_parser("run-scenario", help="Run both planners on a single sporadic scenario.")
    p_sc.add_argument("--config", required=True)
    p_sc.add_argument("--out", required=True)
    p_sc.add_argument("--timeout-ms", type=int, default=5_000)
    p_sc.add_argument("--save-schedules", action="store_true", default=True)
    p_sc.set_defaults(func=_cmd_run_scenario)

    p_mat = sub.add_parser("run-matrix", help="Run a sporadic experimental matrix.")
    p_mat.add_argument("--config", required=True)
    p_mat.add_argument("--out", required=True)
    p_mat.add_argument("--timeout-ms", type=int, default=None)
    p_mat.add_argument("--warmup", type=int, default=1)
    p_mat.add_argument("--save-all", action="store_true")
    p_mat.add_argument("--no-plots", action="store_true")
    p_mat.set_defaults(func=_cmd_run_matrix)

    p_val = sub.add_parser("validate", help="Validate a schedule against an exported sporadic instance.")
    p_val.add_argument("--instance", required=True)
    p_val.add_argument("--schedule", required=True)
    p_val.add_argument("--no-require-deadlines", action="store_true")
    p_val.set_defaults(func=_cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (SporadicValidationError, ValueError) as exc:
        print(f"ERROR (sporadic_validation): {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
