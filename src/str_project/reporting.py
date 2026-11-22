"""Reporting, artifact persistence, and systematic comparative analysis (Section 15)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .executor import ExecutionReport
from .model import Schedule, collect_versions
from .schedule_io import save_schedule


def _ns_to_ms(ns: int | None) -> str:
    if ns is None:
        return "N/A"
    return f"{ns / 1_000_000:.3f} ms"


def save_execution_artifacts(
    report: ExecutionReport,
    schedule: Schedule,
    out_dir: str | Path,
) -> Path:
    """Save execution report, original schedule, and Markdown summary in out_dir."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    report_path = out / "execution_report.json"
    report_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    save_schedule(schedule, out / "schedule.json")

    lines = [
        f"# Relatório de Execução ({report.mode})",
        "",
        f"- **Instância:** `{report.instance_id}` (`{report.instance_hash[:12]}...`)",
        f"- **Status:** `{report.status}`",
        f"- **Unidades executadas:** {report.units_executed}/{report.total_expected_units}",
        f"- **Quantum físico:** {_ns_to_ms(report.quantum_ns)}",
        f"- **Tempo total (wall):** {_ns_to_ms(report.total_wall_ns)}",
        f"- **Tempo total (CPU):** {_ns_to_ms(report.total_cpu_ns)}",
        f"- **Maior atraso de despacho:** {_ns_to_ms(report.max_dispatch_lateness_ns)}",
        f"- **Maior duração de unidade:** {_ns_to_ms(report.max_work_elapsed_ns)}",
        f"- **Maior excesso de slot:** {_ns_to_ms(report.max_slot_overrun_ns)}",
        f"- **Versão final do estado compartilhado:** {report.final_shared_state.get('version')}",
        f"- **Versão registrada por P3:** {report.recorded_copy.get('version') if report.recorded_copy else 'N/A'}",
    ]
    if report.error_message:
        lines.append(f"- **Diagnóstico de erro:** {report.error_message}")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def _load_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _check_recorded_copy_consistency(
    recorded: dict[str, Any] | None,
    final_state: dict[str, Any],
    tol: float = 1e-9,
) -> tuple[bool, str]:
    """Verify internal consistency of P3's recorded copy (allows version 0 or version 1)."""
    if recorded is None:
        return False, "missing_recorded_copy"
    ver = recorded.get("version")
    if ver == 0:
        ok = (
            recorded.get("block_id") is None
            and recorded.get("indicators") is None
            and recorded.get("alert") == "sem_dados"
            and recorded.get("alert_active") is False
            and recorded.get("command") == "desligado"
            and recorded.get("ventilation_on") is False
        )
        return ok, "consistent_E0_version_0" if ok else "inconsistent_E0_fields"
    if ver == 1:
        rec_ind = recorded.get("indicators") or {}
        fin_ind = final_state.get("indicators") or {}
        ind_match = all(
            k in rec_ind
            and k in fin_ind
            and math.isclose(rec_ind[k], fin_ind[k], rel_tol=tol, abs_tol=tol)
            for k in ("count", "min", "max", "mean", "variance")
        )
        ok = (
            ind_match
            and recorded.get("alert") == final_state.get("alert")
            and recorded.get("alert_active") == final_state.get("alert_active")
            and recorded.get("command") == final_state.get("command")
            and recorded.get("ventilation_on") == final_state.get("ventilation_on")
        )
        return ok, "consistent_version_1" if ok else "inconsistent_version_1_fields"
    return False, f"unexpected_version:{ver}"


def _compare_final_states(
    left_state: dict[str, Any] | None,
    right_state: dict[str, Any] | None,
    tol: float = 1e-9,
) -> tuple[bool, list[str]]:
    if left_state is None or right_state is None:
        return False, ["missing_final_shared_state"]
    diffs: list[str] = []
    for key in ("version", "alert", "alert_active", "command", "ventilation_on"):
        if left_state.get(key) != right_state.get(key):
            diffs.append(f"{key}: left={left_state.get(key)} vs right={right_state.get(key)}")
    l_ind = left_state.get("indicators") or {}
    r_ind = right_state.get("indicators") or {}
    for key in ("count", "min", "max", "mean", "variance"):
        lv = l_ind.get(key)
        rv = r_ind.get(key)
        if lv is None or rv is None or not math.isclose(lv, rv, rel_tol=tol, abs_tol=tol):
            diffs.append(f"indicators.{key}: left={lv} vs right={rv}")
    return len(diffs) == 0, diffs


