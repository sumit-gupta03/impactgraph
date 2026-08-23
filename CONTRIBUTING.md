# Contributing to impactgraph

impactgraph is the thin pull-request layer on top of [datagraph](https://github.com/sumit-gupta03/datagraph).
Rule of thumb for where a change belongs:

- **Extractors, graph algorithms, lineage, relationships, profiling, knowledge base, MCP** → datagraph.
- **The `check`/`pr` commands, Markdown PR comment, GitHub Action, risk gating, CI ergonomics** → here.

## Setup

```bash
pip install "datagraph[sql,yaml] @ git+https://github.com/sumit-gupta03/datagraph@main"   # or: pip install datagraph
pip install -e ".[dev]"
pytest
```

## Pull requests

- Keep it deterministic: nothing here may invent nodes or edges; the LLM (if used) only explains.
- Add a test in `tests/` (they create a tiny git repo in `tmp_path` and run the CLI end-to-end).
- Run `pytest` on Python 3.9+ (CI covers Ubuntu + Windows).
