"""Metrics aggregation, CSV/JSON export, charts, and scientific reporting for sporadic experiments."""

from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = (len(sorted_vals) - 1) * (p / 100.0)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return sorted_vals[lo]
    frac = idx - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _time_stats_ms(ns_values: list[int]) -> dict[str, float]:
    ms = sorted(v / 1_000_000.0 for v in ns_values)
    if not ms:
        return {
            "count": 0,
            "min_ms": 0.0,
            "median_ms": 0.0,
            "mean_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "max_ms": 0.0,
            "iqr_ms": 0.0,
        }
    q25 = _percentile(ms, 25.0)
    q75 = _percentile(ms, 75.0)
    return {
        "count": len(ms),
        "min_ms": ms[0],
        "median_ms": _percentile(ms, 50.0),
        "mean_ms": statistics.mean(ms),
        "p95_ms": _percentile(ms, 95.0),
        "p99_ms": _percentile(ms, 99.0),
        "max_ms": ms[-1],
        "iqr_ms": q75 - q25,
    }


def _aggregate_method_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = [r["status"] for r in records]
    sat_cnt = statuses.count("SAT")
    unsat_cnt = statuses.count("UNSAT")
    timeout_cnt = statuses.count("TIMEOUT")
    unknown_cnt = statuses.count("UNKNOWN")
    err_cnt = sum(1 for s in statuses if s not in {"SAT", "UNSAT", "TIMEOUT", "UNKNOWN"})

    sat_recs = [r for r in records if r["status"] == "SAT"]
    val_passed = sum(1 for r in sat_recs if r.get("validation_passed") is True)
    val_failed = sum(1 for r in sat_recs if r.get("validation_passed") is not True)

    wall_stats = _time_stats_ms([int(r["planning_wall_time_ns"]) for r in records])
    prep_stats = _time_stats_ms([int(r["prep_time_ns"]) for r in records])

    nodes_exp = [int(r["nodes_expanded"]) for r in records if r.get("nodes_expanded") is not None]
    return {
        "total_runs": len(records),
        "sat": sat_cnt,
        "unsat": unsat_cnt,
        "timeout": timeout_cnt,
        "unknown": unknown_cnt,
        "errors": err_cnt,
        "sat_validation_passed": val_passed,
        "sat_validation_failed": val_failed,
        "wall_time": wall_stats,
        "prep_time": prep_stats,
        "max_nodes_expanded": max(nodes_exp) if nodes_exp else None,
        "median_nodes_expanded": statistics.median(nodes_exp) if nodes_exp else None,
    }