def _summarize_execution_pair(
    left_exec: dict[str, Any] | None,
    right_exec: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if left_exec is None and right_exec is None:
        return None
    same_input = (
        left_exec is not None
        and right_exec is not None
        and left_exec.get("input_hash") == right_exec.get("input_hash")
    )
    same_quantum = (
        left_exec is not None
        and right_exec is not None
        and left_exec.get("quantum_ns") == right_exec.get("quantum_ns")
    )
    final_match, final_diffs = _compare_final_states(
        left_exec.get("final_shared_state") if left_exec else None,
        right_exec.get("final_shared_state") if right_exec else None,
    )
    l_copy_ok, l_copy_note = (
        _check_recorded_copy_consistency(
            left_exec.get("recorded_copy"), left_exec.get("final_shared_state", {})
        )
        if left_exec
        else (False, "missing")
    )
    r_copy_ok, r_copy_note = (
        _check_recorded_copy_consistency(
            right_exec.get("recorded_copy"), right_exec.get("final_shared_state", {})
        )
        if right_exec
        else (False, "missing")
    )

    def _extract_runtime(rep: dict[str, Any] | None) -> dict[str, Any] | None:
        if rep is None:
            return None
        seg_timings = rep.get("segment_timings", [])
        dl_flags = [s.get("physical_deadline_met") for s in seg_timings if s.get("physical_deadline_met") is not None]
        return {
            "status": rep.get("status"),
            "units_executed": rep.get("units_executed"),
            "quantum_ns": rep.get("quantum_ns"),
            "total_wall_ns": rep.get("total_wall_ns"),
            "total_cpu_ns": rep.get("total_cpu_ns"),
            "max_dispatch_lateness_ns": rep.get("max_dispatch_lateness_ns"),
            "max_work_elapsed_ns": rep.get("max_work_elapsed_ns"),
            "max_slot_overrun_ns": rep.get("max_slot_overrun_ns"),
            "all_physical_deadlines_met": all(dl_flags) if dl_flags else None,
            "recorded_version": (rep.get("recorded_copy") or {}).get("version"),
        }

    return {
        "same_input_hash": same_input,
        "same_quantum_ns": same_quantum,
        "final_shared_state_equal": final_match,
        "final_shared_state_diffs": final_diffs,
        "left_recorded_copy_consistent": l_copy_ok,
        "left_recorded_copy_note": l_copy_note,
        "right_recorded_copy_consistent": r_copy_ok,
        "right_recorded_copy_note": r_copy_note,
        "left": _extract_runtime(left_exec),
        "right": _extract_runtime(right_exec),
    }


def compare_runs(
    left_dir: str | Path,
    right_dir: str | Path,
    out_dir: str | Path,
) -> dict[str, Any]:
    """Compare planning and execution artifacts produced by two methods (e.g. Xu & Parnas vs SMT/Z3)."""
    l_root = Path(left_dir)
    r_root = Path(right_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    l_plan = _load_json_if_exists(l_root / "plan.json")
    r_plan = _load_json_if_exists(r_root / "plan.json")
    l_logical = _load_json_if_exists(l_root / "logical" / "execution_report.json")
    r_logical = _load_json_if_exists(r_root / "logical" / "execution_report.json")
    l_timed = _load_json_if_exists(l_root / "timed" / "execution_report.json")
    r_timed = _load_json_if_exists(r_root / "timed" / "execution_report.json")

    left_name = (l_plan or {}).get("planner", l_root.name)
    right_name = (r_plan or {}).get("planner", r_root.name)

    planning_section: dict[str, Any] | None = None
    if l_plan is not None or r_plan is not None:
        same_instance = (
            l_plan is not None
            and r_plan is not None
            and l_plan.get("instance_hash") == r_plan.get("instance_hash")
        )
        same_objective = (
            l_plan is not None
            and r_plan is not None
            and l_plan.get("objective") == r_plan.get("objective")
        )
        status_agreement = (
            l_plan is not None
            and r_plan is not None
            and l_plan.get("status") == r_plan.get("status")
        )
        l_val = (l_plan or {}).get("validation") or {}
        r_val = (r_plan or {}).get("validation") or {}

        planning_section = {
            "same_instance_hash": same_instance,
            "same_objective": same_objective,
            "status_agreement": status_agreement,
            "left": {
                "planner": left_name,
                "status": (l_plan or {}).get("status"),
                "objective": (l_plan or {}).get("objective"),
                "logical_lmax": (l_plan or {}).get("logical_lmax"),
                "lower_bound": (l_plan or {}).get("lower_bound"),
                "validation_ok": l_val.get("ok"),
                "preprocessing_ns": (l_plan or {}).get("preprocessing_ns"),
                "model_build_ns": (l_plan or {}).get("model_build_ns"),
                "search_ns": (l_plan or {}).get("search_ns"),
                "total_planning_ns": (l_plan or {}).get("total_planning_ns"),
                "nodes_generated": (l_plan or {}).get("nodes_generated"),
                "nodes_expanded": (l_plan or {}).get("nodes_expanded"),
                "z3_statistics": ((l_plan or {}).get("details") or {}).get("z3_statistics"),
            },
            "right": {
                "planner": right_name,
                "status": (r_plan or {}).get("status"),
                "objective": (r_plan or {}).get("objective"),
                "logical_lmax": (r_plan or {}).get("logical_lmax"),
                "lower_bound": (r_plan or {}).get("lower_bound"),
                "validation_ok": r_val.get("ok"),
                "preprocessing_ns": (r_plan or {}).get("preprocessing_ns"),
                "model_build_ns": (r_plan or {}).get("model_build_ns"),
                "search_ns": (r_plan or {}).get("search_ns"),
                "total_planning_ns": (r_plan or {}).get("total_planning_ns"),
                "nodes_generated": (r_plan or {}).get("nodes_generated"),
                "nodes_expanded": (r_plan or {}).get("nodes_expanded"),
                "z3_statistics": ((r_plan or {}).get("details") or {}).get("z3_statistics"),
            },
        }

    logical_section = _summarize_execution_pair(l_logical, r_logical)
    timed_section = _summarize_execution_pair(l_timed, r_timed)

    comparison: dict[str, Any] = {
        "left_label": left_name,
        "right_label": right_name,
        "left_dir": str(l_root),
        "right_dir": str(r_root),
        "planning": planning_section,
        "execution_logical": logical_section,
        "execution_timed": timed_section,
        "versions": collect_versions(),
    }

    (out / "comparison.json").write_text(
        json.dumps(comparison, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    md_lines = [
        f"# Relatório Comparativo: `{left_name}` vs `{right_name}`",
        "",
    ]
    if planning_section:
        lp = planning_section["left"]
        rp = planning_section["right"]
        md_lines += [
            "## 1. Planejamento Pré-Execução (Camada Lógica)",
            "",
            f"- **Mesma instância (hash):** `{planning_section['same_instance_hash']}`",
            f"- **Mesmo objetivo:** `{planning_section['same_objective']}`",
            f"- **Concordância de classificação:** `{planning_section['status_agreement']}`",
            "",
            f"| Métrica | `{left_name}` | `{right_name}` |",
            "|---|---|---|",
            f"| Status | `{lp['status']}` | `{rp['status']}` |",
            f"| Escala validada | `{lp['validation_ok']}` | `{rp['validation_ok']}` |",
            f"| `Lmax` lógico | `{lp['logical_lmax']}` | `{rp['logical_lmax']}` |",
            f"| Limite inferior (`lower_bound`) | `{lp['lower_bound']}` | `{rp['lower_bound']}` |",
            f"| Pré-processamento | {_ns_to_ms(lp['preprocessing_ns'])} | {_ns_to_ms(rp['preprocessing_ns'])} |",
            f"| Construção do modelo | {_ns_to_ms(lp['model_build_ns'])} | {_ns_to_ms(rp['model_build_ns'])} |",
            f"| Busca / Consulta | {_ns_to_ms(lp['search_ns'])} | {_ns_to_ms(rp['search_ns'])} |",
            f"| **Tempo total de planejamento** | **{_ns_to_ms(lp['total_planning_ns'])}** | **{_ns_to_ms(rp['total_planning_ns'])}** |",
            f"| Nós gerados / expandidos | `{lp['nodes_generated']} / {lp['nodes_expanded']}` | `{rp['nodes_generated']} / {rp['nodes_expanded']}` |",
            "",
        ]

    if logical_section:
        ll = logical_section["left"] or {}
        rl = logical_section["right"] or {}
        md_lines += [
            "## 2. Execução Lógica (Validação Funcional)",
            "",
            f"- **Mesma entrada CSV (hash):** `{logical_section['same_input_hash']}`",
            f"- **Estado final de P1/P2 equivalente (tolerância `1e-9`):** `{logical_section['final_shared_state_equal']}`",
            f"- **Consistência da cópia P3 (`{left_name}`):** `{logical_section['left_recorded_copy_consistent']}` ({logical_section['left_recorded_copy_note']})",
            f"- **Consistência da cópia P3 (`{right_name}`):** `{logical_section['right_recorded_copy_consistent']}` ({logical_section['right_recorded_copy_note']})",
            "",
            f"| Métrica | `{left_name}` | `{right_name}` |",
            "|---|---|---|",
            f"| Status execução | `{ll.get('status')}` | `{rl.get('status')}` |",
            f"| Unidades executadas | `{ll.get('units_executed')}` | `{rl.get('units_executed')}` |",
            f"| Versão registrada por P3 | `{ll.get('recorded_version')}` | `{rl.get('recorded_version')}` |",
            f"| Tempo total (wall) | {_ns_to_ms(ll.get('total_wall_ns'))} | {_ns_to_ms(rl.get('total_wall_ns'))} |",
            "",
        ]

    if timed_section:
        lt = timed_section["left"] or {}
        rt = timed_section["right"] or {}
        md_lines += [
            "## 3. Execução Temporizada (Desempenho Observado)",
            "",
            f"- **Mesmo `quantum_ns` calibrado:** `{timed_section['same_quantum_ns']}`",
            f"- **Estado final de P1/P2 equivalente:** `{timed_section['final_shared_state_equal']}`",
            f"- **Consistência da cópia P3 (`{left_name}`):** `{timed_section['left_recorded_copy_consistent']}` ({timed_section['left_recorded_copy_note']})",
            f"- **Consistência da cópia P3 (`{right_name}`):** `{timed_section['right_recorded_copy_consistent']}` ({timed_section['right_recorded_copy_note']})",
            "",
            f"| Métrica | `{left_name}` | `{right_name}` |",
            "|---|---|---|",
            f"| Status execução | `{lt.get('status')}` | `{rt.get('status')}` |",
            f"| Quantum físico (`q`) | {_ns_to_ms(lt.get('quantum_ns'))} | {_ns_to_ms(rt.get('quantum_ns'))} |",
            f"| Deadlines físicos atendidos | `{lt.get('all_physical_deadlines_met')}` | `{rt.get('all_physical_deadlines_met')}` |",
            f"| Maior atraso de despacho | {_ns_to_ms(lt.get('max_dispatch_lateness_ns'))} | {_ns_to_ms(rt.get('max_dispatch_lateness_ns'))} |",
            f"| Maior duração de unidade | {_ns_to_ms(lt.get('max_work_elapsed_ns'))} | {_ns_to_ms(rt.get('max_work_elapsed_ns'))} |",
            f"| Maior excesso de slot | {_ns_to_ms(lt.get('max_slot_overrun_ns'))} | {_ns_to_ms(rt.get('max_slot_overrun_ns'))} |",
            f"| Tempo total (wall) | {_ns_to_ms(lt.get('total_wall_ns'))} | {_ns_to_ms(rt.get('total_wall_ns'))} |",
            f"| Versão registrada por P3 | `{lt.get('recorded_version')}` | `{rt.get('recorded_version')}` |",
            "",
        ]

    (out / "comparison.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return comparison
