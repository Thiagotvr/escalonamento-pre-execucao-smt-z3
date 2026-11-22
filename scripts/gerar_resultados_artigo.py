"""Reproducible experiment suite generating all tables, raw JSON data, and IEEE figures for the paper."""

from __future__ import annotations

import csv
import json
import math
import random
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

from str_project.application import (
    build_tasks,
    load_application_config,
    run_sequential_reference,
)
from str_project.calibration import calibrate_quantum
from str_project.executor import TimingConfig, execute_schedule
from str_project.instance_io import load_instance, parse_instance
from str_project.model import PlanningLimits, SchedulingInstance, collect_versions
from str_project.oracle import solve_oracle
from str_project.planners.smt_z3 import plan_smt_z3
from str_project.planners.xu_parnas import plan_xu_parnas
from str_project.schedule_io import known_invalid_interleaved_schedule
from str_project.validator import validate_schedule

ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = ROOT / "resultados_artigo"
RAW_DIR = OUT_ROOT / "dados_brutos"
TAB_DIR = OUT_ROOT / "tabelas"
FIG_DIR = OUT_ROOT / "figuras"


def _ns_to_ms(ns: int | float | None) -> float | None:
    if ns is None:
        return None
    return ns / 1_000_000.0


def _fmt_ms(ns: int | float | None, decimals: int = 3) -> str:
    if ns is None:
        return "--"
    return f"{ns / 1_000_000.0:.{decimals}f}"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_csv(path: Path, headers: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        writer.writerows(rows)


def _write_tex(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def _scale_instance(inst: SchedulingInstance, factor: int) -> SchedulingInstance:
    data = inst.canonical_dict()
    data["instance_id"] = f"{inst.instance_id}_scale_{factor}x"
    for seg in data["segments"]:
        seg["release"] *= factor
        seg["execution_units"] *= factor
        seg["deadline"] *= factor
    return parse_instance(data)


def _alternating_benchmark(
    inst: SchedulingInstance,
    *,
    objective: str = "feasibility",
    repetitions: int = 10,
    warmup: int = 2,
    timeout_ms: int = 15_000,
) -> dict[str, Any]:
    limits = PlanningLimits(timeout_ms=timeout_ms)
    records: dict[str, list[dict[str, Any]]] = {"xu-parnas": [], "smt-z3": []}
    last_results: dict[str, Any] = {}

    for r in range(warmup + repetitions):
        order = ("xu-parnas", "smt-z3") if r % 2 == 0 else ("smt-z3", "xu-parnas")
        for method in order:
            res = (
                plan_xu_parnas(inst, limits, objective=objective)
                if method == "xu-parnas"
                else plan_smt_z3(inst, limits, objective=objective)
            )
            last_results[method] = res
            if r >= warmup:
                records[method].append(
                    {
                        "status": res.status,
                        "logical_lmax": res.logical_lmax,
                        "lower_bound": res.lower_bound,
                        "preprocessing_ns": res.preprocessing_ns,
                        "model_build_ns": res.model_build_ns,
                        "search_ns": res.search_ns,
                        "total_planning_ns": res.total_planning_ns,
                        "nodes_generated": res.nodes_generated,
                        "nodes_expanded": res.nodes_expanded,
                        "validation_ok": res.validation.ok if res.validation else None,
                    }
                )

    def _agg(rows: list[dict[str, Any]]) -> dict[str, Any]:
        totals = [x["total_planning_ns"] for x in rows]
        preps = [x["preprocessing_ns"] for x in rows if x["preprocessing_ns"] is not None]
        builds = [x["model_build_ns"] for x in rows if x["model_build_ns"] is not None]
        searches = [x["search_ns"] for x in rows if x["search_ns"] is not None]
        return {
            "count": len(rows),
            "statuses": sorted({x["status"] for x in rows}),
            "logical_lmax": rows[-1]["logical_lmax"],
            "lower_bound": rows[-1]["lower_bound"],
            "nodes_generated": rows[-1]["nodes_generated"],
            "nodes_expanded": rows[-1]["nodes_expanded"],
            "validation_ok": rows[-1]["validation_ok"],
            "total_min_ns": min(totals),
            "total_median_ns": int(statistics.median(totals)),
            "total_max_ns": max(totals),
            "total_mean_ns": int(statistics.mean(totals)),
            "prep_median_ns": int(statistics.median(preps)) if preps else None,
            "build_median_ns": int(statistics.median(builds)) if builds else None,
            "search_median_ns": int(statistics.median(searches)) if searches else None,
        }

    return {
        "instance_id": inst.instance_id,
        "segments": len(inst.segments),
        "total_units": inst.total_units(),
        "objective": objective,
        "summary": {
            "xu-parnas": _agg(records["xu-parnas"]),
            "smt-z3": _agg(records["smt-z3"]),
        },
        "last_schedules": {
            m: (last_results[m].schedule.to_dict() if last_results[m].schedule else None)
            for m in ("xu-parnas", "smt-z3")
        },
        "z3_statistics": last_results["smt-z3"].details.get("z3_statistics"),
        "xu_root_details": {
            k: last_results["xu-parnas"].details.get(k)
            for k in ("root_lmax", "root_lower_bound", "root_latest_segment", "root_g1", "root_g2")
        },
    }


def run_exp1_validacao_cruzada() -> dict[str, Any]:
    """Experiment 1: Fidelity & correctness audit (Reference cases + 100 random feasibility + 30 min_lmax)."""
    temp_inst = load_instance(ROOT / "instances" / "temperature_case.json")
    ex1_inst = load_instance(ROOT / "instances" / "xu_example_1.json")
    ex2_inst = load_instance(ROOT / "instances" / "xu_example_2.json")

    preempt_base = {
        "schema_version": 1,
        "instance_id": "preempcao_sem_ex",
        "objective": "feasibility",
        "processes": [{"id": "PA", "segments": ["A"]}, {"id": "PB", "segments": ["B"]}],
        "segments": [
            {"id": "A", "release": 0, "execution_units": 2, "deadline": 3},
            {"id": "B", "release": 1, "execution_units": 1, "deadline": 2},
        ],
        "precedence": [],
        "exclusion": [],
    }
    cases = [
        ("temperature_case_v1", temp_inst, False),
        ("xu_parnas_example_1 (G1)", ex1_inst, False),
        ("xu_parnas_example_2 (G2)", ex2_inst, False),
        ("preempcao_sem_EX", parse_instance(preempt_base), True),
        (
            "exclusao_dir_A_EX_B",
            parse_instance({**preempt_base, "instance_id": "ex_ab", "exclusion": [["A", "B"]]}),
            True,
        ),
        (
            "exclusao_dir_B_EX_A",
            parse_instance({**preempt_base, "instance_id": "ex_ba", "exclusion": [["B", "A"]]}),
            True,
        ),
        (
            "inviavel_ciclo_PC",
            parse_instance(
                {
                    "schema_version": 1,
                    "instance_id": "ciclo_pc",
                    "objective": "feasibility",
                    "processes": [{"id": "P1", "segments": ["A"]}, {"id": "P2", "segments": ["B"]}],
                    "segments": [
                        {"id": "A", "release": 0, "execution_units": 2, "deadline": 10},
                        {"id": "B", "release": 0, "execution_units": 2, "deadline": 10},
                    ],
                    "precedence": [["A", "B"], ["B", "A"]],
                    "exclusion": [],
                }
            ),
            True,
        ),
        (
            "inviavel_sobrecarga",
            parse_instance(
                {
                    "schema_version": 1,
                    "instance_id": "sobrecarga",
                    "objective": "feasibility",
                    "processes": [{"id": "P1", "segments": ["A"]}, {"id": "P2", "segments": ["B"]}],
                    "segments": [
                        {"id": "A", "release": 0, "execution_units": 4, "deadline": 5},
                        {"id": "B", "release": 0, "execution_units": 3, "deadline": 5},
                    ],
                    "precedence": [],
                    "exclusion": [],
                }
            ),
            True,
        ),
    ]

    ref_rows = []
    for label, inst, use_oracle in cases:
        orac_status = "--"
        if use_oracle:
            orac = solve_oracle(inst, objective="feasibility")
            orac_status = "feasible" if orac.feasible else "infeasible"
        xu = plan_xu_parnas(inst, PlanningLimits(timeout_ms=15_000))
        z3 = plan_smt_z3(inst, PlanningLimits(timeout_ms=15_000))
        xu_val = validate_schedule(inst, xu.schedule, require_deadlines=True).ok if xu.schedule else None
        z3_val = validate_schedule(inst, z3.schedule, require_deadlines=True).ok if z3.schedule else None
        agree = xu.status == z3.status and (not use_oracle or xu.status == orac_status)
        ref_rows.append(
            {
                "caso": label,
                "segmentos": len(inst.segments),
                "unidades": inst.total_units(),
                "oraculo": orac_status,
                "xu_parnas": xu.status,
                "smt_z3": z3.status,
                "xu_lmax": xu.logical_lmax,
                "z3_lmax": z3.logical_lmax,
                "validador_xu": xu_val,
                "validador_z3": z3_val,
                "concordancia": agree,
            }
        )

    # Randomized audit: 100 feasibility + 30 min_lmax
    rng = random.Random(1990)
    feas_total = 100
    feas_agree = 0
    feas_feasible_cnt = 0
    feas_invalid_cnt = 0

    opt_total = 30
    opt_agree = 0

    for idx in range(feas_total):
        n_segs = rng.randint(2, 4)
        names = [f"S{i}" for i in range(n_segs)]
        segs = []
        for nm in names:
            r = rng.randint(0, 5)
            c = rng.randint(1, 3)
            d = r + c + rng.randint(0, 3)
            segs.append({"id": nm, "release": r, "execution_units": c, "deadline": d})
        prec, excl = [], []
        for i in range(n_segs):
            for j in range(n_segs):
                if i == j:
                    continue
                if i < j and rng.random() < 0.2:
                    prec.append([names[i], names[j]])
                if rng.random() < 0.35:
                    excl.append([names[i], names[j]])
        inst = parse_instance(
            {
                "schema_version": 1,
                "instance_id": f"audit_{idx}",
                "objective": "feasibility",
                "processes": [{"id": f"P{i}", "segments": [nm]} for i, nm in enumerate(names)],
                "segments": segs,
                "precedence": prec,
                "exclusion": excl,
            }
        )
        orac = solve_oracle(inst, objective="feasibility")
        xu = plan_xu_parnas(inst, PlanningLimits(timeout_ms=10_000), objective="feasibility")
        z3 = plan_smt_z3(inst, PlanningLimits(timeout_ms=10_000), objective="feasibility")
        if orac.feasible:
            feas_feasible_cnt += 1
        if (xu.status == "feasible") == orac.feasible and xu.status == z3.status:
            feas_agree += 1
        if xu.schedule and not validate_schedule(inst, xu.schedule, require_deadlines=True).ok:
            feas_invalid_cnt += 1
        if z3.schedule and not validate_schedule(inst, z3.schedule, require_deadlines=True).ok:
            feas_invalid_cnt += 1

        if idx < opt_total:
            orac_o = solve_oracle(inst, objective="min_lmax")
            xu_o = plan_xu_parnas(inst, PlanningLimits(timeout_ms=10_000), objective="min_lmax")
            z3_o = plan_smt_z3(inst, PlanningLimits(timeout_ms=10_000), objective="min_lmax")
            if xu_o.logical_lmax == orac_o.optimal_lmax == z3_o.logical_lmax:
                opt_agree += 1

    payload = {
        "reference_cases": ref_rows,
        "random_feasibility_audit": {
            "total": feas_total,
            "feasible_count": feas_feasible_cnt,
            "infeasible_count": feas_total - feas_feasible_cnt,
            "full_agreement_count": feas_agree,
            "invalid_schedules": feas_invalid_cnt,
        },
        "random_min_lmax_audit": {
            "total": opt_total,
            "exact_lmax_agreement_count": opt_agree,
        },
    }
    _write_json(RAW_DIR / "validacao_cruzada.json", payload)

    # CSV + LaTeX Table 1
    csv_headers = [
        "Caso",
        "Seg.",
        "Unid.",
        "Oraculo",
        "Xu_Parnas",
        "SMT_Z3",
        "Lmax_Xu",
        "Lmax_Z3",
        "Concordancia",
    ]
    csv_rows = [
        [
            r["caso"],
            r["segmentos"],
            r["unidades"],
            r["oraculo"],
            r["xu_parnas"],
            r["smt_z3"],
            r["xu_lmax"],
            r["z3_lmax"],
            "Sim" if r["concordancia"] else "Nao",
        ]
        for r in ref_rows
    ]
    csv_rows.append(
        [
            f"Lote aleatorio viabilidade (N={feas_total})",
            "2-4",
            "2-12",
            f"{feas_feasible_cnt}V/{feas_total - feas_feasible_cnt}I",
            f"{feas_agree}/{feas_total}",
            f"{feas_agree}/{feas_total}",
            "--",
            "--",
            f"{100.0 * feas_agree / feas_total:.1f}%",
        ]
    )
    csv_rows.append(
        [
            f"Lote aleatorio min Lmax (N={opt_total})",
            "2-4",
            "2-12",
            "Exato",
            f"{opt_agree}/{opt_total}",
            f"{opt_agree}/{opt_total}",
            "Exato",
            "Exato",
            f"{100.0 * opt_agree / opt_total:.1f}%",
        ]
    )
    _write_csv(TAB_DIR / "tabela1_validacao_cruzada.csv", csv_headers, csv_rows)

    tex_lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{Valida\c{c}\~ao cruzada de fidelidade e conformidade entre Or\'aculo, Xu \& Parnas e SMT/Z3.}",
        r"\label{tab:validacao_cruzada}",
        r"\scriptsize",
        r"\begin{tabular}{lcccccc}",
        r"\hline",
        r"\textbf{Inst\^ancia / Lote} & \textbf{Seg./Unid.} & \textbf{Or\'aculo} & \textbf{Xu\&Parnas} & \textbf{SMT/Z3} & \textbf{Conc.} \\",
        r"\hline",
    ]
    for r in ref_rows:
        lbl = r["caso"].replace("_", r"\_")
        st_map = {"feasible": "Vi\\'avel", "infeasible": "Invi\\'avel", "--": "--"}
        conc_txt = r"100\%" if r["concordancia"] else "Falha"
        tex_lines.append(
            f"{lbl} & {r['segmentos']}/{r['unidades']} & {st_map[r['oraculo']]} & "
            f"{st_map[r['xu_parnas']]} & {st_map[r['smt_z3']]} & "
            f"{conc_txt} \\\\"
        )
    tex_lines.append(r"\hline")
    tex_lines.append(
        f"Lote aleat\\'orio viab. ($N={feas_total}$) & 2--4 / 2--12 & {feas_feasible_cnt}V/{feas_total - feas_feasible_cnt}I & "
        f"{feas_agree}/{feas_total} & {feas_agree}/{feas_total} & {100.0 * feas_agree / feas_total:.1f}\\% \\\\"
    )
    tex_lines.append(
        f"Lote aleat\\'orio $\\min L_{{\\max}}$ ($N={opt_total}$) & 2--4 / 2--12 & \'Otimo & "
        f"{opt_agree}/{opt_total} & {opt_agree}/{opt_total} & {100.0 * opt_agree / opt_total:.1f}\\% \\\\"
    )
    tex_lines += [
        r"\hline",
        r"\end{tabular}",
        r"\end{table}",
    ]
    _write_tex(TAB_DIR / "tabela1_validacao_cruzada.tex", "\n".join(tex_lines))
    return payload


def run_exp2_referencia_e_gantt() -> dict[str, Any]:
    """Experiment 2: Planning benchmark on reference instances + Fig 1 (Gantt) + Fig 2 (Bar chart)."""
    insts = [
        ("temperature_case_v1", load_instance(ROOT / "instances" / "temperature_case.json")),
        ("xu_parnas_example_1", load_instance(ROOT / "instances" / "xu_example_1.json")),
        ("xu_parnas_example_2", load_instance(ROOT / "instances" / "xu_example_2.json")),
    ]
    results = []
    for _, inst in insts:
        results.append(
            _alternating_benchmark(inst, objective="feasibility", repetitions=15, warmup=3, timeout_ms=15_000)
        )
    _write_json(RAW_DIR / "benchmark_referencia.json", {"results": results, "versions": collect_versions()})

    # Table 2 CSV + LaTeX
    headers = [
        "Instancia",
        "Segmentos",
        "Unidades",
        "Xu_mediana_ms",
        "Xu_min_ms",
        "Xu_max_ms",
        "Xu_nos_ger_exp",
        "Z3_prep_ms",
        "Z3_build_ms",
        "Z3_search_ms",
        "Z3_mediana_ms",
        "Z3_min_ms",
        "Z3_max_ms",
        "Razao_Z3_Xu",
    ]
    rows = []
    tex_rows = []
    for res in results:
        xu = res["summary"]["xu-parnas"]
        z3 = res["summary"]["smt-z3"]
        ratio = z3["total_median_ns"] / max(1, xu["total_median_ns"])
        rows.append(
            [
                res["instance_id"],
                res["segments"],
                res["total_units"],
                _fmt_ms(xu["total_median_ns"]),
                _fmt_ms(xu["total_min_ns"]),
                _fmt_ms(xu["total_max_ns"]),
                f"{xu['nodes_generated']}/{xu['nodes_expanded']}",
                _fmt_ms(z3["prep_median_ns"]),
                _fmt_ms(z3["build_median_ns"]),
                _fmt_ms(z3["search_median_ns"]),
                _fmt_ms(z3["total_median_ns"]),
                _fmt_ms(z3["total_min_ns"]),
                _fmt_ms(z3["total_max_ns"]),
                f"{ratio:.1f}x",
            ]
        )
        lbl = res["instance_id"].replace("_", r"\_")
        tex_rows.append(
            f"{lbl} & {res['segments']}/{res['total_units']} & "
            f"{_fmt_ms(xu['total_median_ns'], 2)} [{_fmt_ms(xu['total_min_ns'], 2)}--{_fmt_ms(xu['total_max_ns'], 2)}] & "
            f"{xu['nodes_generated']}/{xu['nodes_expanded']} & "
            f"{_fmt_ms(z3['build_median_ns'], 2)} & {_fmt_ms(z3['search_median_ns'], 2)} & "
            f"{_fmt_ms(z3['total_median_ns'], 2)} & {ratio:.1f}$\\times$ \\\\"
        )
    _write_csv(TAB_DIR / "tabela2_desempenho_referencia.csv", headers, rows)

    tex = "\n".join(
        [
            r"\begin{table*}[t]",
            r"\centering",
            r"\caption{Desempenho de planejamento nas inst\^ancias de refer\^encia (15 repeti\c{c}\~oes alternadas, 3 aquecimentos, modo viabilidade).}",
            r"\label{tab:desempenho_referencia}",
            r"\footnotesize",
            r"\begin{tabular}{lccccccc}",
            r"\hline",
            r"\textbf{Inst\^ancia} & \textbf{Seg./Unid.} & \textbf{Xu\&Parnas med. [min--max] (ms)} & \textbf{N\'os (ger./exp.)} & \textbf{Z3 build (ms)} & \textbf{Z3 check (ms)} & \textbf{Z3 total med. (ms)} & \textbf{Raz\~ao Z3/Xu} \\",
            r"\hline",
            *tex_rows,
            r"\hline",
            r"\end{tabular}",
            r"\end{table*}",
        ]
    )
    _write_tex(TAB_DIR / "tabela2_desempenho_referencia.tex", tex)

    # Figure 1: Comparative Gantt Chart for temperature_case_v1
    temp_res = results[0]
    xu_merged = temp_res["last_schedules"]["xu-parnas"]["merged_view"]
    z3_merged = temp_res["last_schedules"]["smt-z3"]["merged_view"]

    proc_of = {
        "A1": "P1", "A2": "P1", "A3": "P1",
        "A4": "P2", "A5": "P2", "A6": "P2", "A7": "P2",
        "S": "P3", "A8": "P3",
    }
    colors = {"P1": "#2b6cb0", "P2": "#2f855a", "P3": "#c05621"}

    fig, axes = plt.subplots(2, 1, figsize=(8.2, 4.3), sharex=True)
    titles = [
        "Escala Xu & Parnas (Lmax = -1 | S antes de A7 → P3 registra E0, versão 0)",
        "Escala SMT/Z3 (Lmax = -1 | A7 antes de S → P3 registra bloco atual, versão 1)",
    ]
    for ax, blocks, title in zip(axes, [xu_merged, z3_merged], titles):
        for b in blocks:
            seg = b["segment_id"]
            st, en = b["start_tick"], b["end_tick"]
            proc = proc_of[seg]
            hatch = "///" if seg in {"A7", "S"} else None
            ax.barh(
                0,
                en - st,
                left=st,
                height=0.55,
                color=colors[proc],
                edgecolor="white",
                linewidth=1.2,
                hatch=hatch,
                alpha=0.92,
            )
            ax.text(
                (st + en) / 2.0,
                0,
                seg,
                ha="center",
                va="center",
                color="white",
                fontsize=8.5,
                fontweight="bold",
            )
        ax.axvline(8, color="#4a5568", linestyle="--", linewidth=1.0)
        ax.axvline(20, color="#c53030", linestyle=":", linewidth=1.2)
        ax.text(8.1, 0.37, "d(P1)=8, r(P3)=8", fontsize=7.5, color="#4a5568")
        ax.text(19.8, 0.37, "d(P2,P3)=20", fontsize=7.5, color="#c53030", ha="right")
        ax.set_yticks([])
        ax.set_ylim(-0.45, 0.52)
        ax.set_title(title, fontsize=9.5, fontweight="bold", pad=6)
        ax.grid(axis="x", linestyle=":", alpha=0.4)

    axes[1].set_xlabel("Tempo lógico (unidades discretas u)", fontsize=9)
    axes[1].set_xticks(range(0, 21, 1))
    axes[1].set_xlim(0, 20.5)

    legend_handles = [
        mpatches.Patch(color=colors["P1"], label="P1 – Aquisição (A1–A3)"),
        mpatches.Patch(color=colors["P2"], label="P2 – Análise (A4–A7)"),
        mpatches.Patch(color=colors["P3"], label="P3 – Registro (S, A8)"),
        mpatches.Patch(facecolor="#718096", hatch="///", edgecolor="white", label="Exclusão mútua (A7 ↔ S)"),
    ]
    fig.legend(handles=legend_handles, loc="lower center", ncol=4, fontsize=7.8, frameon=False, bbox_to_anchor=(0.5, -0.02))
    fig.tight_layout(rect=[0, 0.06, 1, 1])
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_DIR / "fig1_gantt_temperatura.png", dpi=300, bbox_inches="tight")
    fig.savefig(FIG_DIR / "fig1_gantt_temperatura.pdf", bbox_inches="tight")
    plt.close(fig)

    # Figure 2: Bar chart of planning time (log scale)
    labels = ["Temperatura\n(9 seg, 19 u)", "Xu Ex. 1 (G1)\n(4 seg, 80 u)", "Xu Ex. 2 (G2)\n(3 seg, 100 u)"]
    xu_ms = [r["summary"]["xu-parnas"]["total_median_ns"] / 1e6 for r in results]
    z3_ms = [r["summary"]["smt-z3"]["total_median_ns"] / 1e6 for r in results]

    fig, ax = plt.subplots(figsize=(6.8, 3.8))
    x = list(range(len(labels)))
    w = 0.35
    b1 = ax.bar([i - w / 2 for i in x], xu_ms, width=w, label="Xu & Parnas", color="#2b6cb0")
    b2 = ax.bar([i + w / 2 for i in x], z3_ms, width=w, label="SMT/Z3", color="#dd6b20")
    ax.set_yscale("log")
    ax.set_ylabel("Tempo mediano de planejamento (ms, escala log)", fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_title("Tempo de Planejamento: Xu & Parnas vs. SMT/Z3 (Instâncias de Referência)", fontsize=9.5, fontweight="bold")
    ax.grid(axis="y", which="both", linestyle=":", alpha=0.45)
    ax.legend(fontsize=8.5)
    for bars in (b1, b2):
        for bar in bars:
            h = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                h * 1.15,
                f"{h:.2f} ms",
                ha="center",
                va="bottom",
                fontsize=7.8,
                fontweight="bold",
            )
    ax.set_ylim(0.1, max(z3_ms) * 3.0)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig2_desempenho_referencia.png", dpi=300, bbox_inches="tight")
    fig.savefig(FIG_DIR / "fig2_desempenho_referencia.pdf", bbox_inches="tight")
    plt.close(fig)

    return {"results": results}


def run_exp3_escalabilidade_unidades() -> dict[str, Any]:
    """Experiment 3: Scaling discrete execution units (C_i * k) with fixed segment graph."""
    base = load_instance(ROOT / "instances" / "temperature_case.json")
    factors = [1, 2, 3, 4, 6, 8]
    rows_data = []
    for k in factors:
        scaled = _scale_instance(base, k)
        bench = _alternating_benchmark(scaled, objective="feasibility", repetitions=5, warmup=1, timeout_ms=20_000)
        xu = bench["summary"]["xu-parnas"]
        z3 = bench["summary"]["smt-z3"]
        rows_data.append(
            {
                "fator": k,
                "segmentos": len(scaled.segments),
                "total_units": scaled.total_units(),
                "xu_status": xu["statuses"][0],
                "z3_status": z3["statuses"][0],
                "xu_median_ns": xu["total_median_ns"],
                "z3_build_median_ns": z3["build_median_ns"],
                "z3_search_median_ns": z3["search_median_ns"],
                "z3_median_ns": z3["total_median_ns"],
                "ratio_z3_xu": z3["total_median_ns"] / max(1, xu["total_median_ns"]),
            }
        )

    _write_json(RAW_DIR / "escalabilidade_unidades.json", {"rows": rows_data})

    headers = [
        "Fator",
        "Unidades",
        "Xu_status",
        "Xu_mediana_ms",
        "Z3_status",
        "Z3_build_ms",
        "Z3_search_ms",
        "Z3_mediana_ms",
        "Razao_Z3_Xu",
    ]
    csv_rows = [
        [
            f"{r['fator']}x",
            r["total_units"],
            r["xu_status"],
            _fmt_ms(r["xu_median_ns"]),
            r["z3_status"],
            _fmt_ms(r["z3_build_median_ns"]),
            _fmt_ms(r["z3_search_median_ns"]),
            _fmt_ms(r["z3_median_ns"]),
            f"{r['ratio_z3_xu']:.1f}x",
        ]
        for r in rows_data
    ]
    _write_csv(TAB_DIR / "tabela3_escalabilidade_unidades.csv", headers, csv_rows)

    tex_rows = [
        f"{r['fator']}$\\times$ & {r['total_units']} & {_fmt_ms(r['xu_median_ns'], 2)} & "
        f"{_fmt_ms(r['z3_build_median_ns'], 2)} & {_fmt_ms(r['z3_search_median_ns'], 2)} & "
        f"{_fmt_ms(r['z3_median_ns'], 2)} & {r['ratio_z3_xu']:.1f}$\\times$ \\\\"
        for r in rows_data
    ]
    tex = "\n".join(
        [
            r"\begin{table}[t]",
            r"\centering",
            r"\caption{Escalabilidade em fun\c{c}\~ao da quantidade total de unidades discretas (inst\^ancia de temperatura escalada por $k$).}",
            r"\label{tab:escalabilidade_unidades}",
            r"\scriptsize",
            r"\begin{tabular}{ccccccc}",
            r"\hline",
            r"\textbf{$k$} & \textbf{Unid.} & \textbf{Xu (ms)} & \textbf{Z3 build} & \textbf{Z3 check} & \textbf{Z3 tot. (ms)} & \textbf{Z3/Xu} \\",
            r"\hline",
            *tex_rows,
            r"\hline",
            r"\end{tabular}",
            r"\end{table}",
        ]
    )
    _write_tex(TAB_DIR / "tabela3_escalabilidade_unidades.tex", tex)

    # Figure 3: Scalability vs Total Units
    units = [r["total_units"] for r in rows_data]
    xu_ms = [r["xu_median_ns"] / 1e6 for r in rows_data]
    z3_ms = [r["z3_median_ns"] / 1e6 for r in rows_data]

    fig, ax = plt.subplots(figsize=(6.8, 3.8))
    ax.plot(units, xu_ms, marker="o", linewidth=2.0, color="#2b6cb0", label="Xu & Parnas (nível de segmento)")
    ax.plot(units, z3_ms, marker="s", linewidth=2.0, color="#dd6b20", label="SMT/Z3 (formulação unitária)")
    ax.set_yscale("log")
    ax.set_xlabel("Total de unidades discretas de execução (U)", fontsize=9)
    ax.set_ylabel("Tempo mediano de planejamento (ms, escala log)", fontsize=9)
    ax.set_title("Impacto da Granularidade Discreta (U) mantendo 9 Segmentos Fixos", fontsize=9.5, fontweight="bold")
    ax.grid(True, which="both", linestyle=":", alpha=0.45)
    ax.legend(fontsize=8.5)
    for u, y_x, y_z in zip(units, xu_ms, z3_ms):
        ax.annotate(f"{y_x:.2f}", (u, y_x), textcoords="offset points", xytext=(0, -13), ha="center", fontsize=7.5, color="#2b6cb0")
        ax.annotate(f"{y_z:.1f}", (u, y_z), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=7.5, color="#dd6b20")
    ax.set_ylim(min(xu_ms) * 0.45, max(z3_ms) * 2.2)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig3_escalabilidade_unidades.png", dpi=300, bbox_inches="tight")
    fig.savefig(FIG_DIR / "fig3_escalabilidade_unidades.pdf", bbox_inches="tight")
    plt.close(fig)

    return {"rows": rows_data}


def run_exp4_escalabilidade_segmentos() -> dict[str, Any]:
    """Experiment 4: Varying number of segments N with dense exclusions (feasible & infeasible)."""
    rng = random.Random(202604)
    n_list = [4, 6, 8, 10, 12]
    per_n = 6
    timeout_ms = 5_000

    summary_rows = []
    all_details = []

    for n_segs in n_list:
        xu_times_ms = []
        z3_times_ms = []
        xu_nodes = []
        feas_cnt = 0
        infeas_cnt = 0
        agree_cnt = 0
        xu_timeouts = 0
        z3_timeouts = 0

        for idx in range(per_n):
            names = [f"T{i}" for i in range(n_segs)]
            # Phase-transition regime (~85-110% load) producing both feasible and infeasible
            # instances that genuinely exercise G1/G2 branching and exclusion conflicts.
            segs = []
            for i, nm in enumerate(names):
                r = rng.randint(0, max(2, int(1.4 * n_segs)))
                c = rng.randint(1, 3)
                if idx % 2 == 0:
                    slack = rng.randint(max(2, n_segs), max(4, int(2.2 * n_segs)))
                else:
                    slack = rng.randint(max(1, n_segs // 2), max(3, int(1.3 * n_segs)))
                d = r + c + slack
                segs.append({"id": nm, "release": r, "execution_units": c, "deadline": d})
            prec, excl = [], []
            for i in range(n_segs):
                for j in range(n_segs):
                    if i == j:
                        continue
                    if i < j and rng.random() < 0.12:
                        prec.append([names[i], names[j]])
                    if rng.random() < 0.45:
                        excl.append([names[i], names[j]])

            inst = parse_instance(
                {
                    "schema_version": 1,
                    "instance_id": f"seg_{n_segs}_case_{idx}",
                    "objective": "feasibility",
                    "processes": [{"id": f"P{i}", "segments": [nm]} for i, nm in enumerate(names)],
                    "segments": segs,
                    "precedence": prec,
                    "exclusion": excl,
                }
            )
            xu = plan_xu_parnas(inst, PlanningLimits(timeout_ms=timeout_ms))
            z3 = plan_smt_z3(inst, PlanningLimits(timeout_ms=timeout_ms))

            if xu.status == "timeout":
                xu_timeouts += 1
            if z3.status == "timeout":
                z3_timeouts += 1
            if xu.status in {"feasible", "infeasible"} and z3.status in {"feasible", "infeasible"}:
                if xu.status == z3.status:
                    agree_cnt += 1
                if xu.status == "feasible":
                    feas_cnt += 1
                else:
                    infeas_cnt += 1
            xu_times_ms.append((xu.total_planning_ns or 0) / 1e6)
            z3_times_ms.append((z3.total_planning_ns or 0) / 1e6)
            xu_nodes.append(xu.nodes_expanded or 0)

            all_details.append(
                {
                    "n_segments": n_segs,
                    "total_units": inst.total_units(),
                    "exclusions": len(inst.exclusion),
                    "instance_id": inst.instance_id,
                    "xu_status": xu.status,
                    "z3_status": z3.status,
                    "xu_ms": (xu.total_planning_ns or 0) / 1e6,
                    "z3_ms": (z3.total_planning_ns or 0) / 1e6,
                    "xu_nodes_expanded": xu.nodes_expanded,
                }
            )

        summary_rows.append(
            {
                "n_segments": n_segs,
                "instances": per_n,
                "feasible": feas_cnt,
                "infeasible": infeas_cnt,
                "agreement": agree_cnt,
                "xu_timeouts": xu_timeouts,
                "z3_timeouts": z3_timeouts,
                "xu_median_ms": statistics.median(xu_times_ms),
                "xu_max_ms": max(xu_times_ms),
                "xu_max_nodes_expanded": max(xu_nodes),
                "z3_median_ms": statistics.median(z3_times_ms),
                "z3_max_ms": max(z3_times_ms),
            }
        )

    payload = {"summary": summary_rows, "details": all_details}
    _write_json(RAW_DIR / "escalabilidade_segmentos_conflitos.json", payload)

    headers = [
        "Segmentos",
        "Instancias",
        "Viaveis_Inviaveis",
        "Concordancia",
        "Xu_mediana_ms",
        "Xu_max_ms",
        "Xu_max_nos_exp",
        "Z3_mediana_ms",
        "Z3_max_ms",
        "Timeouts_Xu_Z3",
    ]
    csv_rows = [
        [
            r["n_segments"],
            r["instances"],
            f"{r['feasible']}V/{r['infeasible']}I",
            f"{r['agreement']}/{r['instances']}",
            f"{r['xu_median_ms']:.3f}",
            f"{r['xu_max_ms']:.3f}",
            r["xu_max_nodes_expanded"],
            f"{r['z3_median_ms']:.3f}",
            f"{r['z3_max_ms']:.3f}",
            f"{r['xu_timeouts']}/{r['z3_timeouts']}",
        ]
        for r in summary_rows
    ]
    _write_csv(TAB_DIR / "tabela4_escalabilidade_segmentos.csv", headers, csv_rows)

    tex_rows = [
        f"{r['n_segments']} & {r['feasible']}V/{r['infeasible']}I & {r['agreement']}/{r['instances']} & "
        f"{r['xu_median_ms']:.2f} ({r['xu_max_ms']:.2f}) & {r['xu_max_nodes_expanded']} & "
        f"{r['z3_median_ms']:.2f} ({r['z3_max_ms']:.2f}) & {r['xu_timeouts']}/{r['z3_timeouts']} \\\\"
        for r in summary_rows
    ]
    tex = "\n".join(
        [
            r"\begin{table}[t]",
            r"\centering",
            r"\caption{Desempenho com aumento do n\'umero de segmentos ($N$) e alta densidade de exclus\~oes ($\approx 45\%$, 6 inst\^ancias por $N$, limite 5\,s).}",
            r"\label{tab:escalabilidade_segmentos}",
            r"\scriptsize",
            r"\begin{tabular}{ccccccc}",
            r"\hline",
            r"\textbf{$N$} & \textbf{V/I} & \textbf{Conc.} & \textbf{Xu med. (max) ms} & \textbf{Max n\'os} & \textbf{Z3 med. (max) ms} & \textbf{TO (Xu/Z3)} \\",
            r"\hline",
            *tex_rows,
            r"\hline",
            r"\end{tabular}",
            r"\end{table}",
        ]
    )
    _write_tex(TAB_DIR / "tabela4_escalabilidade_segmentos.tex", tex)

    # Figure 4: Median & max time vs N segments
    ns = [r["n_segments"] for r in summary_rows]
    xu_med = [r["xu_median_ms"] for r in summary_rows]
    z3_med = [r["z3_median_ms"] for r in summary_rows]
    xu_mx = [r["xu_max_ms"] for r in summary_rows]
    z3_mx = [r["z3_max_ms"] for r in summary_rows]

    fig, ax = plt.subplots(figsize=(6.8, 3.8))
    ax.plot(ns, xu_med, marker="o", linewidth=2.0, color="#2b6cb0", label="Xu & Parnas (mediana)")
    ax.plot(ns, xu_mx, marker="o", linestyle="--", linewidth=1.2, alpha=0.65, color="#2b6cb0", label="Xu & Parnas (máximo)")
    ax.plot(ns, z3_med, marker="s", linewidth=2.0, color="#dd6b20", label="SMT/Z3 (mediana)")
    ax.plot(ns, z3_mx, marker="s", linestyle="--", linewidth=1.2, alpha=0.65, color="#dd6b20", label="SMT/Z3 (máximo)")
    ax.set_yscale("log")
    ax.set_xlabel("Número de segmentos (N) com ~45% de pares em EXCLUDES", fontsize=9)
    ax.set_ylabel("Tempo de planejamento (ms, escala log)", fontsize=9)
    ax.set_title("Escalabilidade sob Alta Densidade de Conflitos de Exclusão", fontsize=9.5, fontweight="bold")
    ax.set_xticks(ns)
    ax.grid(True, which="both", linestyle=":", alpha=0.45)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig4_escalabilidade_segmentos.png", dpi=300, bbox_inches="tight")
    fig.savefig(FIG_DIR / "fig4_escalabilidade_segmentos.pdf", bbox_inches="tight")
    plt.close(fig)

    return payload


def run_exp5_viabilidade_vs_otimizacao() -> dict[str, Any]:
    """Experiment 5: Comparing feasibility mode vs min_lmax optimization mode."""
    infeas_tight = parse_instance(
        {
            "schema_version": 1,
            "instance_id": "inviavel_exclusao_apertada",
            "objective": "feasibility",
            "processes": [
                {"id": "PA", "segments": ["A"]},
                {"id": "PB", "segments": ["B"]},
                {"id": "PC", "segments": ["C"]},
            ],
            "segments": [
                {"id": "A", "release": 0, "execution_units": 4, "deadline": 6},
                {"id": "B", "release": 1, "execution_units": 3, "deadline": 5},
                {"id": "C", "release": 2, "execution_units": 3, "deadline": 7},
            ],
            "precedence": [],
            "exclusion": [["A", "B"], ["B", "A"], ["B", "C"], ["C", "B"]],
        }
    )
    insts = [
        load_instance(ROOT / "instances" / "temperature_case.json"),
        load_instance(ROOT / "instances" / "xu_example_1.json"),
        load_instance(ROOT / "instances" / "xu_example_2.json"),
        infeas_tight,
    ]

    rows = []
    for inst in insts:
        b_feas = _alternating_benchmark(inst, objective="feasibility", repetitions=5, warmup=1, timeout_ms=20_000)
        b_opt = _alternating_benchmark(inst, objective="min_lmax", repetitions=5, warmup=1, timeout_ms=20_000)
        rows.append(
            {
                "instance_id": inst.instance_id,
                "units": inst.total_units(),
                "xu_feas_ms": b_feas["summary"]["xu-parnas"]["total_median_ns"] / 1e6,
                "xu_opt_ms": b_opt["summary"]["xu-parnas"]["total_median_ns"] / 1e6,
                "xu_opt_lmax": b_opt["summary"]["xu-parnas"]["logical_lmax"],
                "z3_feas_ms": b_feas["summary"]["smt-z3"]["total_median_ns"] / 1e6,
                "z3_opt_ms": b_opt["summary"]["smt-z3"]["total_median_ns"] / 1e6,
                "z3_opt_lmax": b_opt["summary"]["smt-z3"]["logical_lmax"],
                "z3_opt_status": b_opt["summary"]["smt-z3"]["statuses"][0],
                "xu_opt_status": b_opt["summary"]["xu-parnas"]["statuses"][0],
            }
        )

    _write_json(RAW_DIR / "viabilidade_vs_otimizacao.json", {"rows": rows})

    headers = [
        "Instancia",
        "Unid.",
        "Xu_viab_ms",
        "Xu_minLmax_ms",
        "Z3_viab_ms",
        "Z3_minLmax_ms",
        "Lmax_otimo_Xu",
        "Lmax_otimo_Z3",
    ]
    csv_rows = [
        [
            r["instance_id"],
            r["units"],
            f"{r['xu_feas_ms']:.3f}",
            f"{r['xu_opt_ms']:.3f}",
            f"{r['z3_feas_ms']:.3f}",
            f"{r['z3_opt_ms']:.3f}",
            r["xu_opt_lmax"],
            r["z3_opt_lmax"],
        ]
        for r in rows
    ]
    _write_csv(TAB_DIR / "tabela5_viabilidade_vs_otimizacao.csv", headers, csv_rows)

    tex_rows = []
    for r in rows:
        lbl = r["instance_id"].replace("_", r"\_")
        tex_rows.append(
            f"{lbl} & {r['units']} & "
            f"{r['xu_feas_ms']:.2f} & {r['xu_opt_ms']:.2f} & "
            f"{r['z3_feas_ms']:.2f} & {r['z3_opt_ms']:.2f} & "
            f"{r['xu_opt_lmax']} / {r['z3_opt_lmax']} \\\\"
        )
    tex = "\n".join(
        [
            r"\begin{table}[t]",
            r"\centering",
            r"\caption{Custo de decis\~ao de viabilidade (\texttt{feasibility}) versus minimiza\c{c}\~ao de $L_{\max}$ (\texttt{min\_lmax}, mediana de 5 repeti\c{c}\~oes).}",
            r"\label{tab:viab_vs_opt}",
            r"\scriptsize",
            r"\begin{tabular}{lcccccc}",
            r"\hline",
            r"\textbf{Inst\^ancia} & \textbf{U} & \textbf{Xu viab.} & \textbf{Xu \'otimo} & \textbf{Z3 viab.} & \textbf{Z3 \'otimo} & \textbf{$L_{\max}^*$ (Xu/Z3)} \\",
            r"\hline",
            *tex_rows,
            r"\hline",
            r"\end{tabular}",
            r"\end{table}",
        ]
    )
    _write_tex(TAB_DIR / "tabela5_viabilidade_vs_otimizacao.tex", tex)
    return {"rows": rows}


def run_exp6_execucao_real_e_diagnostico() -> dict[str, Any]:
    """Experiment 6: Physical quantum calibration, real execution (logical & timed), and failure diagnostics."""
    inst = load_instance(ROOT / "instances" / "temperature_case.json")
    app_cfg = load_application_config(ROOT / "data" / "application_config.json")
    csv_path = ROOT / "data" / "temperatures.csv"
    seq_ref = run_sequential_reference(app_cfg, csv_path)

    xu_plan = plan_xu_parnas(inst, PlanningLimits(timeout_ms=15_000))
    z3_plan = plan_smt_z3(inst, PlanningLimits(timeout_ms=15_000))
    assert xu_plan.schedule is not None and z3_plan.schedule is not None

    cal = calibrate_quantum(inst, csv_path, app_cfg, repetitions=30, warmup_runs=5)
    _write_json(RAW_DIR / "calibracao.json", cal.to_dict())

    with tempfile.TemporaryDirectory(prefix="str_art_exec_") as td:
        troot = Path(td)
        # Logical runs
        xu_log = execute_schedule(
            inst, xu_plan.schedule, build_tasks(app_cfg, csv_path, troot / "xu_log_p3.json"), TimingConfig(mode="logical")
        )
        z3_log = execute_schedule(
            inst, z3_plan.schedule, build_tasks(app_cfg, csv_path, troot / "z3_log_p3.json"), TimingConfig(mode="logical")
        )
        # Timed runs under identical calibrated quantum
        xu_tim = execute_schedule(
            inst,
            xu_plan.schedule,
            build_tasks(app_cfg, csv_path, troot / "xu_tim_p3.json"),
            TimingConfig(mode="timed", quantum_ns=cal.quantum_ns),
        )
        z3_tim = execute_schedule(
            inst,
            z3_plan.schedule,
            build_tasks(app_cfg, csv_path, troot / "z3_tim_p3.json"),
            TimingConfig(mode="timed", quantum_ns=cal.quantum_ns),
        )

        # Deliberate failure diagnostic 1: slow A2 task -> runtime_budget_violation
        slow_tasks = build_tasks(app_cfg, csv_path, troot / "slow_p3.json")
        orig_a2_exec = slow_tasks.tasks["A2"]._execute_unit

        def _slow_a2(u_idx: int):
            time.sleep(0.012)
            return orig_a2_exec(u_idx)

        slow_tasks.tasks["A2"]._execute_unit = _slow_a2  # type: ignore[method-assign]
        diag_slow = execute_schedule(
            inst,
            xu_plan.schedule,
            slow_tasks,
            TimingConfig(mode="timed", quantum_ns=cal.quantum_ns),
        )

        # Deliberate failure diagnostic 2: invalid A7/S interleaved schedule
        bad_sched = known_invalid_interleaved_schedule()
        diag_val_reject = execute_schedule(
            inst, bad_sched, build_tasks(app_cfg, csv_path, troot / "bad1.json"), TimingConfig(mode="logical")
        )
        diag_torn = execute_schedule(
            inst,
            bad_sched,
            build_tasks(app_cfg, csv_path, troot / "bad2.json"),
            TimingConfig(mode="logical", allow_invalid_schedule=True),
        )

    _write_json(RAW_DIR / "execucao_xu_logica.json", xu_log.to_dict())
    _write_json(RAW_DIR / "execucao_z3_logica.json", z3_log.to_dict())
    _write_json(RAW_DIR / "execucao_xu_temporizada.json", xu_tim.to_dict())
    _write_json(RAW_DIR / "execucao_z3_temporizada.json", z3_tim.to_dict())

    diag_payload = {
        "sequential_reference_indicators": seq_ref["indicators"],
        "slow_a2_test": {
            "status": diag_slow.status,
            "failed_unit": diag_slow.failed_unit,
            "slot_overrun_ns": diag_slow.max_slot_overrun_ns,
            "error_message": diag_slow.error_message,
        },
        "interleaved_a7_s_validator_reject": {
            "status": diag_val_reject.status,
            "units_executed": diag_val_reject.units_executed,
            "validation_errors": diag_val_reject.validation_errors,
        },
        "interleaved_a7_s_deliberate_run": {
            "status": diag_torn.status,
            "failed_unit": diag_torn.failed_unit,
            "error_message": diag_torn.error_message,
        },
    }
    _write_json(RAW_DIR / "diagnostico_falhas.json", diag_payload)

    # Verify numerical equality with sequential reference
    max_abs_diff_xu = max(
        abs(xu_tim.final_shared_state["indicators"][k] - seq_ref["indicators"][k])
        for k in ("count", "min", "max", "mean", "variance")
    )
    max_abs_diff_z3 = max(
        abs(z3_tim.final_shared_state["indicators"][k] - seq_ref["indicators"][k])
        for k in ("count", "min", "max", "mean", "variance")
    )

    headers = [
        "Metrica",
        "Xu_Parnas_Temporizado",
        "SMT_Z3_Temporizado",
    ]
    csv_rows = [
        ["Status da execucao", xu_tim.status, z3_tim.status],
        ["Quantum fisico calibrado q (ms)", _fmt_ms(cal.quantum_ns), _fmt_ms(cal.quantum_ns)],
        ["Unidades executadas", f"{xu_tim.units_executed}/19", f"{z3_tim.units_executed}/19"],
        ["Tempo total wall (ms)", _fmt_ms(xu_tim.total_wall_ns), _fmt_ms(z3_tim.total_wall_ns)],
        ["Tempo total CPU (ms)", _fmt_ms(xu_tim.total_cpu_ns), _fmt_ms(z3_tim.total_cpu_ns)],
        ["Maior duracao de unidade (ms)", _fmt_ms(xu_tim.max_work_elapsed_ns), _fmt_ms(z3_tim.max_work_elapsed_ns)],
        ["Maior atraso de despacho (ms)", _fmt_ms(xu_tim.max_dispatch_lateness_ns), _fmt_ms(z3_tim.max_dispatch_lateness_ns)],
        ["Maior excesso de slot (ms)", _fmt_ms(xu_tim.max_slot_overrun_ns), _fmt_ms(z3_tim.max_slot_overrun_ns)],
        [
            "Todos deadlines fisicos atendidos",
            "Sim" if all(s.physical_deadline_met for s in xu_tim.segment_timings) else "Nao",
            "Sim" if all(s.physical_deadline_met for s in z3_tim.segment_timings) else "Nao",
        ],
        ["Erro numerico max vs referencia seq.", f"{max_abs_diff_xu:.2e}", f"{max_abs_diff_z3:.2e}"],
        ["Versao final estado compartilhado (A7)", xu_tim.final_shared_state["version"], z3_tim.final_shared_state["version"]],
        ["Versao registrada por P3 (A8)", xu_tim.recorded_copy["version"], z3_tim.recorded_copy["version"]],
    ]
    _write_csv(TAB_DIR / "tabela6_execucao_real_e_calibracao.csv", headers, csv_rows)

    tex_rows = []
    for r in csv_rows:
        metric_lbl = str(r[0]).replace("_", r"\_")
        tex_rows.append(f"{metric_lbl} & {r[1]} & {r[2]} \\\\")
    tex = "\n".join(
        [
            r"\begin{table}[t]",
            r"\centering",
            r"\caption{Execu\c{c}\~ao real temporizada das escalas de Xu \& Parnas e SMT/Z3 sobre a aplica\c{c}\~ao de temperatura (calibrado em 30 repeti\c{c}\~oes).}",
            r"\label{tab:execucao_real}",
            r"\scriptsize",
            r"\begin{tabular}{lcc}",
            r"\hline",
            r"\textbf{M\'etrica} & \textbf{Xu \& Parnas} & \textbf{SMT/Z3} \\",
            r"\hline",
            *tex_rows,
            r"\hline",
            r"\end{tabular}",
            r"\end{table}",
        ]
    )
    _write_tex(TAB_DIR / "tabela6_execucao_real_e_calibracao.tex", tex)

    # Figure 5: Per-unit observed work time vs calibrated quantum q
    xu_ticks = [f"{t.segment_id}.{t.unit_index}\n(t={t.start_tick})" for t in xu_tim.traces]
    xu_work = [t.work_elapsed_ns / 1e6 for t in xu_tim.traces]
    z3_ticks = [f"{t.segment_id}.{t.unit_index}\n(t={t.start_tick})" for t in z3_tim.traces]
    z3_work = [t.work_elapsed_ns / 1e6 for t in z3_tim.traces]
    q_ms = cal.quantum_ns / 1e6

    fig, axes = plt.subplots(2, 1, figsize=(8.8, 4.8), sharey=True)
    for ax, ticks, work, title, color in [
        (axes[0], xu_ticks, xu_work, "Xu & Parnas — Duração real por unidade vs. quantum calibrado q", "#2b6cb0"),
        (axes[1], z3_ticks, z3_work, "SMT/Z3 — Duração real por unidade vs. quantum calibrado q", "#dd6b20"),
    ]:
        pos = list(range(len(ticks)))
        ax.bar(pos, work, color=color, alpha=0.88, width=0.65)
        ax.axhline(q_ms, color="#c53030", linestyle="--", linewidth=1.3, label=f"Quantum calibrado q = {q_ms:.2f} ms")
        ax.set_xticks(pos)
        ax.set_xticklabels(ticks, fontsize=6.8)
        ax.set_ylabel("Tempo (ms)", fontsize=8.5)
        ax.set_title(title, fontsize=9.2, fontweight="bold")
        ax.grid(axis="y", linestyle=":", alpha=0.45)
        ax.legend(loc="upper right", fontsize=8)
    axes[0].set_ylim(0, q_ms * 1.18)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig5_execucao_temporizada.png", dpi=300, bbox_inches="tight")
    fig.savefig(FIG_DIR / "fig5_execucao_temporizada.pdf", bbox_inches="tight")
    plt.close(fig)

    return {
        "calibration": cal.to_dict(),
        "xu_timed_summary": {
            "status": xu_tim.status,
            "total_wall_ns": xu_tim.total_wall_ns,
            "max_work_elapsed_ns": xu_tim.max_work_elapsed_ns,
            "max_dispatch_lateness_ns": xu_tim.max_dispatch_lateness_ns,
            "max_slot_overrun_ns": xu_tim.max_slot_overrun_ns,
            "recorded_version": xu_tim.recorded_copy["version"],
        },
        "z3_timed_summary": {
            "status": z3_tim.status,
            "total_wall_ns": z3_tim.total_wall_ns,
            "max_work_elapsed_ns": z3_tim.max_work_elapsed_ns,
            "max_dispatch_lateness_ns": z3_tim.max_dispatch_lateness_ns,
            "max_slot_overrun_ns": z3_tim.max_slot_overrun_ns,
            "recorded_version": z3_tim.recorded_copy["version"],
        },
        "diagnostics": diag_payload,
    }


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    print("[1/6] Executando validação cruzada...")
    e1 = run_exp1_validacao_cruzada()
    print("[2/6] Executando benchmark de referência e Gantt...")
    e2 = run_exp2_referencia_e_gantt()
    print("[3/6] Executando escalabilidade por unidades discretas...")
    e3 = run_exp3_escalabilidade_unidades()
    print("[4/6] Executando escalabilidade por segmentos e conflitos...")
    e4 = run_exp4_escalabilidade_segmentos()
    print("[5/6] Executando comparação feasibility vs min_lmax...")
    e5 = run_exp5_viabilidade_vs_otimizacao()
    print("[6/6] Executando calibração, execução real e diagnóstico de falhas...")
    e6 = run_exp6_execucao_real_e_diagnostico()
    print("Concluído! Todos os dados, tabelas (.csv/.tex) e figuras (.png/.pdf) salvos em:", OUT_ROOT)


if __name__ == "__main__":
    main()