def export_matrix_results(
    matrix_output: dict[str, Any],
    out_dir: str | Path,
    *,
    generate_plots: bool = True,
) -> dict[str, Any]:
    """Export per-run CSV, grouped summary CSV/JSON, plots, and Markdown report."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = matrix_output["records"]
    pairs: list[dict[str, Any]] = matrix_output["pairs"]

    # 1. Per-run detailed CSV
    csv_cols = [
        "scenario_id",
        "seed",
        "generation_mode",
        "horizon",
        "horizon_policy",
        "utilization_band",
        "jitter_label",
        "num_tasks",
        "num_jobs",
        "num_discarded_jobs",
        "num_segments",
        "total_units",
        "num_precedences",
        "num_exclusions",
        "nominal_utilization",
        "effective_utilization",
        "input_hash",
        "instance_hash",
        "method",
        "execution_order_index",
        "status",
        "logical_lmax",
        "lower_bound",
        "prep_time_ns",
        "model_build_time_ns",
        "solver_time_ns",
        "planning_wall_time_ns",
        "nodes_generated",
        "nodes_expanded",
        "validation_passed",
        "timeout",
        "failure_reason",
        "code_revision",
    ]
    metrics_csv = out / "metrics.csv"
    with metrics_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(csv_cols)
        for rec in records:
            writer.writerow([rec.get(c) for c in csv_cols])

    # 2. Overall summary + grouped summary by (num_tasks, horizon, generation_mode, utilization_band)
    xu_all = [r for r in records if r["method"] == "xu-parnas"]
    z3_all = [r for r in records if r["method"] == "smt-z3"]

    decided_pairs = [p for p in pairs if p["agreement"] is not None]
    agreed_pairs = [p for p in decided_pairs if p["agreement"] is True]
    divergences = [p for p in pairs if p["divergence_detected"]]

    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for rec in records:
        key = (
            rec["num_tasks"],
            rec["horizon"],
            rec["utilization_band"],
            rec["generation_mode"],
            rec["jitter_label"],
        )
        grouped.setdefault(key, []).append(rec)

    group_rows: list[dict[str, Any]] = []
    for key in sorted(grouped.keys()):
        n_tasks, horizon, util_band, mode, j_label = key
        grp = grouped[key]
        g_xu = [r for r in grp if r["method"] == "xu-parnas"]
        g_z3 = [r for r in grp if r["method"] == "smt-z3"]
        agg_xu = _aggregate_method_records(g_xu)
        agg_z3 = _aggregate_method_records(g_z3)
        group_rows.append(
            {
                "num_tasks": n_tasks,
                "horizon": horizon,
                "utilization_band": util_band,
                "generation_mode": mode,
                "jitter_label": j_label,
                "scenarios": len(g_xu),
                "mean_jobs": statistics.mean(r["num_jobs"] for r in g_xu),
                "mean_discarded_jobs": statistics.mean(r["num_discarded_jobs"] for r in g_xu),
                "mean_units": statistics.mean(r["total_units"] for r in g_xu),
                "mean_nominal_u": statistics.mean(r["nominal_utilization"] for r in g_xu),
                "mean_effective_u": statistics.mean(r["effective_utilization"] for r in g_xu),
                "xu_sat": agg_xu["sat"],
                "xu_unsat": agg_xu["unsat"],
                "xu_timeout": agg_xu["timeout"],
                "xu_median_ms": agg_xu["wall_time"]["median_ms"],
                "xu_p95_ms": agg_xu["wall_time"]["p95_ms"],
                "xu_max_nodes_exp": agg_xu["max_nodes_expanded"],
                "z3_sat": agg_z3["sat"],
                "z3_unsat": agg_z3["unsat"],
                "z3_timeout": agg_z3["timeout"],
                "z3_median_ms": agg_z3["wall_time"]["median_ms"],
                "z3_p95_ms": agg_z3["wall_time"]["p95_ms"],
            }
        )

    summary_csv = out / "summary.csv"
    if group_rows:
        s_cols = list(group_rows[0].keys())
        with summary_csv.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(s_cols)
            for row in group_rows:
                writer.writerow(
                    [
                        f"{row[c]:.3f}" if isinstance(row[c], float) else row[c]
                        for c in s_cols
                    ]
                )

    summary_payload = {
        "matrix_id": matrix_output["matrix_id"],
        "scope_note": (
            "Extensao esporadica offline em horizonte finito (0 < C_i <= D_i <= T_i). "
            "Resultados separados da etapa periodica original; nao constituem prova universal "
            "para todas as sequencias esporadicas admissiveis."
        ),
        "timeout_ms": matrix_output["timeout_ms"],
        "warmup_scenarios": matrix_output["warmup_scenarios"],
        "total_scenarios": matrix_output["total_scenarios"],
        "decided_pairs": len(decided_pairs),
        "agreed_pairs": len(agreed_pairs),
        "agreement_rate": (
            (len(agreed_pairs) / len(decided_pairs)) if decided_pairs else None
        ),
        "divergences": divergences,
        "overall": {
            "xu-parnas": _aggregate_method_records(xu_all),
            "smt-z3": _aggregate_method_records(z3_all),
        },
        "groups": group_rows,
        "code_revision": matrix_output["code_revision"],
        "environment": matrix_output["environment"],
    }
    (out / "summary.json").write_text(
        json.dumps(summary_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # 3. Optional matplotlib figures (explicitly titled as Sporadic Extension!)
    fig_paths: list[str] = []
    if generate_plots and group_rows:
        fig_paths = _generate_sporadic_plots(records, group_rows, out / "figuras")

    # 4. Markdown report
    _write_markdown_report(summary_payload, out / "RELATORIO_ESPORADICAS.md", fig_paths)
    return summary_payload


def _generate_sporadic_plots(
    records: list[dict[str, Any]],
    group_rows: list[dict[str, Any]],
    fig_dir: Path,
) -> list[str]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return []

    fig_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []

    # Plot 1: Median planning time by generation pattern and horizon
    patterns = sorted({r["generation_mode"] for r in records})
    xu_med_pat = []
    z3_med_pat = []
    for pat in patterns:
        x_vals = [
            r["planning_wall_time_ns"] / 1e6
            for r in records
            if r["method"] == "xu-parnas" and r["generation_mode"] == pat
        ]
        z_vals = [
            r["planning_wall_time_ns"] / 1e6
            for r in records
            if r["method"] == "smt-z3" and r["generation_mode"] == pat
        ]
        xu_med_pat.append(statistics.median(x_vals) if x_vals else 0.0)
        z3_med_pat.append(statistics.median(z_vals) if z_vals else 0.0)

    fig, ax = plt.subplots(figsize=(6.8, 3.8))
    x = list(range(len(patterns)))
    w = 0.35
    b1 = ax.bar([i - w / 2 for i in x], xu_med_pat, width=w, label="Xu & Parnas", color="#2b6cb0")
    b2 = ax.bar([i + w / 2 for i in x], z3_med_pat, width=w, label="SMT/Z3", color="#dd6b20")
    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(patterns, fontsize=8.5)
    ax.set_ylabel("Tempo mediano de planejamento (ms, escala log)", fontsize=9)
    ax.set_title("Extensão Esporádica: Tempo por Padrão de Ativação", fontsize=9.5, fontweight="bold")
    ax.grid(axis="y", which="both", linestyle=":", alpha=0.45)
    ax.legend(fontsize=8.5)
    for bars in (b1, b2):
        for bar in bars:
            h = bar.get_height()
            if h > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    h * 1.15,
                    f"{h:.2f}",
                    ha="center",
                    va="bottom",
                    fontsize=7.5,
                    fontweight="bold",
                )
    ax.set_ylim(0.05, max(max(xu_med_pat + z3_med_pat, default=1.0) * 3.0, 1.0))
    fig.tight_layout()
    p1_png = fig_dir / "fig_esporadica_padroes.png"
    fig.savefig(p1_png, dpi=300, bbox_inches="tight")
    fig.savefig(fig_dir / "fig_esporadica_padroes.pdf", bbox_inches="tight")
    plt.close(fig)
    saved.append(str(p1_png))

    # Plot 2: Planning time vs total execution units across sporadic scenarios
    xu_pts = [
        (r["total_units"], r["planning_wall_time_ns"] / 1e6)
        for r in records
        if r["method"] == "xu-parnas" and not r["timeout"]
    ]
    z3_pts = [
        (r["total_units"], r["planning_wall_time_ns"] / 1e6)
        for r in records
        if r["method"] == "smt-z3" and not r["timeout"]
    ]
    fig, ax = plt.subplots(figsize=(6.8, 3.8))
    if xu_pts:
        ax.scatter(
            [p[0] for p in xu_pts],
            [p[1] for p in xu_pts],
            s=22,
            alpha=0.72,
            color="#2b6cb0",
            label="Xu & Parnas (concluídos)",
        )
    if z3_pts:
        ax.scatter(
            [p[0] for p in z3_pts],
            [p[1] for p in z3_pts],
            s=22,
            alpha=0.72,
            marker="s",
            color="#dd6b20",
            label="SMT/Z3 (concluídos)",
        )
    ax.set_yscale("log")
    ax.set_xlabel("Total de unidades discretas instanciadas no cenário esporádico (U)", fontsize=9)
    ax.set_ylabel("Tempo de planejamento (ms, escala log)", fontsize=9)
    ax.set_title("Extensão Esporádica: Tempo de Planejamento vs. Unidades Instanciadas", fontsize=9.5, fontweight="bold")
    ax.grid(True, which="both", linestyle=":", alpha=0.45)
    ax.legend(fontsize=8.5)
    fig.tight_layout()
    p2_png = fig_dir / "fig_esporadica_unidades.png"
    fig.savefig(p2_png, dpi=300, bbox_inches="tight")
    fig.savefig(fig_dir / "fig_esporadica_unidades.pdf", bbox_inches="tight")
    plt.close(fig)
    saved.append(str(p2_png))

    return saved


def _write_markdown_report(
    summary: dict[str, Any],
    path: Path,
    fig_paths: list[str],
) -> None:
    xu = summary["overall"]["xu-parnas"]
    z3 = summary["overall"]["smt-z3"]
    agr = summary["agreement_rate"]
    agr_str = f"{agr * 100:.1f}%" if agr is not None else "N/A"

    lines = [
        f"# Relatório Experimental — Extensão para Tarefas Esporádicas (`{summary['matrix_id']}`)",
        "",
        "> **Nota de Escopo Científico:** estes resultados referem-se exclusivamente à **extensão para cenários finitos offline de tarefas esporádicas** (`0 < C_i <= D_i <= T_i`, horizonte fechado por deadline `d <= H`), totalmente separados dos resultados periódicos originais em `resultados_artigo/`. Uma resposta `SAT` para uma ou `N` sequências finitas **não** constitui prova universal de escalonabilidade para todas as sequências esporádicas admissíveis.",
        "",
        "## 1. Resumo Geral",
        "",
        f"- **Total de cenários esporádicos avaliados:** {summary['total_scenarios']} (após {summary['warmup_scenarios']} cenário(s) de aquecimento)",
        f"- **Limite de tempo por consulta (`timeout_ms`):** {summary['timeout_ms']} ms",
        f"- **Revisão de código (`git`):** `{summary['code_revision']}`",
        f"- **Ambiente:** Python `{summary['environment'].get('python')}`, Z3 `{summary['environment'].get('z3')}`, `{summary['environment'].get('platform')}`",
        f"- **Concordância (nos {summary['decided_pairs']} pares concluídos por ambos):** **{summary['agreed_pairs']}/{summary['decided_pairs']} ({agr_str})**",
        f"- **Divergências detectadas (SAT vs. UNSAT):** `{len(summary['divergences'])}`",
        "",
        "| Métrica | Xu & Parnas | SMT/Z3 |",
        "|---|---:|---:|",
        f"| `SAT` (viável) | {xu['sat']} | {z3['sat']} |",
        f"| `UNSAT` (inviável) | {xu['unsat']} | {z3['unsat']} |",
        f"| `TIMEOUT` (inconclusivo) | {xu['timeout']} | {z3['timeout']} |",
        f"| `UNKNOWN` | {xu['unknown']} | {z3['unknown']} |",
        f"| Escalas `SAT` aprovadas no verificador independente | {xu['sat_validation_passed']}/{xu['sat']} | {z3['sat_validation_passed']}/{z3['sat']} |",
        f"| Tempo de planejamento — Mediana (ms) | {xu['wall_time']['median_ms']:.3f} | {z3['wall_time']['median_ms']:.3f} |",
        f"| Tempo de planejamento — p95 (ms) | {xu['wall_time']['p95_ms']:.3f} | {z3['wall_time']['p95_ms']:.3f} |",
        f"| Tempo de planejamento — Máximo (ms) | {xu['wall_time']['max_ms']:.3f} | {z3['wall_time']['max_ms']:.3f} |",
        f"| Tempo de planejamento — IQR (ms) | {xu['wall_time']['iqr_ms']:.3f} | {z3['wall_time']['iqr_ms']:.3f} |",
        f"| Tempo médio de preparação (gerador + adaptador, ms) | {xu['prep_time']['median_ms']:.3f} | {z3['prep_time']['median_ms']:.3f} |",
        f"| Máximo de nós expandidos | {xu['max_nodes_expanded']} | N/A |",
        "",
        "## 2. Resultados Agrupados por Configuração",
        "",
        "| `N` | `H` | Carga | Padrão | Jitter | Jobs (med.) | Unid. (med.) | `U_nom` | `U_efet` | Xu (SAT/UNSAT/TO) | Xu med. (ms) | Z3 (SAT/UNSAT/TO) | Z3 med. (ms) |",
        "|---:|---:|---|---|---|---:|---:|---:|---:|---|---:|---|---:|",
    ]
    for g in summary["groups"]:
        lines.append(
            f"| {g['num_tasks']} | {g['horizon']} | {g['utilization_band']} | {g['generation_mode']} | {g['jitter_label']} "
            f"| {g['mean_jobs']:.1f} | {g['mean_units']:.1f} | {g['mean_nominal_u']:.2f} | {g['mean_effective_u']:.2f} "
            f"| {g['xu_sat']}/{g['xu_unsat']}/{g['xu_timeout']} | {g['xu_median_ms']:.2f} "
            f"| {g['z3_sat']}/{g['z3_unsat']}/{g['z3_timeout']} | {g['z3_median_ms']:.2f} |"
        )

    lines += [
        "",
        "## 3. Limitações Científicas Declaradas",
        "",
        "1. **Cenários finitos offline ≠ garantia universal:** `SAT` certifica apenas que a sequência concreta de liberações avaliada dentro do horizonte `H` admite escala válida; não prova escalonabilidade para todas as sequências esporádicas admissíveis.",
        "2. **Contraexemplos `UNSAT`:** uma resposta `UNSAT` para uma sequência esporádica válida demonstra que aquela sequência específica não é escalonável sob as restrições modeladas (servindo de contraexemplo caso se deseje viabilidade universal).",
        "3. **Operação online:** ambos os planejadores operam *offline* conhecendo as liberações do cenário de antemão, não sendo escalonadores *online* para chegadas imprevisíveis.",
        "4. **Escopo de deadlines restritos:** esta bateria adota `0 < C_i <= D_i <= T_i` e política de horizonte `d <= H` (com registro explícito das ativações descartadas).",
        "5. **Carga nominal vs. efetiva:** `U_nom = sum(C_i / T_i)` é apenas um indicador assintótico e não decide isoladamente a viabilidade na presença de segmentos, precedências, exclusões direcionais e horizonte finito.",
    ]
    if fig_paths:
        lines += ["", "## 4. Figuras Geradas", ""]
        for fp in fig_paths:
            lines.append(f"- `{Path(fp).name}`")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
