"""Command-line interface for planning, validating, calibrating, executing, and comparing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .application import (
    ApplicationConfig,
    build_tasks,
    default_application_config,
    load_application_config,
)
from .calibration import calibrate_quantum, load_calibration, save_calibration
from .executor import TimingConfig, execute_schedule
from .instance_io import load_instance
from .model import InvalidInputError, PlanningLimits, collect_versions
from .planners.smt_z3 import plan_smt_z3
from .planners.xu_parnas import plan_xu_parnas
from .reporting import compare_runs, save_execution_artifacts
from .schedule_io import load_schedule, save_planning_result
from .validator import validate_schedule


def _load_app_config(config_path: str | None, input_path: str) -> ApplicationConfig:
    if config_path:
        return load_application_config(config_path)
    sibling = Path(input_path).resolve().parent / "application_config.json"
    if sibling.exists():
        return load_application_config(sibling)
    return default_application_config()


def _cmd_plan(args: argparse.Namespace) -> int:
    instance = load_instance(args.instance)
    limits = PlanningLimits(
        timeout_ms=args.timeout_ms,
        max_nodes=args.max_nodes,
        save_smt2_path=args.save_smt2,
        record_search_trace=args.trace,
    )
    if args.method == "xu-parnas":
        result = plan_xu_parnas(instance, limits, objective=args.objective)
    elif args.method == "smt-z3":
        result = plan_smt_z3(instance, limits, objective=args.objective)
    else:
        raise ValueError(f"Unknown planning method: {args.method!r}")

    save_planning_result(result, args.out)
    print(
        json.dumps(
            {
                "planner": result.planner,
                "instance_id": result.instance_id,
                "objective": result.objective,
                "status": result.status,
                "logical_lmax": result.logical_lmax,
                "lower_bound": result.lower_bound,
                "total_planning_ns": result.total_planning_ns,
                "nodes_generated": result.nodes_generated,
                "nodes_expanded": result.nodes_expanded,
                "out": str(args.out),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if result.status in {"feasible", "infeasible"} else 2


def _cmd_validate(args: argparse.Namespace) -> int:
    instance = load_instance(args.instance)
    schedule = load_schedule(args.schedule)
    report = validate_schedule(
        instance,
        schedule,
        require_deadlines=not args.no_require_deadlines,
    )
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    return 0 if report.ok else 1


def _cmd_calibrate(args: argparse.Namespace) -> int:
    instance = load_instance(args.instance)
    app_cfg = _load_app_config(args.config, args.input)
    schedule = load_schedule(args.schedule) if args.schedule else None
    cal = calibrate_quantum(
        instance,
        args.input,
        app_cfg,
        schedule=schedule,
        repetitions=args.repetitions,
        warmup_runs=args.warmup,
        safety_factor=args.safety_factor,
        min_margin_ns=args.min_margin_ns,
    )
    save_calibration(cal, args.out)
    print(
        json.dumps(
            {
                "quantum_ns": cal.quantum_ns,
                "quantum_ms": round(cal.quantum_ns / 1_000_000, 3),
                "max_work_ns": cal.global_work_stats["max_ns"],
                "max_dispatch_ns": cal.dispatch_probe_stats["max_ns"],
                "repetitions": cal.repetitions,
                "out": str(args.out),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _cmd_execute(args: argparse.Namespace) -> int:
    instance = load_instance(args.instance)
    schedule = load_schedule(args.schedule)
    app_cfg = _load_app_config(args.config, args.input)

    quantum_ns: int | None = None
    if args.mode == "timed":
        if not args.timing:
            raise InvalidInputError("--timing <calibration.json> is required in timed mode.")
        cal = load_calibration(args.timing)
        quantum_ns = int(cal["quantum_ns"])

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    record_file = out_dir / "p3_record.json"

    tasks = build_tasks(app_cfg, args.input, record_file)
    timing_cfg = TimingConfig(
        mode=args.mode,
        quantum_ns=quantum_ns,
        allow_invalid_schedule=args.allow_invalid_schedule,
    )
    report = execute_schedule(instance, schedule, tasks, timing_cfg)
    report_path = save_execution_artifacts(report, schedule, out_dir)
    print(
        json.dumps(
            {
                "status": report.status,
                "mode": report.mode,
                "units_executed": report.units_executed,
                "total_wall_ns": report.total_wall_ns,
                "max_dispatch_lateness_ns": report.max_dispatch_lateness_ns,
                "max_work_elapsed_ns": report.max_work_elapsed_ns,
                "max_slot_overrun_ns": report.max_slot_overrun_ns,
                "recorded_version": (report.recorded_copy or {}).get("version"),
                "report": str(report_path),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if report.status == "ok" else 1


def _cmd_compare(args: argparse.Namespace) -> int:
    comp = compare_runs(args.left, args.right, args.out)
    print(
        json.dumps(
            {
                "left": comp["left_label"],
                "right": comp["right_label"],
                "planning_agreement": (comp["planning"] or {}).get("status_agreement"),
                "logical_final_equal": (comp["execution_logical"] or {}).get("final_shared_state_equal"),
                "timed_final_equal": (comp["execution_timed"] or {}).get("final_shared_state_equal"),
                "out": str(args.out),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _cmd_benchmark(args: argparse.Namespace) -> int:
    """Run repeated alternating planning benchmarks (Section 15 protocol)."""
    instance = load_instance(args.instance)
    limits = PlanningLimits(timeout_ms=args.timeout_ms)
    obj = args.objective or instance.objective

    samples: dict[str, list[dict[str, Any]]] = {"xu-parnas": [], "smt-z3": []}
    total_rounds = args.warmup + args.repetitions

    for r_idx in range(total_rounds):
        order = ("xu-parnas", "smt-z3") if r_idx % 2 == 0 else ("smt-z3", "xu-parnas")
        for method in order:
            res = (
                plan_xu_parnas(instance, limits, objective=obj)
                if method == "xu-parnas"
                else plan_smt_z3(instance, limits, objective=obj)
            )
            if r_idx >= args.warmup:
                samples[method].append(
                    {
                        "round": r_idx - args.warmup + 1,
                        "order": list(order),
                        "status": res.status,
                        "logical_lmax": res.logical_lmax,
                        "preprocessing_ns": res.preprocessing_ns,
                        "model_build_ns": res.model_build_ns,
                        "search_ns": res.search_ns,
                        "total_planning_ns": res.total_planning_ns,
                        "nodes_generated": res.nodes_generated,
                        "nodes_expanded": res.nodes_expanded,
                    }
                )

    def _agg(rows: list[dict[str, Any]]) -> dict[str, Any]:
        totals = sorted(r["total_planning_ns"] for r in rows)
        n = len(totals)
        median = totals[n // 2] if n % 2 == 1 else (totals[n // 2 - 1] + totals[n // 2]) // 2
        return {
            "count": n,
            "statuses": sorted({r["status"] for r in rows}),
            "min_ns": totals[0],
            "median_ns": median,
            "max_ns": totals[-1],
            "mean_ns": sum(totals) // n,
        }

    payload = {
        "instance_id": instance.instance_id,
        "instance_hash": instance.instance_hash(),
        "objective": obj,
        "warmup_rounds": args.warmup,
        "repetitions": args.repetitions,
        "timeout_ms": args.timeout_ms,
        "summary": {
            "xu-parnas": _agg(samples["xu-parnas"]),
            "smt-z3": _agg(samples["smt-z3"]),
        },
        "samples": samples,
        "versions": collect_versions(),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="str_project.cli",
        description="Escalonamento Pré-Execução em Tempo Real: Xu & Parnas vs SMT/Z3",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # plan
    p_plan = sub.add_parser("plan", help="Calculate a pre-run-time schedule.")
    p_plan.add_argument("--method", choices=["xu-parnas", "smt-z3"], required=True)
    p_plan.add_argument("--instance", required=True)
    p_plan.add_argument("--out", required=True)
    p_plan.add_argument("--objective", choices=["feasibility", "min_lmax"], default=None)
    p_plan.add_argument("--timeout-ms", type=int, default=30_000)
    p_plan.add_argument("--max-nodes", type=int, default=None)
    p_plan.add_argument("--save-smt2", default=None)
    p_plan.add_argument("--trace", action="store_true")
    p_plan.set_defaults(func=_cmd_plan)

    # validate
    p_val = sub.add_parser("validate", help="Independently validate a schedule.")
    p_val.add_argument("--instance", required=True)
    p_val.add_argument("--schedule", required=True)
    p_val.add_argument("--no-require-deadlines", action="store_true")
    p_val.set_defaults(func=_cmd_validate)

    # calibrate
    p_cal = sub.add_parser("calibrate", help="Calibrate physical quantum_ns empirically.")
    p_cal.add_argument("--instance", required=True)
    p_cal.add_argument("--input", required=True)
    p_cal.add_argument("--out", required=True)
    p_cal.add_argument("--config", default=None)
    p_cal.add_argument("--schedule", default=None)
    p_cal.add_argument("--repetitions", type=int, default=20)
    p_cal.add_argument("--warmup", type=int, default=3)
    p_cal.add_argument("--safety-factor", type=float, default=4.0)
    p_cal.add_argument("--min-margin-ns", type=int, default=1_500_000)
    p_cal.set_defaults(func=_cmd_calibrate)

    # execute
    p_exec = sub.add_parser("execute", help="Execute a verified schedule over real tasks.")
    p_exec.add_argument("--instance", required=True)
    p_exec.add_argument("--schedule", required=True)
    p_exec.add_argument("--input", required=True)
    p_exec.add_argument("--mode", choices=["logical", "timed"], required=True)
    p_exec.add_argument("--timing", default=None)
    p_exec.add_argument("--config", default=None)
    p_exec.add_argument("--out", required=True)
    p_exec.add_argument("--allow-invalid-schedule", action="store_true")
    p_exec.set_defaults(func=_cmd_execute)

    # compare
    p_cmp = sub.add_parser("compare", help="Compare planning and execution runs.")
    p_cmp.add_argument("--left", required=True)
    p_cmp.add_argument("--right", required=True)
    p_cmp.add_argument("--out", required=True)
    p_cmp.set_defaults(func=_cmd_compare)

    # benchmark
    p_bench = sub.add_parser("benchmark", help="Run alternating planning benchmarks.")
    p_bench.add_argument("--instance", required=True)
    p_bench.add_argument("--out", required=True)
    p_bench.add_argument("--objective", choices=["feasibility", "min_lmax"], default=None)
    p_bench.add_argument("--repetitions", type=int, default=10)
    p_bench.add_argument("--warmup", type=int, default=2)
    p_bench.add_argument("--timeout-ms", type=int, default=30_000)
    p_bench.set_defaults(func=_cmd_benchmark)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except InvalidInputError as exc:
        print(f"ERROR (invalid_input): {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
