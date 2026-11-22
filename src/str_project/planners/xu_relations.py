"""Relation consistency checking and adjusted release times for Xu & Parnas (1990)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from ..model import SchedulingInstance


@dataclass(frozen=True)
class RelationCheckResult:
    consistent: bool
    reason: str | None
    pc_closure: frozenset[tuple[str, str]]


def transitive_closure_pc(
    pc: set[tuple[str, str]] | frozenset[tuple[str, str]],
) -> frozenset[tuple[str, str]]:
    """Compute the transitive closure of PRECEDE (PC).

    Note: PM (PREEMPTS) must NEVER be transitively closed.
    """
    adj: dict[str, set[str]] = {}
    for u, v in pc:
        adj.setdefault(u, set()).add(v)
        adj.setdefault(v, set())

    closure: set[tuple[str, str]] = set()
    for start in adj:
        visited: set[str] = set()
        queue: deque[str] = deque(adj[start])
        while queue:
            cur = queue.popleft()
            if cur in visited:
                continue
            visited.add(cur)
            closure.add((start, cur))
            for nxt in adj.get(cur, ()):
                if nxt not in visited:
                    queue.append(nxt)
    return frozenset(closure)


def check_relations(
    pc: set[tuple[str, str]] | frozenset[tuple[str, str]],
    ex: set[tuple[str, str]] | frozenset[tuple[str, str]],
    pm: set[tuple[str, str]] | frozenset[tuple[str, str]],
) -> RelationCheckResult:
    """Verify consistency of (PC, EX, PM) per Xu & Parnas (1990), Section III, p. 363.

    Inconsistent pairs (applied symmetrically for (i, j) and (j, i)):
    - PC(i, j) and PC(j, i) (equivalently any cycle in PC, including self-loop PC(i, i))
    - PC(i, j) and PM(j, i)
    - EX(i, j) and PM(j, i)
    - PM(i, j) and PM(j, i) (including self-loop PM(i, i))
    """
    pc_closure = transitive_closure_pc(pc)

    for i, j in pc_closure:
        if i == j:
            return RelationCheckResult(
                consistent=False,
                reason=f"cyclic_precedence_involving:{i}",
                pc_closure=pc_closure,
            )
        if (j, i) in pc_closure:
            return RelationCheckResult(
                consistent=False,
                reason=f"pc_cycle:{i}<->{j}",
                pc_closure=pc_closure,
            )

    for i, j in pm:
        if i == j:
            return RelationCheckResult(
                consistent=False,
                reason=f"self_preempts:{i}",
                pc_closure=pc_closure,
            )
        if (j, i) in pm:
            return RelationCheckResult(
                consistent=False,
                reason=f"pm_conflict:{i}<->{j}",
                pc_closure=pc_closure,
            )
        if (j, i) in pc_closure:
            return RelationCheckResult(
                consistent=False,
                reason=f"pc_pm_conflict:PC({j},{i})_and_PM({i},{j})",
                pc_closure=pc_closure,
            )
        if (j, i) in ex:
            return RelationCheckResult(
                consistent=False,
                reason=f"ex_pm_conflict:EX({j},{i})_and_PM({i},{j})",
                pc_closure=pc_closure,
            )

    return RelationCheckResult(consistent=True, reason=None, pc_closure=pc_closure)


def adjusted_releases(
    instance: SchedulingInstance,
    pc: set[tuple[str, str]] | frozenset[tuple[str, str]],
) -> dict[str, int]:
    """Compute adjusted release times r'[i] in topological order of PC.

    r'[i] = r[i]                                      if i has no PC predecessor
    r'[i] = max(r[i], max(r'[j] + c[j] : PC(j, i)))   otherwise
    """
    seg_map = instance.segment_map()
    seg_ids = [s.id for s in instance.segments]
    preds: dict[str, set[str]] = {sid: set() for sid in seg_ids}
    succs: dict[str, set[str]] = {sid: set() for sid in seg_ids}
    for u, v in pc:
        if u in seg_map and v in seg_map:
            preds[v].add(u)
            succs[u].add(v)

    in_degree = {sid: len(preds[sid]) for sid in seg_ids}
    queue: deque[str] = deque(sorted(sid for sid, deg in in_degree.items() if deg == 0))
    topo_order: list[str] = []

    while queue:
        u = queue.popleft()
        topo_order.append(u)
        for v in sorted(succs[u]):
            in_degree[v] -= 1
            if in_degree[v] == 0:
                queue.append(v)

    if len(topo_order) != len(seg_ids):
        raise ValueError("Cannot compute adjusted_releases: PC contains a cycle.")

    r_adj: dict[str, int] = {}
    for sid in topo_order:
        base_r = seg_map[sid].release
        if not preds[sid]:
            r_adj[sid] = base_r
        else:
            r_adj[sid] = max(
                base_r,
                max(r_adj[p] + seg_map[p].execution_units for p in preds[sid]),
            )
    return r_adj
