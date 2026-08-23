"""The one thing impactgraph does: diff -> graph -> blast radius -> verdict."""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from datagraph import ImpactAnalysis, ImpactGraph, analyze_impact, changed_node_ids, collect_changes

LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

# impactgraph check flag  ->  datagraph build flag
BUILD_FLAGS: Dict[str, str] = {
    "dbt_manifest": "--dbt-manifest",
    "dbt_catalog": "--dbt-catalog",
    "sql": "--sql",
    "openlineage": "--openlineage",
    "lineage_file": "--lineage-file",
    "airflow": "--airflow",
    "lambda_": "--lambda",
    "js": "--js",
    "warehouse": "--warehouse",
    "datahub": "--datahub",
}


@dataclass
class CheckResult:
    graph: ImpactGraph
    changed_files: List[str]
    changed_ids: List[str]
    analysis: Optional[ImpactAnalysis]
    graph_path: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    @property
    def level(self) -> str:
        return self.analysis.risk["level"] if self.analysis else "LOW"

    @property
    def score(self) -> float:
        return float(self.analysis.risk["score"]) if self.analysis else 0.0

    def breaches(self, fail_on: Optional[str]) -> bool:
        if not fail_on or fail_on.upper() == "NONE" or self.analysis is None:
            return False
        return LEVELS.index(self.level) >= LEVELS.index(fail_on.upper())

    def to_dict(self) -> Dict:
        d = {
            "changed_files": self.changed_files,
            "changed": self.changed_ids,
            "risk": {"level": self.level, "score": self.score},
            "notes": self.notes,
        }
        if self.analysis is not None:
            d.update(self.analysis.to_dict())
        else:
            d.update({"affected": {}, "affected_by_type": {}, "owners": {}, "recommended_tests": [], "trees": []})
        return d


def build_graph(code: str, inputs: Dict[str, Optional[str]], output: Optional[str] = None,
                update: bool = False, quiet: bool = True) -> ImpactGraph:
    """Build a datagraph graph from ``code`` plus any data inputs, via datagraph's own CLI
    (so every extractor/flag datagraph supports works here unchanged)."""
    from datagraph.cli import main as dg_main

    out = output or os.path.join(tempfile.gettempdir(), f"impactgraph-{os.getpid()}.json")
    argv = ["build", "--repo", code, "-o", out]
    for key, flag in BUILD_FLAGS.items():
        if inputs.get(key):
            argv += [flag, str(inputs[key])]
    if update:
        argv.append("--update")
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink if quiet else sys.stdout):
        rc = dg_main(argv)
    if rc != 0:
        raise RuntimeError(f"datagraph build failed (exit {rc}):\n{sink.getvalue()}")
    return ImpactGraph.load(out)


def check(repo: str = ".", base: str = "HEAD", head: Optional[str] = None, *, code: Optional[str] = None,
          graph: Optional[ImpactGraph] = None, graph_path: Optional[str] = None, inputs: Optional[Dict[str, str]] = None,
          save_graph: Optional[str] = None, update: bool = False, max_depth: Optional[int] = None,
          include_inferred: bool = True, quiet: bool = True) -> CheckResult:
    """Diff ``repo`` (base[...head]) against a graph and compute the blast radius.

    Graph source, in order: ``graph`` object, ``graph_path`` file, otherwise build from
    ``code`` (defaults to ``repo``) + ``inputs`` (dbt_manifest, sql, warehouse, ...).
    """
    notes: List[str] = []
    if graph is None:
        if graph_path:
            graph = ImpactGraph.load(graph_path)
        else:
            graph = build_graph(code or repo, inputs or {}, output=save_graph, update=update, quiet=quiet)
            graph_path = save_graph
    changes = collect_changes(repo, base=base, head=head)
    files = list(changes.files)
    if not files:
        notes.append("no changes detected")
        return CheckResult(graph, files, [], None, graph_path, notes)
    ids = changed_node_ids(graph, changes)
    if not ids:
        notes.append("changed files do not map to any graph node (docs/config only?)")
        return CheckResult(graph, files, [], None, graph_path, notes)
    analysis = analyze_impact(graph, ids, max_depth=max_depth, include_inferred=include_inferred)
    return CheckResult(graph, files, ids, analysis, graph_path, notes)


# ------------------------------------------------------------------ markdown


def _tree_md(entry: Dict, depth: int, lines: List[str], limit: int = 200) -> None:
    if len(lines) >= limit:
        return
    via = f" via {entry['via']}" if entry.get("via") else ""
    prov = entry.get("provenance", "extracted")
    tag = f" _({prov})_" if prov != "extracted" else ""
    lines.append(f"{'  ' * depth}- `{entry.get('name', entry.get('id'))}` ({entry.get('type', '?')}){via}{tag}")
    for child in entry.get("children", []):
        _tree_md(child, depth + 1, lines, limit)


def to_markdown(result: CheckResult, title: str = "impactgraph — change impact") -> str:
    a = result.analysis
    if a is None:
        why = "; ".join(result.notes) or "nothing affected"
        files = ", ".join(f"`{f}`" for f in result.changed_files[:15]) or "—"
        return f"### ✅ {title}: no impact\n\n{why}. Changed files: {files}\n"
    icon = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}.get(a.risk["level"], "⚠")
    out = [f"### {icon} {title}: risk **{a.risk['level']}** (score {a.risk['score']})", ""]
    files = ", ".join(f"`{f}`" for f in result.changed_files[:15])
    out.append(f"**Changed:** {len(result.changed_ids)} node(s) in {len(result.changed_files)} file(s) — {files}")
    by_type = a.summary_by_type()
    summary = " · ".join(f"{v} {k}" for k, v in sorted(by_type.items(), key=lambda kv: -kv[1]))
    out.append(f"**Affected:** {len(a.affected)}" + (f" — {summary}" if summary else ""))
    if a.owners:
        out.append("**Notify:** " + " · ".join(f"{o} ({', '.join(n[:4])})" for o, n in a.owners.items()))
    out.append("")
    tree_lines: List[str] = []
    for t in a.trees:
        _tree_md(t, 0, tree_lines)
    if tree_lines:
        out += ["<details><summary>Blast radius</summary>", ""] + tree_lines + ["", "</details>", ""]
    if a.recommended_tests:
        out.append("**Recommended tests**")
        out += [f"- [ ] {t}" for t in a.recommended_tests]
        out.append("")
    if a.include_inferred:
        out.append("_Includes heuristic edges (inferred / llm); rerun with `--no-inferred` for artifact-backed edges only._")
    return "\n".join(out) + "\n"
