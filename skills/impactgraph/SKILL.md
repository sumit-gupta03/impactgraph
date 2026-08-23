---
name: impactgraph
description: Pre-merge change-impact check for code and data. Use before merging, before editing a shared function / dbt model / table, or when asked "what breaks if I change this?", "is this PR safe?", "what depends on X?", "blast radius", "who do I notify?", "what should I test?". Runs impactgraph on the current git diff (or a named node) and returns affected code, dbt models, tables, columns, dashboards, with a risk level, owners and a test plan.
---

# impactgraph — is this change safe?

impactgraph is the pull-request face of datagraph: a deterministic graph (Python/JS AST, dbt manifest,
SQL, Airflow, Lambda, warehouse metadata, OpenLineage/DataHub lineage) plus the git diff → blast radius,
risk, owners, test plan. The graph is never built by an LLM; you explain the output — do not invent nodes.

## Steps
1. Run the check on the working tree (uncommitted changes) or against the base branch:
   ```bash
   impactgraph check --repo . --base origin/main --dbt-manifest target/manifest.json --format json
   ```
   Add whatever the repo has: `--sql sql/`, `--airflow dags/`, `--lambda template.yaml`, `--js web/`,
   `--warehouse prod.db`, `--openlineage events.json`, `--lineage-file lineage.yml`.
   Use `--save-graph impactgraph.json --update` to cache the graph between runs, `--graph FILE` to reuse it.
2. Other questions (passed straight to datagraph):
   - **What breaks if X changes?** `impactgraph impact dbt:customer --graph impactgraph.json --json`
   - **Where does X come from?** `impactgraph lineage table:prod.analytics.dim_customer --graph impactgraph.json --json`
   - **Tell me about X before I edit it:** `impactgraph context X --graph impactgraph.json`
   - **Most dangerous nodes:** `impactgraph hotspots --graph impactgraph.json --json`
   - `--no-inferred` keeps only artifact-backed edges.
3. Read the JSON: `risk.level`, `affected_by_type`, `owners`, `recommended_tests`, `trees`
   (`via` = edge type, `provenance` = extracted | inferred | llm).
4. Report: what changed, what can break and why (walk the tree), whether the risk level looks right,
   who to notify, which tests to run before/after deploy. Mark `inferred`/`llm` edges as heuristics.

## Notes
- `impactgraph pr` prints the same result as Markdown (what the GitHub Action posts). `--fail-on HIGH` exits 1 at/above that level.
- Node ids: `file:path`, `func:path::name`, `dbt:model`, `source:src.name`, `table:db.schema.name`,
  `column:parent.col`, `exposure:name`, `dag:id`, `task:dag/task`, `lambda:name`, `api:METHOD /path`.
- For the full data side (relationships, profiling, wiki, MCP) use the engine directly: https://github.com/sumit-gupta03/datagraph
