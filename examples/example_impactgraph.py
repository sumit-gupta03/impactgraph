"""
=====================================================================================
 impactgraph - complete capability tour  (run me:  python example_impactgraph.py)
=====================================================================================

impactgraph answers ONE question - "what breaks if I merge this?" - by mapping a git
diff onto the deterministic graph built by datagraph (code + dbt + SQL + warehouse).

This script creates a small demo git repository (Python ETL + dbt project + SQL),
makes a change in it, and then shows every capability:

   1  check()  - the one call that does everything
   2  Anatomy of the result (risk, affected, owners, tests, trees, provenance)
   3  Markdown - exactly what the GitHub Action posts on a pull request
   4  JSON - for CI, dashboards, Slack bots
   5  HTML - the interactive blast-radius view
   6  --fail-on - gate the build on a risk level
   7  A real pull request: base...head between two branches
   8  Reuse a saved graph (fast repeated checks) and --update
   9  A docs-only change - correctly reports "no impact"
  10  Everything else passes through to datagraph (impact / lineage / context / nodes)
  11  CLI cheat sheet + the GitHub Action
  12  A ready-to-copy CI gate

Requirements
------------
    pip install "impactgraph[sql]"        # pulls in datagraph-core; sqlglot for SQL lineage
    git must be on PATH

Outputs are written to ./impactgraph_demo_out/
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "impactgraph_demo_out"
REPO = OUT / "demo_repo"


def banner(number: int, title: str) -> None:
    print("\n" + "=" * 86)
    print(f" {number}. {title}")
    print("=" * 86)


def git(*args: str, cwd: Path = None) -> str:
    """Run git with a fixed identity so the demo never touches your global config."""
    result = subprocess.run(
        ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com", *args],
        cwd=str(cwd or REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout.strip()


# --------------------------------------------------------------------------- demo repo

ETL_ORIGINAL = '''"""Customer ETL."""


def load_customers(conn):
    """Reads the customer dimension and writes the sales fact."""
    rows = conn.execute("SELECT customer_id, name, country FROM dim_customer").fetchall()
    conn.execute("INSERT INTO fact_sales (customer_id, amount) VALUES (?, ?)", rows)
    return rows


def load_products(conn):
    """Unrelated function - must NOT show up in the blast radius."""
    return conn.execute("SELECT product_id FROM dim_product").fetchall()


def refresh_marts(conn):
    """Calls load_customers, so it is affected when load_customers changes."""
    return load_customers(conn)
'''

DBT_MANIFEST = {
    "metadata": {"project_name": "demo"},
    "nodes": {
        "model.demo.dim_customer": {
            "resource_type": "model", "name": "dim_customer", "original_file_path": "models/dim_customer.sql",
            "database": "prod", "schema": "analytics", "config": {"materialized": "table"},
            "depends_on": {"nodes": []}, "columns": {"customer_id": {"data_type": "NUMBER"}},
            "compiled_code": "select customer_id, country from raw.customers",
            "meta": {"owner": "data-platform"},
        },
        "model.demo.fact_booking": {
            "resource_type": "model", "name": "fact_booking", "original_file_path": "models/fact_booking.sql",
            "database": "prod", "schema": "analytics", "config": {"materialized": "table"},
            "depends_on": {"nodes": ["model.demo.dim_customer"]},
            "columns": {"customer_id": {"data_type": "NUMBER"}, "amount": {"data_type": "NUMBER"}},
            "compiled_code": "select customer_id, sum(amount) amount from analytics.dim_customer group by 1",
            "meta": {"owner": "finance"},
        },
    },
    "sources": {},
    "exposures": {
        "exposure.demo.revenue_report": {
            "name": "revenue_report", "type": "dashboard", "owner": {"name": "finance"},
            "depends_on": {"nodes": ["model.demo.fact_booking"]},
        },
        "exposure.demo.customer_dashboard": {
            "name": "customer_dashboard", "type": "dashboard", "owner": {"name": "growth"},
            "depends_on": {"nodes": ["model.demo.fact_booking"]},
        },
    },
}


def build_demo_repo() -> None:
    """A tiny repo: Python ETL that writes fact_sales, a dbt project, a SQL view, docs."""
    if REPO.exists():
        shutil.rmtree(REPO, ignore_errors=True)
    (REPO / "etl").mkdir(parents=True)
    (REPO / "models").mkdir()
    (REPO / "sql").mkdir()
    (REPO / "target").mkdir()
    (REPO / "docs").mkdir()

    (REPO / "etl" / "__init__.py").write_text("", encoding="utf-8")
    (REPO / "etl" / "load_customers.py").write_text(ETL_ORIGINAL, encoding="utf-8")
    (REPO / "models" / "dim_customer.sql").write_text("select customer_id, country from raw.customers\n", encoding="utf-8")
    (REPO / "models" / "fact_booking.sql").write_text(
        "select customer_id, sum(amount) amount from analytics.dim_customer group by 1\n", encoding="utf-8")
    (REPO / "sql" / "customer_summary.sql").write_text(
        "CREATE VIEW customer_summary AS\n"
        "SELECT country, COUNT(*) AS customers FROM dim_customer GROUP BY country;\n", encoding="utf-8")
    (REPO / "target" / "manifest.json").write_text(json.dumps(DBT_MANIFEST, indent=2), encoding="utf-8")
    (REPO / "docs" / "readme.md").write_text("# Demo\n", encoding="utf-8")

    git("init", "-q", "-b", "main")
    git("add", ".")
    git("commit", "-q", "-m", "initial commit")


OUT.mkdir(exist_ok=True)
print(__doc__.split("Requirements")[0])
build_demo_repo()
print(f"demo repo    : {REPO}")
print(f"output folder: {OUT}")

# The change we are about to review: load_customers() now also writes to a second table.
(REPO / "etl" / "load_customers.py").write_text(
    ETL_ORIGINAL.replace(
        '    conn.execute("INSERT INTO fact_sales (customer_id, amount) VALUES (?, ?)", rows)',
        '    conn.execute("INSERT INTO fact_sales (customer_id, amount) VALUES (?, ?)", rows)\n'
        '    conn.execute("INSERT INTO fact_booking (customer_id) VALUES (?)", rows)',
    ),
    encoding="utf-8",
)
print("uncommitted change: load_customers() now also writes fact_booking")


# =============================================================================== 1
banner(1, "check() - the one call that does everything")

from impactgraph import check, to_markdown                                     # noqa: E402
from impactgraph.core import safe_console_text   # keeps legacy Windows consoles happy

INPUTS = {                       # anything datagraph can read; all optional
    "dbt_manifest": str(REPO / "target" / "manifest.json"),
    "sql": str(REPO / "sql"),
    # "dbt_catalog": ..., "warehouse": "postgresql+psycopg2://...", "airflow": "dags/",
    # "lambda_": "serverless.yml", "js": "web/", "openlineage": "events.ndjson",
}

result = check(
    repo=str(REPO),          # the git repository
    base="HEAD",             # HEAD = my uncommitted changes; use "origin/main" for a PR
    inputs=INPUTS,           # what to build the graph from
    save_graph=str(OUT / "impactgraph.json"),   # keep the graph for later runs
)

print(f"changed files : {result.changed_files}")
print(f"changed nodes : {result.changed_ids}")
print(f"risk          : {result.level} (score {result.score})")
print(f"affected      : {len(result.analysis.affected)} node(s)")
print("\nequivalent CLI: impactgraph check --repo . --dbt-manifest target/manifest.json --sql sql")


# =============================================================================== 2
banner(2, "Anatomy of the result")

analysis = result.analysis
print("by type      :", analysis.summary_by_type())
print("owners       :", analysis.owners, " <- who to notify, from dbt/DataHub metadata")
print("\nrecommended tests:")
for test in analysis.recommended_tests:
    print(f"    - {test}")

print("\nthe blast radius as a tree (via = edge type, provenance = extracted|inferred|llm):")


def print_tree(entry, depth=0):
    via = f"  via {entry['via']}" if entry.get("via") else ""
    prov = entry.get("provenance", "extracted")
    tag = f"  [{prov}]" if prov != "extracted" else ""
    print(f"    {'  ' * depth}{entry['name']} ({entry['type']}){via}{tag}")
    for child in entry.get("children", []):
        print_tree(child, depth + 1)


for tree in analysis.trees:
    print_tree(tree)

print("\nnotice: load_products() was NOT touched, so nothing downstream of it is listed -")
print("impactgraph maps changed LINE RANGES to the exact functions, not whole files.")
print("\nresult.to_dict() keys:", sorted(result.to_dict().keys()))


# =============================================================================== 3
banner(3, "Markdown - what the GitHub Action posts on the pull request")

markdown = to_markdown(result, title="impactgraph - change impact")
(OUT / "pr-comment.md").write_text(markdown, encoding="utf-8")   # UTF-8 on disk: GitHub shows the emoji
print(safe_console_text(markdown))                               # downgraded if the console cannot encode them
print(f"(written to {OUT / 'pr-comment.md'})")


# =============================================================================== 4
banner(4, "JSON - for CI, dashboards and bots")

payload = result.to_dict()
(OUT / "impact.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
print(json.dumps({
    "risk": payload["risk"],
    "changed_files": payload["changed_files"],
    "affected_by_type": payload["affected_by_type"],
    "owners": payload["owners"],
    "recommended_tests": payload["recommended_tests"][:3],
}, indent=2))
print(f"(full JSON written to {OUT / 'impact.json'})")
print("CLI: impactgraph check --format json -o impact.json")


# =============================================================================== 5
banner(5, "HTML - the interactive blast-radius view")

from datagraph.html_report import render_html                                  # noqa: E402

(OUT / "impact.html").write_text(
    render_html(result.graph, result.analysis, title="What this change can break"), encoding="utf-8")
print(f"written: {OUT / 'impact.html'}  (open it in a browser - click nodes to explore)")
print("CLI: impactgraph check --html impact.html")


# =============================================================================== 6
banner(6, "--fail-on - gate the build on a risk level")

for threshold in ["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]:
    verdict = "FAIL (exit 1)" if result.breaches(threshold) else "pass (exit 0)"
    print(f"    --fail-on {threshold:<9} risk is {result.level:<8} -> {verdict}")
print("\nTypical policy: --fail-on CRITICAL in CI, and review HIGH manually.")


# =============================================================================== 7
banner(7, "A real pull request: base...head between two branches")

git("add", "-A")
git("commit", "-q", "-m", "feat: also load fact_booking")
git("checkout", "-q", "-b", "feature/pricing")
(REPO / "models" / "fact_booking.sql").write_text(
    "select customer_id, sum(amount * 1.2) amount from analytics.dim_customer group by 1\n", encoding="utf-8")
git("add", "-A")
git("commit", "-q", "-m", "feat: apply 20% uplift in fact_booking")

pr = check(repo=str(REPO), base="main", head="feature/pricing", inputs=INPUTS,
           graph_path=str(OUT / "impactgraph.json"))
print(f"PR feature/pricing vs main")
print(f"    changed files : {pr.changed_files}")
print(f"    changed nodes : {pr.changed_ids}")
print(f"    risk          : {pr.level} (score {pr.score})")
print(f"    affected      : {sorted(k for k in pr.analysis.affected if not k.startswith('column:'))}")
print(f"    notify        : {pr.analysis.owners}")
print("\nThis is exactly what runs in the GitHub Action:")
print("    impactgraph check --repo . --base origin/main --format markdown --fail-on CRITICAL")


# =============================================================================== 8
banner(8, "Reuse a saved graph - fast repeated checks")

import time                                                                     # noqa: E402

start = time.perf_counter()
check(repo=str(REPO), base="main", head="feature/pricing", inputs=INPUTS)              # rebuilds the graph
rebuild_s = time.perf_counter() - start

start = time.perf_counter()
check(repo=str(REPO), base="main", head="feature/pricing", graph_path=str(OUT / "impactgraph.json"))
reuse_s = time.perf_counter() - start

print(f"    building the graph every time : {rebuild_s:.2f}s")
print(f"    reusing impactgraph.json      : {reuse_s:.2f}s")
print("\nIn CI: build once with --save-graph, then run checks with --graph.")
print("`--update` skips the rebuild entirely while the inputs are unchanged:")
print("    impactgraph check --save-graph impactgraph.json --update ...")


# =============================================================================== 9
banner(9, "A docs-only change - correctly reports 'no impact'")

(REPO / "docs" / "readme.md").write_text("# Demo\n\nSome new documentation.\n", encoding="utf-8")
docs = check(repo=str(REPO), base="HEAD", graph_path=str(OUT / "impactgraph.json"))
print(f"    changed files : {docs.changed_files}")
print(f"    risk          : {docs.level}")
print(f"    notes         : {docs.notes}")
print(f"    breaches HIGH?: {docs.breaches('HIGH')}")
print("\nMarkdown for such a PR:")
print(safe_console_text(to_markdown(docs)))


# =============================================================================== 10
banner(10, "Everything else passes through to datagraph")

from impactgraph.cli import main as impactgraph_cli                              # noqa: E402

graph_arg = ["--graph", str(OUT / "impactgraph.json")]
print("$ impactgraph impact dbt:dim_customer")
impactgraph_cli(["impact", "dbt:dim_customer", *graph_arg])

print("\n$ impactgraph lineage fact_booking --json   (truncated)")
impactgraph_cli(["nodes", "--search", "fact_booking", *graph_arg])

print("\n$ impactgraph context dbt:fact_booking   (first lines)")
from datagraph.knowledge import context                                          # noqa: E402
from datagraph import ImpactGraph                                                # noqa: E402

saved = ImpactGraph.load(OUT / "impactgraph.json")
print("    " + "\n    ".join(context(saved, "dbt:fact_booking").splitlines()[:10]))

print("\n$ impactgraph hotspots")
impactgraph_cli(["hotspots", "--top", "5", *graph_arg])

print("\nThe whole datagraph API is re-exported too:")
print("    from impactgraph import ImpactGraph, analyze_impact, DbtExtractor, star_schema, ...")


# =============================================================================== 11
banner(11, "CLI and the GitHub Action")

print("""
  # what breaks if I merge my current work?
  impactgraph check --repo . --dbt-manifest target/manifest.json

  # a pull request, as a Markdown comment, failing the job at HIGH or above
  impactgraph check --repo . --base origin/main --format markdown --fail-on HIGH

  # machine readable + keep the graph for later questions
  impactgraph check --repo . --base origin/main --format json --save-graph impactgraph.json
  impactgraph pr --repo . --base origin/main -o comment.md      # same as --format markdown

  # options
  --code DIR          code root when it is not the repo root
  --graph FILE        reuse a graph instead of building one
  --update            skip the rebuild while inputs are unchanged
  --max-depth N       stop the walk after N hops
  --no-inferred       artifact-backed edges only (drop heuristics)
  --html FILE         also write the interactive view
  --warehouse DSN --airflow DIR --lambda FILE --js DIR --openlineage FILE --datahub URL

  # anything else goes straight to datagraph
  impactgraph impact dbt:customer --json
  impactgraph lineage table:prod.analytics.dim_customer --html lineage.html
  impactgraph context dim_customer
  impactgraph model --markdown MODEL.md
  impactgraph mcp --graph impactgraph.json

  (on Windows, if the launcher is blocked:  python -m impactgraph.cli ...)

  # .github/workflows/impact.yml
  name: change impact
  on: pull_request
  permissions: { contents: read, pull-requests: write }
  jobs:
    impact:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
          with: { fetch-depth: 0 }
        - uses: actions/setup-python@v5
          with: { python-version: "3.12" }
        - uses: sumit-gupta03/impactgraph@main
          with:
            repo-path: src
            dbt-manifest: target/manifest.json
            fail-on: CRITICAL          # LOW | MEDIUM | HIGH | CRITICAL | NONE
""")


# =============================================================================== 12
banner(12, "A ready-to-copy CI gate")

print('''
    # ci_gate.py - run this in any CI system
    import sys
    from impactgraph import check, to_markdown

    result = check(".", base="origin/main", inputs={"dbt_manifest": "target/manifest.json"})

    with open("comment.md", "w", encoding="utf-8") as fh:
        fh.write(to_markdown(result))

    print(f"risk={result.level} score={result.score} affected={len(result.analysis.affected)}")
    for owner, assets in result.analysis.owners.items():
        print(f"notify {owner}: {', '.join(assets)}")

    sys.exit(1 if result.breaches("CRITICAL") else 0)
''')

print("=" * 86)
print(f" Done. Results in: {OUT}")
print("   pr-comment.md   - the PR comment")
print("   impact.json     - machine-readable result")
print("   impact.html     - interactive blast radius (open in a browser)")
print("   impactgraph.json- the graph, reusable by datagraph too")
print("=" * 86)
